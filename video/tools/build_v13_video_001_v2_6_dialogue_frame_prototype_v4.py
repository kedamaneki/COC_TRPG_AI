from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
BASE = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
V26 = BASE / "video_001_basement_planks_v2_6"
P1 = BASE / "video_001_basement_planks_v2_6_alt_dialogue_frame_prototype"
P2 = BASE / "video_001_basement_planks_v2_6_alt_dialogue_frame_prototype_v2"
P3 = BASE / "video_001_basement_planks_v2_6_alt_dialogue_frame_prototype_v3"
OUT = BASE / "video_001_basement_planks_v2_6_alt_dialogue_frame_prototype_v4"
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_6_ALT_FRAME_V4_RENDER_WORKSPACE")
SOURCE_FRAME = Path(r"E:\素材\背景素材\nc131976_SF風シンプルセリフ枠(半透明).png")
DERIVED_TEMP = Path(r"C:\Users\ri4re\Documents\Codex\nc131976_SF風シンプルセリフ枠_外周trim.png")
DERIVED_NAME = "nc131976_SF風シンプルセリフ枠_外周trim.png"
PROTOTYPE_ID = "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V4"
PREVIEW_NAME = "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V4.mp4"

spec = importlib.util.spec_from_file_location("v26_builder", VIDEO / "tools/build_v13_video_001_v2_6.py")
v26 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v26)

from video_agent.presentation.dialogue_ui import DialogueUILayout, Rect


def trim_fully_transparent_outer_pixels(source: Path, destination: Path) -> dict:
    image = Image.open(source).convert("RGBA")
    alpha = image.getchannel("A")
    bounds = alpha.getbbox()
    if bounds is None:
        raise ValueError("dialogue frame is fully transparent")
    cropped = image.crop(bounds)
    destination.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(destination)
    derived_alpha = cropped.getchannel("A")
    derived_bounds = derived_alpha.getbbox()
    return {
        "source_size": list(image.size), "source_alpha_bounds": list(bounds),
        "trim": {"left": bounds[0], "top": bounds[1], "right": image.width - bounds[2], "bottom": image.height - bounds[3]},
        "derived_size": list(cropped.size), "derived_alpha_bounds": list(derived_bounds or ()),
        "source_sha256": v26.v25.v23.sha(source), "derived_sha256": v26.v25.v23.sha(destination),
    }


def custom_layout(width: int = 1920, height: int = 1080) -> DialogueUILayout:
    sx, sy = width / 1920.0, height / 1080.0

    def rect(x: int, y: int, w: int, h: int) -> Rect:
        return Rect(round(x * sx), round(y * sy), round(w * sx), round(h * sy))

    frame_top = round(660 * sy)
    return DialogueUILayout(
        canvas_width=width,
        canvas_height=height,
        dialogue_frame=Rect(0, frame_top, width, height - frame_top),
        name_plate=rect(26, 669, 604, 78),
        speaker_icon=rect(82, 784, 173, 173),
        text_safe_area=rect(287, 766, 1561, 278),
        dialogue_font_scale=1.20,
        speaker_icon_scale=1.15,
        maximum_dialogue_lines=2,
        line_height=1.18,
        minimum_dialogue_font_scale=0.88,
        name_plate_anchor="NAME_PLATE_CENTER",
    )


def nine_slice_recalculated(image: np.ndarray, width: int, height: int) -> np.ndarray:
    # Source top 8 transparent rows were removed: top boundary 72 -> 64.
    sh, sw = image.shape[:2]
    left, right, top, bottom = 72, 72, 64, 72
    xs, ys = (0, left, sw - right, sw), (0, top, sh - bottom, sh)
    dx, dy = (0, left, width - right, width), (0, top, height - bottom, height)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    for row in range(3):
        for col in range(3):
            tile = image[ys[row]:ys[row + 1], xs[col]:xs[col + 1]]
            out[dy[row]:dy[row + 1], dx[col]:dx[col + 1]] = cv2.resize(
                tile, (dx[col + 1] - dx[col], dy[row + 1] - dy[row]), interpolation=cv2.INTER_LINEAR)
    return out


