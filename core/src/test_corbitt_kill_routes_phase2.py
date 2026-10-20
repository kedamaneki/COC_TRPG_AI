"""Phase 2 WP-A gate: Route A/B helpers and break remap (fixtures expanded in Phase 5)."""
import unittest

from CharacterManager import CharacterManager
from CorbittKillRoutes import (
    ROUTE_A_HP0,
    ROUTE_B_DAGGER,
    build_derived_so_payload,
    grant_dagger_ownership,
    pc_controls_magic_dagger,
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
                "corbitt_knife": {
                    "object_id": "corbitt_knife",
                    "status": "ON_FLOOR",
                    "exists": True,
                },
            },
        }
        self.current_phase = "investigation"


class CorbittKillRoutesPhase2Tests(unittest.TestCase):
    def test_break_remap_pre_defeat(self):
        sc = _Scenario()
        remap = remap_body_break_to_attack("break", "corbitt_body", scenario_mgr=sc)
        self.assertTrue(remap["remapped"])
        self.assertEqual(remap["target"], "walter_corbitt")
        sc.flags["corbitt_defeated"] = True
        self.assertFalse(
            remap_body_break_to_attack("break", "corbitt_body", scenario_mgr=sc)["remapped"]
        )

    def test_route_a_payload_on_hp0(self):
        payload = try_route_a_on_hp0(defender_id="walter_corbitt", new_hp=0)
        self.assertEqual(payload["validated_kill_route_id"], ROUTE_A_HP0)
        self.assertEqual(payload["world_fact"]["fact_origin"], "SOURCE")
        self.assertIsNone(try_route_a_on_hp0(defender_id="walter_corbitt", new_hp=1))
        self.assertIsNone(try_route_a_on_hp0(defender_id="other", new_hp=0))

    def test_route_b_requires_owned_dagger(self):
        sc = _Scenario()
        self.assertIsNone(
            try_route_b_on_hit(
                attacker_id="pc",
                defender_id="walter_corbitt",
                weapon={"id": "corbitt_floating_dagger", "name": "魔法のダガー"},
                scenario_mgr=sc,
            )
        )
        grant_dagger_ownership(sc, "pc")
        self.assertTrue(pc_controls_magic_dagger(sc, "pc"))
        payload = try_route_b_on_hit(
            attacker_id="pc",
            defender_id="walter_corbitt",
            weapon={"id": "corbitt_floating_dagger", "name": "魔法のダガー"},
            scenario_mgr=sc,
        )
        self.assertEqual(payload["validated_kill_route_id"], ROUTE_B_DAGGER)

    def test_armor_applied_fields_on_hit(self):
        chars = CharacterManager.__new__(CharacterManager)
        chars.characters = {
            "pc": {
                "profile": {"name": "PC"},
                "attributes": {"HP": {"current": 12, "max": 12}, "DB": "0"},
                "skills": {"近接戦闘": 70},
                "weapons": [{"name": "棍棒", "skill": "近接戦闘", "damage": "1D6"}],
            },
            "walter_corbitt": {
                "profile": {"name": "Corbitt"},
                "attributes": {"HP": {"current": 17, "max": 17}, "DB": "1D4"},
                "skills": {"近接戦闘": 50},
                "combat_profile": {"armor_points": 5, "armor_roll": "2D6"},
                "weapons": [],
            },
        }
        chars.save_data = lambda: None
        chars.get_stat_current = lambda cid, key: chars.characters[cid]["attributes"][key]["current"]
        chars.get_stat_max = lambda cid, key: chars.characters[cid]["attributes"][key]["max"]
        chars.apply_pool_damage = lambda cid, key, dmg: self._apply_pool(chars, cid, key, dmg)
        gsm = GameStateManager(chars)
        hit = gsm.apply_melee_hit("pc", "walter_corbitt", weapon={"name": "棍棒", "skill": "近接戦闘", "damage": "1D6"})
        self.assertIn("armor_applied", hit)
        self.assertEqual(hit["armor_before"], 5)
        self.assertLessEqual(hit["armor_after"], 5)
        self.assertEqual(
            hit["armor_before"] - hit["armor_after"],
            hit["armor_mitigated"],
        )

    @staticmethod
    def _apply_pool(chars, cid, key, dmg):
        pool = chars.characters[cid]["attributes"][key]
        old = int(pool["current"])
        new = max(0, old - int(dmg))
        pool["current"] = new
        return old, new

    def test_derived_so_has_source_provenance(self):
        payload = build_derived_so_payload(route=ROUTE_A_HP0)
        wf = payload["world_fact"]
        self.assertEqual(wf["validated_kill_route_id"], ROUTE_A_HP0)
        self.assertEqual(wf["fact_origin"], "SOURCE")
        self.assertTrue(wf["may_define_kill_route"])


if __name__ == "__main__":
    unittest.main()
