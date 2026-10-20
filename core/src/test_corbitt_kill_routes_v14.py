"""V14 fixtures A–E, N1, N4, P1–P6 for Corbitt kill routes."""
import unittest

from CharacterManager import CharacterManager
from CombatResolutionGuard import (
    CombatResolutionError,
    declare_resolution_class,
    may_define_kill_route,
    validate_kill_route_authority,
    validate_victory_provenance,
)
from CompletionAtomicity import CompletionAtomicityError, commit_special_objective_completion
from CorbittKillRoutes import (
    ROUTE_A_HP0,
    ROUTE_B_DAGGER,
    build_derived_so_payload,
    grant_dagger_ownership,
    remap_body_break_to_attack,
    try_route_a_on_hp0,
    try_route_b_on_hit,
)
from GameStateManager import GameStateManager


class _Scenario:
    def __init__(self):
        self.flags = {
            "corbitt_defeated": False,
            "object_states": {
                "corbitt_knife": {"object_id": "corbitt_knife", "status": "ON_FLOOR", "exists": True},
            },
        }
        self.current_phase = "investigation"


def _chars_with_armor(armor=5, hp=17):
    chars = CharacterManager.__new__(CharacterManager)
    chars.characters = {
        "pc": {
            "profile": {"name": "PC"},
            "attributes": {"HP": {"current": 12, "max": 12}, "DB": "0"},
            "skills": {"近接戦闘": 70},
            "weapons": [{"name": "棍棒", "skill": "近接戦闘", "damage": "1D6"}],
            "states": [],
        },
        "walter_corbitt": {
            "profile": {"name": "Corbitt"},
            "attributes": {"HP": {"current": hp, "max": 17}, "DB": "1D4"},
            "skills": {"近接戦闘": 50},
            "combat_profile": {"armor_points": armor, "armor_roll": "2D6"},
            "weapons": [],
            "states": [],
        },
    }
    chars.save_data = lambda: None
    chars.get_stat_current = lambda cid, key: chars.characters[cid]["attributes"][key]["current"]
    chars.get_stat_max = lambda cid, key: chars.characters[cid]["attributes"][key]["max"]

    def apply_pool(cid, key, dmg):
        pool = chars.characters[cid]["attributes"][key]
        old = int(pool["current"])
        new = max(0, old - int(dmg))
        pool["current"] = new
        return old, new

    chars.apply_pool_damage = apply_pool
    return chars


