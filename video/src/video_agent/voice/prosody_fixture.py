from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from video_agent.common.io import read_json, sha256_file, write_json
from video_agent.local_paths import apply_render_overrides
from video_agent.voice.engines import AquesTalkAdapter, VoicevoxAdapter


def _legacy_parts(reading: str, limit: int = 48) -> list[str]:
    """Iteration 2 baseline: punctuation/length based subdivisions."""
    import re
    pieces, current = [], ""
    for piece in re.split(r"(?<=[。！？、])", reading):
        if not piece:
            continue
        if current and len(current) + len(piece) > limit:
            pieces.append(current)
            current = ""
        while len(piece) > limit:
            room = limit - len(current)
            current += piece[:room]
            pieces.append(current)
            current, piece = "", piece[room:]
        current += piece
    if current:
        pieces.append(current)
    return pieces or [reading]


def _concat(parts: list[Path], output: Path, ffmpeg: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if len(parts) == 1:
        shutil.copy2(parts[0], output)
        return
    listing = output.with_suffix(".ffconcat")
    listing.write_text("ffconcat version 1.0\n" + "\n".join(
        f"file '{part.resolve().as_posix()}'" for part in parts) + "\n", encoding="utf-8")
    subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c:a", "pcm_s16le", str(output)], check=True)


def build_prosody_ab_fixture(root: Path, project: Path, lines: list[dict]) -> dict:
    config = apply_render_overrides(read_json(root / "config" / "render_m1.json"), root.parent)
    profiles = {item["voice_profile_id"]: item
                for item in read_json(root / "config" / "voices" / "m1_profiles.json")}
    cache = root / "cache" / "voice"
    aq = AquesTalkAdapter(cache / "aquestalk", dll_root=Path(config["aquestalk_dll_root"]),
                         bridge_source=root / "src" / "video_agent" / "voice" / "AquesTalkBridge.cs",
                         bridge_exe=root / "cache" / "tools" / "AquesTalkBridge.exe",
                         csc_path=Path(config["csc_path"]))
    vv = VoicevoxAdapter(cache / "voicevox", config["voicevox_url"])
    ffmpeg = Path(config["ffmpeg_path"])
    destination = project / "review" / "aquestalk_prosody_ab"
    manifest = {
        "schema_version": "0.1",
        "reference_scope": "YMM4_BUNDLED_AQUESTALK_ENGINE_DIRECT",
        "reference_limitation": "YMM4 frontend text analysis/export is not reproduced; human YMM4 export remains required for a frontend-level comparison.",
        "processing": {
            "agent_current": "Iteration 2 punctuation/length subdivision followed by WAV concat",
            "agent_candidate": "One natural utterance/sentence per AquesTalk invocation; comma remains inside the WAV",
            "reference_yymm4": "Direct output from the exact AquesTalk.dll bundled with the installed YMM4, same voice type and reading speed",
            "pitch_playback": "100%; no pitch shift or time stretch",
            "post_processing": "none in fixture WAVs",
        },
        "samples": [],
    }
    for speaker_id, label in (("pc_01", "reimu"), ("pc_02", "marisa")):
        candidates = [line for line in lines if line["speaker_id"] == speaker_id
                      and line["presentation_mode"] == "VOICED" and len(line.get("voice_text") or line["text"]) > 5][:3]
        for index, line in enumerate(candidates, 1):
            profile = profiles[line["voice_profile_id"]]
            source_text = line.get("voice_text") or line["text"]
            reading = vv.phonetic_reading(source_text, 3)
            base = destination / label
            current_parts = [aq.synthesize(part, profile).path for part in _legacy_parts(reading)]
            current = base / "agent_current" / f"{index:02d}.wav"
            candidate = base / "agent_candidate" / f"{index:02d}.wav"
            reference = base / "reference_yymm4" / f"{index:02d}.wav"
            _concat(current_parts, current, ffmpeg)
            natural = aq.synthesize(reading, profile).path
            _concat([natural], candidate, ffmpeg)
            _concat([natural], reference, ffmpeg)
            manifest["samples"].append({
                "speaker_id": speaker_id, "speaker_label": label, "index": index,
                "source_script_line_id": line["source_script_line_id"], "source_text": source_text,
                "phonetic_input": reading, "voice_type": profile["voice_type"],
                "reading_speed": profile["reading_speed"], "pitch_playback": profile["pitch_playback"],
                "current_parts": len(current_parts),
                "files": {"agent_current": str(current.relative_to(destination)).replace("\\", "/"),
                          "agent_candidate": str(candidate.relative_to(destination)).replace("\\", "/"),
                          "reference_yymm4": str(reference.relative_to(destination)).replace("\\", "/")},
                "sha256": {"agent_current": sha256_file(current), "agent_candidate": sha256_file(candidate),
                           "reference_yymm4": sha256_file(reference)},
            })
    write_json(destination / "manifest.json", manifest)
    return manifest
