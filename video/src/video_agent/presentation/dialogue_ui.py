from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

from video_agent.rendering.subtitles import (
    BREAK_PARTICLES,
    LINE_END_PROHIBITED,
    LINE_START_PROHIBITED,
    japanese_line_breaks,
    text_pixel_width,
)


# Accepted V2.6 Alt Dialogue Frame Prototype V7 is the presentation default.
DEFAULT_DIALOGUE_FONT_SIZE = 62
DEFAULT_NAME_FONT_SIZE = 62
DEFAULT_SPEAKER_ICON_SCALE = 1.15
DEFAULT_FRAME_NINE_SLICE = {"left": 72, "right": 72, "top": 64, "bottom": 72}


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2

    def overlaps(self, other: "Rect") -> bool:
        return self.x < other.right and self.right > other.x and self.y < other.bottom and self.bottom > other.y


@dataclass(frozen=True)
class DialogueUILayout:
    canvas_width: int
    canvas_height: int
    dialogue_frame: Rect
    name_plate: Rect
    speaker_icon: Rect
    text_safe_area: Rect
    dialogue_font_scale: float = 1.20
    speaker_icon_scale: float = DEFAULT_SPEAKER_ICON_SCALE
    maximum_dialogue_lines: int = 2
    line_height: float = 1.18
    minimum_dialogue_font_scale: float = 0.88
    name_plate_anchor: str = "NAME_PLATE_CENTER"

    def as_dict(self) -> dict:
        value = asdict(self)
        value["name_plate"]["anchor"] = self.name_plate_anchor
        return value


def layout_for_canvas(width: int = 1920, height: int = 1080) -> DialogueUILayout:
    sx, sy = width / 1920.0, height / 1080.0

    def rect(x: int, y: int, w: int, h: int) -> Rect:
        return Rect(round(x * sx), round(y * sy), round(w * sx), round(h * sy))

    return DialogueUILayout(
        canvas_width=width,
        canvas_height=height,
        dialogue_frame=rect(0, 660, 1920, 420),
        name_plate=rect(0, 660, 640, 68),
        speaker_icon=rect(82, 784, 173, 173),
        text_safe_area=rect(287, 766, 1561, 278),
    )


def fit_name_font_size(name: str, plate: Rect, preferred: int = DEFAULT_NAME_FONT_SIZE,
                       minimum_scale: float = 0.80) -> int:
    available = plate.width - 40
    minimum = round(preferred * minimum_scale)
    for size in range(preferred, minimum - 1, -1):
        if text_pixel_width(name, size) <= available:
            return size
    return minimum


def wrap_dialogue(text: str, safe_area: Rect, preferred_font_size: int = DEFAULT_DIALOGUE_FONT_SIZE,
                  maximum_lines: int = 2, minimum_scale: float = 0.88) -> dict:
    minimum = round(preferred_font_size * minimum_scale)
    for size in range(preferred_font_size, minimum - 1, -1):
        if text_pixel_width(text, size) > safe_area.width and maximum_lines == 2:
            choices = []
            for index in range(1, len(text)):
                first, second = text[:index].rstrip(), text[index:].lstrip()
                if not first or not second or first[-1] in LINE_END_PROHIBITED or second[0] in LINE_START_PROHIBITED:
                    continue
                if text_pixel_width(first, size) > safe_area.width or text_pixel_width(second, size) > safe_area.width:
                    continue
                if first[-1] in "。！？!?":
                    priority = 6
                elif first[-1] in "、，,；;：:":
                    priority = 5
                elif any(first.endswith(particle) for particle in BREAK_PARTICLES):
                    priority = 4
                elif first[-1].isspace():
                    priority = 3
                else:
                    continue
                balance = abs(text_pixel_width(first, size) - text_pixel_width(second, size))
                choices.append((priority, -balance, first, second))
            if choices:
                _, _, first, second = max(choices)
                return {"lines": [first, second], "font_size": size, "overflow": False,
                        "line_count": 2, "font_scale_from_preferred": size / preferred_font_size}
        lines, unbreakable = japanese_line_breaks(text, safe_area.width, size)
        if not unbreakable and len(lines) <= maximum_lines:
            return {"lines": lines, "font_size": size, "overflow": False,
                    "line_count": len(lines), "font_scale_from_preferred": size / preferred_font_size}
    lines, unbreakable = japanese_line_breaks(text, safe_area.width, minimum)
    return {"lines": lines, "font_size": minimum,
            "overflow": unbreakable or len(lines) > maximum_lines,
            "line_count": len(lines), "font_scale_from_preferred": minimum / preferred_font_size}


