from types import SimpleNamespace

from main import append_system_log_entry, ensure_lifecycle_relation_id
from ProgressDirectorV2 import record_unified_turn


def test_producer_relation_is_shared_without_reusing_event_identity():
    result = {"location_changed": True, "new_location": "b", "log": "【移動】a から b"}
    ensure_lifecycle_relation_id(result, transaction_id="tx-1", actor_id="pc_01")
    assert result["lifecycle_relation_id"] == "lifecycle_tx_tx-1"
    assert result["lifecycle_actor_id"] == "pc_01"

    logs = []
    append_system_log_entry(
        logs, "a", result["log"], action_id="move", target="b",
        roll_type="none", transaction_id="tx-1", actor_id="pc_01",
        adjudication=result,
    )
    assert logs[0]["meta"]["lifecycle_relation_id"] == result["lifecycle_relation_id"]

    state = {
        "evaluation_session_id": "fixture", "pl_id": "pc_01",
        "unified_event_log": [], "director_v2": {
            "state_before": {"location": "a", "flags": {}, "pc_knowledge": {}, "public_knowledge": []},
            "goal_before": {}, "visited_locations": ["a"],
        },
    }
    scenario = SimpleNamespace(
        location="b", flags={}, meta={}, scenario_meta={},
        get_current_phase=lambda: "investigation",
    )
    action = {"action": "move", "target": "b", "actor_id": "pc_01", "transaction_id": "tx-1"}
    row = record_unified_turn(state, scenario, result=result, action=action)
    assert row["lifecycle_relation_id"] == logs[0]["meta"]["lifecycle_relation_id"]
    assert row["event_id"] != ""


def test_relation_allocator_is_idempotent_for_unkeyed_forced_move():
    result = {"location_changed": True, "new_location": "b"}
    ensure_lifecycle_relation_id(result, actor_id="pc_01")
    first = result["lifecycle_relation_id"]
    ensure_lifecycle_relation_id(result, actor_id="pc_01")
    assert result["lifecycle_relation_id"] == first
    assert first.startswith("lifecycle_")


def test_lifecycle_actor_cannot_change_after_resolution():
    result = {"location_changed": True, "new_location": "b"}
    ensure_lifecycle_relation_id(result, actor_id="pc_01")
    try:
        ensure_lifecycle_relation_id(result, actor_id="pc_02")
    except ValueError as exc:
        assert "actor identity changed" in str(exc)
    else:
        raise AssertionError("actor mutation must fail closed")


def test_frozen_lifecycle_actor_survives_turn_rotation_and_next_event_uses_next_actor():
    state = {
        "evaluation_session_id": "rotation-fixture", "pl_id": "pc_02",
        "unified_event_log": [], "director_v2": {
            "state_before": {"location": "a", "flags": {}, "pc_knowledge": {}, "public_knowledge": []},
            "goal_before": {}, "visited_locations": ["a"],
        },
    }
    scenario = SimpleNamespace(
        location="b", flags={}, meta={}, scenario_meta={},
        get_current_phase=lambda: "investigation",
    )
    first = {"location_changed": True, "new_location": "b", "status": "success"}
    ensure_lifecycle_relation_id(first, actor_id="pc_01")
    first_row = record_unified_turn(
        state, scenario, result=first,
        action={"action": "move", "target": "b", "actor_id": "pc_01"},
    )
    assert first_row["actor"] == "pc_01"
    assert first_row["lifecycle_actor_id"] == "pc_01"

    state["director_v2"]["state_before"] = {
        "location": "b", "flags": {}, "pc_knowledge": {}, "public_knowledge": [],
    }
    scenario.location = "c"
    second = {"location_changed": True, "new_location": "c", "status": "success"}
    ensure_lifecycle_relation_id(second, actor_id="pc_02")
    second_row = record_unified_turn(
        state, scenario, result=second,
        action={"action": "move", "target": "c", "actor_id": "pc_02"},
    )
    assert second_row["actor"] == "pc_02"
    assert second_row["lifecycle_actor_id"] == "pc_02"
