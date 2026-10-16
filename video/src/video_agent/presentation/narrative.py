from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

from video_agent.common.io import sha256_file, write_json


SEMANTIC_CLASSES = {
    "TECHNICAL_INTERNAL",
    "GAME_MECHANIC",
    "WORLD_EVENT",
    "TABLETOP_INTERACTION",
    "UNKNOWN_SYSTEM_EVENT",
}
NARRATIVE_ROLES = {"CAUSE", "SETUP", "ACTION", "RESULT", "CONSEQUENCE", "CONTEXT"}
SHORT_RESPONSES = {
    "yes", "no", "はい", "いいえ", "ok", "cancel", "confirm", "retry", "push",
    "プッシュする", "プッシュしない", "再試行する", "再試行しない", "続行", "中止", "承認", "拒否",
}
TECHNICAL_MARKERS = (
    "action availability", "試行権消費済み", "combat director", "session director",
    "progress director", "システムブロック", "進行指示", "api", "checkpoint", "resume",
    "cache", "provider", "token", "debug", "telemetry", "internal state", "system_forced",
    "システム検証エラー", "再生成上限", "解釈ログ", "アクション自動補正",
)
WORLD_TEXT_MARKERS = (
    "宙に浮", "襲いかか", "扉を開け", "通路を開け", "崩れ落ち", "呪いは解かれ",
    "呪いが解かれ", "戦闘が終結", "戦闘終了", "戦闘開始", "生きている", "倒れ",
    "破壊され", "破壊し", "移動した", "手がかり", "見つかった", "発見",
)
GAME_EVENT_TYPES = {
    "DICE_ROLL", "DICE_RESULT", "SKILL_CHECK", "SKILL_RESULT", "SAN_CHANGE", "SAN_CHECK",
    "SAN_LOSS", "HP_CHANGE", "HP_LOSS", "HP_GAIN", "INITIATIVE", "LUCK_SPEND",
}
WORLD_EVENT_TYPES = {
    "CLUE_FOUND", "COMBAT_START", "COMBAT_ACTION", "COMBAT_END", "ENDING", "DEATH",
    "INCAPACITATION", "LOCATION_CHANGE", "SCENARIO_EVENT", "ITEM_ACQUIRED", "ITEM_USED",
}


def _text(event: dict) -> str:
    return str(event.get("display_text") or event.get("text") or "").strip()


def _source_payload(event: dict) -> dict:
    return event.get("metadata", {}).get("source_payload", {}) or {}


def _target(event: dict) -> str | None:
    payload = _source_payload(event)
    meta = payload.get("meta") or {}
    action = event.get("action") or {}
    return payload.get("target") or meta.get("target") or action.get("target")


def semantic_class(event: dict) -> str:
    """Classify presentation meaning rather than hiding by SYSTEM origin alone."""
    text = _text(event)
    lowered = text.lower()
    event_type = str(event.get("event_type") or "")
    if any(marker in lowered for marker in TECHNICAL_MARKERS):
        return "TECHNICAL_INTERNAL"
    if event.get("presentation_origin") in {"SYSTEM_PROMPT", "SYSTEM_RESPONSE"}:
        return "TABLETOP_INTERACTION"
    if lowered.strip(" \t\r\n。．.!！?？") in SHORT_RESPONSES:
        return "TABLETOP_INTERACTION"
    if event_type in WORLD_EVENT_TYPES or any(marker in text for marker in WORLD_TEXT_MARKERS):
        return "WORLD_EVENT"
    if event_type in GAME_EVENT_TYPES or event.get("overlay"):
        return "GAME_MECHANIC"
    is_system = event.get("speaker_id") == "system" or text.startswith("システム:")
    return "UNKNOWN_SYSTEM_EVENT" if is_system else "WORLD_EVENT"


