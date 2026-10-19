from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path


IGNORED_NAMES = {".gitkeep", "Thumbs.db", ".DS_Store"}
TYPE_BY_SUFFIX = {
    ".png": "PORTRAIT_OR_IMAGE", ".jpg": "PORTRAIT_OR_IMAGE", ".jpeg": "PORTRAIT_OR_IMAGE",
    ".webp": "PORTRAIT_OR_IMAGE", ".bmp": "PORTRAIT_OR_IMAGE", ".wav": "AUDIO",
    ".mp3": "AUDIO", ".ogg": "AUDIO", ".m4a": "AUDIO", ".mp4": "VIDEO",
    ".mov": "VIDEO", ".webm": "VIDEO", ".psd": "LAYERED_PORTRAIT",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_id(relative: str, digest: str) -> str:
    stem = "".join(char.lower() if char.isalnum() else "_" for char in Path(relative).stem)
    path_digest = hashlib.sha256(relative.casefold().encode("utf-8")).hexdigest()
    return f"detected_{stem.strip('_') or 'asset'}_{digest[:8]}_{path_digest[:8]}"


def _rekey_scan_root_assets(registry: dict, scan_root: Path) -> int:
    scoped = []
    for item in registry.get("assets", []):
        value = item.get("path")
        if not value or item.get("source") != "LOCAL_ASSET_SCAN":
            continue
        path = Path(value)
        if not path.is_absolute():
            continue
        try:
            relative = path.resolve().relative_to(scan_root.resolve()).as_posix()
        except ValueError:
            continue
        scoped.append((item, relative))
    changed = 0
    for item, relative in scoped:
        new_id = _asset_id(relative, item["sha256"])
        if item.get("asset_id") != new_id:
            item["asset_id"] = new_id
            changed += 1
        item["scan_relative_path"] = relative
    digest_groups = {}
    for item in registry.get("assets", []):
        if item.get("sha256"):
            digest_groups.setdefault(item["sha256"], []).append(item)
    for item, _ in scoped:
        peers = [peer for peer in digest_groups[item["sha256"]] if peer is not item]
        item["duplicate_of_asset_ids"] = [peers[0]["asset_id"]] if item.get("change_status") == "DUPLICATE_CONTENT" and peers else []
    return changed


def scan_assets(scan_root: Path, registry_path: Path, *, write_registry: bool = True) -> dict:
    scan_root, registry_path = Path(scan_root), Path(registry_path)
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    existing = {}
    for item in registry.get("assets", []):
        value = item.get("path")
        if not value:
            continue
        candidate = Path(value)
        if candidate.is_absolute():
            try:
                key = candidate.resolve().relative_to(scan_root.resolve()).as_posix()
            except ValueError:
                continue
        else:
            if item.get("scan_relative_path"):
                key = Path(item["scan_relative_path"]).as_posix()
            elif candidate.parent == Path("."):
                key = candidate.as_posix()
            else:
                resolved = (registry_path.parent.parent / candidate).resolve()
                try:
                    key = resolved.relative_to(scan_root.resolve()).as_posix()
                except ValueError:
                    continue
        existing[key] = item
    digest_index = {}
    for item in registry.get("assets", []):
        digest_index.setdefault(item.get("sha256"), []).append(item)
    findings, additions = [], []
    if not scan_root.exists():
        return {"status": "SCAN_ROOT_MISSING", "scan_root": str(scan_root), "findings": [], "counts": {}}
    for path in sorted((item for item in scan_root.rglob("*") if item.is_file()), key=lambda p: p.as_posix().lower()):
        if path.name in IGNORED_NAMES:
            continue
        relative = path.relative_to(scan_root).as_posix()
        digest = sha256_file(path)
        previous = existing.get(relative)
        if previous and previous.get("sha256") == digest:
            status = "UNCHANGED"
        elif previous:
            status = "CHANGED_HASH"
        elif digest in digest_index:
            status = "DUPLICATE_CONTENT"
        else:
            status = "NEW_ASSET"
        finding = {
            "path": relative, "size": path.stat().st_size, "sha256": digest,
            "asset_type": TYPE_BY_SUFFIX.get(path.suffix.lower(), "UNKNOWN"),
            "mime_type": mimetypes.guess_type(path.name)[0], "scan_status": status,
        }
        findings.append(finding)
        if status != "UNCHANGED":
            addition = {
                "asset_id": _asset_id(relative, digest), "asset_type": finding["asset_type"],
                "path": str(path.resolve()), "scan_relative_path": relative,
                "sha256": digest, "size": finding["size"],
                "source": "LOCAL_ASSET_SCAN", "author": "UNKNOWN", "license": "UNKNOWN",
                "commercial_use": None, "credit_required": None, "credit_text": None,
                "detection_status": "DETECTED", "approval_status": "NOT_APPROVED",
                "license_status": "LICENSE_REVIEW_REQUIRED", "change_status": status,
                "supersedes_asset_id": previous.get("asset_id") if previous else None,
                "duplicate_of_asset_ids": [digest_index[digest][0]["asset_id"]] if digest_index.get(digest) else [],
                "auto_use": False,
            }
            additions.append(addition)
            digest_index.setdefault(digest, []).append(addition)
    missing = []
    for relative, item in sorted(existing.items()):
        if not (scan_root / relative).exists():
            missing.append({
                "asset_id": item.get("asset_id"), "path": relative,
                "sha256": item.get("sha256"), "scan_status": "MISSING_ASSET",
                "approval_status": item.get("approval_status"),
            })
    if write_registry:
        if additions:
            registry.setdefault("assets", []).extend(additions)
        rekeyed_count = _rekey_scan_root_assets(registry, scan_root)
        registry["last_scan"] = {
            "at": datetime.now(timezone.utc).isoformat(), "scan_root": str(scan_root),
            "detected_count": len(additions), "missing_count": len(missing),
            "registry_refreshed": True, "rekeyed_count": rekeyed_count,
        }
        registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts = {key: sum(item["scan_status"] == key for item in findings)
              for key in ("UNCHANGED", "NEW_ASSET", "CHANGED_HASH", "DUPLICATE_CONTENT")}
    approval_counts = {
        "APPROVED_ASSETS": sum(str(item.get("approval_status", "")).startswith("APPROVED") for item in registry.get("assets", [])),
        "UNAPPROVED_ASSETS": sum(item.get("approval_status") in {"NOT_APPROVED", None} for item in registry.get("assets", [])),
    }
    counts["MISSING_ASSET"] = len(missing)
    return {"status": "PASS", "scan_root": str(scan_root), "registry_path": str(registry_path),
            "findings": findings, "registered": additions, "counts": counts,
            "missing": missing, "approval_counts": approval_counts,
            "scan_executed": True, "registry_refreshed": bool(write_registry),
            "scan_timestamp": registry.get("last_scan", {}).get("at"),
            "unapproved_auto_used": 0, "policy": "DETECTED / NOT_APPROVED / LICENSE_REVIEW_REQUIRED"}


def render_markdown(report: dict) -> str:
    counts = report.get("counts", {})
    lines = ["# VIDEO_ASSET_SCAN_REPORT", "", f"- Status: `{report['status']}`",
             f"- Scan root: `{report['scan_root']}`"]
    for name in ("UNCHANGED", "NEW_ASSET", "CHANGED_HASH", "DUPLICATE_CONTENT", "MISSING_ASSET"):
        lines.append(f"- {name}: `{counts.get(name, 0)}`")
    for name, value in report.get("approval_counts", {}).items():
        lines.append(f"- {name}: `{value}`")
    lines += [f"- Registry refreshed: `{str(report.get('registry_refreshed', False)).lower()}`",
              f"- Scan timestamp: `{report.get('scan_timestamp')}`"]
    lines += ["- Unapproved auto-used: `0`", "", "## Findings", ""]
    for item in report.get("findings", []):
        lines.append(f"- `{item['scan_status']}` `{item['path']}` `{item['sha256']}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Register newly added video assets without approving them.")
    parser.add_argument("scan_root", type=Path)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--markdown-report", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = scan_assets(args.scan_root, args.registry, write_registry=not args.dry_run)
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_report:
        args.markdown_report.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_report.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report["counts"], ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
