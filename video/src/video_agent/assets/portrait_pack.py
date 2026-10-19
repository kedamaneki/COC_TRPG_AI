from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable


APPROVED_STATUSES = {"APPROVED", "APPROVED_FOR_PREVIEW", "APPROVED_FOR_LOCAL_PREVIEW", "TEST_ONLY"}


class PortraitPackError(ValueError):
    """Raised when a portrait pack violates identity or approval contracts."""


def _load(path: Path | str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def load_portrait_pack(
    portrait_registry_path: Path | str,
    asset_registry_path: Path | str,
    *,
    pack_id: str,
) -> list[dict[str, Any]]:
    portrait_document = _load(portrait_registry_path)
    asset_document = _load(asset_registry_path)
    assets = {item["asset_id"]: item for item in asset_document["assets"]}
    profiles = [item for item in portrait_document["portraits"] if item.get("pack_id") == pack_id]
    if not profiles:
        raise PortraitPackError(f"PORTRAIT_PACK_MISSING:{pack_id}")
    seen_profiles: set[str] = set()
    resolved: list[dict[str, Any]] = []
    for profile in profiles:
        profile_id = profile["portrait_profile_id"]
        if profile_id in seen_profiles:
            raise PortraitPackError(f"DUPLICATE_PORTRAIT_ID:{profile_id}")
        seen_profiles.add(profile_id)
        asset_id = profile["asset_id"]
        asset = assets.get(asset_id)
        if asset is None:
            raise PortraitPackError(f"PORTRAIT_ASSET_MISSING:{profile_id}:{asset_id}")
        tags = profile.get("semantic_tags") or []
        if not tags:
            raise PortraitPackError(f"PORTRAIT_SEMANTIC_TAGS_MISSING:{profile_id}")
        resolved.append({**profile, "asset": asset})
    return resolved


def semantic_portrait_lookup(
    profiles: Iterable[dict[str, Any]],
    *tags: str,
    automatic: bool = False,
) -> list[dict[str, Any]]:
    required = {tag.lower() for tag in tags}
    matches: list[dict[str, Any]] = []
    for profile in profiles:
        available = {str(tag).lower() for tag in profile.get("semantic_tags", [])}
        if not required.issubset(available):
            continue
        asset = profile.get("asset", {})
        if automatic:
            if not asset.get("auto_use", False):
                continue
            if asset.get("approval_status") not in APPROVED_STATUSES:
                continue
            if asset.get("license_status") != "LICENSE_APPROVED":
                continue
        matches.append(profile)
    return matches


def scene_actor_layer_eligible(profile: dict[str, Any], scene_type: str) -> bool:
    if not profile.get("npc_presence_layer_eligible", False):
        return False
    allowed = {str(value).lower() for value in profile.get("allowed_scene_types", [])}
    return "*" in allowed or scene_type.lower() in allowed


def assert_registry_ids_unique(document: dict[str, Any], field: str, collection: str) -> None:
    values = [str(item[field]) for item in document[collection]]
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        raise PortraitPackError(f"DUPLICATE_{field.upper()}:" + ",".join(duplicates))
