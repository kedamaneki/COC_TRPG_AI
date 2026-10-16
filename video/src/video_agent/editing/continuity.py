from __future__ import annotations


def build_continuity_report(events: list[dict], plan_by_id: dict[str, dict], dependencies: list[dict], protected: dict[str, dict]) -> dict:
    missing_context = []
    for dependency in dependencies:
        source_plan = plan_by_id[dependency["source_event_id"]]
        dependent_plan = plan_by_id[dependency["dependent_event_id"]]
        if source_plan["content_decision"] == "CUT" and dependent_plan["content_decision"] != "CUT":
            missing_context.append(dependency)
    missing_clue = [event["event_id"] for event in events
                    if event["event_type"] == "CLUE_FOUND" and plan_by_id[event["event_id"]]["content_decision"] == "CUT"]
    missing_item = [event["event_id"] for event in events
                    if event["event_type"] == "ITEM_GAINED" and plan_by_id[event["event_id"]]["content_decision"] == "CUT"]
    location = [event["event_id"] for event in events
                if event["event_type"] == "LOCATION_CHANGE" and plan_by_id[event["event_id"]]["content_decision"] == "CUT"]
    combat_start = [event for event in events if event["event_type"] == "COMBAT_START"]
    combat_end = [event for event in events if event["event_type"] == "COMBAT_END"]
    broken_combat = []
    if combat_start and any(plan_by_id[event["event_id"]]["content_decision"] == "CUT" for event in combat_start):
        broken_combat.append("COMBAT_START_CUT")
    if combat_end and any(plan_by_id[event["event_id"]]["content_decision"] == "CUT" for event in combat_end):
        broken_combat.append("COMBAT_END_CUT")
    endings = [event for event in events if event["event_type"] == "ENDING"]
    broken_ending = [event["event_id"] for event in endings if plan_by_id[event["event_id"]]["content_decision"] == "CUT"]
    return {
        "missing_context": missing_context, "orphan_reference": [],
        "unexplained_location_change": location, "missing_item_origin": missing_item,
        "missing_clue_origin": missing_clue, "broken_combat_context": broken_combat,
        "broken_ending_context": broken_ending,
        "status": "PASS" if not (missing_context or location or missing_item or missing_clue or broken_combat or broken_ending) else "FAIL",
    }