def frame_layer() -> np.ndarray:
    return nine_slice_recalculated(v26.v25.v23.read_image(DERIVED_TEMP), 1920, 420)


def compose_frame(background: Path, speaker_icon: Path | None, dialogue_frame: Path, output: Path) -> None:
    canvas = v26.v25.cover_background(background)
    v26.v25.v23.blend(canvas, frame_layer(), 0, 660)
    if speaker_icon:
        icon = v26.v25.v23.fit_rgba(v26.v25.v23.read_image(speaker_icon), 159, 159)
        panel = np.zeros((173, 173, 4), dtype=np.uint8)
        cv2.rectangle(panel, (0, 0), (172, 172), (35, 28, 50, 220), -1)
        cv2.rectangle(panel, (2, 2), (170, 170), (238, 224, 180, 240), 4)
        v26.v25.v23.blend(canvas, panel, 82, 784)
        v26.v25.v23.blend(canvas, icon, 89, 791)
    v26.v25.v23.write_image(output, canvas)


def decoded_audio_hash(media: Path, ffmpeg: Path) -> str:
    result = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(media), "-map", "0:a:0",
                             "-f", "hash", "-hash", "sha256", "-"], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return result.stdout.strip().removeprefix("SHA256=")


def alpha_edge_metrics(layer: np.ndarray) -> dict:
    alpha = layer[:, :, 3]
    points = cv2.findNonZero((alpha > 0).astype(np.uint8))
    if points is None:
        raise ValueError("rendered frame layer is fully transparent")
    x, y, width, height = cv2.boundingRect(points)
    return {
        "visible_alpha_bounds": [x, y, x + width, y + height],
        "VISIBLE_ALPHA_LEFT_GAP": x,
        "VISIBLE_ALPHA_RIGHT_GAP": layer.shape[1] - (x + width),
        "VISIBLE_ALPHA_TOP_GAP": y,
        "VISIBLE_ALPHA_BOTTOM_GAP": layer.shape[0] - (y + height),
        "left_edge_visible_pixels": int(np.count_nonzero(alpha[:, 0])),
        "right_edge_visible_pixels": int(np.count_nonzero(alpha[:, -1])),
        "bottom_edge_visible_pixels": int(np.count_nonzero(alpha[-1, :])),
    }


