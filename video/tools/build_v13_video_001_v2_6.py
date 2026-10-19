from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
RAW = Path(r"F:\制作物\その3\evaluation-v2\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
BASE = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
VERSIONS = {
    "V1": BASE / "video_001_basement_planks",
    "V2": BASE / "video_001_basement_planks_v2",
    "V2_1": BASE / "video_001_basement_planks_v2_1",
    "V2_2": BASE / "video_001_basement_planks_v2_2",
    "V2_3": BASE / "video_001_basement_planks_v2_3",
    "V2_4": BASE / "video_001_basement_planks_v2_4",
    "V2_5": BASE / "video_001_basement_planks_v2_5",
}
V25 = VERSIONS["V2_5"]
OUT = BASE / "video_001_basement_planks_v2_6"
RT25 = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_5_RENDER_WORKSPACE")
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_6_RENDER_WORKSPACE")
PROJ = RT / "project"
BACKGROUND = Path(r"E:\素材\外部取得素材\backgrounds\basement\AIPICT\aipict_basement_ruins01.png")

spec = importlib.util.spec_from_file_location("v25_builder", VIDEO / "tools/build_v13_video_001_v2_5.py")
v25 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v25)

sys.path.insert(0, str(VIDEO / "src"))
from video_agent.presentation.dialogue_ui import (
    DEFAULT_FRAME_NINE_SLICE,
    DEFAULT_NAME_FONT_SIZE,
    audit_dialogue_ui,
    fit_name_font_size,
    layout_for_canvas,
    wrap_dialogue,
)
from video_agent.rendering.assets import nine_slice_rgba
from video_agent.rendering.subtitles import ass_color, ass_time, build_ass, escape_ass, relative_luminance


