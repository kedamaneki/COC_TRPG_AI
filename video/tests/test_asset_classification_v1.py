from __future__ import annotations

import json
from pathlib import Path

from video_agent.assets.classification import (
    build_license_evidence,
    build_semantic_index,
    canonicalize_assets,
    classify_background,
    classify_bgm,
    classify_sfx,
    invalidate_changed_hash,
    semantic_lookup,
)
from video_agent.presentation.planner import semantic_asset_candidates


def asset(asset_id: str, path: str, sha: str = "hash", *, approved: bool = False) -> dict:
    return {
        "asset_id": asset_id,
        "path": path,
        "sha256": sha,
        "license_status": "LICENSE_APPROVED" if approved else "LICENSE_REVIEW_REQUIRED",
        "approval_status": "APPROVED_FOR_PREVIEW" if approved else "NOT_APPROVED",
        "auto_use": approved,
    }


def test_duplicate_content_is_grouped_by_sha_without_changing_ids() -> None:
    groups, mapping = canonicalize_assets([asset("b", "z/b.wav", "same"), asset("a", "a/a.wav", "same")])
    assert len(groups) == 1
    assert groups[0]["canonical_asset_id"] == "a"
    assert groups[0]["duplicate_asset_ids"] == ["b"]
    assert mapping == {"a": "a", "b": "a"}


def test_semantic_classifiers_keep_clear_and_unknown_cases_separate() -> None:
    assert classify_background("地下室.png")["environment_type"] == "BASEMENT"
    assert "CALM" in classify_bgm("日常BGM.mp3")["mood"]
    assert classify_sfx("木材が割れる.wav")["action_semantic"] == "wood_break"
    unknown = classify_sfx("nc00000.wav")
    assert unknown["action_semantic"] == "UNKNOWN"
    assert unknown["classification_confidence"] == "LOW"


def test_license_evidence_is_separate_and_does_not_approve(tmp_path: Path) -> None:
    evidence_file = tmp_path / "利用規約.txt"
    evidence_file.write_text("human review required", encoding="utf-8")
    canonical = [{
        "canonical_asset_id": "a", "canonical_path": str(tmp_path / "nc123.wav"), "sha256": "x",
        "duplicate_asset_ids": [], "duplicate_paths": [], "review_count": 1,
    }]
    classification = {"a": {"category": "SFX"}}
    result = build_license_evidence(canonical, classification, tmp_path)
    row = result["records"][0]
    assert result["evidence_file_count"] == 1
    assert row["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert row["source_locator_hints"][0]["license_evidence"] is False


def test_unapproved_assets_are_indexed_but_never_auto_selected() -> None:
    record = {
        "asset_id": "a", "canonical_asset_id": "a", "category": "SFX",
        **classify_sfx("木材が割れる.wav"),
    }
    index = build_semantic_index([record], {"assets": [asset("a", "x.wav")]})
    assert semantic_lookup(index, "sfx", "wood_break", automatic=False) == ["a"]
    assert semantic_lookup(index, "sfx", "wood_break", automatic=True) == []


def test_approved_asset_can_be_selected_by_semantic_tag() -> None:
    record = {
        "asset_id": "a", "canonical_asset_id": "a", "category": "SFX",
        **classify_sfx("木材が割れる.wav"),
    }
    index = build_semantic_index([record], {"assets": [asset("a", "x.wav", approved=True)]})
    assert semantic_lookup(index, "sfx", "wood_break") == ["a"]
    assert semantic_asset_candidates(index, "sfx", "wood_break") == ["a"]


def test_changed_hash_invalidates_both_approval_gates() -> None:
    before = asset("a", "x.wav", "old", approved=True)
    after = invalidate_changed_hash(before, "new")
    assert after["license_status"] == "LICENSE_REVIEW_REQUIRED"
    assert after["approval_status"] == "NOT_APPROVED"
    assert after["auto_use"] is False
    assert after["change_status"] == "CHANGED_ASSET_REQUIRES_REVIEW"

