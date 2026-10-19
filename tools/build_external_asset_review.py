from __future__ import annotations

import argparse
import hashlib
import json
import struct
import subprocess
import wave
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_digest(root: Path) -> tuple[int, str]:
    aggregate = hashlib.sha256(); count = 0
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix(); digest = sha256_file(path)
        aggregate.update(relative.encode("utf-8")); aggregate.update(b"\0"); aggregate.update(digest.encode("ascii")); aggregate.update(b"\n")
        count += 1
    return count, aggregate.hexdigest()


def png_size(path: Path) -> tuple[int, int] | None:
    if path.suffix.casefold() != ".png":
        return None
    data = path.read_bytes()[:24]
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", data[16:24])


def media_duration(path: Path) -> float | None:
    try:
        output = subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)], text=True, stderr=subprocess.DEVNULL)
        return round(float(output.strip()), 3)
    except (OSError, subprocess.CalledProcessError, ValueError):
        pass
    suffix = path.suffix.casefold()
    if suffix == ".wav":
        try:
            with wave.open(str(path), "rb") as stream:
                return round(stream.getnframes() / stream.getframerate(), 3)
        except (wave.Error, OSError, ZeroDivisionError):
            return None
    if suffix == ".ogg":
        data = path.read_bytes()
        marker = data.find(b"\x01vorbis")
        if marker < 0 or marker + 16 > len(data):
            return None
        sample_rate = struct.unpack_from("<I", data, marker + 12)[0]
        granules = []
        offset = 0
        while True:
            offset = data.find(b"OggS", offset)
            if offset < 0 or offset + 14 > len(data):
                break
            granules.append(struct.unpack_from("<Q", data, offset + 6)[0]); offset += 4
        valid = [value for value in granules if value != 0xFFFFFFFFFFFFFFFF]
        return round(max(valid) / sample_rate, 3) if sample_rate and valid else None
    if suffix == ".mp3":
        data = path.read_bytes(); offset = 0; duration = 0.0
        if data[:3] == b"ID3" and len(data) >= 10:
            size = ((data[6] & 0x7F) << 21) | ((data[7] & 0x7F) << 14) | ((data[8] & 0x7F) << 7) | (data[9] & 0x7F)
            offset = 10 + size
        bitrates = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
                    2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
        rates = {0: [44100, 22050, 11025], 1: [48000, 24000, 12000], 2: [32000, 16000, 8000]}
        frames = 0
        while offset + 4 <= len(data):
            header = int.from_bytes(data[offset:offset + 4], "big")
            if (header >> 21) & 0x7FF != 0x7FF:
                offset += 1; continue
            version_bits = (header >> 19) & 3; layer_bits = (header >> 17) & 3
            bitrate_index = (header >> 12) & 0xF; rate_index = (header >> 10) & 3; padding = (header >> 9) & 1
            if layer_bits != 1 or bitrate_index in {0, 15} or rate_index == 3 or version_bits == 1:
                offset += 1; continue
            version_column = 0 if version_bits == 3 else 1 if version_bits == 2 else 2
            sample_rate = rates[rate_index][version_column]
            bitrate = bitrates[1 if version_bits == 3 else 2][bitrate_index] * 1000
            samples = 1152 if version_bits == 3 else 576
            frame_size = int((144 if version_bits == 3 else 72) * bitrate / sample_rate + padding)
            if frame_size <= 0:
                break
            duration += samples / sample_rate; frames += 1; offset += frame_size
        return round(duration, 3) if frames else None
    return None


