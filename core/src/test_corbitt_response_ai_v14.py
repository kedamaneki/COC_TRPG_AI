"""V14 fixtures F–H for Corbitt response AI."""
import unittest
from unittest.mock import MagicMock

from BossCombatPolicy import (
    ACTION_DOMINATE,
    ACTION_MAGIC_DAGGER,
    ACTION_NORMAL_ATTACK,
    activate_body,
    choose_corbitt_action,
    is_body_active,
    note_pc_hit,
    preferred_defense_for_corbitt,
    resolve_dominate,
)


class _Scenario:
    def __init__(self, dagger_status="DESTROYED"):
        self.flags = {
            "object_states": {
                "corbitt_knife": {
                    "object_id": "corbitt_knife",
                    "status": dagger_status,
                    "exists": True,
                },
            },
        }


class _Chars:
    def __init__(self, mp=18, pow_c=90, pow_t=50):
        self.characters = {
            "walter_corbitt": {
                "profile": {"name": "Corbitt"},
                "attributes": {"POW": pow_c, "MP": {"current": mp, "max": 18}},
                "states": [],
            },
            "pc": {
                "profile": {"name": "PC"},
                "attributes": {"POW": pow_t, "MP": {"current": 10, "max": 10}},
                "states": [],
            },
        }

    def get_stat_current(self, cid, key):
        val = self.characters[cid]["attributes"][key]
        return val["current"] if isinstance(val, dict) else val

    def apply_mp_cost(self, cid, amount):
        pool = self.characters[cid]["attributes"]["MP"]
        pool["current"] = max(0, int(pool["current"]) - int(amount))

    def save_data(self):
        pass


class CorbittResponseAIV14Tests(unittest.TestCase):
    def test_F_fight_back_when_body_active(self):
        state = {}
        self.assertEqual(preferred_defense_for_corbitt(state, attack_type="melee"), "dodge")
        activate_body(state, _Chars(mp=10), round_number=1)
        self.assertEqual(preferred_defense_for_corbitt(state, attack_type="melee"), "fight_back")
        decision = choose_corbitt_action(
            state=state,
            char_mgr=_Chars(mp=0),
            scenario_mgr=_Scenario("DESTROYED"),
            target_id="pc",
        )
        self.assertEqual(decision["action"], ACTION_NORMAL_ATTACK)

    def test_G_body_activation(self):
        state = {}
        note_pc_hit(state)
        chars = _Chars(mp=5)
        result = activate_body(state, chars, round_number=3)
        self.assertTrue(result["ok"])
        self.assertTrue(is_body_active(state))
        self.assertEqual(chars.get_stat_current("walter_corbitt", "MP"), 3)
        self.assertEqual(result["event"]["event_type"], "CORBITT_BODY_ACTIVATED")
        self.assertEqual(result["body_activation"]["rounds_remaining"], 5)

    def test_H_dominate_route(self):
        decision = choose_corbitt_action(
            state={},
            char_mgr=_Chars(mp=18),
            scenario_mgr=_Scenario("DESTROYED"),
            target_id="pc",
        )
        self.assertEqual(decision["action"], ACTION_DOMINATE)
        chars = _Chars(mp=5, pow_c=90, pow_t=10)
        dice = MagicMock()
        dice.execute_melee_opposed_roll.return_value = {
            "outcome": "hit_attacker",
            "log": "opposed POW",
        }
        dice.roll.return_value = 2
        result = resolve_dominate(
            char_mgr=chars, dice_engine=dice,
            caster_id="walter_corbitt", target_id="pc",
        )
        self.assertTrue(result["caster_won"])
        self.assertEqual(result["duration_rounds"], 3)
        self.assertIn("ぼんやり", chars.characters["pc"]["states"])

    def test_dagger_priority_over_dominate(self):
        decision = choose_corbitt_action(
            state={},
            char_mgr=_Chars(mp=18),
            scenario_mgr=_Scenario("IN_COMBAT"),
            target_id="pc",
        )
        self.assertEqual(decision["action"], ACTION_MAGIC_DAGGER)


if __name__ == "__main__":
    unittest.main()
