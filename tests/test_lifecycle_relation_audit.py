import json

from tools.audit_lifecycle_relations import audit


def _write(root, unified, session):
    (root / "unified-event-log.json").write_text(json.dumps(unified), encoding="utf-8")
    (root / "session-log.json").write_text(json.dumps(session), encoding="utf-8")


def _pair(relation="lr-1"):
    unified = [{
        "event_type": "LOCATION_CHANGE", "lifecycle_relation_id": relation,
        "selected_action": "move", "actor": "pc_01",
        "state_before": {"location": "a"}, "state_after": {"location": "b"},
    }]
    session = [{
        "location": "a", "text": "システム: 【移動】a から b",
        "meta": {"lifecycle_relation_id": relation, "action_id": "move", "target": "b", "actor_id": "pc_01"},
    }]
    return unified, session


def test_complete_relation_pair_passes(tmp_path):
    unified, session = _pair()
    _write(tmp_path, unified, session)
    report = audit(tmp_path)
    assert report["status"] == "PASS"
    assert report["relation_pairs"] == 1


def test_missing_and_ambiguous_relations_fail(tmp_path):
    unified, session = _pair("")
    _write(tmp_path, unified, session)
    assert audit(tmp_path)["lifecycle_relation_missing"] == 2

    unified, session = _pair()
    unified.append(dict(unified[0]))
    _write(tmp_path, unified, session)
    report = audit(tmp_path)
    assert report["status"] == "FAIL"
    assert report["lifecycle_relation_ambiguous"] == 1


def test_v8_historical_actor_contradiction_is_reproduced_exactly(tmp_path):
    unified, session = _pair("lifecycle_b51ee8ad2fe24ec7925b2eb3e2ec2dd9")
    session[0]["meta"]["actor_id"] = "pc_02"
    _write(tmp_path, unified, session)
    report = audit(tmp_path)
    assert report["status"] == "FAIL"
    assert report["lifecycle_relation_contradictory"] == 1
    assert report["lifecycle_actor_contradiction"] == 1
    assert report["contradiction_details"] == [{
        "lifecycle_relation_id": "lifecycle_b51ee8ad2fe24ec7925b2eb3e2ec2dd9",
        "authority_actor": "pc_01", "display_actor": "pc_02",
        "authority_from": "a", "display_from": "a",
        "authority_to": "b", "display_to": "b",
        "actor_contradiction": True, "structural_contradiction": False,
    }]


def test_patched_producer_rotation_and_next_actor_are_contradiction_free(tmp_path):
    first_u, first_s = _pair("lr-patched-actor-a")
    second_u, second_s = _pair("lr-patched-actor-b")
    first_u[0]["actor"] = first_s[0]["meta"]["actor_id"] = "pc_01"
    second_u[0].update({
        "actor": "pc_02",
        "state_before": {"location": "b"},
        "state_after": {"location": "c"},
    })
    second_s[0].update({"location": "b"})
    second_s[0]["meta"].update({"actor_id": "pc_02", "target": "c"})
    _write(tmp_path, first_u + second_u, first_s + second_s)
    report = audit(tmp_path)
    assert report["status"] == "PASS"
    assert report["lifecycle_relation_contradictory"] == 0
    assert report["lifecycle_actor_contradiction"] == 0
