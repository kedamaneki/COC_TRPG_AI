import unittest

from video_agent.presentation.replay_summary import (
    audit_summary_bridges,
    audit_summary_plan,
    classify_replay_events,
    make_summary_bridge,
    make_summary_block,
)


class ReplaySummaryLayerV1Tests(unittest.TestCase):
    def setUp(self):
        self.events = [
            {"raw_event_offset": 1, "event_id": "e1", "event_type": "LOCATION_CHANGE",
             "location": "basement", "selected_action": "move", "target": "ground"},
            {"raw_event_offset": 2, "event_id": "e2", "event_type": "ACTION_BLOCKED",
             "location": "ground", "action": "search", "target": "desk"},
            {"raw_event_offset": 3, "event_id": "e3", "event_type": "TURN",
             "location": "ground", "selected_action": "search", "target": "breaker", "progress_delta": 1},
            {"raw_event_offset": 4, "event_id": "e4", "event_type": "LOCATION_CHANGE",
             "location": "ground", "selected_action": "move", "target": "basement"},
        ]

    def test_full_summary_omit_classification_preserves_every_event(self):
        rows = classify_replay_events(self.events, full_ranges=[(1, 1)], summary_ranges=[(2, 4)],
                                      omit_event_types={"ACTION_BLOCKED"})
        self.assertEqual([row["replay_render_mode"] for row in rows],
                         ["FULL_RENDER", "OMIT", "SUMMARY_RENDER", "SUMMARY_RENDER"])
        self.assertEqual([row["raw_event_offset"] for row in rows], [1, 2, 3, 4])

    def test_grounded_kp_summary_passes_all_gates(self):
        classified = classify_replay_events(self.events, full_ranges=[(1, 1)], summary_ranges=[(2, 4)],
                                            omit_event_types={"ACTION_BLOCKED"})
        block = make_summary_block(
            "summary_1", self.events, start=2, end=4,
            text="一階を調べたあと、地下室へ戻りました。", locations=["ground"],
            claims=[
                {"claim_id": "search", "claim_type": "ACTION",
                 "evidence_offsets": [3], "matches": {"selected_action": "search", "target": "breaker"}},
                {"claim_id": "return", "claim_type": "LOCATION",
                 "evidence_offsets": [4], "matches": {"event_type": "LOCATION_CHANGE", "target": "basement"}},
            ],
        )
        report = audit_summary_plan(self.events, classified, [block], source_start=1, source_end=4)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["SUMMARY_TRACEABILITY"], 1.0)
        self.assertTrue(all(value == 0 for value in report["counts"].values()))

    def test_invented_reason_and_unexplained_gap_fail(self):
        classified = classify_replay_events(self.events, full_ranges=[], summary_ranges=[(3, 4)])
        block = make_summary_block(
            "bad", self.events, start=3, end=4, text="怖くなったので戻った。", locations=["ground"],
            claims=[{"claim_id": "fear", "claim_type": "REASON", "evidence_offsets": [4],
                     "matches": {"target": "basement"}}],
        )
        report = audit_summary_plan(self.events, classified, [block], source_start=1, source_end=4)
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["counts"]["SUMMARY_INVENTED_REASON"], 1)

    def test_entry_and_exit_bridges_present_boundary_location_changes(self):
        classified = classify_replay_events(
            self.events,
            full_ranges=[],
            summary_ranges=[(2, 4)],
            bridge_offsets={1: "SUMMARY_ENTRY_BRIDGE", 4: "SUMMARY_EXIT_BRIDGE"},
        )
        entry = make_summary_bridge(
            "entry", self.events, bridge_type="SUMMARY_ENTRY_BRIDGE",
            text="地下室を離れて一階へ移ります。", voice_text="ちかしつをはなれて、いっかいへうつります。",
            evidence_offsets=[1], from_location="basement", to_location="ground",
            claims=[{"claim_id": "leave", "claim_type": "LOCATION", "evidence_offsets": [1],
                     "matches": {"event_type": "LOCATION_CHANGE", "target": "ground"}}],
        )
        exit_bridge = make_summary_bridge(
            "exit", self.events, bridge_type="SUMMARY_EXIT_BRIDGE",
            text="再び地下室へ戻ります。", voice_text="ふたたび、ちかしつへもどります。",
            evidence_offsets=[4], from_location="ground", to_location="basement",
            claims=[{"claim_id": "return", "claim_type": "LOCATION", "evidence_offsets": [4],
                     "matches": {"event_type": "LOCATION_CHANGE", "target": "basement"}}],
        )
        report = audit_summary_bridges(
            self.events, classified, [entry, exit_bridge], summary_ranges=[(2, 4)]
        )
        self.assertEqual(report["status"], "PASS", report)
        self.assertTrue(report["LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED"])
        self.assertTrue(all(value == 0 for value in report["counts"].values()))

    def test_missing_bridge_and_invented_reason_fail_closed(self):
        classified = classify_replay_events(
            self.events, full_ranges=[], summary_ranges=[(2, 4)],
            bridge_offsets={1: "SUMMARY_ENTRY_BRIDGE", 4: "SUMMARY_EXIT_BRIDGE"},
        )
        entry = make_summary_bridge(
            "bad_entry", self.events, bridge_type="SUMMARY_ENTRY_BRIDGE",
            text="道具を探すため一階へ移ります。", voice_text="どうぐをさがすため、いっかいへうつります。",
            evidence_offsets=[1], from_location="basement", to_location="ground", claims=[],
        )
        report = audit_summary_bridges(self.events, classified, [entry], summary_ranges=[(2, 4)])
        self.assertEqual(report["status"], "FAIL")
        self.assertEqual(report["counts"]["SUMMARY_EXIT_CONTEXT_MISSING"], 1)
        self.assertEqual(report["counts"]["BRIDGE_INVENTED_REASON"], 1)


if __name__ == "__main__":
    unittest.main()
