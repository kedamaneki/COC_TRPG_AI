from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np


def edge_silence(path: Path, threshold_db: float = -45.0) -> dict:
    with wave.open(str(path), "rb") as stream:
        rate = stream.getframerate()
        width = stream.getsampwidth()
        channels = stream.getnchannels()
        frames = stream.getnframes()
        raw = stream.readframes(frames)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        raise ValueError(f"unsupported WAV sample width: {width}")
    samples = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    peak = float(np.max(np.abs(samples))) if len(samples) else 0.0
    threshold = peak * math.pow(10.0, threshold_db / 20.0)
    active = np.flatnonzero(np.abs(samples) > threshold)
    duration = len(samples) / float(rate)
    if not len(active):
        return {"duration_sec": duration, "leading_sec": duration, "trailing_sec": duration}
    return {
        "duration_sec": duration,
        "leading_sec": active[0] / float(rate),
        "trailing_sec": (len(samples) - 1 - active[-1]) / float(rate),
    }


def internal_utterance_gaps(timeline: dict, project: Path, speaker_ids: set[str] | None = None) -> list[dict]:
    groups: dict[tuple[str, str], list[dict]] = {}
    for clip in timeline["clips"]:
        chunk = clip.get("speech_chunk") or {}
        if clip.get("voice_engine") != "AQUESTALK" or int(chunk.get("count", 1)) <= 1:
            continue
        if speaker_ids and clip.get("speaker_id") not in speaker_ids:
            continue
        key = (clip["speaker_id"], clip.get("source_script_line_id") or clip["clip_id"])
        groups.setdefault(key, []).append(clip)
    results = []
    for (speaker_id, source_line), clips in groups.items():
        clips.sort(key=lambda item: int(item["speech_chunk"]["index"]))
        for current, following in zip(clips, clips[1:]):
            current_edge = edge_silence(project / current["voice_file"])
            next_edge = edge_silence(project / following["voice_file"])
            timeline_gap = max(0.0, following["start_sec"] - (current["start_sec"] + current["duration_sec"]))
            padding = max(0.0, current["duration_sec"] - current_edge["duration_sec"])
            results.append({
                "speaker_id": speaker_id,
                "source_script_line_id": source_line,
                "from_clip_id": current["clip_id"],
                "to_clip_id": following["clip_id"],
                "wav_trailing_sec": round(current_edge["trailing_sec"], 4),
                "timeline_padding_sec": round(padding, 4),
                "timeline_gap_sec": round(timeline_gap, 4),
                "next_wav_leading_sec": round(next_edge["leading_sec"], 4),
                "total_internal_silence_sec": round(current_edge["trailing_sec"] + padding + timeline_gap + next_edge["leading_sec"], 4),
            })
    return results


def suspicious_audio_bursts(path: Path, *, minimum_duration: float = 0.05,
                            maximum_duration: float = 0.30,
                            high_frequency_hz: float = 5000.0) -> list[dict]:
    """Detect short, energetic, non-speech-like high-frequency WAV bursts."""
    with wave.open(str(path), "rb") as stream:
        rate = stream.getframerate()
        width = stream.getsampwidth()
        channels = stream.getnchannels()
        frames = stream.getnframes()
        raw = stream.readframes(frames)
    dtype = {1: np.int8, 2: np.int16, 4: np.int32}.get(width)
    if dtype is None:
        return []
    samples = np.frombuffer(raw, dtype=dtype).astype(np.float64)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    duration = len(samples) / float(rate)
    if not minimum_duration <= duration <= maximum_duration or not len(samples):
        return []
    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples)))
    if rms <= 1.0 or peak <= 1.0:
        return []
    centered = samples - float(np.mean(samples))
    spectrum = np.square(np.abs(np.fft.rfft(centered * np.hanning(len(centered)))))
    frequencies = np.fft.rfftfreq(len(centered), 1.0 / rate)
    total = float(spectrum.sum()) or 1.0
    high_ratio = float(spectrum[frequencies >= high_frequency_hz].sum() / total)
    zero_crossing = float(np.mean(np.signbit(centered[:-1]) != np.signbit(centered[1:]))) if len(centered) > 1 else 0.0
    # Known blank-engine artifacts may be narrow-band rather than pure hiss;
    # their defining property is a very short, energetic, rapidly changing clip.
    suspicious = high_ratio >= 0.18 or zero_crossing >= 0.16
    if not suspicious:
        return []
    return [{
        "path": str(path), "duration_sec": round(duration, 6),
        "rms": round(rms, 2), "peak": round(peak, 2),
        "high_frequency_ratio": round(high_ratio, 4),
        "zero_crossing_rate": round(zero_crossing, 4),
    }]