def audit_dialogue_ui(clips: Iterable[dict], layout: DialogueUILayout,
                      preferred_font_size: int = DEFAULT_DIALOGUE_FONT_SIZE,
                      preferred_name_size: int = DEFAULT_NAME_FONT_SIZE) -> dict:
    keys = (
        "NAME_PLATE_EMPTY_WHEN_SPEAKER_PRESENT", "NAME_OUTSIDE_NAME_PLATE",
        "NAME_PLATE_TEXT_CLIPPING", "DIALOGUE_FONT_TOO_SMALL", "DIALOGUE_TEXT_CLIPPING",
        "DIALOGUE_TEXT_OVERFLOW", "DIALOGUE_LINE_COUNT_EXCEEDED", "SPEAKER_ICON_TOO_SMALL",
        "SPEAKER_ICON_DIALOGUE_COLLISION", "SPEAKER_ICON_NAME_PLATE_COLLISION",
        "VERTICAL_ALIGNMENT_MISMATCH",
    )
    counts = {key: 0 for key in keys}
    details = {key: [] for key in keys}
    minimum_dialogue_size = round(preferred_font_size * layout.minimum_dialogue_font_scale)
    minimum_icon = round(150 * layout.speaker_icon_scale)
    for clip in clips:
        clip_id = clip.get("clip_id") or clip.get("fixture_id") or "unknown"
        mode = clip.get("presentation_mode", "VOICED")
        speaker = clip.get("speaker_id") or ""
        voiced_speaker = mode == "VOICED" and speaker != "system"
        name = str(clip.get("speaker_name") or "")
        if voiced_speaker and not name:
            counts["NAME_PLATE_EMPTY_WHEN_SPEAKER_PRESENT"] += 1
            details["NAME_PLATE_EMPTY_WHEN_SPEAKER_PRESENT"].append(clip_id)
        if name:
            name_size = fit_name_font_size(name, layout.name_plate, preferred_name_size)
            if text_pixel_width(name, name_size) > layout.name_plate.width - 40:
                counts["NAME_OUTSIDE_NAME_PLATE"] += 1
                counts["NAME_PLATE_TEXT_CLIPPING"] += 1
                details["NAME_OUTSIDE_NAME_PLATE"].append(clip_id)
                details["NAME_PLATE_TEXT_CLIPPING"].append(clip_id)
        wrapped = wrap_dialogue(str(clip.get("subtitle_text") or ""), layout.text_safe_area,
                                preferred_font_size, layout.maximum_dialogue_lines,
                                layout.minimum_dialogue_font_scale)
        clip["dialogue_ui"] = {**wrapped, "name_font_size": fit_name_font_size(name, layout.name_plate, preferred_name_size) if name else None}
        if wrapped["font_size"] < minimum_dialogue_size:
            counts["DIALOGUE_FONT_TOO_SMALL"] += 1
            details["DIALOGUE_FONT_TOO_SMALL"].append(clip_id)
        if wrapped["overflow"]:
            counts["DIALOGUE_TEXT_OVERFLOW"] += 1
            counts["DIALOGUE_TEXT_CLIPPING"] += 1
            details["DIALOGUE_TEXT_OVERFLOW"].append(clip_id)
            details["DIALOGUE_TEXT_CLIPPING"].append(clip_id)
        if wrapped["line_count"] > layout.maximum_dialogue_lines:
            counts["DIALOGUE_LINE_COUNT_EXCEEDED"] += 1
            details["DIALOGUE_LINE_COUNT_EXCEEDED"].append(clip_id)
        if voiced_speaker and not clip.get("speaker_icon_asset_id"):
            counts["SPEAKER_ICON_TOO_SMALL"] += 1
            details["SPEAKER_ICON_TOO_SMALL"].append(clip_id)
    if layout.speaker_icon.width < minimum_icon or layout.speaker_icon.height < minimum_icon:
        counts["SPEAKER_ICON_TOO_SMALL"] += 1
        details["SPEAKER_ICON_TOO_SMALL"].append("layout")
    if layout.speaker_icon.overlaps(layout.text_safe_area):
        counts["SPEAKER_ICON_DIALOGUE_COLLISION"] += 1
        details["SPEAKER_ICON_DIALOGUE_COLLISION"].append("layout")
    if layout.speaker_icon.overlaps(layout.name_plate):
        counts["SPEAKER_ICON_NAME_PLATE_COLLISION"] += 1
        details["SPEAKER_ICON_NAME_PLATE_COLLISION"].append("layout")
    if layout.name_plate.center[1] >= layout.text_safe_area.y or layout.text_safe_area.bottom > layout.dialogue_frame.bottom:
        counts["VERTICAL_ALIGNMENT_MISMATCH"] += 1
        details["VERTICAL_ALIGNMENT_MISMATCH"].append("layout")
    return {"status": "PASS" if not any(counts.values()) else "FAIL", "counts": counts, "details": details,
            "metrics": {"dialogue_font_scale": layout.dialogue_font_scale,
                        "speaker_icon_scale": layout.speaker_icon_scale,
                        "dialogue_font_size": preferred_font_size,
                        "name_font_size": preferred_name_size,
                        "name_plate_bounds": asdict(layout.name_plate),
                        "text_safe_area_bounds": asdict(layout.text_safe_area),
                        "max_line_count": layout.maximum_dialogue_lines}}
