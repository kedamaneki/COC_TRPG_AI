from types import SimpleNamespace

from main import append_system_log_entry, ensure_lifecycle_relation_id
from ProgressDirectorV2 import record_unified_turn


def test_producer_relation_is_shared_without_reusing_event_identity():
    result = {"location_changed": True, "new_location": "b", "log": "【移動】a から b"}
    ensure_lifecycle_relation_id(result, transaction_id="tx-1")
    assert result["lifecycle_relation_id"] == "lifecycle_tx_tx-1"

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
    ensure_lifecycle_relation_id(result)
    first = result["lifecycle_relation_id"]
    ensure_lifecycle_relation_id(result)
    assert result["lifecycle_relation_id"] == first
    assert first.startswith("lifecycle_")
