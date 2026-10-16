from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = ROOT / ".test-tmp"
TEST_TMP.mkdir(exist_ok=True)
ITERATION2_FIXTURE = ROOT / "tests" / "fixtures" / "formal_auditor_v2" / "iteration2_existing"
MODULE_PATH = ROOT / "tools" / "audit_longrun_formal_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_longrun_formal_v2", MODULE_PATH)
auditor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(auditor)


def good_fixture():
    roll = {
        "event_id": "roll_1", "event_type": "INVESTIGATION_ROLLED", "cycle": 2,
        "resolution_mode": "ROLL", "adjudication_id": "adj_roll", "actor": "pc_1",
        "target": "door", "skill_or_stat": "目星", "target_value": 50, "roll": 59,
        "raw_result": "FAILURE", "final_result": "REGULAR_SUCCESS",
        "modifier": {"type": "LUCK_SPEND", "amount": 9, "resource_before": 50, "resource_after": 41},
    }
    san_trigger = {
        "event_id": "san_trigger", "event_type": "SAN_EFFECT_TRIGGERED", "cycle": 3,
        "adjudication_id": "adj_san", "effect": {"force_san_check": "0/1D4"},
    }
    san_result = {
        "event_id": "san_result", "event_type": "SAN_CHECK_RESOLVED", "cycle": 3,
        "trigger_event_id": "san_trigger", "adjudication_id": "adj_san", "roll_type": "san",
        "san_before": 70, "san_roll": 40, "san_result": "SUCCESS", "san_loss": 0, "san_after": 70,
    }
    object_found = {
        "event_id": "object_1", "event_type": "OBJECT_STATE_CHANGED", "cycle": 4,
        "object_id": "corbitt_knife", "object_state_before": {"status": "UNDISCOVERED"},
        "object_state_after": {"status": "AVAILABLE", "destroyed": False},
    }
    object_owned = {
        "event_id": "object_2", "event_type": "OBJECT_STATE_CHANGED", "cycle": 4,
        "object_id": "corbitt_knife", "object_state_before": {"status": "AVAILABLE"},
        "object_state_after": {"status": "OWNED", "owner_id": "pc_1", "destroyed": False},
        "narrative_options": [{"option_id": "inspect", "availability_event_id": "availability_1"}],
    }
    combat_start = {"event_id": "combat_1", "event_type": "COMBAT_STARTED", "combat_id": "knife_combat", "cycle": 5}
    combat_action = {
        "event_id": "combat_2", "event_type": "COMBAT_ACTION_RESOLVED", "combat_id": "knife_combat", "cycle": 5,
        "resolution_mode": "ROLL", "adjudication_id": "adj_combat", "actor": "pc_1", "target": "corbitt_knife",
        "skill_or_stat": "回避", "target_value": 55, "roll": 20, "raw_result": "REGULAR_SUCCESS",
        "final_result": "REGULAR_SUCCESS", "modifier": None,
    }
    combat_end = {"event_id": "combat_3", "event_type": "COMBAT_ENDED", "combat_id": "knife_combat", "cycle": 5}
    final = {
        "event_id": "final_1", "event_type": "COMBAT_ACTION_RESOLVED", "combat_id": "final_combat", "cycle": 9,
        "resolution_mode": "NO_ROLL", "resolution_reason": "SCENARIO_SPECIAL_OBJECTIVE",
        "adjudication_id": "adj_final", "actor": "pc_1", "target": "corbitt_body",
        "final_result": "SPECIAL_OBJECTIVE_COMPLETED", "world_fact": {"event": "CORBITT_BODY_DESTROYED"},
    }
    final_start = {"event_id": "final_start", "event_type": "COMBAT_STARTED", "combat_id": "final_combat", "cycle": 9}
    final_end = {"event_id": "final_end", "event_type": "COMBAT_ENDED", "combat_id": "final_combat", "cycle": 9}
    unified = [roll, san_trigger, san_result, object_found, object_owned, combat_start, combat_action, combat_end, final_start, final, final_end]
    normalized = []
    for row in unified:
        event = {
            "event_id": f"norm:{row['event_id']}", "event_type": row["event_type"],
            "source_event_ids": [row["event_id"]], "adjudication_id": row.get("adjudication_id"),
            "metadata": {"source_payload": copy.deepcopy(row)},
        }
        if row["event_id"] == "roll_1":
            event.update({
                "actor_id": "pc_1", "action": {"target": "door"},
                "dice": {"resolution_mode": "ROLL", "skill_name": "目星", "target_value": 50, "roll": 59, "raw_result": "FAILURE", "final_result": "REGULAR_SUCCESS"},
                "modifier": copy.deepcopy(row["modifier"]),
            })
        elif row["event_id"] == "combat_2":
            event.update({
                "actor_id": "pc_1", "action": {"target": "corbitt_knife"},
                "dice": {"resolution_mode": "ROLL", "skill_name": "回避", "target_value": 55, "roll": 20, "raw_result": "REGULAR_SUCCESS", "final_result": "REGULAR_SUCCESS"},
            })
        elif row["event_id"] == "final_1":
            event.update({
                "actor_id": "pc_1", "action": {"target": "corbitt_body"},
                "dice": {"resolution_mode": "NO_ROLL", "automatic_result": "SPECIAL_OBJECTIVE_COMPLETED"},
            })
        elif row["event_id"] == "san_result":
            event["san"] = {"before": 70, "target": 70, "roll": 40, "result": "SUCCESS", "loss": 0, "after": 70, "normalization_source": "STRUCTURED", "trigger_event_id": "san_trigger"}
        normalized.append(event)
    return {
        "result": {"session_id": "FIXTURE_GOOD", "completed": True, "phase": "clear", "pause_reason": "game_clear", "human_interventions": 0, "final_flags": {"corbitt_defeated": True}},
        "session": [], "unified": unified,
        "normalized_doc": {"events": normalized, "metadata": {"conversion_warnings": []}},
        "provenance": {"source_traceability_rate": 1.0}, "validation": {"status": "PASS"},
        "checkpoint_state": {"combat_state": {"active": False}},
        "checkpoint_manifest": {"checkpoint_id": "CHECKPOINT_CYCLE_000009", "cycle": 9, "completed": True},
        "input_manifest": {"run_input_identity": "PASS"},
    }


