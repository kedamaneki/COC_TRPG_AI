from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from video_agent.assets.approval import AssetApprovalError, approve_registered_asset, verify_license_evidence
from video_agent.presentation.dice_sfx import DiceExpressionError, physical_dice_count, select_dice_sfx


@pytest.mark.parametrize(("expression", "expected"), [
    ("1D3", 1), ("1d4", 1), ("D6", 1), ("1D8+2", 1), ("1D10+2", 1),
    ("2D6+3", 2), ("3D6", 3), ("D100", 2), ("1D100", 2), ("2D100+1D4", 5),
])
def test_physical_dice_count(expression: str, expected: int) -> None:
    assert physical_dice_count(expression) == expected


def test_dice_sfx_selection_is_count_based() -> None:
    assert select_dice_sfx("1D6", single_asset_id="single", multi_asset_id="multi").asset_id == "single"
    result = select_dice_sfx("D100", single_asset_id="single", multi_asset_id="multi")
    assert (result.asset_id, result.physical_dice_count) == ("multi", 2)


def test_invalid_dice_expression_fails_closed() -> None:
    with pytest.raises(DiceExpressionError):
        physical_dice_count("percentile check")


def _evidence(tmp_path: Path, payload: bytes = b"asset") -> tuple[Path, dict]:
    asset = tmp_path / "asset.wav"
    asset.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    metadata = {"source_url": "https://example.test/asset", "asset_title": "Asset", "creator": "Creator",
                "license_name": "CC0 1.0", "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
                "sha256": digest, "commercial_use": True, "video_use": True, "modification_allowed": True,
                "attribution_required": False, "credit_text": None}
    Path(str(asset) + ".source.json").write_text(json.dumps(metadata), encoding="utf-8")
    for suffix in (".license.txt", ".source.html", ".license.html"):
        Path(str(asset) + suffix).write_text("evidence", encoding="utf-8")
    return asset, metadata


def test_evidence_backed_approval(tmp_path: Path) -> None:
    asset, metadata = _evidence(tmp_path)
    registry = {"assets": [{"asset_id": "a", "path": str(asset), "sha256": metadata["sha256"],
                              "approval_status": "NOT_APPROVED", "license_status": "LICENSE_REVIEW_REQUIRED"}]}
    evidence = verify_license_evidence(asset)
    approved = approve_registered_asset(registry, asset, evidence)
    assert approved["license_status"] == "LICENSE_APPROVED"
    assert approved["approval_status"] == "APPROVED_FOR_PREVIEW"
    assert approved["auto_use"] is False


def test_changed_hash_invalidates_approval(tmp_path: Path) -> None:
    asset, _ = _evidence(tmp_path)
    asset.write_bytes(b"changed")
    with pytest.raises(AssetApprovalError, match="ASSET_HASH_MISMATCH"):
        verify_license_evidence(asset)
