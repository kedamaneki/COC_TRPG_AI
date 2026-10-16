import importlib.util
from pathlib import Path

from video_agent.normalizer.session import normalize_session


_AUDITOR_PATH = Path(__file__).parents[1] / "tools" / "audit_longrun_formal_v2.py"
_SPEC = importlib.util.spec_from_file_location("early_gate_auditor", _AUDITOR_PATH)
_AUDITOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_AUDITOR)


def _source():
    roll = {
        "resolution_mode": "ROLL", "skill_or_stat": "目星",
        "target_value": 65, "roll": 32, "raw_result": "REGULAR_SUCCESS",
        "final_result": "REGULAR_SUCCESS", "modifier": {"type": "NONE"},
    }
    unified = []
    for index in range(3):
        unified.append({
            "event_id": f"summary-{index}", "event_type": "TURN_SUMMARY",
            "adjudication_id": f"adj-summary-{index}", "dice_used": True,
            "actor": "pc_01", "target": f"clue-{index}",
            **roll,
        })
    unified.append({
        "event_id": "movement-1", "event_type": "LOCATION_CHANGE",
        "selected_action": "move", "location": "introduction",
        "state_before": {"location": "introduction"},
        "state_after": {"location": "boston_globe"},
    })
    session = []
    for index in range(2):
        session.append({
            "event_id": f"social-{index}", "location": "boston_globe",
            "text": "システム: 社交判定",
            "meta": {
                "adjudication_id": f"adj-social-{index}", **roll,
                "action_id": "negotiate", "target": "artie_wilmott",
                "actor_id": "pc_01",
            },
        })
    return {
        "root": "fixture", "source_files": [], "pcs": {}, "npcs": {},
        "scenarios": [{}], "unified_events": unified, "session_events": session,
        "result": {"session_id": "EARLY_GATE_EVIDENCE_FIXTURE", "completed": False},
    }


def test_deterministic_six_event_early_gate_acceptance():
    normalized = normalize_session(_source())
    events = normalized["events"]
    formal = [event for event in events if (event.get("dice") or {}).get("resolution_mode")]
    assert len(formal) == 5
    assert all(event.get("adjudication_id") for event in formal)
    assert all((event.get("dice") or {}).get("roll") is not None for event in formal)
    movement = next(event for event in events if event["source_event_ids"] == ["movement-1"])
    assert movement["event_type"] == "LOCATION_CHANGE"
    assert movement.get("dice") is None
    assert normalized["metadata"]["conversion_warnings"] == []
    assert normalized["provenance"]["source_event_count"] == 6
    assert all(event["source_event_ids"] for event in events)
    findings = _AUDITOR.audit_roll_contract(
        _source()["unified_events"], normalized["events"], "FIXTURE_CHECKPOINT"
    )
    assert [item for item in findings if item["category"] == "ROLL_CONTRACT_INCOMPLETE"] == []
    contradiction = _AUDITOR.audit_normalizer_warnings(normalized, "FIXTURE_CHECKPOINT")
    assert contradiction == []
    trace_findings, rate = _AUDITOR.audit_traceability(
        normalized["events"], {"source_traceability_rate": 1.0},
        {"status": "PASS"}, "FIXTURE_CHECKPOINT",
    )
    assert trace_findings == []
    assert rate == 1.0


def test_dice_used_without_structured_adjudication_is_not_promoted():
    source = _source()
    source["unified_events"] = [{
        "event_id": "bad-summary", "event_type": "TURN_SUMMARY", "dice_used": True,
        "target_value": 65, "roll": 32, "result": "REGULAR_SUCCESS",
    }]
    source["session_events"] = []
    normalized = normalize_session(source)
    assert normalized["events"][0].get("dice") is None


