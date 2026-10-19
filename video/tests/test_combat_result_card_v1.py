from __future__ import annotations

import copy

import pytest

from video_agent.presentation.combat_result_card import (
    CombatResultCardError,
    assert_combat_result_card,
    audit_combat_result_card,
    build_no_roll_special_objective_card,
)


@pytest.fixture
def source_events() -> list[dict]:
    return [
        {"raw_event_offset": 275, "event_id": "selected", "event_type": "COMBAT_ACTION_SELECTED",
         "selected_action": "break", "target": "corbitt_body"},
        {"raw_event_offset": 277, "event_id": "resolved", "event_type": "COMBAT_ACTION_RESOLVED",
         "resolution_mode": "NO_ROLL", "objective_outcome": "SPECIAL_OBJECTIVE_COMPLETED"},
        {"raw_event_offset": 278, "event_id": "objective", "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
         "world_fact": {"fact": "CORBITT_BODY_DESTROYED"}},
        {"raw_event_offset": 279, "event_id": "ending", "event_type": "COMBAT_ENDING"},
        {"raw_event_offset": 280, "event_id": "ended", "event_type": "COMBAT_ENDED",
         "combat_state": "ENDED"},
    ]


def test_no_roll_special_objective_card_is_source_bound(source_events: list[dict]) -> None:
    card = build_no_roll_special_objective_card(source_events)
    audit = assert_combat_result_card(card, source_events)
    assert audit.status == "PASS"
    assert [stage["label"] for stage in card["stages"]] == ["遺体を破壊", "コービットを打倒", "戦闘終了"]
    assert card["scene_actor_transition"]["fade_out_after_raw_event_offset"] == 278


@pytest.mark.parametrize("field", ["attack_roll", "damage_roll", "hp_change", "enemy_attack"])
def test_invented_combat_fact_fails(field: str, source_events: list[dict]) -> None:
    card = build_no_roll_special_objective_card(source_events)
    card[field] = 1
    assert audit_combat_result_card(card, source_events).status == "FAIL"
    with pytest.raises(CombatResultCardError, match="COMBAT_RESULT_CARD_AUDIT_FAILED"):
        assert_combat_result_card(card, source_events)


def test_missing_causal_event_fails(source_events: list[dict]) -> None:
    incomplete = [row for row in source_events if row["event_type"] != "COMBAT_ENDING"]
    with pytest.raises(CombatResultCardError, match="SPECIAL_OBJECTIVE_CHAIN_INCOMPLETE"):
        build_no_roll_special_objective_card(incomplete)


def test_card_causal_order_fails_closed(source_events: list[dict]) -> None:
    card = build_no_roll_special_objective_card(source_events)
    broken = copy.deepcopy(card)
    broken["source_raw_event_offsets"] = list(reversed(broken["source_raw_event_offsets"]))
    assert audit_combat_result_card(broken, source_events).causal_order_mismatch == 1
