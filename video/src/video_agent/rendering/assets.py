from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def create_test_assets(root: Path) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    background = root / "fallback_background.png"
    aq = root / "portrait_aquestalk.png"
    vv = root / "portrait_voicevox.png"
    if not background.exists():
        image = np.zeros((1080, 1920, 3), dtype=np.uint8)
        for y in range(1080):
            image[y, :, :] = (32 + y // 24, 26 + y // 36, 24 + y // 54)
        cv2.rectangle(image, (80, 70), (1840, 690), (54, 46, 43), -1)
        cv2.rectangle(image, (120, 110), (1800, 650), (72, 62, 58), 8)
        _write_image(background, image)
    _portrait(aq, (60, 90, 220), (180, 220, 255))
    _portrait(vv, (180, 150, 40), (255, 235, 150))
    return {"m1_background_fallback": background, "m1_portrait_aquestalk": aq, "m1_portrait_voicevox": vv}


def _portrait(path: Path, coat: tuple[int, int, int], hair: tuple[int, int, int]) -> None:
    if path.exists():
        return
    image = np.zeros((720, 480, 4), dtype=np.uint8)
    cv2.ellipse(image, (240, 600), (210, 230), 0, 0, 360, (*coat, 255), -1)
    cv2.circle(image, (240, 270), 205, (*hair, 255), -1)
    cv2.ellipse(image, (240, 315), (150, 165), 0, 0, 360, (205, 220, 245, 255), -1)
    cv2.circle(image, (185, 300), 18, (20, 20, 20, 255), -1)
    cv2.circle(image, (295, 300), 18, (20, 20, 20, 255), -1)
    cv2.ellipse(image, (240, 375), (50, 20), 0, 0, 180, (40, 40, 80, 255), 6)
    _write_image(path, image)


def _alpha_blend(canvas: np.ndarray, layer: np.ndarray, x: int, y: int) -> None:
    height, width = layer.shape[:2]
    if x < 0 or y < 0 or x + width > canvas.shape[1] or y + height > canvas.shape[0]:
        raise ValueError("overlay outside canvas")
    if layer.shape[2] == 4:
        alpha = layer[:, :, 3:4].astype(np.float32) / 255.0
        canvas[y:y + height, x:x + width] = (
            layer[:, :, :3] * alpha + canvas[y:y + height, x:x + width] * (1 - alpha)
        ).astype(np.uint8)
    else:
        canvas[y:y + height, x:x + width] = layer[:, :, :3]


def _read_image(path: Path, flags: int) -> np.ndarray | None:
    """Read images without depending on OpenCV's Windows Unicode-path support."""
    try:
        return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), flags)
    except (OSError, ValueError):
        return None


def _write_image(path: Path, image: np.ndarray) -> None:
    suffix = path.suffix or ".png"
    ok, encoded = cv2.imencode(suffix, image)
    if not ok:
        raise RuntimeError(f"image encode failed: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded.tofile(str(path))


def nine_slice_rgba(image: np.ndarray, width: int, height: int, boundaries: dict) -> np.ndarray:
    """Scale a dialogue frame while preserving the accepted V7 border geometry."""
    source_h, source_w = image.shape[:2]
    left, right = int(boundaries["left"]), int(boundaries["right"])
    top, bottom = int(boundaries["top"]), int(boundaries["bottom"])
    if min(left, right, top, bottom) < 0:
        raise ValueError("nine-slice boundaries must be non-negative")
    if left + right >= source_w or top + bottom >= source_h:
        raise ValueError("nine-slice boundaries exceed source image")
    if left + right >= width or top + bottom >= height:
        raise ValueError("nine-slice target is too small")
    xs, ys = (0, left, source_w - right, source_w), (0, top, source_h - bottom, source_h)
    dx, dy = (0, left, width - right, width), (0, top, height - bottom, height)
    output = np.zeros((height, width, image.shape[2]), dtype=image.dtype)
    for row in range(3):
        for column in range(3):
            tile = image[ys[row]:ys[row + 1], xs[column]:xs[column + 1]]
            output[dy[row]:dy[row + 1], dx[column]:dx[column + 1]] = cv2.resize(
                tile,
                (dx[column + 1] - dx[column], dy[row + 1] - dy[row]),
                interpolation=cv2.INTER_LINEAR,
            )
    return output


def rectangles_overlap(first: dict, second: dict) -> bool:
    return not (int(first["x"]) + int(first["width"]) <= int(second["x"]) or
                int(second["x"]) + int(second["width"]) <= int(first["x"]) or
                int(first["y"]) + int(first["height"]) <= int(second["y"]) or
                int(second["y"]) + int(second["height"]) <= int(first["y"]))


def head_portrait_box(image_width: int, image_height: int, slot: dict) -> dict:
    margin = int(slot.get("safe_margin", 0))
    available_width = min(int(slot["width"]) - margin * 2, int(slot.get("max_face_width", image_width)))
    available_height = min(int(slot["height"]) - margin * 2, int(slot.get("max_face_height", image_height)))
    scale = min(available_width / image_width, available_height / image_height, 1.0)
    width, height = max(1, round(image_width * scale)), max(1, round(image_height * scale))
    return {
        "x": int(slot["x"]) + (int(slot["width"]) - width) // 2,
        "y": int(slot["y"]) + (int(slot["height"]) - height) // 2,
        "width": width, "height": height,
    }


def layout_overlap_issues(layout: dict) -> list[str]:
    issues = []
    for first_name, second_name in layout.get("forbidden_overlaps", []):
        first, second = layout.get(first_name), layout.get(second_name)
        if first and second and rectangles_overlap(first, second):
            issues.append(f"{first_name}_OVERLAPS_{second_name}")
    return issues


def compose_frame(background: Path, portrait: Path | None, output: Path, side: str,
                  dialogue_frame: Path | None = None, frame_region: dict | None = None,
                  portrait_kind: str = "FULL_BODY", layout: dict | None = None) -> None:
    canvas = _read_image(background, cv2.IMREAD_COLOR)
    if canvas is None:
        raise FileNotFoundError(background)
    if portrait:
        layer = _read_image(portrait, cv2.IMREAD_UNCHANGED)
        if layer is None:
            raise FileNotFoundError(portrait)
        if portrait_kind == "HEAD_ONLY":
            slot_name = "head_portrait_left_region" if side == "left" else "head_portrait_right_region"
            slot = (layout or {}).get(slot_name)
            if not slot:
                raise ValueError(f"missing HEAD_ONLY slot: {slot_name}")
            box = head_portrait_box(layer.shape[1], layer.shape[0], slot)
            layer = cv2.resize(layer, (box["width"], box["height"]), interpolation=cv2.INTER_AREA)
            x, y = box["x"], box["y"]
        else:
            x = 90 if side == "left" else canvas.shape[1] - layer.shape[1] - 90
            y = canvas.shape[0] - layer.shape[0]
        _alpha_blend(canvas, layer, x, y)
    if dialogue_frame:
        layer = _read_image(dialogue_frame, cv2.IMREAD_UNCHANGED)
        if layer is None:
            raise FileNotFoundError(dialogue_frame)
        region = frame_region or {"x": 160, "y": 670, "width": 1600, "height": 375}
        boundaries = region.get("nine_slice")
        if boundaries:
            layer = nine_slice_rgba(layer, int(region["width"]), int(region["height"]), boundaries)
        else:
            layer = cv2.resize(layer, (int(region["width"]), int(region["height"])), interpolation=cv2.INTER_AREA)
        _alpha_blend(canvas, layer, int(region["x"]), int(region["y"]))
    _write_image(output, canvas)
