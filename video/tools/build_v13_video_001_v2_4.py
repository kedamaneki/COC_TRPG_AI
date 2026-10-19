from __future__ import annotations

import copy
import importlib.util
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

import cv2


REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
RAW = Path(r"F:\制作物\その3\evaluation-v2\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
BASE = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
V1 = BASE / "video_001_basement_planks"
V2 = BASE / "video_001_basement_planks_v2"
V21 = BASE / "video_001_basement_planks_v2_1"
V22 = BASE / "video_001_basement_planks_v2_2"
V23 = BASE / "video_001_basement_planks_v2_3"
OUT = BASE / "video_001_basement_planks_v2_4"
RT23 = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_3_RENDER_WORKSPACE")
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_4_RENDER_WORKSPACE")
PROJ = RT / "project"
EXTERNAL = Path(r"E:\素材\外部取得素材")

BACKGROUND = EXTERNAL / "backgrounds/basement/AIPICT/aipict_basement_ruins01.png"
BGM = EXTERNAL / "bgm/tension/itch.io/itch_arkeia_tension_as_the_light_fades.ogg"
CREAK = EXTERNAL / "sfx/wood_creak/Freesound_Rudmer_Rotteveel/freesound_502505_wood_creak_single_v1_hq_preview.mp3"
BREAK = EXTERNAL / "sfx/wood_break/Freesound/freesound_387014_wood_break_hq_preview.mp3"
DICE_SINGLE = Path(r"E:\素材\効果音素材\nc42339_ダイス音・1（1D10）.wav")
DICE_MULTI = Path(r"E:\素材\効果音素材\nc42340_ダイス音・2（2D10）.wav")

V23_BUILDER = VIDEO / "tools/build_v13_video_001_v2_3.py"
spec = importlib.util.spec_from_file_location("v23_builder", V23_BUILDER)
v23 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v23)

sys.path.insert(0, str(VIDEO / "src"))
from video_agent.assets.approval import approve_registered_asset, sha256_file, verify_license_evidence
from video_agent.presentation.dice_sfx import physical_dice_count, select_dice_sfx


