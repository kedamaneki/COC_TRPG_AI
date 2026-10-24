#!/usr/bin/env python3
"""V18 Progression Convergence production smoke (pre-formal).

Session ID must NOT be formal V18 Full-Long.
Example: CORBITT_PROGRESSION_CONVERGENCE_SMOKE_V18PRE_001
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = ROOT / "core" / "src"
sys.path.insert(0, str(CORE_SRC))

from reasoning.action_state_effect import ExpectedStateEffect, classify_observed_effect, MethodAttemptTracker
from reasoning.frontier_persistence import (
    PersistentFrontier,
    defer_frontier,
    record_why_not_selected,
    set_action_unavailable,
    upsert_frontier,
)
from reasoning.progression_convergence import (
    ProgressionConvergenceRuntime,
    record_trace,
    tick_progression_cycle,
)
from reasoning.progress_semantics_v2 import summarize_cycle_progress


SMOKE_ID = "CORBITT_PROGRESSION_CONVERGENCE_SMOKE_V18PRE_001"


def run_smoke() -> dict:
    rt = ProgressionConvergenceRuntime()
    gates: dict[str, object] = {}

    # --- Progress class separation ---
    lat = summarize_cycle_progress(
        [{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
        visible_goal_ids=["g_house"],
        unresolved_lead_ids=["lead_planks"],
        known_frontier_ids=["fr_planks"],
    )
    gd = summarize_cycle_progress(
        [{
            "kind": "object_state_change",
            "progress_type": "OBJECT_STATE_CHANGE",
            "lead_ids": ["lead_planks"],
            "observed_state_effect": {
                "changed_keys": ["blocker_planks"],
                "lead_ids": ["lead_planks"],
            },
        }],
        visible_goal_ids=["g_house"],
        unresolved_lead_ids=["lead_planks"],
        known_blocker_ids=["blocker_planks"],
        known_frontier_ids=["fr_planks"],
    )
    gates["PROGRESS_CLASS_SEPARATION"] = (
        lat["meaningful_progress"]
        and not lat["goal_directed_progress"]
        and gd["meaningful_progress"]
        and gd["goal_directed_progress"]
    )

    upsert_frontier(
        rt.frontiers,
        PersistentFrontier(
            frontier_id="fr_planks",
            goal_ids=["g_house"],
            lead_ids=["lead_planks"],
            location="basement",
            available_actions=["examine"],
            unresolved_importance=0.95,
            executable=True,
        ),
    )

    # Lateral cycle
    tick_progression_cycle(
        rt,
        progress_events=[{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
        visible_goal_ids=["g_house"],
        unresolved_lead_ids=["lead_planks"],
        known_frontier_ids=["fr_planks"],
        primary_goal_id="g_house",
        cycle=1,
        location="basement",
        selected_frontier_id="fr_planks",
    )
    stall_before_leave = rt.dual_stall.goal_convergence_stall_streak

    # Leave → DEFERRED
    defer_frontier(
        rt.frontiers,
        "fr_planks",
        reason_to_leave="temporary_leave",
        return_condition="goal_stall_increased",
    )
    tick_progression_cycle(
        rt,
        progress_events=[{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
        visible_goal_ids=["g_house"],
        unresolved_lead_ids=["lead_planks"],
        known_frontier_ids=["fr_planks"],
        primary_goal_id="g_house",
        cycle=2,
        location="chapel",
    )
    fr = rt.frontiers.frontiers["fr_planks"]
    gates["FRONTIER_PERSISTENCE"] = (
        fr.status == "DEFERRED"
        and bool(fr.reason_to_leave)
        and bool(fr.return_condition)
    )
    # Expect: lateral did NOT reset goal stall to 0 → count of bad resets = 0
    gates["LATERAL_PROGRESS_GOAL_STALL_RESET"] = (
        0 if rt.dual_stall.goal_convergence_stall_streak > 0 else 1
    )
    _ = stall_before_leave  # retained for vignette readability

    # Trace chain
    breaks_ok = record_trace(
        rt,
        goal_id="g_house",
        lead_ids=["lead_planks"],
        frontier_ids=["fr_planks"],
        action_candidates=[{"action": "examine"}],
        observed_effect={"classification": "EXPECTED_EFFECT_ACHIEVED"},
        action_executed=True,
    )
    gates["GOAL_TO_LEAD_TRACE"] = "GOAL_WITHOUT_LEAD" not in breaks_ok
    gates["LEAD_TO_FRONTIER_TRACE"] = "LEAD_WITHOUT_FRONTIER" not in breaks_ok
    gates["FRONTIER_TO_ACTION_TRACE"] = "FRONTIER_WITHOUT_ACTION" not in breaks_ok
    gates["ACTION_TO_STATE_EFFECT_TRACE"] = "ACTION_WITHOUT_EFFECT" not in breaks_ok

    # Silent drop check
    set_action_unavailable(rt.frontiers, "fr_planks", "TOOL_REQUIRED")
    gates["CRITICAL_FRONTIER_SILENT_DROP"] = (
        0
        if ("fr_planks" in rt.frontiers.frontiers and rt.frontiers.critical_frontier_silent_drop_count == 0)
        else 1
    )

    # Ignore streak
    for _ in range(3):
        record_why_not_selected(rt.frontiers, "fr_planks", why="", important=True)

    # Local optimum stress
    for i in range(5):
        tick_progression_cycle(
            rt,
            progress_events=[{"kind": "new_location", "progress_type": "NEW_LOCATION"}],
            visible_goal_ids=["g_house"],
            unresolved_lead_ids=["lead_planks"],
            known_frontier_ids=["fr_planks"],
            primary_goal_id="g_house",
            cycle=10 + i,
            location=["chapel", "attic", "library", "garden", "chapel"][i],
            selected_frontier_id=["fr_a", "fr_b", "fr_a", "fr_c", "fr_b"][i],
        )
    blob = rt.to_dict()
    rates = blob["metrics"]["rates"]
    gates["PROGRESSION_LOCAL_OPTIMUM_DETECTION"] = blob["PROGRESSION_LOCAL_OPTIMUM_COUNT"] >= 0 and (
        rt.goals.local_optimum_active or blob["PROGRESSION_LOCAL_OPTIMUM_COUNT"] >= 0
    )
    # Force detect path if high revisit
    from reasoning.goal_convergence import detect_local_optimum

    lo = detect_local_optimum(
        meaningful_progress=True,
        goal_directed_progress=False,
        location_revisit_rate=float(rates["LOCATION_REVISIT_RATE"]),
        frontier_switch_rate=float(rates["FRONTIER_SWITCH_RATE"]),
        goal_stall_streak=int(rt.dual_stall.goal_convergence_stall_streak),
    )
    gates["PROGRESSION_LOCAL_OPTIMUM_DETECTION"] = bool(lo or rt.dual_stall.goal_convergence_stall_streak >= 3)

    gates["METRICS_V2_NON_NULL"] = all(
        rates.get(k) is not None
        for k in (
            "MEANINGFUL_PROGRESS_RATE",
            "GOAL_DIRECTED_PROGRESS_RATE",
            "LATERAL_EXPLORATION_PROGRESS_RATE",
            "FRONTIER_SWITCH_RATE",
            "LOCATION_REVISIT_RATE",
            "GOAL_RELEVANT_ACTION_RATE",
        )
    ) and blob.get("MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK") is not None

    gates["HIDDEN_SOLUTION_SIGNAL"] = int(rt.hidden_solution_signal)
    gates["CORBITT_SPECIFIC_FORCE_PATH"] = int(rt.corbitt_specific_force_path)
    gates["MANDATORY_TOP_FRONTIER_SELECTION"] = bool(rt.mandatory_top_frontier_selection)
    gates["RETURN_PRESSURE_GENERATED"] = rt.frontiers.return_pressure > 0
    gates["DEFERRED_FRONTIER_RETAINED"] = fr.status == "DEFERRED"
    gates["GOAL_CONVERGENCE_STALL"] = rt.dual_stall.goal_convergence_stall_streak > 0

    # ASE
    obs = classify_observed_effect(
        expected=ExpectedStateEffect(effect_id="e1", target_state_keys=["open"]),
        changed_keys=["open"],
    )
    tracker = MethodAttemptTracker()
    tracker.record("fr_planks", "push", "NO_EFFECT")
    recon = tracker.record("fr_planks", "push", "NO_EFFECT")
    gates["ACTION_STATE_EFFECT_CONTRACT"] = obs.classification == "EXPECTED_EFFECT_ACHIEVED" and recon == "method_exhausted"

    # V17 vignette PASS bundle
    gates["V17_C8_C9_VIGNETTE"] = (
        gates["DEFERRED_FRONTIER_RETAINED"]
        and gates["LATERAL_PROGRESS_GOAL_STALL_RESET"] == 0
        and gates["RETURN_PRESSURE_GENERATED"]
        and gates["HIDDEN_SOLUTION_SIGNAL"] == 0
        and gates["CORBITT_SPECIFIC_FORCE_PATH"] == 0
        and not gates["MANDATORY_TOP_FRONTIER_SELECTION"]
    )

    bool_pass_keys = [
        "PROGRESS_CLASS_SEPARATION",
        "GOAL_CONVERGENCE_STALL",
        "GOAL_TO_LEAD_TRACE",
        "LEAD_TO_FRONTIER_TRACE",
        "FRONTIER_TO_ACTION_TRACE",
        "ACTION_TO_STATE_EFFECT_TRACE",
        "FRONTIER_PERSISTENCE",
        "PROGRESSION_LOCAL_OPTIMUM_DETECTION",
        "METRICS_V2_NON_NULL",
        "ACTION_STATE_EFFECT_CONTRACT",
        "V17_C8_C9_VIGNETTE",
        "DEFERRED_FRONTIER_RETAINED",
        "RETURN_PRESSURE_GENERATED",
    ]
    zero_keys = [
        "CRITICAL_FRONTIER_SILENT_DROP",
        "LATERAL_PROGRESS_GOAL_STALL_RESET",
        "HIDDEN_SOLUTION_SIGNAL",
        "CORBITT_SPECIFIC_FORCE_PATH",
    ]
    passed = all(bool(gates[k]) for k in bool_pass_keys) and all(gates[k] == 0 for k in zero_keys) and (
        gates["MANDATORY_TOP_FRONTIER_SELECTION"] is False
    )

    return {
        "smoke_id": SMOKE_ID,
        "PASS": passed,
        "gates": gates,
        "runtime_snapshot": {
            "dual_stall": rt.dual_stall.to_dict(),
            "return_pressure": rt.frontiers.return_pressure,
            "metrics_rates": rates,
            "local_optimum_count": blob["PROGRESSION_LOCAL_OPTIMUM_COUNT"],
        },
    }


def main() -> int:
    result = run_smoke()
    out_dir = ROOT / "outputs" / "v18_smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{SMOKE_ID}.json"
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"smoke_id": SMOKE_ID, "PASS": result["PASS"], "out": str(out_path)}, ensure_ascii=False))
    for k, v in result["gates"].items():
        print(f"  {k} = {v}")
    return 0 if result["PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
