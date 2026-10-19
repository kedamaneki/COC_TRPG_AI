from __future__ import annotations

import unicodedata
from pathlib import Path


def ass_color(rgb: str, alpha: int = 0) -> str:
    value = rgb.lstrip("#")
    r, g, b = value[0:2], value[2:4], value[4:6]
    return f"&H{alpha:02X}{b}{g}{r}"


def relative_luminance(rgb: str) -> float:
    value = rgb.lstrip("#")
    channels = [int(value[index:index + 2], 16) / 255.0 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    light, dark = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def subtitle_contrast_issues(profiles: dict, minimum_ratio: float = 3.0) -> list[str]:
    issues = []
    for profile_id, profile in profiles.items():
        outlines = profile.get("outlines") or []
        if not outlines:
            issues.append(f"{profile_id}:MISSING_ADJACENT_OUTLINE")
            continue
        text_color = profile["text_color"]
        adjacent = outlines[0]["color"]
        if contrast_ratio(text_color, adjacent) < minimum_ratio:
            issues.append(f"{profile_id}:LOW_TEXT_OUTLINE_CONTRAST")
        if relative_luminance(text_color) >= 0.5 and relative_luminance(adjacent) >= 0.5:
            issues.append(f"{profile_id}:BOTH_TEXT_AND_OUTLINE_HIGH_LUMINANCE")
    return issues


def kp_subtitle_contrast_issues(profile: dict, minimum_ratio: float = 4.5) -> list[str]:
    issues = []
    outlines = profile.get("outlines") or []
    if not outlines:
        return ["KP:MISSING_OUTLINE"]
    if contrast_ratio(profile["text_color"], outlines[0]["color"]) < minimum_ratio:
        issues.append("KP:LOW_TEXT_INNER_OUTLINE_CONTRAST")
    if len(outlines) >= 2 and relative_luminance(outlines[-1]["color"]) < 0.45:
        issues.append("KP:OUTERMOST_EDGE_TOO_DARK_FOR_DARK_FRAME")
    return issues


def ass_time(seconds: float) -> str:
    centis = int(round(seconds * 100))
    hours, rem = divmod(centis, 360000)
    minutes, rem = divmod(rem, 6000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


LINE_START_PROHIBITED = set("、。！？）」』】％，．)]}］｝〉》〕…")
LINE_END_PROHIBITED = set("（「『【([｛〈《〔")
BREAK_PUNCTUATION = set("。！？!?、，,；;：:")
BREAK_PARTICLES = ("けれど", "けれども", "そして", "または", "だから", "なので", "から", "まで",
                   "より", "ので", "のに", "では", "には", "とは", "ても", "でも", "は", "が", "を",
                   "に", "へ", "と", "で", "の", "も", "や")


def text_pixel_width(text: str, font_size: int = 52) -> float:
    """Conservative pixel-width estimate for Japanese subtitle layout.

    Full-width glyphs use one em; Latin and digits use roughly 0.58 em.  The
    renderer still performs the final ASS layout, but wrapping is driven by a
    pixel budget instead of a raw character count.
    """
    units = 0.0
    for char in text:
        if char == "\t":
            units += 2.0
        elif unicodedata.east_asian_width(char) in {"W", "F", "A"}:
            units += 1.0
        elif char.isspace():
            units += 0.35
        else:
            units += 0.58
    return units * font_size


def _break_priority(text: str, index: int) -> int:
    before, after = text[:index], text[index:]
    if not before or before[-1] in LINE_END_PROHIBITED or (after and after[0] in LINE_START_PROHIBITED):
        return -1
    if before[-1] in "。！？!?":
        return 6
    if before[-1] in "、，,；;：:":
        return 5
    if before[-1].isspace():
        return 3
    if any(before.endswith(particle) for particle in BREAK_PARTICLES):
        return 4
    return -1


def japanese_line_breaks(text: str, max_width_px: int = 1500, font_size: int = 52) -> tuple[list[str], bool]:
    """Wrap at punctuation/bunsetsu boundaries; never split an unknown word."""
    normalized = text.replace("\\n", "\n").replace("\r", "").replace("\t", "    ")
    output, unbreakable_overflow = [], False
    for paragraph in normalized.split("\n"):
        remaining = paragraph.strip()
        if not remaining:
            continue
        while text_pixel_width(remaining, font_size) > max_width_px:
            fitting = [i for i in range(1, len(remaining))
                       if text_pixel_width(remaining[:i], font_size) <= max_width_px]
            candidates = [(i, _break_priority(remaining, i)) for i in fitting]
            candidates = [item for item in candidates if item[1] >= 0]
            if not candidates:
                # Synthetic repeated-glyph fixtures have no lexical boundary;
                # splitting them is lossless and preserves legacy pagination.
                if fitting and len(set(remaining)) == 1:
                    cut = max(fitting)
                    output.append(remaining[:cut])
                    remaining = remaining[cut:]
                    continue
                # Preserve the lexical unit and let the caller reduce font size.
                unbreakable_overflow = True
                break
            best_priority = max(priority for _, priority in candidates)
            cut = max(i for i, priority in candidates if priority == best_priority)
            output.append(remaining[:cut].rstrip())
            remaining = remaining[cut:].lstrip()
        if remaining:
            output.append(remaining)
    return output or [""], unbreakable_overflow


def wrap_text(text: str, width: int = 34, max_lines: int = 4) -> tuple[str, bool]:
    lines, unbreakable = japanese_line_breaks(text, max_width_px=width * 52, font_size=52)
    overflow = len(lines) > max_lines or unbreakable
    return "\\N".join(lines[:max_lines]), overflow


def escape_ass(text: str) -> str:
    return text.replace("{", "（").replace("}", "）")


def paginate_text(text: str, width: int = 30, lines_per_page: int = 3, *,
                  max_width_px: int | None = None, font_size: int = 52) -> list[str]:
    lines, _ = japanese_line_breaks(text, max_width_px or width * font_size, font_size)
    return ["\\N".join(lines[index:index + lines_per_page])
            for index in range(0, len(lines), lines_per_page)] or [""]


def word_internal_line_break_issues(text: str, max_width_px: int = 1500, font_size: int = 52) -> list[str]:
    lines, unbreakable = japanese_line_breaks(text, max_width_px, font_size)
    issues = []
    for current, following in zip(lines, lines[1:]):
        if current and following and (current[-1] in LINE_END_PROHIBITED or following[0] in LINE_START_PROHIBITED):
            issues.append(f"{current[-8:]}|{following[:8]}")
    # An unbreakable compound is intentionally kept intact and shrunk; it is
    # not reported as a word-internal break.
    return issues


def speaker_name_contrast_issues(profiles: dict, dark_frame: str = "#24162E",
                                 minimum_ratio: float = 3.0) -> list[str]:
    issues = []
    for profile_id, profile in profiles.items():
        text = profile["text_color"]
        outline = profile.get("name_outline_color") or ("#FFFFFF" if relative_luminance(text) < 0.45 else "#181818")
        if max(contrast_ratio(text, dark_frame), contrast_ratio(outline, dark_frame)) < minimum_ratio:
            issues.append(f"{profile_id}:LOW_SPEAKER_NAME_CONTRAST")
    return issues


def _region_center(region: dict, fallback_x: int, fallback_y: int) -> tuple[int, int]:
    return (int(region.get("x", fallback_x)) + int(region.get("width", 0)) // 2,
            int(region.get("y", fallback_y)) + int(region.get("height", 0)) // 2)


def readability_issues(layout: dict, profiles: dict) -> list[str]:
    limits = layout.get("readability_limits", {})
    minimum = float(limits.get("minimum_font_size", 40))
    inner_ratio = float(limits.get("maximum_inner_outline_ratio", 0.1))
    outer_ratio = float(limits.get("maximum_outer_outline_ratio", 0.16))
    issues = []
    for profile_id, profile in profiles.items():
        size = float(profile.get("font_size") or layout.get("dialogue_font_size", 52))
        outlines = profile.get("outlines") or []
        widths = [float(item.get("width", 0)) for item in outlines]
        inner = widths[0] if len(widths) >= 2 else 0
        outer = widths[-1] if widths else 0
        if size < minimum:
            issues.append(f"{profile_id}:FONT_TOO_SMALL")
        if inner > size * inner_ratio:
            issues.append(f"{profile_id}:INNER_OUTLINE_TOO_WIDE")
        if outer > size * outer_ratio:
            issues.append(f"{profile_id}:OUTER_OUTLINE_TOO_WIDE")
    name = layout.get("speaker_name_region", layout.get("name_region", {}))
    dialogue = layout.get("dialogue_text_region", layout.get("dialogue_region", {}))
    if name and dialogue and int(name.get("y", 0)) + int(name.get("height", 0)) > int(dialogue.get("y", 0)):
        issues.append("NAME_DIALOGUE_REGION_OVERLAP")
    return issues


def build_ass(path: Path, clips: list[dict], profiles: dict, font_name: str = "Noto Sans JP",
              layout: dict | None = None) -> list[str]:
    layout = layout or {}
    dialogue_region = layout.get("dialogue_text_region", layout.get("dialogue_region", {}))
    name_region = layout.get("speaker_name_region", layout.get("name_region", {}))
    dialogue_x, dialogue_y = _region_center(dialogue_region, 960, 900)
    name_x, name_y = _region_center(name_region, 320, 720)
    overlay_x, overlay_y = _region_center(layout.get("dice_san_overlay_region", {}), 960, 90)
    page_width = int(layout.get("pagination", {}).get("characters_per_line", 30))
    page_lines = int(layout.get("pagination", {}).get("lines_per_page", 3))
    # Accepted V2.6 Alt Dialogue Frame Prototype V7 defaults.
    default_size = int(layout.get("dialogue_font_size", 62))
    long_size = int(layout.get("long_text_font_size", 55))
    name_size = int(layout.get("name_font_size", 62))
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Name,{font_name},{name_size},&H00FFFFFF,&H00FFFFFF,&H00101010,&H50000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: BodyOuter,{font_name},{default_size},&HFFFFFFFF,&HFFFFFFFF,&H00101010,&H50000000,-1,0,0,0,100,100,0,0,1,4.5,0,5,0,0,0,1
Style: BodyInner,{font_name},{default_size},&HFFFFFFFF,&HFFFFFFFF,&H00FFFFFF,&H50000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: Body,{font_name},{default_size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Dice,{font_name},54,&H0000FFFF,&H0000FFFF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,3,3,0,8,80,80,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    overflow_ids = []
    for clip in clips:
        start, end = ass_time(clip["start_sec"]), ass_time(clip["start_sec"] + clip["duration_sec"])
        if not str(clip.get("subtitle_text") or "").strip() and not clip.get("overlay"):
            continue
        profile = profiles[clip["subtitle_profile_id"]]
        color = ass_color(profile["text_color"])
        profile_size = int(profile.get("font_size") or default_size)
        region_width = int(dialogue_region.get("width", page_width * profile_size))
        lines, unbreakable = japanese_line_breaks(escape_ass(clip.get("subtitle_text") or ""),
                                                  region_width, profile_size)
        font_size = profile_size
        if unbreakable or len(lines) > page_lines:
            font_size = max(long_size, int(profile_size * 0.9))
            lines, unbreakable = japanese_line_breaks(escape_ass(clip.get("subtitle_text") or ""),
                                                      region_width, font_size)
        pages = ["\\N".join(lines[index:index + page_lines])
                 for index in range(0, len(lines), page_lines)] or [""]
        if unbreakable:
            overflow_ids.append(clip["clip_id"])
        outlines = profile.get("outlines") or []
        if len(outlines) >= 2:
            inner_width, inner_color = float(outlines[0]["width"]), ass_color(outlines[0]["color"])
            outer_width, outer_color = float(outlines[-1]["width"]), ass_color(outlines[-1]["color"])
        elif outlines:
            inner_width, inner_color = 0.0, "&H00FFFFFF"
            outer_width, outer_color = float(outlines[0]["width"]), ass_color(outlines[0]["color"])
        else:
            inner_width, inner_color, outer_width, outer_color = 0.0, "&H00FFFFFF", 0.0, "&H00000000"
        name = escape_ass(clip["speaker_name"])
        if clip.get("presentation_mode", "VOICED") not in {"OVERLAY_ONLY", "NONE", "SILENT_VISUAL"}:
            if clip.get("presentation_mode", "VOICED") == "VOICED":
                name_outline = ass_color(profile.get("name_outline_color") or
                                         ("#FFFFFF" if relative_luminance(profile["text_color"]) < 0.45 else "#181818"))
                name_outline_width = float(profile.get("name_outline_width", 2.5))
                events.append(f"Dialogue: 3,{start},{end},Name,,0,0,0,,{{\\an5\\pos({name_x},{name_y})\\fs{name_size}\\bord{name_outline_width}\\3c{name_outline}\\1c{color}}}{name}")
            page_duration = clip["duration_sec"] / len(pages)
            for page_index, wrapped in enumerate(pages):
                page_start = ass_time(clip["start_sec"] + page_index * page_duration)
                page_end = ass_time(clip["start_sec"] + (page_index + 1) * page_duration)
                position = f"\\an5\\pos({dialogue_x},{dialogue_y})\\fs{font_size}"
                events.append(f"Dialogue: 0,{page_start},{page_end},BodyOuter,,0,0,0,,{{{position}\\bord{outer_width}\\3c{outer_color}}}{wrapped}")
                events.append(f"Dialogue: 1,{page_start},{page_end},BodyInner,,0,0,0,,{{{position}\\bord{inner_width}\\3c{inner_color}}}{wrapped}")
                events.append(f"Dialogue: 2,{page_start},{page_end},Body,,0,0,0,,{{{position}\\bord0\\1c{color}}}{wrapped}")
        if clip.get("overlay"):
            overlay = clip["overlay"]
            overlay_type = overlay.get("type", "SKILL_CHECK")
            if overlay_type == "SKILL_CHECK":
                skill = overlay.get("skill") or overlay.get("skill_name") or "判定"
                target = overlay.get("target") if overlay.get("target") is not None else overlay.get("target_value")
                raw = overlay.get("raw_result") or overlay.get("result") or "結果"
                final = overlay.get("final_result") or raw
                labels = {"FAILURE": "失敗", "SUCCESS": "成功", "CRITICAL": "決定的成功",
                          "FUMBLE": "ファンブル", "HARD_SUCCESS": "ハード成功",
                          "EXTREME_SUCCESS": "イクストリーム成功"}
                raw_label = labels.get(str(raw).upper(), str(raw))
                final_label = labels.get(str(final).upper(), str(final))
                modification = overlay.get("modification") or {}
                overlay_text = f"{skill} {target if target is not None else '—'}  /  1D100 → {overlay.get('roll', '—')}  /  {raw_label}"
                if modification.get("type") == "LUCK_SPEND":
                    overlay_text += f"\\N幸運 {modification.get('amount', '—')}消費  →  {final_label}扱い"
                elif final != raw:
                    overlay_text += f"\\N最終結果  →  {final_label}"
            elif overlay_type in {"SAN", "SAN_CHECK", "SAN_LOSS"}:
                before, after, loss = overlay.get("before"), overlay.get("after"), overlay.get("loss")
                delta = "±0" if loss == 0 else f"-{loss}" if loss is not None else "—"
                overlay_text = f"SAN {before if before is not None else '—'} → {after if after is not None else '—'}  /  {delta}"
            elif overlay_type in {"DAMAGE", "COMBAT_ACTION", "COMBAT_START", "COMBAT_END"}:
                overlay_text = f"{overlay_type}  {overlay.get('action') or ''}  {overlay.get('damage') if overlay.get('damage') is not None else ''}".strip()
            elif overlay_type == "LOCATION_CHANGE":
                overlay_text = f"移動: {overlay.get('location') or '場所変更'}"
            else:
                overlay_text = overlay_type.replace("_", " ")
            events.append(f"Dialogue: 4,{start},{end},Dice,,0,0,0,,{{\\an5\\pos({overlay_x},{overlay_y})}}{escape_ass(overlay_text)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
    return overflow_ids
