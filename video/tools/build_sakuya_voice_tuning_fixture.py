from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from video_agent.voice.engines import AquesTalkAdapter
from video_agent.voice.sakuya_voice_tuning import (ANONYMOUS_ASSIGNMENT, FIXTURE_LINES,
    TUNING_PROFILE_IDS, TUNING_RATES, validate_tuning_profiles)
from video_agent.voice.yukkuri_voice_compat import measure_loudness, measure_wav, render_exact_fixture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.video_root.resolve(), args.output.resolve()
    config = json.loads((root / "config/render_m1.json").read_text(encoding="utf-8"))
    document = json.loads((root / "config/voice_profiles.json").read_text(encoding="utf-8"))
    profiles = {item["voice_profile_id"]: item for item in document["profiles"]}
    errors = validate_tuning_profiles(profiles)
    if errors:
        raise SystemExit(";".join(errors))
    output.mkdir(parents=True, exist_ok=True)
    adapter = AquesTalkAdapter(output / ".cache", dll_root=Path(config["aquestalk_dll_root"]),
                              bridge_source=root / "src/video_agent/voice/AquesTalkBridge.cs",
                              bridge_exe=output / ".tools/AquesTalkBridge.exe", csc_path=Path(config["csc_path"]))
    ffmpeg = Path(config["ffmpeg_path"])
    records = []
    rate_outputs: dict[tuple[int, str], Path] = {}
    for rate in TUNING_RATES:
        profile = profiles[TUNING_PROFILE_IDS[rate]]
        for line_id, line in FIXTURE_LINES.items():
            path = output / f"sakuya_{rate}_{line_id}.wav"
            render = render_exact_fixture(adapter, ffmpeg, line["synthesis_text"], profile, path)
            measurement = {**measure_wav(path), **measure_loudness(ffmpeg, path)}
            rate_outputs[(rate, line_id)] = path
            records.append({"rate_percent": rate, "profile_id": profile["voice_profile_id"],
                            "line_id": line_id, "display_text": line["display_text"],
                            "synthesis_text": line["synthesis_text"], "render": render,
                            "measurement": measurement})
    anonymous_records = []
    for label, rate in ANONYMOUS_ASSIGNMENT.items():
        for line_id in FIXTURE_LINES:
            source = rate_outputs[(rate, line_id)]
            destination = output / f"sakuya_{label}_{line_id}.wav"
            shutil.copyfile(source, destination)
            anonymous_records.append({"candidate": label, "line_id": line_id,
                                      "path": str(destination), "measurement": measure_wav(destination)})
    public_manifest = {
        "fixture_id": "FIXTURE_SAKUYA_TUNING_001", "status": "PASS",
        "candidate_labels": list(ANONYMOUS_ASSIGNMENT), "line_ids": list(FIXTURE_LINES),
        "voice_type_all": "f1", "reading_speed_all": 105, "source_volume_all": 50,
        "pitch_speed_coupling": "PASS", "pitch_preserving_process_count": 0,
        "active_mapping_changed": False, "auto_use": False,
        "human_review": "PENDING", "anonymous_records": anonymous_records,
    }
    mapping_manifest = {
        "fixture_id": "FIXTURE_SAKUYA_TUNING_001", "mapping": ANONYMOUS_ASSIGNMENT,
        "profile_by_rate": TUNING_PROFILE_IDS,
        "notice": "Keep this mapping separate while conducting blind review.",
    }
    technical_manifest = {
        "fixture_id": "FIXTURE_SAKUYA_TUNING_001", "status": "PASS", "records": records,
        "playback_rates": list(TUNING_RATES), "human_review": "PENDING",
    }
    (output / "fixture_manifest.json").write_text(json.dumps(public_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "anonymous_mapping_manifest.json").write_text(json.dumps(mapping_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "technical_manifest.json").write_text(json.dumps(technical_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "rate_labeled_wavs": len(records),
                      "anonymous_wavs": len(anonymous_records)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