def audit(data):
    return auditor.run_audit(**data)


def categories(report):
    return [item["category"] for item in report["findings"]]


def write_cli_fixture(root: Path, *, completed=True):
    data = good_fixture()
    data["result"]["completed"] = completed
    run, norm = root / "core-run", root / "normalizer-output"
    checkpoint = run / "checkpoints" / "cycle_000009"
    (checkpoint / "runtime_data").mkdir(parents=True)
    norm.mkdir(parents=True)
    files = {
        run / "result.json": data["result"], run / "session-log.json": data["session"],
        run / "unified-event-log.json": data["unified"], run / "input_manifest.json": data["input_manifest"],
        checkpoint / "manifest.json": data["checkpoint_manifest"], checkpoint / "state.json": data["checkpoint_state"],
        norm / "normalized_session.json": data["normalized_doc"], norm / "provenance_report.json": data["provenance"],
        norm / "validation_report.json": data["validation"],
    }
    for path, value in files.items():
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    (checkpoint / "COMPLETE").write_text("complete", encoding="utf-8")
    return run, norm


class FormalAuditorV2Tests(unittest.TestCase):
    def test_auditor_uses_explicit_or_latest_valid_checkpoint(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            root = Path(tmp)
            for cycle, valid in ((2, True), (7, False), (5, True)):
                path = root / "checkpoints" / f"cycle_{cycle:06d}"
                (path / "runtime_data").mkdir(parents=True)
                (path / "manifest.json").write_text(json.dumps({"checkpoint_id": f"CP{cycle}", "cycle": cycle, "completed": valid}), encoding="utf-8")
                (path / "state.json").write_text("{}", encoding="utf-8")
                if valid:
                    (path / "COMPLETE").write_text("complete", encoding="utf-8")
            self.assertEqual(auditor.resolve_checkpoint(root).name, "cycle_000005")
            self.assertEqual(auditor.resolve_checkpoint(root, "CP2").name, "cycle_000002")

    def test_auditor_has_no_fixed_session_id(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("CORBITT_LONGRUN_POST_ADJUDICATION_FIX_001", source)
        self.assertNotIn("CORBITT_LONGRUN_ITERATION2_V2_001", source)
        self.assertNotIn('"cycle_000033"', source)

    def test_auditor_rejects_raw_run_output_path(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            root = Path(tmp)
            normalized = root.parent / "normalized.json"
            normalized.write_text("{}", encoding="utf-8")
            with self.assertRaises(auditor.AuditInputError):
                auditor.guard_output_path(root, normalized, root / "audit")

    def test_roll_contract_complete_passes(self):
        self.assertNotIn("ROLL_CONTRACT_INCOMPLETE", categories(audit(good_fixture())))

    def test_roll_contract_missing_field_fails(self):
        data = good_fixture()
        data["unified"][0]["roll"] = None
        self.assertIn("ROLL_CONTRACT_INCOMPLETE", categories(audit(data)))

    def test_lifecycle_resolution_mode_is_rejected(self):
        data = good_fixture()
        data["normalized_doc"]["events"].append({
            "event_id": "bad_location", "event_type": "LOCATION_CHANGE",
            "source_event_ids": ["raw_location"], "adjudication_id": "adj_bad_move",
            "dice": {"resolution_mode": "NO_ROLL"},
        })
        report = audit(data)
        self.assertIn("LIFECYCLE_MISCLASSIFIED_AS_NO_ROLL", categories(report))
        self.assertFalse(report["gate"]["lifecycle_misclassification_zero"])

    def test_mandatory_san_effect_dropped_detected(self):
        data = good_fixture()
        data["unified"] = [row for row in data["unified"] if row["event_id"] != "san_result"]
        data["normalized_doc"]["events"] = [row for row in data["normalized_doc"]["events"] if row["event_id"] != "norm:san_result"]
        self.assertIn("MANDATORY_SAN_EFFECT_DROPPED", categories(audit(data)))

    def test_san_snapshot_not_misclassified(self):
        report = audit(good_fixture())
        self.assertNotIn("SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK", categories(report))
        data = good_fixture()
        data["normalized_doc"]["events"].append({
            "event_id": "norm:snapshot", "event_type": "SYSTEM_INTERNAL", "source_event_ids": ["snapshot"],
            "san": {"before": 60, "target": 60, "roll": None, "result": None, "loss": None, "after": 60},
            "metadata": {"source_payload": {"event_id": "snapshot", "event_type": "COMBAT_ACTION_SELECTED", "san": {"kind": "SNAPSHOT"}}},
        })
        self.assertIn("SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK", categories(audit(data)))

    def test_invalid_object_transition_detected(self):
        data = good_fixture()
        data["unified"].append({
            "event_id": "bad_object", "event_type": "OBJECT_STATE_CHANGED", "object_id": "corbitt_knife",
            "object_state_before": {"status": "DESTROYED", "destroyed": True},
            "object_state_after": {"status": "ACTIVE", "destroyed": False, "active": True},
        })
        self.assertIn("OBJECT_STATE_INVALID_TRANSITION", categories(audit(data)))

    def test_object_narrative_contradiction_detected(self):
        data = good_fixture()
        data["unified"] += [
            {"event_id": "destroy", "event_type": "OBJECT_STATE_CHANGED", "object_id": "corbitt_knife", "object_state_before": {"status": "OWNED"}, "object_state_after": {"status": "DESTROYED", "destroyed": True}},
            {"event_id": "claim", "event_type": "WORLD_EVENT", "narrative_claims": [{"object_id": "corbitt_knife", "predicate": "ATTACKS"}]},
        ]
        self.assertIn("OBJECT_NARRATIVE_STATE_CONTRADICTION", categories(audit(data)))

    def test_ungrounded_narrative_option_detected(self):
        data = good_fixture()
        data["unified"].append({"event_id": "bad_option", "event_type": "WORLD_EVENT", "narrative_options": [{"option_id": "unsupported"}]})
        self.assertIn("UNGROUNDED_NARRATIVE_OPTION", categories(audit(data)))

    def test_luck_raw_and_final_phase_not_confused(self):
        report = audit(good_fixture())
        self.assertFalse(any(item["finding_id"].startswith("luck_phase") for item in report["findings"]))

    def test_combat_requires_termination(self):
        data = good_fixture()
        data["unified"] = [row for row in data["unified"] if row["event_id"] != "combat_3"]
        self.assertIn("COMBAT_WITHOUT_TERMINATION", categories(audit(data)))

    def test_traceability_required(self):
        data = good_fixture()
        data["normalized_doc"]["events"][0]["source_event_ids"] = []
        self.assertIn("NORMALIZATION_GAP", categories(audit(data)))

    def test_new_five_false_positive_regression(self):
        report = audit(good_fixture())
        self.assertEqual([], sorted(set(categories(report)) & auditor.ITERATION2_CATEGORIES))
        self.assertEqual("PASS", report["formal_status"])
        self.assertFalse(report["video_source_eligible"])

    def test_all_new_five_negative_fixtures(self):
        expected = set()
        data = good_fixture()
        data["unified"] = [row for row in data["unified"] if row["event_id"] != "san_result"]
        data["normalized_doc"]["events"] = [row for row in data["normalized_doc"]["events"] if row["event_id"] != "norm:san_result"]
        expected.add("MANDATORY_SAN_EFFECT_DROPPED")
        data["normalized_doc"]["events"].append({"event_id": "norm:snapshot", "source_event_ids": ["snapshot"], "san": {"before": 10, "after": 10}, "metadata": {"source_payload": {"event_type": "STATE_SNAPSHOT", "san": {"kind": "SNAPSHOT"}}}})
        expected.add("SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK")
        data["unified"] += [
            {"event_id": "destroy", "object_id": "knife", "object_state_before": {"status": "OWNED"}, "object_state_after": {"status": "DESTROYED", "destroyed": True}},
            {"event_id": "revive", "object_id": "knife", "object_state_before": {"status": "DESTROYED", "destroyed": True}, "object_state_after": {"status": "ACTIVE", "active": True}},
            {"event_id": "claim", "narrative_claims": [{"object_id": "knife", "predicate": "ATTACKS"}]},
            {"event_id": "option", "narrative_options": [{"option_id": "invented"}]},
        ]
        expected |= {"OBJECT_STATE_INVALID_TRANSITION", "OBJECT_NARRATIVE_STATE_CONTRADICTION", "UNGROUNDED_NARRATIVE_OPTION"}
        self.assertTrue(expected.issubset(set(categories(audit(data)))))

    def test_existing_iteration2_deterministic_fixture_regression(self):
        acceptance = json.loads((ITERATION2_FIXTURE / "iteration2_acceptance.json").read_text(encoding="utf-8-sig"))
        normalized = json.loads((ITERATION2_FIXTURE / "normalized_fixture.json").read_text(encoding="utf-8-sig"))
        self.assertEqual("PASS", acceptance["status"])
        for name in auditor.ITERATION2_CATEGORIES:
            self.assertEqual(0, acceptance["metrics"][name])
        findings = auditor.audit_san([], [], normalized["events"], "ITERATION2_FIXTURE")
        findings += auditor.audit_objects([], [], normalized["events"], "ITERATION2_FIXTURE")
        self.assertEqual([], [item for item in findings if item["category"] in auditor.ITERATION2_CATEGORIES])

    def test_legacy_bad_fixture_redetects_known_problems(self):
        data = good_fixture()
        data["unified"][0]["target_value"] = None
        data["unified"] = [row for row in data["unified"] if row["event_id"] not in {"san_result", "combat_3"}]
        data["normalized_doc"]["events"] = [row for row in data["normalized_doc"]["events"] if row["event_id"] != "norm:san_result"]
        data["normalized_doc"]["events"].append({"event_id": "legacy_snapshot", "source_event_ids": ["legacy"], "san": {"before": 55, "after": 55}, "metadata": {"source_payload": {"event_type": "COMBAT_ACTION_SELECTED"}}})
        found = set(categories(audit(data)))
        self.assertTrue({"ROLL_CONTRACT_INCOMPLETE", "MANDATORY_SAN_EFFECT_DROPPED", "SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK", "COMBAT_WITHOUT_TERMINATION"}.issubset(found))

    def test_cli_generates_required_outputs_and_complete_manifest(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            root = Path(tmp)
            run, norm = write_cli_fixture(root)
            output = root / "audit-output"
            code = auditor.main([
                "--core-run", str(run), "--normalized", str(norm / "normalized_session.json"),
                "--output-dir", str(output), "--normalizer-implementation", str(ROOT / "src" / "video_agent" / "normalizer" / "session.py"),
            ])
            self.assertEqual(0, code)
            self.assertTrue((output / "FULL_SESSION_EVIDENCE_AUDIT.md").is_file())
            self.assertTrue((output / "full_session_evidence_audit.json").is_file())
            manifest = json.loads((output / "audit_manifest.json").read_text(encoding="utf-8"))
            for field in ("session_id", "auditor_version", "auditor_sha256", "normalizer_sha256", "normalized_session_sha256", "raw_session_log_sha256", "unified_event_log_sha256", "checkpoint_id", "legacy_project_id", "started_at", "completed_at"):
                self.assertIn(field, manifest)

    def test_incomplete_run_cannot_receive_formal_audit(self):
        with tempfile.TemporaryDirectory(dir=TEST_TMP) as tmp:
            root = Path(tmp)
            run, norm = write_cli_fixture(root, completed=False)
            with self.assertRaisesRegex(auditor.AuditInputError, "RUN_INCOMPLETE"):
                auditor.main([
                    "--core-run", str(run), "--normalized", str(norm / "normalized_session.json"),
                    "--output-dir", str(root / "audit-output"), "--normalizer-implementation", str(ROOT / "src" / "video_agent" / "normalizer" / "session.py"),
                ])


if __name__ == "__main__":
    unittest.main()