def test_explicit_no_roll_location_adjudication_is_split():
    source = _source()
    source["unified_events"] = [{
        "event_id": "move-adjudication", "event_type": "LOCATION_CHANGE",
        "selected_action": "move", "adjudication_id": "adj-move",
        "resolution_mode": "NO_ROLL", "resolution_reason": "NO_CHECK_REQUIRED",
        "final_result": "LOCATION_CHANGED",
    }]
    source["session_events"] = []
    events = normalize_session(source)["events"]
    adjudication = next(event for event in events if event["event_type"] == "MOVE_ACTION_RESOLVED")
    lifecycle = next(event for event in events if event["event_type"] == "LOCATION_CHANGE")
    assert adjudication["adjudication_id"] == "adj-move"
    assert adjudication["dice"]["resolution_mode"] == "NO_ROLL"
    assert adjudication["dice"]["final_result"] == "LOCATION_CHANGED"
    assert lifecycle["cause_adjudication_id"] == "adj-move"
    assert lifecycle.get("dice") is None
    assert lifecycle.get("adjudication_id") is None


def test_real_run_five_moves_and_four_session_counterparts_are_deduplicated():
    source = _source()
    source["unified_events"] = []
    source["session_events"] = []
    for index in range(5):
        aid = f"adj-move-{index}"
        source["unified_events"].append({
            "event_id": f"u-move-{index}", "selected_action": "move",
            "adjudication_id": aid, "resolution_mode": "NO_ROLL",
            "resolution_reason": "SCENARIO_NO_ROLL", "final_result": "REGULAR_SUCCESS",
            "state_before": {"location": f"room-{index}"},
            "state_after": {"location": f"room-{index + 1}"},
        })
        if index < 4:
            source["session_events"].append({
                "event_id": f"s-move-{index}", "location": f"room-{index}",
                "text": f"システム: 【移動】room-{index + 1}へ移動した。",
                "meta": {
                    "adjudication_id": aid, "resolution_mode": "NO_ROLL",
                    "resolution_reason": "SCENARIO_NO_ROLL", "final_result": "REGULAR_SUCCESS",
                    "action_id": "move", "actor_id": "pc_01",
                },
            })
    normalized = normalize_session(source)
    moves = [e for e in normalized["events"] if e["event_type"] == "MOVE_ACTION_RESOLVED"]
    lifecycles = [e for e in normalized["events"] if e["event_type"] == "LOCATION_CHANGE"]
    assert len(moves) == 5
    assert len(lifecycles) == 5
    assert len({e["adjudication_id"] for e in moves}) == 5
    assert len({e["cause_adjudication_id"] for e in lifecycles}) == 5
    assert all(e.get("dice") is None and e.get("adjudication_id") is None for e in lifecycles)
    covered = {sid for e in normalized["events"] for sid in e["source_event_ids"]}
    assert covered == {f"u-move-{i}" for i in range(5)} | {f"session_log:{i:06d}" for i in range(4)}
    assert _AUDITOR.audit_lifecycle_contract(source["unified_events"], normalized["events"], "FIXTURE") == []


def test_known_bad_lifecycle_with_no_roll_is_still_rejected():
    bad = [{
        "event_id": "bad-location", "event_type": "LOCATION_CHANGE",
        "adjudication_id": "adj-bad", "source_event_ids": ["raw-bad"],
        "dice": {"resolution_mode": "NO_ROLL"},
    }]
    findings = _AUDITOR.audit_lifecycle_contract([], bad, "FIXTURE")
    assert [item["category"] for item in findings] == ["LIFECYCLE_MISCLASSIFIED_AS_NO_ROLL"]


def test_new_core_split_preserves_explicit_cause_without_resolution():
    source = _source()
    source["unified_events"] = [{
        "event_id": "move-result", "event_type": "MOVE_ACTION_RESOLVED",
        "selected_action": "move", "adjudication_id": "adj-new-move",
        "resolution_mode": "NO_ROLL", "resolution_reason": "SCENARIO_GATE",
        "final_result": "LOCATION_CHANGE_ALLOWED",
    }, {
        "event_id": "location", "event_type": "LOCATION_CHANGE",
        "selected_action": "move", "cause_adjudication_id": "adj-new-move",
        "state_before": {"location": "a"}, "state_after": {"location": "b"},
    }]
    source["session_events"] = []
    events = normalize_session(source)["events"]
    assert [event["event_type"] for event in events] == ["MOVE_ACTION_RESOLVED", "LOCATION_CHANGE"]
    assert events[1]["cause_adjudication_id"] == "adj-new-move"
    assert events[1].get("dice") is None
