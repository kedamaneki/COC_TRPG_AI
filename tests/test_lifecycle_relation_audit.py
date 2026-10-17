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