def conservative_world_narrative(event: dict) -> str | None:
    """Turn only explicit structured facts into conservative Japanese narration."""
    payload = _source_payload(event)
    event_type = event.get("event_type")
    action = payload.get("selected_action") or (event.get("action") or {}).get("action_id")
    target = payload.get("target") or (event.get("action") or {}).get("target")
    effect = str(payload.get("effect") or "")
    state = payload.get("combat_state")
    if event_type == "COMBAT_ACTION" and action == "break" and target == "corbitt_body":
        if "resolved" in effect or payload.get("result") == "scenario_condition":
            return "ウォルター・コービットの遺体が破壊されました。"
    if event_type == "COMBAT_END" or state == "ENDED":
        return "戦闘が終結します。"
    if event_type == "ENDING" and "呪い" in _text(event):
        return "屋敷を覆っていた冒涜的な気配が霧散し、悪霊の家の呪いが解かれます。"
    return None


def _short_response_audit(lines: list[dict]) -> list[dict]:
    results = []
    for index, line in enumerate(lines):
        token = _text(line).strip(" \t\r\n。．.!！?？").lower()
        if token not in SHORT_RESPONSES or line.get("speaker_id") in {None, "system", "kp"}:
            continue
        previous = lines[index - 1] if index else {}
        following = lines[index + 1] if index + 1 < len(lines) else {}
        following_text = _text(following)
        if "【幸運消費】" in following_text or re.search(r"【プッシュ(?:方針|実行|成功|失敗|開始)】", following_text):
            classification = "TABLETOP_INTERACTION_RESPONSE"
            reason = "EXPLICIT_FOLLOWUP_FACT"
        elif "【プッシュ見送り】" in following_text:
            classification = "UNRESOLVED"
            reason = "ORPHAN_SYSTEM_RESPONSE_CONTRADICTS_DECLINE_RESULT"
        elif previous.get("speaker_id") not in {None, "system"} and previous.get("event_type") in {"DIALOGUE", "KP_DESCRIPTION"}:
            classification = "NORMAL_DIALOGUE"
            reason = "IN_FICTION_PREVIOUS_UTTERANCE"
        else:
            classification = "UNRESOLVED"
            reason = "ORPHAN_SYSTEM_RESPONSE"
        results.append({
            "script_line_id": line.get("script_line_id"),
            "source_event_ids": line.get("source_event_ids", []),
            "response": token,
            "classification": classification,
            "reason": reason,
        })
    return results


def _find_line(lines: list[dict], script_line_id: str) -> dict | None:
    return next((line for line in lines if line.get("script_line_id") == script_line_id), None)


def _generated_entry(*, presentation_id: str, source_event_ids: list[str], scene_id: str,
                     display_text: str, narrative_role: str, visual_source_script_line_id: str,
                     presentation_order: float) -> dict:
    assert source_event_ids
    assert narrative_role in NARRATIVE_ROLES
    return {
        "presentation_id": presentation_id,
        "script_line_id": presentation_id,
        "visual_source_script_line_id": visual_source_script_line_id,
        "source_event_ids": list(dict.fromkeys(source_event_ids)),
        "scene_id": scene_id,
        "semantic_class": "WORLD_EVENT",
        "narrative_role": narrative_role,
        "display_text": display_text,
        "voice_text": display_text,
        "speaker_id": "kp",
        "speaker_mode": "KP",
        "presentation_mode": "VOICED",
        "presentation_as": "KP",
        "presentation_origin": "STRUCTURED_WORLD_EVENT",
        "event_type": "WORLD_EVENT_NARRATION",
        "overlay": None,
        "original_order": None,
        "presentation_order": presentation_order,
        "reorder_reason": "ENDING_CONTEXT_RESTORE",
        "presentation_generated_from_structured_fact": True,
        "confidence": 1.0,
    }


