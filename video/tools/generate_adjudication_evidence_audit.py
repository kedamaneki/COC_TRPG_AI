"""Generate the read-only M3 adjudication evidence audit artifacts.

This script intentionally does not mutate normalized_session.json, edited_script.json,
or any presentation/runtime implementation.  It only reads the captured session and
writes audit reports beneath projects/corbitt_clear_001 and docs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "corbitt_clear_001"


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def nested(obj: Any, *keys: str, default: Any = None) -> Any:
    current = obj
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    return default if current is None else current


def placeholder_values(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for child in value.values():
            found.extend(placeholder_values(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(placeholder_values(child))
    elif value is None:
        found.append("null")
    elif isinstance(value, str) and value.strip().upper() in {"—", "-", "N/A", "UNKNOWN", "NULL"}:
        found.append(value)
    return found


def presentation_index(lines: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for line in lines:
        for source_id in line.get("source_event_ids", []):
            index.setdefault(source_id, []).append(line)
    return index


def timeline_index(paths: list[Path]) -> dict[str, list[dict[str, Any]]]:
    index: dict[str, list[dict[str, Any]]] = {}
    for path in paths:
        if not path.exists():
            continue
        for clip in load(path).get("clips", []):
            for source_id in clip.get("source_event_ids", []):
                index.setdefault(source_id, []).append(clip)
    return index


def source_ref(event: dict[str, Any]) -> dict[str, Any]:
    payload = nested(event, "metadata", "source_payload", default={})
    return {
        "stream": nested(event, "metadata", "source_stream"),
        "index": nested(event, "metadata", "source_index"),
        "event_id": payload.get("event_id"),
        "transaction_id": payload.get("transaction_id") or nested(payload, "meta", "transaction_id"),
        "investigation_id": payload.get("investigation_id"),
    }


def result_text(value: Any) -> Any:
    if value is None:
        return None
    numeric = {0: "BLOCKED/NO_PROGRESS", 1: "EXTREME_OR_CRITICAL", 2: "SUCCESS", 3: "HARD_SUCCESS"}
    return numeric.get(value, value)


def make_skill_rows(
    events: list[dict[str, Any]],
    m2_index: dict[str, list[dict[str, Any]]],
    m3_index: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("event_type") not in {"SKILL_CHECK", "DICE_RESULT"}:
            continue
        dice = event.get("dice") or {}
        ref = source_ref(event)
        source_payload = nested(event, "metadata", "source_payload", default={})
        m2 = m2_index.get(event["event_id"], [])
        m3 = m3_index.get(event["event_id"], [])
        overlay = next((line.get("overlay") for line in m2 if line.get("overlay")), None)
        missing = [key for key in ("target_value", "roll", "result") if dice.get(key) is None]
        classification = "COMPLETE"
        severity = "INFO"
        recommended = "None"
        notes: list[str] = []
        normalized_complete = not missing
        source_complete = normalized_complete

        if event["event_type"] == "SKILL_CHECK" and (dice.get("roll") is None or dice.get("target_value") is None):
            classification = "SOURCE_LOGGING_GAP"
            severity = "MAJOR"
            recommended = "TRPG Logging"
            source_complete = False
            notes.append("Unified Event Log records result level but omits target_value and/or roll.")
        elif missing:
            classification = "SOURCE_LOGGING_GAP"
            severity = "MAJOR"
            recommended = "TRPG Logging"
            source_complete = False
            notes.append("Source result text does not contain a complete numeric check tuple.")

        text = event.get("text") or ""
        luck = re.search(r"幸運を\s*(\d+)\s*消費.*?(regular|hard|extreme)\s*成功", text, re.I | re.S)
        modifier = None
        final_result = result_text(dice.get("result"))
        if luck:
            modifier = {"type": "LUCK_SPEND", "amount": int(luck.group(1))}
            final_result = f"{luck.group(2).upper()}_SUCCESS"
            classification = "NORMALIZATION_GAP"
            severity = "MAJOR"
            recommended = "Normalizer"
            normalized_complete = False
            notes.append("Luck modifier and final success exist in L1 text but are not structured in L2 dice fields.")

        presentation_present = any(line.get("content_decision") != "CUT" for line in m2)
        if normalized_complete and not presentation_present:
            classification = "PRESENTATION_GAP"
            severity = "MAJOR"
            recommended = "Video Presentation"
            notes.append("Complete normalized result is absent from the M2 presentation plan.")

        overlay_result = overlay.get("result") if isinstance(overlay, dict) else None
        accuracy = "NOT_APPLICABLE"
        if overlay:
            accuracy = "MATCH" if overlay_result == dice.get("result") else "MISMATCH"
            if luck and m3:
                accuracy = "M3_CORRECTED_FROM_EXPLICIT_L1_TEXT"

        rows.append(
            {
                "check_id": event["event_id"],
                "record_role": "unified_skill_record" if event["event_type"] == "SKILL_CHECK" else "session_result_record",
                "scene": event.get("scene_id") or nested(source_payload, "scene_id"),
                "turn": event.get("turn"),
                "source_event_ids": event.get("source_event_ids", []),
                "source_reference": ref,
                "check_type": event["event_type"],
                "actor": event.get("actor_id"),
                "target": nested(event, "action", "target") or source_payload.get("target") or nested(source_payload, "meta", "target"),
                "skill_or_stat": dice.get("skill_name") or source_payload.get("kp_selected_skill") or source_payload.get("skill"),
                "target_value": dice.get("target_value"),
                "roll": dice.get("roll"),
                "raw_result": result_text(dice.get("result")),
                "modifier": modifier,
                "final_result": final_result,
                "state_before": source_payload.get("state_before"),
                "state_after": source_payload.get("state_after"),
                "world_event_links": [],
                "source_complete": source_complete,
                "normalized_complete": normalized_complete,
                "presentation_present": presentation_present,
                "m2_script_line_ids": [line.get("script_line_id") for line in m2],
                "m3_rendered": bool(m3),
                "m3_clip_ids": [clip.get("clip_id") for clip in m3],
                "presentation_overlay": overlay,
                "presentation_accuracy": accuracy,
                "overlay_placeholders": placeholder_values(overlay) if overlay else [],
                "classification": classification,
                "severity": severity,
                "recommended_fix_layer": recommended,
                "missing_evidence": missing,
                "notes": notes,
            }
        )
    return rows


def main() -> None:
    normalized_path = PROJECT / "normalized_session.json"
    edited_path = PROJECT / "edited_script.json"
    normalized = load(normalized_path)
    edited = load(edited_path)
    manifest = load(PROJECT / "source" / "source_manifest.json")
    source_paths = {entry["kind"]: Path(entry["path"]) for entry in manifest["source_files"]}
    unified = load(source_paths["unified-event-log.json"])
    session = load(source_paths["session-log.json"])
    result = load(source_paths["result.json"])
    pcs = load(source_paths["pcs.json"])
    dataset = source_paths["pcs.json"].parent / "datasets" / "corbitt_house.json"

    m2_index = presentation_index(edited["lines"])
    m3_paths = [
        ROOT / "projects" / "m3_scene_preview" / "video_timeline.json",
        ROOT / "projects" / "m3_final_battle_preview" / "video_timeline.json",
    ]
    m3_index = timeline_index(m3_paths)
    events = normalized["events"]
    evidence = make_skill_rows(events, m2_index, m3_index)

    wall_roll = next(e for e in unified if e.get("event_id") == "evt_000238_1d90ff80b8a05f6ef107")
    wall_examine = next(e for e in unified if e.get("event_id") == "evt_000241_9fdcc776929a7cac6e3a")
    wall_break = next(e for e in unified if e.get("event_id") == "evt_000275_f1ab195f578e83b2b637")
    wall_session_claim = session[315]
    wall_break_log = session[359]
    wall_case = {
        "case_id": "wall_board_break",
        "runtime_check": "CONTRADICTORY",
        "actor_str_present": True,
        "actor_str": nested(pcs, "pc_01", "attributes", "STR"),
        "opposed_or_target_str_present": False,
        "adjudication_form": "UNKNOWN",
        "str_requested": True,
        "roll_required_claim": wall_roll.get("roll_required"),
        "target_value": None,
        "roll": None,
        "result_level": wall_roll.get("result"),
        "result_level_interpretation": "Source uses numeric level 2, but no numeric roll evidence is recorded.",
        "first_transaction": wall_examine.get("transaction_id"),
        "first_state_basement_planks_broken": {
            "before": nested(wall_examine, "state_before", "flags", "basement_planks_broken"),
            "after": nested(wall_examine, "state_after", "flags", "basement_planks_broken"),
        },
        "later_break_transaction": wall_break.get("transaction_id"),
        "later_break_action": wall_break.get("selected_action"),
        "later_break_dice_used": wall_break.get("dice_used"),
        "later_break_state_change": nested(wall_break, "flags_changed", "basement_planks_broken"),
        "source_log": "CONTRADICTORY",
        "normalized": "PARTIAL",
        "presentation": "PARTIAL",
        "action_evidence": "MISSING",
        "result_evidence": "PRESENT",
        "classification": "SOURCE_CONTRADICTION",
        "severity": "CRITICAL",
        "recommended_fix_layer": ["TRPG Core", "TRPG Logging", "Scenario Data"],
        "source_event_ids": [
            wall_roll["event_id"], wall_examine["event_id"], wall_break["event_id"],
            "session_log:000315", "session_log:000359",
        ],
        "evidence": {
            "str_claim_text": wall_session_claim.get("text"),
            "actual_break_text": wall_break_log.get("text"),
        },
        "conclusion": "No STR/opposed roll can be proven. The first transaction narrates destruction while state remains false; a later no-roll push changes the flag to true.",
    }

    san_event = next(e for e in events if e.get("event_type") == "SAN_LOSS")
    san_lines = m2_index.get(san_event["event_id"], [])
    san_overlay = next((x.get("overlay") for x in san_lines if x.get("overlay")), None)
    san_text = san_event.get("text") or ""
    san_match = re.search(r"1d100\s*＞\s*(\d+)\s*＞\s*(成功|失敗).*?現在値:(\d+).*?正気度が\s*(\d+)\s*減少", san_text, re.S)
    assert san_match
    san_report = {
        "audit_status": "GAPS_FOUND",
        "san_check_count": 1,
        "checks": [
            {
                "check_id": san_event["event_id"],
                "source_event_ids": san_event.get("source_event_ids"),
                "actor": "pc_02 / エレノア教授",
                "trigger_event": "corbitt_knife encounter; trigger_knife_attack false→true",
                "trigger_source_event_id": "evt_000233_bf4199391d793e604605",
                "san_before": int(san_match.group(3)),
                "san_roll": int(san_match.group(1)),
                "san_target": int(san_match.group(3)),
                "san_result": san_match.group(2),
                "loss_rule_success": "0",
                "loss_rule_failure": "1D4 (runtime encounter payload)",
                "runtime_resolved_failure_formula": "1d3 fallback when value is a single formula",
                "actual_roll_formula": "0 (success branch)",
                "actual_loss": int(san_match.group(4)),
                "san_after": int(san_match.group(3)),
                "state_value_basis": "L1 text explicitly says current=70 and loss=0; checkpoint also records current SAN 70.",
                "l1_complete": True,
                "l2_structured_values": san_event.get("san"),
                "l2_complete": False,
                "presentation_present": bool(san_lines),
                "presentation_overlay": san_overlay,
                "overlay_placeholders": placeholder_values(san_overlay),
                "classification": "NORMALIZATION_GAP",
                "severity": "MAJOR",
                "recommended_fix_layer": "Normalizer",
                "causality": {
                    "trigger": "PRESENT",
                    "san_check": "PRESENT_IN_L1_TEXT",
                    "san_result": "PRESENT_IN_L1_TEXT",
                    "san_change": "PRESENT (0 loss)",
                },
            }
        ],
        "schema_bug": {
            "issue_id": "TRPG_CORE_SAN_LOSS_SCHEMA_BUG",
            "scenario_schema_value": "1D4",
            "runtime_payload_source": "build_corbitt_scenario.py corbitt_knife encounter",
            "runtime_resolver_behavior": "A slash-form value is honored. A single value is ignored on failure and fail_loss defaults to 1d3.",
            "actual_session_impact": "Not observable because this check succeeded and lost 0 SAN.",
            "classification": "SOURCE_GAMEPLAY_GAP",
            "severity": "MAJOR",
            "recommended_fix_layer": "TRPG Core",
            "evidence_files": [
                str(dataset),
                r"F:\制作物\その3\src\build_corbitt_scenario.py:486",
                r"F:\制作物\その3\src\main.py:2299",
            ],
        },
    }

    luck_event = next(e for e in events if e.get("event_id") == "norm:session:000311")
    luck_m2 = m2_index.get(luck_event["event_id"], [])
    luck_m3 = m3_index.get(luck_event["event_id"], [])
    modifier_report = {
        "audit_status": "GAPS_FOUND",
        "luck_spend_count": 1,
        "orphan_modifier_count": 0,
        "modifiers": [
            {
                "modifier_id": "luck_spend_session_000311",
                "source_event_ids": ["session_log:000309", "session_log:000311", "norm:session:000309", "norm:session:000311"],
                "transaction_id": "a4c901d3-1733-4c37-9535-afa47884efe1",
                "linkage": "Explicit duplicated roll tuple (目星 target 50, roll 59) and target corbitt_knife; final log omits transaction_id.",
                "original_target": 50,
                "original_roll": 59,
                "raw_result": "FAILURE",
                "luck_spent": 9,
                "final_result": "REGULAR_SUCCESS",
                "final_target_or_effective_margin": 9,
                "luck_before": 50,
                "luck_after": 41,
                "normalized_raw_result": nested(luck_event, "dice", "result"),
                "normalized_modifier": None,
                "normalized_final_result": None,
                "m2_presentation_result": nested(luck_m2[0], "overlay", "result") if luck_m2 else None,
                "m3_presentation_result": next((nested(c, "overlay", "final_result") for c in luck_m3 if nested(c, "overlay", "final_result") is not None), None),
                "classification": "NORMALIZATION_GAP",
                "severity": "MAJOR",
                "recommended_fix_layer": "Normalizer / structured source logging",
                "presentation_note": "Iteration 6 displays raw failure, Luck -9, and final success using explicit L1 text; M2 base overlay alone still says failure.",
            }
        ],
    }

    combat_types = {"COMBAT_START", "COMBAT_ACTION", "COMBAT_END"}
    combat_events = [e for e in events if e.get("event_type") in combat_types]
    combat_report = {
        "audit_status": "GAPS_FOUND",
        "knife_combat": {
            "combat_start_intended": True,
            "combat_start_logged": False,
            "attacker": "corbitt_floating_dagger",
            "target": "pc_02 / エレノア教授",
            "action": "attack is narrated only",
            "attack_roll": None,
            "defense_or_evade": None,
            "damage_roll": None,
            "hp_change": None,
            "combat_end": None,
            "trigger_source_event_id": "evt_000233_bf4199391d793e604605",
            "classification": "SOURCE_GAMEPLAY_GAP",
            "severity": "CRITICAL",
            "recommended_fix_layer": "TRPG Core",
        },
        "final_battle": {
            "combat_id": "combat-71-2483",
            "combat_start": "PRESENT",
            "important_action": {"actor": "pc_01", "action": "break", "target": "corbitt_body"},
            "check": "SPECIAL_OBJECTIVE / scenario_condition; no attack roll recorded",
            "result": "scenario_condition resolved",
            "corpse_destruction": "PRESENT_AS_STRUCTURED_SPECIAL_OBJECTIVE",
            "special_objective": "PRESENT",
            "combat_end": "PRESENT",
            "attack_roll": None,
            "defense_or_evade": None,
            "damage_roll": None,
            "hp_change": {"before": 12, "after": 12},
            "source_event_ids": [e["event_id"] for e in combat_events],
            "l1_structured_complete_for_special_objective": True,
            "l1_human_narrative": False,
            "l2_complete": True,
            "m3_presentation": "COMPLETE_CONSERVATIVE_NARRATIVE",
            "classification": "SOURCE_NARRATIVE_GAP",
            "severity": "MINOR",
            "recommended_fix_layer": "TRPG Logging / narrative source",
            "note": "This was not a normal attack exchange. The source resolves the battle as one special objective; no missing attack dice are inferred.",
        },
        "normalized_combat_event_count": len(combat_events),
        "normalized_combat_events": [
            {
                "event_id": e["event_id"],
                "event_type": e["event_type"],
                "actor": e.get("actor_id"),
                "combat": e.get("combat"),
                "action": e.get("action"),
                "source_event_ids": e.get("source_event_ids"),
            }
            for e in combat_events
        ],
    }

    gaps = [
        {
            "gap_id": "wall_board_str_evidence_contradiction",
            "classification": "SOURCE_CONTRADICTION",
            "severity": "CRITICAL",
            "recommended_fix_layer": ["TRPG Core", "TRPG Logging", "Scenario Data"],
            "detail": "STR roll_required/result claims have no roll or target, the first transaction narrates destruction while state remains false, and a later no-roll push performs the actual false→true state change.",
        },
        {
            "gap_id": "knife_combat_resolution_missing",
            "classification": "SOURCE_GAMEPLAY_GAP",
            "severity": "CRITICAL",
            "recommended_fix_layer": "TRPG Core",
            "detail": "Knife combat_start is intended by scenario data, but no combat start, attack, defense, damage, HP change, or combat end is executed/logged.",
        },
        {
            "gap_id": "san_fields_dropped_by_normalizer",
            "classification": "NORMALIZATION_GAP",
            "severity": "MAJOR",
            "recommended_fix_layer": "Normalizer",
            "detail": "L1 text has SAN target/current 70, roll 40, success, and loss 0; all L2 SAN fields are null, causing placeholder overlay values.",
        },
        {
            "gap_id": "san_single_formula_fallback",
            "classification": "SOURCE_GAMEPLAY_GAP",
            "subtype": "TRPG_CORE_SAN_LOSS_SCHEMA_BUG",
            "severity": "MAJOR",
            "recommended_fix_layer": "TRPG Core",
            "detail": "The knife encounter supplies value=1D4, but the resolver only honors slash-form values and otherwise defaults failure to 1d3. The executed check succeeded, so this session did not expose a wrong SAN total.",
        },
        {
            "gap_id": "luck_modifier_not_structured",
            "classification": "NORMALIZATION_GAP",
            "severity": "MAJOR",
            "recommended_fix_layer": "Normalizer / structured source logging",
            "detail": "L1 text explicitly changes failure to regular success with Luck 9, while L2 retains only the raw failure and no modifier relation.",
        },
        {
            "gap_id": "unified_skill_numeric_evidence_missing",
            "classification": "SOURCE_LOGGING_GAP",
            "severity": "MAJOR",
            "recommended_fix_layer": "TRPG Logging",
            "detail": "All 35 normalized SKILL_CHECK records sourced from Unified Event Log lack a numeric roll and target threshold; many can only be supplemented by separate session-log records.",
        },
        {
            "gap_id": "final_battle_human_narrative_missing_at_source",
            "classification": "SOURCE_NARRATIVE_GAP",
            "severity": "MINOR",
            "recommended_fix_layer": "TRPG Logging / narrative source",
            "detail": "The special-objective lifecycle is structured, but the source provides no human-readable action/result narration. M3 currently supplies conservative grounded narration.",
        },
    ]
    gap_report = {
        "audit_status": "GAPS_FOUND",
        "gaps": gaps,
        "severity_summary": dict(Counter(g["severity"] for g in gaps)),
        "classification_summary": dict(Counter(g["classification"] for g in gaps)),
        "presentation_gap_count": sum(g["classification"] == "PRESENTATION_GAP" for g in gaps),
        "note": "No primary PRESENTATION_GAP was found for the representative SAN case: the placeholders originate from null normalized fields.",
    }

    report = {
        "audit": "M3_ADJUDICATION_EVIDENCE_AUDIT",
        "status": "GAPS_FOUND",
        "scope": {
            "project": "corbitt_clear_001",
            "normalized_event_count": len(events),
            "edited_script_line_count": len(edited["lines"]),
            "scene_count": len({line.get("scene_id") for line in edited["lines"]}),
            "full_session_logic_audited": True,
            "full_session_m3_rendered": False,
            "m3_render_scope": [str(path) for path in m3_paths],
        },
        "truth_source_priority": ["Core state transition", "Unified Event Log / Source Log", "Normalized Session", "Presentation"],
        "hashes": {
            "normalized_session_sha256": sha256(normalized_path),
            "edited_script_sha256": sha256(edited_path),
        },
        "event_type_counts": dict(Counter(e.get("event_type") for e in events)),
        "skill_check_summary": {
            "normalized_skill_check_records": sum(e.get("event_type") == "SKILL_CHECK" for e in events),
            "normalized_dice_result_records": sum(e.get("event_type") == "DICE_RESULT" for e in events),
            "evidence_rows": len(evidence),
            "classifications": dict(Counter(row["classification"] for row in evidence)),
            "note": "Rows preserve both Unified SKILL_CHECK records and session-log DICE_RESULT records. They are not merged without an explicit transaction/relation.",
        },
        "evidence": evidence,
        "representative_cases": {
            "wall_board_break": wall_case,
            "knife_san": san_report["checks"][0],
            "knife_combat": combat_report["knife_combat"],
            "luck_spend": modifier_report["modifiers"][0],
            "final_battle": combat_report["final_battle"],
        },
        "gap_summary": gap_report,
        "m3_status": ["M3 PRESENTATION_NEEDS_ITERATION", "M3 ASSET_INPUT_REQUIRED", "M3 LICENSE_REVIEW_REQUIRED"],
        "inputs_modified": False,
        "source_result_completed": result.get("completed"),
    }

    dump(PROJECT / "adjudication_evidence_report.json", report)
    dump(PROJECT / "san_evidence_report.json", san_report)
    dump(PROJECT / "combat_evidence_report.json", combat_report)
    dump(PROJECT / "modifier_evidence_report.json", modifier_report)
    dump(PROJECT / "adjudication_gap_report.json", gap_report)

    csv_path = PROJECT / "adjudication_evidence_table.csv"
    columns = [
        "check_id", "record_role", "scene", "turn", "actor", "check_type", "target", "skill_or_stat",
        "target_value", "roll", "raw_result", "modifier", "final_result", "source_complete",
        "normalized_complete", "presentation_present", "m3_rendered", "presentation_accuracy",
        "classification", "severity", "recommended_fix_layer", "missing_evidence",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in evidence:
            out = {key: row.get(key) for key in columns}
            for key in ("modifier", "missing_evidence"):
                out[key] = json.dumps(out[key], ensure_ascii=False)
            writer.writerow(out)

    classification_counts = Counter(row["classification"] for row in evidence)
    doc = f"""# M3 Adjudication Evidence Audit — 判定証拠監査

