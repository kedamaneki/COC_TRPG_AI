import unittest

from ProgressDirectorV2 import (
    AUTONOMOUS,
    HUMAN_FORCED,
    SYSTEM_FORCED,
    GoalManagerV2,
    ProgressTrackerV2,
    StallDetectorV2,
    count_forced_from_action_origin,
    apply_s4_candidate_override,
    migrate_legacy_action_origins,
    record_unified_turn,
)


class FakeScenario:
    def __init__(self):
        self.flags = {"exit_found": False, "ladder_searched": False}
        self.location = "hallway"
        self.current_phase = "exploration"
        self.scenario_data = {
            "scenario_meta": {"title": "脱出試験"},
            "locations": {
                "hallway": {"connected_to": ["secret_room"], "exits": {"secret_room": {}}},
                "secret_room": {"connected_to": ["hallway"], "exits": {"hallway": {}}},
            },
        }
        self.event_triggers = [
            {
                "event_id": "find_exit", "priority": 10,
                "trigger_condition": (
                    "action_id == 'search' and target == 'escape_ladder' "
                    "and location == 'secret_room' and flags.ladder_searched == false"
                ),
                "payload": {"flag_updates": {"ladder_searched": True}},
            },
            {
                "event_id": "escape", "priority": 20,
                "trigger_condition": (
                    "action_id == 'climb' and target == 'escape_ladder' "
                    "and location == 'secret_room' and flags.ladder_searched == true"
                ),
                "payload": {"new_phase": "clear", "system_log": "【クリア】脱出"},
            },
        ]

    def get_available_exits(self, location):
        exits = (self.scenario_data["locations"].get(location) or {}).get("exits") or {}
        return [{"id": key, "name": key} for key in exits]


class ProgressTrackerV2Tests(unittest.TestCase):
    def test_location_roundtrip_alone_is_not_progress(self):
        before = {"location": "a", "phase": "exploration", "flags": {}, "public_knowledge": [], "pc_knowledge": {}}
        after = {**before, "location": "b"}
        delta = ProgressTrackerV2.evaluate(before, after, visited_locations=["a", "b"])
        self.assertEqual(delta["progress_delta"], 0)

    def test_important_information_is_progress(self):
        before = {"location": "a", "phase": "exploration", "flags": {}, "public_knowledge": [], "pc_knowledge": {}}
        after = {**before, "public_knowledge": ["clue:door"]}
        delta = ProgressTrackerV2.evaluate(before, after)
        self.assertEqual(delta["progress_delta"], 2)
        self.assertIn("clue:door", delta["knowledge_gained"])

    def test_goal_requirement_completion_is_major_progress(self):
        before = {"location": "secret_room", "phase": "exploration", "flags": {"ladder_searched": False}, "public_knowledge": [], "pc_knowledge": {}}
        after = {**before, "flags": {"ladder_searched": True}}
        g0 = {"remaining_requirements": ["flag:ladder_searched=true", "action:climb/escape_ladder"]}
        g1 = {"remaining_requirements": ["action:climb/escape_ladder"]}
        delta = ProgressTrackerV2.evaluate(before, after, g0, g1)
        self.assertEqual(delta["progress_delta"], 3)


class GoalManagerV2Tests(unittest.TestCase):
    def test_extracts_unmet_condition_and_routes_toward_it(self):
        scenario = FakeScenario()
        goal = GoalManagerV2(scenario).build("hallway")
        self.assertIn("flag:ladder_searched=true", goal["remaining_requirements"])
        self.assertEqual(goal["candidate_next_actions"][0]["action"], "move")
        self.assertEqual(goal["candidate_next_actions"][0]["target"], "secret_room")

    def test_completed_condition_is_excluded_from_remaining(self):
        scenario = FakeScenario()
        scenario.flags["ladder_searched"] = True
        goal = GoalManagerV2(scenario).build("secret_room")
        self.assertIn("flag:ladder_searched=true", goal["completed_requirements"])
        self.assertNotIn("flag:ladder_searched=true", goal["remaining_requirements"])

    def test_only_remaining_action_is_prioritized(self):
        scenario = FakeScenario()
        scenario.flags["ladder_searched"] = True
        goal = GoalManagerV2(scenario).build("secret_room")
        candidate = goal["candidate_next_actions"][0]
        self.assertEqual((candidate["action"], candidate["target"]), ("climb", "escape_ladder"))

    def test_hidden_destination_routes_through_unlock_event(self):
        scenario = FakeScenario()
        scenario.scenario_data["locations"]["hallway"]["exits"] = {}
        scenario.scenario_data["locations"]["hallway"]["connected_to"] = []
        scenario.event_triggers.insert(0, {
            "event_id": "open_secret_room", "priority": 30,
            "trigger_condition": (
                "action_id == 'search' and target == 'wall_panel' "
                "and location == 'hallway' and flags.trapdoor_found == false"
            ),
            "payload": {"flag_updates": {"trapdoor_found": True}},
        })
        scenario.event_triggers.insert(1, {
            "event_id": "enter_secret_room", "priority": 40,
            "trigger_condition": (
                "action_id == 'move' and target == 'secret_room' "
                "and location == 'hallway' and flags.trapdoor_found == true"
            ),
            "payload": {"new_location": "secret_room"},
        })
        scenario.flags["trapdoor_found"] = False
        goal = GoalManagerV2(scenario).build("hallway")
        candidate = goal["candidate_next_actions"][0]
        self.assertEqual((candidate["action"], candidate["target"]), ("search", "wall_panel"))


