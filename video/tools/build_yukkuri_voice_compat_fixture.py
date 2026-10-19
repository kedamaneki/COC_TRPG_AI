from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_agent.voice.engines import AquesTalkAdapter
from video_agent.voice.yukkuri_voice_compat import (FIXTURE_TEXT, build_candidate_profile,
    measure_loudness, measure_wav, render_baseline_fixture, render_exact_fixture, validate_source_profiles)


BASELINE = {"reimu": "m1_aq_f1", "marisa": "aq_marisa_default", "sakuya": "aq_kp_sakuya_v21"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.video_root.resolve(), args.output.resolve()
    config = json.loads((root / "config/render_m1.json").read_text(encoding="utf-8"))
    document = json.loads((root / "config/voice_profiles.json").read_text(encoding="utf-8"))
    profiles = {item["voice_profile_id"]: item for item in document["profiles"]}
    errors = validate_source_profiles(profiles)
    if errors:
        raise SystemExit(";".join(errors))
    adapter = AquesTalkAdapter(output / ".cache", dll_root=Path(config["aquestalk_dll_root"]),
                              bridge_source=root / "src/video_agent/voice/AquesTalkBridge.cs",
                              bridge_exe=output / ".tools/AquesTalkBridge.exe", csc_path=Path(config["csc_path"]))
    ffmpeg = Path(config["ffmpeg_path"])
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for character_id in ("reimu", "marisa", "sakuya"):
        baseline = profiles[BASELINE[character_id]]
        candidate = profiles[f"ymm_exact_{character_id}_v1"]
        baseline_path = output / f"{character_id}_baseline.wav"
        exact_path = output / f"{character_id}_exact.wav"
        baseline_render = render_baseline_fixture(adapter, ffmpeg, FIXTURE_TEXT, baseline, baseline_path)
        exact_render = render_exact_fixture(adapter, ffmpeg, FIXTURE_TEXT, candidate, exact_path)
        records.append({"character_id": character_id, "fixture_text_phonetic": FIXTURE_TEXT,
                        "baseline_profile_id": baseline["voice_profile_id"],
                        "exact_profile_id": candidate["voice_profile_id"],
                        "baseline": {"render": baseline_render, "measurement": {
                            **measure_wav(baseline_path), **measure_loudness(ffmpeg, baseline_path)}},
                        "exact": {"render": exact_render, "measurement": {
                            **measure_wav(exact_path), **measure_loudness(ffmpeg, exact_path)}}})
    manifest = {"fixture_id": "FIXTURE_YMM4_VOICE_COMPAT_001", "status": "PASS", "records": records,
                "human_review": "PENDING", "active_mapping_changed": False,
                "pure_direct_ymm_reference": "REFERENCE_NOT_AVAILABLE"}
    (output / "fixture_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "files": len(records) * 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
