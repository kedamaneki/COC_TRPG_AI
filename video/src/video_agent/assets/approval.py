"""Evidence-backed preview approval for locally registered media assets."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


class AssetApprovalError(ValueError):
    """Raised when evidence is incomplete or the registered content changed."""


@dataclass(frozen=True)
class LicenseEvidence:
    source_json: Path
    evidence_paths: tuple[Path, ...]
    metadata: dict


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_license_evidence(asset_path: Path) -> LicenseEvidence:
    asset_path = Path(asset_path)
    source_json = Path(str(asset_path) + ".source.json")
    required = (source_json, Path(str(asset_path) + ".license.txt"),
                Path(str(asset_path) + ".source.html"), Path(str(asset_path) + ".license.html"))
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise AssetApprovalError("LICENSE_EVIDENCE_MISSING:" + "|".join(missing))
    metadata = json.loads(source_json.read_text(encoding="utf-8-sig"))
    for field in ("source_url", "asset_title", "creator", "license_name", "license_url", "sha256"):
        if not metadata.get(field):
            raise AssetApprovalError(f"LICENSE_EVIDENCE_FIELD_MISSING:{field}")
    actual = sha256_file(asset_path)
    if actual != metadata["sha256"]:
        raise AssetApprovalError(f"ASSET_HASH_MISMATCH:{actual}:{metadata['sha256']}")
    if not metadata.get("commercial_use") or not metadata.get("video_use"):
        raise AssetApprovalError("LICENSE_VIDEO_OR_COMMERCIAL_USE_NOT_ALLOWED")
    if metadata.get("attribution_required") and not metadata.get("credit_text"):
        raise AssetApprovalError("REQUIRED_CREDIT_TEXT_MISSING")
    return LicenseEvidence(source_json=source_json, evidence_paths=required, metadata=metadata)


def approve_registered_asset(registry: dict, asset_path: Path, evidence: LicenseEvidence,
                             *, approval_status: str = "APPROVED_FOR_PREVIEW") -> dict:
    asset_path = Path(asset_path).resolve()
    matches = [item for item in registry.get("assets", [])
               if item.get("path") and Path(item["path"]).resolve() == asset_path]
    if len(matches) != 1:
        raise AssetApprovalError(f"REGISTRY_ASSET_MATCH_COUNT:{len(matches)}:{asset_path}")
    item = matches[0]
    if item.get("sha256") != evidence.metadata["sha256"]:
        raise AssetApprovalError("REGISTRY_HASH_MISMATCH")
    item.update({
        "author": evidence.metadata["creator"],
        "license": evidence.metadata["license_name"],
        "commercial_use": evidence.metadata["commercial_use"],
        "video_use": evidence.metadata["video_use"],
        "modification_allowed": evidence.metadata.get("modification_allowed"),
        "credit_required": evidence.metadata.get("attribution_required"),
        "credit_text": evidence.metadata.get("credit_text"),
        "source_url": evidence.metadata["source_url"],
        "license_url": evidence.metadata["license_url"],
        "license_status": "LICENSE_APPROVED",
        "approval_status": approval_status,
        "auto_use": False,
        "license_evidence_paths": [str(path) for path in evidence.evidence_paths],
        "approved_sha256": evidence.metadata["sha256"],
    })
    return item


def extend_preview_scope(asset: dict, scope: str) -> dict:
    """Add a Human-approved preview scope without enabling automatic use."""
    if asset.get("license_status") != "LICENSE_APPROVED":
        raise AssetApprovalError("PREVIEW_SCOPE_REQUIRES_LICENSE_APPROVAL")
    if asset.get("approval_status") != "APPROVED_FOR_PREVIEW":
        raise AssetApprovalError("PREVIEW_SCOPE_REQUIRES_PREVIEW_APPROVAL")
    if not scope or not isinstance(scope, str):
        raise AssetApprovalError("PREVIEW_SCOPE_INVALID")
    scopes = list(dict.fromkeys([*asset.get("approved_video_scopes", []), scope]))
    asset["approved_video_scopes"] = scopes
    asset["auto_use"] = False
    return asset


def approved_for_preview_scope(asset: dict, scope: str) -> bool:
    """Return true only when license, preview approval, hash, and scope agree."""
    return bool(
        asset.get("license_status") == "LICENSE_APPROVED"
        and asset.get("approval_status") == "APPROVED_FOR_PREVIEW"
        and asset.get("approved_sha256") == asset.get("sha256")
        and scope in asset.get("approved_video_scopes", [])
        and asset.get("auto_use") is False
    )
