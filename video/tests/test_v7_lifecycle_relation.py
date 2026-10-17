import copy

import pytest

from video_agent.normalizer.session import normalize_session


def _source():
    return {
        "root": "v7-fixture", "source_files": [],
        "result": {"session_id": "v7-fixture"}, "scenarios": [], "pcs": {}, "npcs": {},
        "unified_events": [], "session_events": [],
    }


def _add_pair(source, index, before, after, *, transaction="", relation="", forced=False):
    source["unified_events"].append({
        "event_id": f"u{index}", "raw_event_offset": index,
        "event_type": "LOCATION_CHANGE", "selected_action": "move",
        "location": before, "target": after, "actor": "pc_01",
        "transaction_id": transaction, "lifecycle_relation_id": relation,
        "forced_action": forced, "action_origin": "SYSTEM_FORCED" if forced else "AUTONOMOUS",
        "state_before": {"location": before}, "state_after": {"location": after},
    })
    source["session_events"].append({
        "text": f"システム: 【移動】{before} から {after} へ移動した。",
        "location": before,
        "meta": {
            "event_id": f"s{index}", "action_id": "move", "target": after,
            "roll_type": "none", "transaction_id": transaction,
            "lifecycle_relation_id": relation, "actor_id": "pc_01", "kp_narrated": True,
        },
    })


def test_v7_three_duplicate_pairs_become_three_and_keep_all_sources():
    source = _source()
    _add_pair(source, 0, "introduction", "boston_globe", transaction="tx-0")
    _add_pair(source, 1, "boston_globe", "central_library", forced=True)
    # Frozen V7 forced display counterpart did not retain actor identity.
    source["session_events"][-1]["meta"].pop("actor_id")
    _add_pair(source, 2, "central_library", "the_neighborhood", transaction="tx-2")
    original = copy.deepcopy(source)

    rows = [e for e in normalize_session(source)["events"] if e["event_type"] == "LOCATION_CHANGE"]
    assert len(rows) == 3
    assert all(len(row["source_event_ids"]) == 2 for row in rows)
    assert {sid for row in rows for sid in row["source_event_ids"]} == {
        "u0", "s0", "u1", "s1", "u2", "s2",
    }
    assert source == original


def test_explicit_relations_distinguish_same_route_and_reverse_moves():
    source = _source()
    _add_pair(source, 0, "a", "b", relation="lr-0")
    _add_pair(source, 1, "a", "b", relation="lr-1")
    _add_pair(source, 2, "b", "a", relation="lr-2")
    rows = [e for e in normalize_session(source)["events"] if e["event_type"] == "LOCATION_CHANGE"]
    assert len(rows) == 3
    assert [row["lifecycle_relation_id"] for row in rows] == ["lr-0", "lr-1", "lr-2"]
    assert all(row["metadata"]["simple_move_relation"]["method"] == "lifecycle_relation_id" for row in rows)


def test_relation_many_to_one_fails_closed():
    source = _source()
    _add_pair(source, 0, "a", "b", relation="lr-0")
    duplicate = copy.deepcopy(source["session_events"][0])
    duplicate["meta"]["event_id"] = "s-extra"
    source["session_events"].append(duplicate)
    with pytest.raises(ValueError, match="DEDUP_AMBIGUOUS"):
        normalize_session(source)


def test_relationless_inferred_legacy_rows_are_not_merged():
    source = _source()
    _add_pair(source, 0, "a", "b")
    source["unified_events"][0].pop("event_type")
    source["unified_events"][0].pop("raw_event_offset")
    rows = normalize_session(source)["events"]
    assert len(rows) == 2
