from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
RAW = Path(r"F:\制作物\その3\evaluation-v2\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
BASE = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
V26 = BASE / "video_001_basement_planks_v2_6"
OUT = BASE / "video_001_basement_planks_v2_8"
RT26 = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_6_RENDER_WORKSPACE")
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_8_RENDER_WORKSPACE")
PROJ = RT / "project"
VIDEO_ID = "V13_VIDEO_001_BASEMENT_PLANKS_V2_8"

spec = importlib.util.spec_from_file_location("v26_builder", VIDEO / "tools/build_v13_video_001_v2_6.py")
v26 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v26)

sys.path.insert(0, str(VIDEO / "src"))
from video_agent.presentation.dialogue_ui import (
    DEFAULT_NAME_FONT_SIZE,
    audit_dialogue_ui,
    fit_name_font_size,
    layout_for_canvas,
    wrap_dialogue,
)
from video_agent.presentation.replay_summary import (
    audit_summary_bridges,
    audit_summary_plan,
    classify_replay_events,
    make_summary_block,
    make_summary_bridge,
)
from video_agent.rendering.pipeline import M1Pipeline


def rj(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def wj(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def snapshot(path: Path) -> dict:
    return v26.v25.v23.snapshot(path)


def summary_specs(events: list[dict]) -> list[dict]:
    specs = [
        {
            "id": "summary_ground_floor",
            "start": 147, "end": 171,
            "text": "一階では、食器棚、隠し通路、地下室の扉、配電盤を調べました。",
            "voice_text": "いっかいでは、しょっきだな、かくしつうろ、ちかしつのとびら、はいでんばんを、しらべました。",
            "locations": ["corbitt_ground_floor"],
            "claims": [
                {"claim_id": "cupboard", "claim_type": "ACTION", "evidence_offsets": [149],
                 "matches": {"selected_action": "search", "target": "storage_room1_cupboard"}},
                {"claim_id": "hidden", "claim_type": "ACTION", "evidence_offsets": [152, 157],
                 "matches": {"selected_action": "search", "target": "hidden_passage"}},
                {"claim_id": "breaker", "claim_type": "ACTION", "evidence_offsets": [154, 163],
                 "matches": {"selected_action": "search", "target": "kitchen_breaker_box"}},
                {"claim_id": "door", "claim_type": "ACTION", "evidence_offsets": [166, 168, 171],
                 "matches": {"target": "basement_door"}},
            ],
        },
        {
            "id": "summary_upper_floor",
            "start": 172, "end": 223,
            "text": "上階へ移り、予備寝室のベッド、浴室、主寝室の本棚を調べました。",
            "voice_text": "じょうかいへうつり、よびしんしつのべっど、よくしつ、しゅしんしつのほんだなを、しらべました。",
            "locations": ["corbitt_ground_floor", "corbitt_upper_floor"],
            "claims": [
                {"claim_id": "move_upper", "claim_type": "LOCATION", "evidence_offsets": [173],
                 "matches": {"event_type": "LOCATION_CHANGE", "target": "corbitt_upper_floor"}},
                {"claim_id": "bed", "claim_type": "ACTION", "evidence_offsets": [175, 185, 188, 217],
                 "matches": {"selected_action": "search", "target": "spare_bedroom_bed"}},
                {"claim_id": "bath", "claim_type": "ACTION", "evidence_offsets": [190, 198, 201, 206, 220],
                 "matches": {"selected_action": "search", "target": "bathroom_bathtub"}},
                {"claim_id": "books", "claim_type": "ACTION", "evidence_offsets": [177, 203, 214, 223],
                 "matches": {"selected_action": "search", "target": "master_bedroom_bookshelf"}},
            ],
        },
        {
            "id": "summary_return_basement",
            "start": 224, "end": 230,
            "text": "その後は上階と一階を行き来しました。",
            "voice_text": "そのごは、じょうかいと、いっかいをいききしました。",
            "locations": ["corbitt_upper_floor", "corbitt_ground_floor"],
            "claims": [
                {"claim_id": "down", "claim_type": "LOCATION", "evidence_offsets": [225, 229],
                 "matches": {"event_type": "LOCATION_CHANGE", "target": "corbitt_ground_floor"}},
                {"claim_id": "up", "claim_type": "LOCATION", "evidence_offsets": [227],
                 "matches": {"event_type": "LOCATION_CHANGE", "target": "corbitt_upper_floor"}},
            ],
        },
    ]
    return [make_summary_block(item["id"], events, start=item["start"], end=item["end"],
                               text=item["text"], locations=item["locations"], claims=item["claims"])
            | {"voice_text": item["voice_text"]} for item in specs]


def bridge_specs(events: list[dict]) -> list[dict]:
    return [
        make_summary_bridge(
            "summary_entry_bridge", events, bridge_type="SUMMARY_ENTRY_BRIDGE",
            text="板の状態を確認しましたが、その場では突破せず、いったん地下室を離れて一階へ移ります。",
            voice_text="いたのじょうたいを、かくにんしましたが、そのばでは、とっぱせず、いったん、ちかしつをはなれて、いっかいへうつります。",
            evidence_offsets=[144, 146], from_location="corbitt_basement", to_location="corbitt_ground_floor",
            claims=[
                {"claim_id": "planks_examined", "claim_type": "STATE", "evidence_offsets": [144],
                 "matches": {"state_after.flags.basement_planks_examined": True}},
                {"claim_id": "planks_not_broken", "claim_type": "STATE", "evidence_offsets": [144],
                 "matches": {"state_after.flags.basement_planks_broken": False}},
                {"claim_id": "leave_basement", "claim_type": "LOCATION", "evidence_offsets": [146],
                 "matches": {"event_type": "LOCATION_CHANGE", "target": "corbitt_ground_floor"}},
            ],
        ),
        make_summary_bridge(
            "summary_exit_bridge", events, bridge_type="SUMMARY_EXIT_BRIDGE",
            text="一階と上階を調べたのち、再び地下室へ戻ります。",
            voice_text="いっかいと、じょうかいをしらべたのち、ふたたび、ちかしつへもどります。",
            evidence_offsets=[149, 175, 231], from_location="corbitt_ground_floor", to_location="corbitt_basement",
            claims=[
                {"claim_id": "ground_floor_search", "claim_type": "ACTION", "evidence_offsets": [149],
                 "matches": {"selected_action": "search", "target": "storage_room1_cupboard"}},
                {"claim_id": "upper_floor_search", "claim_type": "ACTION", "evidence_offsets": [175],
                 "matches": {"selected_action": "search", "target": "spare_bedroom_bed"}},
                {"claim_id": "return_basement", "claim_type": "LOCATION", "evidence_offsets": [231],
                 "matches": {"event_type": "LOCATION_CHANGE", "target": "corbitt_basement"}},
            ],
        ),
    ]


def make_table_event(block: dict, index: int, template: dict) -> dict:
    row = copy.deepcopy(template)
    row.update({
        "table_event_id": f"summary_table_{index:03d}",
        "source_event_ids": block["source_event_ids"], "raw_event_offsets": block["raw_event_offsets"],
        "speaker_class": "KP", "speaker_id": "kp", "utterance_type": "REPLAY_SUMMARY",
        "visible_text": block["text"], "spoken_text": block["voice_text"],
        "visible_location": None, "visible_object": None, "roll_display": None,
        "truth_class": "FACT_SUMMARY", "transformation_rule": "REPLAY_SUMMARY_LAYER_V1",
        "visual_state": block["summary_block_id"].upper(), "reaction_phase": None,
        "resolved_display_name": "KP", "presentation_character": "sakuya",
        "speaker_icon_asset_id": "portrait_kp_sakuya",
    })
    row["scene_state"].update({"current_location": "corbitt_house_interior",
                               "source_event_ids": block["source_event_ids"]})
    return row


def make_script_line(block: dict, index: int, template: dict) -> dict:
    line = copy.deepcopy(template)
    line.update({
        "line_id": f"summary_line_{index:03d}", "source_table_event_id": f"summary_table_{index:03d}",
        "source_event_ids": block["source_event_ids"], "raw_event_offsets": block["raw_event_offsets"],
        "speaker_class": "KP", "speaker_id": "kp", "resolved_display_name": "KP",
        "text": block["text"], "voice_text": block["voice_text"],
        "event_type": "REPLAY_SUMMARY", "truth_class": "FACT_SUMMARY",
        "visual_state": block["summary_block_id"].upper(), "background_asset_id": "bg_neutral_user",
        "required_location": None, "presentation_mode": "VOICED", "fixed_duration_sec": 4.2,
    })
    line["scene_state"].update({"current_location": "corbitt_house_interior",
                                "source_event_ids": block["source_event_ids"]})
    return line


def make_bridge_table_event(bridge: dict, template: dict) -> dict:
    row = copy.deepcopy(template)
    kind = "entry" if bridge["render_mode"] == "SUMMARY_ENTRY_BRIDGE" else "exit"
    row.update({
        "table_event_id": f"summary_{kind}_bridge_table",
        "source_event_ids": bridge["source_event_ids"], "raw_event_offsets": bridge["raw_event_offsets"],
        "speaker_class": "KP", "speaker_id": "kp", "utterance_type": bridge["render_mode"],
        "visible_text": bridge["text"], "spoken_text": bridge["voice_text"],
        "visible_location": bridge["to_location"], "visible_object": None, "roll_display": None,
        "truth_class": "FACT_BRIDGE", "reason_class": bridge["reason_class"],
        "transformation_rule": "REPLAY_SUMMARY_BRIDGE_V1",
        "visual_state": bridge["bridge_id"].upper(), "reaction_phase": None,
        "resolved_display_name": "KP", "presentation_character": "sakuya",
        "speaker_icon_asset_id": "portrait_kp_sakuya",
    })
    row["scene_state"].update({"current_location": bridge["to_location"],
                               "source_event_ids": bridge["source_event_ids"]})
    return row


def make_bridge_script_line(bridge: dict, template: dict) -> dict:
    line = copy.deepcopy(template)
    kind = "entry" if bridge["render_mode"] == "SUMMARY_ENTRY_BRIDGE" else "exit"
    line.update({
        "line_id": f"summary_{kind}_bridge_line", "source_table_event_id": f"summary_{kind}_bridge_table",
        "source_event_ids": bridge["source_event_ids"], "raw_event_offsets": bridge["raw_event_offsets"],
        "speaker_class": "KP", "speaker_id": "kp", "resolved_display_name": "KP",
        "text": bridge["text"], "voice_text": bridge["voice_text"],
        "event_type": bridge["render_mode"], "truth_class": "FACT_BRIDGE",
        "reason_class": bridge["reason_class"], "visual_state": bridge["bridge_id"].upper(),
        "background_asset_id": "bg_neutral_user", "required_location": bridge["to_location"],
        "presentation_mode": "VOICED", "fixed_duration_sec": 4.2,
    })
    line["scene_state"].update({"current_location": bridge["to_location"],
                                "source_event_ids": bridge["source_event_ids"]})
    return line


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")
    protected = {"RAW": RAW}
    for path in BASE.iterdir():
        if path.is_dir() and path.name != OUT.name:
            protected[path.name] = path
    before = {name: snapshot(path) for name, path in protected.items()}
    OUT.mkdir(parents=True)
    if RT.exists():
        shutil.rmtree(RT)
    shutil.copytree(RT26, RT)

    raw_events = rj(RAW / "unified-event-log.json")
    source_events = [event for event in raw_events if 82 <= int(event.get("raw_event_offset", -1)) <= 233]
    classified = classify_replay_events(
        source_events,
        full_ranges=[(82, 145), (232, 233)],
        summary_ranges=[(147, 231)],
        omit_event_types={"ACTION_BLOCKED", "ACTION_AVAILABILITY_CHECKED"},
        bridge_offsets={146: "SUMMARY_ENTRY_BRIDGE", 231: "SUMMARY_EXIT_BRIDGE"},
    )
    blocks = summary_specs(source_events)
    bridges = bridge_specs(source_events)
    summary_audit = audit_summary_plan(source_events, classified, blocks, source_start=82, source_end=233)
    bridge_audit = audit_summary_bridges(
        source_events, classified, bridges, summary_ranges=[(147, 231)]
    )
    if summary_audit["status"] != "PASS" or bridge_audit["status"] != "PASS":
        raise RuntimeError({"summary": summary_audit, "bridges": bridge_audit})
    wj(OUT / "V13_VIDEO_001_V2_8_REPLAY_CLASSIFICATION.json", classified)
    wj(OUT / "V13_VIDEO_001_V2_8_SUMMARY_BLOCKS.json", blocks)
    wj(OUT / "V13_VIDEO_001_V2_8_SUMMARY_BRIDGES.json", bridges)
    wj(OUT / "V13_VIDEO_001_V2_8_SUMMARY_QA.json", summary_audit)
    wj(OUT / "V13_VIDEO_001_V2_8_BRIDGE_QA.json", bridge_audit)

    old_table = rj(V26 / "V13_VIDEO_001_V2_6_TABLE_LOG.json")
    table_template = next(row for row in old_table["events"] if row["table_event_id"] == "table_020")
    table_rows = [row for row in old_table["events"] if int(row["table_event_id"].split("_")[-1]) < 19]
    table_rows.append(make_bridge_table_event(bridges[0], table_template))
    table_rows += [make_table_event(block, index, table_template) for index, block in enumerate(blocks, 1)]
    table_rows.append(make_bridge_table_event(bridges[1], table_template))
    table_rows += [row for row in old_table["events"] if int(row["table_event_id"].split("_")[-1]) >= 22]
    table = {**old_table, "schema_version": "2.8", "video_id": VIDEO_ID,
             "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_7", "events": table_rows,
             "replay_summary_layer": {
                 "version": "REPLAY_SUMMARY_LAYER_V2", "range": "146..231",
                 "summary_range": "147..230", "block_count": 3, "bridge_count": 2,
                 "entry_bridge_id": bridges[0]["bridge_id"], "exit_bridge_id": bridges[1]["bridge_id"],
             }}
    wj(OUT / "V13_VIDEO_001_V2_8_TABLE_LOG.json", table)

    old_script = rj(V26 / "V13_VIDEO_001_V2_6_SCRIPT.json")
    script_template = next(row for row in old_script["lines"] if row["source_table_event_id"] == "table_020")
    script_lines = [row for row in old_script["lines"] if int(row["source_table_event_id"].split("_")[-1]) < 19]
    summaries = [make_script_line(block, index, script_template) for index, block in enumerate(blocks, 1)]
    bridge_lines = [make_bridge_script_line(bridge, script_template) for bridge in bridges]
    script_lines.append(bridge_lines[0])
    script_lines += summaries
    script_lines.append(bridge_lines[1])
    script_lines += [row for row in old_script["lines"] if row["source_table_event_id"].startswith("table_")
                     and int(row["source_table_event_id"].split("_")[-1]) >= 22]
    script = {**old_script, "schema_version": "2.8", "video_id": VIDEO_ID,
              "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_7", "lines": script_lines,
              "replay_summary_layer": "REPLAY_SUMMARY_LAYER_V2"}

    pipe = M1Pipeline(RT, PROJ)
    # The V2.6 renderer is intentionally reused, but its module-level project
    # path points at the immutable V2.6 workspace unless redirected here.
    v26.PROJ = PROJ
    render_lines = [bridge_lines[0], *summaries, bridge_lines[1]]
    audio = pipe.render_voices(render_lines)
    old_timeline = rj(V26 / "V13_VIDEO_001_V2_6_TIMELINE.json")
    old_clips = old_timeline["clips"]
    clips = [copy.deepcopy(clip) for clip in old_clips if int(clip["source_table_event_id"].split("_")[-1]) < 19]
    base_clip = next(clip for clip in old_clips if clip["source_table_event_id"] == "table_020")
    entry_record = audio[bridge_lines[0]["line_id"]]
    entry_clip = copy.deepcopy(base_clip)
    entry_clip.update({
        "source_table_event_id": bridge_lines[0]["source_table_event_id"],
        "source_event_ids": bridges[0]["source_event_ids"],
        "raw_event_offsets": bridges[0]["raw_event_offsets"], "subtitle_text": bridges[0]["text"],
        "voice_file": entry_record["project_path"], "voice_engine": entry_record["engine"],
        "voice_profile_id": "sakuya_tune_110_v1", "duration_sec": round(entry_record["duration_sec"] + 0.35, 3),
        "event_type": bridges[0]["render_mode"], "truth_class": "FACT_BRIDGE",
        "reason_class": bridges[0]["reason_class"], "visual_state": bridges[0]["bridge_id"].upper(),
        "background_asset_id": "bg_neutral_user", "required_location": bridges[0]["to_location"],
    })
    entry_clip["scene_state"].update({"current_location": bridges[0]["to_location"],
                                      "source_event_ids": bridges[0]["source_event_ids"]})
    clips.append(entry_clip)
    for index, (block, line) in enumerate(zip(blocks, summaries), 1):
        record = audio[line["line_id"]]
        clip = copy.deepcopy(base_clip)
        clip.update({
            "source_table_event_id": f"summary_table_{index:03d}", "source_event_ids": block["source_event_ids"],
            "raw_event_offsets": block["raw_event_offsets"], "subtitle_text": block["text"],
            "voice_file": record["project_path"], "voice_engine": record["engine"],
            "voice_profile_id": "sakuya_tune_110_v1", "duration_sec": round(record["duration_sec"] + 0.35, 3),
            "event_type": "REPLAY_SUMMARY", "truth_class": "FACT_SUMMARY",
            "visual_state": block["summary_block_id"].upper(), "background_asset_id": "bg_neutral_user",
            "required_location": None,
        })
        clip["scene_state"].update({"current_location": "corbitt_house_interior",
                                    "source_event_ids": block["source_event_ids"]})
        clips.append(clip)
    exit_record = audio[bridge_lines[1]["line_id"]]
    exit_clip = copy.deepcopy(base_clip)
    exit_clip.update({
        "source_table_event_id": bridge_lines[1]["source_table_event_id"],
        "source_event_ids": bridges[1]["source_event_ids"],
        "raw_event_offsets": bridges[1]["raw_event_offsets"], "subtitle_text": bridges[1]["text"],
        "voice_file": exit_record["project_path"], "voice_engine": exit_record["engine"],
        "voice_profile_id": "sakuya_tune_110_v1", "duration_sec": round(exit_record["duration_sec"] + 0.35, 3),
        "event_type": bridges[1]["render_mode"], "truth_class": "FACT_BRIDGE",
        "reason_class": bridges[1]["reason_class"], "visual_state": bridges[1]["bridge_id"].upper(),
        "background_asset_id": "bg_basement_aipict", "required_location": bridges[1]["to_location"],
    })
    exit_clip["scene_state"].update({"current_location": bridges[1]["to_location"],
                                     "source_event_ids": bridges[1]["source_event_ids"]})
    clips.append(exit_clip)
    clips += [copy.deepcopy(clip) for clip in old_clips if clip["source_table_event_id"].startswith("table_")
              and int(clip["source_table_event_id"].split("_")[-1]) >= 22]
    cursor = 0.0
    for index, clip in enumerate(clips, 1):
        clip["clip_id"] = f"clip_{index:03d}"
        clip["start_sec"] = round(cursor, 3)
        cursor += float(clip["duration_sec"])
        if clip.get("subtitle_text"):
            ui = layout_for_canvas()
            clip["dialogue_ui"] = {
                **wrap_dialogue(clip["subtitle_text"], ui.text_safe_area),
                "name_font_size": fit_name_font_size(
                    str(clip.get("speaker_name") or ""), ui.name_plate, DEFAULT_NAME_FONT_SIZE
                ) if clip.get("speaker_name") else None,
            }
    timeline = {**old_timeline, "schema_version": "2.8", "video_id": VIDEO_ID,
                "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_7", "clips": clips,
                "duration_sec": round(cursor, 3)}
    cue_by_table = {clip["source_table_event_id"]: clip for clip in clips}
    cues = copy.deepcopy(old_timeline.get("sfx_cues") or [])
    for cue in cues:
        linked = cue_by_table.get(cue.get("source_table_event_id"))
        if linked:
            cue["start_sec"] = round(float(linked["start_sec"]) + 0.2, 3)
    timeline["sfx_cues"] = cues
    timeline["bgm"] = {**(old_timeline.get("bgm") or {}), "end_sec": timeline["duration_sec"]}
    by_table = {clip["source_table_event_id"]: clip for clip in clips}
    for line in script_lines:
        clip = by_table[line["source_table_event_id"]]
        line["dialogue_ui"] = clip.get("dialogue_ui")
    wj(OUT / "V13_VIDEO_001_V2_8_SCRIPT.json", script)
    wj(OUT / "V13_VIDEO_001_V2_8_TIMELINE.json", timeline)

    asset_doc = rj(PROJ / "asset_manifest.json")
    asset_paths = {item["asset_id"]: RT / item["file_path"] for item in asset_doc["assets"]}
    asset_paths["dialogue_frame_user"] = REPO / "video/assets/user_inputs/dialogue_frames/nc131976_SF風シンプルセリフ枠_外周trim.png"
    voice_manifest = rj(V26 / "V13_VIDEO_001_V2_6_VOICE_MANIFEST.json")
    gains = {key: value["dialogue_bus_gain_db"] for key, value in voice_manifest["dialogue_bus"].items()}
    base_video, overflow = v26.render_dialogue(pipe, timeline, gains, asset_paths)

    bgm = v26.v25.BGM
    source_metrics = {"bgm": v26.v25.v23.loudness(pipe.ffmpeg, bgm)}
    bgm_gain = round(-31.0 - source_metrics["bgm"]["lufs"], 3)
    sfx_metrics = {}
    for cue in cues:
        key = cue["kind"]
        if key not in sfx_metrics:
            sfx_metrics[key] = v26.v25.v23.loudness(pipe.ffmpeg, Path(cue["path"]))
    preview = OUT / "V13_VIDEO_001_BASEMENT_PLANKS_V2_8_PREVIEW.mp4"
    args = [str(pipe.ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base_video),
            "-stream_loop", "-1", "-i", str(bgm)]
    for cue in cues:
        args += ["-i", cue["path"]]
    fade = max(0.0, timeline["duration_sec"] - 1.5)
    filters = ["[0:a]asplit=2[dialogue][sidechain]",
               f"[1:a]atrim=duration={timeline['duration_sec']},afade=t=in:st=0:d=1.5,afade=t=out:st={fade}:d=1.5,volume={bgm_gain}dB[bgpre]",
               "[bgpre][sidechain]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=350[bgduck]"]
    labels = ["[dialogue]", "[bgduck]"]
    for input_index, cue in enumerate(cues, 2):
        gain = round(-24.0 - sfx_metrics[cue["kind"]]["lufs"], 3)
        delay = round(float(cue["start_sec"]) * 1000)
        filters.append(f"[{input_index}:a]volume={gain}dB,adelay={delay}|{delay}[sfx{input_index}]")
        labels.append(f"[sfx{input_index}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:duration=first:dropout_transition=0[mix]")
    args += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]", "-c:v", "copy",
             "-c:a", "aac", "-b:a", "192k", "-t", str(timeline["duration_sec"]),
             "-movflags", "+faststart", str(preview)]
    subprocess.run(args, check=True)

    ui_report = audit_dialogue_ui(clips, layout_for_canvas())
    source_after = {name: snapshot(path) for name, path in protected.items()}
    source_unchanged = before == source_after
    counts = {**summary_audit["counts"], **bridge_audit["counts"]}
    technical = preview.is_file() and not overflow and not any(ui_report["counts"].values())
    content = summary_audit["status"] == "PASS" and bridge_audit["status"] == "PASS" and source_unchanged
    accepted = technical and content
    qa = {
        "status": "PASS" if accepted else "FAIL", "SOURCE_ACCEPTED_ARTIFACTS_UNCHANGED": source_unchanged,
        "summary_gate": summary_audit, "bridge_gate": bridge_audit,
        "SUMMARY_TRACEABILITY": summary_audit["SUMMARY_TRACEABILITY"],
        "LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED": bridge_audit["LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED"],
        "counts": counts, "ui_layout": ui_report, "subtitle_overflow_ids": overflow,
        "TECHNICAL_QA": "PASS" if technical else "FAIL", "CONTENT_QA": "PASS" if content else "FAIL",
        "VIDEO_V2_8_ACCEPTED_FOR_HUMAN_REVIEW": accepted, "HUMAN_REVIEW": "PENDING",
        "AUTO_PUBLISH": "prohibited", "LICENSE_REVIEW": "REQUIRED",
    }
    wj(OUT / "V13_VIDEO_001_V2_8_QA_REPORT.json", qa)
    (OUT / "V13_VIDEO_001_V2_8_QA_REPORT.md").write_text(
        "# V13 Video 001 V2.8 QA\n\n"
        f"- SUMMARY_TRACEABILITY: `{summary_audit['SUMMARY_TRACEABILITY']:.1f}`\n"
        + f"- LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED: `{str(bridge_audit['LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED']).lower()}`\n"
        + "\n".join(f"- {key}: `{value}`" for key, value in counts.items())
        + f"\n- TECHNICAL_QA: `{'PASS' if technical else 'FAIL'}`"
        + f"\n- CONTENT_QA: `{'PASS' if content else 'FAIL'}`"
        + f"\n- VIDEO_V2_8_ACCEPTED_FOR_HUMAN_REVIEW: `{str(accepted).lower()}`"
        + "\n- HUMAN_REVIEW: `PENDING`\n- AUTO_PUBLISH: `prohibited`\n",
        encoding="utf-8",
    )
    shutil.copy2(__file__, OUT / "V13_VIDEO_001_V2_8_BUILD_PIPELINE.py")
    artifacts = [{"path": str(path), "size": path.stat().st_size, "sha256": v26.v25.v23.sha(path)}
                 for path in sorted(OUT.iterdir()) if path.is_file() and "ARTIFACT_MANIFEST" not in path.name]
    wj(OUT / "V13_VIDEO_001_V2_8_ARTIFACT_MANIFEST.json", {
        "video_id": VIDEO_ID, "source_range": "82..233", "summary_range": "147..230",
        "bridge_offsets": [146, 231], "source_unchanged": source_unchanged,
        "summary_gate": summary_audit, "bridge_gate": bridge_audit,
        "VIDEO_V2_8_ACCEPTED_FOR_HUMAN_REVIEW": accepted, "artifacts": artifacts,
    })
    print(json.dumps({"video_id": VIDEO_ID, "preview": str(preview), "duration": timeline["duration_sec"],
                      "summary_gate": summary_audit["status"], "bridge_gate": bridge_audit["status"],
                      "location_change_presented": bridge_audit["LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED"],
                      "technical": technical,
                      "content": content, "accepted": accepted}, ensure_ascii=False))


if __name__ == "__main__":
    main()

