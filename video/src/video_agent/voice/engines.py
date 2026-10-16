from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import urllib.parse
import urllib.request
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from video_agent.common.io import stable_digest


class VoiceEngineError(RuntimeError):
    pass


class VoiceEngineUnavailable(VoiceEngineError):
    pass


@dataclass(frozen=True)
class VoiceResult:
    path: Path
    duration_sec: float
    cache_key: str
    engine: str
    engine_version: str
    cache_hit: bool


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as stream:
        return stream.getnframes() / float(stream.getframerate())


def voice_cache_key(engine: str, profile: dict, text: str) -> str:
    return stable_digest({"engine": engine, "profile": profile, "text": text})


class VoiceEngine(ABC):
    engine_name: str

    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    def synthesize(self, text: str, profile: dict) -> VoiceResult:
        raise NotImplementedError


class AquesTalkAdapter(VoiceEngine):
    engine_name = "AQUESTALK"

    def __init__(self, cache_dir: Path, *, dll_root: Path, bridge_source: Path,
                 bridge_exe: Path, csc_path: Path):
        super().__init__(cache_dir)
        self.dll_root = Path(dll_root)
        self.bridge_source = Path(bridge_source)
        self.bridge_exe = Path(bridge_exe)
        self.csc_path = Path(csc_path)

    def _ensure_bridge(self) -> None:
        if self.bridge_exe.exists() and self.bridge_exe.stat().st_mtime >= self.bridge_source.stat().st_mtime:
            return
        if not self.csc_path.exists():
            raise VoiceEngineUnavailable(f"32-bit C# compiler not found: {self.csc_path}")
        self.bridge_exe.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([
            str(self.csc_path), "/nologo", "/platform:x86",
            f"/out:{self.bridge_exe}", str(self.bridge_source),
        ], check=True, capture_output=True, text=True)

    def synthesize(self, text: str, profile: dict) -> VoiceResult:
        key = voice_cache_key(self.engine_name, profile, text)
        output = self.cache_dir / f"{key}.wav"
        if output.exists():
            return VoiceResult(output, wav_duration(output), key, self.engine_name,
                               str(profile.get("version") or "AquesTalk DLL (bundled with YMM4)"), True)
        voice_type = str(profile["voice_type"])
        dll = self.dll_root / voice_type / "AquesTalk.dll"
        if not dll.exists():
            raise VoiceEngineUnavailable(f"AquesTalk DLL not found: {dll}")
        self._ensure_bridge()
        try:
            text.encode("cp932")
        except UnicodeEncodeError as exc:
            raise VoiceEngineError("AquesTalk input must be CP932-compatible phonetic text") from exc
        completed = subprocess.run([
            str(self.bridge_exe), str(dll), str(int(profile["reading_speed"])), text, str(output)
        ], capture_output=True, text=True)
        if completed.returncode or not output.exists():
            raise VoiceEngineError(f"AquesTalk synthesis failed ({completed.returncode}): {completed.stderr.strip()}")
        return VoiceResult(output, wav_duration(output), key, self.engine_name,
                           str(profile.get("version") or "AquesTalk DLL (bundled with YMM4)"), False)


class VoicevoxAdapter(VoiceEngine):
    engine_name = "VOICEVOX"

    def __init__(self, cache_dir: Path, base_url: str = "http://127.0.0.1:50021"):
        super().__init__(cache_dir)
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, data: bytes | None = None, content_type: str | None = None) -> bytes:
        headers = {"Content-Type": content_type} if content_type else {}
        try:
            with urllib.request.urlopen(
                urllib.request.Request(self.base_url + path, data=data, headers=headers), timeout=20
            ) as response:
                return response.read()
        except Exception as exc:
            raise VoiceEngineUnavailable(f"VOICEVOX local engine unavailable at {self.base_url}: {exc}") from exc

    def version(self) -> str:
        return json.loads(self._request("/version").decode("utf-8"))

    def phonetic_reading(self, text: str, style_id: int = 3) -> str:
        query_path = "/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": int(style_id)})
        query = json.loads(self._request(query_path, b"").decode("utf-8"))
        phrases = []
        for phrase in query.get("accent_phrases", []):
            reading = "".join(mora.get("text") or "" for mora in phrase.get("moras", []))
            if reading:
                phrases.append(reading + ("、" if phrase.get("pause_mora") else ""))
        # Accent phrase boundaries are not pauses. Preserve only pauses explicitly
        # reported by VOICEVOX; inserting a comma between every phrase makes
        # AquesTalk stop unnaturally between ordinary words.
        katakana = "".join(phrases).rstrip("、")
        return "".join(chr(ord(char) - 0x60) if "ァ" <= char <= "ヶ" else char for char in katakana)

    def synthesize(self, text: str, profile: dict) -> VoiceResult:
        version = self.version()
        key = voice_cache_key(self.engine_name, {**profile, "engine_version": version}, text)
        output = self.cache_dir / f"{key}.wav"
        if output.exists():
            return VoiceResult(output, wav_duration(output), key, self.engine_name, version, True)
        style_id = int(profile["style_id"])
        query_path = "/audio_query?" + urllib.parse.urlencode({"text": text, "speaker": style_id})
        query = json.loads(self._request(query_path, b"").decode("utf-8"))
        for field in ("speedScale", "pitchScale", "intonationScale", "volumeScale"):
            snake = {"speedScale": "speed_scale", "pitchScale": "pitch_scale",
                     "intonationScale": "intonation_scale", "volumeScale": "volume_scale"}[field]
            if profile.get(snake) is not None:
                query[field] = profile[snake]
        synth_path = "/synthesis?" + urllib.parse.urlencode({"speaker": style_id})
        output.write_bytes(self._request(
            synth_path, json.dumps(query, ensure_ascii=False).encode("utf-8"), "application/json"
        ))
        return VoiceResult(output, wav_duration(output), key, self.engine_name, version, False)
