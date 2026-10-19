from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path


EXPECTED_SOURCE_HASH = "fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d"
ABSOLUTE_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:[A-Za-z]:[\\/]|/Users/|/home/)")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source(source_root: Path, control_root: Path) -> dict:
    manifest = load(control_root / "V13_RAW_FREEZE_MANIFEST.json")
    failures, aggregate = [], hashlib.sha256()
    for row in sorted(manifest["files"], key=lambda item: item["path"]):
        path = source_root / Path(row["path"])
        actual = sha256(path) if path.is_file() else None
        if actual != row["sha256"] or (path.is_file() and path.stat().st_size != row["size"]):
            failures.append(row["path"])
        aggregate.update(row["path"].encode("utf-8") + b"\0" + row["sha256"].encode("ascii") + b"\n")
    actual_aggregate = aggregate.hexdigest()
    return {
        "status": "PASS" if not failures and len(manifest["files"]) == 373 and actual_aggregate == EXPECTED_SOURCE_HASH else "FAIL",
        "file_count": len(manifest["files"]), "aggregate_sha256": actual_aggregate, "failures": failures,
    }


def verify_assets(repo: Path, asset_root: Path) -> dict:
    manifest = load(repo / "manifests/PORTABILITY_EXTERNAL_ASSETS.json")
    rows = []
    for kind, root, items in (("external", asset_root, manifest["assets"]), ("repo", repo, manifest["repo_assets"])):
        for item in items:
            path = root / Path(item["relative_path"])
            actual = sha256(path) if path.is_file() else None
            expected = item.get("sha256")
            rows.append({"asset_id": item["asset_id"], "kind": kind, "exists": path.is_file(),
                         "hash_match": expected is None or actual == expected, "resolved_path": str(path)})
    return {"status": "PASS" if all(row["exists"] and row["hash_match"] for row in rows) else "FAIL", "assets": rows}


def verify_scenario_source(repo: Path) -> dict:
    manifest = load(repo / "manifests/CORBITT_SCENARIO_SOURCE.json")
    configured = os.environ.get("CORBITT_SCENARIO_SOURCE_ROOT")
    root = Path(configured).expanduser().resolve() if configured else (
        repo / manifest["default_relative_root"]
    ).resolve()
    failures, aggregate = [], hashlib.sha256()
    for row in sorted(manifest["files"], key=lambda item: item["path"]):
        path = root / row["path"]
        actual = sha256(path) if path.is_file() else None
        if actual != row["sha256"] or (path.is_file() and path.stat().st_size != row["size"]):
            failures.append(row["path"])
        aggregate.update(
            row["path"].encode("utf-8")
            + b"\0" + str(row["size"]).encode("ascii")
            + b"\0" + row["sha256"].encode("ascii")
            + b"\n"
        )
    actual_aggregate = aggregate.hexdigest()
    return {
        "status": "PASS" if not failures and actual_aggregate == manifest["aggregate_sha256"] else "FAIL",
        "root": str(root),
        "file_count": len(manifest["files"]),
        "aggregate_sha256": actual_aggregate,
        "failures": failures,
    }


def active_runtime_path_scan(repo: Path) -> dict:
    roots = [repo / "core/src", repo / "video/src", repo / "tools/runtime_isolation",
             repo / "tools/night_guard"]
    extra = [repo / "tools/scan_video_assets.py", repo / "tools/classify_video_assets.py",
             repo / "tools/acquire_external_video_assets.py"]
    findings = []
    paths = list(extra)
    for root in roots:
        paths.extend(root.rglob("*"))
    for path in paths:
            if not path.is_file() or path.suffix.lower() not in {".py", ".ps1", ".bat", ".json", ".toml"}:
                continue
            if path.name.startswith("test_"):
                continue
            text = path.read_text(encoding="utf-8-sig", errors="replace")
            for number, line in enumerate(text.splitlines(), 1):
                if ABSOLUTE_PATTERN.search(line) and "os.environ.get" not in line:
                    findings.append({"path": path.relative_to(repo).as_posix(), "line": number, "text": line.strip()[:240]})
    return {"status": "PASS" if not findings else "FAIL", "hardcoded_runtime_path_count": len(findings), "findings": findings}


def runtime_check() -> dict:
    checks = {}
    for name in ("FFMPEG_PATH", "FFPROBE_PATH", "VOICE_RUNTIME_PATH", "VIDEO_FONT_PATH"):
        value = os.environ.get(name)
        checks[name] = {"configured": bool(value), "exists": bool(value and Path(value).exists())}
    ffmpeg = os.environ.get("FFMPEG_PATH")
    if ffmpeg and Path(ffmpeg).is_file():
        result = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace")
        checks["FFMPEG_PATH"]["version"] = (result.stdout or result.stderr).splitlines()[0]
    return {"status": "PASS" if all(row["configured"] and row["exists"] for row in checks.values()) else "FAIL", "checks": checks}


def pipeline_dry_run(repo: Path, source_root: Path, asset_result: dict) -> dict:
    events = load(source_root / "unified-event-log.json")
    selected = [row for row in events if 264 <= int(row.get("raw_event_offset", -1)) <= 281]
    registry_files = ["character_registry.json", "voice_profiles.json", "portrait_registry.json",
                      "asset_registry.json", "yukkuri_subtitle_styles.json", "presentation_layout_m3.json"]
    loaded = {name: load(repo / "video/config" / name) for name in registry_files}
    roll = [row for row in selected if int(row["raw_event_offset"]) == 271]
    return {
        "status": "PASS" if len(selected) == 18 and len(roll) == 1 and asset_result["status"] == "PASS" else "FAIL",
        "source_event_count": len(selected), "roll_offset_271_count": len(roll),
        "registry_files_loaded": sorted(loaded), "render_executed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--source-root", type=Path, default=os.environ.get("CORBITT_V13_SOURCE_ROOT"))
    parser.add_argument("--control-root", type=Path, default=os.environ.get("CORBITT_V13_CONTROL_ROOT"))
    parser.add_argument("--asset-root", type=Path, default=os.environ.get("VIDEO_ASSET_ROOT"))
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    if not args.source_root or not args.control_root or not args.asset_root:
        raise SystemExit("CORBITT_V13_SOURCE_ROOT, CORBITT_V13_CONTROL_ROOT and VIDEO_ASSET_ROOT are required")
    repo = args.repo.resolve()
    source = verify_source(args.source_root.resolve(), args.control_root.resolve())
    assets = verify_assets(repo, args.asset_root.resolve())
    report = {"schema_version": 1, "repo": str(repo), "source": source, "assets": assets,
              "scenario_source": verify_scenario_source(repo),
              "runtime": runtime_check(), "runtime_paths": active_runtime_path_scan(repo)}
    report["pipeline_dry_run"] = pipeline_dry_run(repo, args.source_root.resolve(), assets)
    report["status"] = "PASS" if all(report[key]["status"] == "PASS" for key in
                                        ("source", "assets", "scenario_source", "runtime", "runtime_paths", "pipeline_dry_run")) else "FAIL"
    destination = args.json_report or repo / "docs/CROSS_PC_PORTABILITY_VERIFY.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key]["status"] for key in
                      ("source", "assets", "scenario_source", "runtime", "runtime_paths", "pipeline_dry_run")},
                     ensure_ascii=False))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
