from __future__ import annotations


BOUNDARY_TYPES = {"LOCATION_CHANGE", "COMBAT_START", "COMBAT_END", "ENDING"}


def scene_type(events: list[dict], number: int) -> str:
    types = {event["event_type"] for event in events}
    if "ENDING" in types:
        return "ENDING"
    if types & {"COMBAT_START", "COMBAT_ACTION", "COMBAT_END"}:
        return "COMBAT"
    if types & {"SAN_CHECK", "SAN_LOSS"}:
        return "SAN_SEQUENCE"
    if types & {"DICE_RESULT", "SKILL_CHECK"}:
        return "SKILL_SEQUENCE"
    if "LOCATION_CHANGE" in types:
        return "TRAVEL"
    if number == 1:
        return "INTRO"
    if "CLUE_FOUND" in types:
        return "INVESTIGATION"
    if "DIALOGUE" in types:
        return "ROLEPLAY"
    return "OTHER"


def segment_events(events: list[dict], protected: dict[str, dict]) -> list[dict]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    for event in events:
        boundary = event["event_type"] in BOUNDARY_TYPES
        if current and boundary:
            groups.append(current)
            current = []
        current.append(event)
        if event["event_type"] in {"COMBAT_END", "ENDING"}:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    scenes = []
    for number, group in enumerate(groups, 1):
        participants = sorted({value for event in group for value in (event.get("speaker_id"), event.get("actor_id")) if value})
        locations = [(event.get("location") or {}).get("location_id") for event in group]
        location = next((value for value in locations if value), None)
        weight = sum({"HARD_PROTECTED": 2.0, "SOFT_PROTECTED": 0.8, "NORMAL": 0.05}[protected[event["event_id"]]["level"]] for event in group)
        scenes.append({
            "scene_id": f"scene_{number:03d}", "source_event_ids": [event["event_id"] for event in group],
            "location_id": location, "participants": participants, "scene_type": scene_type(group, number),
            "start_event_id": group[0]["event_id"], "end_event_id": group[-1]["event_id"],
            "importance": round(min(1.0, weight / max(2.0, len(group) * 0.25)), 3),
        })
    return scenes
