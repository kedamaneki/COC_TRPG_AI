import json
import unittest
from pathlib import Path

from video_agent.presentation.final_result import (apply_final_result_overrides,
                                                    final_result_mismatches)
from video_agent.rendering.pipeline import (build_synthetic_lines, expand_speech_lines,
                                            is_whitespace_only, timeline_from_lines)
from video_agent.rendering.subtitles import (LINE_END_PROHIBITED, LINE_START_PROHIBITED,
                                             japanese_line_breaks, speaker_name_contrast_issues,
                                             word_internal_line_break_issues)
from video_agent.voice.qa import suspicious_audio_bursts


ROOT = Path(__file__).resolve().parents[1]


class Iteration6VoiceGuardTests(unittest.TestCase):
    def test_whitespace_only_voice_skip(self):
        self.assertTrue(is_whitespace_only("   \n  "))
        self.assertEqual(expand_speech_lines([{"text": " ", "presentation_mode": "VOICED"}]), [])

    def test_newline_only_voice_skip(self):
        self.assertTrue(is_whitespace_only("\r\n\t"))
        self.assertEqual(build_synthetic_lines({"lines": [{"text": "\n", "presentation_mode": "VOICED"}]}), [])

    def test_silence_clip_has_no_wav(self):
        lines = [{"line_id": "line_001", "source_event_ids": ["e"], "speaker_id": "system",
                  "text": "判定", "subtitle_profile_id": "subtitle_kp",
                  "presentation_mode": "OVERLAY_ONLY", "overlay": {"type": "SKILL_CHECK"}}]
        audio = {"line_001": {"audio_mode": "SILENCE", "project_path": None, "engine": "NONE",
                              "voice_profile_id": None, "duration_sec": 0.15}}
        timeline = timeline_from_lines(lines, audio, {"system": {"display_name": "SYSTEM"}}, 0.35, "bg")
        clip = timeline["clips"][0]
        self.assertEqual(clip["audio_mode"], "SILENCE")
        self.assertIsNone(clip["voice_file"])

    def test_blank_cache_is_ignored(self):
        spec = {"speech_chunking": {"enabled": True}, "lines": [
            {"text": "\t", "presentation_mode": "VOICED", "overlay": None},
            {"text": "話す", "presentation_mode": "VOICED"},
        ]}
        self.assertEqual([line["text"] for line in build_synthetic_lines(spec)], ["話す"])

    def test_known_bad_blank_voice_is_detected(self):
        hits = suspicious_audio_bursts(ROOT / "tests" / "fixtures" / "known_bad_blank_voice.wav")
        self.assertTrue(hits)
        self.assertGreater(hits[0]["high_frequency_ratio"], 0.18)

    def test_null_presentation_clip_is_prevented(self):
        lines = build_synthetic_lines({"speech_chunking": {"enabled": True}, "lines": [
            {"text": "", "presentation_mode": "SUBTITLE_ONLY", "overlay": None},
            {"text": "", "presentation_mode": "OVERLAY_ONLY", "overlay": {"type": "SAN"}},
        ]})
        self.assertEqual(len(lines), 1)
        self.assertIsNotNone(lines[0]["overlay"])


class Iteration6FinalResultTests(unittest.TestCase):
    def test_luck_override_final_result(self):
        lines, changes = apply_final_result_overrides([{
            "script_line_id": "knife", "display_text": "失敗\n【幸運消費】幸運を 9 消費し、regular 成功に書き換えた",
            "overlay": {"type": "SKILL_CHECK", "skill": "目星", "target": 50,
                        "roll": 59, "result": "失敗"},
        }])
        overlay = lines[0]["overlay"]
        self.assertEqual((overlay["raw_result"], overlay["final_result"]), ("FAILURE", "SUCCESS"))
        self.assertEqual(overlay["modification"], {"type": "LUCK_SPEND", "amount": 9})
        self.assertEqual(overlay["presentation_phase"], "FINALIZED_RESULT")
        self.assertEqual(len(changes), 1)

    def test_final_result_mismatch_detection(self):
        bad = [{"script_line_id": "x", "overlay": {
            "type": "SKILL_CHECK", "final_result": "FAILURE",
            "modification": {"type": "LUCK_SPEND", "amount": 9}}}]
        self.assertEqual(final_result_mismatches(bad)[0]["reason"], "LUCK_SPEND_NOT_DISPLAYED_AS_SUCCESS")

    def test_knife_flow_preserves_failure_then_final_success(self):
        source = [
            {"script_line_id": "raw", "display_text": "失敗",
             "overlay": {"type": "SKILL_CHECK", "target": 50, "roll": 59, "result": "失敗"}},
            {"script_line_id": "final", "display_text": "【幸運消費】幸運を9消費しregular 成功に書き換えた",
             "overlay": {"type": "SKILL_CHECK", "target": 50, "roll": 59, "result": "失敗"}},
            {"script_line_id": "knife", "display_text": "ナイフが襲いかかる", "overlay": None},
            {"script_line_id": "san", "display_text": "SANチェック", "overlay": {"type": "SAN"}},
        ]
        result, _ = apply_final_result_overrides(source)
        self.assertEqual(result[0]["overlay"]["final_result"], "FAILURE")
        self.assertEqual(result[1]["overlay"]["final_result"], "SUCCESS")
        self.assertEqual([x["script_line_id"] for x in result], ["raw", "final", "knife", "san"])


class Iteration6SubtitleTests(unittest.TestCase):
    def test_japanese_line_break_prefers_bunsetsu(self):
        text = "探索者は古いナイフを慎重に調べ、その異様な錆を睨みつける。"
        lines, _ = japanese_line_breaks(text, 520, 52)
        self.assertGreater(len(lines), 1)
        self.assertEqual("".join(lines), text)

    def test_no_word_internal_break(self):
        text = "異様な錆の下に隠れた血痕を睨みつける。"
        lines, _ = japanese_line_breaks(text, 480, 52)
        self.assertNotIn(("睨みつけ", "る。"), list(zip(lines, lines[1:])))
        self.assertEqual(word_internal_line_break_issues(text, 480, 52), [])

    def test_kinsoku_line_start(self):
        lines, _ = japanese_line_breaks("これは古いナイフで、危険な呪物です。", 430, 52)
        self.assertTrue(all(not line or line[0] not in LINE_START_PROHIBITED for line in lines))

    def test_kinsoku_line_end(self):
        lines, _ = japanese_line_breaks("探索者は『地下室の扉』を慎重に開く。", 430, 52)
        self.assertTrue(all(not line or line[-1] not in LINE_END_PROHIBITED for line in lines))

    def test_speaker_name_contrast(self):
        profiles = {item["subtitle_profile_id"]: item
                    for item in json.loads((ROOT / "config" / "subtitles" / "defaults.json").read_text(encoding="utf-8"))}
        self.assertEqual(speaker_name_contrast_issues(profiles), [])


if __name__ == "__main__":
    unittest.main()

