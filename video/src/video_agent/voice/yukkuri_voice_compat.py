from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import subprocess
import struct
import wave
from pathlib import Path
from typing import Any

from video_agent.voice.engines import AquesTalkAdapter


SOURCE_RUNTIME_SHA256 = "50d4871eb5853e6e6f74F999C9017E4AEA80B162C959E3CE9AAB78F874459E4B".lower()
PLAYBACK_RATE_SEMANTICS = "PITCH_AND_SPEED_COUPLED"
PLAYBACK_RATE_AUTHORITY = "https://manjubox.net/ymm4/faq/ゆっくりボイス/声質を変更する/"
FIXTURE_TEXT = "これは、おんせいせっていの、かくにんです。きこえかたと、はなすすぴーどを、かくにんしてください。"

EXACT_SOURCE = {
    "reimu": {"source_profile_id": "ymm_reimu_aquestalk_v1_7", "voice_type": "f1",
              "synthesis_speed": 125, "playback_rate_percent": 100.0, "source_volume_percent": 50.0},
    "marisa": {"source_profile_id": "ymm_marisa_aquestalk_v1_7", "voice_type": "f2",
               "synthesis_speed": 125, "playback_rate_percent": 100.0, "source_volume_percent": 50.0},
    "sakuya": {"source_profile_id": "ymm_sakuya_aquestalk_v1_7", "voice_type": "f1",
               "synthesis_speed": 105, "playback_rate_percent": 120.0, "source_volume_percent": 50.0},
}

CANDIDATE_IDS = {
    "reimu": "ymm_exact_reimu_v1", "marisa": "ymm_exact_marisa_v1", "sakuya": "ymm_exact_sakuya_v1",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_candidate_profile(character_id: str) -> dict[str, Any]:
    source = EXACT_SOURCE[character_id]
    return {
        "voice_profile_id": CANDIDATE_IDS[character_id], "character_id": character_id,
        "source_profile_id": source["source_profile_id"], "source_runtime_sha256": SOURCE_RUNTIME_SHA256,
        "engine": "AQUESTALK", "voice_type": source["voice_type"],
        "reading_speed": source["synthesis_speed"], "synthesis_speed": source["synthesis_speed"],
        "playback_rate_percent": source["playback_rate_percent"],
        "source_volume_percent": source["source_volume_percent"],
        "source_gain_linear": source["source_volume_percent"] / 100.0,
        "pitch_mode": "DEFAULT_NO_EXPLICIT_PITCH",
        "post_silence_sec": 0.15, "post_silence_mode": "TIMELINE_TAIL_NOT_AUDIO_PADDING",
        "engine_version": "AquesTalk 1.7.3.1 bundled with the authoritative YMM4 installation",
        "compatibility_mode": "YMM4_EXACT_COMPAT", "playback_rate_semantics": PLAYBACK_RATE_SEMANTICS,
        "playback_rate_authority": PLAYBACK_RATE_AUTHORITY,
        "dsp_implementation": "FFMPEG_ASETRATE_THEN_ARESAMPLE",
        "compatibility_confidence": "MEDIUM", "human_review_status": "PENDING",
        "usage_status": "HUMAN_REVIEW_CANDIDATE", "auto_use": False,
        "bit_identical_claim": False,
    }


def validate_source_profiles(profiles: dict[str, dict[str, Any]]) -> list[str]:
    errors = []
    for character_id, expected in EXACT_SOURCE.items():
        profile = profiles.get(expected["source_profile_id"])
        if profile is None:
            errors.append(f"SOURCE_PROFILE_MISSING:{character_id}")
            continue
        comparisons = {
            "voice_type": expected["voice_type"], "ymm_reading_speed": expected["synthesis_speed"],
            "ymm_playback_rate_percent": expected["playback_rate_percent"],
            "ymm_source_volume_percent": expected["source_volume_percent"],
            "source_sha256": SOURCE_RUNTIME_SHA256,
        }
        for field, value in comparisons.items():
            actual = profile.get(field)
            if isinstance(value, float):
                matches = float(actual) == value
            else:
                matches = str(actual).lower() == str(value).lower()
            if not matches:
                errors.append(f"SOURCE_VALUE_MISMATCH:{character_id}:{field}:{actual}:{value}")
    return errors


def playback_filter(profile: dict[str, Any], input_sample_rate: int, output_sample_rate: int = 48000) -> str:
    rate = float(profile["playback_rate_percent"]) / 100.0
    gain = float(profile["source_volume_percent"]) / 100.0
    filters = []
    if abs(rate - 1.0) > 1e-9:
        filters.append(f"asetrate={input_sample_rate * rate:.6f}")
    filters.append(f"aresample={output_sample_rate}")
    filters.append(f"volume={gain:.9f}")
    return ",".join(filters)


def render_exact_fixture(adapter: AquesTalkAdapter, ffmpeg: Path, text: str,
                         profile: dict[str, Any], destination: Path) -> dict[str, Any]:
    raw_profile = {"voice_type": profile["voice_type"], "reading_speed": profile["synthesis_speed"],
                   "version": profile["engine_version"]}
    raw = adapter.synthesize(text, raw_profile)
    with wave.open(str(raw.path), "rb") as stream:
        sample_rate = stream.getframerate()
    destination.parent.mkdir(parents=True, exist_ok=True)
    filter_value = playback_filter(profile, sample_rate)
    subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw.path),
                    "-af", filter_value, "-ac", "1", "-c:a", "pcm_s16le", str(destination)], check=True)
    return {"raw_synthesis_path": str(raw.path), "raw_synthesis_sha256": sha256_file(raw.path),
            "output_sha256": sha256_file(destination), "filter": filter_value,
            "synthesis_speed": profile["synthesis_speed"],
            "playback_rate_percent": profile["playback_rate_percent"],
            "source_volume_percent": profile["source_volume_percent"]}


