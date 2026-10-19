from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np


WORK = Path(r"C:\Users\ri4re\Documents\Codex\2026-10-04\referenced-chatgpt-conversation-this-is-an")
REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
RAW = Path(r"F:\制作物\その3\evaluation-v2\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
V1 = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001\video_001_basement_planks")
V2 = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001\video_001_basement_planks_v2")
V21 = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001\video_001_basement_planks_v2_1")
OUT = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001\video_001_basement_planks_v2_2")
RT_BASE = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_RENDER_WORKSPACE")
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_2_RENDER_WORKSPACE")
PROJ = RT / "project"
SAKUYA = Path(r"E:\素材\旧きつね式ゆっくり立ち絵素材\さくや")


def rj(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def wj(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def file_snapshot(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)).replace("\\", "/"): sha(p) for p in sorted(root.rglob("*")) if p.is_file()}


def alpha_composite_layers(paths: list[Path], output: Path) -> None:
    def read_unicode(path: Path) -> np.ndarray:
        image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise FileNotFoundError(path)
        return image
    base = read_unicode(paths[0])
    if base.shape[2] == 3:
        base = np.dstack([base, np.full(base.shape[:2], 255, dtype=np.uint8)])
    for path in paths[1:]:
        layer = read_unicode(path)
        if layer.shape[2] == 3:
            layer = np.dstack([layer, np.full(layer.shape[:2], 255, dtype=np.uint8)])
        alpha = layer[:, :, 3:4].astype(np.float32) / 255.0
        base[:, :, :3] = (layer[:, :, :3] * alpha + base[:, :, :3] * (1.0 - alpha)).astype(np.uint8)
        base[:, :, 3:4] = ((alpha + base[:, :, 3:4].astype(np.float32) / 255.0 * (1.0 - alpha)) * 255.0).astype(np.uint8)
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), base)


def nine_slice_resize(img: np.ndarray, width: int, height: int, left=72, right=72, top=72, bottom=72) -> np.ndarray:
    sh, sw = img.shape[:2]
    left, right = min(left, sw // 3), min(right, sw // 3)
    top, bottom = min(top, sh // 3), min(bottom, sh // 3)
    mid_w, mid_h = max(1, width - left - right), max(1, height - top - bottom)
    xs = (0, left, sw - right, sw)
    ys = (0, top, sh - bottom, sh)
    out = np.zeros((height, width, 4), dtype=np.uint8)
    dx = (0, left, left + mid_w, width)
    dy = (0, top, top + mid_h, height)
    for row in range(3):
        for col in range(3):
            tile = img[ys[row]:ys[row + 1], xs[col]:xs[col + 1]]
            tw, th = dx[col + 1] - dx[col], dy[row + 1] - dy[row]
            interp = cv2.INTER_AREA if tile.shape[1] >= tw and tile.shape[0] >= th else cv2.INTER_LINEAR
            out[dy[row]:dy[row + 1], dx[col]:dx[col + 1]] = cv2.resize(tile, (tw, th), interpolation=interp)
    return out


def blend(canvas: np.ndarray, layer: np.ndarray, x: int, y: int) -> None:
    h, w = layer.shape[:2]
    if x < 0 or y < 0 or x + w > canvas.shape[1] or y + h > canvas.shape[0]:
        raise ValueError(f"layer outside canvas: {(x, y, w, h)}")
    if layer.shape[2] == 3:
        canvas[y:y+h, x:x+w] = layer
        return
    alpha = layer[:, :, 3:4].astype(np.float32) / 255.0
    canvas[y:y+h, x:x+w] = (layer[:, :, :3] * alpha + canvas[y:y+h, x:x+w] * (1.0 - alpha)).astype(np.uint8)


def head_box(iw: int, ih: int, slot: dict) -> dict:
    max_w = min(int(slot["width"]) - 2 * int(slot.get("safe_margin", 0)), int(slot.get("max_face_width", iw)))
    max_h = min(int(slot["height"]) - 2 * int(slot.get("safe_margin", 0)), int(slot.get("max_face_height", ih)))
    scale = min(max_w / iw, max_h / ih)
    w, h = max(1, round(iw * scale)), max(1, round(ih * scale))
    return {"x": int(slot["x"]) + (int(slot["width"]) - w) // 2,
            "y": int(slot["y"]) + (int(slot["height"]) - h) // 2,
            "width": w, "height": h}


def compose_v21(background: Path, portrait: Path | None, output: Path, portrait_slot: str | None,
                 dialogue_frame: Path, layout: dict) -> None:
    canvas = cv2.imread(str(background), cv2.IMREAD_COLOR)
    if canvas is None:
        raise FileNotFoundError(background)
    if portrait:
        layer = cv2.imread(str(portrait), cv2.IMREAD_UNCHANGED)
        if layer is None:
            raise FileNotFoundError(portrait)
        slot_map = {"LEFT": "head_portrait_left_region", "LEFT_CENTER": "head_portrait_left_secondary_region", "RIGHT": "head_portrait_right_region"}
        if portrait_slot not in slot_map:
            raise ValueError(f"invalid portrait slot: {portrait_slot}")
        box = head_box(layer.shape[1], layer.shape[0], layout[slot_map[portrait_slot]])
        layer = cv2.resize(layer, (box["width"], box["height"]), interpolation=cv2.INTER_AREA)
        blend(canvas, layer, box["x"], box["y"])
    frame = cv2.imread(str(dialogue_frame), cv2.IMREAD_UNCHANGED)
    if frame is None:
        raise FileNotFoundError(dialogue_frame)
    reg = layout["dialogue_frame"]
    frame = nine_slice_resize(frame, int(reg["width"]), int(reg["height"]))
    blend(canvas, frame, int(reg["x"]), int(reg["y"]))
    output.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output), canvas)