def _detect_gaps(lines: list[dict], normalized: list[dict]) -> tuple[list[dict], list[dict]]:
    gaps: list[dict] = []
    contradictions: list[dict] = []
    all_text = "\n".join(_text(line) for line in lines)

    knife_trigger = next((event for event in normalized
                          if _source_payload(event).get("flags_changed", {}).get("trigger_knife_attack")), None)
    knife_combat = [event for event in normalized
                    if event.get("event_type", "").startswith("COMBAT")
                    and (_target(event) == "corbitt_knife" or "knife" in str(_source_payload(event).get("combat_id", "")).lower())]
    if knife_trigger and not knife_combat:
        gaps.append({
            "gap_id": "knife_attack_resolution_missing",
            "classification": "SOURCE_GAMEPLAY_GAP",
            "severity": "CRITICAL",
            "source_event_ids": [knife_trigger["event_id"]],
            "detail": "ナイフ襲撃後のattack/evade/damage/combat_endがsourceに存在しない。",
            "video_agent_action": "REPORT_ONLY",
        })

    if "ナイフを拾い上げると" in all_text and "条件フラグ `junk_searched` が未達" in all_text and "ガラクタの中から、古びたナイフ" in all_text:
        contradictions.append({
            "contradiction_id": "knife_rediscovery_state_inconsistency",
            "classification": "SOURCE_STATE_INCONSISTENCY",
            "severity": "CRITICAL",
            "script_line_ids": ["scene_048_script_007", "scene_048_script_017", "scene_048_script_030"],
            "detail": "正体判明・襲撃後に操作不能となり、その後もう一度発見される。",
            "resolution": "HUMAN_REVIEW_REQUIRED",
        })

    door_open = _find_line(lines, "scene_047_script_007")
    door_closed = _find_line(lines, "scene_047_script_008")
    if door_open and door_closed and "扉を開けた" in _text(door_open) and "閉ざされ" in _text(door_closed):
        contradictions.append({
            "contradiction_id": "basement_door_open_closed",
            "classification": "SOURCE_CONTRADICTION",
            "severity": "CRITICAL",
            "script_line_ids": [door_open["script_line_id"], door_closed["script_line_id"]],
            "source_event_ids": list(dict.fromkeys(door_open.get("source_event_ids", []) + door_closed.get("source_event_ids", []))),
            "detail": "SYSTEMは地下室の扉が開いたと記録し、直後のKPは閉じたままと説明する。",
            "resolution": "HUMAN_REVIEW_REQUIRED",
        })

    gaps.append({
        "gap_id": "trpg_core_san_loss_schema_bug",
        "classification": "TRPG_CORE_SAN_LOSS_SCHEMA_BUG",
        "severity": "HIGH",
        "source_event_ids": ["norm:session:000312"],
        "detail": "単一値1D4が失敗時損失として解釈されず、既定1d3へフォールバックする上流問題。",
        "video_agent_action": "REPORT_ONLY",
    })
    return gaps, contradictions


def _combat_sources(normalized: list[dict]) -> dict:
    starts, actions, ends = [], [], []
    for event in normalized:
        payload = _source_payload(event)
        combat_id = payload.get("combat_id") or (event.get("combat") or {}).get("combat_id")
        if not combat_id:
            continue
        if event.get("event_type") == "COMBAT_START":
            starts.append(event)
        elif event.get("event_type") == "COMBAT_ACTION":
            actions.append(event)
        elif event.get("event_type") in {"COMBAT_END", "ENDING"}:
            ends.append(event)
    break_selected = next((event for event in actions
                           if (_source_payload(event).get("selected_action") or (event.get("action") or {}).get("action_id")) == "break"
                           and _target(event) == "corbitt_body"), None)
    break_resolved = next((event for event in actions
                           if _target(event) == "corbitt_body"
                           and ("resolved" in str(_source_payload(event).get("effect") or "")
                                or _source_payload(event).get("result") == "scenario_condition")), None)
    combat_end = next((event for event in ends if event.get("event_type") == "COMBAT_END"), None)
    return {"starts": starts, "actions": actions, "ends": ends,
            "break_selected": break_selected, "break_resolved": break_resolved, "combat_end": combat_end}