def render_baseline_fixture(adapter: AquesTalkAdapter, ffmpeg: Path, text: str,
                            profile: dict[str, Any], destination: Path) -> dict[str, Any]:
    raw = adapter.synthesize(text, profile)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # This is the current renderer path: its profile volume/pitch_playback fields
    # are not consumed by AquesTalkAdapter; loudnorm is applied after synthesis.
    subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(raw.path),
                    "-af", "loudnorm=I=-20:TP=-2:LRA=7", "-ar", "48000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(destination)], check=True)
    return {"raw_synthesis_path": str(raw.path), "raw_synthesis_sha256": sha256_file(raw.path),
            "output_sha256": sha256_file(destination), "filter": "loudnorm=I=-20:TP=-2:LRA=7,aresample=48000",
            "reading_speed": profile["reading_speed"],
            "renderer_unused_profile_fields": [field for field in ("pitch_playback", "volume") if field in profile]}


def measure_wav(path: Path, silence_threshold_dbfs: float = -50.0) -> dict[str, Any]:
    with wave.open(str(path), "rb") as stream:
        channels, sample_width, sample_rate, frames = (stream.getnchannels(), stream.getsampwidth(),
                                                        stream.getframerate(), stream.getnframes())
        body = stream.readframes(frames)
    if sample_width != 2:
        raise ValueError(f"unsupported PCM sample width: {sample_width}")
    samples = tuple(value[0] for value in struct.iter_unpack("<h", body))
    rms = int(math.sqrt(sum(value * value for value in samples) / len(samples))) if samples else 0
    peak = max((abs(value) for value in samples), default=0)
    full_scale = float((1 << (8 * sample_width - 1)) - 1)
    rms_dbfs = 20 * math.log10(rms / full_scale) if rms else float("-inf")
    peak_dbfs = 20 * math.log10(peak / full_scale) if peak else float("-inf")
    threshold = full_scale * (10 ** (silence_threshold_dbfs / 20.0))
    last_active = -1
    for index in range(frames - 1, -1, -1):
        frame = samples[index * channels:(index + 1) * channels]
        if max((abs(value) for value in frame), default=0) > threshold:
            last_active = index
            break
    trailing_silence = frames / sample_rate if last_active < 0 else (frames - last_active - 1) / sample_rate
    return {"path": str(path), "sha256": sha256_file(path), "duration_sec": round(frames / sample_rate, 6),
            "sample_rate": sample_rate, "channels": channels, "sample_width_bytes": sample_width,
            "rms_linear": rms, "rms_dbfs": round(rms_dbfs, 3), "peak_linear": peak,
            "peak_dbfs": round(peak_dbfs, 3), "trailing_silence_sec_at_minus_50_dbfs": round(trailing_silence, 6)}


def measure_loudness(ffmpeg: Path, path: Path) -> dict[str, float | str | None]:
    completed = subprocess.run([str(ffmpeg), "-hide_banner", "-i", str(path), "-af",
                                "loudnorm=I=-23:TP=-2:LRA=7:print_format=json", "-f", "null", "NUL"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
    blocks = re.findall(r"\{\s*\"input_i\".*?\}", completed.stderr, flags=re.DOTALL)
    if not blocks:
        return {"integrated_lufs": None, "true_peak_dbtp": None, "status": "MEASUREMENT_UNAVAILABLE"}
    values = json.loads(blocks[-1])
    return {"integrated_lufs": float(values["input_i"]), "true_peak_dbtp": float(values["input_tp"]),
            "loudness_range_lu": float(values["input_lra"]), "status": "PASS"}

