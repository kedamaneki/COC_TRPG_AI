"""Deterministic Iteration 2 acceptance fixture. No LLM or external API calls."""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
VIDEO_ROOT = HERE.parents[1]
CORE = Path(r"F:\制作物\その3\src")
OUT = Path(r"F:\制作物\その3\evaluation-v2\corbitt_iteration2_deterministic_001")
sys.path.insert(0, str(VIDEO_ROOT / "src"))
sys.path.insert(0, str(CORE))

from ScenarioManager import ScenarioManager
from DiceEngine import DiceEngine
from ObjectLifecycle import apply_object_transition
from video_agent.normalizer import normalize_session


def scenario(location):
    data = json.loads((CORE / "scenario_corbitt.json").read_text(encoding="utf-8"))
    manager = ScenarioManager(data)
    manager.location = location
    manager.current_phase = "investigation"
    return manager


def normalize_fixture():
    source = {
        "root": "iteration2_fixture", "source_files": [],
        "result": {"session_id": "corbitt_iteration2_deterministic_001", "scenario_file": "scenario_corbitt.json"},
        "scenarios": [{"scenario_meta": {"title": "悪霊の家"}, "locations": {}}],
        "pcs": {"pc_01": {"profile": {"name": "探索者"}}}, "npcs": {},
        "unified_events": [
            {"event_id": "roll_numeric", "event_type": "INVESTIGATION_ROLLED", "adjudication_id": "adj_roll",
             "actor": "pc_01", "resolution_mode": "ROLL", "target_value": 50, "roll": 20,
             "result_level": 3, "raw_result": 3, "final_result": 3},
            {"event_id": "roll_text", "event_type": "SKILL_CHECK", "adjudication_id": "adj_roll",
             "actor": "pc_01", "resolution_mode": "ROLL", "target_value": 50, "roll": 20,
             "result_level": "ハード成功", "raw_result": "HARD_SUCCESS", "final_result": "ハード成功"},
            {"event_id": "luck_pre", "event_type": "INVESTIGATION_ROLLED", "adjudication_id": "adj_luck",
             "actor": "pc_01", "resolution_mode": "ROLL", "target_value": 50, "roll": 59,
             "raw_result": "FAILURE", "final_result": "FAILURE"},
            {"event_id": "luck_post", "event_type": "SKILL_CHECK", "adjudication_id": "adj_luck",
             "actor": "pc_01", "resolution_mode": "ROLL", "target_value": 50, "roll": 59,
             "raw_result": "FAILURE", "final_result": "REGULAR_SUCCESS",
             "modifier": {"type": "LUCK_SPEND", "amount": 9}},
            {"event_id": "combat_snapshot", "event_type": "COMBAT_ACTION_RESOLVED", "adjudication_id": "adj_combat",
             "actor": "pc_01", "combat_id": "combat_1", "SAN_before": 70, "SAN_after": 70},
            {"event_id": "san_result", "event_type": "SAN_RESULT", "adjudication_id": "adj_san",
             "actor": "pc_01", "san": {"kind": "ADJUDICATION", "before": 70, "target": 70,
             "roll": 40, "result": "SUCCESS", "loss": 0, "after": 70}},
        ],
        "session_events": [],
    }
    return normalize_session(source)


def main():
    checks = {}
    door = scenario("corbitt_ground_floor")
    door.flags["basement_door_examined"] = False
    door_result = door.process_action("inspect", "basement_door", 2)
    checks["door_examine_consistent"] = "まだ閉ざされている" in door_result["system_log"] and not door.flags.get("basement_door_unlocked", False)

    wall = scenario("corbitt_basement")
    wall.flags.update({"basement_planks_examined": False, "basement_planks_broken": False})
    wall_result = wall.process_action("inspect", "basement_planks", 2)
    checks["wall_examine_consistent"] = "壊す必要" in wall_result["system_log"] and not wall.flags["basement_planks_broken"]

    living = scenario("corbitt_ground_floor")
    living.flags["living_room_investigated"] = False
    san_request = living.process_action("inspect", "living_room_clutter", 3)
    checks["mandatory_san_dispatched"] = san_request["san_check"].get("required") is True and san_request["san_check"].get("value", "").upper() == "0/1D3"

    opposed = DiceEngine().execute_opposed_str_roll("PC", 60, "板", 50)
    checks["opposed_roll_complete"] = all(
        opposed["opposed_roll"][side].get(key) is not None
        for side in ("actor", "opponent") for key in ("target_value", "roll", "result")
    )

    states = {"corbitt_knife": {"object_id": "corbitt_knife", "status": "UNDISCOVERED", "destroyed": False}}
    apply_object_transition(states, "corbitt_knife", {"status": "IN_COMBAT", "transition_path": ["AVAILABLE", "IN_COMBAT"]})
    apply_object_transition(states, "corbitt_knife", {"status": "ON_FLOOR", "owner_id": None, "available": True})
    checks["knife_lifecycle_valid"] = states["corbitt_knife"]["status"] == "ON_FLOOR" and states["corbitt_knife"]["owner_id"] is None

    final = scenario("corbitt_basement_room2")
    final.flags.update({"corbitt_defeated": False, "corbitt_body_encountered": True, "learned_corbitt_weakness": False})
    final_result = final.process_action("break", "corbitt_body", 2)
    checks["final_narrative_grounded"] = bool(
        "あるいは" not in final_result["system_log"] and final_result.get("resolution_reason")
    )

    normalized = normalize_fixture()
    warnings = normalized["metadata"]["conversion_warnings"]
    combat_snapshot = next(e for e in normalized["events"] if "combat_snapshot" in e["source_event_ids"])
    checks["san_snapshot_excluded"] = combat_snapshot["san"] is None
    checks["normalizer_no_contradiction"] = not any(w.get("code") == "NORMALIZATION_SOURCE_CONTRADICTION" for w in warnings)

    metrics = {
        "NARRATIVE_STATE_CONTRADICTION": 0 if checks["door_examine_consistent"] and checks["wall_examine_consistent"] else 1,
        "ROLL_CONTRACT_INCOMPLETE": 0 if checks["opposed_roll_complete"] else 1,
        "MANDATORY_SAN_EFFECT_DROPPED": 0 if checks["mandatory_san_dispatched"] else 1,
        "SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK": 0 if checks["san_snapshot_excluded"] else 1,
        "NORMALIZATION_SOURCE_CONTRADICTION": sum(1 for w in warnings if w.get("code") == "NORMALIZATION_SOURCE_CONTRADICTION"),
        "OBJECT_STATE_INVALID_TRANSITION": 0 if checks["knife_lifecycle_valid"] else 1,
        "OBJECT_NARRATIVE_STATE_CONTRADICTION": 0 if checks["knife_lifecycle_valid"] else 1,
        "UNGROUNDED_NARRATIVE_OPTION": 0 if checks["final_narrative_grounded"] else 1,
    }
    status = "PASS" if all(v == 0 for v in metrics.values()) and all(checks.values()) else "FAIL"
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"status": status, "checks": checks, "metrics": metrics}
    (OUT / "iteration2_acceptance.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "normalized_fixture.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
