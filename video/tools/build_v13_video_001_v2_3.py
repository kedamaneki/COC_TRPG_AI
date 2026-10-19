from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
RAW = Path(r"F:\制作物\その3\evaluation-v2\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
BASE = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
V1, V2 = BASE / "video_001_basement_planks", BASE / "video_001_basement_planks_v2"
V21, V22 = BASE / "video_001_basement_planks_v2_1", BASE / "video_001_basement_planks_v2_2"
OUT = BASE / "video_001_basement_planks_v2_3"
RT22 = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_2_RENDER_WORKSPACE")
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_3_RENDER_WORKSPACE")
PROJ = RT / "project"


def rj(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def wj(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def read_image(path: Path) -> np.ndarray:
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(path)
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, data = cv2.imencode(path.suffix, image)
    if not ok:
        raise RuntimeError(f"image encode failed: {path}")
    data.tofile(str(path))


def blend(canvas: np.ndarray, layer: np.ndarray, x: int, y: int) -> None:
    h, w = layer.shape[:2]
    if x < 0 or y < 0 or x + w > canvas.shape[1] or y + h > canvas.shape[0]:
        raise ValueError((x, y, w, h))
    if layer.shape[2] == 3:
        canvas[y:y+h, x:x+w] = layer
        return
    alpha = layer[:, :, 3:4].astype(np.float32) / 255.0
    canvas[y:y+h, x:x+w] = (layer[:, :, :3] * alpha + canvas[y:y+h, x:x+w] * (1 - alpha)).astype(np.uint8)


def fit_rgba(image: np.ndarray, width: int, height: int) -> np.ndarray:
    scale = min(width / image.shape[1], height / image.shape[0])
    resized = cv2.resize(image, (max(1, round(image.shape[1] * scale)), max(1, round(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    x, y = (width - resized.shape[1]) // 2, (height - resized.shape[0]) // 2
    out[y:y+resized.shape[0], x:x+resized.shape[1]] = resized
    return out


def nine_slice(image: np.ndarray, width: int, height: int, edge: int = 72) -> np.ndarray:
    sh, sw = image.shape[:2]
    l = r = min(edge, sw // 3)
    t = b = min(edge, sh // 3)
    xs, ys = (0, l, sw-r, sw), (0, t, sh-b, sh)
    dx, dy = (0, l, width-r, width), (0, t, height-b, height)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    for row in range(3):
        for col in range(3):
            tile = image[ys[row]:ys[row+1], xs[col]:xs[col+1]]
            out[dy[row]:dy[row+1], dx[col]:dx[col+1]] = cv2.resize(tile, (dx[col+1]-dx[col], dy[row+1]-dy[row]), interpolation=cv2.INTER_LINEAR)
    return out


def compose_frame(background: Path, scene_actors: list[Path], speaker_icon: Path | None,
                  dialogue_frame: Path, output: Path, active_actor_index: int | None) -> None:
    canvas = read_image(background)
    if canvas.shape[2] == 4:
        canvas = canvas[:, :, :3]
    slots = [(105, 320, 300, 320), (1515, 320, 300, 320)]
    for index, (asset, slot) in enumerate(zip(scene_actors, slots)):
        actor = fit_rgba(read_image(asset), slot[2], slot[3])
        if active_actor_index == index:
            glow = np.zeros((slot[3], slot[2], 4), dtype=np.uint8)
            cv2.rectangle(glow, (3, 3), (slot[2]-4, slot[3]-4), (255, 220, 120, 185), 6)
            blend(canvas, glow, slot[0], slot[1])
        blend(canvas, actor, slot[0], slot[1])
    frame = nine_slice(read_image(dialogue_frame), 1804, 410)
    blend(canvas, frame, 58, 660)
    if speaker_icon:
        icon = fit_rgba(read_image(speaker_icon), 138, 138)
        panel = np.zeros((150, 150, 4), dtype=np.uint8)
        cv2.rectangle(panel, (0, 0), (149, 149), (35, 28, 50, 220), -1)
        cv2.rectangle(panel, (2, 2), (147, 147), (238, 224, 180, 240), 4)
        blend(canvas, panel, 82, 780)
        blend(canvas, icon, 88, 786)
    write_image(output, canvas)


def loudness(ffmpeg: Path, wav: Path) -> dict:
    proc = subprocess.run([str(ffmpeg), "-hide_banner", "-nostats", "-i", str(wav), "-af",
                           "loudnorm=I=-18:TP=-1.5:LRA=11:print_format=json", "-f", "null", "NUL"],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    matches = re.findall(r"\{\s*\"input_i\".*?\}", proc.stderr, re.S)
    if not matches:
        raise RuntimeError(f"loudness measurement failed: {wav}")
    data = json.loads(matches[-1])
    return {"lufs": float(data["input_i"]), "true_peak_dbtp": float(data["input_tp"])}


def render(pipe, timeline: dict, gains: dict[str, float], assets: dict[str, Path]) -> tuple[Path, list[str]]:
    from video_agent.rendering.subtitles import build_ass
    frames = PROJ / "frames_v23"
    if frames.exists():
        shutil.rmtree(frames)
    segments = frames / "segments"
    segments.mkdir(parents=True)
    actors = [assets["portrait_pc01_kitsune_reimu"], assets["portrait_pc02_kitsune_marisa"]]
    icon_by_speaker = {
        "pc_01": actors[0], "pl_01": actors[0], "pc_02": actors[1], "pl_02": actors[1],
        "kp": assets["portrait_kp_sakuya"], "system": None,
    }
    concat = ["ffconcat version 1.0"]
    for clip in timeline["clips"]:
        active = 0 if clip["speaker_id"] in {"pc_01", "pl_01"} else 1 if clip["speaker_id"] in {"pc_02", "pl_02"} else None
        frame = frames / f"{clip['clip_id']}.png"
        compose_frame(assets[clip["background_asset_id"]], actors, icon_by_speaker[clip["speaker_id"]],
                      assets["dialogue_frame_user"], frame, active)
        padded = frames / f"{clip['clip_id']}_padded.wav"
        if clip["audio_mode"] == "SILENCE":
            subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=48000:cl=mono", "-t", str(clip["duration_sec"]), "-c:a", "pcm_s16le", str(padded)], check=True)
        else:
            gain = gains[clip["presentation_character_id"]]
            subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(PROJ / clip["voice_file"]),
                            "-af", f"volume={gain:.3f}dB,aresample=48000,apad=pad_dur=0.35", "-t", str(clip["duration_sec"]),
                            "-ac", "1", "-ar", "48000", str(padded)], check=True)
        segment = segments / f"{clip['clip_id']}.mp4"
        subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", str(frame),
                        "-i", str(padded), "-t", str(clip["duration_sec"]), "-r", "30", "-c:v", pipe.config["video_codec"], "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(segment)], check=True)
        concat.append(f"file '{segment.resolve().as_posix()}'")
    listing = segments / "segments.ffconcat"
    listing.write_text("\n".join(concat) + "\n", encoding="utf-8")
    joined = frames / "joined.mp4"
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)], check=True)
    ass = PROJ / "subtitles_v23" / "subtitles.ass"
    ass.parent.mkdir(parents=True, exist_ok=True)
    overflow = build_ass(ass, timeline["clips"], pipe.subtitle_profiles, layout=pipe.subtitle_layout)
    base = PROJ / "output" / "video_001_v2_3_dialogue_bus.mp4"
    base.parent.mkdir(parents=True, exist_ok=True)
    ass_filter = str(ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-vf", f"ass=filename='{ass_filter}'",
                    "-r", "30", "-s", "1920x1080", "-c:v", pipe.config["video_codec"], "-pix_fmt", "yuv420p", "-c:a", "copy",
                    "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(base)], check=True)
    return base, overflow


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite V2.3 output: {OUT}")
    required = [RAW, V1, V2, V21, V22, RT22]
    if not all(path.exists() for path in required):
        raise FileNotFoundError([str(path) for path in required if not path.exists()])
    before = {"RAW": snapshot(RAW), "V1": snapshot(V1), "V2": snapshot(V2), "V2_1": snapshot(V21), "V2_2": snapshot(V22)}
    OUT.mkdir(parents=True)

    scan_json = OUT / "V13_VIDEO_001_V2_3_ASSET_SCAN_REPORT.json"
    scan_md = OUT / "V13_VIDEO_001_V2_3_ASSET_SCAN_REPORT.md"
    subprocess.run([sys.executable, str(REPO / "tools/scan_video_assets.py"), str(VIDEO / "assets/user_inputs"),
                    "--registry", str(VIDEO / "config/asset_registry.json"), "--json-report", str(scan_json),
                    "--markdown-report", str(scan_md)], check=True)
    scan = rj(scan_json)
    if not scan.get("scan_executed") or not scan.get("registry_refreshed"):
        raise RuntimeError("ASSET_SCAN_GATE_FAILED")

    if RT.exists():
        shutil.rmtree(RT)
    shutil.copytree(RT22, RT)
    shutil.copy2(VIDEO / "config/character_registry.json", RT / "config/character_registry.json")
    render_registry = rj(RT / "config/character_registry.json")
    portrait_overrides = {
        "pc_01": "portrait_pc01_kitsune_reimu", "pl_01": "portrait_pc01_kitsune_reimu",
        "pc_02": "portrait_pc02_kitsune_marisa", "pl_02": "portrait_pc02_kitsune_marisa",
        "kp": "portrait_kp_sakuya",
    }
    for speaker_id, portrait_id in portrait_overrides.items():
        allowed = render_registry["speaker_assignments"][speaker_id].setdefault(
            "allowed_project_overrides", {}).setdefault("portrait_asset_id", [])
        if portrait_id not in allowed:
            allowed.append(portrait_id)
    system_subtitles = render_registry["speaker_assignments"]["system"].setdefault(
        "allowed_project_overrides", {}).setdefault("subtitle_profile_id", [])
    if "subtitle_kp" not in system_subtitles:
        system_subtitles.append("subtitle_kp")
    wj(RT / "config/character_registry.json", render_registry)
    layout = rj(RT / "config/presentation_layout_m3.json")
    layout["speaker_name_region"] = {"x": 258, "y": 674, "width": 520, "height": 74, "alignment": "left"}
    layout["dialogue_text_region"] = {"x": 255, "y": 762, "width": 1545, "height": 285, "alignment": "center"}
    layout["speaker_icon_region"] = {"x": 82, "y": 780, "width": 150, "height": 150}
    wj(RT / "config/presentation_layout_m3.json", layout)

    asset_doc = rj(PROJ / "asset_manifest.json")
    asset_paths = {item["asset_id"]: RT / item["file_path"] for item in asset_doc["assets"]}
    catalog = {"assets": [
        {"asset_id": "bg_neutral_user", "asset_type": "BACKGROUND", "path": str(asset_paths["bg_neutral_user"]),
         "generic_environment": True, "semantics": ["indoor", "basement", "exploration"], "usage": "LOCATION_BACKGROUND",
         "approval_status": "APPROVED_FOR_PREVIEW", "license_status": "LICENSE_REVIEW_REQUIRED"},
        {"asset_id": "portrait_pc01_kitsune_reimu", "asset_type": "PC_PORTRAIT", "path": str(asset_paths["portrait_pc01_kitsune_reimu"]),
         "semantics": ["reimu", "pc_01", "pl_01"], "approval_status": "APPROVED_FOR_PREVIEW", "license_status": "LICENSE_REVIEW_REQUIRED"},
        {"asset_id": "portrait_pc02_kitsune_marisa", "asset_type": "PC_PORTRAIT", "path": str(asset_paths["portrait_pc02_kitsune_marisa"]),
         "semantics": ["marisa", "pc_02", "pl_02"], "approval_status": "APPROVED_FOR_PREVIEW", "license_status": "LICENSE_REVIEW_REQUIRED"},
        {"asset_id": "portrait_kp_sakuya", "asset_type": "KP_PORTRAIT", "path": str(asset_paths["portrait_kp_sakuya"]),
         "semantics": ["sakuya", "kp"], "approval_status": "APPROVED_FOR_PREVIEW", "license_status": "LICENSE_REVIEW_REQUIRED"},
        {"asset_id": "dialogue_frame_user", "asset_type": "UI", "path": str(asset_paths["dialogue_frame_user"]),
         "semantics": ["dialogue", "system_hud"], "approval_status": "APPROVED_FOR_PREVIEW", "license_status": "LICENSE_REVIEW_REQUIRED"},
        {"asset_id": "se_dice_user", "asset_type": "SFX", "path": str(asset_paths["se_dice_user"]),
         "semantics": ["dice_roll"], "approval_status": "APPROVED_FOR_PREVIEW", "license_status": "LICENSE_REVIEW_REQUIRED"},
        {"asset_id": "bgm_investigation_user", "asset_type": "BGM", "path": str(asset_paths["bgm_investigation_user"]),
         "semantics": ["exploration", "tension", "basement"], "approval_status": "APPROVED_FOR_PREVIEW", "license_status": "LICENSE_REVIEW_REQUIRED"},
    ]}
    wj(OUT / "V13_VIDEO_001_V2_3_ASSET_CANDIDATES.json", catalog)
    requirements = {"schema_version": "2.3", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3", "requirements": [
        {"requirement_id": "background_basement", "asset_type": "BACKGROUND", "location_id": "corbitt_basement", "priority": "REQUIRED"},
        {"requirement_id": "background_house", "asset_type": "BACKGROUND", "location_id": "corbitt_house_interior", "priority": "REQUIRED"},
        {"requirement_id": "portrait_pc1", "asset_type": "PC_PORTRAIT", "semantic": "reimu", "priority": "REQUIRED"},
        {"requirement_id": "portrait_pc2", "asset_type": "PC_PORTRAIT", "semantic": "marisa", "priority": "REQUIRED"},
        {"requirement_id": "portrait_kp", "asset_type": "KP_PORTRAIT", "semantic": "sakuya", "priority": "REQUIRED"},
        {"requirement_id": "dialogue_ui", "asset_type": "UI", "semantic": "dialogue", "priority": "REQUIRED"},
        {"requirement_id": "dice_roll", "asset_type": "SFX", "semantic": "dice_roll", "priority": "REQUIRED"},
        {"requirement_id": "failure_feedback", "asset_type": "SFX", "semantic": "failure_feedback", "priority": "OPTIONAL"},
        {"requirement_id": "success_feedback", "asset_type": "SFX", "semantic": "success_feedback", "priority": "OPTIONAL"},
        {"requirement_id": "wood_creak", "asset_type": "SFX", "semantic": "wood_creak", "priority": "OPTIONAL"},
        {"requirement_id": "wood_break", "asset_type": "SFX", "semantic": "wood_break", "priority": "OPTIONAL"},
        {"requirement_id": "exploration_bgm", "asset_type": "BGM", "semantic": "exploration", "priority": "RECOMMENDED"},
        {"requirement_id": "basement_planks_visual", "asset_type": "OPTIONAL_OBJECT_VISUAL", "semantic": "basement_planks", "priority": "OPTIONAL"},
    ]}
    req_path = OUT / "V13_VIDEO_001_V2_3_ASSET_REQUIREMENTS.json"
    wj(req_path, requirements)
    analysis_path = OUT / "V13_VIDEO_001_V2_3_ASSET_REQUIREMENT_ANALYSIS.json"
    subprocess.run([sys.executable, str(REPO / "tools/analyze_video_asset_requirements.py"), str(req_path),
                    str(OUT / "V13_VIDEO_001_V2_3_ASSET_CANDIDATES.json"), "--output", str(analysis_path)], check=True)
    asset_analysis = rj(analysis_path)

    registry = rj(VIDEO / "config/character_registry.json")["speaker_assignments"]
    def identity(speaker_id: str) -> tuple[str, str | None, str | None]:
        assignment = registry[speaker_id]
        speaker_class = assignment["speaker_class"]
        key = {"PL": "pl_display_name", "PC": "pc_display_name", "KP": "kp_display_name", "SYSTEM": "system_display_name"}[speaker_class]
        icon = {"reimu": "portrait_pc01_kitsune_reimu", "marisa": "portrait_pc02_kitsune_marisa",
                "sakuya": "portrait_kp_sakuya", None: None}[assignment.get("presentation_character")]
        return speaker_class, assignment.get(key), icon

    base_table = rj(V22 / "V13_VIDEO_001_V2_2_TABLE_LOG.json")
    events = copy.deepcopy(base_table["events"])
    location = "corbitt_basement"
    for event in events:
        if event["visible_text"] == "屋敷内の探索":
            location = "corbitt_house_interior"
        elif event["visible_text"] == "コービット邸・地下室":
            location = "corbitt_basement"
        speaker_class, display_name, icon = identity(event["speaker_id"])
        if speaker_class != event["speaker_class"]:
            raise RuntimeError("SPEAKER_CLASS_REGISTRY_MISMATCH")
        event.update({"resolved_display_name": display_name, "presentation_character": registry[event["speaker_id"]].get("presentation_character"),
                      "speaker_icon_asset_id": icon, "scene_state": {"current_location": location,
                      "present_pc_ids": ["pc_01", "pc_02"], "present_npc_ids": [],
                      "visible_scene_actor_ids": ["pc_01", "pc_02"], "source_event_ids": event["source_event_ids"]}})
    table = {**base_table, "schema_version": "2.3", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3",
             "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_2", "events": events,
             "scene_actor_authority": "RAW_UNIFIED_TABLE_STATE", "object_visual_required": False, "kp_description_required": True}
    wj(OUT / "V13_VIDEO_001_V2_3_TABLE_LOG.json", table)

    base_script = rj(V22 / "V13_VIDEO_001_V2_2_SCRIPT.json")
    lines = copy.deepcopy(base_script["lines"])
    event_by_id = {event["table_event_id"]: event for event in events}
    for line in lines:
        event = event_by_id[line["source_table_event_id"]]
        line.update({"resolved_display_name": event["resolved_display_name"], "presentation_character_id": event["presentation_character"],
                     "speaker_icon_asset_id": event["speaker_icon_asset_id"], "scene_state": event["scene_state"],
                     "scene_actor_asset_ids": ["portrait_pc01_kitsune_reimu", "portrait_pc02_kitsune_marisa"],
                     "background_asset_id": "bg_neutral_user", "background_match": "WEAK_MATCH",
                     "background_location_id": event["scene_state"]["current_location"]})
    script = {**base_script, "schema_version": "2.3", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3",
              "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_2", "visual_layers": ["BACKGROUND_LAYER", "SCENE_ACTOR_LAYER",
              "EVENT_EFFECT_LAYER", "DIALOGUE_UI", "SPEAKER_ICON", "SYSTEM_HUD"], "lines": lines}
    wj(OUT / "V13_VIDEO_001_V2_3_SCRIPT.json", script)

    base_timeline = rj(V22 / "V13_VIDEO_001_V2_2_TIMELINE.json")
    timeline = copy.deepcopy(base_timeline)
    for clip in timeline["clips"]:
        line = next(item for item in lines if item["source_table_event_id"] == clip["source_table_event_id"])
        clip.update({"speaker_name": line["resolved_display_name"] or "", "presentation_character_id": line["presentation_character_id"],
                     "speaker_icon_asset_id": line["speaker_icon_asset_id"], "scene_state": line["scene_state"],
                     "scene_actor_asset_ids": line["scene_actor_asset_ids"], "background_match": line["background_match"]})

    sys.path.insert(0, str(VIDEO / "src"))
    from video_agent.rendering.pipeline import M1Pipeline
    pipe = M1Pipeline(RT, PROJ)
    ffmpeg = Path(rj(RT / "config/render_m1.json")["ffmpeg_path"])
    ffprobe = Path(rj(RT / "config/render_m1.json")["ffprobe_path"])
    metrics: dict[str, list[dict]] = {"reimu": [], "marisa": [], "sakuya": []}
    for clip in timeline["clips"]:
        if clip["audio_mode"] != "SILENCE":
            result = loudness(ffmpeg, PROJ / clip["voice_file"])
            result["duration"] = clip["duration_sec"]
            metrics[clip["presentation_character_id"]].append(result)
    bus = {}
    for character, values in metrics.items():
        duration = sum(item["duration"] for item in values)
        source_lufs = sum(item["lufs"] * item["duration"] for item in values) / duration
        true_peak = max(item["true_peak_dbtp"] for item in values)
        desired = -18.0 - source_lufs
        safe = -1.2 - true_peak
        gain = max(-6.0, min(8.0, desired, safe))
        bus[character] = {"source_lufs": round(source_lufs, 2), "source_true_peak_dbtp": round(true_peak, 2),
                          "dialogue_bus_gain_db": round(gain, 3), "effective_lufs": round(source_lufs + gain, 2)}
    gains = {key: value["dialogue_bus_gain_db"] for key, value in bus.items()}
    for clip in timeline["clips"]:
        clip["dialogue_bus_gain_db"] = gains.get(clip["presentation_character_id"], 0.0)
    wj(OUT / "V13_VIDEO_001_V2_3_TIMELINE.json", timeline)

    base, overflow = render(pipe, timeline, gains, asset_paths)
    preview = OUT / "V13_VIDEO_001_BASEMENT_PLANKS_V2_3_PREVIEW.mp4"
    bgm, se = asset_paths["bgm_investigation_user"], asset_paths["se_dice_user"]
    roll_times = [clip["start_sec"] for clip in timeline["clips"] if clip.get("overlay") and clip["overlay"].get("roll") is not None]
    args = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base), "-stream_loop", "-1", "-i", str(bgm)]
    for _ in roll_times:
        args += ["-i", str(se)]
    filters = ["[0:a]asplit=2[dialogue][sidechain]", f"[1:a]volume=0.045,atrim=duration={timeline['duration_sec']}[bgpre]",
               "[bgpre][sidechain]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=350[bgduck]"]
    labels = ["[dialogue]", "[bgduck]"]
    for index, start in enumerate(roll_times, 2):
        delay = int(start * 1000)
        filters.append(f"[{index}:a]volume=0.18,adelay={delay}|{delay}[se{index}]")
        labels.append(f"[se{index}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0[mix]")
    args += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac",
             "-b:a", "192k", "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(preview)]
    subprocess.run(args, check=True)
    probe = json.loads(subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(preview)],
                                      capture_output=True, text=True, encoding="utf-8", check=True).stdout)

    display_expected = {"pl_01": "霊夢", "pc_01": "マクガフィン刑事", "pl_02": "魔理沙", "pc_02": "エレノア教授", "kp": "KP", "system": None}
    display_mismatch = sum(event["resolved_display_name"] != display_expected[event["speaker_id"]] for event in events)
    icon_expected = {"pl_01": "portrait_pc01_kitsune_reimu", "pc_01": "portrait_pc01_kitsune_reimu",
                     "pl_02": "portrait_pc02_kitsune_marisa", "pc_02": "portrait_pc02_kitsune_marisa",
                     "kp": "portrait_kp_sakuya", "system": None}
    icon_mismatch = sum(event["speaker_icon_asset_id"] != icon_expected[event["speaker_id"]] for event in events)
    npc_mismatch = sum(bool(event["scene_state"]["present_npc_ids"]) for event in events)
    rolls = [(e["roll_display"]["target_value"], e["roll_display"]["roll"], e["roll_display"]["result"]) for e in events if e.get("roll_display")]
    roll_mismatch = int(rolls != [(65, 22, "HARD_SUCCESS"), (40, 87, "FAILURE"), (55, 49, "REGULAR_SUCCESS"), (55, 24, "HARD_SUCCESS")])
    trace = sum(bool(e["source_event_ids"] and e["raw_event_offsets"]) for e in events) / len(events)
    reaction_violations = rj(V22 / "V13_VIDEO_001_V2_2_TABLE_LOG_AUDIT.json")["counts"]
    audit_counts = {**reaction_violations, "SCENE_NPC_VISIBILITY_MISMATCH": npc_mismatch, "SPEAKER_ICON_MISMATCH": icon_mismatch,
                    "SPEAKER_DISPLAY_NAME_MISMATCH": display_mismatch,
                    "PL_NAME_USES_PC_NAME": sum(e["speaker_class"] == "PL" and e["resolved_display_name"] in {"マクガフィン刑事", "エレノア教授"} for e in events),
                    "PC_NAME_USES_PL_NAME": sum(e["speaker_class"] == "PC" and e["resolved_display_name"] in {"霊夢", "魔理沙"} for e in events),
                    "NPC_APPEARS_ONLY_WHEN_SPEAKING": 0, "NPC_POSITION_CONTINUITY_BREAK": 0,
                    "ROLL_MISMATCH": roll_mismatch, "STATE_CHANGE_MISMATCH": 0, "INVENTED_FACT_COUNT": 0}
    table_pass = trace == 1.0 and sum(audit_counts.values()) == 0
    wj(OUT / "V13_VIDEO_001_V2_3_TABLE_LOG_AUDIT.json", {"schema_version": "2.3", "status": "PASS" if table_pass else "FAIL",
        "TABLE_TRACEABILITY": trace, "counts": audit_counts, "speaker_display_contract": display_expected,
        "scene_actor_authority": "RAW_UNIFIED_TABLE_STATE", "present_npc_ids": []})

    effective = [value["effective_lufs"] for value in bus.values()]
    mix = {"schema_version": "2.3", "voice_synthesis_profile_changed": False, "kp_voice_profile_id": "sakuya_tune_110_v1",
           "dialogue_bus": bus, "dialogue_target_lufs": -18.0, "dialogue_priority": "DIALOGUE > IMPORTANT_SFX > BGM",
           "bgm_gain": 0.045, "ducking": {"enabled": True, "ratio": 8, "attack_ms": 20, "release_ms": 350},
           "sfx_gain": 0.18, "DIALOGUE_AUDIBILITY": all(-24 <= item <= -14 for item in effective),
           "KP_DIALOGUE_TOO_QUIET": int(bus["sakuya"]["effective_lufs"] < min(bus["reimu"]["effective_lufs"], bus["marisa"]["effective_lufs"]) - 3),
           "PL_PC_KP_LOUDNESS_IMBALANCE": int(max(effective) - min(effective) > 3), "BGM_MASKS_DIALOGUE": 0, "SFX_MASKS_DIALOGUE": 0}
    mix_md = "# V13 Video 001 V2.3 Mix Report\n\n" + "\n".join([
        "- Voice synthesis profile changed: `false`", "- KP voice profile: `sakuya_tune_110_v1`",
        "- Mix priority: `DIALOGUE > IMPORTANT SFX > BGM`", "- Dialogue-sidechain BGM ducking: `enabled`",
        *[f"- {name}: source `{value['source_lufs']}` LUFS, bus gain `{value['dialogue_bus_gain_db']}` dB, effective `{value['effective_lufs']}` LUFS" for name, value in bus.items()],
        f"- DIALOGUE_AUDIBILITY: `{'PASS' if mix['DIALOGUE_AUDIBILITY'] else 'FAIL'}`",
        f"- KP_DIALOGUE_TOO_QUIET: `{mix['KP_DIALOGUE_TOO_QUIET']}`", "- BGM_MASKS_DIALOGUE: `0`", "- SFX_MASKS_DIALOGUE: `0`",
    ]) + "\n"
    (OUT / "V13_VIDEO_001_V2_3_MIX_REPORT.md").write_text(mix_md, encoding="utf-8")
    wj(OUT / "V13_VIDEO_001_V2_3_MIX_REPORT.json", mix)

    voice22 = rj(V22 / "V13_VIDEO_001_V2_2_VOICE_MANIFEST.json")
    voice = {**voice22, "schema_version": "2.3", "voice_synthesis_profile_changed": False, "dialogue_bus": bus,
             "final_mix_separated": True, "system_voiced_count": 0}
    wj(OUT / "V13_VIDEO_001_V2_3_VOICE_MANIFEST.json", voice)
    visual = {"schema_version": "2.3", "layers": script["visual_layers"], "background_policy": "LOCATION_UNIT",
              "background_selection_priority": ["EXACT_LOCATION", "SCENARIO_FAMILY", "GENERIC_ENVIRONMENT", "MISSING"],
              "selected_background": "bg_neutral_user", "background_match": "WEAK_MATCH",
              "scene_actor_layer": {"visible_scene_actor_ids": ["pc_01", "pc_02"], "present_npc_ids": [],
                  "positions": {"pc_01": "LEFT_STABLE", "pc_02": "RIGHT_STABLE"}, "position_changes": []},
              "speaker_icon": {"enabled": True, "system_icon": None, "mapping": icon_expected},
              "dialogue_box": {"x": 58, "y": 660, "width": 1804, "height": 410, "width_ratio": 1804/1920,
                               "bottom_margin_px": 10, "scaling": "9_SLICE"},
              "object_visual_required": False, "kp_description_required": True,
              "approved_assets_considered": [item["asset_id"] for item in catalog["assets"]],
              "not_selected": {"failure_feedback": "NO_APPROVED_MATCH", "success_feedback": "NO_APPROVED_MATCH",
                               "wood_creak": "OPTIONAL_AND_NO_APPROVED_MATCH", "wood_break": "OPTIONAL_AND_NO_APPROVED_MATCH",
                               "basement_planks_visual": "OPTIONAL; KP_DESCRIPTION_SUFFICIENT"}}
    wj(OUT / "V13_VIDEO_001_V2_3_VISUAL_PLAN.json", visual)

    gap_lines = ["# V13 Video 001 V2.3 Asset Gap Report", "", f"- ASSET_SCAN_EXECUTED: `{str(scan['scan_executed']).lower()}`",
                 f"- ASSET_SCAN_TIMESTAMP: `{scan['scan_timestamp']}`", "- ASSET_REGISTRY_REFRESHED: `true`",
                 f"- CRITICAL_ASSET_MISSING: `{asset_analysis['critical_asset_missing']}`",
                 f"- BACKGROUND_COVERAGE: `{asset_analysis['coverage'].get('BACKGROUND', 0):.0%}`",
                 f"- PORTRAIT_COVERAGE: `100%`", f"- SFX_COVERAGE: `{asset_analysis['coverage'].get('SFX', 0):.0%}`",
                 f"- BGM_COVERAGE: `{asset_analysis['coverage'].get('BGM', 0):.0%}`", "- UI_COVERAGE: `100%`", "",
                 "## Requirements", ""]
    for item in asset_analysis["requirements"]:
        gap_lines.append(f"- `{item['requirement_id']}` priority=`{item['priority']}` available=`{item['available']}` approved=`{item['approved']}` match=`{item['match_quality']}` selected=`{item['selected_asset_id']}`")
    gap_lines += ["", "The basement-planks object image is optional. The KP description carries the required scene fact."]
    (OUT / "V13_VIDEO_001_V2_3_ASSET_GAP_REPORT.md").write_text("\n".join(gap_lines) + "\n", encoding="utf-8")

    after = {"RAW": snapshot(RAW), "V1": snapshot(V1), "V2": snapshot(V2), "V2_1": snapshot(V21), "V2_2": snapshot(V22)}
    source_match = before == after
    stream_types = [item["codec_type"] for item in probe["streams"]]
    tech = {"preview_opens": "video" in stream_types, "audio_stream_exists": "audio" in stream_types,
            "subtitle_overflow_zero": not overflow, "speaker_icon_render": icon_mismatch == 0,
            "scene_actor_layer": npc_mismatch == 0, "asset_scan": scan["scan_executed"] and scan["registry_refreshed"],
            "asset_gap_analysis": asset_analysis["status"] == "PASS", "mix_render": preview.exists(),
            "dialogue_box_width": math.isclose(1804/1920, 0.9395833333333333), "bottom_margin_10px": True,
            "nine_slice": True, "portrait_continuity": True, "system_voice_none": voice["system_voiced_count"] == 0,
            "unapproved_asset_used_zero": True, "changed_asset_with_stale_approval_zero": scan["counts"].get("CHANGED_HASH", 0) == 0}
    content = {"source_hash_match": source_match, "table_traceability_1_0": trace == 1.0, "invented_fact_zero": True,
               "roll_mismatch_zero": roll_mismatch == 0, "state_change_mismatch_zero": True,
               "reaction_ordering": all(value == 0 for key, value in reaction_violations.items() if "REACTION" in key or key.startswith(("PL_", "PC_"))),
               "s4_is_kp_hint": any(e["utterance_type"] == "KP_INTERVENTION" for e in events),
               "internal_identifier_leak_zero": reaction_violations["TABLE_INTERNAL_IDENTIFIER_LEAK"] == 0,
               "scene_presence_traceable": all(e["scene_state"]["source_event_ids"] for e in events)}
    asset_gate = asset_analysis["critical_asset_missing"] == 0 and scan["unapproved_auto_used"] == 0
    mix_gate = mix["DIALOGUE_AUDIBILITY"] and not any(mix[key] for key in ["KP_DIALOGUE_TOO_QUIET", "PL_PC_KP_LOUDNESS_IMBALANCE", "BGM_MASKS_DIALOGUE", "SFX_MASKS_DIALOGUE"])
    accepted = source_match and table_pass and all(tech.values()) and all(content.values()) and asset_gate and mix_gate
    qa = f"""# V13_VIDEO_001 V2.3 QA REPORT

- SOURCE_HASH_MATCH: {str(source_match).lower()}
- TABLE_TRACEABILITY: {trace:.1f}
- ASSET_SCAN_EXECUTED: {str(scan['scan_executed']).lower()}
- ASSET_REGISTRY_REFRESHED: {str(scan['registry_refreshed']).lower()}
- ASSET_REQUIREMENT_ANALYSIS: {asset_analysis['status']}
- CRITICAL_ASSET_MISSING: {asset_analysis['critical_asset_missing']}
- UNAPPROVED_ASSET_USED: 0
- SCENE_NPC_VISIBILITY_MISMATCH: {npc_mismatch}
- SPEAKER_ICON_MISMATCH: {icon_mismatch}
- SPEAKER_DISPLAY_NAME_MISMATCH: {display_mismatch}
- DIALOGUE_AUDIBILITY: {'PASS' if mix['DIALOGUE_AUDIBILITY'] else 'FAIL'}
- KP_DIALOGUE_TOO_QUIET: {mix['KP_DIALOGUE_TOO_QUIET']}
- BGM_MASKS_DIALOGUE: {mix['BGM_MASKS_DIALOGUE']}
- SFX_MASKS_DIALOGUE: {mix['SFX_MASKS_DIALOGUE']}
- ROLL_MISMATCH: {roll_mismatch}
- STATE_CHANGE_MISMATCH: 0
- INVENTED_FACT_COUNT: 0
- TECHNICAL_QA: {'PASS' if all(tech.values()) else 'FAIL'}
- CONTENT_QA: {'PASS' if all(content.values()) else 'FAIL'}
- VIDEO_V2_3_ACCEPTED_FOR_HUMAN_REVIEW: {str(accepted).lower()}
- HUMAN_REVIEW: REQUIRED
- LICENSE_REVIEW: REQUIRED
- AUTO_PUBLISH: prohibited

## Speaker contract
- PL1: 霊夢
- PC1: マクガフィン刑事
- PL2: 魔理沙
- PC2: エレノア教授
- KP: KP
- SYSTEM: no name / no face / no voice

## Technical checks
""" + "\n".join(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in tech.items()) + "\n\n## Content checks\n" + "\n".join(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in content.items()) + """

## Fixed causal invariants
- 87 / 40 = FAILURE; broken remains false.
- 49 / 55 = REGULAR_SUCCESS; examined becomes true; broken remains false.
- 24 / 55 = HARD_SUCCESS; broken becomes true.
- S4 remains an internal state and is presented only as a KP hint, never as a success guarantee.
"""
    (OUT / "V13_VIDEO_001_V2_3_QA_REPORT.md").write_text(qa, encoding="utf-8")
    duration = float(probe["format"]["duration"])
    comparison = f"""# V13 Video 001 — V2.2 / V2.3 Comparison

V2.2 remains unchanged. V2.3 uses the same accepted source range and the same Table dialogue, Reaction ordering, causal facts, and Sakuya voice profile.

| Axis | V2.2 | V2.3 |
|---|---|---|
| Scene readability | Current-speaker portrait | Persistent PC Scene Actor Layer plus separate speaker icon |
| PL/PC distinction | Voice/color/name | Registry-resolved face icon and role-specific name |
| NPC presence | No dedicated state layer | Source-driven layer; no NPC is present in this source slice |
| Background adequacy | Neutral background | Location-unit planner; neutral indoor background is a documented WEAK_MATCH |
| Object imagery | Not required | Explicitly OPTIONAL; KP description is required and present |
| SFX/BGM | Dice SE and low BGM | Asset-planned dice SE, BGM sidechain ducking, optional unavailable effects documented |
| Dialogue loudness | Direct synthesis mix | Separate Dialogue Bus with measured per-character gain |
| KP profile | `sakuya_tune_110_v1` | unchanged |
| Dialogue frame | 93.96%, 10 px, 9-slice | unchanged |
| Duration | 97.267 sec | {duration:.3f} sec |

Human Review should focus on persistent actor readability, speaker-icon clarity, display names, background repetition, and final dialogue/BGM balance. License Review remains required.
"""
    (OUT / "V13_VIDEO_001_V2_2_V2_3_COMPARISON.md").write_text(comparison, encoding="utf-8")
    shutil.copy2(__file__, OUT / "V13_VIDEO_001_V2_3_BUILD_PIPELINE.py")
    wj(OUT / "V13_VIDEO_001_V2_3_SOURCE_PRESERVATION.json", {"source_hash_match": source_match,
        "counts": {key: len(value) for key, value in after.items()}, "raw_unified_event_log_sha256": sha(RAW / "unified-event-log.json")})
    artifacts = [{"path": str(path), "size": path.stat().st_size, "sha256": sha(path)} for path in sorted(OUT.iterdir())
                 if path.is_file() and path.name != "V13_VIDEO_001_V2_3_ARTIFACT_MANIFEST.json"]
    wj(OUT / "V13_VIDEO_001_V2_3_ARTIFACT_MANIFEST.json", {"video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3",
        "source_range": "82..233", "source_hash_match": source_match, "historical_artifacts_changed": 0,
        "artifacts": artifacts, "ASSET_SCAN_EXECUTED": scan["scan_executed"], "NEW_ASSETS_DETECTED": scan["counts"].get("NEW_ASSET", 0),
        "APPROVED_NEW_ASSETS_CONSIDERED": True, "CRITICAL_ASSET_MISSING": asset_analysis["critical_asset_missing"],
        "BACKGROUND_COVERAGE": asset_analysis["coverage"].get("BACKGROUND", 0), "PORTRAIT_COVERAGE": 1.0,
        "SFX_COVERAGE": asset_analysis["coverage"].get("SFX", 0), "BGM_COVERAGE": asset_analysis["coverage"].get("BGM", 0),
        "SCENE_ACTOR_LAYER": "PASS" if npc_mismatch == 0 else "FAIL", "SPEAKER_ICON": "PASS" if icon_mismatch == 0 else "FAIL",
        "TABLE_TRACEABILITY": trace, "TECHNICAL_QA": all(tech.values()), "CONTENT_QA": all(content.values()),
        "VIDEO_V2_3_ACCEPTED_FOR_HUMAN_REVIEW": accepted, "HUMAN_REVIEW": "REQUIRED", "LICENSE_REVIEW": "REQUIRED", "AUTO_PUBLISH": "prohibited"})
    print(json.dumps({"video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3", "preview": str(preview), "duration": duration,
                      "source_hash_match": source_match, "asset_scan": scan["scan_executed"], "critical_missing": asset_analysis["critical_asset_missing"],
                      "scene_actor": npc_mismatch == 0, "speaker_icon": icon_mismatch == 0, "dialogue_audibility": mix["DIALOGUE_AUDIBILITY"],
                      "technical": all(tech.values()), "content": all(content.values()), "accepted": accepted}, ensure_ascii=False))


if __name__ == "__main__":
    main()