監査日: 2026-10-12  
対象: `projects/corbitt_clear_001` 全53シーン、Normalized 678イベント、M2 425行

## 総合判定

`ADJUDICATION_EVIDENCE_AUDIT = GAPS_FOUND`

判定・SAN・戦闘の欠落はPresentationだけの問題ではない。代表的なSAN表示の `—` は、L1本文にある数値をNormalizerが構造化しなかったことが直接原因である。壁板はSTRロールの表示漏れではなく、ログと状態遷移が矛盾している。ナイフ戦闘はGameplay処理自体が完結していない。

M3はCLOSEDにしない。状態は `M3 PRESENTATION_NEEDS_ITERATION / M3 ASSET_INPUT_REQUIRED / M3 LICENSE_REVIEW_REQUIRED` を維持する。

## Audit Scope

- Truth Source: Core state transition → Unified Event Log / Source Log → Normalized Session → Presentation。
- 全 `SKILL_CHECK` 35件、全 `DICE_RESULT` 35件、SAN 1件、Luck変更1件、全Combat構造イベント7件を列挙した。
- M2/visual planは全編を監査した。M3の実レンダー確認範囲はナイフ遭遇と最終戦プレビューで、全編レンダーは存在しない。
- `normalized_session.json` と `edited_script.json` は変更していない。

