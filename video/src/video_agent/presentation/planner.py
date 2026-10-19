from __future__ import annotations

import re

from video_agent.assets.classification import semantic_lookup
from video_agent.presentation.assets import resolve_background, resolve_expression


def semantic_asset_candidates(index: dict, category: str, semantic: str, *, automatic: bool = True) -> list[str]:
    """Resolve Planner candidates by semantic meaning, never by filename.

    Automatic lookup reads only the precomputed eligible branch.  The index
    builder places an asset there only after both approval gates and auto_use.
    """
    return semantic_lookup(index, category, semantic, automatic=automatic)


def bgm_category(scene_type: str) -> str:
    return {
        "INTRO": "CALM", "ROLEPLAY": "CALM", "INVESTIGATION": "INVESTIGATION",
        "SKILL_SEQUENCE": "INVESTIGATION", "TRAVEL": "INVESTIGATION",
        "SAN_SEQUENCE": "HORROR", "COMBAT": "COMBAT", "CLIMAX": "CLIMAX", "ENDING": "ENDING",
    }.get(scene_type, "TENSION")


def expression_for(line: dict) -> str:
    event_type = line.get("event_type")
    overlay = line.get("overlay") or {}
    result = str(overlay.get("result") or "")
    if event_type in {"SAN_CHECK", "SAN_LOSS"}:
        return "SCARED"
    if "クリティカル" in result:
        return "SURPRISED"
    if "ファンブル" in result:
        return "SCARED"
    return "NORMAL"


def normalized_overlay(line: dict) -> dict | None:
    overlay = line.get("overlay")
    if not overlay:
        return None
    overlay = dict(overlay)
    overlay_type = overlay.get("type")
    if overlay_type == "SKILL_CHECK" and line.get("event_type") not in {"DICE_RESULT", "SKILL_CHECK"}:
        return None
    if overlay_type == "LOCATION_CHANGE" and line.get("presentation_mode") == "SUBTITLE_ONLY":
        return None
    if overlay_type == "SAN":
        text = line.get("display_text") or ""
        current = re.search(r"現在値[:：]\s*(\d+)", text)
        loss = re.search(r"正気度(?:が|を)?\s*(\d+)\s*減少", text)
        if current:
            before = int(current.group(1))
            amount = int(loss.group(1)) if loss else 0
            overlay.update(before=before, after=before - amount, loss=amount)
    return overlay


def build_visual_plan(lines: list[dict], scenes: list[dict], portrait_profiles: dict[str, dict],
                      background_mapping: dict[str, str], neutral_background: str) -> dict:
    scene_index = {scene["scene_id"]: scene for scene in scenes}
    entries, missing_locations = [], set()
    for line in lines:
        scene = scene_index[line["scene_id"]]
        background, resolution = resolve_background(scene.get("location_id"), background_mapping,
                                                    "GENERIC_INTERIOR", neutral_background)
        if resolution == "NEUTRAL_FALLBACK" and scene.get("location_id"):
            missing_locations.add(scene["location_id"])
        portrait = None
        profile = portrait_profiles.get(line["speaker_id"])
        if profile and line["presentation_mode"] in {"VOICED", "SILENT_VISUAL"}:
            expression, asset_id = resolve_expression(expression_for(line), profile["expressions"])
            if asset_id:
                portrait = {
                    "profile_id": profile["profile_id"], "asset_id": asset_id, "expression": expression,
                    "position": profile["position"], "scale": profile.get("scale", 1.0),
                    "anchor": profile.get("anchor", "BOTTOM"), "crop": profile.get("crop"),
                    "baseline": profile.get("baseline", 0),
                    "portrait_kind": profile.get("portrait_kind", "FULL_BODY"),
                }
        se = []
        if line["event_type"] in {"DICE_RESULT", "SKILL_CHECK"}:
            se.append("se_dice_user")
        if line["event_type"] in {"SAN_CHECK", "SAN_LOSS"}:
            se.append("se_san_user")
        entries.append({
            "script_line_id": line["script_line_id"], "source_event_ids": line["source_event_ids"],
            "scene_id": line["scene_id"], "background_asset_id": background,
            "background_resolution": resolution, "speaker_id": line["speaker_id"], "portrait": portrait,
            "bgm_category": bgm_category(scene["scene_type"]), "bgm_asset_id": "bgm_investigation_user",
            "se": se, "overlay": normalized_overlay(line), "presentation_mode": line["presentation_mode"],
        })
    return {"schema_version": "0.1", "entries": entries, "missing_location_ids": sorted(missing_locations)}
