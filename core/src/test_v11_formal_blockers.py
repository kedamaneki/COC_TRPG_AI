import pytest

import main
from AdjudicationEvidence import EvidenceContractError
from CombatProgression import append_combat_event
from ProgressDirectorV2 import record_unified_turn


def complete_roll(**overrides):
    row = {
        "adjudication_id": "adj_v11",
        "resolution_mode": "ROLL",
        "skill_or_stat": "目星",
        "target_value": 65,
        "roll": 60,
        "raw_result": "REGULAR_SUCCESS",
        "final_result": "REGULAR_SUCCESS",
        "modifier": {"type": "NONE"},
        "actor_id": "pc_01",
        "target_id": "corbitt_body",
    }
    row.update(overrides)
    return row


class ScenarioStub:
    def __init__(self):
        self.location = "room"
        self.flags = {}
        self.current_phase = "investigation"
        self.scenario_data = {"locations": {"room": {"exits": {}}}}
        self.event_triggers = []
        self.stagnation_counter = 0

    def process_action(self, action_id, target, success_level):
        return {"system_log": "判定結果を確定した。", "san_check": {"required": False}}

    def get_available_exits(self, location):
        return []

    def reset_stagnation_counter(self):
        self.stagnation_counter = 0


def test_session_roll_contract_requires_actor_target_and_full_tuple():
    logs = []
    with pytest.raises(EvidenceContractError, match="requires authoritative"):
        main.append_system_log_entry(
            logs, "room", "【技能:目星】CC(1d100<=65) ＞ 出目:60 ＞ 成功",
            action_id="search", target="desk", roll_type="skill", actor_id="pc_01",
        )
    with pytest.raises(EvidenceContractError, match="actor_id, target"):
        main.append_system_log_entry(
            logs, "room", "判定", action_id="search", roll_type="skill",
            adjudication=complete_roll(actor_id="", target_id=""),
        )
    main.append_system_log_entry(
        logs, "room", "判定", action_id="search", target="desk",
        roll_type="skill", actor_id="pc_01", adjudication=complete_roll(),
    )
    meta = logs[0]["meta"]
    for field in (
        "adjudication_id", "actor_id", "target", "skill_or_stat",
        "target_value", "roll", "raw_result", "final_result",
    ):
        assert meta.get(field) not in (None, "")


def test_push_decline_preserves_original_roll_evidence():
    pending = {
        "target": "desk", "target_id": "desk", "skill_name": "目星",
        "original_action": "search", "failed_success_level": 1,
        **complete_roll(
            adjudication_id="adj_push_decline", target_value=50, roll=65,
            raw_result="FAILURE", final_result="FAILURE", target_id="desk",
        ),
    }
    result = main.resolve_push_decline(
        "pc_01", "探索者", pending, "room", ScenarioStub(), "失敗ログ",
    )
    assert result["adjudication_id"] == "adj_push_decline"
    assert result["roll"] == 65
    assert result["target_value"] == 50
    assert result["raw_result"] == "FAILURE"
    assert result["actor_id"] == "pc_01"
    assert result["target_id"] == "desk"


def test_combat_lifecycle_is_pure_and_only_keeps_cause_relation():
    state = {"unified_event_log": []}
    with pytest.raises(ValueError, match="contains resolution fields"):
        append_combat_event(
            state, "COMBAT_ENDED", resolution_mode="NO_ROLL",
            adjudication_id="adj_bad",
        )
    row = append_combat_event(
        state, "COMBAT_ENDED", cause_adjudication_id="adj_source",
        combat_end_condition="scenario_condition",
    )
    assert row["adjudication_id"] == ""
    assert row["cause_adjudication_id"] == "adj_source"
    assert row["resolution_mode"] is None
    assert row["roll"] is None


def test_combined_roll_and_combat_display_are_split_before_session_commit():
    state = {"all_events_log": [], "pl_id": "pc_01"}
    result = {
        **complete_roll(),
        "log": "【技能:目星】判定成功\n【戦闘開始】行動順: 探索者 → 敵",
        "action_id": "search",
        "target": "corbitt_body",
        "roll_type": "skill",
    }
    result["adjudication"] = complete_roll()
    main._append_result_log_with_knowledge(
        state, result, current_loc="room", char_mgr=None, pl_id="pc_01",
        action_id="search", target="corbitt_body", roll_type="skill",
    )
    assert len(state["all_events_log"]) == 2
    adjudication_meta = state["all_events_log"][0]["meta"]
    lifecycle_meta = state["all_events_log"][1]["meta"]
    assert adjudication_meta["resolution_mode"] == "ROLL"
    assert "戦闘開始" not in state["all_events_log"][0]["text"]
    assert lifecycle_meta["roll_type"] == "combat_lifecycle"
    assert lifecycle_meta["cause_adjudication_id"] == "adj_v11"
    assert "resolution_mode" not in lifecycle_meta


def test_turn_summary_uses_authoritative_canonical_roll_identifier():
    scenario = ScenarioStub()
    state = {"current_loc": "room", "pl_id": "pc_01"}
    evidence = complete_roll(
        adjudication_id="adj_identifier", skill_or_stat="STR",
        target_value=55, roll=38,
    )
    event = record_unified_turn(
        state, scenario,
        action={
            "action": "search", "target": "wall_planks", "pc_id": "pc_01",
            "skill": "目星", "transaction_id": "txn_identifier",
        },
        result={
            "status": 2,
            "dice": {"target_value": 55, "roll": 38},
            "adjudication": evidence,
        },
    )
    assert event["skill"] == "STR"
    assert event["canonical_identifier"] == "STR"
    assert event["requested_roll_identifier"] == "目星"
    assert event["skill_or_stat"] == "STR"
