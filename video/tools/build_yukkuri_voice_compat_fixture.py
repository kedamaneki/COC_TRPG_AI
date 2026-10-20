from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_agent.voice.yukkuri_voice_compat import (
    generate_compatibility_fixtures, portable_fixture_manifest,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.video_root.resolve(), args.output.resolve()
    document = json.loads((root / "config/voice_profiles.json").read_text(encoding="utf-8"))
    profiles = {item["voice_profile_id"]: item for item in document["profiles"]}
    records = generate_compatibility_fixtures(root, output, profiles)
    manifest = portable_fixture_manifest(records, output)
    (output / "fixture_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "files": len(records) * 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