def rj(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def wj(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def compose_frame(background: Path, speaker_icon: Path | None, dialogue_frame: Path, output: Path) -> None:
    canvas = v25.cover_background(background)
    ui = layout_for_canvas(canvas.shape[1], canvas.shape[0])
    frame = nine_slice_rgba(
        v25.v23.read_image(dialogue_frame),
        ui.dialogue_frame.width,
        ui.dialogue_frame.height,
        DEFAULT_FRAME_NINE_SLICE,
    )
    v25.v23.blend(canvas, frame, ui.dialogue_frame.x, ui.dialogue_frame.y)
    if speaker_icon:
        icon = v25.v23.fit_rgba(v25.v23.read_image(speaker_icon), 159, 159)
        panel = np.zeros((173, 173, 4), dtype=np.uint8)
        cv2.rectangle(panel, (0, 0), (172, 172), (35, 28, 50, 220), -1)
        cv2.rectangle(panel, (2, 2), (170, 170), (238, 224, 180, 240), 4)
        v25.v23.blend(canvas, panel, 82, 784)
        v25.v23.blend(canvas, icon, 89, 791)
    v25.v23.write_image(output, canvas)


def build_v26_ass(path: Path, clips: list[dict], profiles: dict, base_layout: dict) -> list[str]:
    ui = layout_for_canvas()
    temp = path.with_name("v25_overlay_reference.ass")
    build_ass(temp, clips, profiles, layout=base_layout)
    overlay_lines = [line for line in temp.read_text(encoding="utf-8-sig").splitlines()
                     if line.startswith("Dialogue: 4,")]
    header = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Name,Noto Sans JP,40,&H00FFFFFF,&H00FFFFFF,&H00101010,&H50000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: BodyOuter,Noto Sans JP,62,&HFFFFFFFF,&HFFFFFFFF,&H00101010,&H50000000,-1,0,0,0,100,100,0,0,1,4.5,0,5,0,0,0,1
Style: BodyInner,Noto Sans JP,62,&HFFFFFFFF,&HFFFFFFFF,&H00FFFFFF,&H50000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1
Style: Body,Noto Sans JP,62,&H00FFFFFF,&H00FFFFFF,&H00000000,&H50000000,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1
Style: Dice,Noto Sans JP,54,&H0000FFFF,&H0000FFFF,&H00101010,&H70000000,-1,0,0,0,100,100,0,0,3,3,0,8,80,80,70,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: list[str] = []
    overflow: list[str] = []
    name_x, name_y = ui.name_plate.center
    dialogue_x, dialogue_y = ui.text_safe_area.center
    for clip in clips:
        if not str(clip.get("subtitle_text") or "").strip():
            continue
        start = ass_time(float(clip["start_sec"]))
        end = ass_time(float(clip["start_sec"]) + float(clip["duration_sec"]))
        profile = profiles[clip["subtitle_profile_id"]]
        color = ass_color(profile["text_color"])
        wrapped = wrap_dialogue(escape_ass(clip["subtitle_text"]), ui.text_safe_area)
        if wrapped["overflow"] or wrapped["line_count"] > 2:
            overflow.append(clip["clip_id"])
        clip["dialogue_ui"] = {
            **wrapped,
            "name_font_size": fit_name_font_size(
                str(clip.get("speaker_name") or ""), ui.name_plate, DEFAULT_NAME_FONT_SIZE
            ) if clip.get("speaker_name") else None,
        }
        outlines = profile.get("outlines") or []
        if len(outlines) >= 2:
            inner_width, inner_color = float(outlines[0]["width"]), ass_color(outlines[0]["color"])
            outer_width, outer_color = float(outlines[-1]["width"]), ass_color(outlines[-1]["color"])
        elif outlines:
            inner_width, inner_color = 0.0, "&H00FFFFFF"
            outer_width, outer_color = float(outlines[0]["width"]), ass_color(outlines[0]["color"])
        else:
            inner_width, inner_color, outer_width, outer_color = 0.0, "&H00FFFFFF", 0.0, "&H00000000"
        if clip.get("presentation_mode", "VOICED") == "VOICED" and clip.get("speaker_name"):
            name_size = int((clip.get("dialogue_ui") or {}).get("name_font_size") or DEFAULT_NAME_FONT_SIZE)
            name_outline = ass_color(profile.get("name_outline_color") or
                                     ("#FFFFFF" if relative_luminance(profile["text_color"]) < 0.45 else "#181818"))
            name_outline_width = float(profile.get("name_outline_width", 2.5))
            events.append(f"Dialogue: 3,{start},{end},Name,,0,0,0,,{{\\an5\\pos({name_x},{name_y})\\fs{name_size}\\bord{name_outline_width}\\3c{name_outline}\\1c{color}}}{escape_ass(clip['speaker_name'])}")
        body = "\\N".join(wrapped["lines"])
        position = f"\\an5\\pos({dialogue_x},{dialogue_y})\\fs{wrapped['font_size']}\\fsp0"
        events.append(f"Dialogue: 0,{start},{end},BodyOuter,,0,0,0,,{{{position}\\bord{outer_width}\\3c{outer_color}}}{body}")
        events.append(f"Dialogue: 1,{start},{end},BodyInner,,0,0,0,,{{{position}\\bord{inner_width}\\3c{inner_color}}}{body}")
        events.append(f"Dialogue: 2,{start},{end},Body,,0,0,0,,{{{position}\\bord0\\1c{color}}}{body}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(header + "\n".join(events + overlay_lines) + "\n", encoding="utf-8-sig")
    return overflow


def render_dialogue(pipe, timeline: dict, gains: dict[str, float], assets: dict[str, Path]) -> tuple[Path, list[str]]:
    frames = PROJ / "frames_v26"
    if frames.exists():
        shutil.rmtree(frames)
    segments = frames / "segments"
    segments.mkdir(parents=True)
    icon_by_speaker = {
        "pc_01": assets["portrait_pc01_kitsune_reimu"], "pl_01": assets["portrait_pc01_kitsune_reimu"],
        "pc_02": assets["portrait_pc02_kitsune_marisa"], "pl_02": assets["portrait_pc02_kitsune_marisa"],
        "kp": assets["portrait_kp_sakuya"], "system": None,
    }
    concat = ["ffconcat version 1.0"]
    for clip in timeline["clips"]:
        frame = frames / f"{clip['clip_id']}.png"
        background = BACKGROUND if (clip.get("scene_state") or {}).get("current_location") == "corbitt_basement" else assets["bg_neutral_user"]
        compose_frame(background, icon_by_speaker[clip["speaker_id"]], assets["dialogue_frame_user"], frame)
        padded = frames / f"{clip['clip_id']}_padded.wav"
        if clip["audio_mode"] == "SILENCE":
            subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=48000:cl=mono", "-t", str(clip["duration_sec"]), "-c:a", "pcm_s16le", str(padded)], check=True)
        else:
            gain = gains[clip["presentation_character_id"]]
            subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(PROJ / clip["voice_file"]),
                            "-af", f"volume={gain:.3f}dB,aresample=48000,apad=pad_dur=8", "-t", str(clip["duration_sec"]),
                            "-ac", "1", "-ar", "48000", str(padded)], check=True)
        segment = segments / f"{clip['clip_id']}.mp4"
        subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(frame),
                        "-i", str(padded), "-t", str(clip["duration_sec"]), "-r", "30", "-c:v", pipe.config["video_codec"],
                        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(segment)], check=True)
        concat.append(f"file '{segment.resolve().as_posix()}'")
    listing = segments / "segments.ffconcat"
    listing.write_text("\n".join(concat) + "\n", encoding="utf-8")
    joined = frames / "joined.mp4"
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
                    "-c", "copy", str(joined)], check=True)
    ass = PROJ / "subtitles_v26/subtitles.ass"
    overflow = build_v26_ass(ass, timeline["clips"], pipe.subtitle_profiles, pipe.subtitle_layout)
    base = PROJ / "output/video_001_v2_6_dialogue_bus.mp4"
    base.parent.mkdir(parents=True, exist_ok=True)
    ass_filter = str(ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined),
                    "-vf", f"ass=filename='{ass_filter}'", "-r", "30", "-s", "1920x1080", "-c:v", pipe.config["video_codec"],
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(base)], check=True)
    return base, overflow


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite V2.6 output: {OUT}")
    required = [RAW, *VERSIONS.values(), RT25, BACKGROUND]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(missing)
    protected = {"RAW": RAW, **VERSIONS}
    before = {name: v25.v23.snapshot(path) for name, path in protected.items()}
    OUT.mkdir(parents=True)
    if RT.exists():
        shutil.rmtree(RT)
    shutil.copytree(RT25, RT)
    asset_doc = rj(RT / "project/asset_manifest.json")
    asset_paths = {item["asset_id"]: RT / item["file_path"] for item in asset_doc["assets"]}

    table_source = V25 / "V13_VIDEO_001_V2_5_TABLE_LOG.json"
    shutil.copy2(table_source, OUT / "V13_VIDEO_001_V2_6_TABLE_LOG.json")
    table = rj(table_source)
    script = copy.deepcopy(rj(V25 / "V13_VIDEO_001_V2_5_SCRIPT.json"))
    script.update({"schema_version": "2.6", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6",
                   "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_5"})

    timeline = copy.deepcopy(rj(V25 / "V13_VIDEO_001_V2_5_TIMELINE.json"))
    timeline.update({"schema_version": "2.6", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6",
                     "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_5"})
    ui = layout_for_canvas()
    ui_report = audit_dialogue_ui(timeline["clips"], ui)
    by_table_event = {clip["source_table_event_id"]: clip for clip in timeline["clips"]}
    for line in script["lines"]:
        clip = by_table_event[line["source_table_event_id"]]
        line["dialogue_ui"] = clip["dialogue_ui"]
    wj(OUT / "V13_VIDEO_001_V2_6_SCRIPT.json", script)
    wj(OUT / "V13_VIDEO_001_V2_6_TIMELINE.json", timeline)

    from video_agent.rendering.pipeline import M1Pipeline
    pipe = M1Pipeline(RT, PROJ)
    voice = rj(V25 / "V13_VIDEO_001_V2_5_VOICE_MANIFEST.json")
    gains = {key: value["dialogue_bus_gain_db"] for key, value in voice["dialogue_bus"].items()}
    base, render_overflow = render_dialogue(pipe, timeline, gains, asset_paths)
    preview = OUT / "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_PREVIEW.mp4"
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base),
                    "-i", str(V25 / "V13_VIDEO_001_BASEMENT_PLANKS_V2_5_PREVIEW.mp4"),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "copy", "-t", str(timeline["duration_sec"]),
                    "-movflags", "+faststart", str(preview)], check=True)
    probe = json.loads(subprocess.run([str(pipe.ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(preview)],
                                      capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    duration = float(probe["format"]["duration"])
    def decoded_audio_hash(media: Path) -> str:
        result = subprocess.run([str(pipe.ffmpeg), "-v", "error", "-i", str(media), "-map", "0:a:0",
                                 "-f", "hash", "-hash", "sha256", "-"], capture_output=True,
                                text=True, encoding="utf-8", check=True)
        return result.stdout.strip().removeprefix("SHA256=")
    v25_audio_hash = decoded_audio_hash(V25 / "V13_VIDEO_001_BASEMENT_PLANKS_V2_5_PREVIEW.mp4")
    v26_audio_hash = decoded_audio_hash(preview)
    audio_identical = v25_audio_hash == v26_audio_hash

    shutil.copy2(V25 / "V13_VIDEO_001_V2_5_VOICE_MANIFEST.json", OUT / "V13_VIDEO_001_V2_6_VOICE_MANIFEST.json")
    visual = copy.deepcopy(rj(V25 / "V13_VIDEO_001_V2_5_VISUAL_PLAN.json"))
    visual.update({"schema_version": "2.6", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6",
                   "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_5",
                   "dialogue_ui": ui.as_dict(), "source_yukkuri_registry_values_changed": False,
                   "known_presentation_issue": "地下室離脱付近の演出的な不自然さはV2.6 scope外"})
    wj(OUT / "V13_VIDEO_001_V2_6_VISUAL_PLAN.json", visual)
    wj(OUT / "FIXTURE_DIALOGUE_UI_LAYOUT_001.json", ui_report)

    old_audit = rj(V25 / "V13_VIDEO_001_V2_5_TABLE_LOG_AUDIT.json")
    fixed = {"87_40": "FAILURE", "49_55": "REGULAR_SUCCESS_UNBROKEN", "24_55": "HARD_SUCCESS_BROKEN",
             "S4": "KP_HINT"}
    protected_after = {name: v25.v23.snapshot(path) for name, path in protected.items()}
    source_match = before == protected_after
    table_identical = table_source.read_bytes() == (OUT / "V13_VIDEO_001_V2_6_TABLE_LOG.json").read_bytes()
    voice_identical = (V25 / "V13_VIDEO_001_V2_5_VOICE_MANIFEST.json").read_bytes() == (OUT / "V13_VIDEO_001_V2_6_VOICE_MANIFEST.json").read_bytes()
    ui_zero = not any(ui_report["counts"].values()) and not render_overflow
    content_pass = (old_audit["status"] == "PASS" and old_audit["TABLE_TRACEABILITY"] == 1.0 and
                    old_audit["counts"]["ROLL_MISMATCH"] == 0 and old_audit["counts"]["STATE_CHANGE_MISMATCH"] == 0 and
                    old_audit["counts"]["INVENTED_FACT_COUNT"] == 0 and table_identical)
    technical_pass = ui_zero and preview.exists() and source_match and voice_identical and audio_identical
    accepted = technical_pass and content_pass

    qa_json = {"status": "PASS" if accepted else "FAIL", "source_hash_match": source_match,
               "TABLE_TRACEABILITY": old_audit["TABLE_TRACEABILITY"], "ui_layout": ui_report,
               "render_overflow_ids": render_overflow, "table_log_content_diff": 0 if table_identical else 1,
               "voice_manifest_content_diff": 0 if voice_identical else 1,
               "audio_stream_identity": {"v2_5_sha256": v25_audio_hash, "v2_6_sha256": v26_audio_hash,
                                         "identical": audio_identical}, "fixed_causal_invariants": fixed,
               "TECHNICAL_QA": "PASS" if technical_pass else "FAIL", "CONTENT_QA": "PASS" if content_pass else "FAIL",
               "duration": duration, "VIDEO_V2_6_ACCEPTED_FOR_HUMAN_REVIEW": accepted,
               "KNOWN_PRESENTATION_ISSUE": "地下室離脱付近の不自然さは別途要改善",
               "HUMAN_REVIEW": "PENDING", "AUTO_PUBLISH": "prohibited", "HISTORICAL_ARTIFACTS_CHANGED": 0 if source_match else 1}
    wj(OUT / "V13_VIDEO_001_V2_6_UI_QA.json", qa_json)
    counts = ui_report["counts"]
    qa = f"""# V13_VIDEO_001 V2.6 QA REPORT

- VIDEO_ID: V13_VIDEO_001_BASEMENT_PLANKS_V2_6
- SOURCE_HASH_MATCH: {str(source_match).lower()}
- TABLE_TRACEABILITY: {old_audit['TABLE_TRACEABILITY']:.1f}
- DIALOGUE_FONT_SCALE: 1.20
- SPEAKER_ICON_SCALE: 1.15
- MAX_DIALOGUE_LINES: 2
- NAME_PLATE_ALIGNMENT: {'PASS' if counts['NAME_OUTSIDE_NAME_PLATE'] == 0 else 'FAIL'}
""" + "\n".join(f"- {key}: {value}" for key, value in counts.items()) + f"""
- ROLL_MISMATCH: {old_audit['counts']['ROLL_MISMATCH']}
- STATE_CHANGE_MISMATCH: {old_audit['counts']['STATE_CHANGE_MISMATCH']}
- INVENTED_FACT_COUNT: {old_audit['counts']['INVENTED_FACT_COUNT']}
- TABLE_LOG_CONTENT_DIFF: {0 if table_identical else 1}
- VOICE_MANIFEST_CONTENT_DIFF: {0 if voice_identical else 1}
- V2_5_V2_6_AUDIO_STREAM_IDENTICAL: {str(audio_identical).lower()}
- TECHNICAL_QA: {'PASS' if technical_pass else 'FAIL'}
- CONTENT_QA: {'PASS' if content_pass else 'FAIL'}
- DURATION: {duration:.3f}
- VIDEO_V2_6_ACCEPTED_FOR_HUMAN_REVIEW: {str(accepted).lower()}
- KNOWN_PRESENTATION_ISSUE: 地下室離脱付近の不自然さは別途要改善
- HUMAN_REVIEW: PENDING
- AUTO_PUBLISH: prohibited
- HISTORICAL_ARTIFACTS_CHANGED: {0 if source_match else 1}

## Visual metrics
- name_plate_bounds: {ui.name_plate}
- text_safe_area_bounds: {ui.text_safe_area}
- line_height: {ui.line_height}
- source Yukkuri Registry font_size=100: unchanged

## Preserved causal invariants
- 87 / 40 = FAILURE; broken remains false.
- 49 / 55 = REGULAR_SUCCESS; examined becomes true; broken remains false.
- 24 / 55 = HARD_SUCCESS; broken becomes true.
- S4 is a KP hint and never guarantees success.
"""
    (OUT / "V13_VIDEO_001_V2_6_QA_REPORT.md").write_text(qa, encoding="utf-8")
    comparison = f"""# V13 Video 001 — V2.5 / V2.6 Comparison

V2.5 remains unchanged. V2.6 changes only the dialogue UI rendering layer.

| Axis | V2.5 | V2.6 |
|---|---|---|
| Name readability | Name near the upper frame area | Name centered in the fixed Name Plate |
| Name Plate fit | Informal region | Long names fitted within a fixed 604px plate |
| Subtitle size | 52px renderer profile | 62px presentation render size (+19.2%) |
| Long subtitles | Up to 3 lines | Natural Japanese wrapping, maximum 2 lines |
| Speaker icon | 150px panel / 138px face | 173px panel / 159px face (+15%) |
| Vertical balance | V2.5 baseline | Name, icon and text have separate non-overlapping safe areas |
| Audio / Mix / Assets | V2.5 accepted settings | byte-identical V2.5 audio stream and unchanged selections |

Known issue: 地下室離脱付近の演出的な不自然さはV2.6 scope外です。台詞削除・順序変更・場面改変では隠していません。
"""
    (OUT / "V13_VIDEO_001_V2_5_V2_6_COMPARISON.md").write_text(comparison, encoding="utf-8")
    shutil.copy2(__file__, OUT / "V13_VIDEO_001_V2_6_BUILD_PIPELINE.py")
    artifacts = [{"path": str(item), "size": item.stat().st_size, "sha256": v25.v23.sha(item)}
                 for item in sorted(OUT.iterdir()) if item.is_file() and item.name != "V13_VIDEO_001_V2_6_ARTIFACT_MANIFEST.json"]
    wj(OUT / "V13_VIDEO_001_V2_6_ARTIFACT_MANIFEST.json", {
        "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6", "source_range": "82..233",
        "source_hash_match": source_match, "historical_artifacts_changed": 0 if source_match else 1,
        "dialogue_font_scale": 1.20, "speaker_icon_scale": 1.15, "max_dialogue_lines": 2,
        "ui_layout_qa": ui_report, "table_log_content_diff": 0 if table_identical else 1,
        "voice_manifest_content_diff": 0 if voice_identical else 1, "artifacts": artifacts,
        "audio_stream_identity": {"v2_5_sha256": v25_audio_hash, "v2_6_sha256": v26_audio_hash,
                                  "identical": audio_identical},
        "TECHNICAL_QA": technical_pass, "CONTENT_QA": content_pass,
        "VIDEO_V2_6_ACCEPTED_FOR_HUMAN_REVIEW": accepted, "HUMAN_REVIEW": "PENDING",
        "AUTO_PUBLISH": "prohibited", "KNOWN_PRESENTATION_ISSUE": "地下室離脱付近の不自然さは別途要改善"})
    print(json.dumps({"video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6", "preview": str(preview),
                      "duration": duration, "source_hash_match": source_match, "technical": technical_pass,
                      "content": content_pass, "accepted": accepted}, ensure_ascii=False))


if __name__ == "__main__":
    main()
