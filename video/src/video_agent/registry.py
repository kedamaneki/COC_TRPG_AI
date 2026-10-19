from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from video_agent.local_paths import resolve_external_asset


class RegistryError(ValueError):
    """Raised when presentation identity or assets cannot be resolved safely."""


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegistryError(f"REGISTRY_MISSING:{path.name}")
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


class PresentationRegistry:
    REQUIRED = (
        "character_registry.json",
        "yukkuri_subtitle_styles.json",
        "voice_profiles.json",
        "portrait_registry.json",
        "asset_registry.json",
    )

    def __init__(self, config_root: Path | str):
        self.root = Path(config_root)
        documents = {name: _load(self.root / name) for name in self.REQUIRED}
        self.character_document = documents["character_registry.json"]
        self.subtitle_document = documents["yukkuri_subtitle_styles.json"]
        self.voice_document = documents["voice_profiles.json"]
        self.portrait_document = documents["portrait_registry.json"]
        self.asset_document = documents["asset_registry.json"]
        self.characters = {item["character_id"]: item for item in self.character_document["characters"]}
        self.speaker_assignments = self.character_document["speaker_assignments"]
        self.subtitle_profiles = {
            item["subtitle_profile_id"]: item
            for item in self.subtitle_document["renderer_profiles"]
        }
        self.voice_profiles = {
            item["voice_profile_id"]: item for item in self.voice_document["profiles"]
        }
        self.portraits = {
            item["portrait_profile_id"]: item for item in self.portrait_document["portraits"]
        }
        self.assets = {item["asset_id"]: item for item in self.asset_document["assets"]}
        self._validate()

    def _validate(self) -> None:
        for speaker_id, assignment in self.speaker_assignments.items():
            character_id = assignment.get("character_id")
            if character_id is None:
                if speaker_id != "system":
                    raise RegistryError(f"NULL_CHARACTER_NOT_SYSTEM:{speaker_id}")
                continue
            if character_id not in self.characters:
                raise RegistryError(f"CHARACTER_UNRESOLVED:{speaker_id}:{character_id}")
            character = self.characters[character_id]
            for key, lookup in (
                ("subtitle_profile_id", self.subtitle_profiles),
                ("voice_profile_id", self.voice_profiles),
                ("portrait_profile_id", self.portraits),
            ):
                reference = character.get(key)
                if reference is not None and reference not in lookup:
                    raise RegistryError(f"{key.upper()}_UNRESOLVED:{character_id}:{reference}")

    def resolve_speaker(self, speaker_id: str) -> dict[str, Any]:
        key = speaker_id.lower()
        assignment = self.speaker_assignments.get(key)
        if assignment is None:
            raise RegistryError(f"SPEAKER_NOT_REGISTERED:{speaker_id}")
        character_id = assignment.get("character_id")
        if character_id is None:
            return {
                "speaker_id": key,
                "character_id": None,
                "display_name": assignment["display_name"],
                "voice_profile_id": None,
                "expected_voice_profile_id": None,
                "subtitle_profile_id": assignment["subtitle_profile_id"],
                "portrait_profile_id": None,
                "portrait_asset_id": None,
            }
        character = self.characters[character_id]
        portrait = self.portraits.get(character.get("portrait_profile_id"))
        asset_id = portrait.get("asset_id") if portrait else None
        if assignment.get("auto_use", False) and asset_id:
            asset = self.assets.get(asset_id)
            if not asset:
                raise RegistryError(f"ACTIVE_ASSET_UNRESOLVED:{asset_id}")
            if asset.get("approval_status") not in {"APPROVED", "APPROVED_FOR_LOCAL_PREVIEW", "TEST_ONLY"}:
                raise RegistryError(f"ACTIVE_ASSET_NOT_APPROVED:{asset_id}")
        return {
            "speaker_id": key,
            "character_id": character_id,
            "display_name": assignment.get("display_name") or character["display_name"],
            "voice_profile_id": character.get("voice_profile_id"),
            "expected_voice_profile_id": character.get("voice_profile_id"),
            "subtitle_profile_id": character["subtitle_profile_id"],
            "portrait_profile_id": character.get("portrait_profile_id"),
            "portrait_asset_id": asset_id,
        }

    def resolve_project_characters(self, project_characters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for source in project_characters:
            speaker_id = str(source["character_id"]).lower()
            if speaker_id not in self.speaker_assignments:
                raise RegistryError(f"PROJECT_CHARACTER_NOT_REGISTERED:{speaker_id}")
            resolved = self.resolve_speaker(speaker_id)
            assignment = self.speaker_assignments[speaker_id]
            allowed_overrides = assignment.get("allowed_project_overrides", {})
            for key in ("voice_profile_id", "subtitle_profile_id", "portrait_asset_id"):
                supplied = source.get(key)
                expected = resolved.get(key)
                allowed = set(allowed_overrides.get(key, []))
                if supplied is not None and expected is not None and supplied != expected and supplied not in allowed:
                    raise RegistryError(f"PROJECT_REGISTRY_MISMATCH:{speaker_id}:{key}:{supplied}:{expected}")
            effective = dict(resolved)
            for key in ("voice_profile_id", "subtitle_profile_id", "portrait_asset_id"):
                if source.get(key) in set(allowed_overrides.get(key, [])):
                    effective[key] = source[key]
                    if key == "voice_profile_id":
                        effective["expected_voice_profile_id"] = source[key]
            result[speaker_id] = {**source, **effective, "character_id": speaker_id}
        return result

    def resolve_asset(self, asset_id: str, require_approved: bool = True) -> dict[str, Any]:
        asset = self.assets.get(asset_id)
        if not asset:
            raise RegistryError(f"ASSET_MISSING:{asset_id}")
        if require_approved and asset.get("approval_status") not in {"APPROVED", "APPROVED_FOR_LOCAL_PREVIEW", "TEST_ONLY"}:
            raise RegistryError(f"ASSET_NOT_APPROVED:{asset_id}")
        path = asset.get("path")
        if not path:
            raise RegistryError(f"ASSET_PATH_MISSING:{asset_id}")
        return {**asset, "resolved_path": str(resolve_external_asset(path))}