class StallDetectorV2Tests(unittest.TestCase):
    def test_detects_same_roundtrip_twice(self):
        state = {}
        for before, after in [("a", "b"), ("b", "a"), ("a", "b"), ("b", "a")]:
            state = StallDetectorV2.update(
                state, action="move", target=after,
                location_before=before, location_after=after, progress_delta=0,
            )
        self.assertIn("location_pingpong", state["signals"])

    def test_detects_repeated_action(self):
        state = {}
        for _ in range(3):
            state = StallDetectorV2.update(
                state, action="search", target="desk",
                location_before="study", location_after="study", progress_delta=0,
            )
        self.assertIn("repeated_action", state["signals"])

    def test_detects_three_no_progress_turns(self):
        state = {}
        for i in range(3):
            state = StallDetectorV2.update(
                state, action="search", target=str(i),
                location_before="study", location_after="study", progress_delta=0,
            )
        self.assertEqual(state["no_progress_streak"], 3)
        self.assertEqual(state["intervention_level"], "S2")

    def test_intervention_escalates_one_level_per_no_progress_turn(self):
        state = {}
        levels = []
        for i in range(3):
            state = StallDetectorV2.update(
                state, action="search", target=str(i),
                location_before="study", location_after="study", progress_delta=0,
            )
            levels.append(state["intervention_level"])
        self.assertEqual(levels, ["S0", "S1", "S2"])

    def test_progress_resets_no_progress_streak(self):
        state = {"no_progress_streak": 4}
        state = StallDetectorV2.update(
            state, action="search", target="new_clue",
            location_before="study", location_after="study", progress_delta=2,
        )
        self.assertEqual(state["no_progress_streak"], 0)


