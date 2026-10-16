import unittest

from video_agent.normalizer import normalize_session


def source(unified=None, session=None):
    return {
        "root": "fixture", "source_files": [],
        "result": {"session_id": "adjudication_fixture", "scenario_file": "fixture.json"},
        "scenarios": [{"scenario_meta": {"title": "fixture"}, "locations": {}}],
        "pcs": {"pc_01": {"profile": {"name": "探索者"}}}, "npcs": {},
        "unified_events": unified or [], "session_events": session or [],
    }


class AdjudicationNormalizerTests(unittest.TestCase):
    def test_structured_san_tuple(self):
        item = normalize_session(source(unified=[{
            "event_id": "u1", "event_type": "INVESTIGATION_ROLLED",
            "adjudication_id": "adj_1", "actor": "pc_01",
            "san": {"before": 70, "target": 70, "roll": 40,
                    "result": "SUCCESS", "loss": 0, "after": 70},
        }]))["events"][0]
        self.assertEqual(item["san"]["normalization_source"], "STRUCTURED")
        self.assertEqual(
            {k: item["san"][k] for k in ("before", "roll", "result", "loss", "after")},
            {"before": 70, "roll": 40, "result": "SUCCESS", "loss": 0, "after": 70},
        )

    def test_legacy_san_parse_with_provenance(self):
        item = normalize_session(source(session=[{
            "channel": "IC", "location": "cellar",
            "text": "システム: 【SANチェック】1d100 ＞ 40 ＞ 成功（現在値:70）。正気度が 0 減少した。",
            "meta": {"actor_id": "pc_01", "roll_type": "san"},
        }]))["events"][0]
        self.assertTrue(item["san"]["derived_from_legacy_text"])
        self.assertEqual((item["san"]["before"], item["san"]["after"]), (70, 70))

    def test_legacy_luck_preserves_raw_final_and_resource(self):
        item = normalize_session(source(session=[{
            "channel": "IC", "location": "cellar",
            "text": (
                "システム: 【技能:目星】CC(1d100<=50) ＞ 出目:59 ＞ 失敗\n"
                "【幸運消費】PLの意志により幸運を 9 消費し、regular 成功に書き換えた（残り幸運: 41）"
            ),
            "meta": {"actor_id": "pc_01", "roll_type": "skill"},
        }]))["events"][0]
        self.assertEqual((item["dice"]["target_value"], item["dice"]["roll"]), (50, 59))
        self.assertEqual((item["dice"]["raw_result"], item["dice"]["final_result"]),
                         ("FAILURE", "REGULAR_SUCCESS"))
        self.assertEqual(item["modifier"]["resource_before"], 50)
        self.assertEqual(item["modifier"]["resource_after"], 41)

    def test_adjudication_merge_and_contradiction(self):
        normalized = normalize_session(source(unified=[
            {"event_id": "a", "event_type": "INVESTIGATION_DECLARED",
             "adjudication_id": "adj_2", "actor": "pc_01"},
            {"event_id": "b", "event_type": "INVESTIGATION_ROLLED",
             "adjudication_id": "adj_2", "actor": "pc_01",
             "resolution_mode": "ROLL", "skill_or_stat": "目星",
             "target_value": 50, "roll": 42, "raw_result": "REGULAR_SUCCESS",
             "final_result": "REGULAR_SUCCESS"},
        ]))
        self.assertEqual(normalized["events"][0]["dice"]["roll"], 42)
        self.assertFalse([w for w in normalized["metadata"]["conversion_warnings"]
                          if w["code"] == "NORMALIZATION_SOURCE_CONTRADICTION"])

    def test_combat_san_snapshot_is_not_an_adjudication(self):
        item = normalize_session(source(unified=[{
            "event_id": "combat1", "event_type": "COMBAT_ACTION_RESOLVED",
            "adjudication_id": "adj_combat", "actor": "pc_01",
            "combat_id": "c1", "SAN_before": 70, "SAN_after": 70,
        }]))["events"][0]
        self.assertIsNone(item["san"])

    def test_numeric_and_japanese_success_are_canonical_equal(self):
        normalized = normalize_session(source(unified=[
            {"event_id": "a", "event_type": "INVESTIGATION_ROLLED",
             "adjudication_id": "adj_same", "actor": "pc_01",
             "resolution_mode": "ROLL", "target_value": 50, "roll": 20,
             "result_level": 3, "raw_result": 3, "final_result": 3},
            {"event_id": "b", "event_type": "SKILL_CHECK",
             "adjudication_id": "adj_same", "actor": "pc_01",
             "resolution_mode": "ROLL", "target_value": 50, "roll": 20,
             "result_level": "ハード成功", "raw_result": "HARD_SUCCESS",
             "final_result": "ハード成功"},
        ]))
        self.assertFalse([w for w in normalized["metadata"]["conversion_warnings"]
                          if w["code"] == "NORMALIZATION_SOURCE_CONTRADICTION"])
        self.assertEqual(normalized["events"][0]["dice"]["result_level"], "HARD_SUCCESS")

    def test_luck_pre_and_post_modifier_are_one_phase_aware_adjudication(self):
        normalized = normalize_session(source(unified=[
            {"event_id": "pre", "event_type": "INVESTIGATION_ROLLED",
             "adjudication_id": "adj_luck", "actor": "pc_01",
             "resolution_mode": "ROLL", "target_value": 50, "roll": 59,
             "raw_result": "FAILURE", "final_result": "FAILURE"},
            {"event_id": "post", "event_type": "SKILL_CHECK",
             "adjudication_id": "adj_luck", "actor": "pc_01",
             "resolution_mode": "ROLL", "target_value": 50, "roll": 59,
             "raw_result": "FAILURE", "final_result": "REGULAR_SUCCESS",
             "modifier": {"type": "LUCK_SPEND", "amount": 9}},
        ]))
        self.assertFalse([w for w in normalized["metadata"]["conversion_warnings"]
                          if w["code"] == "NORMALIZATION_SOURCE_CONTRADICTION"])
        self.assertTrue(all(e["dice"]["final_result"] == "REGULAR_SUCCESS"
                            for e in normalized["events"]))


if __name__ == "__main__":
    unittest.main()
