"""V9 historical reproduction and V10 rollable-skill registry acceptance."""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest import mock

from AdjudicationEvidence import EvidenceContractError
from CharacterManager import CharacterManager
from DiceEngine import DiceEngine
from InvestigationFlow import finalize_investigation
from ScenarioManager import ScenarioManager
from SkillRegistry import canonical_roll_identifier, resolve_roll_target
import main


ROOT = Path(__file__).resolve().parent


class _Characters:
    BASE_SKILLS = CharacterManager.BASE_SKILLS

    def __init__(self):
        self.characters = {
            "pc_01": {
                "attributes": {"STR": 55, "EDU": 60},
                "skills": {"目星": 50, "図書館": 45},
            }
        }
        self.active_pc_list = ["pc_01"]

    def get_attribute(self, char_id, name):
        return self.characters[char_id]["attributes"].get(name)

    def get_skill(self, char_id, name):
        skills = self.characters[char_id]["skills"]
        if name in skills:
            return skills[name]
        if name == "母国語":
            return self.get_attribute(char_id, "EDU") or 0
        return self.BASE_SKILLS.get(name, 0)

    def can_offer_luck_burn(self, *_args, **_kwargs):
        return False

    def mark_skill_success(self, *_args, **_kwargs):
        return None


def _scenario():
    return ScenarioManager(json.loads((ROOT / "scenario_corbitt.json").read_text(encoding="utf-8")))


class TestSkillRegistryV10(unittest.TestCase):
    def test_v9_historical_failure_reproduced_without_raw_mutation(self):
        scenario = _scenario()
        chars = _Characters()
        state = {"unified_event_log": [], "last_pl_action": {"skill_proposal_reason": "板を調べる"}}
        # Reproduce the old boundary explicitly: STR was sent to get_skill.
        with mock.patch(
            "main._resolve_authoritative_roll_value",
            side_effect=lambda cm, cid, name: (cm.get_skill(cid, name), {"kind": "SKILL"}),
        ), mock.patch.object(
            scenario, "evaluate_pre_action_guard", return_value=None,
        ), mock.patch.object(
            scenario, "process_action", return_value={"kp_instruction": "ok"},
        ):
            result = main.process_system_action(
                "pc_01", "PC1", "search", "basement_planks", "",
                "corbitt_basement", chars, DiceEngine(), scenario, game_state=state,
            )
        with self.assertRaisesRegex(EvidenceContractError, "target_value, roll, raw_result"):
            finalize_investigation(
                state, result, {"transaction_id": "tx_old"}, active_pc_ids=["pc_01"],
            )

    def test_patched_str_investigation_produces_one_complete_roll_event(self):
        scenario = _scenario()
        chars = _Characters()
        state = {"unified_event_log": [], "last_pl_action": {"skill_proposal_reason": "板を調べる"}}
        with mock.patch.object(
            scenario, "evaluate_pre_action_guard", return_value=None,
        ), mock.patch.object(
            scenario, "process_action", return_value={"kp_instruction": "ok"},
        ), mock.patch("DiceEngine.random.randint", side_effect=[4, 4]):
            result = main.process_system_action(
                "pc_01", "PC1", "search", "basement_planks", "",
                "corbitt_basement", chars, DiceEngine(), scenario, game_state=state,
            )
        self.assertEqual(result["skill_or_stat"], "STR")
        self.assertEqual(result["target_value"], 55)
        self.assertEqual(result["roll"], 44)
        self.assertTrue(result["raw_result"])
        finalize_investigation(
            state, result, {"transaction_id": "tx_new"}, active_pc_ids=["pc_01"],
        )
        rows = [
            e for e in state["unified_event_log"]
            if e.get("event_type") == "INVESTIGATION_ROLLED"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["adjudication_id"], result["adjudication_id"])

    def test_authoritative_scenario_roll_identifiers_resolve(self):
        scenario_data = json.loads((ROOT / "scenario_corbitt.json").read_text(encoding="utf-8"))
        referenced = set()
        for loc in scenario_data.get("locations", {}).values():
            for obj in (loc.get("objects") or {}).values():
                raw = obj.get("required_skill") or obj.get("required_skills") or []
                referenced.update([raw] if isinstance(raw, str) else raw)
        chars = _Characters()
        unresolved = []
        for name in sorted(referenced):
            resolved = resolve_roll_target(chars, "pc_01", name)
            if not resolved["defined"]:
                unresolved.append(name)
        self.assertEqual(unresolved, [])

    def test_alias_and_legal_zero_are_distinct_from_undefined(self):
        chars = _Characters()
        brawl = resolve_roll_target(chars, "pc_01", "近接戦闘（格闘）")
        self.assertEqual((brawl["canonical"], brawl["value"]), ("近接戦闘", 25))
        legal_zero = resolve_roll_target(chars, "pc_01", "信用")
        self.assertTrue(legal_zero["defined"])
        self.assertTrue(legal_zero["legal_zero"])
        with mock.patch("DiceEngine.random.randint", side_effect=[5, 5]):
            zero_roll = DiceEngine().execute_skill_roll(
                "PC1", "信用", legal_zero["value"], allow_zero=True,
            )
        self.assertEqual(zero_roll["target_value"], 0)
        self.assertEqual(zero_roll["roll"], 55)
        self.assertTrue(zero_roll["is_failure"])
        missing = resolve_roll_target(chars, "pc_01", "未定義技能")
        self.assertFalse(missing["defined"])
        self.assertIsNone(missing["value"])

    def test_alias_registry_is_unambiguous(self):
        self.assertEqual(canonical_roll_identifier("STR")["kind"], "ATTRIBUTE")
        self.assertEqual(
            canonical_roll_identifier("近接戦闘（格闘）")["canonical"], "近接戦闘",
        )

    def test_full_registry_audit_metrics_are_zero(self):
        tools = ROOT.parents[1] / "tools"
        import sys
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from audit_skill_registry import audit
        report = audit(
            scenario_path=ROOT / "scenario_corbitt.json",
            pcs_path=ROOT / "pcs.json",
            decision_cases_path=ROOT / "datasets" / "decision_cases.jsonl",
        )
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(set(report["metrics"].values()), {0})
        expected = set(CharacterManager.BASE_SKILLS) | {
            "STR", "CON", "DEX", "APP", "POW", "SIZ", "INT", "EDU",
        }
        self.assertEqual(
            {row["name"] for row in report["rollable_registry"]}, expected,
        )
        for row in report["rollable_registry"]:
            self.assertEqual({actor["defined"] for actor in row["actors"]}, {True})


if __name__ == "__main__":
    unittest.main()
