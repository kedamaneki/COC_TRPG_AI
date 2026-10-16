from __future__ import annotations


ALLOWED_SYSTEM_EVENT_TYPES = {
    "DICE_ROLL",
    "DICE_RESULT",
    "SKILL_CHECK",
    "SKILL_RESULT",
    "SAN_CHANGE",
    "SAN_CHECK",
    "SAN_LOSS",
    "HP_CHANGE",
    "HP_LOSS",
    "HP_GAIN",
}

SUPPRESSED_SYSTEM_EVENT_TYPES = {
    "AUTO_SUCCESS",
    "NO_ROLL",
    "LOCATION_CHANGE",
    "LOCATION_INTERNAL_MOVE",
    "FLAG_CHANGE",
    "TURN",
    "CYCLE",
    "PROGRESS",
    "AVAILABILITY",
    "INTERNAL_STATE",
    "SYSTEM_FORCED",
    "DEBUG",
    "TECHNICAL_METADATA",
}


def is_system_presentation(line: dict) -> bool:
    text = str(line.get("display_text") or line.get("text") or "").lstrip()
    return (line.get("speaker_id") == "system"
            or line.get("event_type") in ALLOWED_SYSTEM_EVENT_TYPES | SUPPRESSED_SYSTEM_EVENT_TYPES
            or text.startswith("システム:"))


def system_presentation_decision(line: dict) -> dict:
    """Whitelist system information that is useful to replay viewers."""
    event_type = str(line.get("event_type") or "INTERNAL_STATE")
    overlay_type = str((line.get("overlay") or {}).get("type") or "")
    if not is_system_presentation(line):
        return {"is_system": False, "allowed": True, "presentation_type": None, "reason": "NOT_SYSTEM"}
    if event_type in ALLOWED_SYSTEM_EVENT_TYPES:
        if not line.get("overlay") and line.get("presentation_mode") in {"OVERLAY_ONLY", "SUBTITLE_ONLY"}:
            return {"is_system": True, "allowed": False, "presentation_type": event_type,
                    "reason": "WHITELIST_REQUIRES_STRUCTURED_OVERLAY"}
        presentation_type = {
            "DICE_RESULT": "SKILL_RESULT",
            "SKILL_CHECK": "SKILL_RESULT",
            "SAN_CHECK": "SAN_CHANGE",
            "SAN_LOSS": "SAN_CHANGE",
            "HP_LOSS": "HP_CHANGE",
            "HP_GAIN": "HP_CHANGE",
        }.get(event_type, event_type)
        return {"is_system": True, "allowed": True, "presentation_type": presentation_type,
                "reason": "WHITELIST_EVENT"}
    if line.get("viewer_essential_status_change") is True and overlay_type == "STATUS_CHANGE":
        return {"is_system": True, "allowed": True, "presentation_type": "STATUS_CHANGE",
                "reason": "EXPLICIT_VIEWER_ESSENTIAL_STATUS"}
    return {"is_system": True, "allowed": False, "presentation_type": event_type,
            "reason": "NOT_IN_PRESENTATION_WHITELIST"}
