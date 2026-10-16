import importlib.util
from pathlib import Path

from video_agent.normalizer.session import _dice, _merge_adjudications


def _event(event_id, stream, aid, dice, modifier=None):
    return {
        "event_id": event_id, "adjudication_id": aid, "dice": dice,
        "modifier": modifier,
        "metadata": {"source_stream": stream},
    }


def test_target_uses_final_target_and_preserves_base_target():
    dice = _dice({
        "base_target": 32, "final_target": 65, "target_value": 32,
        "roll": 20, "raw_result": "HARD_SUCCESS", "final_result": "HARD_SUCCESS",
        "resolution_mode": "ROLL", "skill_or_stat": "目星",
    })
    assert dice["base_target"] == 32
    assert dice["target_value"] == 65


def test_combat_effect_and_special_objective_are_not_roll_results():
    combat = _dice({
        "event_type": "COMBAT_ACTION_RESOLVED", "resolution_mode": "ROLL",
        "target_value": 55, "roll": 32, "raw_result": "REGULAR_SUCCESS",
        "final_result": "HIT_ATTACKER", "skill": "近接戦闘",
    })
    assert combat["roll_result"] == "REGULAR_SUCCESS"
    assert combat["effect_result"] == "HIT_ATTACKER"
    special = _dice({
        "event_type": "SPECIAL_OBJECTIVE_COMPLETED", "resolution_mode": "NO_ROLL",
        "final_result": "SPECIAL_OBJECTIVE_COMPLETED",
    })
    assert special["objective_outcome"] == "SPECIAL_OBJECTIVE_COMPLETED"


def test_contradiction_detector_keeps_same_tier_conflicts_but_respects_source_priority():
    warnings = []
    rows = [
        _event("u", "unified_event_log", "a", {"resolution_mode": "ROLL", "target_value": 65}),
        _event("s", "session_log", "a", {"resolution_mode": "ROLL", "target_value": 32}),
    ]
    _merge_adjudications(rows, warnings)
    assert warnings == []
    assert all(row["dice"]["target_value"] == 65 for row in rows)
    warnings = []
    rows = [
        _event("u1", "unified_event_log", "b", {"resolution_mode": "ROLL", "target_value": 65}),
        _event("u2", "unified_event_log", "b", {"resolution_mode": "ROLL", "target_value": 32}),
    ]
    _merge_adjudications(rows, warnings)
    assert [item["code"] for item in warnings] == ["NORMALIZATION_SOURCE_CONTRADICTION"]


def test_deterministic_auditor_contract_fixture_is_clean():
    path = Path(__file__).resolve().parents[1] / "tools" / "audit_longrun_formal_v2.py"
    spec = importlib.util.spec_from_file_location("formal_auditor_v2_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    unified = [{
        "event_id": "e1", "adjudication_id": "adj", "resolution_mode": "ROLL",
        "actor": "pc", "target": "desk", "skill_or_stat": "目星",
        "target_value": 65, "roll": 20, "raw_result": "HARD_SUCCESS",
        "final_result": "HARD_SUCCESS", "modifier": {"type": "NONE"},
    }, {
        "event_id": "e2", "adjudication_id": "auto", "resolution_mode": "NO_ROLL",
        "resolution_reason": "SCENARIO_NO_ROLL", "final_result": "SUCCESS",
    }]
    assert module.audit_roll_contract(unified, [], "fixture") == []
    normalized = [{"event_id": "n1", "source_event_ids": ["e1"]}]
    findings, rate = module.audit_traceability(
        normalized, {"source_traceability_rate": 1.0}, {"status": "PASS"}, "fixture",
    )
    assert findings == []
    assert rate == 1.0
    assert module.audit_normalizer_warnings(
        {"metadata": {"conversion_warnings": []}}, "fixture",
    ) == []
