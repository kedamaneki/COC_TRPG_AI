import json
import tempfile
import unittest
from pathlib import Path

from video_agent.presentation.assets import (
    generate_credits,
    license_gate,
    resolve_background,
    resolve_expression,
    scan_asset_folder,
)
from video_agent.presentation.planner import (
    bgm_category,
    build_visual_plan,
    normalized_overlay,
)
from video_agent.presentation.identity import resolve_display_identity
from video_agent.presentation.system_filter import system_presentation_decision
from video_agent.presentation.system_response_filter import (
    apply_system_response_filter,
    classify_system_response,
    required_fixture,
)
from video_agent.presentation.system_interaction import (
    classify_system_interaction,
    required_fixture as required_system_interaction_fixture,
    resolve_system_interactions,
)
from video_agent.rendering.pipeline import expand_speech_lines, split_speech_chunks, voice_profile_mismatches
from video_agent.rendering.assets import head_portrait_box, layout_overlap_issues, rectangles_overlap
from video_agent.rendering.subtitles import (
    build_ass,
    contrast_ratio,
    paginate_text,
    readability_issues,
    subtitle_contrast_issues,
    kp_subtitle_contrast_issues,
)
from video_agent.voice.engines import wav_duration
from video_agent.voice.qa import internal_utterance_gaps


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "corbitt_clear_001"


def asset(asset_id="asset", status="APPROVED", commercial=True, **extra):
    value = {
        "asset_id": asset_id,
        "status": status,
        "commercial_use": commercial,
        "creator": "creator",
        "source": "source",
        "license": "license",
    }
    value.update(extra)
    return value


class M3AssetTests(unittest.TestCase):
    def test_scanner_accepts_only_supported_media(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "cache" / "test_tmp") as directory:
            folder = Path(directory)
            (folder / "portrait.PNG").write_bytes(b"x")
            (folder / "voice.mp3").write_bytes(b"x")
            (folder / "notes.txt").write_text("x", encoding="utf-8")
            self.assertEqual([p.name for p in scan_asset_folder(folder)], ["portrait.PNG", "voice.mp3"])

    def test_expression_exact_match(self):
        self.assertEqual(resolve_expression("HAPPY", {"HAPPY": "smile", "NORMAL": "normal"}), ("HAPPY", "smile"))

    def test_expression_falls_back_to_normal(self):
        self.assertEqual(resolve_expression("SCARED", {"NORMAL": "normal"}), ("NORMAL", "normal"))

    def test_location_background_wins(self):
        self.assertEqual(resolve_background("house", {"house": "house_bg"}, "GENERIC", "neutral"),
                         ("house_bg", "LOCATION_SPECIFIC"))

    def test_neutral_background_is_final_fallback(self):
        self.assertEqual(resolve_background("house", {}, "GENERIC", "neutral"),
                         ("neutral", "NEUTRAL_FALLBACK"))

    def test_unknown_license_allows_preview_but_blocks_publish(self):
        gate = license_gate([asset(status="UNKNOWN", commercial=None)], {"asset"})
        self.assertTrue(gate["local_preview_allowed"])
        self.assertFalse(gate["publishable"])
        self.assertIn("NON_PUBLISHABLE_ASSET_USED", gate["warnings"])

    def test_blocked_license_blocks_preview(self):
        gate = license_gate([asset(status="BLOCKED")], {"asset"})
        self.assertFalse(gate["local_preview_allowed"])
        self.assertEqual(gate["blocked_assets"], ["asset"])

    def test_approved_commercial_asset_is_publishable(self):
        self.assertTrue(license_gate([asset()], {"asset"})["publishable"])

    def test_credit_generation_deduplicates_text(self):
        assets = [asset("a", credit_text="共通クレジット"), asset("b", credit_text="共通クレジット")]
        self.assertEqual(generate_credits(assets, {"a", "b"}), "共通クレジット\n")