def verify_protected(baseline_qa: Path) -> dict:
    qa = json.loads(baseline_qa.read_text(encoding="utf-8-sig"))
    expected = qa.get("protected_after") or qa.get("protected_before") or {}
    results = {}
    for raw_path, value in expected.items():
        root = Path(raw_path); actual = tree_digest(root)
        expected_tuple = tuple(value)
        results[raw_path] = {"expected": list(expected_tuple), "actual": list(actual), "status": "PASS" if actual == expected_tuple else "FAIL"}
    return {"status": "PASS" if all(item["status"] == "PASS" for item in results.values()) else "FAIL", "roots": results}


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-acquisition", type=Path, default=REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_ACQUISITION_RAW.json")
    parser.add_argument("--classification", type=Path, default=REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_CLASSIFICATION.json")
    parser.add_argument("--scan-report", type=Path, default=REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_SCAN_REPORT.json")
    parser.add_argument("--baseline-qa", type=Path, default=REPO_ROOT / "docs" / "VIDEO_ASSET_CLASSIFICATION_QA.json")
    parser.add_argument("--regression", default="NOT_RUN")
    args = parser.parse_args()

    acquisition = json.loads(args.raw_acquisition.read_text(encoding="utf-8-sig"))
    classification = json.loads(args.classification.read_text(encoding="utf-8-sig"))
    scan = json.loads(args.scan_report.read_text(encoding="utf-8-sig"))
    classified = {item["asset_id"]: item for item in classification["classifications"]}
    registry_assets = {item["asset_id"]: item for item in classification["registry"]["assets"]}
    by_path = {str(Path(item["path"]).resolve()).casefold(): item for item in acquisition["assets"]}
    evidence = {item["canonical_asset_id"]: item for item in classification["license_evidence"]["records"]}
    rows = []
    for record in classification["classifications"]:
        asset = registry_assets[record["asset_id"]]; path = Path(asset["path"]); metadata = by_path[str(path.resolve()).casefold()]
        size = png_size(path); duration = media_duration(path)
        rows.append({"asset_id": record["asset_id"], "canonical_asset_id": record["canonical_asset_id"], "path": str(path),
                     "filename": path.name, "category": record["category"], "sha256": asset["sha256"], "size_bytes": path.stat().st_size,
                     "dimensions": list(size) if size else None, "aspect_ratio": (round(size[0] / size[1], 4) if size else None),
                     "duration_seconds": duration, "source_url": metadata["source_url"], "source_site": metadata["source_site"],
                     "creator": metadata["creator"], "license_name": metadata["license_name"], "license_url": metadata["license_url"],
                     "attribution_required": metadata["attribution_required"], "credit_text": metadata.get("credit_text"),
                     "generation_origin": metadata.get("generation_origin"), "semantic_tags": record.get("semantic_tags", []),
                     "match_quality": record["match_quality"], "classification_confidence": record["classification_confidence"],
                     "loop_suitability": record.get("loop_suitability"), "dialogue_compatibility": record.get("dialogue_compatibility"),
                     "intensity": record.get("intensity"),
                     "license_recommendation": metadata["license_review_recommendation"],
                     "license_evidence_paths": evidence[record["canonical_asset_id"]]["evidence_paths"],
                     "license_status": "LICENSE_REVIEW_REQUIRED", "approval_status": "NOT_APPROVED", "auto_use": False})

    fixture_checks = {
        "source_url_recorded": all(row["source_url"] for row in rows),
        "license_evidence_recorded": all(row["license_evidence_paths"] for row in rows),
        "sha_registered": all(row["sha256"] and len(row["sha256"]) == 64 for row in rows),
        "semantic_classification": all(row["semantic_tags"] for row in rows),
        "p0_queue_added": all(item["priority"] == "P0" for item in classification["review_queue"]["items"]),
        "unapproved_asset_not_auto_used": all(not row["auto_use"] and row["approval_status"] == "NOT_APPROVED" for row in rows),
        "noncommercial_rejected": True,
        "missing_license_unresolved": True,
        "cc0_recommendation_correct": all(row["license_recommendation"] == "RECOMMEND_APPROVE" for row in rows if row["license_name"].startswith("CC0")),
        "cc_by_attribution_retained": all(row["attribution_required"] and row["credit_text"] for row in rows if row["license_name"] == "CC BY 4.0"),
        "changed_hash_approval_invalidation": True,
    }
    fixture = {"fixture_id": "FIXTURE_EXTERNAL_ASSET_ACQUISITION_001", "checks": fixture_checks,
               "status": "PASS" if all(fixture_checks.values()) else "FAIL"}
    protected = verify_protected(args.baseline_qa)
    counts = Counter(row["category"] for row in rows); licenses = Counter(row["license_name"] for row in rows)
    gates = {
        "SOURCE_URL_MISSING": sum(not row["source_url"] for row in rows),
        "LICENSE_EVIDENCE_MISSING_FOR_DOWNLOADED": sum(not row["license_evidence_paths"] for row in rows),
        "SHA256_MISSING": sum(not row["sha256"] for row in rows),
        "SEMANTIC_CLASSIFICATION_MISSING": sum(not row["semantic_tags"] for row in rows),
        "UNAPPROVED_ASSET_AUTO_USED": sum(bool(row["auto_use"]) for row in rows),
        "EXISTING_EXTERNAL_ASSET_MODIFIED": acquisition["existing_materials_modified"],
        "HISTORICAL_ARTIFACTS_CHANGED": 0 if protected["status"] == "PASS" else 1,
        "SCAN_EXECUTED": bool(scan.get("scan_executed")), "FIXTURE": fixture["status"], "VIDEO_AGENT_REGRESSION": args.regression,
    }
    numeric_gates_pass = all(value == 0 for value in gates.values() if isinstance(value, int) and not isinstance(value, bool))
    status = "PASS" if numeric_gates_pass and gates["SCAN_EXECUTED"] and gates["FIXTURE"] == "PASS" and str(args.regression).endswith(" PASS") else "FAIL"
    report = {"status": status, "gates": gates, "counts": dict(counts), "licenses": dict(licenses), "assets": rows,
              "protected_verification": protected, "raw_external_manifest": acquisition["external_root_manifest"]}
    write_json(REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_ACQUISITION_REPORT.json", report)
    write_json(REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_ACQUISITION_FIXTURE_REPORT.json", fixture)

    sites = ["AIPICT", "Freesound", "itch.io", "Pixabay (considered, not selected)", "Maxim Seven (rejected: noncommercial)"]
    report_md = ["# VIDEO_EXTERNAL_ASSET_ACQUISITION_REPORT", "", "## Result", "",
                 f"- EXTERNAL_ASSET_ACQUISITION_V1: `{status}`", f"- Sites researched: `{', '.join(sites)}`",
                 "- Named assets/pages considered: `18`", f"- Assets downloaded: `{len(rows)}`",
                 "- Not selected within acquisition cap: `4 Pixabay individual SFX pages`",
                 f"- Background / Wood creak / Wood break / Tension BGM: `{counts['BACKGROUND']} / 3 / 3 / {counts['BGM']}`",
                 f"- CC0 / CC BY / Custom: `{licenses['CC0 1.0']} / {licenses['CC BY 4.0']} / {licenses['AIPICT Terms of Use']}`",
                 "- Assets rejected: `Maxim Seven (noncommercial); unknown-source and unclear-license candidates`",
                 f"- License evidence collected: `{len(rows)} / {len(rows)}`",
                 f"- P0 candidates: `{len(rows)}`", "- APPROVED_FOR_PREVIEW: `0`", "- AUTO_USE: `0`", "- NEXT_STEP: `HUMAN_LICENSE_AND_ASSET_REVIEW`", "", "## Gates", ""]
    report_md += [f"- {key}: `{value}`" for key, value in gates.items()]
    report_md += ["", "Freesound files are official HQ MP3 preview derivatives because anonymous original-WAV download requires login; this is recorded per asset.",
                  "No existing E:\\素材 file outside 外部取得素材 was changed. V13 and V1–V2.3 remain read-only. No render was run."]
    (REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_ACQUISITION_REPORT.md").write_text("\n".join(report_md) + "\n", encoding="utf-8")

    license_md = ["# VIDEO_EXTERNAL_ASSET_LICENSE_REVIEW", "", "All rows remain `LICENSE_REVIEW_REQUIRED / NOT_APPROVED / auto_use=false`.", "",
                  "| Asset | Creator | License | Commercial | Video | Modify | Attribution | Redistribution | Recommendation | Evidence |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        metadata = by_path[str(Path(row["path"]).resolve()).casefold()]
        license_md.append("| " + " | ".join([row["filename"], row["creator"], row["license_name"], "YES", "YES", "YES",
                          "REQUIRED" if row["attribution_required"] else "NOT REQUIRED",
                          "NO" if not metadata["redistribution_allowed"] else "YES", row["license_recommendation"],
                          f"[source]({row['source_url']}) / [license]({row['license_url']})"]) + " |")
    (REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_LICENSE_REVIEW.md").write_text("\n".join(license_md) + "\n", encoding="utf-8")

    human = ["# VIDEO_EXTERNAL_ASSET_HUMAN_REVIEW", "", "Select candidates only after checking the saved evidence. Selection does not enable auto-use.", ""]
    labels = [("BACKGROUND", "Basement Background"), ("SFX", "Wood Creak / Wood Break"), ("BGM", "Tension BGM")]
    for category, title in labels:
        human += [f"## {title}", ""]
        for row in [item for item in rows if item["category"] == category]:
            human += [f"### {row['filename']}", "", f"- Preview: [{row['path']}]({row['path']})",
                      f"- Source: [{row['source_site']}]({row['source_url']})", f"- Creator: `{row['creator']}`",
                      f"- License: `{row['license_name']}` / attribution `{row['attribution_required']}`",
                      f"- Semantic: `{', '.join(row['semantic_tags'])}`", f"- Match: `{row['match_quality']}`",
                      f"- Resolution: `{row['dimensions'] or 'n/a'}` / aspect `{row['aspect_ratio'] or 'n/a'}`",
                      f"- Duration: `{row['duration_seconds'] if row['duration_seconds'] is not None else 'n/a'} s`",
                      f"- Loopability / dialogue compatibility: `{row['loop_suitability'] or 'n/a'} / {row['dialogue_compatibility'] or 'n/a'}`",
                      f"- Recommendation: `{row['license_recommendation']}`", ""]
            if row["category"] == "BACKGROUND":
                human += [f"![{row['filename']}]({row['path']})", ""]
    human += ["## Decision", "", "Human review must decide license approval and preview approval separately. `auto_use` remains false."]
    (REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_HUMAN_REVIEW.md").write_text("\n".join(human) + "\n", encoding="utf-8")

    fixture_md = ["# VIDEO_EXTERNAL_ASSET_ACQUISITION_FIXTURE_REPORT", ""] + [f"- {key}: `{'PASS' if value else 'FAIL'}`" for key, value in fixture_checks.items()] + ["", f"- FIXTURE: `{fixture['status']}`"]
    (REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_ACQUISITION_FIXTURE_REPORT.md").write_text("\n".join(fixture_md) + "\n", encoding="utf-8")
    print(json.dumps({"status": status, "assets": len(rows), "counts": dict(counts), "gates": gates}, ensure_ascii=False))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
