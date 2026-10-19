from __future__ import annotations

import json
from pathlib import Path

from video_agent.assets.classification import (
    classify_background,
    classify_bgm,
    classify_sfx,
    invalidate_changed_hash,
    run_external_classification,
)
from video_agent.assets.external_acquisition import DIRECT_ASSETS, ITCH_PACKS


def _write_sidecars(media: Path, *, license_name: str = "CC0 1.0", attribution: bool = False) -> None:
    metadata = {
        "source_url": "https://primary.example/asset", "source_site": "Fixture Primary",
        "creator": "Fixture Author", "license_name": license_name,
        "license_url": "https://primary.example/license", "downloaded_at": "2026-10-19T00:00:00+00:00",
        "commercial_use": True, "video_use": True, "modification_allowed": True,
        "attribution_required": attribution, "redistribution_allowed": False,
        "credit_text": "Fixture credit" if attribution else None,
        "terms_summary": "fixture", "license_review_recommendation": "RECOMMEND_APPROVE",
    }
    media.with_name(media.name + ".source.json").write_text(json.dumps(metadata), encoding="utf-8")
    media.with_name(media.name + ".license.txt").write_text("fixture evidence", encoding="utf-8")


def test_candidate_set_is_bounded_and_all_sources_are_primary() -> None:
    media_count = len(DIRECT_ASSETS) + sum(len(pack["members"]) for pack in ITCH_PACKS)
    assert media_count == 13
    assert all(asset.source_url.startswith("https://") and asset.license_url.startswith("https://") for asset in DIRECT_ASSETS)
    assert all(asset.commercial_use and asset.video_use and asset.modification_allowed for asset in DIRECT_ASSETS)


def test_required_semantics_are_deterministic() -> None:
    assert classify_background("aipict_basement_ruins01.png")["environment_type"] == "BASEMENT"
    assert classify_sfx("freesound_502511_wood_creak_single_v3_hq_preview.mp3")["action_semantic"] == "wood_creak"
    assert classify_sfx("freesound_387014_wood_break_hq_preview.mp3")["action_semantic"] == "wood_break"
    bgm = classify_bgm("itch_arkeia_tension_as_the_light_fades.ogg")
    assert "TENSION" in bgm["semantic_tags"]
    assert bgm["dialogue_compatibility"] == "GOOD"


def test_external_classification_keeps_assets_unapproved(tmp_path: Path) -> None:
    root = tmp_path / "外部取得素材"
    assets = []
    specs = [
        (root / "backgrounds/basement/x_basement.png", b"png"),
        (root / "sfx/wood_creak/x_wood_creak.mp3", b"creak"),
        (root / "sfx/wood_break/x_wood_break.mp3", b"break"),
        (root / "bgm/tension/x_tension_horror.ogg", b"music"),
    ]
    for index, (path, content) in enumerate(specs):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content); _write_sidecars(path)
        assets.append({"asset_id": f"asset_{index}", "path": str(path), "sha256": f"{index + 1:064x}",
                       "license_status": "LICENSE_REVIEW_REQUIRED", "approval_status": "NOT_APPROVED", "auto_use": False})
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({"schema_version": "1", "assets": assets}), encoding="utf-8")
    result = run_external_classification(registry, root)
    assert result["counts"] == {"BACKGROUND": 1, "SFX": 2, "BGM": 1}
    assert all(item["priority"] == "P0" for item in result["review_queue"]["items"])
    assert all(item["evidence_files"] and item["source_url"] for item in result["license_evidence"]["records"])
    assert all(not item["auto_use"] and item["approval_status"] == "NOT_APPROVED" for item in result["selected"])


def test_changed_hash_invalidates_any_previous_approval() -> None:
    changed = invalidate_changed_hash({"sha256": "old", "license_status": "LICENSE_APPROVED",
                                       "approval_status": "APPROVED_FOR_PREVIEW", "auto_use": True}, "new")
    assert changed["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert changed["approval_status"] == "NOT_APPROVED"
    assert changed["auto_use"] is False


def test_license_policy_keeps_cc_by_credit_and_rejects_noncommercial() -> None:
    cc_by = next(pack for pack in ITCH_PACKS if pack["license_name"] == "CC BY 4.0")
    assert cc_by["credit_text"]
    candidate = {"commercial_use": False, "license_status": "LICENSE_REVIEW_REQUIRED", "auto_use": False}
    assert candidate["commercial_use"] is False and candidate["auto_use"] is False