class M3PlanningTests(unittest.TestCase):
    def test_bgm_semantics(self):
        self.assertEqual(bgm_category("SAN_SEQUENCE"), "HORROR")
        self.assertEqual(bgm_category("COMBAT"), "COMBAT")
        self.assertEqual(bgm_category("INVESTIGATION"), "INVESTIGATION")

    def test_san_overlay_is_derived_deterministically(self):
        overlay = normalized_overlay({"overlay": {"type": "SAN"}, "display_text": "現在値: 70、正気度が 3 減少"})
        self.assertEqual((overlay["before"], overlay["after"], overlay["loss"]), (70, 67, 3))

    def test_location_subtitle_does_not_duplicate_overlay(self):
        self.assertIsNone(normalized_overlay({
            "overlay": {"type": "LOCATION_CHANGE", "location": "悪霊の家"},
            "presentation_mode": "SUBTITLE_ONLY",
        }))

    def test_visual_plan_preserves_dice_and_uses_se(self):
        line = {
            "script_line_id": "line", "source_event_ids": ["e"], "scene_id": "scene",
            "speaker_id": "system", "event_type": "DICE_RESULT", "presentation_mode": "OVERLAY_ONLY",
            "overlay": {"type": "SKILL_CHECK", "skill": "目星", "roll": 42}, "display_text": "判定",
        }
        plan = build_visual_plan([line], [{"scene_id": "scene", "scene_type": "SKILL_SEQUENCE", "location_id": "house"}],
                                 {}, {}, "neutral")
        entry = plan["entries"][0]
        self.assertEqual(entry["overlay"]["roll"], 42)
        self.assertEqual(entry["se"], ["se_dice_user"])
        self.assertEqual(plan["missing_location_ids"], ["house"])

    def test_overlay_only_never_gets_portrait(self):
        line = {
            "script_line_id": "line", "source_event_ids": ["e"], "scene_id": "scene",
            "speaker_id": "pc_01", "event_type": "DIALOGUE", "presentation_mode": "OVERLAY_ONLY",
            "overlay": None, "display_text": "text",
        }
        profile = {"pc_01": {"profile_id": "p", "position": "LEFT", "expressions": {"NORMAL": "portrait"}}}
        plan = build_visual_plan([line], [{"scene_id": "scene", "scene_type": "ROLEPLAY", "location_id": None}],
                                 profile, {}, "neutral")
        self.assertIsNone(plan["entries"][0]["portrait"])

    def test_visual_plan_preserves_head_only_portrait_kind(self):
        line = {
            "script_line_id": "line", "source_event_ids": ["e"], "scene_id": "scene",
            "speaker_id": "pc_01", "event_type": "DIALOGUE", "presentation_mode": "VOICED",
            "overlay": None, "display_text": "text",
        }
        profile = {"pc_01": {
            "profile_id": "p", "position": "LEFT", "portrait_kind": "HEAD_ONLY",
            "expressions": {"NORMAL": "portrait"},
        }}
        plan = build_visual_plan([line], [{"scene_id": "scene", "scene_type": "ROLEPLAY", "location_id": None}],
                                 profile, {}, "neutral")
        self.assertEqual(plan["entries"][0]["portrait"]["portrait_kind"], "HEAD_ONLY")

    def test_system_presentation_uses_whitelist(self):
        move = {"speaker_id": "pc_01", "event_type": "LOCATION_CHANGE", "presentation_mode": "SUBTITLE_ONLY",
                "display_text": "システム: 判定なし（自動成功）\n【移動】内部移動", "overlay": None}
        dice = {"speaker_id": "pc_02", "event_type": "DICE_RESULT", "presentation_mode": "OVERLAY_ONLY",
                "display_text": "technical", "overlay": {"type": "SKILL_CHECK", "roll": 42}}
        self.assertFalse(system_presentation_decision(move)["allowed"])
        self.assertTrue(system_presentation_decision(dice)["allowed"])

    def test_system_whitelist_requires_structured_overlay(self):
        technical = {"speaker_id": "pc_01", "event_type": "DICE_RESULT", "presentation_mode": "OVERLAY_ONLY",
                     "display_text": "システム内部確定", "overlay": None}
        decision = system_presentation_decision(technical)
        self.assertFalse(decision["allowed"])
        self.assertEqual(decision["reason"], "WHITELIST_REQUIRES_STRUCTURED_OVERLAY")

    def test_system_push_yes_and_no_are_hidden(self):
        for answer in ("Yes", "No"):
            events = [
                {"speaker_id": "system", "role": "SYSTEM", "event_type": "PUSH_PROMPT", "text": "Push?"},
                {"speaker_id": "pc_01", "event_type": "DIALOGUE", "text": answer},
            ]
            self.assertEqual(classify_system_response(events, 1)["action"], "HIDE")

    def test_npc_and_kp_acknowledgements_remain_dialogue(self):
        for prompt in (
            {"speaker_id": "npc_01", "role": "NPC", "event_type": "DIALOGUE", "text": "来ますか？"},
            {"speaker_id": "kp", "role": "KP", "event_type": "KP_DESCRIPTION", "text": "本当に扉を開けますか？"},
        ):
            events = [prompt, {"speaker_id": "pc_01", "event_type": "DIALOGUE", "text": "はい"}]
            self.assertEqual(classify_system_response(events, 1)["action"], "KEEP")

    def test_adjacent_system_result_context_hides_short_response(self):
        events = [
            {"script_line_id": "result1", "speaker_id": "pc_02", "event_type": "DICE_RESULT",
             "presentation_mode": "OVERLAY_ONLY", "display_text": "技能失敗", "overlay": {"type": "SKILL_CHECK"}},
            {"script_line_id": "answer", "speaker_id": "pc_02", "event_type": "DIALOGUE",
             "presentation_mode": "VOICED", "display_text": "yes"},
            {"script_line_id": "result2", "speaker_id": "pc_02", "event_type": "DICE_RESULT",
             "presentation_mode": "OVERLAY_ONLY", "display_text": "プッシュ処理", "overlay": {"type": "SKILL_CHECK"}},
        ]
        filtered, report = apply_system_response_filter(events)
        self.assertNotIn("answer", [item["script_line_id"] for item in filtered])
        self.assertEqual(report["system_responses_hidden"], 1)

    def test_required_system_response_fixture_has_no_false_positives(self):
        fixture = required_fixture()
        self.assertTrue(all(item["pass"] for item in fixture["cases"]))
        self.assertEqual(fixture["false_positive_count"], 0)

    def test_tabletop_system_prompt_and_response_become_kp_pl_dialogue(self):
        events = [
            {"script_line_id": "p", "source_event_ids": ["evt:p"], "speaker_id": "system",
             "role": "SYSTEM", "event_type": "PUSH_PROMPT", "text": "Push? [yes/no]"},
            {"script_line_id": "r", "source_event_ids": ["evt:r"], "speaker_id": "pc_02",
             "event_type": "DIALOGUE", "display_text": "Yes"},
        ]
        presented, report = resolve_system_interactions(events, {"pc_02": "player_marisa"})
        self.assertEqual([item["presentation_as"] for item in presented], ["KP", "PL"])
        self.assertEqual([item.get("display_text") for item in presented], ["プッシュしますか？", "Yes"])
        self.assertEqual(presented[1]["player_id"], "player_marisa")
        self.assertEqual(report["prompt_response_pairs"], 1)

    def test_luck_prompt_is_recovered_from_explicit_followup_fact(self):
        events = [
            {"script_line_id": "fail", "source_event_ids": ["evt:fail"], "speaker_id": "pc_02",
             "event_type": "DICE_RESULT", "display_text": "目星 失敗"},
            {"script_line_id": "answer", "source_event_ids": ["evt:answer"], "speaker_id": "pc_02",
             "event_type": "DIALOGUE", "display_text": "yes"},
            {"script_line_id": "result", "source_event_ids": ["evt:result"], "speaker_id": "pc_02",
             "event_type": "DICE_RESULT", "display_text": "【幸運消費】PLの意志により幸運を 9 消費"},
        ]
        presented, report = resolve_system_interactions(events, {"pc_02": "player_marisa"})
        prompt = next(item for item in presented if item.get("presentation_origin") == "SYSTEM_PROMPT")
        self.assertEqual(prompt["display_text"], "幸運を9ポイント消費して成功にしますか？")
        self.assertEqual(prompt["prompt_grounding"], "FOLLOWUP_EXPLICIT_LUCK_SPEND")
        self.assertEqual(prompt["source_event_ids"], ["evt:result"])
        self.assertEqual(report["ungrounded_kp_prompt_count"], 0)

    def test_technical_and_ambiguous_system_interactions_are_not_presented_as_kp(self):
        technical = {"speaker_id": "system", "role": "SYSTEM", "event_type": "CONFIRMATION_PROMPT",
                     "text": "checkpoint resume?"}
        self.assertEqual(classify_system_interaction(technical)["classification"],
                         "TECHNICAL_SYSTEM_INTERACTION")
        fixture = required_system_interaction_fixture()
        self.assertTrue(all(item["pass"] for item in fixture["cases"]))

    def test_pl_and_pc_display_names_can_be_resolved_separately(self):
        schema = json.loads((ROOT / "config" / "speaker_identity_m3.json").read_text(encoding="utf-8"))
        fallback = {"display_name": "エレノア教授", "voice_profile_id": "aq_marisa_default",
                    "subtitle_profile_id": "subtitle_marisa"}
        pl = resolve_display_identity("player_marisa", "PL", "pc_02", schema, fallback)
        pc = resolve_display_identity("player_marisa", "PC", "pc_02", schema, fallback)
        unknown = resolve_display_identity("pc_02", "UNKNOWN", "pc_02", schema, fallback)
        self.assertEqual(pl["resolved_display_name"], "魔理沙")
        self.assertEqual(pc["resolved_display_name"], "エレノア教授")
        self.assertEqual(unknown["resolved_display_name"], "エレノア教授")
        self.assertEqual(unknown["resolution"], "CURRENT_MAPPING_FALLBACK")


