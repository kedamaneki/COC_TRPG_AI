"""Corbitt V14 fidelity-pack auditor findings (gated; historical default unchanged)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "audit_longrun_formal_v2.py"
SPEC = importlib.util.spec_from_file_location("audit_longrun_formal_v2", MODULE_PATH)
auditor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(auditor)


def _base_inputs(unified):
    return dict(
        result={
            "session_id": "TEST_V14",
            "completed": True,
            "phase": "clear",
            "pause_reason": "game_clear",
            "human_interventions": 0,
            "final_flags": {"corbitt_defeated": True},
        },
        session=[],
        unified=unified,
        normalized_doc={"events": [], "metadata": {}},
        provenance={"source_traceability_rate": 1.0},
        validation={"status": "PASS"},
        checkpoint_state={"combat": {"active": False}},
        checkpoint_manifest={"checkpoint_id": "cp-test"},
        input_manifest={"run_input_identity": "PASS"},
    )


class CorbittFidelityAuditorTests(unittest.TestCase):
    def test_historical_default_skips_v14_findings(self):
        unified = [{
            "event_id": "e1",
            "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
            "final_result": "SPECIAL_OBJECTIVE_COMPLETED",
            "world_fact": {
                "event": "SPECIAL_OBJECTIVE_COMPLETED",
                "target": "corbitt_body",
                "fact": "CORBITT_BODY_DESTROYED",
            },
            "resolution_mode": "NO_ROLL",
        }]
        report = auditor.run_audit(**_base_inputs(unified), fidelity_pack="none")
        cats = {f["category"] for f in report["findings"]}
        self.assertTrue(cats.isdisjoint(auditor.CORBITT_V14_CATEGORIES))

    def test_so_without_kill_route(self):
        unified = [{
            "event_id": "e1",
            "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
            "final_result": "SPECIAL_OBJECTIVE_COMPLETED",
            "target": "corbitt_body",
            "world_fact": {
                "event": "SPECIAL_OBJECTIVE_COMPLETED",
                "target": "corbitt_body",
                "fact": "CORBITT_BODY_DESTROYED",
            },
            "resolution_mode": "NO_ROLL",
        }]
        findings = auditor.audit_corbitt_final_battle_fidelity(
            _base_inputs(unified)["result"], unified, "cp-test",
        )
        cats = {f["category"] for f in findings}
        self.assertIn("SPECIAL_OBJECTIVE_WITHOUT_VALIDATED_KILL_ROUTE", cats)
        self.assertIn("UNSUPPORTED_COMBAT_NO_ROLL", cats)
        self.assertTrue(any(f.get("blocking") for f in findings))

    def test_validated_route_a_passes_fidelity(self):
        unified = [{
            "event_id": "e1",
            "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
            "final_result": "SPECIAL_OBJECTIVE_COMPLETED",
            "target": "corbitt_body",
            "resolution_mode": "NO_ROLL",
            "resolution_class": "DETERMINISTIC_RULE",
            "resolution_reason": "DERIVED_AFTER_VALIDATED_KILL",
            "validated_kill_route_id": "ROUTE_A_HP0",
            "fact_origin": "SOURCE",
            "source_rule_id": "CORBITT_HP0_DUST",
            "world_fact": {
                "event": "SPECIAL_OBJECTIVE_COMPLETED",
                "target": "corbitt_body",
                "fact": "CORBITT_BODY_DESTROYED",
                "validated_kill_route_id": "ROUTE_A_HP0",
                "fact_origin": "SOURCE",
                "source_rule_id": "CORBITT_HP0_DUST",
            },
        }]
        findings = auditor.audit_corbitt_final_battle_fidelity(
            _base_inputs(unified)["result"], unified, "cp-test",
        )
        cats = {f["category"] for f in findings}
        self.assertNotIn("SPECIAL_OBJECTIVE_WITHOUT_VALIDATED_KILL_ROUTE", cats)
        self.assertNotIn("SCENARIO_SOURCE_PROVENANCE_MISSING", cats)
        self.assertNotIn("UNSUPPORTED_COMBAT_NO_ROLL", cats)


if __name__ == "__main__":
    unittest.main()