## Skill Checks

監査表はUnified由来の `SKILL_CHECK` とSession Log由来の `DICE_RESULT` を別行で保持した。明示的なtransaction/relationがないレコードを近接だけで統合していない。

- Evidence rows: {len(evidence)}
- COMPLETE: {classification_counts.get('COMPLETE', 0)}
- SOURCE_LOGGING_GAP: {classification_counts.get('SOURCE_LOGGING_GAP', 0)}
- NORMALIZATION_GAP: {classification_counts.get('NORMALIZATION_GAP', 0)}
- PRESENTATION_GAP: {classification_counts.get('PRESENTATION_GAP', 0)}

Unified由来35件はすべて数値rollとtarget thresholdを欠く。結果レベルだけのレコードからダイス値は復元できない。Session Logの別レコードには多くの数値結果があるが、明示IDなしの対応を自動確定していない。

## STR / Opposed Checks

壁板について、PC1のSTR 55はcheckpointに存在する。しかし相手側STR、target threshold、rollは存在せず、対抗ロール・通常STR・Hard/Extremeのどれだったかは確定できない。

`evt_000238...` は `roll_required=true / kp_selected_skill=STR / result=2` を持つがrollを欠く。続くtransactionでは `basement_planks_broken` がfalseのままである。一方Session Logは同じ場面で板を壊したと語る。実際のfalse→trueは後の `evt_000275...` で、PC2の `push / basement_planks / dice_used=false` により発生する。

