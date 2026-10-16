CONTENT_DECISIONS = frozenset({"KEEP", "COMPRESS", "CUT"})
PRESENTATION_MODES = frozenset({"VOICED", "SUBTITLE_ONLY", "OVERLAY_ONLY", "SILENT_VISUAL", "NONE"})
TEXT_TREATMENTS = frozenset({"VERBATIM", "TRIM_REDUNDANCY", "LIGHT_NORMALIZE", "COMPRESSED", "NONE"})
PROTECTION_LEVELS = frozenset({"HARD_PROTECTED", "SOFT_PROTECTED", "NORMAL"})


def safe_default(event: dict) -> dict:
    return {
        "source_event_id": event["event_id"], "content_decision": "KEEP",
        "presentation_mode": "VOICED", "text_treatment": "VERBATIM",
        "confidence": 0.0, "reason": "INVALID_PROVIDER_OUTPUT_SAFE_DEFAULT",
    }


def validate_provider_decision(value: dict, supported_ids: set[str]) -> bool:
    return (
        isinstance(value, dict)
        and value.get("source_event_id") in supported_ids
        and value.get("content_decision") in CONTENT_DECISIONS
        and value.get("presentation_mode") in PRESENTATION_MODES
        and value.get("text_treatment") in TEXT_TREATMENTS
        and isinstance(value.get("confidence"), (int, float))
        and 0 <= value["confidence"] <= 1
        and isinstance(value.get("reason"), str)
    )
