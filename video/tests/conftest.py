"""Create deterministic ignored media fixtures required by the historical suite.

The real previews and synthesized voices are intentionally excluded from Git.  A Fresh Clone
must nevertheless be able to execute the complete test suite, so pytest recreates only the
minimal media that tests inspect.  These files are test data, not accepted video artifacts.
"""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path


VIDEO_ROOT = Path(__file__).resolve().parents[1]


def _write_tone(path: Path, duration_sec: float, frequency_hz: float = 440.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 16_000
    frame_count = max(1, int(round(duration_sec * rate)))
    amplitude = 8_000
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        samples = (
            struct.pack("<h", int(amplitude * math.sin(2.0 * math.pi * frequency_hz * index / rate)))
            for index in range(frame_count)
        )
        stream.writeframes(b"".join(samples))


def _ensure_voice_fixtures() -> None:
    project = VIDEO_ROOT / "projects" / "m3_scene_preview"
    timeline = json.loads((project / "video_timeline.json").read_text(encoding="utf-8"))
    for clip in timeline["clips"]:
        voice_file = clip.get("voice_file")
        if clip.get("presentation_mode") != "VOICED" or not voice_file:
            continue
        destination = project / voice_file
        if not destination.exists():
            _write_tone(destination, max(0.01, float(clip["duration_sec"]) - 0.001))

    known_bad = VIDEO_ROOT / "tests" / "fixtures" / "known_bad_blank_voice.wav"
    if not known_bad.exists():
        _write_tone(known_bad, 0.15, frequency_hz=7_000.0)


def _ensure_existence_only_video_fixtures() -> None:
    review = VIDEO_ROOT / "projects" / "m3_scene_preview" / "review"
    review.mkdir(parents=True, exist_ok=True)
    names = (
        "m3_scene_preview.mp4",
        "m3_scene_preview_before_iteration.mp4",
        "m3_scene_preview_after_iteration.mp4",
        "m3_scene_preview_before_iteration2.mp4",
        "m3_scene_preview_after_iteration2.mp4",
        "m3_scene_preview_before_iteration3.mp4",
        "m3_scene_preview_after_iteration3.mp4",
        "m3_scene_preview_before_iteration4.mp4",
        "m3_scene_preview_after_iteration4.mp4",
        "m3_scene_preview_before_iteration5.mp4",
        "m3_scene_preview_after_iteration5.mp4",
        "m3_knife_encounter_preview.mp4",
        "m3_final_battle_preview.mp4",
    )
    for name in names:
        (review / name).touch(exist_ok=True)

    for project_name in ("m1_synthetic", "m1_real_session"):
        project = VIDEO_ROOT / "projects" / project_name
        manifest = json.loads((project / "render_manifest.json").read_text(encoding="utf-8"))
        output = project / manifest["output"]
        output.parent.mkdir(parents=True, exist_ok=True)
        output.touch(exist_ok=True)


def pytest_configure() -> None:
    _ensure_voice_fixtures()
    _ensure_existence_only_video_fixtures()
