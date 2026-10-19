from __future__ import annotations

import pytest

from video_agent.assets.approval import (
    AssetApprovalError,
    approved_for_preview_scope,
    extend_preview_scope,
)


def _asset() -> dict:
    return {
        "sha256": "abc",
        "approved_sha256": "abc",
        "license_status": "LICENSE_APPROVED",
        "approval_status": "APPROVED_FOR_PREVIEW",
        "approved_video_scopes": ["VIDEO_001"],
        "auto_use": False,
    }


def test_scope_extension_preserves_auto_use_false() -> None:
    asset = extend_preview_scope(_asset(), "VIDEO_002_FINAL_BATTLE")
    assert approved_for_preview_scope(asset, "VIDEO_002_FINAL_BATTLE")
    assert asset["auto_use"] is False


def test_scope_extension_is_idempotent() -> None:
    asset = _asset()
    extend_preview_scope(asset, "VIDEO_002_FINAL_BATTLE")
    extend_preview_scope(asset, "VIDEO_002_FINAL_BATTLE")
    assert asset["approved_video_scopes"].count("VIDEO_002_FINAL_BATTLE") == 1


def test_unlicensed_asset_cannot_receive_scope() -> None:
    asset = _asset()
    asset["license_status"] = "LICENSE_REVIEW_REQUIRED"
    with pytest.raises(AssetApprovalError, match="REQUIRES_LICENSE_APPROVAL"):
        extend_preview_scope(asset, "VIDEO_002_FINAL_BATTLE")


def test_changed_hash_invalidates_scoped_approval() -> None:
    asset = extend_preview_scope(_asset(), "VIDEO_002_FINAL_BATTLE")
    asset["sha256"] = "changed"
    assert not approved_for_preview_scope(asset, "VIDEO_002_FINAL_BATTLE")