分類: **SOURCE_CONTRADICTION / CRITICAL**。STR成功を動画側で補完してはならない。

## SAN Checks

SANチェックは1件。

- trigger: コービットのナイフが自律攻撃を開始
- before/target: 70
- roll: 40
- result: 成功
- actual loss: 0
- after: 70

L1本文には上記があるが、L2の `san` とstate changeはnull/空で、M2 overlayも `before/after/loss/result=null` となる。分類は **NORMALIZATION_GAP / MAJOR**。表示の `—` をPresentationで推測補完するべきではない。

ナイフ遭遇のscenario builderは失敗損失を単一値 `1D4` として渡す。一方runtime resolverはslash形式だけを直接扱い、単一値では `fail_loss` がなければ `1d3` へfallbackする。これは **TRPG_CORE_SAN_LOSS_SCHEMA_BUG**。今回の実ロールは成功で損失0だったため、誤ったSAN減少値は実セッション上では発生していない。

## Luck Modifiers

Luck Spendは1件。目星50に59で失敗し、幸運9を消費してregular成功、残り41になった。L1本文は一つの結果文内で元判定を再掲しており孤立modifierではないが、最終レコードはtransaction_idを欠く。L2はraw failureだけを保持し、modifier/final resultを構造化していない。

分類: **NORMALIZATION_GAP / MAJOR**。M3 Iteration 6は明示的L1本文から「失敗→幸運-9→成功」を正しく表示するが、M2の元overlayは失敗のままである。

