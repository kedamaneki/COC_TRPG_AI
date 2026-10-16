from __future__ import annotations

from video_agent.presentation.system_filter import is_system_presentation


SHORT_RESPONSES = {
    "yes", "no", "はい", "いいえ", "ok", "cancel", "confirm", "retry", "push",
    "プッシュする", "プッシュしない", "再試行する", "再試行しない", "続行", "中止", "承認", "拒否",
}
HIDE_RESPONSES = {"yes", "no", "はい", "いいえ", "ok", "cancel", "confirm", "承認", "拒否"}
PROMPT_TYPES = {"SYSTEM_INTERNAL", "PUSH_PROMPT", "RETRY_PROMPT", "CONFIRMATION_PROMPT"}
FOLLOWUP_TYPES = {"DICE_ROLL", "DICE_RESULT", "SKILL_CHECK", "SKILL_RESULT", "SAN_CHANGE", "SAN_LOSS",
                  "HP_CHANGE", "SYSTEM_INTERNAL", "SYSTEM_FORCED", "PROGRESS"}


def _text(event: dict) -> str:
    return str(event.get("display_text") or event.get("text") or "").strip()


def _normalized_response(event: dict) -> str:
    return _text(event).strip(" \t\r\n。．.!！?？").lower()


def _explicit_system_prompt(event: dict) -> bool:
    return (event.get("speaker_id") == "system"
            or event.get("role") == "SYSTEM"
            or event.get("event_type") in PROMPT_TYPES
            or event.get("interaction_target") == "SYSTEM")


def _system_followup(event: dict) -> bool:
    return (event.get("event_type") in FOLLOWUP_TYPES
            or event.get("speaker_id") == "system"
            or is_system_presentation(event))


def classify_system_response(events: list[dict], index: int) -> dict:
    current = events[index]
    response = _normalized_response(current)
    if response not in SHORT_RESPONSES:
        return {"is_system_response": False, "action": "KEEP", "confidence": "NONE",
                "evidence": ["NOT_SHORT_RESPONSE"]}
    if current.get("speaker_id") in {None, "system", "kp"}:
        return {"is_system_response": False, "action": "KEEP", "confidence": "NONE",
                "evidence": ["NOT_PC_OR_PL"]}

    previous = events[max(0, index - 3):index]
    following = events[index + 1:index + 3]
    evidence = []
    explicit_target = current.get("interaction_target") == "SYSTEM"
    explicit_prompt = bool(previous and _explicit_system_prompt(previous[-1]))
    adjacent_system_before = bool(previous and is_system_presentation(previous[-1]))
    adjacent_system_after = bool(following and _system_followup(following[0]))
    if explicit_target:
        evidence.append("EXPLICIT_INTERACTION_TARGET_SYSTEM")
    if explicit_prompt:
        evidence.append("ADJACENT_EXPLICIT_SYSTEM_PROMPT")
    if adjacent_system_before:
        evidence.append("ADJACENT_SYSTEM_EVENT_BEFORE")
    if adjacent_system_after:
        evidence.append("ADJACENT_SYSTEM_EVENT_AFTER")

    # Deterministic safe default: an explicit SYSTEM relation/prompt is enough.
    # Otherwise require a system event on both sides of the short response.
    confirmed = explicit_target or explicit_prompt or (adjacent_system_before and adjacent_system_after)
    if not confirmed:
        return {"is_system_response": False, "action": "KEEP", "confidence": "LOW", "evidence": evidence}

    if response in HIDE_RESPONSES:
        action = "HIDE"
    elif response in {"push", "retry", "プッシュする", "再試行する", "続行"} and adjacent_system_after:
        action = "OVERLAY_ONLY"
    else:
        action = "SUBTITLE_ONLY"
    return {"is_system_response": True, "action": action, "confidence": "HIGH",
            "normalized_response": response, "evidence": evidence}


def apply_system_response_filter(events: list[dict]) -> tuple[list[dict], dict]:
    output, candidates = [], []
    for index, event in enumerate(events):
        decision = classify_system_response(events, index)
        if decision["is_system_response"]:
            candidates.append({"script_line_id": event.get("script_line_id"),
                               "source_event_ids": event.get("source_event_ids", []), **decision})
            if decision["action"] == "HIDE":
                continue
            transformed = dict(event)
            transformed["presentation_mode"] = decision["action"]
            transformed["system_response"] = decision
            output.append(transformed)
        else:
            output.append(event)
    return output, {
        "system_response_candidates": len(candidates),
        "system_responses_hidden": sum(item["action"] == "HIDE" for item in candidates),
        "system_responses_subtitle_only": sum(item["action"] == "SUBTITLE_ONLY" for item in candidates),
        "system_responses_overlay_only": sum(item["action"] == "OVERLAY_ONLY" for item in candidates),
        "candidates": candidates,
    }


def required_fixture() -> dict:
    cases = [
        ("SYSTEM Push Yes", [
            {"speaker_id": "system", "role": "SYSTEM", "event_type": "PUSH_PROMPT", "text": "Push?"},
            {"speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "Yes"},
        ], 1, "HIDE"),
        ("SYSTEM Push No", [
            {"speaker_id": "system", "role": "SYSTEM", "event_type": "PUSH_PROMPT", "text": "Push?"},
            {"speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "No"},
        ], 1, "HIDE"),
        ("NPC conversation", [
            {"speaker_id": "npc_01", "role": "NPC", "event_type": "DIALOGUE", "text": "来ますか？"},
            {"speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "はい"},
        ], 1, "KEEP"),
        ("KP conversation", [
            {"speaker_id": "kp", "role": "KP", "event_type": "KP_DESCRIPTION", "text": "本当に扉を開けますか？"},
            {"speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "はい"},
        ], 1, "KEEP"),
    ]
    results = []
    for name, events, index, expected in cases:
        actual = classify_system_response(events, index)
        results.append({"name": name, "expected_action": expected, "actual": actual,
                        "pass": actual["action"] == expected})
    return {"fixture_version": "0.1", "cases": results,
            "false_positive_count": sum(item["name"].endswith("conversation") and item["actual"]["action"] != "KEEP"
                                        for item in results)}