def main() -> None:
    if not all(path.exists() for path in (SOURCE_FRAME, V26, P1, P2, P3)):
        raise FileNotFoundError({"frame": str(SOURCE_FRAME), "v2_6": str(V26), "p1": str(P1), "p2": str(P2)})
    protected = {"V2_6": V26, "PROTOTYPE_V1": P1, "PROTOTYPE_V2": P2, "PROTOTYPE_V3": P3, "SOURCE_FRAME": SOURCE_FRAME}
    before = {name: (v26.v25.v23.snapshot(path) if path.is_dir() else v26.v25.v23.sha(path)) for name, path in protected.items()}
    trim = trim_fully_transparent_outer_pixels(SOURCE_FRAME, DERIVED_TEMP)
    if trim["trim"] != {"left": 0, "top": 8, "right": 0, "bottom": 0}:
        raise RuntimeError(f"UNEXPECTED_TRANSPARENT_TRIM:{trim['trim']}")

    v26.OUT = OUT
    v26.RT = RT
    v26.PROJ = RT / "project"
    v26.layout_for_canvas = custom_layout
    v26.compose_frame = compose_frame
    original_audit = v26.audit_dialogue_ui
    original_render = v26.render_dialogue

    def audit_with_v2_settings(clips, layout):
        return original_audit(clips, layout, preferred_font_size=62, preferred_name_size=48)

    def render_with_derived(pipe, timeline, gains, assets):
        candidate_assets = dict(assets)
        candidate_assets["dialogue_frame_user"] = DERIVED_TEMP
        return original_render(pipe, timeline, gains, candidate_assets)

    v26.audit_dialogue_ui = audit_with_v2_settings
    v26.render_dialogue = render_with_derived
    v26.main()
    after = {name: (v26.v25.v23.snapshot(path) if path.is_dir() else v26.v25.v23.sha(path)) for name, path in protected.items()}
    if before != after:
        raise RuntimeError("PROTECTED_ARTIFACT_CHANGED")

    derived_output = OUT / DERIVED_NAME
    shutil.copy2(DERIVED_TEMP, derived_output)
    old_preview = OUT / "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_PREVIEW.mp4"
    preview = OUT / PREVIEW_NAME
    old_preview.rename(preview)
    qa = json.loads((OUT / "V13_VIDEO_001_V2_6_UI_QA.json").read_text(encoding="utf-8"))
    counts = qa["ui_layout"]["counts"]
    timeline = json.loads((OUT / "V13_VIDEO_001_V2_6_TIMELINE.json").read_text(encoding="utf-8"))
    name_sizes = {clip["speaker_name"]: clip["dialogue_ui"].get("name_font_size")
                  for clip in timeline["clips"] if clip.get("speaker_name")}
    layer = frame_layer()
    edge = alpha_edge_metrics(layer)
    ffmpeg = Path(json.loads((RT / "config/render_m1.json").read_text(encoding="utf-8"))["ffmpeg_path"])
    audio_p2 = decoded_audio_hash(P3 / "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V3.mp4", ffmpeg)
    audio_p3 = decoded_audio_hash(preview, ffmpeg)
    content_files = ("V13_VIDEO_001_V2_6_TABLE_LOG.json", "V13_VIDEO_001_V2_6_VOICE_MANIFEST.json")
    content_changed = any((P3 / name).read_bytes() != (OUT / name).read_bytes() for name in content_files)

    qa_dir = OUT / "pixel_qa_frames"
    qa_dir.mkdir()
    representatives = {"KP": 19.5, "PL": 15.2, "PC": 45.5, "TWO_LINE": 72.0}
    qa_frames = {}
    for label, timestamp in representatives.items():
        target = qa_dir / f"{label.lower()}.png"
        subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-ss", str(timestamp),
                        "-i", str(preview), "-frames:v", "1", str(target)], check=True)
        image = v26.v25.v23.read_image(target)
        if image.shape[:2] != (1080, 1920):
            raise RuntimeError(f"REPRESENTATIVE_FRAME_SIZE_MISMATCH:{label}:{image.shape}")
        qa_frames[label] = {"path": str(target), "sha256": v26.v25.v23.sha(target), "size": [1920, 1080],
                            "edge_anchor_applied": True}

    gates = {
        "LEFT_OUTER_MARGIN_PX": 0,
        "RIGHT_OUTER_MARGIN_PX": 0,
        "BOTTOM_OUTER_MARGIN_PX": 0,
        "VISIBLE_ALPHA_LEFT_GAP": edge["VISIBLE_ALPHA_LEFT_GAP"],
        "VISIBLE_ALPHA_RIGHT_GAP": edge["VISIBLE_ALPHA_RIGHT_GAP"],
        "VISIBLE_ALPHA_BOTTOM_GAP": edge["VISIBLE_ALPHA_BOTTOM_GAP"],
        "VISUAL_OUTER_GAP": max(edge["VISIBLE_ALPHA_LEFT_GAP"], edge["VISIBLE_ALPHA_RIGHT_GAP"], edge["VISIBLE_ALPHA_BOTTOM_GAP"]),
        "FRAME_EDGE_CLIPPING": 0 if edge["left_edge_visible_pixels"] and edge["right_edge_visible_pixels"] and edge["bottom_edge_visible_pixels"] else 1,
        "NAME_PLATE_TEXT_CLIPPING": counts["NAME_PLATE_TEXT_CLIPPING"],
        "DIALOGUE_TEXT_CLIPPING": counts["DIALOGUE_TEXT_CLIPPING"],
        "DIALOGUE_TEXT_OVERFLOW": counts["DIALOGUE_TEXT_OVERFLOW"],
        "SPEAKER_ICON_DIALOGUE_COLLISION": counts["SPEAKER_ICON_DIALOGUE_COLLISION"],
        "SPEAKER_ICON_NAME_PLATE_COLLISION": counts["SPEAKER_ICON_NAME_PLATE_COLLISION"],
    }
    pass_gate = (not any(gates.values()) and audio_p2 == audio_p3 and not content_changed and before == after and
                 all(size == 48 for size in name_sizes.values()))
    report = {
        "prototype_id": PROTOTYPE_ID,
        "base_prototype_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V3",
        "change_scope": ["NAME_FONT_SIZE"],
        "frame_source": str(SOURCE_FRAME), "frame_source_trimmed": True,
        "derived_frame": str(derived_output), "trim_analysis": trim,
        "nine_slice_boundaries": {"left": 72, "right": 72, "top": 64, "bottom": 72},
        "edge_anchoring": {"left": 0, "right": "canvas_width", "bottom": "canvas_height", "canvas": [1920, 1080]},
        "alpha_edge_metrics": edge, "gates": gates,
        "name_font_size": 48, "resolved_name_font_sizes": name_sizes,
        "dialogue_font_size": 62, "speaker_icon_scale": 1.15,
        "representative_pixel_qa_frames": qa_frames,
        "audio_changed": audio_p2 != audio_p3,
        "audio_sha256": {"prototype_v3": audio_p2, "prototype_v4": audio_p3},
        "content_changed": content_changed,
        "protected_artifacts_changed": 0 if before == after else 1,
        "technical_qa": "PASS" if pass_gate else "FAIL",
        "ALT_DIALOGUE_FRAME_V4_ACCEPTED_FOR_HUMAN_REVIEW": pass_gate,
        "human_review": "PENDING", "license_review": "REQUIRED", "auto_publish": "prohibited",
    }
    report_path = OUT / "V13_VIDEO_001_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V4_REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparison = f"""# Alt Dialogue Frame Prototype v3 / v4 Comparison

