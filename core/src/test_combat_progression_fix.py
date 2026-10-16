import unittest

import main as game_main

from CombatProgression import (
    COMBAT_ACTIVE,
    COMBAT_ENDED,
    append_combat_event,
    build_combat_action_candidates,
    combat_prompt_block,
    evaluate_combat_end,
    guide_combat_action,
    resolve_escape_action,
    validate_combat_action,
    validate_combat_location,
)
from GameStateManager import GameStateManager
from ScenarioManager import ScenarioManager


class FakeCharacters:
    def __init__(self):
        self.active_pc_list = []
        self.characters = {
            "pc": {
                "profile": {"name": "PC", "is_npc": False},
                "attributes": {"DEX": 60},
                "skills": {"近接戦闘（格闘）": 50, "回避": 30},
                "states": [],
                "stats": {"HP": {"current": 10}, "SAN": {"current": 50}},
            },
            "enemy": {
                "profile": {"name": "Enemy", "is_npc": True},
                "attributes": {"DEX": 40},
                "skills": {"近接戦闘（格闘）": 40},
                "states": [],
                "stats": {"HP": {"current": 8}, "SAN": {"current": 0}},
            },
            "pc2": {
                "profile": {"name": "PC2", "is_npc": False},
                "attributes": {"DEX": 50},
                "skills": {"近接戦闘（格闘）": 45, "回避": 35},
                "states": [],
                "stats": {"HP": {"current": 9}, "SAN": {"current": 55}},
            },
        }

    def get_attribute(self, cid, key):
        return self.characters[cid].get("attributes", {}).get(key, 0)

    def get_skill(self, cid, key):
        return self.characters[cid].get("skills", {}).get(key, 0)

    def get_stat_current(self, cid, key):
        return self.characters[cid].get("stats", {}).get(key, {}).get("current", 0)

    def get_pc(self, cid):
        char = self.characters.get(cid)
        if char and not char.get("profile", {}).get("is_npc"):
            return char
        return None

    def get_pc_name(self, cid, default=None):
        char = self.get_pc(cid)
        return char.get("profile", {}).get("name", default) if char else default

    def is_pc_incapacitated(self, cid, state_mgr=None):
        return bool(state_mgr and state_mgr.is_combat_participant_incapacitated(cid))

    def set_active_pcs(self, pc_ids):
        self.active_pc_list = list(pc_ids or [])


def scenario_data(*, escape=False):
    exit_meta = {"combat_escape": True} if escape else {}
    return {
        "scenario_meta": {"title": "combat-test"},
        "initial_state": {"location": "arena", "phase": "investigation", "flags": {"boss_seen": True}},
        "locations": {
            "arena": {
                "objects": {"seal": {"name": "Seal", "usable_actions": ["inspect"]}},
                "connected_to": ["safe"],
                "exits": {"safe": exit_meta},
            },
            "safe": {"objects": {}, "connected_to": ["arena"], "exits": {"arena": {}}},
        },
        "event_triggers": [{
            "event_id": "seal_breaks_combat",
            "priority": 90,
            "trigger_condition": (
                "action_id in ['break', 'force'] and target == 'seal' "
                "and location == 'arena' and flags.boss_seen == true and success_level >= 2"
            ),
            "action_type": "update_and_describe",
            "payload": {"combat_end": True, "new_phase": "clear", "flag_updates": {"won": True}},
        }],
    }


