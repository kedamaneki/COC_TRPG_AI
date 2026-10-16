from __future__ import annotations

import re
from copy import deepcopy


SHORT_RESPONSES = {
    "yes", "no", "はい", "いいえ", "ok", "cancel", "confirm", "retry", "push",
    "プッシュする", "プッシュしない", "再試行する", "再試行しない", "続行", "中止", "承認", "拒否",
}
PROMPT_TYPES = {"PUSH_PROMPT", "RETRY_PROMPT", "CONFIRMATION_PROMPT"}
TECHNICAL_MARKERS = (
    "api", "checkpoint", "resume", "cache", "debug", "provider", "token", "llm", "worker", "exception",
)
INTERNAL_MARKERS = ("flag", "state machine", "availability", "route selection", "progress confirmation")


def _text(event: dict) -> str:
    return str(event.get("display_text") or event.get("text") or "").strip()


def _response_token(event: dict) -> str:
    return _text(event).strip(" \t\r\n。．.!！?？").lower()


def _is_system_prompt(event: dict) -> bool:
    return bool(
        event.get("speaker_id") == "system"
        or event.get("role") == "SYSTEM"
        or event.get("event_type") in PROMPT_TYPES
        or event.get("interaction_target") == "SYSTEM"
    )


def classify_system_interaction(event: dict) -> dict:
    """Classify a SYSTEM prompt without treating ordinary KP/NPC dialogue as SYSTEM."""
    if not _is_system_prompt(event):
        return {"classification": "NOT_SYSTEM_INTERACTION", "interaction_type": None}
    # Iteration 3's structured numeric whitelist remains a separate presentation path.
    # Such events are SYSTEM output, but they are not SYSTEM prompts awaiting a response.
    if event.get("overlay") and event.get("event_type") in {
        "DICE_RESULT", "SKILL_CHECK", "SKILL_RESULT", "SAN_CHANGE", "SAN_LOSS", "HP_CHANGE",
    }:
        return {"classification": "NOT_SYSTEM_INTERACTION", "interaction_type": None}
    lowered = _text(event).lower()
    if any(marker in lowered for marker in TECHNICAL_MARKERS):
        return {"classification": "TECHNICAL_SYSTEM_INTERACTION", "interaction_type": None}
    if any(marker in lowered for marker in INTERNAL_MARKERS) or event.get("event_type") == "SYSTEM_INTERNAL":
        return {"classification": "INTERNAL_SYSTEM_INTERACTION", "interaction_type": None}
    if event.get("event_type") == "PUSH_PROMPT" or "push" in lowered or "プッシュ" in lowered:
        return {"classification": "TABLETOP_INTERACTION", "interaction_type": "PUSH_CONFIRMATION"}
    if event.get("event_type") == "RETRY_PROMPT" or "retry" in lowered or "再試行" in lowered:
        return {"classification": "TABLETOP_INTERACTION", "interaction_type": "RETRY_CONFIRMATION"}
    if any(marker in lowered for marker in ("which", "どちら", "選び", "choice")):
        return {"classification": "TABLETOP_INTERACTION", "interaction_type": "CHOICE_CONFIRMATION"}
    if any(marker in lowered for marker in ("continue", "続行", "続け")):
        return {"classification": "TABLETOP_INTERACTION", "interaction_type": "CONTINUE_CONFIRMATION"}
    if event.get("event_type") == "CONFIRMATION_PROMPT" or any(
        marker in lowered for marker in ("confirm", "しますか", "使用しますか", "開けますか")
    ):
        return {"classification": "TABLETOP_INTERACTION", "interaction_type": "ACTION_CONFIRMATION"}
    return {"classification": "UNKNOWN_SYSTEM_INTERACTION", "interaction_type": None}