class CorbittKillRoutesV14Tests(unittest.TestCase):
    def test_A_armor_blocks_all(self):
        chars = _chars_with_armor(armor=12, hp=17)
        gsm = GameStateManager(chars)
        # Fixed damage via weapon that rolls — use bypass path: inject by calling internals
        hit = gsm._apply_hit_with_armor(
            "pc", "walter_corbitt",
            weapon={"name": "test", "skill": "近接戦闘", "damage": "1D3", "apply_damage_bonus": False},
        )
        # With armor 12, any 1D3 is fully blocked
        self.assertEqual(hit["penetrating_damage"], 0)
        self.assertEqual(hit["hp_after"], 17)
        self.assertIn("armor_applied", hit)
        self.assertEqual(hit["armor_applied"]["penetrating_damage"], 0)

    def test_B_damage_penetrates(self):
        chars = _chars_with_armor(armor=3, hp=17)
        gsm = GameStateManager(chars)
        # Force known raw by patching resolve_weapon_damage_amount
        gsm.resolve_weapon_damage_amount = lambda *a, **k: {
            "damage": 8, "detail": "8", "weapon": {}, "dice": "8", "db": "", "impale": False,
        }
        hit = gsm._apply_hit_with_armor("pc", "walter_corbitt", weapon={})
        self.assertEqual(hit["armor_mitigated"], 3)
        self.assertEqual(hit["armor_after"], 0)
        self.assertEqual(hit["penetrating_damage"], 5)
        self.assertEqual(hit["hp_after"], 12)

    def test_C_hp_zero_route_a(self):
        payload = try_route_a_on_hp0(defender_id="walter_corbitt", new_hp=0)
        self.assertEqual(payload["validated_kill_route_id"], ROUTE_A_HP0)
        self.assertEqual(payload["world_fact"]["fact_origin"], "SOURCE")
        chars = _chars_with_armor(armor=0, hp=2)
        gsm = GameStateManager(chars)
        gsm.resolve_weapon_damage_amount = lambda *a, **k: {
            "damage": 5, "detail": "5", "weapon": {}, "dice": "5", "db": "", "impale": False,
        }
        hit = gsm._apply_hit_with_armor("pc", "walter_corbitt", weapon={})
        self.assertEqual(hit["hp_after"], 0)
        derived = try_route_a_on_hp0(defender_id="walter_corbitt", new_hp=hit["hp_after"])
        self.assertIsNotNone(derived)

    def test_D_dagger_special_kill(self):
        sc = _Scenario()
        grant_dagger_ownership(sc, "pc")
        payload = try_route_b_on_hit(
            attacker_id="pc",
            defender_id="walter_corbitt",
            weapon={"id": "corbitt_floating_dagger", "name": "魔法のダガー"},
            scenario_mgr=sc,
        )
        self.assertEqual(payload["validated_kill_route_id"], ROUTE_B_DAGGER)
        self.assertEqual(payload["resolution_reason"], "DAGGER_SPECIAL_KILL_SOURCE_P34")

    def test_E_and_N1_break_no_auto_clear(self):
        sc = _Scenario()
        remap = remap_body_break_to_attack("break", "corbitt_body", scenario_mgr=sc)
        self.assertTrue(remap["remapped"])
        with self.assertRaises(CombatResolutionError):
            declare_resolution_class(
                in_combat=True,
                action_id="break",
                target="corbitt_body",
                roll_type="none",
                dice_skipped=True,
            )
        self.assertFalse(sc.flags["corbitt_defeated"])

    def test_N4_adaptation_inference_cannot_kill(self):
        with self.assertRaises(CombatResolutionError):
            validate_victory_provenance({
                "validated_kill_route_id": "ROUTE_A_HP0",
                "fact_origin": "ADAPTATION_INFERENCE",
                "may_define_kill_route": True,
            })

    def test_P1_source_kill_ok(self):
        self.assertTrue(may_define_kill_route("SOURCE", True))
        validate_victory_provenance({
            "validated_kill_route_id": ROUTE_A_HP0,
            "fact_origin": "SOURCE",
            "source_rule_id": "CORBITT_HP0_DUST",
            "may_define_kill_route": True,
        })

    def test_P2_transform_cannot_define(self):
        self.assertFalse(may_define_kill_route("ADAPTATION_TRANSFORM", True))
        with self.assertRaises(CombatResolutionError):
            validate_kill_route_authority({
                "validated_kill_route_id": ROUTE_A_HP0,
                "fact_origin": "ADAPTATION_TRANSFORM",
                "may_define_kill_route": True,
                "source_ref": {"rule_id": "CORBITT_HP0_DUST"},
            })

    def test_P3_inference_kill_blocked(self):
        with self.assertRaises(CombatResolutionError):
            validate_victory_provenance({
                "validated_kill_route_id": ROUTE_B_DAGGER,
                "fact_origin": "ADAPTATION_INFERENCE",
            })

    def test_P5_P6_completion_blocked_without_source(self):
        state = {
            "unified_event_log": [{
                "event_id": "evt",
                "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
                "adjudication_id": "adj",
                "target": "corbitt_body",
                "world_fact": {
                    "event": "SPECIAL_OBJECTIVE_COMPLETED",
                    "fact": "CORBITT_BODY_DESTROYED",
                },
            }],
        }
        sc = _Scenario()
        sc.flags["corbitt_defeated"] = True
        with self.assertRaises(CompletionAtomicityError):
            commit_special_objective_completion(
                state,
                {"completion_phase_deferred": "clear", "adjudication_id": "adj", "target": "corbitt_body"},
                sc,
                type("C", (), {"in_combat": False})(),
            )
        self.assertEqual(sc.current_phase, "investigation")

    def test_P1_completion_with_source_ok(self):
        fact = build_derived_so_payload(route=ROUTE_A_HP0)["world_fact"]
        state = {
            "unified_event_log": [{
                "event_id": "evt",
                "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
                "adjudication_id": "adj",
                "target": "corbitt_body",
                "world_fact": fact,
            }],
        }
        sc = _Scenario()
        sc.flags["corbitt_defeated"] = True
        envelope = commit_special_objective_completion(
            state,
            {
                "completion_phase_deferred": "clear",
                "adjudication_id": "adj",
                "target": "corbitt_body",
                "world_fact": fact,
            },
            sc,
            type("C", (), {"in_combat": False})(),
        )
        self.assertEqual(sc.current_phase, "clear")
        self.assertEqual(envelope["validated_kill_route_id"], ROUTE_A_HP0)


if __name__ == "__main__":
    unittest.main()