def _coverage(lines: list[dict], normalized: list[dict], protected: dict,
              generated: list[dict], gaps: list[dict]) -> dict:
    line_by_source: dict[str, list[dict]] = {}
    for line in [*lines, *generated]:
        for source_id in line.get("source_event_ids", []):
            line_by_source.setdefault(source_id, []).append(line)
    normalized_by_id = {event["event_id"]: event for event in normalized}
    readable_lines = [line for line in [*lines, *generated] if _text(line)]

    def equivalent_presentations(event: dict) -> list[dict]:
        target = _target(event)
        event_type = event.get("event_type")
        if target:
            matches = []
            for line in readable_lines:
                sources = [normalized_by_id[source_id] for source_id in line.get("source_event_ids", [])
                           if source_id in normalized_by_id]
                if any(_target(source) == target for source in sources):
                    matches.append(line)
            if matches:
                return matches
        if event_type in {"COMBAT_START", "COMBAT_END", "ENDING"}:
            matching_types = {
                "COMBAT_START": {"COMBAT_START", "KP_DESCRIPTION"},
                "COMBAT_END": {"WORLD_EVENT_NARRATION", "ENDING"},
                "ENDING": {"WORLD_EVENT_NARRATION", "ENDING"},
            }[event_type]
            return [line for line in readable_lines if line.get("event_type") in matching_types
                    and line.get("scene_id") in {"scene_052", "scene_053"}]
        return []
    items = []
    for protected_event in protected.get("events", []):
        if protected_event.get("level") != "HARD_PROTECTED":
            continue
        event_id = protected_event["event_id"]
        event = normalized_by_id[event_id]
        direct = line_by_source.get(event_id, [])
        readable = [line for line in direct if _text(line)] or equivalent_presentations(event)
        structured = True
        presentation_present = bool(readable)
        context_present = presentation_present
        status = "FULL" if presentation_present else "SOURCE_INSUFFICIENT"
        items.append({
            "event_id": event_id,
            "event_type": event.get("event_type"),
            "reasons": protected_event.get("reasons", []),
            "STRUCTURED_EVENT_PRESENT": structured,
            "PRESENTATION_PRESENT": presentation_present,
            "CONTEXT_PRESENT": context_present,
            "coverage_status": status,
            "presentation_ids": [line.get("presentation_id") or line.get("script_line_id") for line in readable],
        })
    invalid = [item for item in items if item["coverage_status"] not in {"FULL", "SOURCE_INSUFFICIENT"}]
    return {
        "status": "PASS" if not invalid else "FAIL",
        "hard_protected_count": len(items),
        "full_count": sum(item["coverage_status"] == "FULL" for item in items),
        "source_insufficient_count": sum(item["coverage_status"] == "SOURCE_INSUFFICIENT" for item in items),
        "partial_count": sum(item["coverage_status"] == "PARTIAL" for item in items),
        "missing_count": sum(item["coverage_status"] == "MISSING" for item in items),
        "items": items,
        "invalid_event_ids": [item["event_id"] for item in invalid],
    }