class M3SubtitleTests(unittest.TestCase):
    def test_long_text_is_paginated_without_loss(self):
        text = "あ" * 200
        pages = paginate_text(text)
        self.assertGreater(len(pages), 1)
        self.assertEqual("".join(page.replace("\\N", "") for page in pages), text)

    def test_zero_san_loss_is_shown_as_plus_minus_zero(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "cache" / "test_tmp") as directory:
            path = Path(directory) / "sub.ass"
            clip = {
                "start_sec": 0.0, "duration_sec": 2.0, "subtitle_text": "SAN判定", "speaker_name": "SYSTEM",
                "subtitle_profile_id": "sub", "presentation_mode": "OVERLAY_ONLY",
                "overlay": {"type": "SAN", "before": 70, "after": 70, "loss": 0},
            }
            build_ass(path, [clip], {"sub": {"text_color": "#FFFFFF"}})
            self.assertIn("±0", path.read_text(encoding="utf-8-sig"))

    def test_layout_separates_name_and_dialogue_regions(self):
        layout = json.loads((ROOT / "config" / "presentation_layout_m3.json").read_text(encoding="utf-8"))
        name = layout["speaker_name_region"]
        dialogue = layout["dialogue_text_region"]
        self.assertLessEqual(name["y"] + name["height"], dialogue["y"])
        self.assertEqual(readability_issues(layout, {
            "test": {"font_size": layout["dialogue_font_size"], "outlines": [
                {"width": layout["inner_outline_width"]}, {"width": layout["outer_outline_width"]}
            ]}
        }), [])

    def test_speech_chunks_preserve_text_and_provenance(self):
        text = "最初の長い発言です。次の意味単位へ進みます。さらに説明を続け、最後まで内容を変えません。"
        source_ids = ["norm:1", "raw:1"]
        lines = expand_speech_lines([{
            "text": text, "voice_text": text, "source_event_ids": source_ids,
            "speaker_id": "kp", "presentation_mode": "VOICED", "script_line_id": "script_1",
        }], 20)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(line["text"] for line in lines), text)
        self.assertTrue(all(line["source_event_ids"] == source_ids for line in lines))
        self.assertTrue(all(line["source_script_line_id"] == "script_1" for line in lines))

    def test_voice_profile_mismatch_is_explicit(self):
        mismatch = voice_profile_mismatches([{
            "clip_id": "clip", "presentation_mode": "VOICED",
            "expected_voice_profile_id": "aq_marisa_default", "actual_voice_profile_id": "m1_vv_pc2",
        }])
        self.assertEqual(mismatch[0]["expected"], "aq_marisa_default")

    def test_high_luminance_text_rejects_high_luminance_adjacent_outline(self):
        profiles = {"yellow": {
            "text_color": "#FFF040",
            "outlines": [{"width": 4, "color": "#FFFFFF"}],
        }}
        issues = subtitle_contrast_issues(profiles)
        self.assertIn("yellow:BOTH_TEXT_AND_OUTLINE_HIGH_LUMINANCE", issues)
        self.assertIn("yellow:LOW_TEXT_OUTLINE_CONTRAST", issues)

    def test_all_registered_subtitle_profiles_have_adjacent_contrast(self):
        raw = json.loads((ROOT / "config" / "subtitles" / "defaults.json").read_text(encoding="utf-8"))
        profiles = {item["subtitle_profile_id"]: item for item in raw}
        self.assertEqual(subtitle_contrast_issues(profiles), [])
        self.assertGreaterEqual(
            contrast_ratio(profiles["subtitle_marisa"]["text_color"],
                           profiles["subtitle_marisa"]["outlines"][0]["color"]),
            3.0,
        )
        self.assertEqual(kp_subtitle_contrast_issues(profiles["subtitle_kp"]), [])

    def test_aquestalk_chunking_does_not_split_at_commas_or_words(self):
        sentence = "長い発言でも、読点の位置では音声を切らず、ひとつの自然な文として合成します。"
        chunks = split_speech_chunks(sentence, 18)
        self.assertEqual(chunks, [sentence])
        self.assertTrue(all(chunk.endswith(("。", "！", "？", "!", "?", "\n")) for chunk in chunks))

    def test_head_only_slots_obey_safe_areas(self):
        layout = json.loads((ROOT / "config" / "presentation_layout_m3.json").read_text(encoding="utf-8"))
        self.assertEqual(layout_overlap_issues(layout), [])
        for side in ("left", "right"):
            slot = layout[f"head_portrait_{side}_region"]
            box = head_portrait_box(480, 720, slot)
            self.assertGreaterEqual(box["x"], slot["x"] + slot["safe_margin"])
            self.assertGreaterEqual(box["y"], slot["y"] + slot["safe_margin"])
            self.assertLessEqual(box["x"] + box["width"], slot["x"] + slot["width"] - slot["safe_margin"])
            self.assertLessEqual(box["y"] + box["height"], slot["y"] + slot["height"] - slot["safe_margin"])
            self.assertFalse(rectangles_overlap(box, layout["dialogue_frame"]))
            self.assertFalse(rectangles_overlap(box, layout["dialogue_text_region"]))


