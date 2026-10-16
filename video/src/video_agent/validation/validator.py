import re

from video_agent import SCHEMA_VERSION
from video_agent.schemas.models import ASSET_STATUSES, EVENT_TYPES, ROLES, VOICE_ENGINES


COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}(?:[0-9A-Fa-f]{2})?$")


def _issue(level, code, path, message):
    return {"level": level, "code": code, "path": path, "message": message}


def validate_session(session):
    issues = []
    if session.get("schema_version") != SCHEMA_VERSION:
        issues.append(_issue("ERROR", "UNKNOWN_SCHEMA_VERSION", "schema_version", "unsupported schema version"))
    participant_ids = set()
    for index, participant in enumerate(session.get("participants") or []):
        pid = participant.get("participant_id")
        if not pid:
            issues.append(_issue("ERROR", "MISSING_PARTICIPANT_ID", f"participants[{index}]", "participant_id is required"))
        elif pid in participant_ids:
            issues.append(_issue("ERROR", "DUPLICATE_PARTICIPANT", f"participants[{index}]", str(pid)))
        participant_ids.add(pid)
        if participant.get("role") not in ROLES:
            issues.append(_issue("ERROR", "INVALID_ROLE", f"participants[{index}].role", str(participant.get("role"))))
    event_ids = set()
    for index, event in enumerate(session.get("events") or []):
        eid = event.get("event_id")
        path = f"events[{index}]"
        if not eid:
            issues.append(_issue("ERROR", "MISSING_EVENT_ID", path, "event_id is required"))
        elif eid in event_ids:
            issues.append(_issue("ERROR", "DUPLICATE_EVENT_ID", path, str(eid)))
        event_ids.add(eid)
        if not event.get("source_event_ids"):
            issues.append(_issue("ERROR", "MISSING_SOURCE_EVENT_ID", path, "provenance is required"))
        if event.get("event_type") not in EVENT_TYPES:
            issues.append(_issue("ERROR", "INVALID_EVENT_TYPE", path, str(event.get("event_type"))))
        if "UNKNOWN_SPEAKER" in ((event.get("metadata") or {}).get("validation_warnings") or []):
            issues.append(_issue("WARNING", "UNKNOWN_SPEAKER", f"{path}.speaker_id", "speaker is not present in source data"))
        for key in ("speaker_id", "actor_id"):
            value = event.get(key)
            if value and value not in participant_ids:
                issues.append(_issue("WARNING", "MISSING_PARTICIPANT", f"{path}.{key}", str(value)))
    return issues


def validate_profiles(profiles):
    issues = []
    ids = {
        category: {str(x.get(category[:-1] + "_id") or x.get("character_id")) for x in values}
        for category, values in profiles.items()
    }
    for index, voice in enumerate(profiles.get("voices") or []):
        if voice.get("engine") not in VOICE_ENGINES:
            issues.append(_issue("ERROR", "MALFORMED_VOICE_PROFILE", f"voices[{index}].engine", str(voice.get("engine"))))
        if voice.get("engine") == "AQUESTALK" and not voice.get("voice_type"):
            issues.append(_issue("ERROR", "MALFORMED_VOICE_PROFILE", f"voices[{index}]", "voice_type required"))
    for index, subtitle in enumerate(profiles.get("subtitles") or []):
        colors = [subtitle.get("text_color")] + [x.get("color") for x in subtitle.get("outlines") or []]
        for color in colors:
            if color and not COLOR_RE.match(str(color)):
                issues.append(_issue("ERROR", "MALFORMED_COLOR", f"subtitles[{index}]", str(color)))
    voice_ids = {str(x.get("voice_profile_id")) for x in profiles.get("voices") or []}
    subtitle_ids = {str(x.get("subtitle_profile_id")) for x in profiles.get("subtitles") or []}
    portrait_ids = {str(x.get("portrait_profile_id")) for x in profiles.get("portraits") or []}
    for index, character in enumerate(profiles.get("characters") or []):
        for field, valid in (("voice_profile_id", voice_ids), ("subtitle_profile_id", subtitle_ids), ("portrait_profile_id", portrait_ids)):
            ref = character.get(field)
            if ref not in valid:
                issues.append(_issue("ERROR", "INVALID_PROFILE_REFERENCE", f"characters[{index}].{field}", str(ref)))
    return issues


def validate_manifest(manifest):
    issues, seen = [], set()
    for index, asset in enumerate(manifest.get("assets") or []):
        aid = asset.get("asset_id")
        if not aid or aid in seen:
            issues.append(_issue("ERROR", "INVALID_ASSET_ID", f"assets[{index}]", str(aid)))
        seen.add(aid)
        if asset.get("status") not in ASSET_STATUSES:
            issues.append(_issue("ERROR", "INVALID_ASSET_STATUS", f"assets[{index}].status", str(asset.get("status"))))
        if asset.get("status") == "UNKNOWN":
            issues.append(_issue("WARNING", "UNKNOWN_ASSET_LICENSE", f"assets[{index}]", str(aid)))
    for index, ref in enumerate(manifest.get("references") or []):
        if ref not in seen:
            issues.append(_issue("ERROR", "NONEXISTENT_ASSET_ID", f"references[{index}]", str(ref)))
    return issues


def validate_all(session, profiles=None, manifest=None):
    issues = validate_session(session)
    if profiles is not None:
        issues.extend(validate_profiles(profiles))
    if manifest is not None:
        issues.extend(validate_manifest(manifest))
    errors = [x for x in issues if x["level"] == "ERROR"]
    warnings = [x for x in issues if x["level"] == "WARNING"]
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "warnings": warnings}