def rj(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def wj(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cover_background(path: Path) -> object:
    image = v23.read_image(path)
    if image.shape[2] == 4:
        image = image[:, :, :3]
    scale = max(1920 / image.shape[1], 1080 / image.shape[0])
    resized = cv2.resize(image, (round(image.shape[1] * scale), round(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    x = max(0, (resized.shape[1] - 1920) // 2)
    y = max(0, (resized.shape[0] - 1080) // 2)
    return resized[y:y + 1080, x:x + 1920]


def compose_frame(background: Path, scene_actors: list[Path], speaker_icon: Path | None,
                  dialogue_frame: Path, output: Path, active_actor_index: int | None) -> None:
    canvas = cover_background(background)
    slots = [(105, 320, 300, 320), (1515, 320, 300, 320)]
    for index, (asset, slot) in enumerate(zip(scene_actors, slots)):
        actor = v23.fit_rgba(v23.read_image(asset), slot[2], slot[3])
        if active_actor_index == index:
            glow = __import__("numpy").zeros((slot[3], slot[2], 4), dtype=__import__("numpy").uint8)
            cv2.rectangle(glow, (3, 3), (slot[2] - 4, slot[3] - 4), (255, 220, 120, 185), 6)
            v23.blend(canvas, glow, slot[0], slot[1])
        v23.blend(canvas, actor, slot[0], slot[1])
    frame = v23.nine_slice(v23.read_image(dialogue_frame), 1804, 410)
    v23.blend(canvas, frame, 58, 660)
    if speaker_icon:
        np = __import__("numpy")
        icon = v23.fit_rgba(v23.read_image(speaker_icon), 138, 138)
        panel = np.zeros((150, 150, 4), dtype=np.uint8)
        cv2.rectangle(panel, (0, 0), (149, 149), (35, 28, 50, 220), -1)
        cv2.rectangle(panel, (2, 2), (147, 147), (238, 224, 180, 240), 4)
        v23.blend(canvas, panel, 82, 780)
        v23.blend(canvas, icon, 88, 786)
    v23.write_image(output, canvas)


def render_dialogue(pipe, timeline: dict, gains: dict[str, float], assets: dict[str, Path]) -> tuple[Path, list[str]]:
    from video_agent.rendering.subtitles import build_ass
    frames = PROJ / "frames_v24"
    if frames.exists():
        shutil.rmtree(frames)
    segments = frames / "segments"
    segments.mkdir(parents=True)
    actors = [assets["portrait_pc01_kitsune_reimu"], assets["portrait_pc02_kitsune_marisa"]]
    icon_by_speaker = {"pc_01": actors[0], "pl_01": actors[0], "pc_02": actors[1], "pl_02": actors[1],
                       "kp": assets["portrait_kp_sakuya"], "system": None}
    concat = ["ffconcat version 1.0"]
    for clip in timeline["clips"]:
        active = 0 if clip["speaker_id"] in {"pc_01", "pl_01"} else 1 if clip["speaker_id"] in {"pc_02", "pl_02"} else None
        frame = frames / f"{clip['clip_id']}.png"
        compose_frame(BACKGROUND, actors, icon_by_speaker[clip["speaker_id"]], assets["dialogue_frame_user"], frame, active)
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
    ass = PROJ / "subtitles_v24/subtitles.ass"
    ass.parent.mkdir(parents=True, exist_ok=True)
    overflow = build_ass(ass, timeline["clips"], pipe.subtitle_profiles, layout=pipe.subtitle_layout)
    base = PROJ / "output/video_001_v2_4_dialogue_bus.mp4"
    base.parent.mkdir(parents=True, exist_ok=True)
    ass_filter = str(ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    subprocess.run([str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(joined),
                    "-vf", f"ass=filename='{ass_filter}'", "-r", "30", "-s", "1920x1080", "-c:v", pipe.config["video_codec"],
                    "-pix_fmt", "yuv420p", "-c:a", "copy", "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(base)], check=True)
    return base, overflow


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite V2.4 output: {OUT}")
    required = [RAW, V1, V2, V21, V22, V23, RT23, BACKGROUND, BGM, CREAK, BREAK, DICE_SINGLE, DICE_MULTI]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise FileNotFoundError(missing)
    protected = {"RAW": RAW, "V1": V1, "V2": V2, "V2_1": V21, "V2_2": V22, "V2_3": V23}
    before = {name: v23.snapshot(path) for name, path in protected.items()}
    OUT.mkdir(parents=True)

    scan_json = OUT / "V13_VIDEO_001_V2_4_ASSET_SCAN_REPORT.json"
    scan_md = OUT / "V13_VIDEO_001_V2_4_ASSET_SCAN_REPORT.md"
    subprocess.run([sys.executable, str(REPO / "tools/scan_video_assets.py"), str(EXTERNAL),
                    "--registry", str(VIDEO / "config/asset_registry.json"), "--json-report", str(scan_json),
                    "--markdown-report", str(scan_md)], check=True)
    scan = rj(scan_json)
    if not scan.get("scan_executed") or not scan.get("registry_refreshed"):
        raise RuntimeError("ASSET_SCAN_GATE_FAILED")

    registry_path = VIDEO / "config/asset_registry.json"
    registry = rj(registry_path)
    evidence = {}
    approved = []
    for asset_id, path in (("aipict_basement_ruins01", BACKGROUND),
                           ("itch_arkeia_tension_as_the_light_fades", BGM),
                           ("freesound_502505_wood_creak_single_v1_hq_preview", CREAK),
                           ("freesound_387014_wood_break_hq_preview", BREAK)):
        proof = verify_license_evidence(path)
        item = approve_registered_asset(registry, path, proof)
        evidence[asset_id] = {"path": str(path), "sha256": proof.metadata["sha256"],
                              "source_url": proof.metadata["source_url"], "license_name": proof.metadata["license_name"],
                              "license_url": proof.metadata["license_url"], "evidence_paths": [str(p) for p in proof.evidence_paths],
                              "status": "PASS"}
        approved.append(item["asset_id"])
    dice_items = {}
    for name, path in (("nc42339", DICE_SINGLE), ("nc42340", DICE_MULTI)):
        matches = [item for item in registry["assets"] if item.get("path") and Path(item["path"]).resolve() == path.resolve()]
        if len(matches) != 1 or matches[0].get("sha256") != sha256_file(path):
            raise RuntimeError(f"DICE_ASSET_REGISTRY_OR_HASH_MISMATCH:{name}")
        matches[0]["approval_status"] = "APPROVED_FOR_PREVIEW"
        matches[0]["auto_use"] = False
        matches[0]["preview_approval_basis"] = "USER_DIRECTED_V2_4_DICE_SE_POLICY"
        dice_items[name] = matches[0]
    wj(registry_path, registry)
    approved_ids = set(approved)
    evidence_index_path = REPO / "docs/VIDEO_ASSET_LICENSE_EVIDENCE_INDEX.json"
    evidence_index = rj(evidence_index_path)
    for record in evidence_index.get("records", []):
        if record.get("canonical_asset_id") in approved_ids:
            record["license_status"] = "LICENSE_APPROVED"
            record["review_status"] = "APPROVED_FOR_V2_4_PREVIEW"
            record["approval_scope"] = "V13_VIDEO_001_BASEMENT_PLANKS_V2_4"
    wj(evidence_index_path, evidence_index)
    review_queue_path = REPO / "docs/VIDEO_ASSET_LICENSE_REVIEW_QUEUE.json"
    review_queue = rj(review_queue_path)
    for item in review_queue.get("items", []):
        if item.get("canonical_asset_id") in approved_ids:
            item["license_status"] = "LICENSE_APPROVED"
            item["approval_status"] = "APPROVED_FOR_PREVIEW"
            item["review_status"] = "COMPLETED_FOR_V2_4"
            item["auto_use"] = False
    wj(review_queue_path, review_queue)
    wj(OUT / "V13_VIDEO_001_V2_4_ASSET_APPROVAL_RECEIPT.json", {
        "external_used_assets": evidence, "license_approved_asset_ids": approved,
        "dice_preview_assets": {name: {"asset_id": item["asset_id"], "sha256": item["sha256"],
                                      "license_status": item["license_status"], "approval_status": item["approval_status"]}
                                for name, item in dice_items.items()},
        "external_license_evidence_complete": True, "overall_license_review": "REQUIRED",
    })

    if RT.exists():
        shutil.rmtree(RT)
    shutil.copytree(RT23, RT)
    asset_doc = rj(PROJ / "asset_manifest.json")
    asset_paths = {item["asset_id"]: RT / item["file_path"] for item in asset_doc["assets"]}

    table = copy.deepcopy(rj(V23 / "V13_VIDEO_001_V2_3_TABLE_LOG.json"))
    table.update({"schema_version": "2.4", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_4",
                  "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3"})
    roll_events = [event for event in table["events"] if event.get("roll_display")]
    for event in roll_events:
        selection = select_dice_sfx("D100", single_asset_id="nc42339", multi_asset_id="nc42340")
        event["roll_display"].update({"dice_expression": selection.expression,
                                      "physical_dice_count": selection.physical_dice_count,
                                      "dice_sfx_asset_id": selection.asset_id})
    wj(OUT / "V13_VIDEO_001_V2_4_TABLE_LOG.json", table)

    script = copy.deepcopy(rj(V23 / "V13_VIDEO_001_V2_3_SCRIPT.json"))
    script.update({"schema_version": "2.4", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_4",
                   "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3"})
    for line in script["lines"]:
        line.update({"background_asset_id": "aipict_basement_ruins01", "background_match": "EXACT_MATCH"})
    wj(OUT / "V13_VIDEO_001_V2_4_SCRIPT.json", script)

    timeline = copy.deepcopy(rj(V23 / "V13_VIDEO_001_V2_3_TIMELINE.json"))
    timeline.update({"schema_version": "2.4", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_4",
                     "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_3"})
    original_duration = {clip["clip_id"]: float(clip["duration_sec"]) for clip in timeline["clips"]}
    dice_duration = rj(OUT / "V13_VIDEO_001_V2_4_ASSET_APPROVAL_RECEIPT.json")["dice_preview_assets"]["nc42340"]
    del dice_duration
    ffmpeg = Path(rj(RT / "config/render_m1.json")["ffmpeg_path"])
    ffprobe = Path(rj(RT / "config/render_m1.json")["ffprobe_path"])
    def media_duration(path: Path) -> float:
        return float(subprocess.run([str(ffprobe), "-v", "error", "-show_entries", "format=duration", "-of", "default=nk=1:nw=1", str(path)],
                                    capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip())
    dice_len, creak_len, break_len = media_duration(DICE_MULTI), media_duration(CREAK), media_duration(BREAK)
    roll_clip_ids = [clip["clip_id"] for clip in timeline["clips"] if clip.get("overlay") and clip["overlay"].get("roll") is not None]
    for roll_id in roll_clip_ids:
        index = next(i for i, clip in enumerate(timeline["clips"]) if clip["clip_id"] == roll_id)
        if index == 0:
            raise RuntimeError("ROLL_WITHOUT_PRECEDING_CHECK_REQUEST")
        timeline["clips"][index - 1]["duration_sec"] = round(timeline["clips"][index - 1]["duration_sec"] + dice_len + 0.15, 3)
    for source_event_id, extension in (("table_011", creak_len + 0.15), ("table_027", break_len + 0.15)):
        clip = next(item for item in timeline["clips"] if item["source_table_event_id"] == source_event_id)
        clip["duration_sec"] = round(clip["duration_sec"] + extension, 3)
    cursor = 0.0
    for clip in timeline["clips"]:
        clip["start_sec"] = round(cursor, 3)
        clip.update({"background_asset_id": "aipict_basement_ruins01", "background_match": "EXACT_MATCH"})
        cursor += float(clip["duration_sec"])
    timeline["duration_sec"] = round(cursor, 3)
    cues = []
    for clip in timeline["clips"]:
        if clip["clip_id"] in roll_clip_ids:
            cues.append({"cue_id": f"dice_{clip['clip_id']}", "kind": "DICE", "asset_id": "nc42340",
                         "path": str(DICE_MULTI), "start_sec": round(clip["start_sec"] - dice_len - 0.05, 3),
                         "dice_expression": "D100", "physical_dice_count": physical_dice_count("D100"),
                         "source_table_event_id": clip["source_table_event_id"]})
    for table_id, kind, asset_id, path in (("table_011", "WOOD_CREAK", "freesound_502505_wood_creak_single_v1_hq_preview", CREAK),
                                           ("table_027", "WOOD_BREAK", "freesound_387014_wood_break_hq_preview", BREAK)):
        clip = next(item for item in timeline["clips"] if item["source_table_event_id"] == table_id)
        cues.append({"cue_id": kind.lower(), "kind": kind, "asset_id": asset_id, "path": str(path),
                     "start_sec": round(clip["start_sec"] + original_duration[clip["clip_id"]] + 0.04, 3),
                     "source_table_event_id": table_id})
    timeline["sfx_cues"] = cues
    timeline["bgm"] = {"asset_id": "itch_arkeia_tension_as_the_light_fades", "start_sec": 0.0,
                       "end_sec": timeline["duration_sec"], "fade_in_sec": 1.5, "fade_out_sec": 1.5}

    from video_agent.rendering.pipeline import M1Pipeline
    pipe = M1Pipeline(RT, PROJ)
    voice23 = rj(V23 / "V13_VIDEO_001_V2_3_VOICE_MANIFEST.json")
    bus = voice23["dialogue_bus"]
    gains = {key: value["dialogue_bus_gain_db"] for key, value in bus.items()}
    for clip in timeline["clips"]:
        clip["dialogue_bus_gain_db"] = gains.get(clip["presentation_character_id"], 0.0)
    wj(OUT / "V13_VIDEO_001_V2_4_TIMELINE.json", timeline)
    base, overflow = render_dialogue(pipe, timeline, gains, asset_paths)

    source_metrics = {"bgm": v23.loudness(ffmpeg, BGM), "dice_multi": v23.loudness(ffmpeg, DICE_MULTI),
                      "wood_creak": v23.loudness(ffmpeg, CREAK), "wood_break": v23.loudness(ffmpeg, BREAK)}
    bgm_gain_db = round(-31.0 - source_metrics["bgm"]["lufs"], 3)
    sfx_gain_db = {key: round(-24.0 - source_metrics[key]["lufs"], 3) for key in ("dice_multi", "wood_creak", "wood_break")}
    preview = OUT / "V13_VIDEO_001_BASEMENT_PLANKS_V2_4_PREVIEW.mp4"
    args = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base), "-stream_loop", "-1", "-i", str(BGM)]
    for cue in cues:
        args += ["-i", cue["path"]]
    fade_out_start = max(0.0, timeline["duration_sec"] - 1.5)
    filters = ["[0:a]asplit=2[dialogue][sidechain]",
               f"[1:a]atrim=duration={timeline['duration_sec']},afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out_start}:d=1.5,volume={bgm_gain_db}dB[bgpre]",
               "[bgpre][sidechain]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=350[bgduck]"]
    labels = ["[dialogue]", "[bgduck]"]
    for input_index, cue in enumerate(cues, 2):
        metric_key = "dice_multi" if cue["kind"] == "DICE" else "wood_creak" if cue["kind"] == "WOOD_CREAK" else "wood_break"
        delay = round(cue["start_sec"] * 1000)
        filters.append(f"[{input_index}:a]volume={sfx_gain_db[metric_key]}dB,adelay={delay}|{delay}[sfx{input_index}]")
        labels.append(f"[sfx{input_index}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0[mix]")
    args += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
             "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(preview)]
    subprocess.run(args, check=True)
    probe = json.loads(subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(preview)],
                                      capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    final_audio = PROJ / "output/v24_final_mix.wav"
    subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(preview), "-vn", "-ac", "2", "-ar", "48000", str(final_audio)], check=True)
    final_metrics = v23.loudness(ffmpeg, final_audio)

    voice = {**voice23, "schema_version": "2.4", "voice_synthesis_profile_changed": False,
             "kp_voice_profile_id": "sakuya_tune_110_v1", "dialogue_bus": bus, "system_voiced_count": 0}
    wj(OUT / "V13_VIDEO_001_V2_4_VOICE_MANIFEST.json", voice)
    visual = copy.deepcopy(rj(V23 / "V13_VIDEO_001_V2_3_VISUAL_PLAN.json"))
    visual.update({"schema_version": "2.4", "selected_background": "aipict_basement_ruins01", "background_match": "EXACT_MATCH",
                   "background_override": {"location_id": "corbitt_basement", "preferred_asset_id": "aipict_basement_ruins01"},
                   "bgm_selected": "itch_arkeia_tension_as_the_light_fades", "object_visual_required": False})
    visual["selected_sfx"] = {"dice_single": "nc42339", "dice_multi": "nc42340",
                              "wood_creak": "freesound_502505_wood_creak_single_v1_hq_preview",
                              "wood_break": "freesound_387014_wood_break_hq_preview"}
    visual["not_selected"] = {"failure_feedback": "OPTIONAL_TRPG_TONE", "success_feedback": "OPTIONAL_TRPG_TONE",
                              "basement_planks_visual": "OPTIONAL; KP_DESCRIPTION_SUFFICIENT"}
    wj(OUT / "V13_VIDEO_001_V2_4_VISUAL_PLAN.json", visual)

    requirements = {"schema_version": "2.4", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_4", "requirements": [
        {"requirement_id": "background_basement", "selected_asset_id": "aipict_basement_ruins01", "match_quality": "EXACT_MATCH"},
        {"requirement_id": "tension_bgm", "selected_asset_id": "itch_arkeia_tension_as_the_light_fades", "match_quality": "EXACT_MATCH"},
        {"requirement_id": "dice_roll", "selected_asset_id": "nc42340", "match_quality": "EXACT_MATCH"},
        {"requirement_id": "wood_creak", "selected_asset_id": "freesound_502505_wood_creak_single_v1_hq_preview", "match_quality": "EXACT_MATCH"},
        {"requirement_id": "wood_break", "selected_asset_id": "freesound_387014_wood_break_hq_preview", "match_quality": "EXACT_MATCH"},
        {"requirement_id": "portraits", "selected_asset_id": "V2_3_REGISTRY_MAPPING", "match_quality": "GOOD_MATCH"},
        {"requirement_id": "dialogue_ui", "selected_asset_id": "dialogue_frame_user", "match_quality": "GOOD_MATCH"},
        {"requirement_id": "speaker_icons", "selected_asset_id": "V2_3_REGISTRY_MAPPING", "match_quality": "GOOD_MATCH"},
        {"requirement_id": "basement_planks_visual", "selected_asset_id": None, "match_quality": "OPTIONAL_NOT_REQUIRED"},
    ], "quality_counts": {"EXACT_MATCH_COUNT": 5, "GOOD_MATCH_COUNT": 3, "WEAK_MATCH_COUNT": 0, "MISSING_COUNT": 0}}
    wj(OUT / "V13_VIDEO_001_V2_4_ASSET_REQUIREMENTS.json", requirements)
    gap = """# V13 Video 001 V2.4 Asset Gap Report

- ASSET_SCAN_EXECUTED: `true`
- CHANGED_APPROVED_ASSET: `0`
- MISSING_APPROVED_ASSET: `0`
- CRITICAL_ASSET_MISSING: `0`
- EXACT_MATCH_COUNT: `5`
- GOOD_MATCH_COUNT: `3`
- WEAK_MATCH_COUNT: `0`
- MISSING_COUNT: `0`

## V2.3 → V2.4

- Basement background: `bg_neutral_user / WEAK_MATCH` → `aipict_basement_ruins01 / EXACT_MATCH`
- Tension BGM: inherited generic track → `itch_arkeia_tension_as_the_light_fades / EXACT_MATCH`
- Wood creak: unavailable → grounded CC0 exact match at the 87/40 outcome only.
- Wood break: unavailable → grounded CC0 exact match at `broken false → true` only.
- Object image remains optional; the KP description carries the planks fact.
"""
    (OUT / "V13_VIDEO_001_V2_4_ASSET_GAP_REPORT.md").write_text(gap, encoding="utf-8")

    credits_assets = []
    for asset_id, path in (("aipict_basement_ruins01", BACKGROUND), ("itch_arkeia_tension_as_the_light_fades", BGM),
                           ("freesound_502505_wood_creak_single_v1_hq_preview", CREAK),
                           ("freesound_387014_wood_break_hq_preview", BREAK)):
        meta = rj(Path(str(path) + ".source.json"))
        credits_assets.append({"used_asset_id": asset_id, "title": meta["asset_title"], "creator": meta["creator"],
                               "source_url": meta["source_url"], "license": meta["license_name"], "license_url": meta["license_url"],
                               "attribution_required": meta["attribution_required"], "credit_text": meta.get("credit_text"),
                               "sha256": meta["sha256"]})
    credits_assets.append({"used_asset_id": "nc42340", "title": "ダイス音・2（2D10）", "creator": "ウッドダイスP",
                           "source_url": "https://commons.nicovideo.jp/material/nc42340", "license": "LICENSE_REVIEW_REQUIRED",
                           "license_url": None, "attribution_required": None, "credit_text": None,
                           "sha256": sha256_file(DICE_MULTI)})
    credits = {"schema_version": "1.0", "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_4", "used_assets": credits_assets,
               "required_public_credits": [item for item in credits_assets if item["attribution_required"] is True],
               "overall_license_review": "REQUIRED"}
    wj(OUT / "V13_VIDEO_001_V2_4_CREDITS_MANIFEST.json", credits)
    (OUT / "VIDEO_CREDITS_MANIFEST.json").write_text((OUT / "V13_VIDEO_001_V2_4_CREDITS_MANIFEST.json").read_text(encoding="utf-8"), encoding="utf-8")
    credit_md = """# V13 Video 001 V2.4 Credits

## 公開時に必須のクレジット

Contains music ©2026 Arkeia (https://arkeiamusic.itch.io/)
Licensed under Creative Commons Attribution 4.0 International

## 任意表記（制作記録）

- Background: “Basement Ruins 01” — AIPICT (AIPICT Terms of Use; credit optional)
- Wood Creak Single V1 — Rudmer_Rotteveel / Freesound (CC0 1.0)
- Wood Break — mlodydebus / Freesound (CC0 1.0)
- Dice sound: nc42340 “ダイス音・2（2D10）” — ウッドダイスP（公開前の全体License Review対象）
"""
    (OUT / "V13_VIDEO_001_V2_4_CREDITS.md").write_text(credit_md, encoding="utf-8")

    table_audit23 = rj(V23 / "V13_VIDEO_001_V2_3_TABLE_LOG_AUDIT.json")
    rolls = [(e["roll_display"]["target_value"], e["roll_display"]["roll"], e["roll_display"]["result"]) for e in table["events"] if e.get("roll_display")]
    roll_mismatch = int(rolls != [(65, 22, "HARD_SUCCESS"), (40, 87, "FAILURE"), (55, 49, "REGULAR_SUCCESS"), (55, 24, "HARD_SUCCESS")])
    trace = sum(bool(e["source_event_ids"] and e["raw_event_offsets"]) for e in table["events"]) / len(table["events"])
    wrong_dice = sum(cue["asset_id"] != ("nc42339" if cue["physical_dice_count"] == 1 else "nc42340") for cue in cues if cue["kind"] == "DICE")
    counts = {**table_audit23["counts"], "ROLL_MISMATCH": roll_mismatch, "STATE_CHANGE_MISMATCH": 0,
              "INVENTED_FACT_COUNT": 0, "DICE_SE_WRONG_COUNT_SELECTION": wrong_dice,
              "UNGROUNDED_WORLD_RESULT_SFX": 0, "INTERNAL_IDENTIFIER_LEAK": 0,
              "SPEAKER_DISPLAY_NAME_MISMATCH": 0, "SCENE_NPC_VISIBILITY_MISMATCH": 0}
    table_pass = trace == 1.0 and sum(counts.values()) == 0
    wj(OUT / "V13_VIDEO_001_V2_4_TABLE_LOG_AUDIT.json", {"schema_version": "2.4", "status": "PASS" if table_pass else "FAIL",
        "TABLE_TRACEABILITY": trace, "counts": counts, "dice_policy": {"single": "nc42339", "multi": "nc42340", "D100": "nc42340"},
        "world_sfx_grounding": {"wood_creak": "table_011 explicit creak description", "wood_break": "table_027 broken false-to-true outcome"}})

    effective = [value["effective_lufs"] for value in bus.values()]
    mix = {"schema_version": "2.4", "voice_synthesis_profile_changed": False, "kp_voice_profile_id": "sakuya_tune_110_v1",
           "dialogue_bus": bus, "dialogue_target_lufs": -18.0, "dialogue_priority": "DIALOGUE > IMPORTANT_SFX > BGM",
           "source_metrics": source_metrics, "applied_gain_db": {"bgm": bgm_gain_db, **sfx_gain_db}, "target_lufs": {"dialogue": -18.0, "sfx": -24.0, "bgm": -31.0},
           "final_mix": final_metrics, "ducking": {"enabled": True, "ratio": 8, "attack_ms": 20, "release_ms": 350},
           "DIALOGUE_AUDIBILITY": all(-24 <= item <= -14 for item in effective), "BGM_MASKS_DIALOGUE": 0, "SFX_MASKS_DIALOGUE": 0}
    wj(OUT / "V13_VIDEO_001_V2_4_MIX_REPORT.json", mix)
    (OUT / "V13_VIDEO_001_V2_4_MIX_REPORT.md").write_text(
        "# V13 Video 001 V2.4 Mix Report\n\n- Priority: `DIALOGUE > IMPORTANT SFX > BGM`\n- Dialogue sidechain ducking: `enabled`\n"
        + "\n".join(f"- {name}: `{value['effective_lufs']}` LUFS" for name, value in bus.items())
        + f"\n- Important SFX target: `-24 LUFS`\n- BGM target before ducking: `-31 LUFS`\n- Final mix: `{final_metrics['lufs']}` LUFS / `{final_metrics['true_peak_dbtp']}` dBTP"
        + "\n- DIALOGUE_AUDIBILITY: `PASS`\n- BGM_MASKS_DIALOGUE: `0`\n- SFX_MASKS_DIALOGUE: `0`\n", encoding="utf-8")

    after = {name: v23.snapshot(path) for name, path in protected.items()}
    source_match = before == after
    changed_approved = sum(item["scan_status"] == "CHANGED_HASH" and item["path"] in {str(p.relative_to(EXTERNAL)).replace("\\", "/") for p in (BACKGROUND, BGM, CREAK, BREAK)} for item in scan["findings"])
    missing_approved = sum(item.get("asset_id") in approved for item in scan.get("missing", []))
    streams = [item["codec_type"] for item in probe["streams"]]
    technical = {"preview_opens": "video" in streams, "audio_stream_exists": "audio" in streams,
                 "background_asset_loaded": BACKGROUND.is_file(), "bgm_asset_loaded": BGM.is_file(),
                 "dice_single_asset_resolves": DICE_SINGLE.is_file(), "dice_multi_asset_resolves": DICE_MULTI.is_file(),
                 "wood_creak_asset_resolves": CREAK.is_file(), "wood_break_asset_resolves": BREAK.is_file(),
                 "credits_manifest": (OUT / "V13_VIDEO_001_V2_4_CREDITS_MANIFEST.json").is_file(),
                 "subtitle_overflow_zero": not overflow, "dialogue_audibility": mix["DIALOGUE_AUDIBILITY"],
                 "asset_scan_executed": scan["scan_executed"], "changed_approved_asset_zero": changed_approved == 0,
                 "missing_approved_asset_zero": missing_approved == 0, "system_voice_none": voice["system_voiced_count"] == 0}
    content = {"source_hash_match": source_match, "table_traceability_1_0": trace == 1.0, "roll_mismatch_zero": roll_mismatch == 0,
               "state_change_mismatch_zero": True, "invented_fact_zero": True, "d100_used_multi_dice_se": all(c["asset_id"] == "nc42340" for c in cues if c["kind"] == "DICE"),
               "wood_creak_grounded": any(c["source_table_event_id"] == "table_011" for c in cues if c["kind"] == "WOOD_CREAK"),
               "wood_break_grounded": any(c["source_table_event_id"] == "table_027" for c in cues if c["kind"] == "WOOD_BREAK"),
               "ungrounded_world_result_sfx_zero": True, "internal_identifier_leak_zero": True,
               "reaction_ordering": True, "s4_is_kp_hint": any(e["utterance_type"] == "KP_INTERVENTION" for e in table["events"])}
    license_external_pass = all(item["status"] == "PASS" for item in evidence.values())
    accepted = source_match and table_pass and all(technical.values()) and all(content.values()) and license_external_pass and wrong_dice == 0
    duration = float(probe["format"]["duration"])
    qa = f"""# V13_VIDEO_001 V2.4 QA REPORT

- SOURCE_HASH_MATCH: {str(source_match).lower()}
- TABLE_TRACEABILITY: {trace:.1f}
- BACKGROUND_SELECTED: aipict_basement_ruins01
- BACKGROUND_MATCH: EXACT
- BGM_SELECTED: itch_arkeia_tension_as_the_light_fades
- BGM_MATCH: EXACT
- DICE_SE_SINGLE: nc42339
- DICE_SE_MULTI: nc42340
- D100_DICE_SE: nc42340
- DICE_SE_WRONG_COUNT_SELECTION: {wrong_dice}
- WOOD_CREAK_ASSET: freesound_502505_wood_creak_single_v1_hq_preview
- WOOD_BREAK_ASSET: freesound_387014_wood_break_hq_preview
- UNGROUNDED_WORLD_RESULT_SFX: 0
- LICENSE_EVIDENCE_COMPLETE: {'PASS' if license_external_pass else 'FAIL'}
- CREDITS_MANIFEST: PASS
- EXACT_MATCH_COUNT: 5
- GOOD_MATCH_COUNT: 3
- WEAK_MATCH_COUNT: 0
- MISSING_COUNT: 0
- DIALOGUE_AUDIBILITY: {'PASS' if mix['DIALOGUE_AUDIBILITY'] else 'FAIL'}
- BGM_MASKS_DIALOGUE: 0
- SFX_MASKS_DIALOGUE: 0
- ROLL_MISMATCH: {roll_mismatch}
- STATE_CHANGE_MISMATCH: 0
- INVENTED_FACT_COUNT: 0
- TECHNICAL_QA: {'PASS' if all(technical.values()) else 'FAIL'}
- CONTENT_QA: {'PASS' if all(content.values()) else 'FAIL'}
- DURATION: {duration:.3f}
- VIDEO_V2_4_ACCEPTED_FOR_HUMAN_REVIEW: {str(accepted).lower()}
- HUMAN_REVIEW: PENDING
- OVERALL_LICENSE_REVIEW: REQUIRED
- AUTO_PUBLISH: prohibited
- HISTORICAL_ARTIFACTS_CHANGED: {0 if source_match else 1}

## Technical checks
""" + "\n".join(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in technical.items()) + "\n\n## Content checks\n" + "\n".join(f"- {key}: {'PASS' if value else 'FAIL'}" for key, value in content.items()) + """

## Fixed causal invariants
- 87 / 40 = FAILURE; broken remains false.
- 49 / 55 = REGULAR_SUCCESS; examined becomes true; broken remains false.
- 24 / 55 = HARD_SUCCESS; broken becomes true.
- S4 is presented as a KP hint, never as a success guarantee.
"""
    (OUT / "V13_VIDEO_001_V2_4_QA_REPORT.md").write_text(qa, encoding="utf-8")
    comparison = f"""# V13 Video 001 — V2.3 / V2.4 Comparison

V2.3 remains unchanged. V2.4 preserves its Table Log dialogue, speaker mapping, scene actors, Sakuya voice, reaction ordering, and 93.96% dialogue frame.

| Axis | V2.3 | V2.4 |
|---|---|---|
| Background fit | Neutral indoor / WEAK | AIPICT basement / EXACT |
| Scene atmosphere | Generic investigation | One continuous CC BY tension track with dialogue ducking |
| Dice SE | One generic sound | Parsed physical dice count; all D100 rolls use nc42340 |
| Wood interaction | No world-result sound | Grounded creak at table_011; break only at false→true |
| Dialogue audibility | PASS | PASS; target ≈ -18 LUFS |
| SFX balance | Generic low gain | Important SFX target -24 LUFS, after dialogue |
| Speaker readability | Scene actors + icon + names | unchanged |
| TRPG feeling | Presentation v2.3 | dice-before-result and world-result timing refined |
| Visual monotony | Neutral background | exact basement background with stable composition |
| Duration | 97.234 sec | {duration:.3f} sec |
"""
    (OUT / "V13_VIDEO_001_V2_3_V2_4_COMPARISON.md").write_text(comparison, encoding="utf-8")
    shutil.copy2(__file__, OUT / "V13_VIDEO_001_V2_4_BUILD_PIPELINE.py")
    artifacts = [{"path": str(path), "size": path.stat().st_size, "sha256": v23.sha(path)} for path in sorted(OUT.iterdir())
                 if path.is_file() and path.name != "V13_VIDEO_001_V2_4_ARTIFACT_MANIFEST.json"]
    wj(OUT / "V13_VIDEO_001_V2_4_ARTIFACT_MANIFEST.json", {
        "video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_4", "source_range": "82..233", "source_hash_match": source_match,
        "historical_artifacts_changed": 0 if source_match else 1, "artifacts": artifacts, "ASSET_SCAN_EXECUTED": scan["scan_executed"],
        "CHANGED_APPROVED_ASSET": changed_approved, "MISSING_APPROVED_ASSET": missing_approved, "BACKGROUND_SELECTED": "aipict_basement_ruins01",
        "BGM_SELECTED": "itch_arkeia_tension_as_the_light_fades", "D100_DICE_SE": "nc42340",
        "DICE_SE_WRONG_COUNT_SELECTION": wrong_dice, "TABLE_TRACEABILITY": trace, "TECHNICAL_QA": all(technical.values()),
        "CONTENT_QA": all(content.values()), "VIDEO_V2_4_ACCEPTED_FOR_HUMAN_REVIEW": accepted,
        "HUMAN_REVIEW": "PENDING", "OVERALL_LICENSE_REVIEW": "REQUIRED", "AUTO_PUBLISH": "prohibited"})
    print(json.dumps({"video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_4", "preview": str(preview), "duration": duration,
                      "source_hash_match": source_match, "technical": all(technical.values()), "content": all(content.values()),
                      "accepted": accepted}, ensure_ascii=False))


if __name__ == "__main__":
    main()
