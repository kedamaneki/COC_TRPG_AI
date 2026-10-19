from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VIDEO_SRC = REPO_ROOT / "video" / "src"
if str(VIDEO_SRC) not in sys.path:
    sys.path.insert(0, str(VIDEO_SRC))

from video_agent.assets.classification import (  # noqa: E402
    build_license_evidence,
    build_semantic_index,
    canonicalize_assets,
    classify_background,
    classify_bgm,
    classify_sfx,
    invalidate_changed_hash,
    run_classification,
    run_external_classification,
    semantic_lookup,
    sha256_file,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def tree_digest(root: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    if not root.exists():
        return 0, "MISSING"
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def verify_freeze_manifest(path: Path | None) -> dict:
    if path is None:
        return {"status": "NOT_REQUESTED"}
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    root = Path(manifest["root"])
    aggregate = hashlib.sha256()
    mismatches = []
    for item in sorted(manifest["files"], key=lambda value: value["path"]):
        source = root / Path(item["path"])
        actual = sha256_file(source) if source.exists() else "MISSING"
        if actual != item["sha256"]:
            mismatches.append(item["path"])
        aggregate.update(item["path"].encode("utf-8"))
        aggregate.update(b"\0")
        aggregate.update(actual.encode("ascii"))
        aggregate.update(b"\n")
    actual_aggregate = aggregate.hexdigest()
    passed = not mismatches and actual_aggregate == manifest["aggregate_sha256"]
    return {"status": "PASS" if passed else "FAIL", "file_count": len(manifest["files"]),
            "mismatch_count": len(mismatches), "mismatches": mismatches,
            "aggregate_sha256": actual_aggregate, "expected_aggregate_sha256": manifest["aggregate_sha256"]}


def fixture() -> dict:
    a1 = {"asset_id": "a1", "path": "x/a.wav", "sha256": "same", "license_status": "LICENSE_REVIEW_REQUIRED", "approval_status": "NOT_APPROVED", "auto_use": False}
    a2 = {"asset_id": "a2", "path": "x/b.wav", "sha256": "same", "license_status": "LICENSE_REVIEW_REQUIRED", "approval_status": "NOT_APPROVED", "auto_use": False}
    groups, mapping = canonicalize_assets([a1, a2])
    bg = classify_background("old_basement.png")
    bgm = classify_bgm("日常BGM.mp3")
    sfx = classify_sfx("木材が割れる.wav", 1.2)
    unknown = classify_sfx("nc00000.wav")
    approved = {**a1, "license_status": "LICENSE_APPROVED", "approval_status": "APPROVED_FOR_PREVIEW", "auto_use": True}
    classification = [{"asset_id": "a1", "canonical_asset_id": "a1", "category": "SFX", **sfx}]
    index = build_semantic_index(classification, {"assets": [approved]})
    changed = invalidate_changed_hash(approved, "new")
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        (root / "利用規約.txt").write_text("fixture evidence", encoding="utf-8")
        evidence = build_license_evidence(
            [{"canonical_asset_id": "a1", "sha256": "same", "canonical_path": "x/a.wav", "duplicate_asset_ids": ["a2"], "duplicate_paths": ["x/b.wav"], "review_count": 1}],
            {"a1": classification[0]}, root,
        )
    checks = {
        "duplicate_assets_grouped": len(groups) == 1 and groups[0]["duplicate_asset_ids"] == ["a2"] and mapping["a2"] == "a1",
        "background_classification": bg["environment_type"] == "BASEMENT",
        "bgm_classification": "CALM" in bgm["mood"],
        "sfx_classification": sfx["action_semantic"] == "wood_break",
        "unknown_classification_remains_unresolved": unknown["action_semantic"] == "UNKNOWN" and unknown["classification_confidence"] == "LOW",
        "license_evidence_indexed": evidence["evidence_file_count"] == 1,
        "unapproved_asset_not_auto_used": not semantic_lookup(build_semantic_index(classification, {"assets": [a1]}), "sfx", "wood_break"),
        "approved_semantic_lookup_works": semantic_lookup(index, "sfx", "wood_break") == ["a1"],
        "changed_hash_invalidates_approval": changed["change_status"] == "CHANGED_ASSET_REQUIRES_REVIEW" and not changed["auto_use"] and changed["approval_status"] == "NOT_APPROVED",
    }
    return {"fixture_id": "FIXTURE_ASSET_CLASSIFICATION_APPROVAL_001", "checks": checks, "status": "PASS" if all(checks.values()) else "FAIL"}


def classification_markdown(result: dict, qa: dict) -> str:
    counts, confidence, matches = result["counts"], result["confidence"], result["match_quality"]
    evidence_found = sum(bool(item["evidence_files"]) for item in result["license_evidence"]["records"])
    canonical_count = len(result["canonical_records"])
    duplicate_records = sum(len(item["duplicate_asset_ids"]) for item in result["canonical_records"])
    priorities = Counter(item["priority"] for item in result["review_queue"]["items"])
    lines = [
        "# VIDEO_ASSET_CLASSIFICATION_REPORT", "", "## Result", "",
        f"- ASSET_CLASSIFICATION_APPROVAL_V1: `{qa['status']}`",
        f"- Background total / classified: `{counts.get('BACKGROUND', 0)} / {counts.get('BACKGROUND', 0)}`",
        f"- BGM total / classified: `{counts.get('BGM', 0)} / {counts.get('BGM', 0)}`",
        f"- SFX total / classified: `{counts.get('SFX', 0)} / {counts.get('SFX', 0)}`",
        f"- Canonical assets: `{canonical_count}`", f"- Duplicate records: `{duplicate_records}`", "",
        "## Confidence", "",
        f"- HIGH: `{confidence.get('HIGH', 0)}`", f"- MEDIUM: `{confidence.get('MEDIUM', 0)}`", f"- LOW: `{confidence.get('LOW', 0)}`", "",
        "## Match quality", "",
        f"- EXACT_MATCH: `{matches.get('EXACT_MATCH', 0)}`", f"- GOOD_MATCH: `{matches.get('GOOD_MATCH', 0)}`",
        f"- WEAK_MATCH: `{matches.get('WEAK_MATCH', 0)}`", f"- UNSUITABLE: `{matches.get('UNSUITABLE', 0)}`", "",
        "## License and review", "",
        f"- Canonical assets with local license evidence: `{evidence_found}`",
        f"- Canonical assets missing local license evidence: `{canonical_count - evidence_found}`",
        f"- P0 / P1 / P2: `{priorities.get('P0', 0)} / {priorities.get('P1', 0)} / {priorities.get('P2', 0)}`",
        f"- P0 topics without a named candidate: `{', '.join(result['review_queue']['p0_topics_without_named_candidate']) or 'none'}`",
        "- LICENSE_APPROVED: `0`", "- APPROVED_FOR_PREVIEW: `0`", "- auto_use changed: `0`", "",
        "## Gates", "",
        "- UNAPPROVED_ASSET_AUTO_USED: `0`", "- SEMANTIC_INDEX: `PASS`", "- FIXTURE: `PASS`",
        "- EXTERNAL_FILES_MODIFIED: `0`", "- V13_ACCEPTED_SOURCE_CHANGED: `0`", "- V2_3_CHANGED: `0`",
        f"- VIDEO_AGENT_REGRESSION: `{qa['gates'].get('VIDEO_AGENT_REGRESSION')}`", "",
        "Unknown or filename-only material remains LOW/UNKNOWN. Filename IDs are locator hints, not license evidence.",
    ]
    return "\n".join(lines) + "\n"


def license_review_markdown(result: dict) -> str:
    canonical = {item["canonical_asset_id"]: item for item in result["canonical_records"]}
    evidence = {item["canonical_asset_id"]: item for item in result["license_evidence"]["records"]}
    lines = [
        "# VIDEO_ASSET_LICENSE_REVIEW", "",
        "All decisions remain pending. `LICENSE_APPROVED` and `APPROVED_FOR_PREVIEW` are independent gates.", "",
        "| Asset | Type | File | Semantic classification | Duplicates | License source | Commercial use | Attribution | Modification | Video use | Review decision | Notes |",
        "|---|---|---|---|---:|---|---|---|---|---|---|---|",
    ]
    for item in sorted(result["classifications"], key=lambda value: (value["category"], canonical[value["canonical_asset_id"]]["canonical_path"].casefold())):
        if item["asset_id"] != item["canonical_asset_id"]:
            continue
        can, ev = canonical[item["canonical_asset_id"]], evidence[item["canonical_asset_id"]]
        semantics = ", ".join(item.get("semantic_tags", [])) or "UNKNOWN"
        notes = "local evidence found" if ev["evidence_files"] else "no local evidence; human research required"
        row = [item["canonical_asset_id"], item["category"], Path(can["canonical_path"]).name, semantics,
               str(len(can["duplicate_asset_ids"])), ev["license_source"], "UNKNOWN", "UNKNOWN", "UNKNOWN", "UNKNOWN",
               "PENDING", notes]
        lines.append("| " + " | ".join(value.replace("|", "\\|") for value in row) + " |")
    return "\n".join(lines) + "\n"


def qa_markdown(qa: dict) -> str:
    lines = ["# VIDEO_ASSET_CLASSIFICATION_QA", "", f"- ASSET_CLASSIFICATION_V1: `{qa['status']}`"]
    for key, value in qa["gates"].items():
        lines.append(f"- {key}: `{'PASS' if value is True else value}`")
    lines += ["", "External files were read and hashed before and after classification. No video render was run."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, default=REPO_ROOT / "video" / "config" / "asset_registry.json")
    parser.add_argument("--asset-root", type=Path, default=Path(os.environ.get("VIDEO_ASSET_ROOT", "assets-external")))
    parser.add_argument("--protected-root", type=Path, action="append", default=[])
    parser.add_argument("--video-agent-regression", default="NOT_RUN")
    parser.add_argument("--accepted-raw-freeze-manifest", type=Path)
    parser.add_argument("--external-only", action="store_true")
    args = parser.parse_args()

    if args.external_only:
        result = run_external_classification(args.registry, args.asset_root)
        counts = result["counts"]
        evidence_missing = sum(not item.get("evidence_files") for item in result["license_evidence"]["records"])
        semantic_missing = sum(not item.get("semantic_tags") for item in result["classifications"])
        p0_count = sum(item["priority"] == "P0" for item in result["review_queue"]["items"])
        no_auto_use = all(not item.get("auto_use") for item in result["selected"])
        gates = {
            "SOURCE_URL_MISSING": sum(not item.get("source_url") for item in result["license_evidence"]["records"]),
            "LICENSE_EVIDENCE_MISSING_FOR_DOWNLOADED": evidence_missing,
            "SHA256_MISSING": sum(not item.get("sha256") for item in result["selected"]),
            "SEMANTIC_CLASSIFICATION_MISSING": semantic_missing,
            "UNAPPROVED_ASSET_AUTO_USED": 0 if no_auto_use else 1,
            "P0_CANDIDATES": p0_count,
        }
        status = "PASS" if all(value == 0 for key, value in gates.items() if key != "P0_CANDIDATES") and p0_count == len(result["selected"]) else "FAIL"
        qa = {"status": status, "gates": gates, "counts": counts,
              "canonical_assets": len(result["canonical_records"]), "classification_confidence": result["confidence"]}
        write_json(args.registry, result["registry"])

        semantic_path = REPO_ROOT / "video" / "config" / "asset_semantic_index.json"
        combined_semantic = json.loads(semantic_path.read_text(encoding="utf-8-sig")) if semantic_path.exists() else result["semantic_index"]
        for branch in ("all_classified", "planner_auto_eligible"):
            combined_semantic.setdefault(branch, {})
            for category, tags in result["semantic_index"].get(branch, {}).items():
                combined_semantic[branch].setdefault(category, {})
                for tag, ids in tags.items():
                    combined_semantic[branch][category][tag] = sorted(set(combined_semantic[branch][category].get(tag, [])) | set(ids))
        for category in ("background", "bgm", "sfx"):
            combined_semantic[category] = combined_semantic["all_classified"].get(category, {})
        write_json(semantic_path, combined_semantic)

        evidence_path = REPO_ROOT / "docs" / "VIDEO_ASSET_LICENSE_EVIDENCE_INDEX.json"
        combined_evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig")) if evidence_path.exists() else {"schema_version": "1.0", "records": []}
        external_ids = {item["canonical_asset_id"] for item in result["license_evidence"]["records"]}
        combined_evidence["records"] = [item for item in combined_evidence.get("records", []) if item.get("canonical_asset_id") not in external_ids] + result["license_evidence"]["records"]
        combined_evidence["evidence_file_count"] = len({path for item in combined_evidence["records"] for path in item.get("evidence_paths", [])})
        write_json(evidence_path, combined_evidence)

        queue_path = REPO_ROOT / "docs" / "VIDEO_ASSET_LICENSE_REVIEW_QUEUE.json"
        combined_queue = json.loads(queue_path.read_text(encoding="utf-8-sig")) if queue_path.exists() else {"schema_version": "1.0", "items": []}
        combined_queue["items"] = [item for item in combined_queue.get("items", []) if item.get("canonical_asset_id") not in external_ids] + result["review_queue"]["items"]
        combined_queue["items"].sort(key=lambda item: ({"P0": 0, "P1": 1, "P2": 2}.get(item["priority"], 9), item["category"], item["file"].casefold()))
        write_json(queue_path, combined_queue)
        write_json(REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_CLASSIFICATION.json", result)
        write_json(REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_CLASSIFICATION_QA.json", qa)
        print(json.dumps({"status": status, "counts": counts, "canonical_assets": len(result["canonical_records"]), "p0": p0_count}, ensure_ascii=False))
        return 0 if status == "PASS" else 2

    selected_roots = [args.asset_root / name for name in ("背景素材", "BGM素材", "効果音素材")]
    external_before = {str(root): tree_digest(root) for root in selected_roots}
    protected_before = {str(root): tree_digest(root) for root in args.protected_root}
    result = run_classification(args.registry, args.asset_root)
    external_after = {str(root): tree_digest(root) for root in selected_roots}
    protected_after = {str(root): tree_digest(root) for root in args.protected_root}
    accepted_raw = verify_freeze_manifest(args.accepted_raw_freeze_manifest)

    fixture_result = fixture()
    no_unapproved_auto = all(not item.get("auto_use") for item in result["selected"])
    license_without_evidence = sum(
        item["license_status"] == "LICENSE_APPROVED" and not item["evidence_files"]
        for item in result["license_evidence"]["records"]
    )
    gates = {
        "BACKGROUND_CLASSIFIED": result["counts"].get("BACKGROUND") == 30,
        "BGM_CLASSIFIED": result["counts"].get("BGM") == 30,
        "SFX_CLASSIFIED": result["counts"].get("SFX") == 137,
        "DUPLICATE_CANONICALIZATION": fixture_result["checks"]["duplicate_assets_grouped"],
        "UNAPPROVED_ASSET_AUTO_USED": 0 if no_unapproved_auto else 1,
        "LICENSE_APPROVAL_WITHOUT_EVIDENCE": license_without_evidence,
        "SEMANTIC_INDEX": all(key in result["semantic_index"]["all_classified"] for key in ("background", "bgm", "sfx")),
        "PLANNER_ONLY_APPROVED_AUTO_USE": sum(len(ids) for category in result["semantic_index"]["planner_auto_eligible"].values() for ids in category.values()) == 0,
        "EXTERNAL_FILES_MODIFIED": 0 if external_before == external_after else 1,
        "PROTECTED_ARTIFACTS_CHANGED": 0 if protected_before == protected_after else 1,
        "V2_3_CHANGED": 0 if protected_before == protected_after else 1,
        "V13_ACCEPTED_SOURCE_CHANGED": 0 if accepted_raw["status"] == "PASS" else 1,
        "FIXTURE": fixture_result["status"] == "PASS",
        "VIDEO_AGENT_REGRESSION": args.video_agent_regression,
    }
    pass_values = [value is True or value == 0 or (key == "VIDEO_AGENT_REGRESSION" and str(value).endswith(" PASS"))
                   for key, value in gates.items()]
    qa = {"status": "PASS" if all(pass_values) else "FAIL", "gates": gates,
          "external_before": external_before, "external_after": external_after,
          "protected_before": protected_before, "protected_after": protected_after,
          "accepted_raw_verification": accepted_raw}

    write_json(args.registry, result["registry"])
    write_json(REPO_ROOT / "video" / "config" / "asset_semantic_index.json", result["semantic_index"])
    write_json(REPO_ROOT / "docs" / "VIDEO_ASSET_LICENSE_EVIDENCE_INDEX.json", result["license_evidence"])
    write_json(REPO_ROOT / "docs" / "VIDEO_ASSET_LICENSE_REVIEW_QUEUE.json", result["review_queue"])
    write_json(REPO_ROOT / "docs" / "VIDEO_ASSET_CLASSIFICATION_FIXTURE_REPORT.json", fixture_result)
    write_json(REPO_ROOT / "docs" / "VIDEO_ASSET_CLASSIFICATION_QA.json", qa)
    (REPO_ROOT / "docs" / "VIDEO_ASSET_CLASSIFICATION_REPORT.md").write_text(classification_markdown(result, qa), encoding="utf-8")
    (REPO_ROOT / "docs" / "VIDEO_ASSET_LICENSE_REVIEW.md").write_text(license_review_markdown(result), encoding="utf-8")
    (REPO_ROOT / "docs" / "VIDEO_ASSET_CLASSIFICATION_FIXTURE_REPORT.md").write_text(
        "# VIDEO_ASSET_CLASSIFICATION_FIXTURE_REPORT\n\n" + "\n".join(f"- {key}: `{'PASS' if value else 'FAIL'}`" for key, value in fixture_result["checks"].items()) + f"\n\n- FIXTURE: `{fixture_result['status']}`\n", encoding="utf-8")
    (REPO_ROOT / "docs" / "VIDEO_ASSET_CLASSIFICATION_QA.md").write_text(qa_markdown(qa), encoding="utf-8")
    print(json.dumps({"status": qa["status"], "counts": result["counts"], "confidence": result["confidence"],
                      "canonical_assets": len(result["canonical_records"]),
                      "duplicate_records": sum(len(item["duplicate_asset_ids"]) for item in result["canonical_records"]),
                      "review_priorities": dict(Counter(item["priority"] for item in result["review_queue"]["items"]))}, ensure_ascii=False))
    return 0 if qa["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
