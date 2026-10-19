from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ENV_TO_RENDER_KEY = {
    "FFMPEG_PATH": "ffmpeg_path",
    "FFPROBE_PATH": "ffprobe_path",
    "VIDEO_FONT_PATH": "font_path",
    "VOICE_RUNTIME_PATH": "aquestalk_dll_root",
    "CSC_PATH": "csc_path",
    "VOICEVOX_URL": "voicevox_url",
}


def load_local_paths(repo_root: Path | str | None = None) -> dict[str, str]:
    root = Path(repo_root).resolve() if repo_root else None
    explicit = os.environ.get("CORBITT_LOCAL_PATHS_FILE")
    candidate = Path(explicit).expanduser() if explicit else (root / "config/local_paths.json" if root else None)
    values: dict[str, str] = {}
    if candidate and candidate.is_file():
        values.update({str(k): str(v) for k, v in json.loads(candidate.read_text(encoding="utf-8-sig")).items() if v})
    for key in set(ENV_TO_RENDER_KEY) | {
        "CORBITT_PROJECT_ROOT", "CORBITT_V13_SOURCE_ROOT", "CORBITT_V13_CONTROL_ROOT",
        "VIDEO_ASSET_ROOT", "VIDEO_OUTPUT_ROOT", "CORBITT_RENDER_WORK_ROOT",
        "VIDEO_PYTHON", "CORE_PYTHON",
    }:
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def apply_render_overrides(config: dict[str, Any], repo_root: Path | str | None = None) -> dict[str, Any]:
    result = dict(config)
    local = load_local_paths(repo_root)
    for env_name, config_name in ENV_TO_RENDER_KEY.items():
        if local.get(env_name):
            result[config_name] = local[env_name]
    return result


def resolve_external_asset(path_value: str | Path, asset_root: str | Path | None = None) -> Path:
    path = Path(path_value)
    root_value = asset_root or os.environ.get("VIDEO_ASSET_ROOT")
    if not root_value:
        return path
    root = Path(root_value)
    text = str(path).replace("/", "\\")
    marker = "素材\\"
    if marker in text:
        return root / text.split(marker, 1)[1]
    return path if path.is_absolute() else root / path
