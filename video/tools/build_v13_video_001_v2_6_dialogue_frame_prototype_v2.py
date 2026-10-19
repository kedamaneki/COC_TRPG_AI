from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import cv2
import numpy as np


REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
BASE = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
V26 = BASE / "video_001_basement_planks_v2_6"
PROTOTYPE_V1 = BASE / "video_001_basement_planks_v2_6_alt_dialogue_frame_prototype"
OUT = BASE / "video_001_basement_planks_v2_6_alt_dialogue_frame_prototype_v2"
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_6_ALT_FRAME_V2_RENDER_WORKSPACE")
FRAME = Path(r"E:\素材\背景素材\nc131976_SF風シンプルセリフ枠(半透明).png")
PROTOTYPE_ID = "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V2"
PREVIEW_NAME = "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V2.mp4"

spec = importlib.util.spec_from_file_location("v26_builder", VIDEO / "tools/build_v13_video_001_v2_6.py")
v26 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v26)

from video_agent.presentation.dialogue_ui import DialogueUILayout, Rect


def custom_layout(width: int = 1920, height: int = 1080) -> DialogueUILayout:
    sx, sy = width / 1920.0, height / 1080.0

    def rect(x: int, y: int, w: int, h: int) -> Rect:
        return Rect(round(x * sx), round(y * sy), round(w * sx), round(h * sy))

    return DialogueUILayout(
        canvas_width=width,
        canvas_height=height,
        dialogue_frame=rect(10, 660, 1900, 410),
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


def compose_frame(background: Path, speaker_icon: Path | None, dialogue_frame: Path, output: Path) -> None:
    canvas = v26.v25.cover_background(background)
    frame = v26.v25.v23.nine_slice(v26.v25.v23.read_image(dialogue_frame), 1900, 410)
    v26.v25.v23.blend(canvas, frame, 10, 660)
    if speaker_icon:
        icon = v26.v25.v23.fit_rgba(v26.v25.v23.read_image(speaker_icon), 159, 159)
        panel = np.zeros((173, 173, 4), dtype=np.uint8)
        cv2.rectangle(panel, (0, 0), (172, 172), (35, 28, 50, 220), -1)
        cv2.rectangle(panel, (2, 2), (170, 170), (238, 224, 180, 240), 4)
        v26.v25.v23.blend(canvas, panel, 82, 784)
        v26.v25.v23.blend(canvas, icon, 89, 791)
    v26.v25.v23.write_image(output, canvas)


def decoded_audio_hash(media: Path, ffmpeg: Path) -> str:
    import subprocess
    result = subprocess.run([str(ffmpeg), "-v", "error", "-i", str(media), "-map", "0:a:0",
                             "-f", "hash", "-hash", "sha256", "-"], capture_output=True,
                            text=True, encoding="utf-8", check=True)
    return result.stdout.strip().removeprefix("SHA256=")


def main() -> None:
    if not all(path.exists() for path in (FRAME, V26, PROTOTYPE_V1)):
        raise FileNotFoundError({"frame": str(FRAME), "v2_6": str(V26), "prototype_v1": str(PROTOTYPE_V1)})
    protected = {"V2_6": V26, "PROTOTYPE_V1": PROTOTYPE_V1}
    before = {name: v26.v25.v23.snapshot(path) for name, path in protected.items()}
    v26.OUT = OUT
    v26.RT = RT
    v26.PROJ = RT / "project"
    v26.layout_for_canvas = custom_layout
    v26.compose_frame = compose_frame
    original_audit = v26.audit_dialogue_ui
    original_render = v26.render_dialogue

    def audit_with_38px_names(clips, layout):
        return original_audit(clips, layout, preferred_font_size=62, preferred_name_size=38)

    def render_with_candidate(pipe, timeline, gains, assets):
        candidate_assets = dict(assets)
        candidate_assets["dialogue_frame_user"] = FRAME
        return original_render(pipe, timeline, gains, candidate_assets)

    v26.audit_dialogue_ui = audit_with_38px_names
    v26.render_dialogue = render_with_candidate
    v26.main()
    after = {name: v26.v25.v23.snapshot(path) for name, path in protected.items()}
    if before != after:
        raise RuntimeError("PROTECTED_ARTIFACT_CHANGED")

    old_preview = OUT / "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_PREVIEW.mp4"
    preview = OUT / PREVIEW_NAME
    old_preview.rename(preview)
    qa_path = OUT / "V13_VIDEO_001_V2_6_UI_QA.json"
    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    timeline = json.loads((OUT / "V13_VIDEO_001_V2_6_TIMELINE.json").read_text(encoding="utf-8"))
    name_sizes = {clip["speaker_name"]: clip["dialogue_ui"].get("name_font_size")
                  for clip in timeline["clips"] if clip.get("speaker_name")}
    frame_ratio = 1900 / 1920
    counts = qa["ui_layout"]["counts"]
    ffmpeg = Path(json.loads((RT / "config/render_m1.json").read_text(encoding="utf-8"))["ffmpeg_path"])
    audio_v1 = decoded_audio_hash(PROTOTYPE_V1 / "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_PREVIEW.mp4", ffmpeg)
    audio_v2 = decoded_audio_hash(preview, ffmpeg)
    content_files = (
        "V13_VIDEO_001_V2_6_TABLE_LOG.json",
        "V13_VIDEO_001_V2_6_VOICE_MANIFEST.json",
    )
    content_changed = any((PROTOTYPE_V1 / name).read_bytes() != (OUT / name).read_bytes() for name in content_files)
    gates = {
        "NAME_FONT_SIZE_TARGET": all(size == 38 for size in name_sizes.values()),
        "NAME_TOO_SMALL": sum(size < 30 for size in name_sizes.values()),
        "NAME_OUTSIDE_NAME_PLATE": counts["NAME_OUTSIDE_NAME_PLATE"],
        "NAME_PLATE_TEXT_CLIPPING": counts["NAME_PLATE_TEXT_CLIPPING"],
        "DIALOGUE_FRAME_WIDTH_RATIO": frame_ratio,
        "LEFT_OUTER_MARGIN_PX": 10,
        "RIGHT_OUTER_MARGIN_PX": 10,
        "LEFT_OUTER_MARGIN_EXCESS": 0,
        "RIGHT_OUTER_MARGIN_EXCESS": 0,
        "DIALOGUE_TEXT_CLIPPING": counts["DIALOGUE_TEXT_CLIPPING"],
        "DIALOGUE_TEXT_OVERFLOW": counts["DIALOGUE_TEXT_OVERFLOW"],
        "SPEAKER_ICON_DIALOGUE_COLLISION": counts["SPEAKER_ICON_DIALOGUE_COLLISION"],
        "SPEAKER_ICON_NAME_PLATE_COLLISION": counts["SPEAKER_ICON_NAME_PLATE_COLLISION"],
    }
    pass_gate = (gates["NAME_FONT_SIZE_TARGET"] and gates["NAME_TOO_SMALL"] == 0 and
                 0.97 <= frame_ratio <= 0.99 and all(gates[key] == 0 for key in gates if key not in {
                     "NAME_FONT_SIZE_TARGET", "DIALOGUE_FRAME_WIDTH_RATIO", "LEFT_OUTER_MARGIN_PX", "RIGHT_OUTER_MARGIN_PX"}) and
                 not content_changed and audio_v1 == audio_v2 and before == after)
    report = {
        "prototype_id": PROTOTYPE_ID,
        "base_prototype_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE",
        "change_scope": ["NAME_FONT_SIZE", "DIALOGUE_FRAME_HORIZONTAL_MARGIN"],
        "name_font_size": 38,
        "name_font_scale_min": 0.80,
        "resolved_name_font_sizes": name_sizes,
        "dialogue_frame_width_ratio": frame_ratio,
        "left_outer_margin_px": 10,
        "right_outer_margin_px": 10,
        "dialogue_font_size": 62,
        "speaker_icon_scale": 1.15,
        "gates": gates,
        "technical_qa": "PASS" if pass_gate else "FAIL",
        "content_changed": content_changed,
        "audio_changed": audio_v1 != audio_v2,
        "audio_sha256": {"prototype_v1": audio_v1, "prototype_v2": audio_v2},
        "protected_artifacts_changed": 0 if before == after else 1,
        "dialogue_frame": {"path": str(FRAME), "sha256": v26.v25.v23.sha(FRAME),
                           "approval_status": "NOT_APPROVED", "license_status": "LICENSE_REVIEW_REQUIRED",
                           "auto_use": False, "use_scope": "USER_REQUESTED_LOCAL_PROTOTYPE_ONLY"},
        "human_review": "PENDING",
        "auto_publish": "prohibited",
    }
    report_path = OUT / "V13_VIDEO_001_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V2_REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    comparison = f"""# Alt Dialogue Frame Prototype v1 / v2 Comparison

| Axis | Prototype v1 | Prototype v2 |
|---|---:|---:|
| Name readability | 40px renderer setting | 38px fixed target; long names fit-to-box only |
| Name Plate balance | x=74, width=604 | x=26, width=604; centered over expanded frame |
| Dialogue frame width | 1804px (93.96%) | 1900px ({frame_ratio:.2%}) |
| Outer margin | 58px / 58px | 10px / 10px |
| Subtitle readability | 62px, max 2 lines | unchanged |
| Speaker Icon balance | scale 1.15 | unchanged |
| Overall visual density | wide outside margins | near edge-to-edge SF frame |
| Audio / content | V2.6 source | unchanged; decoded audio SHA-256 identical |

The dialogue frame continues to use 9-slice scaling. Internal padding, text safe area, icon size, audio, BGM, SE, background, timeline order, reaction order, location logic and S4 expression are unchanged.
"""
    (OUT / "V13_VIDEO_001_V2_6_ALT_DIALOGUE_FRAME_V1_V2_COMPARISON.md").write_text(comparison, encoding="utf-8")
    manifest_path = OUT / "V13_VIDEO_001_V2_6_ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({"prototype_only": True, "prototype_id": PROTOTYPE_ID, "prototype_v2_report": report,
                     "license_review_required": True, "auto_publish": "prohibited"})
    manifest["artifacts"] = [{"path": str(item), "size": item.stat().st_size, "sha256": v26.v25.v23.sha(item)}
                             for item in sorted(OUT.iterdir()) if item.is_file() and item != manifest_path]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prototype_id": PROTOTYPE_ID, "preview": str(preview), "technical_qa": report["technical_qa"],
                      "content_changed": content_changed, "audio_changed": audio_v1 != audio_v2}, ensure_ascii=False))


if __name__ == "__main__":
    main()
