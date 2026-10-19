from __future__ import annotations

import json
import math
import platform
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path

from video_agent.common.io import read_json, sha256_file, stable_digest, write_json
from video_agent.rendering.assets import compose_frame, create_test_assets
from video_agent.rendering.subtitles import build_ass, paginate_text, readability_issues
from video_agent.voice import AquesTalkAdapter, VoicevoxAdapter
from video_agent.voice.engines import VoiceEngineUnavailable, wav_duration
from video_agent.registry import PresentationRegistry
from video_agent.local_paths import apply_render_overrides


STATES = {"NEW", "SCRIPT_READY", "VOICE_READY", "TIMELINE_READY", "RENDERED", "QA_PASSED",
          "COMPLETED", "PAUSED_RESUMABLE", "BLOCKED_VOICE_ENGINE", "RENDER_FAILED", "QA_FAILED"}


def _version(executable: Path) -> str:
    result = subprocess.run([str(executable), "-version"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return (result.stdout or result.stderr).splitlines()[0]


def _state(project: Path, status: str, completed: list[str], error: str | None = None) -> None:
    if status not in STATES:
        raise ValueError(status)
    write_json(project / "project_state.json", {"status": status, "completed_steps": completed, "error": error})


def apply_dictionary(text: str, dictionary: dict[str, str]) -> str:
    value = text
    for source in sorted(dictionary, key=lambda item: (-len(item), item)):
        value = value.replace(source, dictionary[source])
    return value


def normalize_presented_text(text: str | None) -> str:
    """Normalize transport whitespace without changing spoken wording."""
    return (text or "").replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")


def is_whitespace_only(text: str | None) -> bool:
    return not normalize_presented_text(text).strip()


def split_voice_text(text: str, limit: int = 48) -> list[str]:
    """Split only at natural sentence boundaries; commas remain in one WAV."""
    chunks, current = [], ""
    for piece in re.split(r"(?<=[。！？!?\n])", text):
        if not piece:
            continue
        if current and len(current) + len(piece) > limit:
            chunks.append(current)
            current = ""
        # An oversized sentence is safer as one synthesis unit than a split at
        # an arbitrary character/word boundary, which destroys prosody.
        if not current and len(piece) > limit:
            chunks.append(piece)
            continue
        current += piece
    if current:
        chunks.append(current)
    return chunks or [text]


def split_speech_chunks(text: str, limit: int = 52) -> list[str]:
    """Split synthesis units at sentence boundaries without rewriting text."""
    if len(text) <= limit:
        return [text]
    pieces = [piece for piece in re.split(r"(?<=[。！？!?\n])", text) if piece]
    chunks, current = [], ""
    for piece in pieces:
        if current and len(current) + len(piece) > limit:
            chunks.append(current)
            current = ""
        if not current and len(piece) > limit:
            chunks.append(piece)
            continue
        current += piece
        if piece.endswith("\n"):
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks or [text]


def expand_speech_lines(lines: list[dict], max_chars: int = 52) -> list[dict]:
    expanded = []
    for source_index, line in enumerate(lines, 1):
        text = normalize_presented_text(line.get("text"))
        # A blank voiced line is neither speech nor an intentional pause.  It
        # must not reach a speech engine.  An overlay may still carry viewer
        # information, so only retain blank non-voiced lines with an overlay.
        if is_whitespace_only(text) and not line.get("overlay"):
            continue
        should_split = line.get("presentation_mode", "VOICED") == "VOICED"
        chunks = split_speech_chunks(text, max_chars) if should_split else [text]
        voice_text = line.get("voice_text")
        if voice_text not in {None, text} and len(chunks) > 1:
            voice_chunks = split_speech_chunks(voice_text, max_chars)
            if len(voice_chunks) != len(chunks):
                raise ValueError("VOICE_TEXT_CHUNK_ALIGNMENT_FAILED")
        else:
            voice_chunks = chunks if voice_text is not None else [None] * len(chunks)
        source_line_id = line.get("source_script_line_id") or line.get("script_line_id") or f"source_line_{source_index:03d}"
        chunk_pairs = [(chunk, voice_chunk) for chunk, voice_chunk in zip(chunks, voice_chunks)
                       if line.get("overlay") or (not is_whitespace_only(chunk)
                       and not is_whitespace_only(voice_chunk if voice_chunk is not None else chunk))]
        for chunk_index, (chunk, voice_chunk) in enumerate(chunk_pairs, 1):
            expanded.append({
                **line,
                "text": chunk,
                "voice_text": voice_chunk,
                "source_script_line_id": source_line_id,
                "speech_chunk": {"index": chunk_index, "count": len(chunk_pairs), "original_text": text},
                "synthesis_boundary": "SENTENCE_OR_UTTERANCE",
            })
    return [{**line, "line_id": f"line_{index:03d}"} for index, line in enumerate(expanded, 1)]


def build_synthetic_lines(spec: dict) -> list[dict]:
    if spec.get("speech_chunking", {}).get("enabled"):
        return expand_speech_lines(spec["lines"], int(spec["speech_chunking"].get("max_chars", 52)))
    kept = [line for line in spec["lines"]
            if not is_whitespace_only(line.get("text")) or line.get("overlay")]
    return [{**line, "text": normalize_presented_text(line.get("text")),
             "line_id": f"line_{i:03d}"} for i, line in enumerate(kept, 1)]


def build_real_lines(spec: dict, normalized: dict) -> list[dict]:
    index = {event["event_id"]: event for event in normalized["events"]}
    lines = []
    for number, item in enumerate(spec["event_lines"], 1):
        event = index[item["event_id"]]
        line = {
            "line_id": f"line_{number:03d}",
            "source_event_ids": [event["event_id"], *event["source_event_ids"]],
            "speaker_id": event.get("speaker_id") or event.get("actor_id") or "system",
            "text": event["text"],
            "voice_text": item.get("voice_text", event["text"]),
            "voice_profile_id": item["voice_profile_id"],
            "subtitle_profile_id": item["subtitle_profile_id"],
            "portrait_asset_id": item.get("portrait_asset_id"),
            "event_type": event["event_type"],
            "dice": event.get("dice"),
        }
        lines.append(line)
    return lines


def timeline_from_lines(lines: list[dict], audio: dict[str, dict], characters: dict, gap: float,
                        background_asset_id: str) -> dict:
    clips, cursor = [], 0.0
    for number, line in enumerate(lines, 1):
        voice = audio[line["line_id"]]
        profile = characters[line["speaker_id"]]
        chunk = line.get("speech_chunk") or {}
        internal_chunk = int(chunk.get("index", 1)) < int(chunk.get("count", 1))
        post_speech_gap = 0.0 if internal_chunk else gap
        duration = round(voice["duration_sec"] + post_speech_gap, 3)
        dice = line.get("dice")
        overlay = line.get("overlay")
        if overlay is None and dice and dice.get("roll") is not None:
            overlay = {"type": "SKILL_CHECK", **{key: dice.get(key) for key in ("skill_name", "target_value", "roll", "result")}}
        presentation_mode = line.get("presentation_mode", "VOICED")
        show_portrait = presentation_mode in {"VOICED", "SILENT_VISUAL"}
        clips.append({
            "clip_id": f"clip_{number:03d}", "source_event_ids": line["source_event_ids"],
            "start_sec": round(cursor, 3), "duration_sec": duration,
            "speaker_id": line["speaker_id"],
            "speaker_name": line.get("resolved_display_name") or profile["display_name"],
            "audio_mode": voice.get("audio_mode", "VOICE"),
            "voice_file": voice.get("project_path"), "voice_engine": voice["engine"],
            "expected_voice_profile_id": profile.get("expected_voice_profile_id", profile.get("voice_profile_id")),
            "actual_voice_profile_id": voice.get("voice_profile_id"),
            "subtitle_text": line["text"], "subtitle_profile_id": line["subtitle_profile_id"],
            "presentation_mode": presentation_mode,
            "event_type": line.get("event_type"),
            "background_asset_id": line.get("background_asset_id", background_asset_id),
            "portrait_asset_ids": [line["portrait_asset_id"]] if show_portrait and line.get("portrait_asset_id") else [],
            "portrait_kind": line.get("portrait_kind"), "portrait_side": line.get("portrait_side"),
            "overlay": overlay,
            "source_script_line_id": line.get("source_script_line_id"),
            "speech_chunk": line.get("speech_chunk"),
            "speaker_context": line.get("speaker_context"),
            "synthesis_boundary": line.get("synthesis_boundary"),
            "presentation_origin": line.get("presentation_origin"),
            "presentation_as": line.get("presentation_as"),
            "system_interaction_id": line.get("system_interaction_id"),
            "interaction_type": line.get("interaction_type"),
            "prompt_grounding": line.get("prompt_grounding"),
            "prompt_grounding_source_event_ids": line.get("prompt_grounding_source_event_ids", []),
            "pl_voice_fallback": line.get("pl_voice_fallback"),
            "post_speech_gap_sec": post_speech_gap,
        })
        cursor = round(cursor + duration, 3)
    return {"timeline_version": "0.1", "duration_sec": cursor, "clips": clips}


def voice_profile_mismatches(clips: list[dict]) -> list[dict]:
    return [{"clip_id": clip["clip_id"], "expected": clip.get("expected_voice_profile_id"),
             "actual": clip.get("actual_voice_profile_id")}
            for clip in clips if clip.get("presentation_mode") == "VOICED"
            and clip.get("expected_voice_profile_id") != clip.get("actual_voice_profile_id")]


def create_silence_wav(path: Path, duration_sec: float, sample_rate: int = 48000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(b"\x00\x00" * int(duration_sec * sample_rate))


class M1Pipeline:
    def __init__(self, root: Path, project: Path):
        self.root = Path(root)
        self.project = Path(project)
        self.spec = read_json(self.project / "project.json")
        self.config = apply_render_overrides(read_json(self.root / "config" / "render_m1.json"), self.root.parent)
        self.assets = {item["asset_id"]: item for item in read_json(self.root / "assets" / "manifest.json")["assets"]}
        project_manifest = self.project / "asset_manifest.json"
        if project_manifest.exists():
            self.assets.update({item["asset_id"]: item for item in read_json(project_manifest)["assets"]})
        self.presentation_registry = PresentationRegistry(self.root / "config")
        self.voice_profiles = self.presentation_registry.voice_profiles
        self.subtitle_profiles = self.presentation_registry.subtitle_profiles
        project_characters = read_json(self.project / "characters.json")
        self.characters = self.presentation_registry.resolve_project_characters(project_characters)
        layout_path = self.spec.get("subtitle_layout_config")
        self.subtitle_layout = read_json(self.root / layout_path) if layout_path else {}
        self.ffmpeg = Path(self.config["ffmpeg_path"])
        self.ffprobe = Path(self.config["ffprobe_path"])

    def prepare_script(self) -> list[dict]:
        if self.spec["fixture_type"] == "synthetic":
            lines = build_synthetic_lines(self.spec)
        else:
            normalized = read_json(self.root / self.spec["normalized_session"])
            lines = build_real_lines(self.spec, normalized)
        write_json(self.project / "script_lines.json", lines)
        _state(self.project, "SCRIPT_READY", ["script"])
        return lines

    def render_voices(self, lines: list[dict] | None = None) -> dict[str, dict]:
        lines = lines or read_json(self.project / "script_lines.json")
        pronunciation = read_json(self.root / "config" / "pronunciation_dictionary.json")
        cache = self.root / "cache" / "voice"
        aq = AquesTalkAdapter(
            cache / "aquestalk", dll_root=Path(self.config["aquestalk_dll_root"]),
            bridge_source=self.root / "src" / "video_agent" / "voice" / "AquesTalkBridge.cs",
            bridge_exe=self.root / "cache" / "tools" / "AquesTalkBridge.exe",
            csc_path=Path(self.config["csc_path"]),
        )
        vv = VoicevoxAdapter(cache / "voicevox", self.config["voicevox_url"])
        engines = {"AQUESTALK": aq, "VOICEVOX": vv}
        audio_dir = self.project / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)
        records = {}
        try:
            for line in lines:
                if line.get("presentation_mode", "VOICED") != "VOICED":
                    records[line["line_id"]] = {
                        "audio_mode": "SILENCE", "project_path": None,
                        "cache_path": None, "cache_key": None, "cache_hit": True,
                        "engine": "NONE", "engine_version": "timeline-native silence",
                        "voice_profile_id": None,
                        "duration_sec": round(float(line.get("fixed_duration_sec", 3.0)), 6),
                        "sha256": None,
                    }
                    continue
                if is_whitespace_only(line.get("voice_text") if line.get("voice_text") is not None else line.get("text")):
                    raise ValueError(f"WHITESPACE_VOICE_GENERATION_BLOCKED:{line['line_id']}")
                profile = self.voice_profiles[line["voice_profile_id"]]
                voice_text = apply_dictionary(line.get("voice_text") or line["text"], pronunciation)
                if profile["engine"] == "AQUESTALK" and re.search(r"[一-龯々]", voice_text):
                    voice_text = vv.phonetic_reading(voice_text, 3)
                if profile.get("compatibility_mode") == "YMM4_EXACT_COMPAT":
                    from video_agent.voice.yukkuri_voice_compat import render_exact_fixture
                    destination = audio_dir / f"{line['line_id']}.wav"
                    compatibility = render_exact_fixture(aq, self.ffmpeg, voice_text, profile, destination)
                    cache_identity = {
                        "voice_profile_id": line["voice_profile_id"],
                        "source_text": voice_text,
                        "voice_type": profile["voice_type"],
                        "reading_speed": profile["synthesis_speed"],
                        "playback_rate_percent": profile["playback_rate_percent"],
                        "source_volume_percent": profile["source_volume_percent"],
                        "raw_synthesis_sha256": compatibility["raw_synthesis_sha256"],
                    }
                    records[line["line_id"]] = {
                        "audio_mode": "VOICE",
                        "project_path": str(destination.relative_to(self.project)).replace("\\", "/"),
                        "cache_path": compatibility["raw_synthesis_path"],
                        "cache_key": stable_digest(cache_identity), "cache_identity": cache_identity,
                        "cache_hit": False,
                        "engine": "AQUESTALK", "engine_version": profile["engine_version"],
                        "voice_profile_id": line["voice_profile_id"],
                        "duration_sec": round(wav_duration(destination), 6), "sha256": sha256_file(destination),
                        "compatibility_mode": "YMM4_EXACT_COMPAT",
                        "playback_rate_semantics": profile["playback_rate_semantics"],
                    }
                    continue
                if profile["engine"] == "AQUESTALK" and len(voice_text) > 48:
                    parts = [engines[profile["engine"]].synthesize(part, profile)
                             for part in split_voice_text(voice_text)]
                    concat_file = audio_dir / f"{line['line_id']}_parts.ffconcat"
                    concat_file.write_text("ffconcat version 1.0\n" + "\n".join(
                        f"file '{part.path.resolve().as_posix()}'" for part in parts) + "\n", encoding="utf-8")
                    combined = audio_dir / f"{line['line_id']}_combined.wav"
                    subprocess.run([str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                                    "-i", str(concat_file), "-c:a", "pcm_s16le", str(combined)], check=True)
                    result = parts[0]
                    source_voice = combined
                    cache_key = stable_digest([part.cache_key for part in parts])
                    cache_hit = all(part.cache_hit for part in parts)
                else:
                    result = engines[profile["engine"]].synthesize(voice_text, profile)
                    source_voice = result.path
                    cache_key = result.cache_key
                    cache_hit = result.cache_hit
                destination = audio_dir / f"{line['line_id']}.wav"
                subprocess.run([
                    str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source_voice),
                    "-af", "loudnorm=I=-20:TP=-2:LRA=7", "-ar", "48000", "-ac", "1",
                    "-c:a", "pcm_s16le", str(destination)
                ], check=True)
                normalized_duration = wav_duration(destination)
                records[line["line_id"]] = {
                    "audio_mode": "VOICE",
                    "project_path": str(destination.relative_to(self.project)).replace("\\", "/"),
                    "cache_path": str(result.path.relative_to(self.root)).replace("\\", "/"),
                    "cache_key": cache_key, "cache_hit": cache_hit,
                    "engine": result.engine, "engine_version": result.engine_version,
                    "voice_profile_id": line["voice_profile_id"], "duration_sec": round(normalized_duration, 6),
                    "sha256": sha256_file(destination),
                }
        except VoiceEngineUnavailable as exc:
            _state(self.project, "BLOCKED_VOICE_ENGINE", ["script"], str(exc))
            raise
        write_json(self.project / "audio_manifest.json", records)
        _state(self.project, "VOICE_READY", ["script", "voice"])
        return records

    def build_timeline(self, lines: list[dict] | None = None, audio: dict | None = None) -> dict:
        lines = lines or read_json(self.project / "script_lines.json")
        audio = audio or read_json(self.project / "audio_manifest.json")
        timeline = timeline_from_lines(lines, audio, self.characters, self.config["normal_gap_sec"],
                                       self.spec["background_asset_id"])
        write_json(self.project / "video_timeline.json", timeline)
        _state(self.project, "TIMELINE_READY", ["script", "voice", "timeline"])
        return timeline

    def render_video(self, timeline: dict | None = None) -> Path:
        timeline = timeline or read_json(self.project / "video_timeline.json")
        if not self.ffmpeg.exists() or not self.ffprobe.exists():
            _state(self.project, "RENDER_FAILED", ["script", "voice", "timeline"], "FFmpeg/ffprobe missing")
            raise FileNotFoundError("FFmpeg/ffprobe missing")
        frames = self.project / "frames"
        frames.mkdir(exist_ok=True)
        generated = create_test_assets(self.root / "assets" / "test_m1")
        asset_paths = {asset_id: self.root / item["file_path"] for asset_id, item in self.assets.items() if item.get("file_path")}
        asset_paths.update(generated)
        segments = frames / "segments"
        segments.mkdir(exist_ok=True)
        concat_lines = ["ffconcat version 1.0"]
        for clip in timeline["clips"]:
            portrait_id = clip["portrait_asset_ids"][0] if clip["portrait_asset_ids"] else None
            portrait = asset_paths.get(portrait_id) if portrait_id else None
            side = "left" if clip["speaker_id"] == "pc_01" else "right"
            frame = frames / f"{clip['clip_id']}.png"
            dialogue_id = self.spec.get("dialogue_frame_asset_id")
            dialogue_frame = asset_paths.get(dialogue_id) if dialogue_id else None
            compose_frame(asset_paths[clip["background_asset_id"]], portrait, frame, side,
                          dialogue_frame, self.subtitle_layout.get("dialogue_frame"),
                          clip.get("portrait_kind") or "FULL_BODY", self.subtitle_layout)
            padded_audio = frames / f"{clip['clip_id']}_padded.wav"
            if clip.get("audio_mode") == "SILENCE":
                subprocess.run([
                    str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
                    "-t", str(clip["duration_sec"]), "-c:a", "pcm_s16le", str(padded_audio)
                ], check=True)
            else:
                source_audio = self.project / clip["voice_file"]
                subprocess.run([
                    str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source_audio),
                    "-af", f"aresample=48000,apad=pad_dur={self.config['normal_gap_sec']}",
                    "-t", str(clip["duration_sec"]), "-ac", "1", "-ar", "48000", str(padded_audio)
                ], check=True)
            segment = segments / f"{clip['clip_id']}.mp4"
            subprocess.run([
                str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-loop", "1",
                "-framerate", str(self.config["fps"]), "-i", str(frame), "-i", str(padded_audio),
                "-t", str(clip["duration_sec"]), "-r", str(self.config["fps"]),
                "-c:v", self.config["video_codec"], "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(segment)
            ], check=True)
            concat_lines.append(f"file '{segment.resolve().as_posix()}'")
        segment_list = segments / "segments.ffconcat"
        segment_list.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        joined = frames / "joined.mp4"
        subprocess.run([
            str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(segment_list), "-c", "copy", str(joined)
        ], check=True)

        ass = self.project / "subtitles" / "subtitles.ass"
        overflow = build_ass(ass, timeline["clips"], self.subtitle_profiles, layout=self.subtitle_layout)
        write_json(self.project / "subtitles" / "subtitle_manifest.json", {"file": "subtitles.ass", "overflow_clip_ids": overflow})
        output = self.project / "output" / f"{self.project.name}.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)
        ass_filter = str(ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        try:
            subprocess.run([
                str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined),
                "-vf", f"ass=filename='{ass_filter}'", "-r", str(self.config["fps"]),
                "-s", f"{self.config['width']}x{self.config['height']}", "-c:v", self.config["video_codec"],
                "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", str(timeline["duration_sec"]),
                "-movflags", "+faststart", str(output)
            ], check=True)
        except subprocess.CalledProcessError as exc:
            _state(self.project, "RENDER_FAILED", ["script", "voice", "timeline"], str(exc))
            raise
        _state(self.project, "RENDERED", ["script", "voice", "timeline", "render"])
        return output

    def qa(self, timeline: dict | None = None, output: Path | None = None) -> dict:
        timeline = timeline or read_json(self.project / "video_timeline.json")
        output = output or self.project / "output" / f"{self.project.name}.mp4"
        checks, warnings = [], []
        def add(name: str, ok: bool, detail=None):
            checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        add("mp4_exists", output.exists())
        probe = {}
        if output.exists():
            result = subprocess.run([str(self.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            add("ffprobe_readable", result.returncode == 0)
            if result.returncode == 0:
                probe = json.loads(result.stdout)
        streams = probe.get("streams", [])
        video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
        audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), {})
        duration = float(probe.get("format", {}).get("duration", 0) or 0)
        add("duration_30_to_60_sec", 30 <= duration <= 60, duration)
        add("resolution_1920x1080", video.get("width") == 1920 and video.get("height") == 1080,
            [video.get("width"), video.get("height")])
        add("fps_30", video.get("avg_frame_rate") == "30/1", video.get("avg_frame_rate"))
        add("video_stream", bool(video), video.get("codec_name"))
        add("audio_stream", bool(audio), audio.get("codec_name"))
        add("wav_missing_zero", all(clip.get("audio_mode") == "SILENCE" or
                                    (clip.get("voice_file") and (self.project / clip["voice_file"]).exists())
                                    for clip in timeline["clips"]))
        add("subtitle_missing_zero", (self.project / "subtitles" / "subtitles.ass").exists())
        lookup = self.assets
        used = {clip["background_asset_id"] for clip in timeline["clips"]}
        used.update(asset for clip in timeline["clips"] for asset in clip["portrait_asset_ids"])
        add("unresolved_asset_zero", all(asset in lookup and lookup[asset].get("file_path") for asset in used), sorted(used))
        add("asset_missing_zero", all((self.root / lookup[asset]["file_path"]).exists() for asset in used if asset in lookup))
        subtitle_manifest = read_json(self.project / "subtitles" / "subtitle_manifest.json")
        add("subtitle_overflow_zero", not subtitle_manifest["overflow_clip_ids"], subtitle_manifest["overflow_clip_ids"])
        overlap = any(b["start_sec"] < a["start_sec"] + a["duration_sec"] - 0.002 for a, b in zip(timeline["clips"], timeline["clips"][1:]))
        add("timeline_overlap_zero", not overlap)
        mismatches = voice_profile_mismatches(timeline["clips"])
        add("VOICE_PROFILE_MISMATCH", not mismatches, mismatches)
        sync_errors = []
        for clip in timeline["clips"]:
            if clip["presentation_mode"] != "VOICED" or not clip.get("speech_chunk"):
                continue
            wav = self.project / clip["voice_file"]
            actual_duration = wav_duration(wav)
            pages = paginate_text(clip["subtitle_text"],
                                  int(self.subtitle_layout.get("pagination", {}).get("characters_per_line", 30)),
                                  int(self.subtitle_layout.get("pagination", {}).get("lines_per_page", 3)))
            if len(pages) != 1 or clip["duration_sec"] + 0.002 < actual_duration:
                sync_errors.append({"clip_id": clip["clip_id"], "pages": len(pages),
                                    "audio_duration": round(actual_duration, 3), "clip_duration": clip["duration_sec"]})
        add("speech_chunk_subtitle_sync", not sync_errors, sync_errors)
        style_issues = readability_issues(self.subtitle_layout, self.subtitle_profiles) if self.subtitle_layout else []
        add("subtitle_readability_config", not style_issues, style_issues)
        engines = {clip["voice_engine"] for clip in timeline["clips"] if clip.get("audio_mode") == "VOICE"}
        add("mixed_voice_engines", engines == {"AQUESTALK", "VOICEVOX"}, sorted(engines))
        expected = {line["speaker_id"]: self.voice_profiles[line["voice_profile_id"]]["engine"] for line in read_json(self.project / "script_lines.json")}
        add("speaker_mapping", all(expected[clip["speaker_id"]] == clip["voice_engine"]
                                   for clip in timeline["clips"] if clip.get("audio_mode") == "VOICE"))
        add("provenance", all(clip["source_event_ids"] for clip in timeline["clips"]))
        silence = []
        loudness_by_engine: dict[str, list[float]] = {}
        for clip in timeline["clips"]:
            if clip.get("audio_mode") != "VOICE":
                continue
            wav = self.project / clip["voice_file"]
            result = subprocess.run([str(self.ffmpeg), "-hide_banner", "-i", str(wav), "-af", "volumedetect", "-f", "null", "NUL"],
                                    capture_output=True, text=True, encoding="utf-8", errors="replace")
            if "-inf dB" in result.stderr:
                silence.append(clip["clip_id"])
            match = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", result.stderr)
            if match:
                loudness_by_engine.setdefault(clip["voice_engine"], []).append(float(match.group(1)))
        add("silent_voice_zero", not silence, silence)
        means = {engine: round(sum(values) / len(values), 2) for engine, values in loudness_by_engine.items()}
        if len(means) >= 2 and max(means.values()) - min(means.values()) > 6:
            warnings.append("LOUDNESS_IMBALANCE")
        add("loudness_measured", len(means) >= 2, means)
        frame_sample = self.project / "qa" / "frame_sample.png"
        frame_sample.parent.mkdir(exist_ok=True)
        subprocess.run([str(self.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-ss", str(max(1, duration / 2)),
                        "-i", str(output), "-frames:v", "1", str(frame_sample)], check=False)
        black = False
        if frame_sample.exists():
            import cv2
            image = cv2.imread(str(frame_sample))
            black = image is None or float(image.mean()) < 5.0
        add("black_frame_check", not black, str(frame_sample.relative_to(self.project)))
        if any(lookup[asset]["status"] in {"UNKNOWN", "TEST_ONLY"} for asset in used):
            warnings.extend(["NON_PUBLISHABLE_ASSET_USED", "FALLBACK_BACKGROUND_USED"])
        status = "PASS" if not [check for check in checks if check["status"] == "FAIL"] else "FAIL"
        report = {"status": status, "checks": checks, "warnings": sorted(set(warnings)), "probe": probe}
        write_json(self.project / "qa_report.json", report)
        _state(self.project, "COMPLETED" if status == "PASS" else "QA_FAILED",
               ["script", "voice", "timeline", "render", "qa"] if status == "PASS" else ["script", "voice", "timeline", "render"])
        return report

    def write_manifest(self, timeline: dict, output: Path, qa: dict) -> dict:
        audio = read_json(self.project / "audio_manifest.json")
        manifest = {
            "manifest_version": "0.1", "project": self.project.name,
            "fixture_type": self.spec["fixture_type"], "timeline_sha256": stable_digest(timeline),
            "output": str(output.relative_to(self.project)).replace("\\", "/"),
            "output_sha256": sha256_file(output), "duration_sec": timeline["duration_sec"],
            "engines": {
                "AquesTalk": sorted({item["engine_version"] for item in audio.values() if item["engine"] == "AQUESTALK"}),
                "VOICEVOX": sorted({item["engine_version"] for item in audio.values() if item["engine"] == "VOICEVOX"}),
                "FFmpeg": _version(self.ffmpeg), "Python": platform.python_version(),
            },
            "qa_status": qa["status"], "publishable": False,
            "asset_warnings": qa["warnings"], "source_line_count": len(timeline["clips"]),
        }
        write_json(self.project / "render_manifest.json", manifest)
        return manifest

    def run(self) -> dict:
        lines = self.prepare_script()
        audio = self.render_voices(lines)
        timeline = self.build_timeline(lines, audio)
        output = self.render_video(timeline)
        qa = self.qa(timeline, output)
        manifest = self.write_manifest(timeline, output, qa)
        return {"status": qa["status"], "output": str(output), "manifest": manifest}