## Combat Adjudication

NormalizedのCombat構造イベントは7件。ナイフ遭遇と最終戦は別扱いになる。

- ナイフ: scenario dataはcombat_startを要求するが、実行ログに開始、攻撃roll、回避、防御、damage、HP change、combat endがない。**SOURCE_GAMEPLAY_GAP / CRITICAL**。
- 最終戦: `combat-71-2483` を開始し、`break / corbitt_body` をSPECIAL_OBJECTIVEとしてscenario_conditionで解決し、戦闘終了まで記録している。通常攻撃rollやdamage exchangeではないため、それらを欠落値として創作しない。構造化ライフサイクルは成立するが人間向け本文がないため **SOURCE_NARRATIVE_GAP / MINOR**。M3は構造化事実だけから保守的な決着描写を作成済み。

## Wall Board Break

- Runtime check: CONTRADICTORY
- Source log: CONTRADICTORY
- Normalized: PARTIAL
- Presentation: PARTIAL
- ACTION evidence: MISSING
- RESULT/world-state evidence: PRESENT（ただし後の別transaction）
- Final classification: **SOURCE_CONTRADICTION / CRITICAL**

## Knife Encounter

ナイフ発見の目星はLuckで成功化され、怪異の発生とSANチェックまでは追跡できる。しかし「攻撃してきた」の後にCombat処理が存在しない。M3はSANの原因描写を前へ移したが、attack/evade/damageを生成していない。

