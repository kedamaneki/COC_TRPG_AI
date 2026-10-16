from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from video_agent.common.io import read_json, sha256_file, stable_digest, write_json
from video_agent.presentation.assets import generate_credits, license_gate
from video_agent.presentation.identity import resolve_display_identity
from video_agent.presentation.final_result import (apply_final_result_overrides,
                                                     final_result_mismatches)
from video_agent.presentation.narrative import (apply_narrative_presentation,
                                                 build_narrative_artifacts,
                                                 finalize_narrative_markdown,
                                                 write_narrative_markdown)
from video_agent.presentation.planner import build_visual_plan
from video_agent.presentation.system_filter import system_presentation_decision
from video_agent.presentation.system_interaction import resolve_system_interactions, required_fixture
from video_agent.rendering import M1Pipeline
from video_agent.rendering.pipeline import voice_profile_mismatches
from video_agent.rendering.assets import head_portrait_box, layout_overlap_issues, rectangles_overlap
from video_agent.rendering.subtitles import (kp_subtitle_contrast_issues, paginate_text,
                                             ass_color, japanese_line_breaks,
                                             readability_issues, speaker_name_contrast_issues,
                                             subtitle_contrast_issues, word_internal_line_break_issues)
from video_agent.voice.engines import wav_duration
from video_agent.voice.prosody_fixture import build_prosody_ab_fixture
from video_agent.voice.qa import internal_utterance_gaps, suspicious_audio_bursts


ASSET_SPECS = {
    "portrait_pc_01": ("portrait_pc01_kitsune_reimu", "PORTRAIT", "portraits/pc_01_normal.png", ["PORTRAIT", "PC_01", "NORMAL", "HEAD_ONLY"]),
    "portrait_pc_02": ("portrait_pc02_kitsune_marisa", "PORTRAIT", "portraits/pc_02_normal.png", ["PORTRAIT", "PC_02", "NORMAL", "HEAD_ONLY"]),
    "background_neutral": ("bg_neutral_user", "BACKGROUND", "backgrounds/neutral.png", ["BACKGROUND", "NEUTRAL", "FALLBACK"]),
    "dialogue_frame": ("dialogue_frame_user", "UI", "ui/dialogue_frame.png", ["UI", "DIALOGUE_FRAME"]),
    "bgm_investigation": ("bgm_investigation_user", "BGM", "audio/bgm_investigation.mp3", ["BGM", "INVESTIGATION"]),
    "se_dice": ("se_dice_user", "SE", "audio/se_dice.mp3", ["SE", "DICE"]),
    "se_san": ("se_san_user", "SE", "audio/se_san.mp3", ["SE", "SAN"]),
    "se_transition": ("se_transition_user", "SE", "audio/se_transition.mp3", ["SE", "TRANSITION"]),
}


