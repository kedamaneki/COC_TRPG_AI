"""Read-only, session-agnostic full-session evidence auditor.

This module never writes below ``--core-run`` or beside the normalized input.
All generated artifacts are placed in the required ``--output-dir``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


AUDITOR_VERSION = "2.0.0"
SCHEMA_VERSION = "2.0"
LEGACY_AUDITOR_SHA256 = "24fe6187cf01f8b27340274c642712f0277ae9973917a787d979a6a72823499d"

OLD_CATEGORIES = {
    "SOURCE_CONTRADICTION",
    "SOURCE_GAMEPLAY_GAP",
    "SOURCE_LOGGING_GAP",
    "SOURCE_NARRATIVE_GAP",
    "NORMALIZATION_GAP",
    "ROLL_CONTRACT_INCOMPLETE",
    "COMBAT_WITHOUT_TERMINATION",
    "NORMALIZATION_SOURCE_CONTRADICTION",
    "LIFECYCLE_MISCLASSIFIED_AS_NO_ROLL",
}
ITERATION2_CATEGORIES = {
    "MANDATORY_SAN_EFFECT_DROPPED",
    "SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK",
    "OBJECT_STATE_INVALID_TRANSITION",
    "OBJECT_NARRATIVE_STATE_CONTRADICTION",
    "UNGROUNDED_NARRATIVE_OPTION",
}
ALL_CATEGORIES = OLD_CATEGORIES | ITERATION2_CATEGORIES

LIFECYCLE_TYPES = {
    "LOCATION_CHANGE", "MOVEMENT", "STATE_TRANSITION",
    "COMBAT_STARTED", "COMBAT_ENDING", "COMBAT_ENDED",
    "COMBAT_START", "COMBAT_END",
}


class AuditInputError(RuntimeError):
    """The supplied evidence cannot be audited safely."""


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(path: Path, parent: Path) -> bool:
    path, parent = path.resolve(), parent.resolve()
    return path == parent or parent in path.parents


def guard_output_path(core_run: Path, normalized: Path, output_dir: Path) -> None:
    output = output_dir.resolve()
    protected = [core_run.resolve(), normalized.resolve(), normalized.resolve().parent]
    if any(_inside(output, item) for item in protected):
        raise AuditInputError("RAW_RUN_PATH_GUARD: output-dir must be separate from all inputs")


def _valid_checkpoint(path: Path) -> bool:
    required = [path / "COMPLETE", path / "manifest.json", path / "state.json", path / "runtime_data"]
    if not all(item.exists() for item in required):
        return False
    try:
        manifest = read_json(path / "manifest.json")
    except (OSError, ValueError, TypeError):
        return False
    return bool(manifest.get("completed") or manifest.get("complete"))


def resolve_checkpoint(core_run: Path, explicit: str | None = None) -> Path:
    checkpoints = core_run / "checkpoints"
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_absolute():
            direct = checkpoints / explicit
            by_id = [
                p for p in checkpoints.glob("cycle_*")
                if (p / "manifest.json").is_file()
                and read_json(p / "manifest.json").get("checkpoint_id") == explicit
            ]
            candidate = direct if direct.exists() else (by_id[0] if by_id else direct)
        if not _valid_checkpoint(candidate):
            raise AuditInputError(f"INVALID_CHECKPOINT: {candidate}")
        return candidate.resolve()
    candidates = []
    for path in checkpoints.glob("cycle_*"):
        if not _valid_checkpoint(path):
            continue
        manifest = read_json(path / "manifest.json")
        candidates.append((int(manifest.get("cycle", -1)), str(manifest.get("created_at") or ""), path))
    if not candidates:
        raise AuditInputError("NO_VALID_CHECKPOINT")
    return max(candidates, key=lambda item: (item[0], item[1]))[2].resolve()


def _first_existing(root: Path, names: Iterable[str]) -> Path:
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    raise AuditInputError(f"required input missing below {root}: {', '.join(names)}")


def _event_id(event: dict[str, Any], prefix: str, index: int) -> str:
    return str(event.get("event_id") or (event.get("meta") or {}).get("event_id") or f"{prefix}:{index:06d}")


def _finding(
    finding_id: str,
    category: str,
    severity: str,
    message: str,
    *,
    source_event_ids: Iterable[str] = (),
    normalized_event_ids: Iterable[str] = (),
    adjudication_id: str | None = None,
    checkpoint: str | None = None,
    cycle: int | None = None,
    evidence: Any = None,
    evidence_state: str = "GAP",
    classification: str | None = None,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "category": category,
        "classification": classification or category,
        "severity": severity,
        "message": message,
        "source_event_ids": sorted({str(x) for x in source_event_ids if x}),
        "normalized_event_ids": sorted({str(x) for x in normalized_event_ids if x}),
        "adjudication_id": adjudication_id,
        "checkpoint": checkpoint,
        "cycle": cycle,
        "evidence_state": evidence_state,
        "evidence": evidence or {},
    }


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    return (event.get("metadata") or {}).get("source_payload") or {}


def _source_ids(event: dict[str, Any]) -> list[str]:
    return [str(x) for x in (event.get("source_event_ids") or []) if x]


def _adjudication(event: dict[str, Any]) -> str | None:
    return event.get("adjudication_id") or (event.get("meta") or {}).get("adjudication_id") or _payload(event).get("adjudication_id")


def _is_failure(value: Any) -> bool:
    return str(value or "").upper() in {"FAILURE", "FAIL", "MISS", "1"}


def _is_success(value: Any) -> bool:
    token = str(value or "").upper()
    return "SUCCESS" in token or token in {"HIT", "ACTOR_WINS", "2", "3", "4", "5"}


def audit_roll_contract(
    unified: list[dict[str, Any]], normalized: list[dict[str, Any]], checkpoint_id: str
) -> list[dict[str, Any]]:
    findings = []
    seen: set[tuple[str, str]] = set()
    records: list[tuple[str, dict[str, Any], str, list[str]]] = []
    for index, event in enumerate(unified):
        mode = str(event.get("resolution_mode") or "").upper()
        if mode in {"ROLL", "NO_ROLL"}:
            records.append((_event_id(event, "unified", index), event, mode, [_event_id(event, "unified", index)]))
    for event in normalized:
        dice = event.get("dice") or {}
        mode = str(dice.get("resolution_mode") or "").upper()
        if mode in {"ROLL", "NO_ROLL"}:
            records.append((str(event.get("event_id")), {**_payload(event), **dice, "modifier": event.get("modifier"), "adjudication_id": _adjudication(event), "actor": event.get("actor_id") or _payload(event).get("actor"), "target": (event.get("action") or {}).get("target") or _payload(event).get("target")}, mode, _source_ids(event)))
    for event_id, record, mode, source_ids in records:
        adjudication_id = record.get("adjudication_id")
        key = (str(adjudication_id or event_id), mode)
        if key in seen:
            continue
        seen.add(key)
        if mode == "ROLL":
            skill = record.get("skill_or_stat") or record.get("skill") or record.get("skill_name") or record.get("attack_skill") or record.get("kp_selected_skill")
            required = {
                "adjudication_id": adjudication_id,
                "actor": record.get("actor") or record.get("actor_id"),
                "target": record.get("target") or record.get("target_id"),
                "skill": skill,
                "target_value": record.get("target_value"),
                "roll": record.get("roll"),
                "raw_result": record.get("raw_result"),
                "final_result": record.get("final_result"),
            }
            missing = [name for name, value in required.items() if value in (None, "")]
            if "modifier" not in record:
                missing.append("modifier")
            opposed = record.get("opposed_roll") or record.get("opposed")
            if opposed:
                for side in ("actor", "opponent"):
                    part = opposed.get(side) or {}
                    for field in ("target_value", "roll", "result"):
                        if part.get(field) in (None, ""):
                            missing.append(f"opposed.{side}.{field}")
            if missing:
                findings.append(_finding(
                    f"roll_contract:{adjudication_id or event_id}", "ROLL_CONTRACT_INCOMPLETE", "CRITICAL",
                    "ROLL adjudication is missing required structured evidence.",
                    source_event_ids=source_ids or [event_id], adjudication_id=adjudication_id,
                    checkpoint=checkpoint_id, cycle=record.get("cycle"), evidence={"missing": sorted(set(missing)), "record": required},
                    classification="SOURCE_LOGGING_GAP",
                ))
        else:
            reason = record.get("resolution_reason") or record.get("reason_code") or record.get("reason")
            outcome = record.get("final_result") or record.get("automatic_result")
            missing = [name for name, value in {"adjudication_id": adjudication_id, "reason": reason, "final_result": outcome}.items() if value in (None, "")]
            if missing:
                findings.append(_finding(
                    f"no_roll_contract:{adjudication_id or event_id}", "ROLL_CONTRACT_INCOMPLETE", "MAJOR",
                    "NO_ROLL adjudication is missing its reason or final outcome.",
                    source_event_ids=source_ids or [event_id], adjudication_id=adjudication_id,
                    checkpoint=checkpoint_id, cycle=record.get("cycle"), evidence={"missing": missing},
                    classification="SOURCE_LOGGING_GAP",
                ))
    return findings


def audit_lifecycle_contract(
    unified: list[dict[str, Any]], normalized: list[dict[str, Any]], checkpoint_id: str
) -> list[dict[str, Any]]:
    """Reject lifecycle facts that masquerade as ROLL/NO_ROLL adjudications."""
    findings = []
    records = []
    for index, event in enumerate(unified):
        records.append((_event_id(event, "unified", index), event, [_event_id(event, "unified", index)]))
    for event in normalized:
        records.append((str(event.get("event_id")), event, _source_ids(event)))
    for event_id, event, source_ids in records:
        event_type = str(event.get("event_type") or "").upper()
        dice = event.get("dice") if isinstance(event.get("dice"), dict) else {}
        mode = str(event.get("resolution_mode") or dice.get("resolution_mode") or "").upper()
        if event_type not in LIFECYCLE_TYPES or mode not in {"ROLL", "NO_ROLL"}:
            continue
        findings.append(_finding(
            f"lifecycle_resolution:{event_id}", "LIFECYCLE_MISCLASSIFIED_AS_NO_ROLL", "MAJOR",
            "Lifecycle events must not carry ROLL/NO_ROLL adjudication fields.",
            source_event_ids=source_ids or [event_id], normalized_event_ids=[event_id],
            adjudication_id=_adjudication(event), checkpoint=checkpoint_id,
            evidence={"event_type": event_type, "resolution_mode": mode},
            classification="NORMALIZATION_GAP",
        ))
    return findings


def audit_luck(normalized: list[dict[str, Any]], checkpoint_id: str) -> list[dict[str, Any]]:
    findings = []
    for event in normalized:
        modifier, dice = event.get("modifier") or {}, event.get("dice") or {}
        if modifier.get("type") != "LUCK_SPEND":
            continue
        missing = [name for name, value in {
            "amount": modifier.get("amount"), "resource_before": modifier.get("resource_before"),
            "resource_after": modifier.get("resource_after"), "roll": dice.get("roll"),
            "target_value": dice.get("target_value"), "raw_result": dice.get("raw_result"),
            "final_result": dice.get("final_result"),
        }.items() if value is None]
        coherent = (
            not missing and _is_failure(dice.get("raw_result")) and _is_success(dice.get("final_result"))
            and modifier["resource_before"] - modifier["amount"] == modifier["resource_after"]
        )
        if not coherent:
            findings.append(_finding(
                f"luck_phase:{event.get('event_id')}", "NORMALIZATION_GAP", "MAJOR",
                "Luck raw/final phase is incomplete or internally inconsistent.",
                source_event_ids=_source_ids(event), normalized_event_ids=[event.get("event_id")],
                adjudication_id=_adjudication(event), checkpoint=checkpoint_id,
                evidence={"missing": missing, "dice": dice, "modifier": modifier},
            ))
    return findings


def _contains_mandatory_san(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in {"force_san_check", "mandatory_san", "mandatory_san_effect"} and item not in (None, False, ""):
                return True
            if lowered == "san_check" and isinstance(item, dict) and item.get("required") is True:
                return True
            if _contains_mandatory_san(item):
                return True
    elif isinstance(value, list):
        return any(_contains_mandatory_san(item) for item in value)
    return False


def audit_san(
    session: list[dict[str, Any]], unified: list[dict[str, Any]], normalized: list[dict[str, Any]], checkpoint_id: str
) -> list[dict[str, Any]]:
    findings = []
    raw_events = []
    for prefix, stream in (("session", session), ("unified", unified)):
        for index, event in enumerate(stream):
            body = event.get("meta") or event
            raw_events.append((_event_id(event, prefix, index), body))
    triggers = []
    san_by_adj: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    san_by_trigger: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for event_id, body in raw_events:
        event_type = str(body.get("event_type") or "").upper()
        if event_type in {"SAN_REQUIRED", "SAN_EFFECT_TRIGGERED", "MANDATORY_SAN_EFFECT"} or _contains_mandatory_san(body):
            triggers.append((event_id, body))
        explicit = event_type in {"SAN_CHECK", "SAN_ROLL", "SAN_RESULT", "SAN_CHECK_RESOLVED"} or str(body.get("roll_type") or "").lower() in {"san", "san_check"}
        if explicit:
            if body.get("adjudication_id"):
                san_by_adj[str(body["adjudication_id"])].append((event_id, body))
            if body.get("trigger_event_id"):
                san_by_trigger[str(body["trigger_event_id"])].append((event_id, body))
    normalized_san = []
    for event in normalized:
        san = event.get("san")
        if not san:
            continue
        normalized_san.append(event)
        payload = _payload(event)
        source_type = str(payload.get("event_type") or "").upper()
        kind = str((payload.get("san") or {}).get("kind") or payload.get("san_kind") or "").upper()
        complete = all(san.get(field) is not None for field in ("before", "target", "roll", "result", "loss", "after"))
        if kind == "SNAPSHOT" or (not complete and source_type not in {"SAN_CHECK", "SAN_ROLL", "SAN_RESULT", "SAN_CHECK_RESOLVED"}):
            findings.append(_finding(
                f"san_snapshot:{event.get('event_id')}", "SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK", "MAJOR",
                "A SAN state snapshot was normalized as a SAN adjudication.",
                source_event_ids=_source_ids(event), normalized_event_ids=[event.get("event_id")],
                adjudication_id=_adjudication(event), checkpoint=checkpoint_id,
                evidence={"san": san, "source_event_type": source_type, "san_kind": kind},
                classification="NORMALIZATION_GAP",
            ))
    for trigger_id, trigger in triggers:
        adj = trigger.get("adjudication_id")
        candidates = san_by_trigger.get(trigger_id, []) + (san_by_adj.get(str(adj), []) if adj else [])
        normalized_candidates = [
            event for event in normalized_san
            if trigger_id in _source_ids(event) or (adj and _adjudication(event) == adj)
            or (event.get("san") or {}).get("trigger_event_id") == trigger_id
        ]
        complete = any(all(body.get(field) is not None for field in ("san_before", "san_roll", "san_result", "san_loss", "san_after")) for _, body in candidates)
        complete = complete or any(all((event.get("san") or {}).get(field) is not None for field in ("before", "target", "roll", "result", "loss", "after")) for event in normalized_candidates)
        if not complete:
            findings.append(_finding(
                f"mandatory_san:{trigger_id}", "MANDATORY_SAN_EFFECT_DROPPED", "CRITICAL",
                "A mandatory SAN effect lacks a complete request/roll/result/state lifecycle.",
                source_event_ids=[trigger_id] + [item[0] for item in candidates],
                normalized_event_ids=[event.get("event_id") for event in normalized_candidates],
                adjudication_id=adj, checkpoint=checkpoint_id, cycle=trigger.get("cycle"),
                evidence={"trigger": trigger, "candidate_count": len(candidates), "normalized_candidate_count": len(normalized_candidates)},
                classification="SOURCE_GAMEPLAY_GAP",
            ))
    return findings


ALLOWED_OBJECT_TRANSITIONS = {
    "UNDISCOVERED": {"AVAILABLE"},
    "AVAILABLE": {"IN_COMBAT", "ON_FLOOR", "OWNED", "REMOVED"},
    "IN_COMBAT": {"INCAPACITATED", "ON_FLOOR", "DESTROYED"},
    "INCAPACITATED": {"ON_FLOOR", "DESTROYED"},
    "ON_FLOOR": {"OWNED", "DESTROYED", "REMOVED"},
    "OWNED": {"ON_FLOOR", "DESTROYED", "REMOVED"},
    "DESTROYED": {"DESTROYED"},
    "REMOVED": {"REMOVED"},
}


def _object_transition(event: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]] | None:
    object_id = event.get("object_id") or event.get("target_object_id")
    before, after = event.get("object_state_before"), event.get("object_state_after")
    if object_id and isinstance(before, dict) and isinstance(after, dict):
        return str(object_id), before, after
    return None


def _nested_object_states(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    direct = state.get("object_states")
    if isinstance(direct, dict):
        return direct
    flags = state.get("flags")
    if isinstance(flags, dict) and isinstance(flags.get("object_states"), dict):
        return flags["object_states"]
    return {}


def _object_transitions(event: dict[str, Any]) -> list[tuple[str, dict[str, Any], dict[str, Any], list[str]]]:
    direct = _object_transition(event)
    if direct:
        object_id, before, after = direct
        return [(object_id, before, after, list(after.get("transition_path") or []))]
    updates = event.get("object_state_updates") or {}
    if not isinstance(updates, dict):
        return []
    before_states = _nested_object_states(event.get("state_before"))
    after_states = _nested_object_states(event.get("state_after"))
    rows = []
    for object_id, update in updates.items():
        update = update or {}
        before = before_states.get(object_id) or {}
        after = after_states.get(object_id) or {key: value for key, value in update.items() if key != "transition_path"}
        rows.append((str(object_id), before, after, list(update.get("transition_path") or [])))
    return rows


def audit_objects(
    session: list[dict[str, Any]], unified: list[dict[str, Any]], normalized: list[dict[str, Any]], checkpoint_id: str
) -> list[dict[str, Any]]:
    findings = []
    destroyed: set[str] = set()
    for index, event in enumerate(unified):
        event_id = _event_id(event, "unified", index)
        for object_id, before, after, transition_path in _object_transitions(event):
            before_status, after_status = str(before.get("status") or "").upper(), str(after.get("status") or "").upper()
            path = [str(item).upper() for item in transition_path]
            if not path or path[-1] != after_status:
                path.append(after_status)
            previous = before_status or "UNDISCOVERED"
            invalid_steps = []
            for status in path:
                if not status or status == previous:
                    continue
                if status not in ALLOWED_OBJECT_TRANSITIONS.get(previous, set()):
                    invalid_steps.append(f"{previous}->{status}")
                previous = status
            invalid = bool(invalid_steps)
            invalid = invalid or bool(before.get("destroyed") is True and (after.get("destroyed") is not True or after.get("active") or after.get("owner_id")))
            invalid = invalid or bool(after.get("destroyed") is True and (after.get("active") or after.get("available") or after.get("owner_id")))
            invalid = invalid or bool(after_status == "OWNED" and not after.get("owner_id"))
            if before_status == "DESTROYED" or before.get("destroyed") is True:
                destroyed.add(object_id)
            if after_status == "DESTROYED" or after.get("destroyed") is True:
                destroyed.add(object_id)
            if invalid:
                findings.append(_finding(
                    f"object_transition:{event_id}", "OBJECT_STATE_INVALID_TRANSITION", "CRITICAL",
                    "Object lifecycle transition violates the structured lifecycle contract.",
                    source_event_ids=[event_id], adjudication_id=event.get("adjudication_id"), checkpoint=checkpoint_id,
                    cycle=event.get("cycle"), evidence={"object_id": object_id, "before": before, "after": after, "transition_path": path, "invalid_steps": invalid_steps},
                    evidence_state="CONTRADICTION",
                    classification="SOURCE_CONTRADICTION",
                ))
        facts = event.get("narrative_fact_tags") or []
        claims = event.get("narrative_claims") or []
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            object_id = str(claim.get("object_id") or "")
            predicate = str(claim.get("predicate") or claim.get("state") or "").upper()
            structured = event.get("object_state_after") or {}
            contradiction = object_id in destroyed and predicate in {"ATTACKS", "ACTIVE", "AVAILABLE", "OWNED", "EXISTS"}
            contradiction = contradiction or (structured.get("destroyed") is True and predicate in {"ATTACKS", "ACTIVE", "AVAILABLE", "OWNED"})
            if contradiction:
                findings.append(_finding(
                    f"object_narrative:{event_id}:{object_id}", "OBJECT_NARRATIVE_STATE_CONTRADICTION", "CRITICAL",
                    "Structured narrative claim contradicts the object's authoritative state.",
                    source_event_ids=[event_id], adjudication_id=event.get("adjudication_id"), checkpoint=checkpoint_id,
                    cycle=event.get("cycle"), evidence={"object_id": object_id, "claim": claim, "state": structured},
                    evidence_state="CONTRADICTION",
                    classification="SOURCE_CONTRADICTION",
                ))
        if facts and destroyed:
            for tag in facts:
                if isinstance(tag, dict) and str(tag.get("object_id")) in destroyed and str(tag.get("fact") or "").upper() in {"ATTACKS", "ACTIVE"}:
                    findings.append(_finding(
                        f"object_fact:{event_id}:{tag.get('object_id')}", "OBJECT_NARRATIVE_STATE_CONTRADICTION", "CRITICAL",
                        "Narrative fact tag revives a destroyed object.", source_event_ids=[event_id], checkpoint=checkpoint_id,
                        evidence={"tag": tag}, evidence_state="CONTRADICTION",
                        classification="SOURCE_CONTRADICTION",
                    ))
        for option in event.get("narrative_options") or []:
            if not isinstance(option, dict):
                continue
            grounded = option.get("grounded") is True or bool(option.get("grounded_by") or option.get("scenario_action_id") or option.get("availability_event_id") or option.get("adjudication_id"))
            if not grounded:
                findings.append(_finding(
                    f"ungrounded_option:{event_id}:{option.get('option_id') or 'unknown'}", "UNGROUNDED_NARRATIVE_OPTION", "MAJOR",
                    "A structured narrative option has no Scenario, availability, state, or adjudication evidence.",
                    source_event_ids=[event_id], adjudication_id=event.get("adjudication_id"), checkpoint=checkpoint_id,
                    cycle=event.get("cycle"), evidence={"option": option}, evidence_state="INSUFFICIENT_EVIDENCE",
                    classification="SOURCE_NARRATIVE_GAP",
                ))
    return findings


def audit_combat_and_goal(
    result: dict[str, Any], unified: list[dict[str, Any]], checkpoint_state: dict[str, Any], checkpoint_id: str
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    findings = []
    combats: defaultdict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
    for index, event in enumerate(unified):
        combat_id = event.get("combat_id")
        if combat_id:
            combats[str(combat_id)].append((_event_id(event, "unified", index), event))
    for combat_id, rows in combats.items():
        types = {str(event.get("event_type") or "") for _, event in rows}
        started = bool(types & {"COMBAT_START", "COMBAT_STARTED"})
        ended = bool(types & {"COMBAT_END", "COMBAT_ENDED", "COMBAT_INTERRUPTED", "COMBAT_ESCAPED", "COMBAT_ABORTED_BY_SCENARIO"})
        if started and not ended:
            findings.append(_finding(
                f"combat_termination:{combat_id}", "COMBAT_WITHOUT_TERMINATION", "CRITICAL",
                "Combat starts but has no explicit termination event.",
                source_event_ids=[event_id for event_id, _ in rows], checkpoint=checkpoint_id,
                evidence={"combat_id": combat_id, "event_types": sorted(types)},
                classification="SOURCE_GAMEPLAY_GAP",
            ))
    flags = result.get("final_flags") or {}
    completed = result.get("completed") is True
    clear = str(result.get("phase") or "").lower() == "clear"
    ending = str(result.get("pause_reason") or result.get("ending") or "").lower() in {"game_clear", "clear", "completed"}
    defeated = flags.get("corbitt_defeated") is True
    active_combat = (checkpoint_state.get("combat") or checkpoint_state.get("combat_state") or {}).get("active") is True
    special = any(
        str(event.get("final_result") or event.get("automatic_result") or "").upper() == "SPECIAL_OBJECTIVE_COMPLETED"
        or str((event.get("world_fact") or {}).get("event") or "").upper() == "CORBITT_BODY_DESTROYED"
        for event in unified
    )
    sync = completed and clear and ending and defeated and not active_combat and special
    if completed and not sync:
        findings.append(_finding(
            "goal_completion_sync", "SOURCE_CONTRADICTION", "CRITICAL",
            "Completion, ending, objective, defeated flag, and combat state are not synchronized.",
            checkpoint=checkpoint_id, evidence={"completed": completed, "clear": clear, "ending": ending, "corbitt_defeated": defeated, "active_combat": active_combat, "special_objective": special},
            evidence_state="CONTRADICTION",
        ))
    return findings, {"scenario_completed": completed and clear, "goal_completion_synchronized": sync}


def audit_traceability(
    normalized: list[dict[str, Any]], provenance: dict[str, Any], validation: dict[str, Any], checkpoint_id: str
) -> tuple[list[dict[str, Any]], float]:
    untraceable = [str(event.get("event_id")) for event in normalized if not event.get("source_event_ids")]
    rate = 1.0 - (len(untraceable) / len(normalized) if normalized else 0.0)
    declared = provenance.get("source_traceability_rate")
    findings = []
    if untraceable or declared != 1.0:
        findings.append(_finding(
            "traceability", "NORMALIZATION_GAP", "CRITICAL",
            "Every normalized event must retain source provenance and the declared rate must equal 1.0.",
            normalized_event_ids=untraceable, checkpoint=checkpoint_id,
            evidence={"computed_rate": rate, "declared_rate": declared, "untraceable_count": len(untraceable)},
        ))
    if validation.get("status") != "PASS":
        findings.append(_finding(
            "normalizer_validation", "NORMALIZATION_GAP", "CRITICAL",
            "Formal Normalizer validation did not pass.", checkpoint=checkpoint_id, evidence={"validation": validation},
        ))
    return findings, rate


def audit_normalizer_warnings(normalized_doc: dict[str, Any], checkpoint_id: str) -> list[dict[str, Any]]:
    findings = []
    for index, warning in enumerate((normalized_doc.get("metadata") or {}).get("conversion_warnings") or []):
        code = warning.get("code") if isinstance(warning, dict) else None
        if code == "NORMALIZATION_SOURCE_CONTRADICTION":
            findings.append(_finding(
                f"normalization_contradiction:{index}", "NORMALIZATION_SOURCE_CONTRADICTION", "MAJOR",
                "Normalizer reported contradictory source evidence.", checkpoint=checkpoint_id, evidence={"warning": warning},
                evidence_state="CONTRADICTION",
            ))
    return findings


def audit_legacy_parse(normalized: list[dict[str, Any]], checkpoint_id: str) -> list[dict[str, Any]]:
    offenders = []
    for event in normalized:
        if any((event.get(name) or {}).get("normalization_source") == "LEGACY_TEXT_PARSE" for name in ("san", "modifier")):
            offenders.append(event)
    if not offenders:
        return []
    return [_finding(
        "legacy_text_parse", "NORMALIZATION_GAP", "MAJOR",
        "Formal session depends on legacy free-text parsing.",
        source_event_ids=[source for event in offenders for source in _source_ids(event)],
        normalized_event_ids=[event.get("event_id") for event in offenders], checkpoint=checkpoint_id,
        evidence={"count": len(offenders)},
    )]


def run_audit(
    *, result: dict[str, Any], session: list[dict[str, Any]], unified: list[dict[str, Any]],
    normalized_doc: dict[str, Any], provenance: dict[str, Any], validation: dict[str, Any],
    checkpoint_state: dict[str, Any], checkpoint_manifest: dict[str, Any], input_manifest: dict[str, Any],
) -> dict[str, Any]:
    checkpoint_id = str(checkpoint_manifest.get("checkpoint_id") or "UNKNOWN")
    normalized = list(normalized_doc.get("events") or [])
    findings = []
    findings += audit_roll_contract(unified, normalized, checkpoint_id)
    findings += audit_lifecycle_contract(unified, normalized, checkpoint_id)
    findings += audit_luck(normalized, checkpoint_id)
    findings += audit_san(session, unified, normalized, checkpoint_id)
    findings += audit_objects(session, unified, normalized, checkpoint_id)
    combat_findings, completion = audit_combat_and_goal(result, unified, checkpoint_state, checkpoint_id)
    findings += combat_findings
    trace_findings, traceability = audit_traceability(normalized, provenance, validation, checkpoint_id)
    findings += trace_findings
    findings += audit_normalizer_warnings(normalized_doc, checkpoint_id)
    findings += audit_legacy_parse(normalized, checkpoint_id)
    severity = Counter(item["severity"] for item in findings)
    categories = Counter(item["category"] for item in findings)
    classifications = Counter(item["classification"] for item in findings)
    human_zero = result.get("human_interventions", result.get("human_intervention")) == 0
    input_identity = input_manifest.get("run_input_identity") == "PASS"
    gate = {
        **completion,
        "human_intervention_zero": human_zero,
        "critical_zero": severity["CRITICAL"] == 0,
        "major_zero": severity["MAJOR"] == 0,
        "source_contradiction_zero": categories["SOURCE_CONTRADICTION"] == 0,
        "normalization_gap_zero": categories["NORMALIZATION_GAP"] == 0,
        "roll_contract_incomplete_zero": categories["ROLL_CONTRACT_INCOMPLETE"] == 0,
        "combat_without_termination_zero": categories["COMBAT_WITHOUT_TERMINATION"] == 0,
        "normalization_source_contradiction_zero": categories["NORMALIZATION_SOURCE_CONTRADICTION"] == 0,
        "lifecycle_misclassification_zero": categories["LIFECYCLE_MISCLASSIFIED_AS_NO_ROLL"] == 0,
        **{f"{name.lower()}_zero": categories[name] == 0 for name in sorted(ITERATION2_CATEGORIES)},
        "legacy_text_parse_zero": not any(item["finding_id"] == "legacy_text_parse" for item in findings),
        "traceability_one": traceability == 1.0,
        "input_identity_pass": input_identity,
    }
    formal_status = "PASS" if all(gate.values()) else "NEEDS_ITERATION"
    return {
        "schema_version": SCHEMA_VERSION,
        "auditor_version": AUDITOR_VERSION,
        "session_id": result.get("session_id"),
        "checkpoint_id": checkpoint_id,
        "formal_status": formal_status,
        "video_source_eligible": False,
        "video_eligibility_note": "Auditor v2 never promotes video eligibility; the upper formal runner owns that decision.",
        "gate": gate,
        "summary": {
            "critical_findings": severity["CRITICAL"], "major_findings": severity["MAJOR"],
            "minor_findings": severity["MINOR"], "traceability": traceability,
            "finding_count": len(findings), "categories": {name: categories[name] for name in sorted(ALL_CATEGORIES)},
            "classifications": {name: classifications[name] for name in sorted(OLD_CATEGORIES)},
        },
        "findings": findings,
    }


def _markdown(report: dict[str, Any], manifest: dict[str, Any]) -> str:
    lines = [
        "# Full Session Evidence Audit v2", "",
        f"- Formal status: `{report['formal_status']}`",
        f"- Session: `{report['session_id']}`",
        f"- Checkpoint: `{report['checkpoint_id']}`",
        f"- Auditor: `{report['auditor_version']}` / `{manifest['auditor_sha256']}`",
        "- `VIDEO_SOURCE_ELIGIBLE = false` (上位Formal判定まで固定)", "",
        "## Gate", "",
    ]
    lines += [f"- `{name}`: {'PASS' if value else 'FAIL'}" for name, value in report["gate"].items()]
    lines += ["", "## Findings", ""]
    if not report["findings"]:
        lines.append("- なし")
    for item in report["findings"]:
        lines.append(f"- **{item['severity']} / {item['category']} / {item['finding_id']}**: {item['message']}")
    lines += ["", "## Provenance", "", f"- Manifest: `audit_manifest.json`", f"- Implementation SHA-256: `{manifest['auditor_sha256']}`", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="audit-longrun-formal-v2")
    parser.add_argument("--core-run", type=Path, required=True)
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--provenance", type=Path)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--normalizer-implementation", type=Path, required=True)
    parser.add_argument("--legacy-project", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    core_run, normalized_path, output_dir = args.core_run.resolve(), args.normalized.resolve(), args.output_dir.resolve()
    guard_output_path(core_run, normalized_path, output_dir)
    checkpoint = resolve_checkpoint(core_run, args.checkpoint)
    result_path = _first_existing(core_run, ("result.json", "result.partial.json"))
    session_path = _first_existing(core_run, ("session-log.json", "session_log.json"))
    unified_path = _first_existing(core_run, ("unified-event-log.json", "unified_event_log.json"))
    input_manifest_path = core_run / "input_manifest.json"
    provenance_path = (args.provenance or normalized_path.parent / "provenance_report.json").resolve()
    validation_path = (args.validation or normalized_path.parent / "validation_report.json").resolve()
    for required in (normalized_path, provenance_path, validation_path):
        if not required.is_file():
            raise AuditInputError(f"required Formal Normalizer artifact missing: {required}")
    result = read_json(result_path)
    if not result.get("completed"):
        raise AuditInputError("RUN_INCOMPLETE: Formal audit is forbidden until the Raw Run completes")
    report = run_audit(
        result=result, session=read_json(session_path), unified=read_json(unified_path),
        normalized_doc=read_json(normalized_path), provenance=read_json(provenance_path),
        validation=read_json(validation_path), checkpoint_state=read_json(checkpoint / "state.json"),
        checkpoint_manifest=read_json(checkpoint / "manifest.json"),
        input_manifest=read_json(input_manifest_path) if input_manifest_path.is_file() else {},
    )
    output_dir.mkdir(parents=True, exist_ok=False)
    implementation = sha256(Path(__file__).resolve())
    report["implementation_sha256"] = implementation
    report["legacy_auditor_sha256"] = LEGACY_AUDITOR_SHA256
    legacy = []
    for project in args.legacy_project:
        project = project.resolve()
        entry = {"project_id": project.name, "path": str(project)}
        for name in ("normalized_session.json", "adjudication_evidence_report.json", "adjudication_gap_report.json"):
            path = project / name
            if path.is_file():
                entry[f"{name}_sha256"] = sha256(path)
        legacy.append(entry)
    manifest = {
        "schema_version": SCHEMA_VERSION, "session_id": result.get("session_id"),
        "auditor_version": AUDITOR_VERSION, "auditor_sha256": implementation,
        "implementation_sha256": implementation,
        "legacy_auditor_sha256": LEGACY_AUDITOR_SHA256,
        "normalizer_sha256": sha256(args.normalizer_implementation.resolve()),
        "normalized_session_sha256": sha256(normalized_path),
        "raw_session_log_sha256": sha256(session_path),
        "unified_event_log_sha256": sha256(unified_path),
        "checkpoint_id": report["checkpoint_id"], "checkpoint_path": str(checkpoint),
        "legacy_project_id": [item["project_id"] for item in legacy], "legacy_projects": legacy,
        "started_at": started, "completed_at": datetime.now(timezone.utc).isoformat(),
        "formal_status": report["formal_status"], "video_source_eligible": False,
    }
    write_json(output_dir / "full_session_evidence_audit.json", report)
    write_json(output_dir / "audit_manifest.json", manifest)
    (output_dir / "FULL_SESSION_EVIDENCE_AUDIT.md").write_text(_markdown(report, manifest), encoding="utf-8")
    print(json.dumps({"formal_status": report["formal_status"], "video_source_eligible": False, "output_dir": str(output_dir), "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0 if report["formal_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