def _naturalize_prompt(text: str, interaction_type: str) -> str:
    cleaned = re.sub(r"^\s*(?:system|システム)\s*[:：]\s*", "", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*\[\s*yes\s*/\s*no\s*\]\s*", "", cleaned, flags=re.IGNORECASE).strip()
    exact = cleaned.lower().strip(" ?？")
    if interaction_type == "PUSH_CONFIRMATION" and exact == "push":
        return "プッシュしますか？"
    if interaction_type == "RETRY_CONFIRMATION" and exact == "retry":
        return "再試行しますか？"
    return cleaned


def _implicit_confirmation(previous: dict, response: dict, following: dict) -> dict | None:
    """Recover a missing tabletop prompt only from explicit outcome facts around the response."""
    if _response_token(response) not in SHORT_RESPONSES:
        return None
    if response.get("speaker_id") in {None, "system", "kp"}:
        return None
    before_type = previous.get("event_type")
    after_text = _text(following)
    if before_type not in {"DICE_RESULT", "SKILL_CHECK", "SKILL_RESULT"}:
        return None
    luck = re.search(r"【幸運消費】.*?幸運を\s*(\d+)\s*消費", after_text)
    if luck:
        amount = int(luck.group(1))
        return {
            "classification": "TABLETOP_INTERACTION",
            "interaction_type": "ACTION_CONFIRMATION",
            "prompt_text": f"幸運を{amount}ポイント消費して成功にしますか？",
            "grounding": "FOLLOWUP_EXPLICIT_LUCK_SPEND",
            "grounding_source_event_ids": list(following.get("source_event_ids") or []),
        }
    if re.search(r"【プッシュ(?:方針|実行|成功|失敗|開始)】", after_text):
        return {
            "classification": "TABLETOP_INTERACTION",
            "interaction_type": "PUSH_CONFIRMATION",
            "prompt_text": "プッシュしますか？",
            "grounding": "FOLLOWUP_EXPLICIT_PUSH",
            "grounding_source_event_ids": list(following.get("source_event_ids") or []),
        }
    return None


def _as_kp_prompt(prompt: dict, interaction_id: str, interaction_type: str, display_text: str,
                  response: dict, grounding: str, grounding_ids: list[str]) -> dict:
    source_ids = list(dict.fromkeys((prompt.get("source_event_ids") or []) + grounding_ids))
    base_id = response.get("script_line_id") or prompt.get("script_line_id") or interaction_id
    return {
        "script_line_id": f"{base_id}__system_prompt",
        "visual_source_script_line_id": response.get("script_line_id") or prompt.get("script_line_id"),
        "scene_id": response.get("scene_id") or prompt.get("scene_id"),
        "source_event_ids": source_ids,
        "speaker_id": "kp",
        "speaker_mode": "KP",
        "event_type": "SYSTEM_INTERACTION_PROMPT",
        "presentation_mode": "VOICED",
        "display_text": display_text,
        "voice_text": display_text,
        "overlay": None,
        "presentation_origin": "SYSTEM_PROMPT",
        "presentation_as": "KP",
        "system_interaction_id": interaction_id,
        "interaction_type": interaction_type,
        "prompt_grounding": grounding,
        "prompt_grounding_source_event_ids": grounding_ids,
    }


def _as_pl_response(response: dict, interaction_id: str, interaction_type: str,
                    pc_to_player: dict[str, str]) -> dict:
    transformed = deepcopy(response)
    pc_id = response.get("pc_id") or response.get("speaker_id")
    transformed.update({
        "speaker_mode": "PL",
        "pc_id": pc_id,
        "player_id": response.get("player_id") or pc_to_player.get(pc_id),
        "presentation_mode": "VOICED",
        "presentation_origin": "SYSTEM_RESPONSE",
        "presentation_as": "PL",
        "system_interaction_id": interaction_id,
        "interaction_type": interaction_type,
    })
    return transformed


def resolve_system_interactions(events: list[dict], pc_to_player: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    pc_to_player = pc_to_player or {}
    output: list[dict] = []
    pairs: list[dict] = []
    warnings: list[dict] = []
    hidden_technical = 0
    used: set[int] = set()
    counter = 0

    for index, event in enumerate(events):
        if index in used:
            continue
        classification = classify_system_interaction(event)
        if classification["classification"] in {"TECHNICAL_SYSTEM_INTERACTION", "INTERNAL_SYSTEM_INTERACTION"}:
            hidden_technical += 1
            used.add(index)
            continue
        if classification["classification"] == "UNKNOWN_SYSTEM_INTERACTION":
            warnings.append({"code": "AMBIGUOUS_SYSTEM_INTERACTION", "script_line_id": event.get("script_line_id")})
            used.add(index)
            continue
        if classification["classification"] == "TABLETOP_INTERACTION":
            response_index = index + 1
            if response_index >= len(events) or _response_token(events[response_index]) not in SHORT_RESPONSES:
                warnings.append({"code": "AMBIGUOUS_SYSTEM_INTERACTION", "script_line_id": event.get("script_line_id")})
                output.append(event)
                used.add(index)
                continue
            response = events[response_index]
            counter += 1
            interaction_id = f"si_{counter:03d}"
            prompt_text = _naturalize_prompt(_text(event), classification["interaction_type"])
            prompt = _as_kp_prompt(event, interaction_id, classification["interaction_type"], prompt_text,
                                   response, "EXPLICIT_SYSTEM_PROMPT", list(event.get("source_event_ids") or []))
            output.extend([prompt, _as_pl_response(response, interaction_id, classification["interaction_type"], pc_to_player)])
            used.update({index, response_index})
            pairs.append({
                "system_interaction_id": interaction_id,
                "prompt_script_line_id": prompt["script_line_id"],
                "response_script_line_id": response.get("script_line_id"),
                "interaction_type": classification["interaction_type"],
                "classification": "TABLETOP_INTERACTION",
                "grounding": "EXPLICIT_SYSTEM_PROMPT",
            })
            continue

        implicit = None
        if 0 < index < len(events) - 1:
            implicit = _implicit_confirmation(events[index - 1], event, events[index + 1])
        if implicit:
            counter += 1
            interaction_id = f"si_{counter:03d}"
            grounding_ids = implicit["grounding_source_event_ids"]
            synthetic_source = {"source_event_ids": grounding_ids, "scene_id": event.get("scene_id")}
            prompt = _as_kp_prompt(synthetic_source, interaction_id, implicit["interaction_type"],
                                   implicit["prompt_text"], event, implicit["grounding"], grounding_ids)
            output.extend([prompt, _as_pl_response(event, interaction_id, implicit["interaction_type"], pc_to_player)])
            used.add(index)
            pairs.append({
                "system_interaction_id": interaction_id,
                "prompt_script_line_id": prompt["script_line_id"],
                "response_script_line_id": event.get("script_line_id"),
                "interaction_type": implicit["interaction_type"],
                "classification": "TABLETOP_INTERACTION",
                "grounding": implicit["grounding"],
            })
            continue

        output.append(event)
        used.add(index)

    report = {
        "tabletop_interactions_detected": len(pairs),
        "tabletop_interactions_presented": len(pairs),
        "technical_interactions_hidden": hidden_technical,
        "prompt_response_pairs": len(pairs),
        "ambiguous_pairs": sum(item["code"] == "AMBIGUOUS_SYSTEM_INTERACTION" for item in warnings),
        "pl_voice_fallback_count": 0,
        "ungrounded_kp_prompt_count": sum(not item.get("grounding") for item in pairs),
        "pairs": pairs,
        "warnings": warnings,
    }
    return output, report


def required_fixture() -> dict:
    cases = [
        ("Push Yes", [
            {"script_line_id": "p", "source_event_ids": ["evt:p"], "speaker_id": "system", "role": "SYSTEM", "event_type": "PUSH_PROMPT", "text": "Push? [yes/no]"},
            {"script_line_id": "r", "source_event_ids": ["evt:r"], "speaker_id": "pc_02", "event_type": "DIALOGUE", "text": "Yes", "display_text": "Yes"},
        ], ["KP", "PL"], ["プッシュしますか？", "Yes"]),
        ("Retry No", [
            {"script_line_id": "p", "source_event_ids": ["evt:p"], "speaker_id": "system", "role": "SYSTEM", "event_type": "RETRY_PROMPT", "text": "Retry?"},
            {"script_line_id": "r", "source_event_ids": ["evt:r"], "speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "No", "display_text": "No"},
        ], ["KP", "PL"], ["再試行しますか？", "No"]),
        ("Technical checkpoint", [
            {"script_line_id": "t", "source_event_ids": ["evt:t"], "speaker_id": "system", "role": "SYSTEM", "event_type": "CONFIRMATION_PROMPT", "text": "checkpoint resume?"},
        ], [], []),
        ("NPC dialogue", [
            {"script_line_id": "n", "source_event_ids": ["evt:n"], "speaker_id": "npc", "role": "NPC", "event_type": "DIALOGUE", "text": "一緒に来ますか？", "display_text": "一緒に来ますか？"},
            {"script_line_id": "r", "source_event_ids": ["evt:r"], "speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "はい", "display_text": "はい"},
        ], [None, None], ["一緒に来ますか？", "はい"]),
        ("KP dialogue", [
            {"script_line_id": "k", "source_event_ids": ["evt:k"], "speaker_id": "kp", "role": "KP", "event_type": "KP_DESCRIPTION", "text": "本当に開けますか？", "display_text": "本当に開けますか？"},
            {"script_line_id": "r", "source_event_ids": ["evt:r"], "speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "はい", "display_text": "はい"},
        ], [None, None], ["本当に開けますか？", "はい"]),
        ("Ambiguous", [
            {"script_line_id": "u", "source_event_ids": ["evt:u"], "speaker_id": "system", "role": "SYSTEM", "event_type": "DIALOGUE", "text": "Proceed?"},
            {"script_line_id": "r", "source_event_ids": ["evt:r"], "speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "Yes", "display_text": "Yes"},
        ], [None], ["Yes"]),
    ]
    results = []
    for name, source, expected_as, expected_text in cases:
        transformed, report = resolve_system_interactions(source, {"pc_01": "player_reimu", "pc_02": "player_marisa"})
        actual_as = [item.get("presentation_as") for item in transformed]
        actual_text = [_text(item) for item in transformed]
        results.append({
            "name": name,
            "expected_presentation_as": expected_as,
            "actual_presentation_as": actual_as,
            "expected_text": expected_text,
            "actual_text": actual_text,
            "report": report,
            "pass": actual_as == expected_as and actual_text == expected_text,
        })
    return {"fixture_version": "0.1", "cases": results}
