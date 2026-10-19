from __future__ import annotations

from typing import Any


BASE_PROFILE_ID = "ymm_exact_sakuya_v1"
TUNING_RATES = (120, 115, 110, 105)
TUNING_PROFILE_IDS = {rate: f"sakuya_tune_{rate}_v1" for rate in TUNING_RATES}

# Deliberately non-sequential so the listening order does not reveal the rate.
ANONYMOUS_ASSIGNMENT = {"A": 110, "B": 120, "C": 105, "D": 115}

FIXTURE_LINES = {
    "check": {
        "display_text": "これは、音声設定の確認です。聞こえ方と、話すスピードを確認してください。",
        "synthesis_text": "これは、おんせいせっていの、かくにんです。きこえかたと、はなすすぴーどを、かくにんしてください。",
    },
    "kp_check": {
        "display_text": "では、筋力で判定してください。目標値は55です。",
        "synthesis_text": "では、きんりょくで、はんていしてください。もくひょうちは、ごじゅうごです。",
    },
    "kp_result": {
        "display_text": "力を込めると、古びた板が大きく割れます。",
        "synthesis_text": "ちからをこめると、ふるびたいたが、おおきくわれます。",
    },
}


def validate_tuning_profiles(profiles: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    base = profiles.get(BASE_PROFILE_ID)
    if base is None:
        return ["BASE_PROFILE_MISSING"]
    if base.get("usage_status") != "TUNING_REFERENCE":
        errors.append("BASE_PROFILE_NOT_TUNING_REFERENCE")
    for rate in TUNING_RATES:
        profile = profiles.get(TUNING_PROFILE_IDS[rate])
        if profile is None:
            errors.append(f"CANDIDATE_MISSING:{rate}")
            continue
        required = {
            "base_profile_id": BASE_PROFILE_ID,
            "voice_type": "f1",
            "reading_speed": 105,
            "synthesis_speed": 105,
            "playback_rate_percent": float(rate),
            "source_volume_percent": 50.0,
            "playback_rate_semantics": "PITCH_AND_SPEED_COUPLED",
            "dsp_implementation": "FFMPEG_ASETRATE_THEN_ARESAMPLE",
        }
        for field, expected in required.items():
            if profile.get(field) != expected:
                errors.append(f"CANDIDATE_FIELD_MISMATCH:{rate}:{field}")
    return errors


def resolve_anonymous_selection(profiles: dict[str, dict[str, Any]], manifest: dict[str, Any],
                                label: str) -> tuple[str, int]:
    mapping = manifest.get("mapping")
    profile_by_rate = manifest.get("profile_by_rate")
    if not isinstance(mapping, dict) or set(mapping) != {"A", "B", "C", "D"}:
        raise ValueError("SAKUYA_ANONYMOUS_MAPPING_INVALID:LABELS")
    rates = [int(value) for value in mapping.values()]
    if len(set(rates)) != 4 or set(rates) != set(TUNING_RATES):
        raise ValueError("SAKUYA_ANONYMOUS_MAPPING_INVALID:RATES")
    if label not in mapping or not isinstance(profile_by_rate, dict):
        raise ValueError("SAKUYA_ANONYMOUS_MAPPING_INVALID:SELECTION")
    rate = int(mapping[label])
    profile_id = profile_by_rate.get(str(rate))
    profile = profiles.get(profile_id)
    if profile is None or float(profile.get("playback_rate_percent", -1)) != float(rate):
        raise ValueError("SAKUYA_ANONYMOUS_MAPPING_INVALID:PROFILE")
    return profile_id, rate


def validate_approved_selection(profiles: dict[str, dict[str, Any]], manifest: dict[str, Any],
                                label: str = "A") -> list[str]:
    errors = validate_tuning_profiles(profiles)
    try:
        selected_id, _ = resolve_anonymous_selection(profiles, manifest, label)
    except ValueError as exc:
        return [*errors, str(exc)]
    for rate, profile_id in TUNING_PROFILE_IDS.items():
        profile = profiles[profile_id]
        selected = profile_id == selected_id
        expected_status = "APPROVED" if selected else "NOT_SELECTED"
        if profile.get("usage_status") != expected_status:
            errors.append(f"SELECTION_USAGE_STATUS_MISMATCH:{rate}")
        if profile.get("human_review_status") != expected_status:
            errors.append(f"SELECTION_REVIEW_STATUS_MISMATCH:{rate}")
        if bool(profile.get("auto_use")) != selected:
            errors.append(f"SELECTION_AUTO_USE_MISMATCH:{rate}")
    return errors