class CombatProgressionFixTests(unittest.TestCase):
    def setUp(self):
        self.chars = FakeCharacters()
        self.state_mgr = GameStateManager(self.chars)
        self.scenario = ScenarioManager(scenario_data())
        self.scenario.location = "arena"
        self.state = {"current_loc": "arena", "active_pcs": ["pc"], "unified_event_log": []}
        self.state_mgr.start_combat(["pc", "enemy"], location_id="arena")

    def candidates(self):
        return build_combat_action_candidates(
            self.state_mgr, self.chars, self.scenario, "pc", "arena", active_pc_ids=["pc"]
        )

    def test_combat_start_sets_active_single_source_of_truth(self):
        self.assertTrue(self.state_mgr.in_combat)
        self.assertEqual(self.state_mgr.combat_state, COMBAT_ACTIVE)
        self.assertEqual(self.state_mgr.combat_location_id, "arena")
        self.assertTrue(self.state_mgr.combat_id)

    def test_combat_state_survives_save_and_load(self):
        saved = self.state_mgr.export_to_dict()
        restored = GameStateManager(self.chars)
        restored.load_from_dict(saved)
        self.assertEqual(restored.combat_state, COMBAT_ACTIVE)
        self.assertEqual(restored.combat_location_id, "arena")
        self.assertEqual(restored.get_current_actor(), "pc")

    def test_active_candidates_exclude_normal_exploration_and_move(self):
        candidates = self.candidates()
        actions = {item["action"] for item in candidates}
        self.assertFalse(actions & {"search", "inspect", "talk", "wait", "move"})
        self.assertIn("attack", actions)
        self.assertIn("break", actions)

    def test_scenario_combat_end_event_generates_special_candidate(self):
        special = [row for row in self.candidates() if row["category"] == "SPECIAL"]
        self.assertIn(("break", "seal"), {(row["action"], row["target"]) for row in special})

    def test_normal_location_move_is_illegal_during_combat(self):
        verdict = validate_combat_action({"action": "move", "target": "safe"}, self.candidates())
        self.assertFalse(verdict["legal"])
        self.assertEqual(verdict["reason"], "normal_location_move_forbidden_during_combat")

    def test_illegal_action_is_guided_to_legal_candidate(self):
        guided, verdict = guide_combat_action(
            {"action": "search", "target": "seal", "transaction_id": "t1"},
            self.candidates(), state_mgr=self.state_mgr,
        )
        self.assertFalse(verdict["legal"])
        self.assertTrue(guided["combat_guided"])
        self.assertEqual(guided["combat_legality"], "LEGAL")
        self.assertNotIn(guided["action"], {"search", "move", "wait"})

    def test_illegal_signature_is_remembered(self):
        guide_combat_action(
            {"action": "move", "target": "safe"}, self.candidates(), state_mgr=self.state_mgr,
        )
        self.assertIn("move:safe", self.state_mgr.combat_illegal_actions)

    def test_prompt_lists_only_combat_candidates(self):
        prompt = combat_prompt_block(self.candidates(), self.state_mgr, self.chars)
        self.assertIn("通常moveは禁止", prompt)
        self.assertIn("action=attack", prompt)
        self.assertNotIn("action=search", prompt)

    def test_enemy_incapacitation_satisfies_end_condition(self):
        self.chars.characters["enemy"]["stats"]["HP"]["current"] = 0
        status = evaluate_combat_end(self.state_mgr, active_pc_ids=["pc"])
        self.assertTrue(status["ended"])
        self.assertEqual(status["reason"], "enemies_incapacitated")

    def test_end_transitions_to_ended_and_normal_progression_ready(self):
        self.state_mgr.end_combat("enemies_incapacitated")
        self.assertFalse(self.state_mgr.in_combat)
        self.assertEqual(self.state_mgr.combat_state, COMBAT_ENDED)
        self.assertEqual(self.state_mgr.combat_end_reason, "enemies_incapacitated")

    def test_rounds_advance_without_location_change(self):
        self.state_mgr.next_turn()
        self.state_mgr.next_turn()
        self.state_mgr.next_turn()
        self.assertGreaterEqual(self.state_mgr.round_number, 2)
        self.assertEqual(self.state_mgr.combat_location_id, "arena")

    def test_location_inconsistency_is_detected_and_repaired(self):
        self.scenario.location = "safe"
        self.state["current_loc"] = "safe"
        result = validate_combat_location(self.state, self.state_mgr, self.scenario)
        self.assertFalse(result["ok"])
        self.assertEqual(self.state["current_loc"], "arena")
        self.assertEqual(self.state["unified_event_log"][-1]["event_type"], "COMBAT_LOCATION_INCONSISTENCY")

    def test_combat_log_contains_required_fields_and_origin(self):
        append_combat_event(
            self.state, "COMBAT_ACTION_RESOLVED", state_mgr=self.state_mgr,
            actor="pc", target="enemy", combat_goal="ENEMY_DEFEATED",
            action_category="ATTACK", selected_action="attack",
            action_origin="SYSTEM_GUIDED", legality="LEGAL", skill="近接戦闘（格闘）",
            roll=42, result="hit", damage=3, HP_before=8, HP_after=5,
            SAN_before=50, SAN_after=50, position_before="arena", position_after="arena",
            effect="damage", combat_progress_delta=1, transaction_id="t1",
        )
        row = self.state["unified_event_log"][-1]
        for key in (
            "combat_id", "round", "actor", "target", "combat_goal", "action_category",
            "selected_action", "action_origin", "legality", "HP_before", "HP_after",
            "position_before", "position_after", "combat_progress_delta", "combat_end_condition",
        ):
            self.assertIn(key, row)
        self.assertEqual(row["action_origin"], "SYSTEM_GUIDED")

    def test_escape_requires_explicit_combat_escape_route(self):
        failed = resolve_escape_action(
            self.state, self.state_mgr, self.scenario,
            actor_id="pc", destination="safe", success=True,
        )
        self.assertFalse(failed["ok"])
        self.assertTrue(self.state_mgr.in_combat)

    def test_escape_success_ends_combat_and_changes_location_atomically(self):
        scenario = ScenarioManager(scenario_data(escape=True))
        scenario.location = "arena"
        result = resolve_escape_action(
            self.state, self.state_mgr, scenario,
            actor_id="pc", destination="safe", success=True,
            transaction_id="escape-1",
        )
        self.assertTrue(result["ok"])
        self.assertFalse(self.state_mgr.in_combat)
        self.assertEqual(self.state["current_loc"], "safe")
        self.assertEqual(scenario.location, "safe")
        types = [row["event_type"] for row in self.state["unified_event_log"]]
        self.assertIn("ESCAPE_ATTEMPT", types)
        self.assertIn("ESCAPE_SUCCESS", types)
        self.assertIn("COMBAT_ENDED", types)

    def test_scenario_declared_combat_resolution_bypasses_stale_object_actions(self):
        self.assertTrue(
            self.scenario._is_scenario_combat_resolution_action("break", "seal", "arena")
        )
        blocked = self.scenario.evaluate_pre_action_guard("break", "seal", "arena")
        self.assertIsNone(blocked)

    def test_timeline_handoff_preserves_special_combat_metadata(self):
        state = {
            "current_loc": "arena",
            "all_events_log": [{
                "channel": "IC",
                "location": "arena",
                "text": "PC: sealを破壊する",
                "meta": {
                    "pc_id": "pc",
                    "actor_id": "pc",
                    "decision_owner_id": "pc",
                    "action_id": "break",
                    "target": "seal",
                    "skill": "",
                    "needs_system": True,
                    "system_processed": False,
                    "transaction_id": "special-1",
                    "action_origin": "SYSTEM_GUIDED",
                    "combat_action_category": "SPECIAL",
                    "combat_goal": "SPECIAL_OBJECTIVE",
                },
            }],
        }
        action = game_main._action_data_from_timeline(
            state, self.scenario, "PC", char_mgr=None,
        )
        self.assertEqual(action["combat_action_category"], "SPECIAL")
        self.assertEqual(action["combat_goal"], "SPECIAL_OBJECTIVE")
        self.assertEqual(action["action_origin"], "SYSTEM_GUIDED")

        state.update({
            "unified_event_log": [],
            "public_knowledge_ids": [],
            "last_processed_action_id": None,
            "pending_action_id": "special-1",
            "pending_san_check": None,
            "pending_push_roll": None,
            "pending_luck_burn": None,
            "pending_combat_defense": None,
            "pending_decision": None,
            "timeline_pending": None,
            "last_system_result": None,
        })
        result = {
            "status": 2,
            "log": "seal broken",
            "action_id": "break",
            "target": "seal",
            "roll_type": "none",
            "san_check": {"required": False},
        }
        game_main.commit_system_resolution(
            state,
            result,
            current_loc="arena",
            action_data=action,
            char_mgr=self.chars,
            scenario_mgr=self.scenario,
            state_mgr=self.state_mgr,
            pl_id="pc",
            char_name="PC",
            auto_resolve_san=False,
            transaction_id="special-1",
        )
        resolved = [
            row for row in state["unified_event_log"]
            if row.get("event_type") == "COMBAT_ACTION_RESOLVED"
        ]
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["action_category"], "SPECIAL")
        self.assertEqual(resolved[0]["action_origin"], "SYSTEM_GUIDED")

    def test_scenario_special_resolves_before_combat_end_events(self):
        append_combat_event(
            self.state, "COMBAT_ACTION_SELECTED", state_mgr=self.state_mgr,
            actor="pc", target="seal", combat_goal="SPECIAL_OBJECTIVE",
            action_category="SPECIAL", selected_action="break",
            action_origin="SYSTEM_GUIDED", legality="LEGAL",
            HP_before=10, SAN_before=50, position_before="arena",
            position_after="arena", transaction_id="special-end-1",
        )
        game_main._apply_combat_payload_effects(
            {"combat_end": True},
            self.state_mgr,
            self.chars,
            "pc",
            "seal broken",
            active_pcs=["pc"],
            game_state=self.state,
            current_loc="arena",
        )
        types = [row["event_type"] for row in self.state["unified_event_log"]]
        self.assertEqual(types, [
            "COMBAT_ACTION_SELECTED",
            "COMBAT_ACTION_RESOLVED",
            "COMBAT_ENDING",
            "COMBAT_ENDED",
        ])
        resolved = self.state["unified_event_log"][1]
        self.assertEqual(resolved["transaction_id"], "special-end-1")
        self.assertEqual(resolved["action_origin"], "SYSTEM_GUIDED")
        self.assertEqual(self.state_mgr.combat_state, COMBAT_ENDED)

    def special_objective_payload(self):
        return {
            "combat_end": True,
            "adjudication_id": "adj-special-1",
            "resolution_mode": "NO_ROLL",
            "resolution_reason": "SPECIAL_OBJECTIVE:SEAL_DESTROYED",
            "trigger_event_id": "seal_breaks_combat",
            "cause_event_ids": ["seal_breaks_combat"],
            "state_before": {"won": False},
            "state_after": {"won": True},
            "world_fact": {
                "event": "SPECIAL_OBJECTIVE_COMPLETED",
                "target": "seal",
                "fact": "SEAL_DESTROYED",
            },
            "human_readable_description": "Seal destroyed.",
        }

    def select_special_objective(self):
        return append_combat_event(
            self.state, "COMBAT_ACTION_SELECTED", state_mgr=self.state_mgr,
            actor="pc", target="seal", combat_goal="SPECIAL_OBJECTIVE",
            action_category="SPECIAL", selected_action="break",
            action_origin="SYSTEM_GUIDED", legality="LEGAL",
            HP_before=10, SAN_before=50, position_before="arena",
            position_after="arena", transaction_id="special-objective-1",
            adjudication_id="adj-special-1",
        )

    def test_valid_special_objective_payload_is_accepted_with_provenance(self):
        self.select_special_objective()
        game_main._apply_combat_payload_effects(
            self.special_objective_payload(), self.state_mgr, self.chars, "pc",
            game_state=self.state, current_loc="arena",
        )
        event = next(row for row in self.state["unified_event_log"]
                     if row["event_type"] == "SPECIAL_OBJECTIVE_COMPLETED")
        self.assertEqual(event["adjudication_id"], "adj-special-1")
        self.assertEqual(event["transaction_id"], "special-objective-1")
        self.assertEqual(event["final_result"], "SPECIAL_OBJECTIVE_COMPLETED")
        self.assertEqual(event["world_fact"]["fact"], "SEAL_DESTROYED")
        self.assertEqual(event["state_before"], {"won": False})
        self.assertEqual(event["state_after"], {"won": True})
        self.assertEqual(event["cause_event_ids"], ["seal_breaks_combat"])

    def test_invalid_special_objective_payload_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "world_fact.event mismatch"):
            append_combat_event(
                self.state, "SPECIAL_OBJECTIVE_COMPLETED", state_mgr=self.state_mgr,
                actor="pc", target="seal", adjudication_id="adj-bad",
                world_fact={"event": "OTHER", "target": "seal", "fact": "SEAL_DESTROYED"},
            )

    def test_special_objective_event_is_idempotent(self):
        fields = {
            "actor": "pc", "target": "seal", "adjudication_id": "adj-special-1",
            "world_fact": {
                "event": "SPECIAL_OBJECTIVE_COMPLETED",
                "target": "seal", "fact": "SEAL_DESTROYED",
            },
        }
        first = append_combat_event(
            self.state, "SPECIAL_OBJECTIVE_COMPLETED", state_mgr=self.state_mgr, **fields,
        )
        second = append_combat_event(
            self.state, "SPECIAL_OBJECTIVE_COMPLETED", state_mgr=self.state_mgr, **fields,
        )
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertEqual(len(self.state["unified_event_log"]), 1)

    def test_special_objective_state_mutation_and_termination_happen_once(self):
        payload = self.scenario.process_action("break", "seal", 2)
        payload["adjudication_id"] = "adj-special-1"
        payload["resolution_mode"] = "NO_ROLL"
        payload.update(self.special_objective_payload())
        self.select_special_objective()
        game_main._apply_combat_payload_effects(
            payload, self.state_mgr, self.chars, "pc",
            game_state=self.state, current_loc="arena",
        )
        game_main._apply_combat_payload_effects(
            payload, self.state_mgr, self.chars, "pc",
            game_state=self.state, current_loc="arena",
        )
        types = [row["event_type"] for row in self.state["unified_event_log"]]
        self.assertTrue(self.scenario.flags["won"])
        self.assertEqual(types.count("SPECIAL_OBJECTIVE_COMPLETED"), 1)
        self.assertEqual(types.count("COMBAT_ENDING"), 1)
        self.assertEqual(types.count("COMBAT_ENDED"), 1)
        self.assertEqual(self.state_mgr.combat_state, COMBAT_ENDED)

    def test_unknown_combat_event_remains_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown combat event type"):
            append_combat_event(self.state, "UNREGISTERED_EVENT", state_mgr=self.state_mgr)

    def test_minimal_three_round_combat_ends_and_resumes_normal_progression(self):
        append_combat_event(
            self.state, "COMBAT_STARTED", state_mgr=self.state_mgr,
            actor="pc", combat_goal="ENEMY_DEFEATED",
            position_before="arena", position_after="arena",
        )
        for expected_round in (1, 2, 3):
            if expected_round > 1:
                while self.state_mgr.round_number < expected_round:
                    self.state_mgr.next_turn()
            append_combat_event(
                self.state, "COMBAT_ROUND_STARTED", state_mgr=self.state_mgr,
                actor=self.state_mgr.get_current_actor(), combat_goal="ENEMY_DEFEATED",
            )
            append_combat_event(
                self.state, "COMBAT_ACTION_SELECTED", state_mgr=self.state_mgr,
                actor="pc", target="enemy", combat_goal="ENEMY_DEFEATED",
                action_category="ATTACK", selected_action="attack",
                action_origin="AUTONOMOUS", legality="LEGAL",
                transaction_id=f"r{expected_round}",
            )
            append_combat_event(
                self.state, "COMBAT_ACTION_RESOLVED", state_mgr=self.state_mgr,
                actor="pc", target="enemy", combat_goal="ENEMY_DEFEATED",
                action_category="ATTACK", selected_action="attack",
                action_origin="AUTONOMOUS", legality="LEGAL",
                result="hit", damage=3, combat_progress_delta=1,
                transaction_id=f"r{expected_round}",
            )
        self.chars.characters["enemy"]["stats"]["HP"]["current"] = 0
        end = evaluate_combat_end(self.state_mgr, active_pc_ids=["pc"])
        self.assertTrue(end["ended"])
        append_combat_event(
            self.state, "COMBAT_ENDING", state_mgr=self.state_mgr,
            combat_end_condition=end["reason"],
        )
        self.state_mgr.end_combat(end["reason"])
        append_combat_event(
            self.state, "COMBAT_ENDED", state_mgr=self.state_mgr,
            combat_end_condition=end["reason"], effect="normal progression may resume",
        )
        self.assertFalse(self.state_mgr.in_combat)
        self.assertEqual(self.state_mgr.combat_state, COMBAT_ENDED)
        self.assertEqual(self.state["current_loc"], "arena")
        types = [row["event_type"] for row in self.state["unified_event_log"]]
        self.assertEqual(types.count("COMBAT_ROUND_STARTED"), 3)
        self.assertEqual(types.count("COMBAT_ACTION_SELECTED"), 3)
        self.assertEqual(types.count("COMBAT_ACTION_RESOLVED"), 3)
        self.assertEqual(types[-1], "COMBAT_ENDED")

    def post_combat_state(self):
        return {
            "current_loc": "arena",
            "active_pcs": ["pc", "pc2"],
            "active_pc_id": "pc",
            "pl_id": "pc",
            "char_name": "PC",
            "all_events_log": [],
            "unified_event_log": [],
            "investigation_flow": {"attempts": {"keep": {"attempt_status": "EXHAUSTED"}}},
            "director_v2": {},
            "pending_combat_defense": {"attacker_id": "enemy", "defender_id": "pc"},
            "pending_decision": {
                "decision_type": "PENDING_COMBAT_DEFENSE", "target_action_id": "attack",
            },
            "timeline_pending": "PENDING_COMBAT_DEFENSE",
            "pending_action_id": "combat-tx",
            "last_processed_action_id": "combat-tx",
            "combat_action_queue": ["stale"],
            "pending_combat_action": {"action": "attack"},
        }

    def test_multi_pc_enemy_defeat_recovers_to_inactive_once(self):
        state = self.post_combat_state()
        self.state_mgr.start_combat(["pc", "pc2", "enemy"], location_id="arena")
        combat_id = self.state_mgr.combat_id
        self.chars.characters["enemy"]["stats"]["HP"]["current"] = 0
        self.state_mgr.turn_count = 22

        recovered = game_main.reconcile_post_combat_timeline(
            state, self.state_mgr, self.scenario, self.chars,
        )
        self.assertTrue(recovered)
        self.assertFalse(self.state_mgr.in_combat)
        self.assertEqual(self.state_mgr.combat_state, "INACTIVE")
        self.assertEqual(self.state_mgr.last_combat_id, combat_id)
        self.assertEqual(self.state_mgr.get_combat_turn_queue(), [])
        self.assertIsNone(state["pending_combat_defense"])
        self.assertIsNone(state["pending_decision"])
        self.assertIsNone(state["pending_action_id"])
        self.assertEqual(state["combat_action_queue"], [])
        self.assertEqual(self.state_mgr.turn_count, 22)
        self.assertIn(state["active_pc_id"], state["active_pcs"])
        self.assertIn((state["director_v2"] or {}).get("action_phase"), {
            "DECIDE", "DISCOVER", "INVESTIGATE", "EXECUTE", "TRANSITION",
        })
        self.assertIn("keep", state["investigation_flow"]["attempts"])
        types = [row["event_type"] for row in state["unified_event_log"]]
        self.assertEqual(types.count("COMBAT_ENDING"), 1)
        self.assertEqual(types.count("COMBAT_ENDED"), 1)
        self.assertEqual(types.count("NORMAL_PROGRESSION_RESUMED"), 1)

        again = game_main.reconcile_post_combat_timeline(
            state, self.state_mgr, self.scenario, self.chars,
        )
        self.assertFalse(again)
        types = [row["event_type"] for row in state["unified_event_log"]]
        self.assertEqual(types.count("NORMAL_PROGRESSION_RESUMED"), 1)
        self.assertEqual(self.state_mgr.turn_count, 22)

    def test_timeline_selector_recovers_before_normal_action_generation(self):
        state = self.post_combat_state()
        self.state_mgr.start_combat(["pc", "pc2", "enemy"], location_id="arena")
        self.chars.characters["enemy"]["stats"]["HP"]["current"] = 0
        step = game_main.determine_timeline_next_step(
            state, "PC", self.scenario, state_mgr=self.state_mgr, char_mgr=self.chars,
        )
        self.assertFalse(self.state_mgr.in_combat)
        self.assertNotEqual(step, "combat_npc_act")
        self.assertIn(step, {"kp_opening", "kp_narrate", "pl_speak", "system_process"})

    def test_combat_round_and_session_turn_remain_independent(self):
        state = self.post_combat_state()
        self.state_mgr.start_combat(["pc", "pc2", "enemy"], location_id="arena")
        self.state_mgr.turn_count = 22
        self.state_mgr.round_number = 3
        self.chars.characters["enemy"]["stats"]["HP"]["current"] = 0
        game_main.reconcile_post_combat_timeline(state, self.state_mgr, self.scenario, self.chars)
        resumed = next(
            row for row in state["unified_event_log"]
            if row["event_type"] == "NORMAL_PROGRESSION_RESUMED"
        )
        self.assertEqual(resumed["session_turn_before"], 22)
        self.assertEqual(resumed["session_turn_after"], 22)
        self.assertEqual(self.state_mgr.round_number, 0)

    def test_normal_action_succeeds_and_advances_session_turn_after_recovery(self):
        state = self.post_combat_state()
        self.scenario.bind_game_state(self.state_mgr)
        self.state_mgr.start_combat(["pc", "pc2", "enemy"], location_id="arena")
        self.state_mgr.turn_count = 22
        self.chars.characters["enemy"]["stats"]["HP"]["current"] = 0
        game_main.reconcile_post_combat_timeline(state, self.state_mgr, self.scenario, self.chars)
        result = self.scenario.process_action("inspect", "seal", 2)
        self.assertTrue(result.get("dice_success"))
        self.assertEqual(self.state_mgr.turn_count, 23)
        self.assertEqual(self.state_mgr.combat_state, "INACTIVE")

    def test_recovery_keeps_scene_and_location_consistent(self):
        state = self.post_combat_state()
        self.state_mgr.current_scene_id = "basement_scene"
        self.state_mgr.start_combat(["pc", "pc2", "enemy"], location_id="arena")
        self.chars.characters["enemy"]["stats"]["HP"]["current"] = 0
        game_main.reconcile_post_combat_timeline(state, self.state_mgr, self.scenario, self.chars)
        resumed = state["unified_event_log"][-1]
        self.assertEqual(state["current_loc"], "arena")
        self.assertEqual(self.scenario.location, "arena")
        self.assertEqual(resumed["scene"], "basement_scene")
        self.assertEqual(resumed["location"], "arena")

    def test_recovery_failure_is_explicit_when_no_pc_can_act(self):
        state = self.post_combat_state()
        self.state_mgr.start_combat(["pc", "pc2", "enemy"], location_id="arena")
        for cid in ("pc", "pc2", "enemy"):
            self.chars.characters[cid]["stats"]["HP"]["current"] = 0
        recovered = game_main.reconcile_post_combat_timeline(
            state, self.state_mgr, self.scenario, self.chars,
        )
        self.assertFalse(recovered)
        failures = [
            row for row in state["unified_event_log"]
            if row["event_type"] == "POST_COMBAT_RECOVERY_FAILURE"
        ]
        self.assertEqual(len(failures), 1)
        self.assertIn("active_actor", failures[0]["effect"]["issues"])


if __name__ == "__main__":
    unittest.main()
