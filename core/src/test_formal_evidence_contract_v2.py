import json

import pytest

import EvaluationCheckpoint as checkpoint
from EventIdentity import append_unified_event, EventIdentityError
from AdjudicationEvidence import (
    EvidenceContractError, no_roll_evidence, roll_evidence, validate_evidence,
)
from CombatProgression import append_combat_event
from InvestigationFlow import append_investigation_event


def test_roll_and_no_roll_known_good_and_bad():
    roll = roll_evidence(
        adjudication_id="adj_r", skill_or_stat="目星", target_value=65,
        roll=32, raw_result="REGULAR_SUCCESS", final_result="REGULAR_SUCCESS",
    )
    no_roll = no_roll_evidence(
        adjudication_id="adj_n", reason="SCENARIO_NO_ROLL", final_outcome="SUCCESS",
    )
    assert validate_evidence(roll) and validate_evidence(no_roll)
    with pytest.raises(EvidenceContractError):
        validate_evidence({"adjudication_id": "bad", "resolution_mode": "ROLL"})
    with pytest.raises(EvidenceContractError):
        validate_evidence({"adjudication_id": "bad", "resolution_mode": "NO_ROLL"})


def test_non_resolution_events_do_not_masquerade_as_no_roll():
    state = {"unified_event_log": []}
    row = append_combat_event(state, "COMBAT_STARTED", resolution_mode="NO_ROLL")
    assert row["resolution_mode"] is None
    ctx = {"investigation_id": "i", "actor_id": "pc", "target_id": "desk", "roll_required": True}
    row = append_investigation_event(state, "INVESTIGATION_DECLARED", ctx)
    assert "resolution_mode" not in row


def test_combat_roll_and_effect_taxonomies_are_separate():
    state = {"unified_event_log": []}
    row = append_combat_event(
        state, "COMBAT_ACTION_RESOLVED", resolution_mode="ROLL",
        adjudication_id="adj_c", actor="pc", target="knife", skill="近接戦闘",
        target_value=55, roll=32, raw_result="REGULAR_SUCCESS",
        final_result="REGULAR_SUCCESS", roll_result="REGULAR_SUCCESS",
        effect_result="HIT_ATTACKER",
    )
    assert row["final_result"] == "REGULAR_SUCCESS"
    assert row["effect_result"] == "HIT_ATTACKER"
    assert row["modifier"] == {"type": "NONE"}


def test_durable_segment_crash_resume_has_full_coverage(tmp_path):
    state = {"session_id": "s", "unified_event_log": []}
    for i in range(1, 5):
        append_unified_event(state, {"event_type": "FIXTURE", "value": i})
    events = state["unified_event_log"]
    checkpoint.write_durable_segment(
        tmp_path, segment_id="segment_001", session_id="s", cycle=1,
        start_event_offset=0, events=events[:2], start_checkpoint_id=None,
        end_checkpoint_id="CHECKPOINT_CYCLE_000001",
    )
    loaded = {
        "manifest": {"session_id": "s", "cycle": 2, "checkpoint_id": "CHECKPOINT_CYCLE_000002"},
        "payload": {"session_state": {"unified_event_log": events}},
    }
    recovered = checkpoint.ensure_checkpoint_segment_coverage(tmp_path, loaded)
    assert recovered is not None
    report = checkpoint.merge_segments(tmp_path, raw_events=events)
    assert report["status"] == "PASS"
    assert report["missing_events"] == 0
    assert report["duplicate_events_removed"] == 0
    assert report["coverage_ratio"] == 1.0
    docs = checkpoint.load_segments(tmp_path)
    assert any(row.get("provenance") == "RECONSTRUCTED_FROM_RAW" for row in docs)


def test_event_identity_exists_before_commit_and_is_preserved(tmp_path):
    state = {"session_id": "identity", "unified_event_log": []}
    row = append_unified_event(state, {"event_type": "CHECK", "value": 1})
    original_id = row["event_id"]
    assert row["raw_event_offset"] == 0
    checkpoint.write_durable_segment(
        tmp_path, segment_id="segment_001", session_id="identity", cycle=1,
        start_event_offset=0, events=state["unified_event_log"],
        start_checkpoint_id=None, end_checkpoint_id="CHECKPOINT_CYCLE_000001",
    )
    segment = checkpoint.load_segments(tmp_path)[0]
    assert segment["events"][0]["event_id"] == original_id
    assert segment["start_event_id"] == original_id == segment["end_event_id"]


def test_segment_rejects_missing_event_id(tmp_path):
    with pytest.raises(EventIdentityError, match="SEGMENT_EVENT_ID_MISSING"):
        checkpoint.write_durable_segment(
            tmp_path, segment_id="segment_001", session_id="bad", cycle=1,
            start_event_offset=0, events=[{"event_type": "BAD"}],
            start_checkpoint_id=None, end_checkpoint_id="CHECKPOINT_CYCLE_000001",
        )


def test_merge_requires_missing_duplicate_unexpected_and_full_coverage(tmp_path):
    state = {"session_id": "coverage", "unified_event_log": []}
    append_unified_event(state, {"event_type": "A"})
    append_unified_event(state, {"event_type": "B"})
    checkpoint.write_durable_segment(
        tmp_path, segment_id="segment_001", session_id="coverage", cycle=1,
        start_event_offset=0, events=state["unified_event_log"],
        start_checkpoint_id=None, end_checkpoint_id="CHECKPOINT_CYCLE_000001",
    )
    report = checkpoint.merge_segments(tmp_path, raw_events=state["unified_event_log"])
    assert report["status"] == "PASS"
    assert report["missing_events"] == 0
    assert report["duplicate_events_removed"] == 0
    assert report["unexpected_events"] == 0
    assert report["coverage_ratio"] == 1.0


@pytest.mark.parametrize("crash_point", [
    "before_segment_write", "during_segment_temp_write", "after_segment_complete",
    "before_checkpoint_complete", "after_checkpoint_complete",
])
def test_crash_timing_variations_only_adopt_complete_segments(tmp_path, crash_point):
    state = {"session_id": "crash", "unified_event_log": []}
    append_unified_event(state, {"event_type": "CYCLE_COMPLETE", "cycle": 1})
    if crash_point == "during_segment_temp_write":
        partial = tmp_path / "segments" / "segment_001_cycle_000001.tmp-crash"
        partial.mkdir(parents=True)
        (partial / "segment.json").write_text("{}", encoding="utf-8")
    elif crash_point not in {"before_segment_write"}:
        checkpoint.write_durable_segment(
            tmp_path, segment_id="segment_001", session_id="crash", cycle=1,
            start_event_offset=0, events=state["unified_event_log"],
            start_checkpoint_id=None, end_checkpoint_id="CHECKPOINT_CYCLE_000001",
        )
        if crash_point == "before_checkpoint_complete":
            incomplete = tmp_path / "checkpoints" / "cycle_000001.tmp-crash"
            incomplete.mkdir(parents=True)
            (incomplete / "state.json").write_text("{}", encoding="utf-8")
        elif crash_point == "after_checkpoint_complete":
            complete = tmp_path / "checkpoints" / "cycle_000001"
            complete.mkdir(parents=True)
            (complete / "COMPLETE").write_text("CHECKPOINT_CYCLE_000001\n", encoding="utf-8")
    report = checkpoint.merge_segments(tmp_path, raw_events=state["unified_event_log"])
    if crash_point in {"before_segment_write", "during_segment_temp_write"}:
        assert report["status"] == "FAILED"
        assert report["missing_events"] == 1
    else:
        assert report["status"] == "PASS"
        assert report["coverage_ratio"] == 1.0