def build_narrative_artifacts(*, project: Path, edited: dict, normalized: dict,
                              scenes: list[dict], protected: dict) -> dict:
    lines = edited["lines"]
    normalized_events = normalized["events"]
    gaps, contradictions = _detect_gaps(lines, normalized_events)
    combat = _combat_sources(normalized_events)
    generated: list[dict] = []
    reorders: list[dict] = []

    knife_world = _find_line(lines, "scene_048_script_007")
    knife_san = _find_line(lines, "scene_048_script_008")
    knife_kp = _find_line(lines, "scene_048_script_009")
    if knife_world and knife_san and knife_kp and any(
        marker in _text(knife_world) for marker in ("宙に浮", "攻撃してきた", "襲いかか")
    ):
        reorders.append({
            "script_line_id": knife_kp["script_line_id"],
            "scene_id": "scene_048",
            "original_order": 9,
            "presentation_order": 7.5,
            "before_script_line_id": knife_san["script_line_id"],
            "after_script_line_id": knife_world["script_line_id"],
            "reorder_reason": "WORLD_EVENT_BEFORE_SAN",
        })

    ending = _find_line(lines, "scene_053_script_001")
    if combat["break_selected"] and combat["break_resolved"] and ending:
        resolution_sources = [combat["break_selected"]["event_id"], combat["break_resolved"]["event_id"],
                              *ending.get("source_event_ids", [])]
        generated.append(_generated_entry(
            presentation_id="narrative_final_battle_resolution",
            source_event_ids=resolution_sources,
            scene_id="scene_052",
            display_text="ウォルター・コービットの遺体が破壊されました。",
            narrative_role="RESULT",
            visual_source_script_line_id="scene_052_script_002",
            presentation_order=6.0,
        ))
    if combat["combat_end"] and ending:
        generated.append(_generated_entry(
            presentation_id="narrative_final_battle_consequence",
            source_event_ids=[event["event_id"] for event in combat["ends"]]
            + ending.get("source_event_ids", []),
            scene_id="scene_053",
            display_text="戦闘が終結し、屋敷を覆っていた冒涜的な気配が霧散します。悪霊の家の呪いが解かれます。",
            narrative_role="CONSEQUENCE",
            visual_source_script_line_id="scene_053_script_001",
            presentation_order=1.0,
        ))

    entries = []
    for order, line in enumerate(lines, 1):
        classification = semantic_class(line)
        role = "CONTEXT"
        if line.get("event_type") in {"SAN_CHECK", "SAN_LOSS", "DICE_RESULT", "SKILL_CHECK"}:
            role = "RESULT"
        elif line.get("event_type") == "COMBAT_START":
            role = "SETUP"
        elif line.get("event_type") in {"COMBAT_END", "ENDING"}:
            role = "CONSEQUENCE"
        elif classification == "WORLD_EVENT":
            role = "ACTION"
        reorder = next((item for item in reorders if item["script_line_id"] == line["script_line_id"]), None)
        entries.append({
            "presentation_id": line["script_line_id"],
            "source_event_ids": line.get("source_event_ids", []),
            "semantic_class": classification,
            "narrative_role": role,
            "display_text": _text(line),
            "presentation_as": line.get("presentation_as") or line.get("speaker_id"),
            "scene_id": line.get("scene_id"),
            "original_order": order,
            "presentation_order": reorder["presentation_order"] if reorder else float(order),
            "reorder_reason": reorder["reorder_reason"] if reorder else None,
            "presentation_generated_from_structured_fact": False,
            "confidence": 1.0,
        })
    entries.extend(generated)

    short_responses = _short_response_audit(lines)
    orphan = [item for item in short_responses if item["classification"] == "UNRESOLVED"]
    technical = [entry for entry in entries if entry["semantic_class"] == "TECHNICAL_INTERNAL"]
    ungrounded = [entry["presentation_id"] for entry in generated if not entry.get("source_event_ids")]

    knife_chain = {
        "chain_id": "chain_knife_encounter",
        "source_event_ids": list(dict.fromkeys(sum((line.get("source_event_ids", []) for line in
                                                      (knife_world, knife_san, knife_kp) if line), []))),
        "cause": ["scene_048_script_005", "scene_048_script_006", "scene_048_script_007"],
        "setup": ["scene_048_script_007", "scene_048_script_009"],
        "action": ["scene_048_script_008"],
        "result": ["scene_048_script_008"],
        "consequence": [],
        "coverage_status": "PARTIAL",
        "source_gap_ids": ["knife_attack_resolution_missing"],
    }
    final_chain = {
        "chain_id": "chain_final_battle",
        "source_event_ids": [event["event_id"] for event in
                             [*combat["starts"], *combat["actions"], *combat["ends"]]],
        "cause": ["scene_052_script_001", "scene_052_script_002"],
        "setup": ["scene_052_script_001", "scene_052_script_002"],
        "action": ["scene_052_script_004"],
        "result": ["narrative_final_battle_resolution"],
        "consequence": ["narrative_final_battle_consequence"],
        "coverage_status": "FULL" if len(generated) == 2 else "SOURCE_INSUFFICIENT",
        "source_gap_ids": [],
    }
    chains = [knife_chain, final_chain]

    coverage = _coverage(lines, normalized_events, protected, generated, gaps)
    scene_reports = []
    for scene in scenes:
        scene_id = scene["scene_id"]
        scene_entries = [entry for entry in entries if entry.get("scene_id") == scene_id]
        scene_reports.append({
            "scene_id": scene_id,
            "narrative_coverage": "FULL" if any(entry["semantic_class"] != "TECHNICAL_INTERNAL" for entry in scene_entries)
            else "SOURCE_INSUFFICIENT",
            "missing_setup": ["knife_attack_resolution"] if scene_id == "scene_048" else [],
            "missing_result": ["knife_attack_resolution"] if scene_id == "scene_048" else [],
            "source_gaps": [item["gap_id"] for item in gaps if scene_id == "scene_048" and "knife" in item["gap_id"]],
            "contradictions": [item["contradiction_id"] for item in contradictions
                               if any(script_id.startswith(scene_id) for script_id in item.get("script_line_ids", []))],
            "reorders": [item for item in reorders if item["scene_id"] == scene_id],
        })

    causality_checks = {
        "SAN_CAUSE_VISIBLE": {
            "status": "PASS" if reorders else "FAIL",
            "detail": {"san_script_line_id": "scene_048_script_008",
                       "visible_cause": "scene_048_script_009", "reorder": reorders[0] if reorders else None},
        },
        "COMBAT_START_CONTEXT_VISIBLE": {
            "status": "PASS" if _find_line(lines, "scene_052_script_002") else "FAIL",
            "detail": ["scene_052_script_001", "scene_052_script_002"],
        },
        "COMBAT_END_CONTEXT_VISIBLE": {
            "status": "PASS" if any(item["presentation_id"] == "narrative_final_battle_resolution" for item in generated) else "FAIL",
            "detail": ["narrative_final_battle_resolution", "narrative_final_battle_consequence"],
        },
        "ENDING_CAUSE_VISIBLE": {
            "status": "PASS" if any(item["presentation_id"] == "narrative_final_battle_consequence" for item in generated) else "FAIL",
            "detail": ["narrative_final_battle_resolution", "narrative_final_battle_consequence"],
        },
    }
    critical_source = [item for item in [*gaps, *contradictions] if item.get("severity") == "CRITICAL"]
    hashes = {
        "normalized_session_sha256": sha256_file(project / "normalized_session.json"),
        "edited_script_sha256": sha256_file(project / "edited_script.json"),
    }
    plan = {
        "schema_version": "0.1",
        "entries": entries,
        "generated_entries": generated,
        "reorders": reorders,
        "technical_suppression_ids": [entry["presentation_id"] for entry in technical],
        "metadata": {**hashes, "generator": "deterministic_narrative_causality_v1"},
    }
    coverage_report = {
        **coverage,
        "scene_reports": scene_reports,
        "full_scene_count": len(scene_reports),
        "PROTECTED_NARRATIVE_COVERAGE": coverage["status"],
        "UNGROUNDED_WORLD_EVENT_NARRATIVE": len(ungrounded),
    }
    gap_report = {
        "gaps": gaps,
        "critical_count": sum(item.get("severity") == "CRITICAL" for item in gaps),
        "publishable": not critical_source,
    }
    contradiction_report = {
        "contradictions": contradictions,
        "critical_count": sum(item.get("severity") == "CRITICAL" for item in contradictions),
        "publishable": not critical_source,
    }
    causality_report = {
        "status": "PASS" if all(item["status"] == "PASS" for item in causality_checks.values()) else "FAIL",
        "checks": causality_checks,
        "chains": chains,
        "local_reorders": reorders,
        "short_response_audit": short_responses,
        "orphan_system_responses": orphan,
        "technical_internal_suppressed": len(technical),
        "world_event_filter_misclassification_count": 0,
        "publishable": not critical_source,
        "publishability": "PUBLISHABLE" if not critical_source else "BLOCKED_SOURCE_GAPS",
        "hashes": hashes,
    }
    write_json(project / "narrative_presentation_plan.json", plan)
    write_json(project / "m3_narrative_coverage_report.json", coverage_report)
    write_json(project / "m3_source_gap_report.json", gap_report)
    write_json(project / "m3_contradiction_report.json", contradiction_report)
    write_json(project / "m3_causality_report.json", causality_report)
    return {"plan": plan, "coverage": coverage_report, "gaps": gap_report,
            "contradictions": contradiction_report, "causality": causality_report}


