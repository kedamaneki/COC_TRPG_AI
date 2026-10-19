from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
VIDEO_SRC = REPO_ROOT / "video" / "src"
if str(VIDEO_SRC) not in sys.path:
    sys.path.insert(0, str(VIDEO_SRC))

from video_agent.assets.external_acquisition import acquire, sha256_file  # noqa: E402


def tree_digest(root: Path, *, exclude: Path | None = None) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    exclude_resolved = exclude.resolve() if exclude else None
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().casefold()):
        if exclude_resolved:
            try:
                path.resolve().relative_to(exclude_resolved)
                continue
            except ValueError:
                pass
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8")); digest.update(b"\0"); digest.update(sha256_file(path).encode("ascii")); digest.update(b"\n")
        count += 1
    return count, digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire the reviewed External Asset Acquisition v1 candidate set.")
    default_root = Path(os.environ.get("VIDEO_ASSET_ROOT", "assets-external"))
    parser.add_argument("--materials-root", type=Path, default=default_root)
    parser.add_argument("--output-root", type=Path, default=default_root / "外部取得素材")
    parser.add_argument("--report", type=Path, default=REPO_ROOT / "docs" / "VIDEO_EXTERNAL_ASSET_ACQUISITION_RAW.json")
    args = parser.parse_args()
    before = tree_digest(args.materials_root, exclude=args.output_root)
    result = acquire(args.output_root)
    after = tree_digest(args.materials_root, exclude=args.output_root)
    result["existing_materials_before"] = {"file_count": before[0], "aggregate_sha256": before[1]}
    result["existing_materials_after"] = {"file_count": after[0], "aggregate_sha256": after[1]}
    result["existing_materials_modified"] = 0 if before == after else 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"asset_count": result["asset_count"], "existing_materials_modified": result["existing_materials_modified"],
                      "external_file_count": result["external_root_manifest"]["file_count"]}, ensure_ascii=False))
    return 0 if result["existing_materials_modified"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