## Final Battle

最終戦はnormal attackではなく特殊目標一回で終了する。開始、通常行動拒否、special objective選択、scenario_condition解決、終了は構造ログにある。数値攻撃を推測せず、この解決形式をそのまま報告する。

## Presentation Gaps

今回の代表問題には、L2が完全なのにL3だけ欠ける一次的な `PRESENTATION_GAP` は確認しなかった。SAN placeholderはNormalizer起因で、LuckのM2不一致もmodifier/final resultがL2で構造化されていないことが起点である。

## Normalization Gaps

1. SAN本文のbefore/target/roll/result/loss/afterがL2でnull。
2. Luck消費とfinal resultがL2に独立構造として存在しない。

## Source Logging Gaps

Unifiedの全35 `SKILL_CHECK` はrollとtarget thresholdを欠く。特に壁板は `result=2` だけで、何を振って成功したのかを証明できない。

## Source Gameplay Gaps

1. ナイフ戦闘の開始から終了までの処理が欠落。
2. SAN単一式 `1D4` が失敗側式として扱われず `1d3` fallbackになる実装不整合。

## Source Contradictions

壁板は、STR判定で壊したという本文、壊れていないstate、後の自動成功による実state changeが競合する。自動補正は禁止する。

## Severity Summary

- CRITICAL: 2
- MAJOR: 4
- MINOR: 1