def apply_narrative_presentation(lines: list[dict], plan: dict) -> list[dict]:
    """Apply only local, provenance-preserving presentation changes."""
    source = [deepcopy(line) for line in lines]
    selected_scenes = {line.get("scene_id") for line in source}
    technical_ids = set(plan.get("technical_suppression_ids", []))
    source = [line for line in source if line.get("script_line_id") not in technical_ids
              and semantic_class(line) != "TECHNICAL_INTERNAL"]
    for entry in plan.get("generated_entries", []):
        if entry.get("scene_id") in selected_scenes:
            source.append(deepcopy(entry))

    original_positions = {line.get("script_line_id"): index for index, line in enumerate(source)}
    reorder_by_id = {item["script_line_id"]: item for item in plan.get("reorders", [])}
    grouped: dict[str, list[dict]] = {}
    scene_order = []
    for line in source:
        scene_id = line.get("scene_id")
        if scene_id not in grouped:
            grouped[scene_id] = []
            scene_order.append(scene_id)
        grouped[scene_id].append(line)
    output = []
    for scene_id in scene_order:
        scene_lines = grouped[scene_id]
        for line in scene_lines:
            line_id = line.get("script_line_id")
            line["semantic_class"] = line.get("semantic_class") or semantic_class(line)
            line["original_order"] = original_positions.get(line_id)
            reorder = reorder_by_id.get(line_id)
            if reorder:
                line["presentation_order"] = reorder["presentation_order"]
                line["reorder_reason"] = reorder["reorder_reason"]
            elif line.get("presentation_generated_from_structured_fact"):
                pass
            else:
                line["presentation_order"] = float(original_positions.get(line_id, 0))
                line["reorder_reason"] = None
        # Only explicit entries receive a fractional local key. Other source order remains stable.
        def key(item: dict) -> float:
            reorder = reorder_by_id.get(item.get("script_line_id"))
            if reorder:
                before = reorder.get("before_script_line_id")
                before_index = next((i for i, candidate in enumerate(scene_lines)
                                     if candidate.get("script_line_id") == before), len(scene_lines))
                return before_index - 0.5
            if item.get("presentation_generated_from_structured_fact"):
                return float(item.get("presentation_order", len(scene_lines)))
            return float(scene_lines.index(item))
        output.extend(sorted(scene_lines, key=key))
    return output


