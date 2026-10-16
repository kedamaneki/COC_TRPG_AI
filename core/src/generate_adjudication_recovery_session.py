"""Create a deterministic, offline acceptance session for evidence contracts.

This is not a replacement for a long autonomous playthrough.  It exercises the
same Unified/Session logging contracts with fixed rolls so regressions are
repeatable and no external API is required.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation-v2" / "corbitt_adjudication_fix_001"


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def event(event_id, event_type, adjudication_id, **fields):
    base = {
        "event_id": event_id,
        "turn_id": fields.pop("turn_id", 1),
        "event_type": event_type,
        "transaction_id": fields.pop("transaction_id", "txn_acceptance"),
        "adjudication_id": adjudication_id,
        "interaction_id": fields.pop("interaction_id", ""),
        "actor": fields.pop("actor", "pc_01"),
        "target": fields.pop("target", ""),
        "location": fields.pop("location", "corbitt_basement"),
        "resolution_mode": fields.pop("resolution_mode", "NO_ROLL"),
        "skill_or_stat": fields.pop("skill_or_stat", ""),
        "target_value": fields.pop("target_value", None),
        "roll": fields.pop("roll", None),
        "raw_result": fields.pop("raw_result", None),
        "modifier": fields.pop("modifier", None),
        "final_result": fields.pop("final_result", None),
        "state_before": fields.pop("state_before", {}),
        "state_after": fields.pop("state_after", {}),
        "cause_event_ids": fields.pop("cause_event_ids", []),
        "result_event_ids": fields.pop("result_event_ids", []),
    }
    base.update(fields)
    return base


def main():
    unified = []
    unified.append(event(
        "wall_action", "ACTION_DECLARATION", "adj_wall_001", turn_id=1,
        transaction_id="txn_wall_001", target="basement_planks",
        selected_action="break", resolution_mode="NO_ROLL",
        result_event_ids=["wall_roll"],
    ))
    unified.append(event(
        "wall_roll", "INVESTIGATION_ROLLED", "adj_wall_001", turn_id=2,
        transaction_id="txn_wall_001", target="basement_planks",
        resolution_mode="ROLL", skill_or_stat="STR", skill="STR",
        target_value=50, roll=42, result_level=2,
        raw_result="REGULAR_SUCCESS", final_result="REGULAR_SUCCESS",
        state_before={"basement_planks_broken": False},
        state_after={"basement_planks_broken": True},
        cause_event_ids=["wall_action"], result_event_ids=["wall_world"],
    ))
    unified.append(event(
        "wall_world", "WORLD_EVENT", "adj_wall_001", turn_id=3,
        transaction_id="txn_wall_001", target="basement_planks",
        resolution_mode="NO_ROLL", final_result="REGULAR_SUCCESS",
        state_before={"basement_planks_broken": False},
        state_after={"basement_planks_broken": True},
        cause_event_ids=["wall_roll"],
        world_fact={"event": "BASEMENT_PLANKS_BROKEN"},
        human_readable_description="板を破壊し、奥の部屋への通路を開けた。",
    ))
    unified.append(event(
        "san_roll", "SAN_CHECK", "adj_san_001", turn_id=4,
        transaction_id="txn_knife_001", target="corbitt_knife",
        resolution_mode="ROLL", skill_or_stat="SAN", target_value=70,
        roll=40, result_level=2, raw_result="REGULAR_SUCCESS",
        final_result="REGULAR_SUCCESS",
        san={"before": 70, "target": 70, "roll": 40, "result": "SUCCESS",
             "success_loss_formula": "0", "failure_loss_formula": "1D4",
             "resolved_loss_formula": "0", "loss": 0, "after": 70,
             "trigger_event_id": "knife_encounter"},
    ))
    unified.append(event(
        "luck_roll", "INVESTIGATION_ROLLED", "adj_luck_001", turn_id=5,
        transaction_id="txn_luck_001", target="corbitt_knife",
        resolution_mode="ROLL", skill_or_stat="目星", skill="目星",
        target_value=50, roll=59, result_level=1, raw_result="FAILURE",
        modifier={"type": "LUCK_SPEND", "amount": 9,
                  "resource_before": 50, "resource_after": 41},
        final_result="REGULAR_SUCCESS",
    ))
    unified.append(event(
        "knife_encounter", "WORLD_EVENT", "adj_knife_trigger", turn_id=6,
        transaction_id="txn_knife_001", target="corbitt_knife",
        world_fact={"event": "CORBITT_DAGGER_ANIMATED"},
        human_readable_description="ナイフが宙に浮き、探索者へ襲いかかった。",
        result_event_ids=["knife_combat_start"],
    ))
    combat_id = "combat_knife_001"
    unified.append(event(
        "knife_combat_start", "COMBAT_STARTED", "adj_knife_start", turn_id=7,
        transaction_id="txn_knife_start", target="corbitt_floating_dagger",
        combat_id=combat_id, combat_goal="ENEMY_DEFEATED",
        participants=["pc_01", "corbitt_floating_dagger"],
        trigger_event_id="knife_encounter",
    ))
    unified.append(event(
        "knife_attack_selected", "COMBAT_ACTION_SELECTED", "adj_knife_attack", turn_id=8,
        transaction_id="txn_knife_attack", target="corbitt_floating_dagger",
        combat_id=combat_id, selected_action="attack", action_category="ATTACK",
        skill="近接戦闘", resolution_mode="NO_ROLL",
        result_event_ids=["knife_attack_resolved"],
    ))
    unified.append(event(
        "knife_attack_resolved", "COMBAT_ACTION_RESOLVED", "adj_knife_attack", turn_id=9,
        transaction_id="txn_knife_attack", target="corbitt_floating_dagger",
        combat_id=combat_id, selected_action="attack", action_category="ATTACK",
        skill="近接戦闘", resolution_mode="ROLL", target_value=55, roll=18,
        raw_result="HARD_SUCCESS", final_result="HIT",
        defense_type="dodge", defense_target_value=35, defense_roll=72,
        damage_formula="1D3", damage_roll="1D3=2", actual_damage=2, damage=2,
        HP_before=1, HP_after=0, cause_event_ids=["knife_attack_selected"],
        result_event_ids=["knife_incapacitated"],
    ))
    unified.append(event(
        "knife_incapacitated", "COMBATANT_INCAPACITATED", "adj_knife_attack", turn_id=10,
        transaction_id="txn_knife_attack", actor="corbitt_floating_dagger",
        target="pc_01", combat_id=combat_id, HP_before=1, HP_after=0,
        cause_event_ids=["knife_attack_resolved"], result_event_ids=["knife_combat_end"],
    ))
    unified.append(event(
        "knife_combat_end", "COMBAT_ENDED", "adj_knife_attack", turn_id=11,
        transaction_id="txn_knife_attack", actor="system", target="corbitt_floating_dagger",
        combat_id=combat_id, combat_end_condition="enemies_incapacitated",
        cause_event_ids=["knife_incapacitated"],
    ))
    unified.append(event(
        "final_special", "COMBAT_ACTION_RESOLVED", "adj_final_001", turn_id=12,
        transaction_id="txn_final_001", target="corbitt_body",
        location="corbitt_basement_room3", combat_id="combat_final_001",
        selected_action="break", action_category="SPECIAL",
        resolution_mode="NO_ROLL", final_result="SPECIAL_OBJECTIVE_COMPLETED",
        state_before={"corbitt_defeated": False}, state_after={"corbitt_defeated": True},
        world_fact={"event": "CORBITT_BODY_DESTROYED"},
        human_readable_description="コービットの遺体が破壊され、屋敷の呪いが解けた。",
    ))

    session = [
        {"channel": "IC", "location": "corbitt_basement", "secret_to": None,
         "text": "システム: 【STR対抗】判定に成功。板を破壊し、奥の部屋への通路を開けた。",
         "meta": {"event_id": "session_wall", "transaction_id": "txn_wall_001",
                  "adjudication_id": "adj_wall_001", "actor_id": "pc_01",
                  "action_id": "break", "target": "basement_planks", "roll_type": "opposed_str",
                  "resolution_mode": "ROLL", "skill_or_stat": "STR", "target_value": 50,
                  "roll": 42, "raw_result": "REGULAR_SUCCESS", "final_result": "REGULAR_SUCCESS",
                  "state_before": {"basement_planks_broken": False},
                  "state_after": {"basement_planks_broken": True}}},
        {"channel": "IC", "location": "corbitt_basement", "secret_to": None,
         "text": "システム: 【SANチェック】1d100 ＞ 40 ＞ 成功（現在値:70）。正気度が 0 減少した。",
         "meta": {"event_id": "session_san", "transaction_id": "txn_knife_001",
                  "adjudication_id": "adj_san_001", "actor_id": "pc_01", "roll_type": "san",
                  "san": unified[3]["san"], "resolution_mode": "ROLL", "skill_or_stat": "SAN",
                  "target_value": 70, "roll": 40, "raw_result": "REGULAR_SUCCESS",
                  "final_result": "REGULAR_SUCCESS"}},
        {"channel": "IC", "location": "corbitt_basement", "secret_to": None,
         "text": "システム: 目星50、出目59で失敗。幸運を9消費し、レギュラー成功へ変更（幸運50→41）。",
         "meta": {"event_id": "session_luck", "transaction_id": "txn_luck_001",
                  "adjudication_id": "adj_luck_001", "actor_id": "pc_01", "roll_type": "skill",
                  "skill_or_stat": "目星", "target_value": 50, "roll": 59,
                  "raw_result": "FAILURE", "final_result": "REGULAR_SUCCESS",
                  "modifier": unified[4]["modifier"]}},
        {"channel": "IC", "location": "corbitt_basement", "secret_to": None,
         "text": "システム: ナイフを無力化し、戦闘が終了した。",
         "meta": {"event_id": "session_knife_end", "transaction_id": "txn_knife_attack",
                  "adjudication_id": "adj_knife_attack", "actor_id": "pc_01",
                  "action_id": "attack", "target": "corbitt_floating_dagger", "roll_type": "combat"}},
    ]

    dump(OUT / "unified-event-log.json", unified)
    dump(OUT / "session-log.json", session)
    dump(OUT / "result.json", {
        "session_id": "corbitt_adjudication_fix_001", "scenario_file": "scenario_corbitt.json",
        "seed": 20261012, "completed": True, "phase": "acceptance_contract",
        "turns": len(session), "cycles": len(unified), "offline_deterministic": True,
    })
    runtime = OUT / "checkpoints" / "cycle_0001" / "runtime_data"
    (runtime / "datasets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "src" / "pcs.json", runtime / "pcs.json")
    shutil.copy2(ROOT / "src" / "npcs.json", runtime / "npcs.json")
    shutil.copy2(ROOT / "src" / "scenario_corbitt.json", runtime / "datasets" / "scenario_corbitt.json")
    print(OUT)


if __name__ == "__main__":
    main()
