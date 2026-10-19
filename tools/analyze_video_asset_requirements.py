from __future__ import annotations

import argparse
import json
from pathlib import Path


MATCH_RANK = {"EXACT": 3, "FAMILY": 2, "GENERIC": 1, "NONE": 0}


def analyze_requirements(requirements: list[dict], assets: list[dict]) -> dict:
    results: list[dict] = []
    for requirement in requirements:
        candidates = []
        for asset in assets:
            if asset.get("requirement_types", [asset.get("asset_type")]) and requirement["asset_type"] not in asset.get(
                    "requirement_types", [asset.get("asset_type")]):
                continue
            semantic_match = requirement.get("semantic") in asset.get("semantics", []) if requirement.get("semantic") else False
            location = requirement.get("location_id")
            if location and location == asset.get("location_id"):
                match = "EXACT"
            elif location and location in asset.get("location_family_ids", []):
                match = "FAMILY"
            elif semantic_match or asset.get("generic_environment"):
                match = "GENERIC"
            elif not location and not requirement.get("semantic"):
                match = "GENERIC"
            else:
                continue
            candidate = dict(asset)
            candidate["match_type"] = match
            candidates.append(candidate)
        candidates.sort(key=lambda item: (MATCH_RANK[item["match_type"]], str(item.get("approval_status", "")).startswith("APPROVED")), reverse=True)
        selected = candidates[0] if candidates else None
        available = selected is not None and Path(selected["path"]).exists()
        approved = bool(selected and str(selected.get("approval_status", "")).startswith("APPROVED"))
        match_quality = "MISSING" if not available else "SUFFICIENT" if selected["match_type"] in {"EXACT", "FAMILY"} else "WEAK_MATCH"
        blocking = requirement.get("priority") == "REQUIRED" and (not available or not approved)
        results.append({**requirement, "available": available, "approved": approved,
                        "match_quality": match_quality, "blocking": blocking,
                        "selected_asset_id": selected.get("asset_id") if selected else None,
                        "candidate_asset_ids": [item.get("asset_id") for item in candidates],
                        "not_selected_reasons": {item.get("asset_id"): "LOWER_MATCH_PRIORITY" for item in candidates[1:]}})
    critical = sum(item["blocking"] for item in results)
    by_type = {}
    for asset_type in sorted({item["asset_type"] for item in requirements}):
        group = [item for item in results if item["asset_type"] == asset_type and item.get("priority") != "OPTIONAL"]
        by_type[asset_type] = 1.0 if not group else sum(item["available"] and item["approved"] for item in group) / len(group)
    return {"status": "PASS" if critical == 0 else "FAIL", "requirements": results,
            "critical_asset_missing": critical, "coverage": by_type,
            "object_visual_required": False, "kp_description_required": True}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("requirements", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    requirements = json.loads(args.requirements.read_text(encoding="utf-8-sig"))
    assets = json.loads(args.assets.read_text(encoding="utf-8-sig"))
    report = analyze_requirements(requirements["requirements"], assets["assets"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "critical_asset_missing": report["critical_asset_missing"]}))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