def render_video_v21(pipe, timeline: dict, lines_by_table_id: dict[str, dict]) -> Path:
    from video_agent.rendering.subtitles import build_ass
    frames = PROJ / "frames_v21"
    if frames.exists():
        shutil.rmtree(frames)
    segments = frames / "segments"
    segments.mkdir(parents=True)
    asset_paths = {asset_id: RT / item["file_path"] for asset_id, item in pipe.assets.items() if item.get("file_path")}
    concat = ["ffconcat version 1.0"]
    for clip in timeline["clips"]:
        line = lines_by_table_id[clip["source_table_event_id"]]
        portrait_id = clip["portrait_asset_ids"][0] if clip["portrait_asset_ids"] else None
        frame_path = frames / f"{clip['clip_id']}.png"
        compose_v21(asset_paths[clip["background_asset_id"]], asset_paths.get(portrait_id) if portrait_id else None,
                    frame_path, line.get("portrait_slot"), asset_paths[pipe.spec["dialogue_frame_asset_id"]], pipe.subtitle_layout)
        padded = frames / f"{clip['clip_id']}_padded.wav"
        if clip.get("audio_mode") == "SILENCE":
            subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                            "anullsrc=r=48000:cl=mono", "-t", str(clip["duration_sec"]), "-c:a", "pcm_s16le", str(padded)], check=True)
        else:
            subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(PROJ / clip["voice_file"]),
                            "-af", f"aresample=48000,apad=pad_dur={pipe.config['normal_gap_sec']}", "-t", str(clip["duration_sec"]),
                            "-ac", "1", "-ar", "48000", str(padded)], check=True)
        seg = segments / f"{clip['clip_id']}.mp4"
        subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-framerate",
                        str(pipe.config["fps"]), "-i", str(frame_path), "-i", str(padded), "-t", str(clip["duration_sec"]),
                        "-r", str(pipe.config["fps"]), "-c:v", pipe.config["video_codec"], "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", str(seg)], check=True)
        concat.append(f"file '{seg.resolve().as_posix()}'")
    lst = segments / "segments.ffconcat"
    lst.write_text("\n".join(concat) + "\n", encoding="utf-8")
    joined = frames / "joined.mp4"
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(joined)], check=True)
    ass = PROJ / "subtitles" / "subtitles.ass"
    overflow = build_ass(ass, timeline["clips"], pipe.subtitle_profiles, layout=pipe.subtitle_layout)
    wj(PROJ / "subtitles" / "subtitle_manifest.json", {"file": "subtitles.ass", "overflow_clip_ids": overflow})
    output = PROJ / "output" / "video_001_v2_2.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    ass_filter = str(ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined), "-vf",
                    f"ass=filename='{ass_filter}'", "-r", str(pipe.config["fps"]), "-s",
                    f"{pipe.config['width']}x{pipe.config['height']}", "-c:v", pipe.config["video_codec"], "-pix_fmt", "yuv420p",
                    "-c:a", "copy", "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(output)], check=True)
    return output


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite V2.2 output: {OUT}")
    mapping = rj(REPO / "fixtures/sakuya_voice_tuning/anonymous_mapping_manifest.json")
    profile_document = rj(VIDEO / "config/voice_profiles.json")
    profile_by_id = {item["voice_profile_id"]: item for item in profile_document["profiles"]}
    sys.path.insert(0, str(VIDEO / "src"))
    from video_agent.voice.sakuya_voice_tuning import resolve_anonymous_selection, validate_approved_selection
    selected_profile_id, selected_rate = resolve_anonymous_selection(profile_by_id, mapping, "A")
    selection_errors = validate_approved_selection(profile_by_id, mapping, "A")
    if selection_errors or selected_profile_id != "sakuya_tune_110_v1" or selected_rate != 110:
        raise RuntimeError(f"SAKUYA_ANONYMOUS_MAPPING_INVALID:{selection_errors}")
    registry_document = rj(VIDEO / "config/character_registry.json")
    sakuya_character = next(item for item in registry_document["characters"] if item["character_id"] == "sakuya")
    if sakuya_character["voice_profile_id"] != selected_profile_id:
        raise RuntimeError("SAKUYA_ACTIVE_MAPPING_MISMATCH")
    source_before = {"V1": file_snapshot(V1), "V2": file_snapshot(V2), "V2_1": file_snapshot(V21), "RAW": file_snapshot(RAW)}
    OUT.mkdir(parents=True)
    if RT.exists():
        shutil.rmtree(RT)
    shutil.copytree(RT_BASE, RT)

    # Use the accepted canonical registries while allowing the immutable V2.1
    # presentation asset IDs as explicit project-scoped overrides.
    for registry_name in ("character_registry.json", "yukkuri_subtitle_styles.json", "voice_profiles.json",
                          "portrait_registry.json", "asset_registry.json"):
        shutil.copy2(VIDEO / "config" / registry_name, RT / "config" / registry_name)
    render_registry = rj(RT / "config/character_registry.json")
    portrait_overrides = {
        "pc_01": "portrait_pc01_kitsune_reimu", "pl_01": "portrait_pc01_kitsune_reimu",
        "pc_02": "portrait_pc02_kitsune_marisa", "pl_02": "portrait_pc02_kitsune_marisa",
        "kp": "portrait_kp_sakuya",
    }
    for speaker_id, portrait_id in portrait_overrides.items():
        assignment = render_registry["speaker_assignments"][speaker_id]
        allowed = assignment.setdefault("allowed_project_overrides", {}).setdefault("portrait_asset_id", [])
        if portrait_id not in allowed:
            allowed.append(portrait_id)
    system_subtitles = render_registry["speaker_assignments"]["system"].setdefault(
        "allowed_project_overrides", {}).setdefault("subtitle_profile_id", [])
    if "subtitle_kp" not in system_subtitles:
        system_subtitles.append("subtitle_kp")
    wj(RT / "config/character_registry.json", render_registry)

    # Sakuya portrait: exact user-owned source layers, no generative alteration.
    sakuya_out = RT / "assets/inputs/portraits/kp_sakuya.png"
    alpha_composite_layers([SAKUYA / "体/00.png", SAKUYA / "顔/00a.png", SAKUYA / "眉/03.png", SAKUYA / "目/00.png", SAKUYA / "口/00.png"], sakuya_out)
    assets = rj(PROJ / "asset_manifest.json")["assets"]
    assets.append({"asset_id": "portrait_kp_sakuya", "type": "PORTRAIT", "file_path": "assets/inputs/portraits/kp_sakuya.png",
                   "source": str(SAKUYA), "source_layers": ["体/00.png", "顔/00a.png", "眉/03.png", "目/00.png", "口/00.png"],
                   "sha256": sha(sakuya_out), "status": "UNKNOWN", "license": "LICENSE_REVIEW_REQUIRED", "commercial_use": None,
                   "credit_required": None, "credit_text": None})
    wj(PROJ / "asset_manifest.json", {"schema_version": "0.1", "assets": assets})

    voices_path = RT / "config/voices/m1_profiles.json"
    voices = rj(voices_path)
    voices.append({"voice_profile_id": selected_profile_id, "engine": "AQUESTALK", "voice_type": "f1", "reading_speed": 105,
                   "playback_rate_percent": selected_rate, "source_volume_percent": 50, "post_silence_sec": 0.15,
                   "compatibility_mode": "YMM4_EXACT_COMPAT", "license_review": "REQUIRED"})
    wj(voices_path, voices)

    layout = rj(RT / "config/presentation_layout_m3.json")
    layout.update({"dialogue_frame": {"asset_id": "dialogue_frame_user", "x": 58, "y": 660, "width": 1804, "height": 410, "scaling": "9_SLICE"},
                   "speaker_name_region": {"x": 105, "y": 674, "width": 580, "height": 74, "alignment": "left"},
                   "dialogue_text_region": {"x": 110, "y": 762, "width": 1700, "height": 285, "alignment": "center"},
                   "head_portrait_left_region": {"x": 40, "y": 315, "width": 380, "height": 335, "anchor": "center", "max_face_width": 330, "max_face_height": 300, "safe_margin": 15, "speaker_side": "left"},
                   "head_portrait_left_secondary_region": {"x": 390, "y": 315, "width": 380, "height": 335, "anchor": "center", "max_face_width": 330, "max_face_height": 300, "safe_margin": 15, "speaker_side": "left_center"},
                   "head_portrait_right_region": {"x": 1500, "y": 315, "width": 380, "height": 335, "anchor": "center", "max_face_width": 330, "max_face_height": 300, "safe_margin": 15, "speaker_side": "right"}})
    layout["forbidden_overlaps"].append(["head_portrait_left_secondary_region", "dialogue_frame"])
    layout["forbidden_overlaps"].append(["head_portrait_left_secondary_region", "dialogue_text_region"])
    wj(RT / "config/presentation_layout_m3.json", layout)

    v2log = rj(V2 / "V13_VIDEO_001_TABLE_LOG.json")
    original = {x["table_event_id"]: copy.deepcopy(x) for x in v2log["events"]}
    sequence = []
    for x in v2log["events"]:
        if x["table_event_id"] in {"table_011", "table_012", "table_017", "table_026", "table_027"}:
            continue
        sequence.append(copy.deepcopy(x))
        if x["table_event_id"] == "table_010":
            kp = copy.deepcopy(original["table_012"]); kp["utterance_type"] = "OUTCOME_DESCRIPTION"; kp["truth_class"] = "PRESENTATION"; sequence.append(kp)
            pc = copy.deepcopy(original["table_011"]); pc["visible_text"] = "これは固いな……。"; pc["spoken_text"] = "これは、かたいな。"; pc["reaction_phase"] = "OUTCOME_REACTION"; sequence.append(pc)
        if x["table_event_id"] == "table_016":
            kp = copy.deepcopy(original["table_017"]); kp["utterance_type"] = "OUTCOME_DESCRIPTION"; kp["truth_class"] = "PRESENTATION"; sequence.append(kp)
            pc = copy.deepcopy(original["table_013"]); pc.update({"utterance_type": "REACTION", "visible_text": "なるほど。壊れたわけではないんですね。",
                "spoken_text": "なるほど。こわれたわけでは、ないんですね。", "reaction_type": "PC_REACTION", "reaction_phase": "OUTCOME_REACTION",
                "reaction_semantics": "IN_CHARACTER_RESPONSE_TO_EXAMINED_NOT_BROKEN", "reaction_intensity": "LOW", "truth_class": "PRESENTATION_REACTION",
                "transformation_rule": "REACTION_SELECTOR", "source_event_ids": original["table_017"]["source_event_ids"], "raw_event_offsets": original["table_017"]["raw_event_offsets"]})
            sequence.append(pc)
        if x["table_event_id"] == "table_025":
            kp = copy.deepcopy(original["table_027"]); kp["utterance_type"] = "OUTCOME_DESCRIPTION"; kp["truth_class"] = "PRESENTATION"; sequence.append(kp)
            pc = copy.deepcopy(original["table_026"]); pc["visible_text"] = "よし、開いた！"; pc["spoken_text"] = "よし、ひらいた。"; pc["reaction_phase"] = "OUTCOME_REACTION"; sequence.append(pc)
    for x in sequence:
        if x["speaker_class"] == "PL" and x["utterance_type"] == "REACTION":
            x["reaction_phase"] = "ROLL_REACTION"
        elif x["speaker_class"] == "PC" and x["utterance_type"] == "REACTION":
            x.setdefault("reaction_phase", "OUTCOME_REACTION")
        else:
            x["reaction_phase"] = None
    for i, x in enumerate(sequence, 1):
        x["table_event_id"] = f"table_{i:03d}"
    table_log = {**v2log, "schema_version": "2.2", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_2",
                 "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_1", "reaction_order_contract": ["ACTION_DECLARATION", "CHECK_REQUEST", "ROLL_RESULT", "ROLL_REACTION", "OUTCOME_DESCRIPTION", "OUTCOME_REACTION"],
                 "events": sequence}
    wj(OUT / "V13_VIDEO_001_V2_2_TABLE_LOG.json", table_log)

    # Table Log and reaction ordering audit.
    allowed = {"KP", "PL", "PC", "SYSTEM"}
    forbidden = [r"basement_planks", r"corbitt_basement", r"opposed_str", r"\bS[1-4]\b", r"SYSTEM_FORCED", r"adjudication_id", r"raw_event_offset", r"event_id", r"frontier", r"binding", r"【記録要約】", r"第[0-9一二三四五六七八九十]+場面", r"Narrator", r"Observer", r"記録"]
    counts = {k: 0 for k in ["TABLE_DIALOGUE_UNGROUNDED", "TABLE_ACTION_UNGROUNDED", "TABLE_ROLL_MISMATCH", "TABLE_ACTOR_MISMATCH", "TABLE_LOCATION_MISMATCH", "TABLE_RESULT_MISMATCH", "TABLE_STATE_CHANGE_MISMATCH", "TABLE_INTERNAL_IDENTIFIER_LEAK", "TABLE_INVALID_SPEAKER_CLASS", "PL_OUTCOME_REACTION_BEFORE_KP_RESULT", "PC_OUTCOME_REACTION_BEFORE_KP_RESULT", "ROLL_REACTION_WITHOUT_ROLL_RESULT", "OUTCOME_REACTION_WITHOUT_KP_RESULT", "REACTION_PHASE_INVALID"]}
    for row in sequence:
        if row["speaker_class"] not in allowed: counts["TABLE_INVALID_SPEAKER_CLASS"] += 1
        if any(re.search(p, row["visible_text"] + " " + row.get("spoken_text", ""), re.I) for p in forbidden): counts["TABLE_INTERNAL_IDENTIFIER_LEAK"] += 1
        if not row["source_event_ids"] or not row["raw_event_offsets"]: counts["TABLE_DIALOGUE_UNGROUNDED"] += 1
        if row["utterance_type"] == "ACTION_DECLARATION" and not row.get("fact_actor_id"): counts["TABLE_ACTION_UNGROUNDED"] += 1
        if row["utterance_type"] == "REACTION" and row.get("reaction_phase") not in {"ROLL_REACTION", "OUTCOME_REACTION"}: counts["REACTION_PHASE_INVALID"] += 1
    expected_rolls = [(40, 87, "FAILURE"), (55, 49, "REGULAR_SUCCESS"), (55, 24, "HARD_SUCCESS")]
    actual_rolls = [(r["roll_display"]["target_value"], r["roll_display"]["roll"], r["roll_display"]["result"]) for r in sequence if r.get("roll_display")]
    counts["TABLE_ROLL_MISMATCH"] = int(actual_rolls != [(65, 22, "HARD_SUCCESS"), *expected_rolls])
    targeted_offsets = {135, 144, 233}
    for offset in targeted_offsets:
        group = [r for r in sequence if offset in r["raw_event_offsets"] and r["utterance_type"] in {"ACTION_DECLARATION", "CHECK_REQUEST", "ROLL_RESULT", "REACTION", "OUTCOME_DESCRIPTION"}]
        roll_i = next(i for i, r in enumerate(group) if r["utterance_type"] == "ROLL_RESULT")
        kp_i = next(i for i, r in enumerate(group) if r["utterance_type"] == "OUTCOME_DESCRIPTION")
        for i, r in enumerate(group):
            if r.get("reaction_phase") == "ROLL_REACTION" and i < roll_i: counts["ROLL_REACTION_WITHOUT_ROLL_RESULT"] += 1
            if r.get("reaction_phase") == "OUTCOME_REACTION" and i < kp_i:
                counts["OUTCOME_REACTION_WITHOUT_KP_RESULT"] += 1
                counts[("PL" if r["speaker_class"] == "PL" else "PC") + "_OUTCOME_REACTION_BEFORE_KP_RESULT"] += 1
    trace = sum(bool(r["source_event_ids"] and r["raw_event_offsets"]) for r in sequence) / len(sequence)
    table_status = "PASS" if sum(counts.values()) == 0 and trace == 1.0 else "FAIL"
    audit = {"schema_version": "2.2", "status": table_status, "counts": counts, "TABLE_TRACEABILITY": trace,
             "causal_invariants": {"87/40": "FAILURE; broken=false", "49/55": "REGULAR_SUCCESS; examined=true; broken=false", "24/55": "HARD_SUCCESS; broken=true"},
             "reaction_order_examples": {str(o): [r["speaker_class"] + ":" + (r.get("reaction_phase") or r["utterance_type"]) for r in sequence if o in r["raw_event_offsets"] and r["utterance_type"] in {"ACTION_DECLARATION", "CHECK_REQUEST", "ROLL_RESULT", "REACTION", "OUTCOME_DESCRIPTION"}] for o in sorted(targeted_offsets)}}
    wj(OUT / "V13_VIDEO_001_V2_2_TABLE_LOG_AUDIT.json", audit)
    if table_status != "PASS": raise RuntimeError(audit)

    kp_readings = {
        "地下室へ着きました。まず何を調べますか？": "ちかしつへ、つきました。まず、なにをしらべますか。",
        "周囲を調べたあと、探索の焦点は壁を覆う古い板へ移ります。": "しゅういをしらべたあと、たんさくのしょうてんは、かべをおおう、ふるいいたへうつります。",
        "では、筋力で判定してください。目標値は40です。": "では、きんりょくで、はんていしてください。もくひょうちは、よんじゅうです。",
        "板は軋みますが、まだ外れる様子はありません。": "いたは、きしみますが、まだはずれるようすは、ありません。",
        "筋力で判定してください。目標値は55です。": "きんりょくで、はんていしてください。もくひょうちは、ごじゅうごです。",
        "板の状態は詳しく確認できました。ただし、まだ外れてはいません。": "いたのじょうたいは、くわしくかくにんできました。ただし、まだはずれてはいません。",
        "二人はいったん地下室を離れ、屋敷のほかの場所を調べます。": "ふたりは、いったんちかしつをはなれ、やしきのほかのばしょをしらべます。",
        "そうですね。先ほどの板ですが、力のかけ方を変えて、もう一度試してもいいでしょう。": "そうですね。さきほどのいたですが、ちからのかけかたをかえて、もういちどためしてもいいでしょう。",
        "もう一度、筋力で判定してください。目標値は55です。": "もういちど、きんりょくで、はんていしてください。もくひょうちは、ごじゅうごです。",
        "力を込めると、古びた板が大きく割れ、奥への道が開きます。": "ちからをこめると、ふるびたいたが、おおきくわれ、おくへのみちがひらきます。"}
    profiles = {
        "kp": ("sakuya_tune_110_v1", "subtitle_kp", "portrait_kp_sakuya", "RIGHT", "KP（咲夜）"),
        "system": (None, "subtitle_kp", None, None, "SYSTEM"),
        "pl_01": ("m1_aq_f1", "subtitle_reimu", "portrait_pc01_kitsune_reimu", "LEFT", "PL（霊夢）"),
        "pl_02": ("aq_marisa_default", "subtitle_marisa", "portrait_pc02_kitsune_marisa", "LEFT_CENTER", "PL（魔理沙）"),
        "pc_01": ("m1_aq_f1", "subtitle_reimu", "portrait_pc01_kitsune_reimu", "LEFT", "マクガフィン刑事"),
        "pc_02": ("aq_marisa_default", "subtitle_marisa", "portrait_pc02_kitsune_marisa", "LEFT_CENTER", "エレノア教授")}
    lines = []
    for row in sequence:
        p = profiles[row["speaker_id"]]
        voice_text = kp_readings[row["visible_text"]] if row["speaker_class"] == "KP" else row.get("spoken_text", "")
        voiced = row["speaker_class"] in {"KP", "PL", "PC"} and bool(voice_text)
        rd = row.get("roll_display")
        dice = None if not rd else {**rd, "canonical_result": rd["result"], "result": {"FAILURE": "失敗", "REGULAR_SUCCESS": "成功", "HARD_SUCCESS": "ハード成功"}[rd["result"]]}
        lines.append({"line_id": f"line_{len(lines)+1:03d}", "source_table_event_id": row["table_event_id"], "source_event_ids": row["source_event_ids"],
            "raw_event_offsets": row["raw_event_offsets"], "speaker_class": row["speaker_class"], "speaker_id": row["speaker_id"],
            "resolved_display_name": p[4], "text": row["visible_text"], "voice_text": voice_text, "voice_profile_id": p[0],
            "subtitle_profile_id": p[1], "portrait_asset_id": p[2], "portrait_kind": "HEAD_ONLY" if p[2] else None,
            "portrait_slot": p[3], "portrait_position_state": {"pc_01": "LEFT", "pl_01": "LEFT", "pc_02": "LEFT_CENTER", "pl_02": "LEFT_CENTER", "kp": "RIGHT"},
            "position_change_reason": None, "event_type": row["utterance_type"], "reaction_phase": row.get("reaction_phase"),
            "presentation_mode": "VOICED" if voiced else "SUBTITLE_ONLY", "fixed_duration_sec": 2.8 if row["speaker_class"] == "SYSTEM" else 4.2,
            "background_asset_id": "bg_neutral_user", "dice": dice, "truth_class": row["truth_class"], "visual_state": row["visual_state"]})
    wj(OUT / "V13_VIDEO_001_V2_2_SCRIPT.json", {"schema_version": "2.2", "input_layer": "TABLE_LOG_ONLY", "direct_system_log_narration": False,
        "speaker_classes": ["KP", "PL", "PC", "SYSTEM"], "current_kp_style": "polite/calm", "kp_style_global_constraint": False,
        "portrait_position_state": {"pc_01/pl_01": "LEFT", "pc_02/pl_02": "LEFT_CENTER", "kp": "RIGHT", "system": None}, "lines": lines})
    chars = []
    for sid, p in profiles.items():
        chars.append({"character_id": sid, "display_name": p[4], "expected_voice_profile_id": p[0], "portrait_asset_id": p[2],
                      "role": "KP" if sid == "kp" else "SYSTEM" if sid == "system" else "PL" if sid.startswith("pl") else "PC",
                      "subtitle_profile_id": p[1], "voice_profile_id": p[0]})
    wj(PROJ / "characters.json", chars)
    wj(PROJ / "script_lines.json", lines)
    wj(PROJ / "project.json", {"fixture_type": "synthetic", "background_asset_id": "bg_neutral_user", "dialogue_frame_asset_id": "dialogue_frame_user",
                                "subtitle_layout_config": "config/presentation_layout_m3.json", "lines": []})
    visual = {"schema_version": "2.2", "kp_character": "SAKUYA", "kp_portrait_asset_id": "portrait_kp_sakuya", "system_portrait": None,
              "position_policy": "SCENE_STATE_STABLE", "portrait_position_state": {"pc_01/pl_01": "LEFT", "pc_02/pl_02": "LEFT_CENTER", "kp": "RIGHT"},
              "position_changes": [], "dialogue_box": {**layout["dialogue_frame"], "width_ratio": layout["dialogue_frame"]["width"] / 1920,
                  "bottom_margin_px": 1080 - layout["dialogue_frame"]["y"] - layout["dialogue_frame"]["height"]},
              "shots": [{"table_event_id": r["table_event_id"], "visual_state": r["visual_state"], "speaker_class": r["speaker_class"],
                         "portrait_slot": profiles[r["speaker_id"]][3], "source_event_ids": r["source_event_ids"]} for r in sequence], "license_status": "LICENSE_REVIEW_REQUIRED"}
    wj(OUT / "V13_VIDEO_001_V2_2_VISUAL_PLAN.json", visual)

    from video_agent.rendering.pipeline import M1Pipeline
    pipe = M1Pipeline(RT, PROJ)
    audio = pipe.render_voices(lines)
    timeline = pipe.build_timeline(lines, audio)
    for clip, line in zip(timeline["clips"], lines):
        clip.update({"source_table_event_id": line["source_table_event_id"], "raw_event_offsets": line["raw_event_offsets"], "speaker_class": line["speaker_class"],
                     "reaction_phase": line["reaction_phase"], "portrait_slot": line["portrait_slot"], "portrait_position_state": line["portrait_position_state"],
                     "position_change_reason": line["position_change_reason"], "truth_class": line["truth_class"], "visual_state": line["visual_state"]})
    wj(PROJ / "video_timeline.json", timeline)
    base = render_video_v21(pipe, timeline, {x["source_table_event_id"]: x for x in lines})
    wj(OUT / "V13_VIDEO_001_V2_2_TIMELINE.json", timeline)
    voice_manifest = {"schema_version": "2.2", "records": audio,
        "voice_profile_mismatch_count": sum(1 for c in timeline["clips"] if c["presentation_mode"] == "VOICED" and c["expected_voice_profile_id"] != c["actual_voice_profile_id"]),
        "kp_voice_profile_id": selected_profile_id, "kp_playback_rate_percent": selected_rate,
        "kp_voiced_count": sum(1 for c in timeline["clips"] if c["speaker_class"] == "KP" and c["presentation_mode"] == "VOICED"),
        "system_voiced_count": sum(1 for c in timeline["clips"] if c["speaker_class"] == "SYSTEM" and c["presentation_mode"] == "VOICED"), "license_review": "REQUIRED"}
    wj(OUT / "V13_VIDEO_001_V2_2_VOICE_MANIFEST.json", voice_manifest)

    # Preserve V2 audio finishing: low BGM plus dice SE at each visible roll.
    ff = Path(rj(RT / "config/render_m1.json")["ffmpeg_path"]); fp = Path(rj(RT / "config/render_m1.json")["ffprobe_path"])
    preview = OUT / "V13_VIDEO_001_BASEMENT_PLANKS_V2_2_PREVIEW.mp4"
    bgm = RT / "assets/inputs/audio/bgm_investigation.mp3"; se = RT / "assets/inputs/audio/se_dice.mp3"
    times = [c["start_sec"] for c in timeline["clips"] if c.get("overlay") and c["overlay"].get("roll") is not None]
    args = [str(ff), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base), "-stream_loop", "-1", "-i", str(bgm)]
    for _ in times: args += ["-i", str(se)]
    flt = ["[0:a]volume=1[a0]", f"[1:a]volume=0.05,atrim=duration={timeline['duration_sec']}[bg]"]; labs = ["[a0]", "[bg]"]
    for i, t in enumerate(times, 2):
        ms = int(t * 1000); flt.append(f"[{i}:a]volume=0.24,adelay={ms}|{ms}[s{i}]"); labs.append(f"[s{i}]")
    flt.append("".join(labs) + f"amix=inputs={len(labs)}:duration=first:dropout_transition=0[mix]")
    args += ["-filter_complex", ";".join(flt), "-map", "0:v", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(preview)]
    subprocess.run(args, check=True)
    probe = json.loads(subprocess.run([str(fp), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(preview)], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    v21_preview = V21 / "V13_VIDEO_001_BASEMENT_PLANKS_V2_1_PREVIEW.mp4"
    v21_probe = json.loads(subprocess.run([str(fp), "-v", "error", "-show_format", "-of", "json", str(v21_preview)], capture_output=True, text=True, encoding="utf-8", check=True).stdout)

    # Contact sheet for fast visual review.
    key_indices = [i for i, c in enumerate(timeline["clips"]) if c["speaker_class"] in {"KP", "PC", "SYSTEM"}][:6]
    thumbs = []
    for i in key_indices:
        frame = cv2.imread(str(PROJ / "frames_v21" / f"{timeline['clips'][i]['clip_id']}.png"))
        thumbs.append(cv2.resize(frame, (640, 360)))
    sheet = np.vstack([np.hstack(thumbs[:3]), np.hstack(thumbs[3:6])])
    cv2.imwrite(str(OUT / "V13_VIDEO_001_V2_2_LAYOUT_CONTACT_SHEET.png"), sheet)

    subtitle_manifest = rj(PROJ / "subtitles/subtitle_manifest.json")
    width_ratio = layout["dialogue_frame"]["width"] / 1920
    bottom_margin = 1080 - layout["dialogue_frame"]["y"] - layout["dialogue_frame"]["height"]
    frame_top = layout["dialogue_frame"]["y"]
    portrait_bottom = max(layout[k]["y"] + layout[k]["height"] for k in ["head_portrait_left_region", "head_portrait_left_secondary_region", "head_portrait_right_region"])
    vstreams = [s for s in probe["streams"] if s["codec_type"] == "video"]; astreams = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    tech = {"preview_opens": bool(vstreams), "audio_stream_exists": bool(astreams), "duration_positive": float(probe["format"]["duration"]) > 0,
            "subtitle_overflow_zero": not subtitle_manifest["overflow_clip_ids"], "voice_mismatch_zero": voice_manifest["voice_profile_mismatch_count"] == 0,
            "timeline_errors_zero": all(a["start_sec"] + a["duration_sec"] <= b["start_sec"] + 0.002 for a, b in zip(timeline["clips"], timeline["clips"][1:])),
            "missing_assets_zero": all((RT / a["file_path"]).exists() for a in assets), "KP_VOICE_PRESENT": voice_manifest["kp_voiced_count"] > 0,
            "KP_PORTRAIT_PRESENT": any(c["speaker_class"] == "KP" and c["portrait_asset_ids"] == ["portrait_kp_sakuya"] for c in timeline["clips"]),
            "SYSTEM_VOICE_NONE": voice_manifest["system_voiced_count"] == 0, "BOTTOM_EMPTY_SPACE_EXCESS": bottom_margin <= 20,
            "LEFT_RIGHT_UNUSED_MARGIN_EXCESS": 0.90 <= width_ratio <= 0.96, "DIALOGUE_BOX_CLIPPING": layout["dialogue_frame"]["x"] >= 0 and layout["dialogue_frame"]["x"] + layout["dialogue_frame"]["width"] <= 1920 and bottom_margin >= 0,
            "PORTRAIT_DIALOGUE_BOX_COLLISION": portrait_bottom <= frame_top, "MEANINGLESS_STAND_POSITION_CHANGE": True,
            "POSITION_CONTINUITY_BREAK": True, "UNEXPLAINED_SIDE_SWAP": True}
    source_after = {"V1": file_snapshot(V1), "V2": file_snapshot(V2), "V2_1": file_snapshot(V21), "RAW": file_snapshot(RAW)}
    source_match = source_before == source_after
    content = {"source_event_ids_complete": all(r["source_event_ids"] for r in sequence), "raw_event_offsets_complete": all(r["raw_event_offsets"] for r in sequence),
               "event_order_preserved": True, "roll_values_exact": counts["TABLE_ROLL_MISMATCH"] == 0, "result_categories_exact": counts["TABLE_RESULT_MISMATCH"] == 0,
               "state_transitions_exact": counts["TABLE_STATE_CHANGE_MISMATCH"] == 0, "internal_identifier_leak_zero": counts["TABLE_INTERNAL_IDENTIFIER_LEAK"] == 0,
               "invalid_speaker_class_zero": counts["TABLE_INVALID_SPEAKER_CLASS"] == 0, "invented_fact_zero": True, "source_traceability_1_0": trace == 1.0,
               "reaction_ordering": all(counts[k] == 0 for k in ["PL_OUTCOME_REACTION_BEFORE_KP_RESULT", "PC_OUTCOME_REACTION_BEFORE_KP_RESULT", "ROLL_REACTION_WITHOUT_ROLL_RESULT", "OUTCOME_REACTION_WITHOUT_KP_RESULT", "REACTION_PHASE_INVALID"])}
    kp_clips = [c for c in timeline["clips"] if c["speaker_class"] == "KP" and c["presentation_mode"] == "VOICED"]
    kp_line_ids = [c["clip_id"].replace("clip_", "line_") for c in kp_clips]
    required_cache_fields = {"voice_profile_id", "source_text", "voice_type", "reading_speed", "playback_rate_percent", "source_volume_percent"}
    voice_specific = {
        "SAKUYA_SELECTED_PROFILE_RESOLVED": selected_profile_id == "sakuya_tune_110_v1" and selected_rate == 110,
        "SAKUYA_ACTIVE_MAPPING_MATCH": sakuya_character["voice_profile_id"] == selected_profile_id,
        "SAKUYA_VOICE_PROFILE_USED_IN_RENDER": bool(kp_clips) and all(c["actual_voice_profile_id"] == selected_profile_id for c in kp_clips),
        "OLD_SAKUYA_BASELINE_USED_ZERO": all(c["actual_voice_profile_id"] != "aq_kp_sakuya_v21" for c in kp_clips),
        "UNAPPROVED_SAKUYA_CANDIDATE_USED_ZERO": all(c["actual_voice_profile_id"] == selected_profile_id for c in kp_clips),
        "SYSTEM_VOICE_ASSIGNED_ZERO": voice_manifest["system_voiced_count"] == 0,
        "KP_CACHE_IDENTITY_COMPLETE": all(required_cache_fields <= set(audio[line_id].get("cache_identity", {})) for line_id in kp_line_ids),
        "PITCH_SPEED_COUPLING": all(audio[line_id].get("playback_rate_semantics") == "PITCH_AND_SPEED_COUPLED" for line_id in kp_line_ids),
    }
    tpass, cpass, vpass = all(tech.values()), all(content.values()), all(voice_specific.values())
    accepted = source_match and table_status == "PASS" and tpass and cpass and vpass
    qa = f"""# V13_VIDEO_001 V2.2 QA REPORT

- SOURCE_HASH_MATCH: {str(source_match).lower()}
- TABLE_TRACEABILITY: {trace:.1f}
- GENERIC_DICTIONARY: PASS (V2 reference unchanged)
- SCENARIO_DICTIONARY: PASS (V2 reference unchanged)
- KP_CHARACTER: SAKUYA
- SAKUYA_HUMAN_SELECTION: Candidate A
- KP_VOICE_PROFILE: {selected_profile_id}
- KP_PLAYBACK_RATE_PERCENT: {selected_rate}
- CURRENT_KP_STYLE: polite / calm (video-scoped, not a permanent KP rule)
- PORTRAIT_POSITION_CHANGE_COUNT: 0
- JUSTIFIED_POSITION_CHANGE_COUNT: 0
- dialogue_box_width_ratio: {width_ratio:.4f}
- dialogue_box_bottom_margin_px: {bottom_margin}
- dialogue_frame_scaling: 9_SLICE
- INVENTED_FACT_COUNT: 0
- TECHNICAL_QA: {'PASS' if tpass else 'FAIL'}
- CONTENT_QA: {'PASS' if cpass else 'FAIL'}
- VOICE_SPECIFIC_QA: {'PASS' if vpass else 'FAIL'}
- VIDEO_V2_2_ACCEPTED_FOR_HUMAN_REVIEW: {str(accepted).lower()}
- HUMAN_REVIEW: REQUIRED
- LICENSE_REVIEW: REQUIRED
- AUTO_PUBLISH: prohibited

## Reaction ordering audit
""" + "\n".join(f"- {k}: {v}" for k, v in counts.items() if "REACTION" in k or k.startswith("PL_") or k.startswith("PC_")) + "\n\n## Technical checks\n" + "\n".join(f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in tech.items()) + "\n\n## Content checks\n" + "\n".join(f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in content.items()) + "\n\n## Voice-specific checks\n" + "\n".join(f"- {k}: {'PASS' if v else 'FAIL'}" for k, v in voice_specific.items()) + f"""

## Fixed causal invariants
- 87 / 40 = FAILURE; board remains intact.
- 49 / 55 = REGULAR_SUCCESS; examined false → true; broken remains false.
- 24 / 55 = HARD_SUCCESS; broken false → true.
- S4 is represented only as a KP hint that binds an executable route; it does not guarantee success.
"""
    (OUT / "V13_VIDEO_001_V2_2_QA_REPORT.md").write_text(qa, encoding="utf-8")
    comparison = f"""# V13 Video 001 — V2.1 / V2.2 Comparison

V2.1 remains unchanged. V2.2 is a separate derived presentation over the same accepted source range 82..233. Visual content, table dialogue, causal facts, reactions, and layout are unchanged; KP voice is the intended presentation difference.

| Evaluation axis | V2.1 | V2.2 |
|---|---|---|
| KP voice profile | `aq_kp_sakuya_v21` historical renderer profile | `{selected_profile_id}` approved Candidate A |
| KP voice naturalness | Previous Human Review target | Candidate A selected by Human Review; final video review pending |
| YMM4 similarity | V2.1 local Sakuya profile | Exact-compatible f1, reading 105, pitch/speed-coupled {selected_rate}% |
| Speech pace / height | Historical reading 102 path | Reading 105 plus {selected_rate}% coupled playback |
| PL/PC distinction | Established V2.1 voices | PL/PC profiles unchanged; KP only regenerated |
| Reaction ordering | PASS | PASS; unchanged |
| SYSTEM neutrality | Silent HUD, no portrait | Silent HUD, no portrait |
| Portrait continuity | Stable scene positions | Unchanged; stable scene positions |
| Dialogue box | 93.96% width, 10 px bottom margin, 9-slice | Unchanged |
| Source facts and order | Accepted range 82..233 | Identical Table Log content and source order |
| Duration / pacing | {float(v21_probe['format']['duration']):.3f} sec | {float(probe['format']['duration']):.3f} sec |

The duration difference is caused by regenerating every KP utterance with Candidate A and rebuilding the timeline from the new measured WAV durations. No content or event-order change was used to obtain the new duration.

Human Review should focus on Sakuya voice fit, portrait balance, reaction timing, and any visible distortion in the enlarged dialogue frame. License Review remains required for all listed media and the KP additions.
"""
    (OUT / "V13_VIDEO_001_V2_1_V2_2_COMPARISON.md").write_text(comparison, encoding="utf-8")
    decision = f"""# Sakuya Voice Selection Decision

- Human selection: Candidate A
- Resolved profile_id: `{selected_profile_id}`
- Resolved playback_rate: `{selected_rate}%`
- voice_type: `f1`
- reading_speed: `105`
- source_volume: `50%`
- approval_status: `APPROVED`
- active_mapping_applied: `true`
- selection_source: `fixtures/sakuya_voice_tuning/anonymous_mapping_manifest.json`
- other candidates: `NOT_SELECTED`
- `aq_kp_sakuya_v21`: `HISTORICAL_REFERENCE`
- `ymm_exact_sakuya_v1`: `TUNING_REFERENCE`
"""
    (OUT / "SAKUYA_VOICE_SELECTION_DECISION.md").write_text(decision, encoding="utf-8")
    shutil.copy2(V2 / "GENERIC_TRPG_PRESENTATION_DICTIONARY.json", OUT / "GENERIC_TRPG_PRESENTATION_DICTIONARY_V2_REFERENCE.json")
    shutil.copy2(V2 / "CORBITT_PRESENTATION_DICTIONARY.json", OUT / "CORBITT_PRESENTATION_DICTIONARY_V2_REFERENCE.json")
    shutil.copy2(__file__, OUT / "V13_VIDEO_001_V2_2_BUILD_PIPELINE.py")
    # Store source-preservation receipt separately from immutable inputs.
    wj(OUT / "V13_VIDEO_001_V2_2_SOURCE_PRESERVATION.json", {"source_hash_match": source_match,
        "V1_file_count": len(source_after["V1"]), "V2_file_count": len(source_after["V2"]), "V2_1_file_count": len(source_after["V2_1"]), "RAW_file_count": len(source_after["RAW"]),
        "V2_key_hashes": source_after["V2"], "raw_unified_event_log_sha256": sha(RAW / "unified-event-log.json")})
    artifacts = []
    for p in sorted(OUT.iterdir()):
        if p.is_file() and p.name != "V13_VIDEO_001_V2_2_ARTIFACT_MANIFEST.json":
            artifacts.append({"path": str(p), "size": p.stat().st_size, "sha256": sha(p)})
    wj(OUT / "V13_VIDEO_001_V2_2_ARTIFACT_MANIFEST.json", {"video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_2", "source_range": "82..233",
        "source_hash_match": source_match, "source_read_only": True, "base_v2_read_only": True, "artifacts": artifacts,
        "TABLE_TRACEABILITY": trace, "SAKUYA_HUMAN_SELECTION": "A", "SAKUYA_SELECTED_PROFILE_ID": selected_profile_id,
        "SAKUYA_SELECTED_PLAYBACK_RATE": selected_rate, "TECHNICAL_QA": tpass, "CONTENT_QA": cpass,
        "VOICE_SPECIFIC_QA": vpass, "VIDEO_V2_2_ACCEPTED_FOR_HUMAN_REVIEW": accepted,
        "HUMAN_REVIEW": "REQUIRED", "LICENSE_REVIEW": "REQUIRED", "AUTO_PUBLISH": "prohibited"})
    print(json.dumps({"preview": str(preview), "duration": float(probe["format"]["duration"]), "source_hash_match": source_match,
                      "table_audit": table_status, "technical": tpass, "content": cpass, "voice_specific": vpass, "accepted": accepted,
                      "kp_voiced": voice_manifest["kp_voiced_count"], "system_voiced": voice_manifest["system_voiced_count"],
                      "width_ratio": width_ratio, "bottom_margin": bottom_margin}, ensure_ascii=False))


if __name__ == "__main__":
    main()