class M3GeneratedArtifactTests(unittest.TestCase):
    def test_full_plan_covers_every_edited_line(self):
        edited = json.loads((PROJECT / "edited_script.json").read_text(encoding="utf-8"))
        plan = json.loads((PROJECT / "visual_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(len(plan["entries"]), len(edited["lines"]))
        self.assertEqual(len(plan["entries"]), 425)

    def test_expected_missing_backgrounds_are_reported(self):
        report = json.loads((PROJECT / "missing_assets_report.json").read_text(encoding="utf-8"))
        backgrounds = [item for item in report["missing"] if item["type"] == "background"]
        self.assertEqual(len(backgrounds), 10)
        self.assertTrue(all(item["fallback_asset_id"] == "bg_neutral_user" for item in backgrounds))

    def test_audio_plan_has_ducking_and_limiter(self):
        mix = json.loads((PROJECT / "audio_mix_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(mix["buses"]["bgm"]["duck_trigger"], "speech_active")
        self.assertLess(mix["buses"]["bgm"]["duck_gain_db"], 0)
        self.assertLessEqual(mix["limiter"], 1.0)

    def test_machine_qa_passes_and_review_remains_pending(self):
        qa = json.loads((PROJECT / "presentation_qa_report.json").read_text(encoding="utf-8"))
        self.assertEqual(qa["status"], "PASS")
        self.assertEqual(qa["human_review"], "PENDING")
        self.assertTrue((PROJECT / "review" / "m3_scene_preview.mp4").exists())

    def test_iteration3_system_and_identity_qa_pass(self):
        qa = json.loads((PROJECT / "presentation_qa_report.json").read_text(encoding="utf-8"))
        checks = {item["name"]: item for item in qa["checks"]}
        for name in ("SYSTEM_PRESENTATION_WHITELIST", "KP_SUBTITLE_CONTRAST",
                     "SPEAKER_IDENTITY_RESOLUTION", "PL_PC_DISPLAY_NAME_RESOLUTION",
                     "AQUESTALK_PROSODY_AB_FIXTURE", "AQUESTALK_NO_WORD_LEVEL_SPLIT"):
            self.assertEqual(checks[name]["status"], "PASS", name)

    def test_iteration3_review_artifacts_exist(self):
        review = PROJECT / "review"
        for name in ("m3_scene_preview_before_iteration3.mp4", "m3_scene_preview_after_iteration3.mp4",
                     "m3_kp_subtitle_fixture.png", "m3_system_presentation_fixture.png"):
            self.assertTrue((review / name).exists(), name)
        manifest = json.loads((review / "aquestalk_prosody_ab" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(sum(item["speaker_label"] == "reimu" for item in manifest["samples"]), 3)
        self.assertEqual(sum(item["speaker_label"] == "marisa" for item in manifest["samples"]), 3)

    def test_iteration4_system_response_filter_artifacts_exist(self):
        review = PROJECT / "review"
        for name in ("m3_scene_preview_before_iteration4.mp4", "m3_scene_preview_after_iteration4.mp4",
                     "m3_system_response_fixture.json"):
            self.assertTrue((review / name).exists(), name)
        report = json.loads((PROJECT / "system_response_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["system_response_leak_count"], 0)
        self.assertEqual(report["false_positive_count"], 0)

    def test_iteration5_system_interaction_artifacts_and_qa_exist(self):
        review = PROJECT / "review"
        for name in ("m3_scene_preview_before_iteration5.mp4", "m3_scene_preview_after_iteration5.mp4",
                     "m3_system_interaction_fixture.json"):
            self.assertTrue((review / name).exists(), name)
        report = json.loads((PROJECT / "system_interaction_report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["tabletop_interactions_detected"], 1)
        self.assertEqual(report["tabletop_interactions_presented"], 1)
        self.assertEqual(report["prompt_response_pairs"], 1)
        self.assertEqual(report["ambiguous_pairs"], 0)
        self.assertEqual(report["pl_voice_fallback_count"], 0)
        self.assertEqual(report["ungrounded_kp_prompt_count"], 0)
        qa = json.loads((PROJECT / "presentation_qa_report.json").read_text(encoding="utf-8"))
        checks = {item["name"]: item["status"] for item in qa["checks"]}
        for name in ("TABLETOP_SYSTEM_INTERACTION_PRESENTED", "SYSTEM_INTERACTION_PAIRING_VALID",
                     "TECHNICAL_SYSTEM_INTERACTION_HIDDEN", "SYSTEM_RESPONSE_CONTEXT_VISIBLE",
                     "PL_PC_IDENTITY_VALID", "UNGROUNDED_KP_PROMPT"):
            self.assertEqual(checks[name], "PASS", name)

    def test_marisa_uses_expected_aquestalk_profile(self):
        timeline = json.loads((ROOT / "projects" / "m3_scene_preview" / "video_timeline.json").read_text(encoding="utf-8"))
        clips = [clip for clip in timeline["clips"] if clip["speaker_id"] == "pc_02" and clip["presentation_mode"] == "VOICED"]
        self.assertTrue(clips)
        self.assertTrue(all(clip["voice_engine"] == "AQUESTALK" for clip in clips))
        self.assertTrue(all(clip["expected_voice_profile_id"] == "aq_marisa_default" for clip in clips))
        self.assertEqual(voice_profile_mismatches(clips), [])

    def test_voiced_chunks_follow_real_wav_duration(self):
        preview = ROOT / "projects" / "m3_scene_preview"
        timeline = json.loads((preview / "video_timeline.json").read_text(encoding="utf-8"))
        layout = json.loads((ROOT / "config" / "presentation_layout_m3.json").read_text(encoding="utf-8"))
        for clip in timeline["clips"]:
            if clip["presentation_mode"] != "VOICED":
                continue
            self.assertEqual(len(paginate_text(clip["subtitle_text"],
                                               layout["pagination"]["characters_per_line"],
                                               layout["pagination"]["lines_per_page"])), 1)
            self.assertGreaterEqual(clip["duration_sec"] + 0.002, wav_duration(preview / clip["voice_file"]))

    def test_internal_chunks_have_no_added_gap_and_final_chunk_keeps_tail_gap(self):
        timeline = json.loads((ROOT / "projects" / "m3_scene_preview" / "video_timeline.json").read_text(encoding="utf-8"))
        groups = {}
        for clip in timeline["clips"]:
            chunk = clip.get("speech_chunk") or {}
            if int(chunk.get("count", 1)) > 1:
                groups.setdefault(clip["source_script_line_id"], []).append(clip)
        self.assertTrue(groups)
        for clips in groups.values():
            clips.sort(key=lambda item: item["speech_chunk"]["index"])
            self.assertTrue(all(clip["post_speech_gap_sec"] == 0.0 for clip in clips[:-1]))
            self.assertGreater(clips[-1]["post_speech_gap_sec"], 0.0)

    def test_aquestalk_internal_silence_is_bounded_for_reimu_and_marisa(self):
        preview = ROOT / "projects" / "m3_scene_preview"
        timeline = json.loads((preview / "video_timeline.json").read_text(encoding="utf-8"))
        measurements = internal_utterance_gaps(timeline, preview, {"pc_01", "pc_02"})
        voiced_speakers = {clip["speaker_id"] for clip in timeline["clips"]
                           if clip["presentation_mode"] == "VOICED" and clip["voice_engine"] == "AQUESTALK"}
        self.assertEqual(voiced_speakers, {"pc_01", "pc_02"})
        self.assertTrue(all(item["timeline_gap_sec"] == 0.0 for item in measurements))
        self.assertTrue(all(item["total_internal_silence_sec"] <= 0.12 for item in measurements))

    def test_before_after_and_readability_fixture_exist(self):
        review = PROJECT / "review"
        for name in ("m3_scene_preview_before_iteration.mp4", "m3_scene_preview_after_iteration.mp4",
                     "m3_subtitle_readability_fixture.png", "m3_scene_preview_before_iteration2.mp4",
                     "m3_scene_preview_after_iteration2.mp4", "m3_subtitle_palette_fixture.png"):
            self.assertTrue((review / name).exists(), name)

    def test_m3_state_is_resumable_and_not_closed(self):
        state = json.loads((PROJECT / "m3_project_state.json").read_text(encoding="utf-8"))
        self.assertEqual(state["status"], "HUMAN_REVIEW_REQUIRED")
        self.assertIn("M3_PRESENTATION_NEEDS_ITERATION", state["phase_decisions"])
        self.assertIn("visual_plan", state["completed_steps"])
        self.assertIn("qa", state["completed_steps"])


if __name__ == "__main__":
    unittest.main()
