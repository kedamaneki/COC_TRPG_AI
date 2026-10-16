from pathlib import Path

from video_agent.common.io import read_json


def load_profiles(config_root):
    root = Path(config_root)
    result = {}
    for category in ("characters", "voices", "subtitles", "portraits"):
        result[category] = []
        for path in sorted((root / category).glob("*.json")):
            value = read_json(path)
            result[category].extend(value if isinstance(value, list) else [value])
    return result
