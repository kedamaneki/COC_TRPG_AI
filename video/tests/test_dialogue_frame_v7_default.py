import json
from pathlib import Path

import cv2
import numpy as np

from video_agent.presentation.dialogue_ui import DEFAULT_FRAME_NINE_SLICE
from video_agent.rendering.assets import nine_slice_rgba


REPO = Path(__file__).resolve().parents[2]


def test_v7_frame_asset_and_config_are_the_defaults() -> None:
    presentation = json.loads((REPO / "video/config/presentation_m3.json").read_text(encoding="utf-8"))
    layout = json.loads((REPO / "video/config/presentation_layout_m3.json").read_text(encoding="utf-8"))
    source = REPO / presentation["asset_sources"]["dialogue_frame"]
    assert source.is_file()
    assert source.name == "nc131976_SF風シンプルセリフ枠_外周trim.png"
    assert layout["dialogue_frame"]["x"] == 0
    assert layout["dialogue_frame"]["width"] == 1920
    assert layout["dialogue_frame"]["height"] == 420
    assert layout["dialogue_frame"]["nine_slice"] == DEFAULT_FRAME_NINE_SLICE
    assert layout["name_font_size"] == layout["dialogue_font_size"] == 62
    assert layout["pagination"]["lines_per_page"] == 2


def test_v7_default_frame_has_no_visible_outer_gap() -> None:
    presentation = json.loads((REPO / "video/config/presentation_m3.json").read_text(encoding="utf-8"))
    source = REPO / presentation["asset_sources"]["dialogue_frame"]
    image = cv2.imdecode(np.fromfile(str(source), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    assert image is not None
    layer = nine_slice_rgba(image, 1920, 420, DEFAULT_FRAME_NINE_SLICE)
    alpha = layer[:, :, 3]
    points = cv2.findNonZero((alpha > 0).astype(np.uint8))
    x, y, width, height = cv2.boundingRect(points)
    assert (x, y, width, height) == (0, 0, 1920, 420)