## Recommended Fix Layer

1. **TRPG Core**: ナイフCombat処理とSAN loss resolver。
2. **TRPG Logging / Scenario Data**: 壁板の判定・状態遷移を一本化し、roll/target/result/world event relationを同じtransactionで記録。
3. **Normalizer**: SAN構造値、Luck modifier、raw/final resultを保持。
4. **Video Presentation**: 上流が揃った後に正規化値だけを表示。欠落ダイスは生成しない。

## M3 Impact

M3は現状の表示基盤を維持できるが、上流欠落があるため全編公開可能とは判定できない。Human Review、素材、ライセンス確認も残る。

## TRPG Core Impact

ナイフ戦闘欠落はシナリオ完走の事実とは別に、ゲーム上の危険と結果を消している。壁板は結果を先に語って後の別処理でstateを合わせており、再現可能な判定証拠になっていない。SAN 1D4問題は今回の成功rollでは顕在化しなかったが、失敗時に誤計算するコード経路が確認できる。

## 成果物

- `projects/corbitt_clear_001/adjudication_evidence_report.json`
- `projects/corbitt_clear_001/san_evidence_report.json`
- `projects/corbitt_clear_001/combat_evidence_report.json`
- `projects/corbitt_clear_001/modifier_evidence_report.json`
- `projects/corbitt_clear_001/adjudication_gap_report.json`
- `projects/corbitt_clear_001/adjudication_evidence_table.csv`
"""
    (ROOT / "docs" / "M3_ADJUDICATION_EVIDENCE_AUDIT.md").write_text(doc, encoding="utf-8")


if __name__ == "__main__":
    main()