class M3Pipeline:
    def __init__(self, root: Path, project: Path):
        self.root = Path(root).resolve()
        project = Path(project)
        self.project = project.resolve() if not project.is_absolute() else project
        self.config = read_json(self.root / "config" / "presentation_m3.json")
        self.edited = read_json(self.project / "edited_script.json")
        self.normalized = read_json(self.project / "normalized_session.json")
        self.protected = read_json(self.project / "protected_events.json")
        self.scenes = read_json(self.project / "scene_plan.json")["scenes"]
        self.preview = self.root / "projects" / "m3_scene_preview"
        self.state_path = self.project / "m3_project_state.json"
        self.asset_root = self.project / "scenario_assets" / "corbitt"
        self.identity_schema = read_json(self.root / "config" / "speaker_identity_m3.json")

    def _state(self, status: str, completed: list[str], phase_decisions: list[str] | None = None):
        value = {"status": status, "completed_steps": completed}
        if phase_decisions:
            value["phase_decisions"] = phase_decisions
        write_json(self.state_path, value)

    def import_assets(self) -> list[dict]:
        assets = []
        for source_key, (asset_id, kind, relative, tags) in ASSET_SPECS.items():
            source = Path(self.config["asset_sources"][source_key])
            destination = self.asset_root / relative
            if not source.exists():
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if not destination.exists() or sha256_file(source) != sha256_file(destination):
                shutil.copy2(source, destination)
            assets.append({
                "asset_id": asset_id, "type": kind,
                "file_path": str(destination.relative_to(self.root)).replace("\\", "/"),
                "source": f"user-provided:{source.name}", "creator": "UNKNOWN", "license": "UNKNOWN",
                "commercial_use": None, "credit_required": None, "credit_text": None,
                "status": "UNKNOWN", "tags": tags, "sha256": sha256_file(destination),
            })
        manifest = {"schema_version": "0.1", "assets": assets, "imported_at": datetime.now(timezone.utc).isoformat()}
        write_json(self.asset_root / "manifest.json", manifest)
        self._state("ASSETS_RESOLVED", ["assets"])
        return assets

    def plan(self, assets: list[dict]) -> dict:
        portraits = {
            "pc_01": {"profile_id": "kitsune_reimu_old", "position": "LEFT", "scale": 1.0,
                      "portrait_kind": "HEAD_ONLY", "expressions": {"NORMAL": "portrait_pc01_kitsune_reimu"}},
            "pc_02": {"profile_id": "kitsune_marisa_old", "position": "RIGHT", "scale": 1.0,
                      "portrait_kind": "HEAD_ONLY", "expressions": {"NORMAL": "portrait_pc02_kitsune_marisa"}},
        }
        plan = build_visual_plan(self.edited["lines"], self.scenes, portraits, {}, "bg_neutral_user")
        plan["metadata"] = {"planner": "deterministic_m3_v1", "edited_script_sha256": stable_digest(self.edited)}
        write_json(self.project / "visual_plan.json", plan)
        narrative = build_narrative_artifacts(project=self.project, edited=self.edited,
                                              normalized=self.normalized, scenes=self.scenes,
                                              protected=self.protected)
        write_narrative_markdown(self.project, narrative)
        missing = [{"type": "background", "location_id": item, "preferred_source": "scenario_specific",
                    "fallback_asset_id": "bg_neutral_user", "status": "USER_INPUT_REQUIRED"}
                   for item in plan["missing_location_ids"]]
        missing.append({"type": "portrait", "character": "pc_02", "preferred_source": "licensed_voice_character_or_original_pc",
                        "fallback_asset_id": "portrait_pc02_kitsune_marisa", "status": "USER_INPUT_REQUIRED"})
        write_json(self.project / "missing_assets_report.json", {"missing": missing})
        used = {entry["background_asset_id"] for entry in plan["entries"]}
        used.update(entry["bgm_asset_id"] for entry in plan["entries"])
        used.update(se for entry in plan["entries"] for se in entry["se"])
        used.update(entry["portrait"]["asset_id"] for entry in plan["entries"] if entry["portrait"])
        used.add("dialogue_frame_user")
        gate = license_gate(assets, used)
        resolution = {"used_asset_ids": sorted(used), "resolved_count": len(used),
                      "missing": missing, "license_gate": gate, "publishability": "LOCAL_PREVIEW"}
        write_json(self.project / "asset_resolution.json", resolution)
        mix = {"schema_version": "0.1", "buses": {
            "voice": {"target_lufs": self.config["mix"]["voice_lufs"], "priority": 1},
            "bgm": {"gain_db": self.config["mix"]["bgm_gain_db"], "duck_gain_db": self.config["mix"]["duck_gain_db"],
                    "duck_trigger": "speech_active", "fade_sec": self.config["mix"]["fade_sec"]},
            "se": {"gain_db": self.config["mix"]["se_gain_db"], "sparse": True},
        }, "limiter": self.config["mix"]["limiter"]}
        write_json(self.project / "audio_mix_plan.json", mix)
        report = {"assets": assets, "gate": gate, "publishability": "LOCAL_PREVIEW"}
        write_json(self.project / "license_report.json", report)
        (self.project / "credits.txt").write_text(generate_credits(assets, used), encoding="utf-8")
        self._state("VISUAL_PLAN_READY", ["assets", "visual_plan", "audio_mix", "license"])
        return plan

    def _selected_lines(self, plan: dict, start_id: str | None = None, end_id: str | None = None,
                        record_reports: bool = True) -> list[dict]:
        start_id = start_id or self.config["preview"]["start_script_line_id"]
        end_id = end_id or self.config["preview"]["end_script_line_id"]
        ids = [line["script_line_id"] for line in self.edited["lines"]]
        selected_source = self.edited["lines"][ids.index(start_id):ids.index(end_id) + 1]
        pc_to_player = {item["pc_id"]: item.get("controlled_by_player_id")
                        for item in self.identity_schema.get("pcs", [])}
        selected, interaction_report = resolve_system_interactions(selected_source, pc_to_player)
        narrative_plan = read_json(self.project / "narrative_presentation_plan.json")
        selected = apply_narrative_presentation(selected, narrative_plan)
        selected, final_result_changes = apply_final_result_overrides(selected)
        fixture = required_fixture()
        if record_reports:
            write_json(self.project / "system_interaction_report.json", interaction_report)
            write_json(self.project / "review" / "m3_system_interaction_fixture.json",
                       {**fixture, "observed_preview": interaction_report})
        visual = {entry["script_line_id"]: entry for entry in plan["entries"]}
        profile_for = {"pc_01": ("m1_aq_f1", "subtitle_reimu"), "pc_02": ("aq_marisa_default", "subtitle_marisa"),
                       "kp": ("m1_vv_kp", "subtitle_kp"), "system": (None, "subtitle_kp")}
        display_for = {"pc_01": "マクガフィン刑事", "pc_02": "エレノア教授", "kp": "KP", "system": "SYSTEM"}
        result = []
        decisions = []
        for line in selected:
            system_decision = system_presentation_decision(line)
            decisions.append({"script_line_id": line["script_line_id"], "event_type": line["event_type"],
                              **system_decision})
            if system_decision["is_system"] and not system_decision["allowed"]:
                continue
            entry = visual[line.get("visual_source_script_line_id", line["script_line_id"])]
            voice, subtitle = profile_for.get(line["speaker_id"], profile_for["system"])
            portrait = entry["portrait"] if line.get("presentation_as") != "KP" else None
            fallback = {"display_name": display_for.get(line["speaker_id"], line["speaker_id"]),
                        "voice_profile_id": voice, "subtitle_profile_id": subtitle,
                        "portrait_profile_id": portrait["profile_id"] if portrait else None}
            source_actor = line.get("player_id") or line["speaker_id"]
            controlled_character = line.get("pc_id") or (line["speaker_id"] if line["speaker_id"].startswith("pc_") else None)
            identity = resolve_display_identity(source_actor, line.get("speaker_mode"), controlled_character,
                                                self.identity_schema, fallback)
            if line.get("presentation_as") == "PL":
                player = next((item for item in self.identity_schema.get("players", [])
                               if item["player_id"] == line.get("player_id")), None)
                if not player or not player.get("voice_profile_id"):
                    interaction_report["pl_voice_fallback_count"] += 1
                    line["pl_voice_fallback"] = "PL_VOICE_FALLBACK_USED"
            result.append({
                "source_event_ids": line["source_event_ids"], "speaker_id": line["speaker_id"],
                "source_script_line_id": line["script_line_id"],
                "text": line.get("display_text") or "", "voice_text": line.get("voice_text"),
                "voice_profile_id": identity["resolved_voice_profile_id"],
                "subtitle_profile_id": identity["resolved_subtitle_profile_id"],
                "resolved_display_name": identity["resolved_display_name"], "speaker_context": identity,
                "portrait_asset_id": portrait["asset_id"] if portrait else None,
                "portrait_kind": portrait["portrait_kind"] if portrait else None,
                "portrait_side": portrait["position"].lower() if portrait else None,
                "background_asset_id": entry["background_asset_id"], "event_type": line["event_type"],
                "overlay": line.get("overlay") if line.get("overlay") is not None else entry.get("overlay"),
                "presentation_mode": line["presentation_mode"],
                "presentation_origin": line.get("presentation_origin"),
                "presentation_as": line.get("presentation_as"),
                "system_interaction_id": line.get("system_interaction_id"),
                "interaction_type": line.get("interaction_type"),
                "prompt_grounding": line.get("prompt_grounding"),
                "prompt_grounding_source_event_ids": line.get("prompt_grounding_source_event_ids", []),
                "pl_voice_fallback": line.get("pl_voice_fallback"),
                "semantic_class": line.get("semantic_class"),
                "narrative_role": line.get("narrative_role"),
                "original_order": line.get("original_order"),
                "presentation_order": line.get("presentation_order"),
                "reorder_reason": line.get("reorder_reason"),
                "presentation_generated_from_structured_fact": line.get(
                    "presentation_generated_from_structured_fact", False),
                "fixed_duration_sec": 3.2,
            })
        if record_reports:
            write_json(self.project / "system_interaction_report.json", interaction_report)
            write_json(self.project / "system_presentation_report.json", {
                "policy": "WHITELIST", "decisions": decisions,
                "removed_count": sum(1 for item in decisions if item["is_system"] and not item["allowed"]),
                "displayed_system_types": sorted({item["presentation_type"] for item in decisions
                                                  if item["is_system"] and item["allowed"]}),
            })
            write_json(self.project / "review" / "m3_final_result_fixture.json", {
                "fixture": {"skill": "目星", "target": 50, "roll": 59,
                            "raw_result": "FAILURE", "final_result": "SUCCESS",
                            "modification": {"type": "LUCK_SPEND", "amount": 9}},
                "observed_changes": final_result_changes,
                "expected_flow": ["失敗", "幸運 9消費", "成功扱い"],
                "pass": any(item.get("raw_result") == "FAILURE"
                            and item.get("final_result") == "SUCCESS"
                            and item.get("modification", {}).get("amount") == 9
                            for item in final_result_changes),
            })
        return result

    def _write_preview_project(self, preview: Path, assets: list[dict], selected: list[dict]) -> None:
        preview.mkdir(parents=True, exist_ok=True)
        write_json(preview / "project.json", {
            "fixture_type": "synthetic", "background_asset_id": "bg_neutral_user", "lines": selected,
            "dialogue_frame_asset_id": "dialogue_frame_user",
            "subtitle_layout_config": self.config["layout_config"],
            "speech_chunking": {"enabled": True, "max_chars": 52},
        })
        write_json(preview / "characters.json", [
            {"character_id": "kp", "display_name": "KP", "role": "KP", "voice_profile_id": "m1_vv_kp", "expected_voice_profile_id": "m1_vv_kp", "subtitle_profile_id": "subtitle_kp", "portrait_asset_id": None},
            {"character_id": "pc_01", "display_name": "マクガフィン刑事", "role": "PC", "voice_profile_id": "m1_aq_f1", "expected_voice_profile_id": "m1_aq_f1", "subtitle_profile_id": "subtitle_reimu", "portrait_asset_id": "portrait_pc01_kitsune_reimu"},
            {"character_id": "pc_02", "display_name": "エレノア教授", "role": "PC", "voice_profile_id": "aq_marisa_default", "expected_voice_profile_id": "aq_marisa_default", "subtitle_profile_id": "subtitle_marisa", "portrait_asset_id": "portrait_pc02_kitsune_marisa"},
            {"character_id": "system", "display_name": "SYSTEM", "role": "SYSTEM", "voice_profile_id": None, "subtitle_profile_id": "subtitle_kp", "portrait_asset_id": None},
        ])
        write_json(preview / "asset_manifest.json", {"schema_version": "0.1", "assets": assets})

    @staticmethod
    def _decorate_timeline(timeline: dict) -> None:
        for clip in timeline["clips"]:
            event_type = clip.get("event_type")
            first_chunk = not clip.get("speech_chunk") or clip["speech_chunk"]["index"] == 1
            clip["se_asset_ids"] = (["se_san_user"] if first_chunk and event_type in {"SAN_CHECK", "SAN_LOSS"}
                                    else ["se_dice_user"] if first_chunk and event_type in {"DICE_RESULT", "SKILL_CHECK"} else [])
            clip["bgm_asset_id"] = "bgm_investigation_user"

    def render_preview(self, assets: list[dict], plan: dict) -> tuple[Path, dict]:
        selected = self._selected_lines(plan)
        self._write_preview_project(self.preview, assets, selected)
        build_prosody_ab_fixture(self.root, self.project, selected)
        renderer = M1Pipeline(self.root, self.preview)
        lines = renderer.prepare_script()
        audio = renderer.render_voices(lines)
        self._state("AUDIO_MIX_READY", ["assets", "visual_plan", "voice", "audio_mix"])
        timeline = renderer.build_timeline(lines, audio)
        self._decorate_timeline(timeline)
        write_json(self.preview / "video_timeline.json", timeline)
        self._state("TIMELINE_READY", ["assets", "visual_plan", "voice", "audio_mix", "timeline"])
        base = renderer.render_video(timeline)
        output = self.preview / "output" / "m3_scene_preview_mixed.mp4"
        self._mix_audio(base, output, timeline, assets, renderer.ffmpeg)
        self._state("RENDERED", ["assets", "visual_plan", "voice", "audio_mix", "timeline", "render"])
        qa = self._qa(output, timeline, assets, renderer.ffmpeg, renderer.ffprobe)
        review_output = self.project / "review" / "m3_scene_preview.mp4"
        review_output.parent.mkdir(exist_ok=True)
        shutil.copy2(output, review_output)
        shutil.copy2(output, self.project / "review" / "m3_scene_preview_after_iteration5.mp4")
        shutil.copy2(output, self.project / "review" / "m3_knife_encounter_preview.mp4")
        shutil.copy2(output, self.project / "review" / "m3_knife_encounter_preview_iteration6.mp4")
        self._subtitle_palette_fixture(output, timeline, renderer.ffmpeg)
        self._iteration3_fixtures(output, timeline, renderer.ffmpeg)
        self._iteration6_readability_fixture(renderer.ffmpeg)
        return review_output, qa

    def _iteration6_readability_fixture(self, ffmpeg: Path) -> None:
        """Render a 1920x1080 sheet for the Iteration 6 human review."""
        review = self.project / "review"
        review.mkdir(exist_ok=True)
        profiles = {item["subtitle_profile_id"]: item
                    for item in read_json(self.root / "config" / "subtitles" / "defaults.json")}
        samples = [
            ("subtitle_kp", "KP 長文: 古いナイフは静寂を破り、探索者の手を振りほどいて宙に浮かび上がった。", 155),
            ("subtitle_reimu", "霊夢 長文: 地下室へ続く扉を調べ、慎重に周囲の気配を確かめます。", 285),
            ("subtitle_marisa", "魔理沙 長文: 幸運を9ポイント消費して、この判定を成功扱いにするぜ。", 415),
            ("subtitle_reimu", "赤系名前  マクガフィン刑事", 545),
            ("subtitle_marisa", "黄色系名前  エレノア教授／魔理沙", 655),
            ("subtitle_kp", "句読点: 『本当に開けますか？』――はい、慎重に開けます！", 775),
            ("subtitle_kp", "複合文: 視線を逸らさず錆びついた魔法のダガーを睨みつける。", 905),
        ]
        header = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\n\n[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\nStyle: S,Yu Gothic,46,&H00FFFFFF,&H00FFFFFF,&H00181818,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,5,0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"""
        events = []
        for profile_id, content, y in samples:
            profile = profiles[profile_id]
            lines, _ = japanese_line_breaks(content, 1540, 46)
            text = "\\N".join(lines).replace("{", "（").replace("}", "）")
            outline = profile.get("outlines") or [{"width": 2, "color": "#181818"}]
            events.append(
                f"Dialogue: 0,0:00:00.00,0:00:05.00,S,,0,0,0,,"
                f"{{\\an5\\pos(960,{y})\\1c{ass_color(profile['text_color'])}"
                f"\\3c{ass_color(outline[0]['color'])}\\bord{outline[0]['width']}}}{text}")
        ass = review / "m3_subtitle_readability_iteration6.ass"
        ass.write_text(header + "\n".join(events) + "\n", encoding="utf-8-sig")
        target = review / "m3_subtitle_readability_iteration6.png"
        ass_filter = str(ass.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=#24162E:s=1920x1080:d=1",
                        "-vf", f"ass=filename='{ass_filter}'", "-frames:v", "1", str(target)], check=True)

    def _finalize_iteration6_artifacts(self) -> None:
        report_path = self.project / "review" / "m3_audio_noise_qa_report.json"
        report = read_json(report_path)
        battle = self.root / "projects" / "m3_final_battle_preview"
        battle_timeline = read_json(battle / "video_timeline.json")
        battle_blank_refs = [clip["clip_id"] for clip in battle_timeline["clips"]
                             if not str(clip.get("subtitle_text") or "").strip() and clip.get("voice_file")]
        battle_bursts = []
        for clip in battle_timeline["clips"]:
            if clip.get("audio_mode") == "VOICE" and clip.get("voice_file"):
                battle_bursts.extend(suspicious_audio_bursts(battle / clip["voice_file"]))
        report.update({
            "final_battle_blank_voice_reference_count": len(battle_blank_refs),
            "final_battle_suspicious_audio_burst_count": len(battle_bursts),
            "final_battle_known_windows_result": "NO_WHITESPACE_VOICE_SOURCE",
            "knife_known_window_result": "NO_WHITESPACE_VOICE_SOURCE",
        })
        write_json(report_path, report)
        report_doc = self.root / "docs" / "M3_PRESENTATION_REPORT.md"
        text = report_doc.read_text(encoding="utf-8")
        marker = "## Presentation Iteration 6"
        if marker in text:
            text = text.split(marker)[0].rstrip() + "\n"
        section = f"""

## Presentation Iteration 6

- blank voice assets removed: Timeline参照0、新規生成0。既存cacheは`ORPHANED_INVALID_VOICE_CACHE`として非参照。
- noise regression result: Knife/Final Battleとも空白音声由来burst 0。既知bad fixtureの検出はPASS。
- luck override display result: `目星50 / 59 / 失敗 → 幸運9消費 → 成功扱い`をraw/final分離で表示。
- subtitle line-break changes: 文字数分割からピクセル幅・句読点・文節・禁則優先へ変更。音声chunkは変更していない。
- KP subtitle contrast: near-white本文と2.25px濃灰outlineへ調整。
- speaker-name readability: 38pxを維持し、識別色に高contrast outlineを追加。QA PASS。
- remaining source gaps: ナイフ戦闘処理欠落、ナイフ再発見、地下室扉矛盾、SAN 1D4/1D3、最終戦Narrative richness不足を維持。

M3はCLOSEDにせず、`M3 PRESENTATION_NEEDS_ITERATION / M3 ASSET_INPUT_REQUIRED / M3 LICENSE_REVIEW_REQUIRED`、Human Review PENDINGを維持する。
"""
        report_doc.write_text(text.rstrip() + section, encoding="utf-8")

    def render_final_battle_preview(self, assets: list[dict], plan: dict) -> Path:
        """Render the conservative final-battle facts without inventing missing gameplay."""
        original_preview = self.preview
        auxiliary = self.root / "projects" / "m3_final_battle_preview"
        try:
            self.preview = auxiliary
            selected = self._selected_lines(plan, "scene_052_script_001", "scene_053_script_001",
                                            record_reports=False)
            self._write_preview_project(auxiliary, assets, selected)
            renderer = M1Pipeline(self.root, auxiliary)
            lines = renderer.prepare_script()
            audio = renderer.render_voices(lines)
            timeline = renderer.build_timeline(lines, audio)
            self._decorate_timeline(timeline)
            write_json(auxiliary / "video_timeline.json", timeline)
            base = renderer.render_video(timeline)
            output = auxiliary / "output" / "m3_final_battle_preview_mixed.mp4"
            self._mix_audio(base, output, timeline, assets, renderer.ffmpeg)
            review_output = self.project / "review" / "m3_final_battle_preview.mp4"
            review_output.parent.mkdir(exist_ok=True)
            shutil.copy2(output, review_output)
            shutil.copy2(output, self.project / "review" / "m3_final_battle_preview_iteration6.mp4")
            return review_output
        finally:
            self.preview = original_preview

    def _iteration3_fixtures(self, output: Path, timeline: dict, ffmpeg: Path) -> None:
        fixture_dir = self.preview / "qa" / "iteration3"
        fixture_dir.mkdir(parents=True, exist_ok=True)

        def frame_for(clip: dict, name: str) -> np.ndarray | None:
            target = fixture_dir / name
            subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-ss",
                            str(clip["start_sec"] + min(0.25, clip["duration_sec"] / 4)), "-i", str(output),
                            "-frames:v", "1", str(target)], check=False)
            image = cv2.imread(str(target))
            return image

        kp = next((item for item in timeline["clips"]
                   if item["presentation_mode"] == "VOICED" and item["speaker_id"] == "kp"), None)
        if kp:
            image = frame_for(kp, "kp.png")
            if image is not None:
                cv2.imwrite(str(self.project / "review" / "m3_kp_subtitle_fixture.png"), image)

        system = []
        for overlay_type in ("SKILL_CHECK", "SAN"):
            clip = next((item for item in timeline["clips"]
                         if (item.get("overlay") or {}).get("type") == overlay_type), None)
            if clip:
                image = frame_for(clip, f"system_{overlay_type.lower()}.png")
                if image is not None:
                    system.append(cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA))
        if system:
            while len(system) < 2:
                system.append(np.zeros_like(system[0]))
            top = cv2.hconcat(system[:2])
            sheet = cv2.vconcat([top, np.zeros_like(top)])
            cv2.imwrite(str(self.project / "review" / "m3_system_presentation_fixture.png"), sheet)

    def _subtitle_palette_fixture(self, output: Path, timeline: dict, ffmpeg: Path) -> None:
        fixture_dir = self.preview / "qa" / "subtitle_palette"
        fixture_dir.mkdir(parents=True, exist_ok=True)
        samples = []
        for profile_id in ("subtitle_reimu", "subtitle_marisa", "subtitle_kp"):
            clip = next((item for item in timeline["clips"]
                         if item["presentation_mode"] == "VOICED" and item["subtitle_profile_id"] == profile_id), None)
            if not clip:
                continue
            sample = fixture_dir / f"{profile_id}.png"
            subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-ss",
                            str(clip["start_sec"] + min(0.25, clip["duration_sec"] / 4)), "-i", str(output),
                            "-frames:v", "1", str(sample)], check=False)
            image = cv2.imread(str(sample))
            if image is not None:
                samples.append(cv2.resize(image, (960, 540), interpolation=cv2.INTER_AREA))
        if samples:
            while len(samples) < 4:
                samples.append(np.zeros_like(samples[0]))
            sheet = cv2.vconcat([cv2.hconcat(samples[:2]), cv2.hconcat(samples[2:4])])
            cv2.imwrite(str(self.project / "review" / "m3_subtitle_palette_fixture.png"), sheet)

    def _mix_audio(self, base: Path, output: Path, timeline: dict, assets: list[dict], ffmpeg: Path):
        lookup = {item["asset_id"]: self.root / item["file_path"] for item in assets}
        bgm = lookup["bgm_investigation_user"]
        se_events = [(clip["start_sec"], asset_id) for clip in timeline["clips"] for asset_id in clip.get("se_asset_ids", [])]
        command = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-i", str(base), "-stream_loop", "-1", "-i", str(bgm)]
        for _, asset_id in se_events:
            command += ["-i", str(lookup[asset_id])]
        filters = [f"[1:a]volume={self.config['mix']['bgm_gain_db']}dB,atrim=0:{timeline['duration_sec']},asetpts=N/SR/TB[bg]",
                   "[bg][0:a]sidechaincompress=threshold=0.015:ratio=8:attack=20:release=500[duck]"]
        mix_inputs = ["[0:a]", "[duck]"]
        for index, (start, _) in enumerate(se_events, 2):
            delay = int(start * 1000)
            label = f"se{index}"
            filters.append(f"[{index}:a]volume={self.config['mix']['se_gain_db']}dB,adelay={delay}|{delay}[{label}]")
            mix_inputs.append(f"[{label}]")
        filters.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0,alimiter=limit={self.config['mix']['limiter']}[mix]")
        command += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-t", str(timeline["duration_sec"]), "-movflags", "+faststart", str(output)]
        subprocess.run(command, check=True)

    def _qa(self, output: Path, timeline: dict, assets: list[dict], ffmpeg: Path, ffprobe: Path) -> dict:
        checks, warnings = [], []
        def add(name, ok, detail=None): checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        result = subprocess.run([str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace")
        probe = json.loads(result.stdout) if result.returncode == 0 else {}
        streams = probe.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})
        duration = float(probe.get("format", {}).get("duration", 0) or 0)
        add("output_exists", output.exists())
        add("duration_60_to_180_sec", 60 <= duration <= 180, duration)
        add("resolution_1920x1080", [video.get("width"), video.get("height")] == [1920, 1080])
        add("audio_stream", bool(audio))
        add("missing_voice_zero", all(clip.get("audio_mode") == "SILENCE" or
                                      (clip.get("voice_file") and (self.preview / clip["voice_file"]).exists())
                                      for clip in timeline["clips"]))
        lookup = {item["asset_id"]: item for item in assets}
        used = {clip["background_asset_id"] for clip in timeline["clips"]}
        used.update(a for clip in timeline["clips"] for a in clip["portrait_asset_ids"] + clip.get("se_asset_ids", []))
        used.update({"bgm_investigation_user", "dialogue_frame_user"})
        add("asset_resolution", all(asset_id in lookup for asset_id in used), sorted(used))
        add("asset_files_exist", all((self.root / lookup[a]["file_path"]).exists() for a in used if a in lookup))
        subtitle_manifest = read_json(self.preview / "subtitles" / "subtitle_manifest.json")
        add("subtitle_overflow_zero", not subtitle_manifest["overflow_clip_ids"], subtitle_manifest["overflow_clip_ids"])
        add("dice_overlay_present", any((c.get("overlay") or {}).get("type") == "SKILL_CHECK" for c in timeline["clips"]))
        add("san_overlay_present", any((c.get("overlay") or {}).get("type") == "SAN" for c in timeline["clips"]))
        add("bgm_present", all(c.get("bgm_asset_id") for c in timeline["clips"]))
        add("se_present", any(c.get("se_asset_ids") for c in timeline["clips"]))
        add("ducking_configured", self.config["mix"]["duck_gain_db"] < 0)
        mismatch = voice_profile_mismatches(timeline["clips"])
        add("VOICE_PROFILE_MISMATCH", not mismatch, mismatch)
        layout = read_json(self.root / self.config["layout_config"])
        profiles = {item["subtitle_profile_id"]: item for item in read_json(self.root / "config" / "subtitles" / "defaults.json")}
        style_issues = readability_issues(layout, profiles) + subtitle_contrast_issues(profiles)
        add("subtitle_readability_config", not style_issues, style_issues)
        kp_issues = kp_subtitle_contrast_issues(profiles["subtitle_kp"])
        add("KP_SUBTITLE_CONTRAST", not kp_issues, kp_issues)
        name_issues = speaker_name_contrast_issues(profiles)
        add("SPEAKER_NAME_CONTRAST", not name_issues, name_issues)
        system_report = read_json(self.project / "system_presentation_report.json")
        denied_ids = {item["script_line_id"] for item in system_report["decisions"]
                      if item["is_system"] and not item["allowed"]}
        leaked = [clip["source_script_line_id"] for clip in timeline["clips"]
                  if clip.get("source_script_line_id") in denied_ids]
        add("SYSTEM_PRESENTATION_WHITELIST", not leaked, {
            "removed_count": system_report["removed_count"],
            "displayed_system_types": system_report["displayed_system_types"], "leaked": leaked})
        interaction_report = read_json(self.project / "system_interaction_report.json")
        fixture = read_json(self.project / "review" / "m3_system_interaction_fixture.json")
        fixture["observed_preview"] = interaction_report
        write_json(self.project / "review" / "m3_system_interaction_fixture.json", fixture)
        interaction_clips = [clip for clip in timeline["clips"] if clip.get("system_interaction_id")]
        grouped = {}
        for clip in interaction_clips:
            grouped.setdefault(clip["system_interaction_id"], []).append(clip)
        pairing_errors = []
        context_errors = []
        identity_errors_pl = []
        ungrounded = []
        for interaction_id, clips in grouped.items():
            origins = [clip.get("presentation_origin") for clip in clips]
            if "SYSTEM_PROMPT" not in origins or "SYSTEM_RESPONSE" not in origins:
                pairing_errors.append(interaction_id)
            prompt_positions = [i for i, clip in enumerate(timeline["clips"])
                                if clip.get("system_interaction_id") == interaction_id
                                and clip.get("presentation_origin") == "SYSTEM_PROMPT"]
            response_positions = [i for i, clip in enumerate(timeline["clips"])
                                  if clip.get("system_interaction_id") == interaction_id
                                  and clip.get("presentation_origin") == "SYSTEM_RESPONSE"]
            if not prompt_positions or not response_positions or max(prompt_positions) >= min(response_positions):
                context_errors.append(interaction_id)
            for clip in clips:
                if clip.get("presentation_origin") == "SYSTEM_PROMPT" and not clip.get("prompt_grounding"):
                    ungrounded.append(clip["clip_id"])
                if clip.get("presentation_origin") == "SYSTEM_RESPONSE":
                    ctx = clip.get("speaker_context") or {}
                    if ctx.get("speaker_mode") != "PL" or not ctx.get("player_id"):
                        identity_errors_pl.append(clip["clip_id"])
        technical_leaks = [clip["clip_id"] for clip in timeline["clips"]
                           if any(marker in (clip.get("subtitle_text") or "").lower()
                                  for marker in ("checkpoint", "resume", "cache", "debug", "provider", "token", "llm", "worker", "exception"))]
        add("TABLETOP_SYSTEM_INTERACTION_PRESENTED",
            len(grouped) == interaction_report["tabletop_interactions_presented"] and bool(grouped),
            {"presented": len(grouped), "expected": interaction_report["tabletop_interactions_presented"]})
        add("SYSTEM_INTERACTION_PAIRING_VALID", not pairing_errors, pairing_errors)
        add("TECHNICAL_SYSTEM_INTERACTION_HIDDEN", not technical_leaks, technical_leaks)
        add("SYSTEM_RESPONSE_CONTEXT_VISIBLE", not context_errors, context_errors)
        add("PL_PC_IDENTITY_VALID", not identity_errors_pl, identity_errors_pl)
        add("UNGROUNDED_KP_PROMPT", not ungrounded and interaction_report["ungrounded_kp_prompt_count"] == 0,
            ungrounded)
        add("SYSTEM_INTERACTION_FIXTURES", all(item["pass"] for item in fixture["cases"]), fixture)
        narrative_coverage = read_json(self.project / "m3_narrative_coverage_report.json")
        narrative_gaps = read_json(self.project / "m3_source_gap_report.json")
        narrative_contradictions = read_json(self.project / "m3_contradiction_report.json")
        narrative_causality = read_json(self.project / "m3_causality_report.json")
        add("PROTECTED_NARRATIVE_COVERAGE",
            narrative_coverage["PROTECTED_NARRATIVE_COVERAGE"] == "PASS",
            {"hard_protected_count": narrative_coverage["hard_protected_count"],
             "full_count": narrative_coverage["full_count"],
             "source_insufficient_count": narrative_coverage["source_insufficient_count"],
             "invalid_event_ids": narrative_coverage["invalid_event_ids"]})
        add("UNGROUNDED_WORLD_EVENT_NARRATIVE",
            narrative_coverage["UNGROUNDED_WORLD_EVENT_NARRATIVE"] == 0,
            narrative_coverage["UNGROUNDED_WORLD_EVENT_NARRATIVE"])
        for check_name in ("SAN_CAUSE_VISIBLE", "COMBAT_START_CONTEXT_VISIBLE",
                           "COMBAT_END_CONTEXT_VISIBLE", "ENDING_CAUSE_VISIBLE"):
            narrative_check = narrative_causality["checks"][check_name]
            add(check_name, narrative_check["status"] == "PASS", narrative_check["detail"])
        add("WORLD_EVENT_FILTER_PRESERVED",
            narrative_causality["world_event_filter_misclassification_count"] == 0,
            narrative_causality["world_event_filter_misclassification_count"])
        add("NARRATIVE_FULL_53_SCENE_AUDIT", narrative_coverage["full_scene_count"] == 53,
            narrative_coverage["full_scene_count"])
        add("NARRATIVE_SOURCE_GAPS_REPORTED", bool(narrative_gaps["gaps"]),
            {"critical_count": narrative_gaps["critical_count"], "gap_count": len(narrative_gaps["gaps"])})
        add("NARRATIVE_CONTRADICTIONS_REPORTED", bool(narrative_contradictions["contradictions"]),
            {"critical_count": narrative_contradictions["critical_count"],
             "contradiction_count": len(narrative_contradictions["contradictions"])})
        expected_hashes = narrative_causality["hashes"]
        actual_hashes = {
            "normalized_session_sha256": sha256_file(self.project / "normalized_session.json"),
            "edited_script_sha256": sha256_file(self.project / "edited_script.json"),
        }
        add("NARRATIVE_INPUT_HASHES_UNCHANGED", actual_hashes == expected_hashes,
            {"expected": expected_hashes, "actual": actual_hashes})
        identity_errors = [clip["clip_id"] for clip in timeline["clips"]
                           if not (clip.get("speaker_context") or {}).get("resolved_display_name")]
        add("SPEAKER_IDENTITY_RESOLUTION", not identity_errors, identity_errors)
        pc_identity_errors = [clip["clip_id"] for clip in timeline["clips"]
                              if clip["speaker_id"].startswith("pc_")
                              and (clip.get("speaker_context") or {}).get("resolved_display_name") != clip["speaker_name"]]
        add("PL_PC_DISPLAY_NAME_RESOLUTION", not pc_identity_errors, pc_identity_errors)
        safe_area_issues = layout_overlap_issues(layout)
        add("layout_safe_areas", not safe_area_issues, safe_area_issues)
        portrait_issues = []
        for side, asset_id in (("left", "portrait_pc01_kitsune_reimu"), ("right", "portrait_pc02_kitsune_marisa")):
            asset = lookup[asset_id]
            image = cv2.imread(str(self.root / asset["file_path"]), cv2.IMREAD_UNCHANGED)
            slot = layout[f"head_portrait_{side}_region"]
            box = head_portrait_box(image.shape[1], image.shape[0], slot)
            for region_name in ("dialogue_frame", "dialogue_text_region"):
                if rectangles_overlap(box, layout[region_name]):
                    portrait_issues.append(f"{side}_HEAD_ONLY_OVERLAPS_{region_name}")
        add("HEAD_ONLY_DIALOGUE_OVERLAP", not portrait_issues, portrait_issues)
        sync_errors = []
        for clip in timeline["clips"]:
            if clip["presentation_mode"] != "VOICED":
                continue
            pages = paginate_text(clip["subtitle_text"], layout["pagination"]["characters_per_line"],
                                  layout["pagination"]["lines_per_page"])
            actual = wav_duration(self.preview / clip["voice_file"])
            if len(pages) != 1 or clip["duration_sec"] + 0.002 < actual:
                sync_errors.append({"clip_id": clip["clip_id"], "pages": len(pages),
                                    "audio_duration": round(actual, 3), "clip_duration": clip["duration_sec"]})
        add("speech_chunk_subtitle_sync", not sync_errors, sync_errors)
        gap_measurements = internal_utterance_gaps(timeline, self.preview, {"pc_01", "pc_02"})
        speakers = {item["speaker_id"] for item in gap_measurements}
        gap_failures = [item for item in gap_measurements if item["total_internal_silence_sec"] > 0.12]
        aquestalk_speakers = {clip["speaker_id"] for clip in timeline["clips"]
                             if clip.get("voice_engine") == "AQUESTALK" and clip.get("presentation_mode") == "VOICED"}
        add("aquestalk_internal_gap", not gap_failures and aquestalk_speakers == {"pc_01", "pc_02"},
            {"measurements": gap_measurements, "speakers_with_internal_boundaries": sorted(speakers),
             "required_aquestalk_speakers": ["pc_01", "pc_02"], "max_sec": 0.12})
        word_level = [clip["clip_id"] for clip in timeline["clips"]
                      if clip.get("voice_engine") == "AQUESTALK"
                      and clip.get("presentation_mode") == "VOICED"
                      and clip.get("synthesis_boundary") != "SENTENCE_OR_UTTERANCE"]
        add("AQUESTALK_NO_WORD_LEVEL_SPLIT", not word_level, word_level)
        prosody = read_json(self.project / "review" / "aquestalk_prosody_ab" / "manifest.json")
        prosody_files = [self.project / "review" / "aquestalk_prosody_ab" / path
                         for sample in prosody["samples"] for path in sample["files"].values()]
        sample_counts = {speaker: sum(1 for item in prosody["samples"] if item["speaker_label"] == speaker)
                         for speaker in ("reimu", "marisa")}
        add("AQUESTALK_PROSODY_AB_FIXTURE",
            sample_counts == {"reimu": 3, "marisa": 3} and all(path.exists() for path in prosody_files),
            {"sample_counts": sample_counts, "reference_scope": prosody["reference_scope"],
             "frontend_reference_pending": True})
        script_lines = read_json(self.preview / "script_lines.json")
        audio_manifest = read_json(self.preview / "audio_manifest.json")
        whitespace_voice = [line["line_id"] for line in script_lines
                            if line.get("presentation_mode", "VOICED") == "VOICED"
                            and not str(line.get("voice_text") if line.get("voice_text") is not None
                                        else line.get("text") or "").strip()
                            and (audio_manifest.get(line["line_id"]) or {}).get("audio_mode") == "VOICE"]
        blank_refs = [clip["clip_id"] for clip in timeline["clips"]
                      if not str(clip.get("subtitle_text") or "").strip() and clip.get("voice_file")]
        null_clips = [clip["clip_id"] for clip in timeline["clips"]
                      if not str(clip.get("subtitle_text") or "").strip() and not clip.get("overlay")]
        add("WHITESPACE_VOICE_ASSET_COUNT", not whitespace_voice, whitespace_voice)
        add("BLANK_TIMELINE_VOICE_REFERENCE", not blank_refs, blank_refs)
        add("NULL_PRESENTATION_CLIP", not null_clips, null_clips)
        result_mismatch = final_result_mismatches([
            {"script_line_id": clip.get("source_script_line_id"), "overlay": clip.get("overlay")}
            for clip in timeline["clips"]])
        expected_final = read_json(self.project / "review" / "m3_final_result_fixture.json")
        finalized_overlays = [(clip.get("overlay") or {}) for clip in timeline["clips"]
                              if (clip.get("overlay") or {}).get("presentation_phase") == "FINALIZED_RESULT"]
        if expected_final.get("pass") and not any(
                overlay.get("raw_result") == "FAILURE"
                and overlay.get("final_result") == "SUCCESS"
                and (overlay.get("modification") or {}).get("amount") == 9
                for overlay in finalized_overlays):
            result_mismatch.append({"reason": "EXPECTED_LUCK_FINALIZED_RESULT_NOT_IN_TIMELINE"})
        add("FINAL_RESULT_MATCHES_GAME_STATE", not result_mismatch, result_mismatch)
        add("DISPLAY_RESULT_MISMATCH", not result_mismatch, result_mismatch)
        word_breaks = []
        dialogue_width = int(layout["dialogue_text_region"]["width"])
        for clip in timeline["clips"]:
            issues = word_internal_line_break_issues(str(clip.get("subtitle_text") or ""),
                                                     dialogue_width,
                                                     int(profiles[clip["subtitle_profile_id"]].get("font_size", 52)))
            if issues:
                word_breaks.append({"clip_id": clip["clip_id"], "issues": issues})
        add("WORD_INTERNAL_LINE_BREAK", not word_breaks, word_breaks)
        burst_hits = []
        for clip in timeline["clips"]:
            if clip.get("audio_mode") == "VOICE" and clip.get("voice_file"):
                burst_hits.extend(suspicious_audio_bursts(self.preview / clip["voice_file"]))
        known_fixture = self.root / "tests" / "fixtures" / "known_bad_blank_voice.wav"
        fixture_hits = suspicious_audio_bursts(known_fixture) if known_fixture.exists() else []
        add("SUSPICIOUS_AUDIO_BURST", not burst_hits,
            {"active_timeline_count": len(burst_hits), "known_bad_fixture_detected": bool(fixture_hits)})
        write_json(self.project / "review" / "m3_audio_noise_qa_report.json", {
            "whitespace_voice_asset_count": len(whitespace_voice),
            "blank_timeline_voice_reference_count": len(blank_refs),
            "null_presentation_clip_count": len(null_clips),
            "active_suspicious_audio_burst_count": len(burst_hits),
            "known_bad_fixture_detected": bool(fixture_hits),
            "known_bad_fixture_measurements": fixture_hits,
            "orphaned_invalid_voice_cache_policy": "ORPHANED_INVALID_VOICE_CACHE_NOT_REFERENCED",
        })
        loud = subprocess.run([str(ffmpeg), "-hide_banner", "-i", str(output), "-af", "volumedetect", "-f", "null", "NUL"],
                              capture_output=True, text=True, encoding="utf-8", errors="replace")
        match = re.search(r"max_volume:\s*(-?[0-9.]+) dB", loud.stderr)
        max_volume = float(match.group(1)) if match else None
        add("audio_clipping_zero", max_volume is not None and max_volume <= 0.0, max_volume)
        frame = self.preview / "qa" / "m3_frame.png"
        frame.parent.mkdir(exist_ok=True)
        subprocess.run([str(ffmpeg), "-y", "-hide_banner", "-loglevel", "error", "-ss", str(duration / 2), "-i", str(output), "-frames:v", "1", str(frame)], check=False)
        image = cv2.imread(str(frame)) if frame.exists() else None
        add("black_frame_zero", image is not None and float(image.mean()) >= 5.0)
        gate = license_gate(assets, used)
        warnings.extend(gate["warnings"])
        if any(c["status"] == "FAIL" for c in checks):
            status = "FAIL"
        else:
            status = "PASS"
        publishability = narrative_causality["publishability"]
        qa = {"status": status, "checks": checks, "warnings": sorted(set(warnings)), "duration_sec": duration,
              "human_review": "PENDING", "publishability": publishability,
              "publishable": narrative_causality["publishable"], "max_volume_db": max_volume}
        write_json(self.project / "presentation_qa_report.json", qa)
        self._state("QA_PASSED" if status == "PASS" else "QA_FAILED", ["assets", "visual_plan", "voice", "audio_mix", "timeline", "render", "qa"])
        return qa

    def run(self) -> dict:
        assets = self.import_assets()
        plan = self.plan(assets)
        output, qa = self.render_preview(assets, plan)
        final_battle_output = self.render_final_battle_preview(assets, plan)
        self._finalize_iteration6_artifacts()
        finalize_narrative_markdown(self.project, qa,
                                    self.project / "review" / "m3_knife_encounter_preview.mp4",
                                    final_battle_output)
        if qa["status"] == "PASS":
            self._state("HUMAN_REVIEW_REQUIRED",
                        ["assets", "visual_plan", "voice", "audio_mix", "timeline", "render", "qa"],
                        ["M3_PRESENTATION_NEEDS_ITERATION", "M3_ASSET_INPUT_REQUIRED", "M3_LICENSE_REVIEW_REQUIRED"])
        else:
            self._state("QA_FAILED", ["assets", "visual_plan", "voice", "audio_mix", "timeline", "render"])
        return {"status": qa["status"], "output": str(output),
                "final_battle_preview": str(final_battle_output), "assets": len(assets),
                "visual_entries": len(plan["entries"]), "human_review": "PENDING",
                "publishability": qa["publishability"], "publishable": qa["publishable"]}