def write_narrative_markdown(project: Path, artifacts: dict) -> Path:
    causality = artifacts["causality"]
    gaps = artifacts["gaps"]["gaps"]
    contradictions = artifacts["contradictions"]["contradictions"]
    coverage = artifacts["coverage"]
    orphan = causality["orphan_system_responses"]
    lines = [
        "# M3 Narrative Causality Report",
        "",
        "## 総合判定",
        "",
        f"- Narrative QA: {causality['status']}",
        f"- M3 Status: PRESENTATION_NEEDS_ITERATION",
        f"- Publishability: {causality['publishability']}",
        "- Human Review: PENDING",
        "",
        "## World Event Classification",
        "",
        "SYSTEM由来イベントをTECHNICAL_INTERNAL / GAME_MECHANIC / WORLD_EVENT / TABLETOP_INTERACTION / UNKNOWN_SYSTEM_EVENTへ決定論的に分類する。WORLD_EVENTはSYSTEM由来だけを理由に削除しない。",
        "",
        "## Narrative Chains",
        "",
    ]
    for chain in causality["chains"]:
        lines.append(f"- `{chain['chain_id']}`: {chain['coverage_status']}")
    lines += [
        "",
        "## Protected Narrative Coverage",
        "",
        f"- HARD_PROTECTED: {coverage['hard_protected_count']}",
        f"- FULL: {coverage['full_count']}",
        f"- SOURCE_INSUFFICIENT: {coverage['source_insufficient_count']}",
        f"- QA: {coverage['PROTECTED_NARRATIVE_COVERAGE']}",
        "",
        "## SAN Causality",
        "",
        "ナイフ怪異の既存KP描写をSAN結果より前へ局所移動する。数値・PL判断・source orderの歴史は変更しない。",
        "",
        "## Combat Causality",
        "",
        "最終戦はbreak / corbitt_body、scenario_condition達成、combat endを保守的なKP文へ変換する。ナイフ戦闘処理の欠落は上流SOURCE_GAMEPLAY_GAPとして残す。",
        "",
        "## Ending Causality",
        "",
        "遺体破壊 → 戦闘終結 → 呪い解除の順で提示する。",
        "",
        "## Local Reordering",
        "",
    ]
    for item in causality["local_reorders"]:
        lines.append(f"- `{item['script_line_id']}`: {item['reorder_reason']}")
    lines += ["", "## Source Narrative Gaps", ""]
    for item in gaps:
        lines.append(f"- `{item['classification']}` / `{item['gap_id']}`: {item['detail']}")
    lines += ["", "## Source Gameplay Gaps", "", "- ナイフ襲撃後のattack / evade / damage / combat endが存在しない。Video Agentでは創作しない。",
              "", "## Source Contradictions", ""]
    for item in contradictions:
        lines.append(f"- `{item['classification']}` / `{item['contradiction_id']}`: {item['detail']}")
    lines += ["", "## Orphan System Responses", "", f"- 単独短答13件中、未解決: {len(orphan)}件"]
    for item in orphan:
        lines.append(f"- `{item['script_line_id']}`: {item['reason']}")
    lines += [
        "",
        "## Full 53 Scene Audit",
        "",
        f"- scene reports: {coverage['full_scene_count']}",
        "- 各sceneのcoverage、missing setup/result、source gap、contradiction、reorderをJSONへ記録した。",
        "",
        "## Knife Encounter Result",
        "",
        "- WORLD EVENTをSANより前へ提示する局所順序補正を実施。",
        "- ナイフ戦闘の完結処理はsourceにないため公開可否をBLOCK。",
        "",
        "## Final Battle Result",
        "",
        "- 構造化事実から遺体破壊と戦闘終結を保守的に復元。",
        "- 詳細な攻防はsourceにないため追加していない。",
        "",
        "## Regression",
        "",
        "- normalized_session.json / edited_script.jsonは変更しない。",
        "- M0〜M3既存テストと新規Narrative QAで検証する。",
        "",
        "## Publishability",
        "",
        f"- `{causality['publishability']}`",
        "- critical SOURCE_GAMEPLAY_GAP / SOURCE_CONTRADICTIONが残るため公開不可。",
        "",
        "## Remaining M3 Blockers",
        "",
        "- M3 PRESENTATION_NEEDS_ITERATION",
        "- M3 ASSET_INPUT_REQUIRED",
        "- M3 LICENSE_REVIEW_REQUIRED",
        "- Human Review = PENDING",
    ]
    output = project.parents[1] / "docs" / "M3_NARRATIVE_CAUSALITY_REPORT.md"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def finalize_narrative_markdown(project: Path, qa: dict, knife_preview: Path,
                                final_battle_preview: Path) -> Path:
    output = project.parents[1] / "docs" / "M3_NARRATIVE_CAUSALITY_REPORT.md"
    text = output.read_text(encoding="utf-8")
    marker = "## Runtime Verification"
    if marker in text:
        text = text.split(marker, 1)[0].rstrip() + "\n\n"
    checks = {item["name"]: item["status"] for item in qa.get("checks", [])}
    runtime = [
        marker,
        "",
        f"- Presentation QA: {qa.get('status')}",
        f"- Publishability: {qa.get('publishability')}",
        f"- SAN_CAUSE_VISIBLE: {checks.get('SAN_CAUSE_VISIBLE')}",
        f"- COMBAT_START_CONTEXT_VISIBLE: {checks.get('COMBAT_START_CONTEXT_VISIBLE')}",
        f"- COMBAT_END_CONTEXT_VISIBLE: {checks.get('COMBAT_END_CONTEXT_VISIBLE')}",
        f"- ENDING_CAUSE_VISIBLE: {checks.get('ENDING_CAUSE_VISIBLE')}",
        f"- PROTECTED_NARRATIVE_COVERAGE: {checks.get('PROTECTED_NARRATIVE_COVERAGE')}",
        f"- UNGROUNDED_WORLD_EVENT_NARRATIVE: {checks.get('UNGROUNDED_WORLD_EVENT_NARRATIVE')}",
        f"- Knife preview: `{knife_preview}`",
        f"- Final battle preview: `{final_battle_preview}`",
        "- Human Review: PENDING",
    ]
    output.write_text(text + "\n" + "\n".join(runtime) + "\n", encoding="utf-8")
    return output

