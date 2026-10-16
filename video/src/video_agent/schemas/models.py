ROLES = frozenset({"KP", "PC", "NPC", "SYSTEM", "UNKNOWN"})
EVENT_TYPES = frozenset({
    "DIALOGUE", "KP_DESCRIPTION", "ACTION_DECLARATION", "SKILL_CHECK",
    "DICE_RESULT", "SAN_CHECK", "SAN_LOSS", "DAMAGE", "HEAL",
    "COMBAT_START", "COMBAT_ACTION", "COMBAT_END", "LOCATION_CHANGE",
    "CLUE_FOUND", "ITEM_GAINED", "ITEM_LOST", "SCENARIO_EVENT",
    "ENDING", "SYSTEM_INTERNAL", "MOVE_ACTION_RESOLVED", "UNKNOWN",
})
ASSET_STATUSES = frozenset({
    "APPROVED", "NONCOMMERCIAL_ONLY", "REQUIRES_CREDIT", "UNKNOWN", "BLOCKED", "TEST_ONLY",
})
VOICE_ENGINES = frozenset({"AQUESTALK", "VOICEVOX", "NONE"})


def empty_event(event_id, source_ids, order):
    return {
        "event_id": event_id,
        "source_event_ids": list(source_ids),
        "cycle": None,
        "turn": None,
        "timestamp_or_order": order,
        "scene_id": None,
        "location": {"location_id": None, "display_name": None},
        "speaker_id": None,
        "actor_id": None,
        "adjudication_id": None,
        "cause_adjudication_id": None,
        "interaction_id": None,
        "event_type": "UNKNOWN",
        "text": None,
        "action": None,
        "dice": None,
        "modifier": None,
        "san": None,
        "combat": None,
        "state_changes": {},
        "metadata": {},
    }
