"""Night Guard production-path NDM wiring smoke (non-V16 session).

Proves causal bind on real imports used by evaluation / Night Guard — not fixture-only.
Does NOT launch CORBITT_LONGRUN_ITERATION3_V16_HOME_001.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE_SRC = REPO / "core" / "src"
sys.path.insert(0, str(CORE_SRC))

SMOKE_SESSION = "CORBITT_NDM_WIRING_SMOKE_V16PRE_001"


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    out = Path(argv[0] if argv else REPO.parent / "evaluation-control" / SMOKE_SESSION)
    out.mkdir(parents=True, exist_ok=True)

    os.environ["NATURAL_DECISION_REQUIRED"] = "true"

    from CombatTerminationContract import run_full_corbitt_termination_chain
    from ndm_integration import enrich_pc_action_with_ndm, ensure_ndm_runtime, guard_executor_commit
    from reasoning.runtime import DECISION_SOURCE_NDM, get_active_runtime

    state = {
        "flags": {},
        "current_loc": "corbitt_basement",
        "director_v2": {
            "goal": {
                "candidate_next_actions": [
                    {"action": "search", "target": "wall_planks", "reason": "examine planks"},
                    {"action": "move", "target": "corbitt_ground_floor", "reason": "seek tool", "leave_reason": "seek_better_tool"},
                ]
            },
            "stall": {"recent_actions": []},
        },
        "ndm_runtime": {},
        "ndm_event_log": [],
    }

    rt = ensure_ndm_runtime(state, required=True, enabled=True, implementation_commit="smoke")
    assert rt.active
    assert state["director_v2"]["NATURAL_DECISION_RUNTIME_ACTIVE"] is True
    assert state["director_v2"]["s_level_authority"] == DECISION_SOURCE_NDM
    assert state["director_v2"]["legacy_stall_detector_primary"] is False

    # Init-failure fail-closed probe (separate object)
    from reasoning.runtime import NaturalDecisionRuntime, NDMInitFailure
    try:
        bad = NaturalDecisionRuntime()
        bad.bootstrap({"director_v2": {}}, enabled=False, required=True)
        init_fail_open = 1
    except NDMInitFailure:
        init_fail_open = 0

    selected = enrich_pc_action_with_ndm(
        state,
        {"action": "search", "target": "wall_planks", "reason": "party wants to check planks"},
        actor_id="pc_01",
    )
    guard_executor_commit(selected, state)
    assert selected.get("decision_source") == DECISION_SOURCE_NDM
    assert selected.get("reasoning_id")
    assert selected.get("candidate_set_id")
    assert selected.get("decision_transaction_id")

    # Second commit keeps coverage
    selected2 = enrich_pc_action_with_ndm(
        state,
        {"action": "move", "target": "corbitt_ground_floor", "reason": "get crowbar", "leave_reason": "seek_better_tool"},
        actor_id="pc_01",
    )
    guard_executor_commit(selected2, state)

    # Combat chain on production module
    combat_state = {"flags": {}, "combat_termination_chain": {}}
    evidence = run_full_corbitt_termination_chain(
        combat_state, validated_kill_route_id="ROUTE_A_HP0", source_rule_id="smoke_src",
    )

    metrics = rt.metrics_snapshot()
    rates = metrics["rates"]
    report = {
        "session_id": SMOKE_SESSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "PRODUCTION_SMOKE": "PASS",
        "NATURAL_DECISION_RUNTIME_ACTIVE": True,
        "PL_REASONING_EVENT_COUNT": rt.telemetry.pl_reasoning_event_count,
        "KP_PROGRESS_ASSESSMENT_COUNT": rt.telemetry.kp_progress_assessment_count,
        "SELECTED_ACTION_WITH_NDM_REASONING_COUNT": rt.telemetry.selected_action_with_ndm_reasoning_count,
        "SELECTED_ACTION_REASONING_ID_MISSING": rt.telemetry.selected_action_reasoning_id_missing,
        "SELECTED_ACTION_DECISION_SOURCE": selected.get("decision_source"),
        "S_LEVEL_AUTHORITY": rt.telemetry.s_level_authority,
        "LEGACY_STALL_DETECTOR_PRIMARY": rt.telemetry.legacy_stall_detector_primary,
        "LEGACY_DECISION_COMMIT_COUNT": rt.telemetry.LEGACY_DECISION_COMMIT_COUNT,
        "NDM_DECISION_CAUSAL_COVERAGE": rates["NDM_DECISION_CAUSAL_COVERAGE"],
        "NDM_INIT_FAIL_OPEN_PATH": init_fail_open,
        "causal_sample": {
            "reasoning_id": selected.get("reasoning_id"),
            "candidate_set_id": selected.get("candidate_set_id"),
            "selected_candidate_id": selected.get("selected_candidate_id"),
            "decision_transaction_id": selected.get("decision_transaction_id"),
            "action": selected.get("action"),
            "target": selected.get("target"),
        },
        "rates": rates,
        "combat_chain": evidence.to_dict(),
        "gates": {
            "NATURAL_DECISION_RUNTIME_ACTIVE_TEST": "PASS",
            "NDM_CAUSAL_ACTION_BINDING": "PASS",
            "LEGACY_DECISION_COMMIT_COUNT_0": rt.telemetry.LEGACY_DECISION_COMMIT_COUNT == 0,
            "ONE_S_LEVEL_AUTHORITY": rt.telemetry.s_level_authority == DECISION_SOURCE_NDM,
            "FULL_TERMINATION_CHAIN": bool(evidence.termination_contract_validated),
            "TELEMETRY_RATES_NUMERIC": all(
                isinstance(rates[k], float)
                for k in (
                    "UNEXPLAINED_ACTION_RATE",
                    "UNRESOLVED_LEAD_ABANDON_RATE",
                    "SELF_RECOVERY_RATE",
                    "MEANINGFUL_PROGRESS_RATE",
                )
            ),
        },
    }
    hard = (
        report["PL_REASONING_EVENT_COUNT"] > 0
        and report["KP_PROGRESS_ASSESSMENT_COUNT"] > 0
        and report["SELECTED_ACTION_WITH_NDM_REASONING_COUNT"] > 0
        and report["SELECTED_ACTION_REASONING_ID_MISSING"] == 0
        and report["LEGACY_DECISION_COMMIT_COUNT"] == 0
        and report["S_LEVEL_AUTHORITY"] == DECISION_SOURCE_NDM
        and report["LEGACY_STALL_DETECTOR_PRIMARY"] is False
        and report["NDM_INIT_FAIL_OPEN_PATH"] == 0
        and report["NDM_DECISION_CAUSAL_COVERAGE"] >= 1.0
        and all(report["gates"].values())
    )
    report["PRODUCTION_SMOKE"] = "PASS" if hard else "FAIL"
    (out / "V16_PRODUCTION_SMOKE_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if hard else 2


if __name__ == "__main__":
    raise SystemExit(main())
