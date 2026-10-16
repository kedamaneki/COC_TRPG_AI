from __future__ import annotations


HARD_TYPES = {"ENDING", "COMBAT_START", "COMBAT_END", "DAMAGE", "CLUE_FOUND"}
SOFT_TYPES = {"DICE_RESULT", "SKILL_CHECK", "SAN_CHECK", "SAN_LOSS", "COMBAT_ACTION", "LOCATION_CHANGE", "ITEM_GAINED", "ITEM_LOST"}
TECHNICAL_STATE_KEYS = ("turn_", "stall_", "visit_", "progress_", "available_", "action_")


def meaningful_state_changes(event: dict) -> list[str]:
    keys = []
    for key, change in (event.get("state_changes") or {}).items():
        if key.startswith(TECHNICAL_STATE_KEYS):
            continue
        if isinstance(change, dict) and change.get("before") != change.get("after"):
            keys.append(key)
    return sorted(keys)


def detect_protected_events(events: list[dict]) -> tuple[dict[str, dict], list[dict]]:
    protected = {}
    for event in events:
        event_type = event["event_type"]
        state_keys = meaningful_state_changes(event)
        if event_type in HARD_TYPES or state_keys:
            level = "HARD_PROTECTED"
        elif event_type in SOFT_TYPES:
            level = "SOFT_PROTECTED"
        else:
            level = "NORMAL"
        reasons = []
        if event_type in HARD_TYPES | SOFT_TYPES:
            reasons.append(event_type)
        if state_keys:
            reasons.append("SCENARIO_STATE_CHANGE:" + ",".join(state_keys))
        protected[event["event_id"]] = {"event_id": event["event_id"], "level": level, "reasons": reasons}

    dependencies = []
    by_stream: dict[str, list[dict]] = {}
    for event in events:
        by_stream.setdefault(event.get("metadata", {}).get("source_stream", "unknown"), []).append(event)
    for stream_events in by_stream.values():
        for index, event in enumerate(stream_events):
            relation = None
            if meaningful_state_changes(event):
                relation = "STATE_CHANGE_CONTEXT"
            elif event["event_type"] == "LOCATION_CHANGE":
                relation = "LOCATION_CONTEXT"
            elif event["event_type"] == "CLUE_FOUND":
                relation = "CLUE_CONTEXT"
            elif event["event_type"] == "ITEM_GAINED":
                relation = "ITEM_CONTEXT"
            elif event["event_type"] == "COMBAT_START":
                relation = "COMBAT_CONTEXT"
            if relation:
                dependent = next((candidate for candidate in stream_events[index + 1:] if candidate["event_type"] != "SYSTEM_INTERNAL"), None)
                if dependent:
                    dependencies.append({
                        "source_event_id": event["event_id"], "dependent_event_id": dependent["event_id"],
                        "relation": relation, "origin": "DETERMINISTIC", "confidence": 0.8,
                    })
    return protected, dependencies