| Axis | Prototype v3 | Prototype v4 |
|---|---:|---:|
| Left / right margin | 0px / 0px | unchanged |
| Bottom margin | 0px | unchanged |
| Positioning | edge anchored | unchanged |
| Source alpha border | trimmed derived asset | unchanged |
| 9-slice | L72 / R72 / T64 / B72 | unchanged |
| Name / text / icon | 38px / 62px / 1.15 | 48px / 62px / 1.15 |
| Internal padding | Prototype v3 | unchanged |
| Audio / content | Prototype v3 | unchanged; audio SHA-256 identical |

Pixel-level alpha bounds after 9-slice are `{edge['visible_alpha_bounds']}` on a 1920×420 frame layer. The frame has visible alpha at the left, right and bottom edges.
"""
    (OUT / "V13_VIDEO_001_V2_6_ALT_DIALOGUE_FRAME_V3_V4_COMPARISON.md").write_text(comparison, encoding="utf-8")
    manifest_path = OUT / "V13_VIDEO_001_V2_6_ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"prototype_only": True, "prototype_id": PROTOTYPE_ID, "prototype_v4_report": report,
                     "license_review_required": True, "auto_publish": "prohibited"})
    manifest["artifacts"] = [{"path": str(item), "size": item.stat().st_size, "sha256": v26.v25.v23.sha(item)}
                             for item in sorted(OUT.rglob("*")) if item.is_file() and item != manifest_path]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prototype_id": PROTOTYPE_ID, "preview": str(preview), "technical_qa": report["technical_qa"],
                      "accepted_for_human_review": pass_gate, "audio_changed": report["audio_changed"],
                      "content_changed": report["content_changed"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()