class InterventionOriginTests(unittest.TestCase):
    def test_s4_overrides_only_after_s3_candidate_is_ignored(self):
        state = {"director_v2": {
            "stall": {"intervention_level": "S4"},
            "goal": {"candidate_next_actions": [{"action": "climb", "target": "ladder"}]},
        }}
        fixed = apply_s4_candidate_override(state, {"action": "move", "target": "hallway"})
        self.assertEqual((fixed["action"], fixed["target"]), ("climb", "ladder"))
        self.assertEqual(fixed["action_origin"], SYSTEM_FORCED)
        self.assertEqual(fixed["intervention_level"], "S4")

    def test_forced_origins_are_counted_and_autonomous_is_not(self):
        state = {"unified_event_log": [
            {"action_origin": SYSTEM_FORCED},
            {"action_origin": HUMAN_FORCED},
            {"action_origin": AUTONOMOUS},
        ]}
        self.assertEqual(count_forced_from_action_origin(state), 2)

    def test_legacy_alias_does_not_override_canonical_origin(self):
        logs = [
            {"meta": {"action_id": "move", "pc_id": "pc1", "action_origin": AUTONOMOUS, "forced_by_system": True}},
        ]
        self.assertEqual(count_forced_from_action_origin({}, logs), 0)

    def test_legacy_save_is_migrated_to_canonical_origin(self):
        save = {"app_state": {"all_events_log": [
            {"meta": {"action_id": "move", "pc_id": "pc1", "forced_by_system": True}},
            {"meta": {"action_id": "search", "pc_id": "pc1"}},
        ]}}
        migrate_legacy_action_origins(save)
        logs = save["app_state"]["all_events_log"]
        self.assertEqual(logs[0]["meta"]["action_origin"], SYSTEM_FORCED)
        self.assertEqual(logs[1]["meta"]["action_origin"], AUTONOMOUS)

    def test_unified_event_contains_required_fields(self):
        state = {"current_loc": "hallway", "pl_id": "pc1"}
        scenario = FakeScenario()
        event = record_unified_turn(
            state, scenario,
            action={
                "action": "search", "target": "door", "pc_id": "pc1",
                "dialogue": "扉を調べる", "transaction_id": "txn-1",
                "action_origin": AUTONOMOUS,
            },
            result={"status": "success"},
        )
        required = {
            "turn_id", "scene_id", "actor", "location", "current_goal",
            "action_intent", "selected_action", "target", "action_origin",
            "dice_used", "skill", "target_value", "roll", "result",
            "state_before", "state_after", "knowledge_gained", "flags_changed",
            "progress_delta", "progress_reason", "stall_count",
            "intervention_level", "intervention_reason", "forced_action",
            "human_intervention", "transaction_id",
        }
        self.assertTrue(required.issubset(event))
        self.assertTrue(event["event_id"])
        self.assertEqual(event["raw_event_offset"], 0)

    def test_summary_inherits_source_adjudication(self):
        state = {"current_loc": "hallway", "pl_id": "pc1"}
        scenario = FakeScenario()
        evidence = {
            "adjudication_id": "adj-social", "resolution_mode": "ROLL",
            "skill_or_stat": "説得", "target_value": 65, "roll": 42,
            "raw_result": "REGULAR_SUCCESS", "final_result": "REGULAR_SUCCESS",
            "modifier": {"type": "NONE"},
        }
        event = record_unified_turn(
            state, scenario,
            action={"action": "negotiate", "target": "clerk", "pc_id": "pc1"},
            result={"status": 2, "dice": {"roll": 42, "target_value": 65},
                    "adjudication": evidence},
        )
        self.assertEqual(event["adjudication_id"], "adj-social")
        self.assertEqual(event["resolution_mode"], "ROLL")
        self.assertEqual(event["roll"], 42)

    def test_s4_event_uses_action_snapshot_and_records_major_progress(self):
        scenario = FakeScenario()
        scenario.location = "secret_room"
        state = {"current_loc": "secret_room", "pl_id": "pc1", "director_v2": {}}
        action = {
            "action": "move", "target": "secret_room", "pc_id": "pc1",
            "transaction_id": "txn-s4", "action_origin": SYSTEM_FORCED,
            "intervention_level": "S4", "intervention_reason": "s3_candidate_ignored",
            "_director_state_before": {
                "location": "hallway", "phase": "exploration", "flags": dict(scenario.flags),
                "public_knowledge": [], "pc_knowledge": {},
            },
            "_director_goal_before": {
                "remaining_requirements": ["location:secret_room", "flag:ladder_searched=true"],
            },
        }
        event = record_unified_turn(state, scenario, action=action, result={"status": "success"})
        self.assertEqual(event["state_before"]["location"], "hallway")
        self.assertEqual(event["state_after"]["location"], "secret_room")
        self.assertEqual(event["progress_delta"], 3)
        self.assertEqual(event["stall_count"], 0)
        self.assertEqual(event["intervention_level"], "S4")

    def test_simple_move_commits_lifecycle_without_resolution_mode(self):
        scenario = FakeScenario()
        scenario.location = "secret_room"
        state = {"current_loc": "secret_room", "pl_id": "pc1", "director_v2": {}}
        action = {
            "action": "move", "target": "secret_room", "pc_id": "pc1",
            "_director_state_before": {"location": "hallway", "phase": "exploration", "flags": {}, "public_knowledge": [], "pc_knowledge": {}},
        }
        event = record_unified_turn(state, scenario, action=action, result={"status": "success", "location_changed": True})
        self.assertEqual(event["event_type"], "LOCATION_CHANGE")
        self.assertNotIn("resolution_mode", event)
        self.assertEqual(len(state["unified_event_log"]), 1)

    def test_checked_move_splits_adjudication_and_lifecycle(self):
        scenario = FakeScenario()
        scenario.location = "secret_room"
        state = {"current_loc": "secret_room", "pl_id": "pc1", "director_v2": {}}
        evidence = {
            "adjudication_id": "adj_move", "resolution_mode": "NO_ROLL",
            "resolution_reason": "SCENARIO_GATE", "final_result": "LOCATION_CHANGE_ALLOWED",
        }
        action = {
            "action": "move", "target": "secret_room", "pc_id": "pc1",
            "_director_state_before": {"location": "hallway", "phase": "exploration", "flags": {}, "public_knowledge": [], "pc_knowledge": {}},
        }
        event = record_unified_turn(
            state, scenario, action=action,
            result={"status": "success", "location_changed": True, "adjudication": evidence},
        )
        adjudication, lifecycle = state["unified_event_log"]
        self.assertEqual(adjudication["event_type"], "MOVE_ACTION_RESOLVED")
        self.assertEqual(adjudication["resolution_mode"], "NO_ROLL")
        self.assertEqual(lifecycle["event_type"], "LOCATION_CHANGE")
        self.assertEqual(lifecycle["cause_adjudication_id"], "adj_move")
        self.assertNotIn("resolution_mode", lifecycle)
        self.assertIs(event, lifecycle)


if __name__ == "__main__":
    unittest.main()
