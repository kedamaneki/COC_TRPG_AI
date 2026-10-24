"""V18 Progression Convergence facade — dual stall + traces + metrics."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .action_state_effect import MethodAttemptTracker, classify_observed_effect
from .dual_stall import DualStallState, apply_progress_to_dual_stall
from .frontier_persistence import (
    FrontierPersistenceStore,
    apply_return_pressure,
    defer_frontier,
    record_why_not_selected,
    set_action_unavailable,
    should_remind_ignored_frontier,
    upsert_frontier,
)
from .goal_convergence import (
    GoalConvergenceTracker,
    detect_local_optimum,
    evaluate_chain_trace,
    note_local_optimum,
    tick_goal_convergence,
)
from .progress_semantics_v2 import summarize_cycle_progress


@dataclass
class ProgressionMetricsV2:
    meaningful_progress_count: int = 0
    goal_directed_progress_count: int = 0
    lateral_exploration_progress_count: int = 0
    total_cycles: int = 0
    frontier_switch_count: int = 0
    location_visit_count: int = 0
    location_revisit_count: int = 0
    goal_relevant_action_count: int = 0
    action_count: int = 0
    visited_locations: list = field(default_factory=list)
    last_frontier_id: str = ""

    def rates(self) -> dict:
        turns = max(1, int(self.total_cycles))
        actions = max(1, int(self.action_count))
        visits = max(1, int(self.location_visit_count))
        return {
            "MEANINGFUL_PROGRESS_RATE": float(self.meaningful_progress_count) / turns,
            "GOAL_DIRECTED_PROGRESS_RATE": float(self.goal_directed_progress_count) / turns,
            "LATERAL_EXPLORATION_PROGRESS_RATE": float(self.lateral_exploration_progress_count) / turns,
            "FRONTIER_SWITCH_RATE": float(self.frontier_switch_count) / turns,
            "LOCATION_REVISIT_RATE": float(self.location_revisit_count) / visits,
            "GOAL_RELEVANT_ACTION_RATE": float(self.goal_relevant_action_count) / actions,
        }

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rates"] = self.rates()
        return d


@dataclass
class ProgressionConvergenceRuntime:
    dual_stall: DualStallState = field(default_factory=DualStallState)
    frontiers: FrontierPersistenceStore = field(default_factory=FrontierPersistenceStore)
    goals: GoalConvergenceTracker = field(default_factory=GoalConvergenceTracker)
    method_attempts: MethodAttemptTracker = field(default_factory=MethodAttemptTracker)
    metrics: ProgressionMetricsV2 = field(default_factory=ProgressionMetricsV2)
    last_trace_breaks: list = field(default_factory=list)
    last_progress_summary: dict = field(default_factory=dict)
    hidden_solution_signal: int = 0
    corbitt_specific_force_path: int = 0
    mandatory_top_frontier_selection: bool = False

    def to_dict(self) -> dict:
        return {
            "schema_version": 18,
            "dual_stall": self.dual_stall.to_dict(),
            "frontiers": self.frontiers.to_dict(),
            "goals": self.goals.to_dict(),
            "method_attempts": self.method_attempts.to_dict(),
            "metrics": self.metrics.to_dict(),
            "last_trace_breaks": list(self.last_trace_breaks),
            "last_progress_summary": dict(self.last_progress_summary),
            "hidden_solution_signal": self.hidden_solution_signal,
            "corbitt_specific_force_path": self.corbitt_specific_force_path,
            "mandatory_top_frontier_selection": self.mandatory_top_frontier_selection,
            "MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK": self.dual_stall.max_goal_convergence_stall_streak,
            "FRONTIER_PERSISTENCE": len(
                [f for f in self.frontiers.frontiers.values() if f.status in ("ACTIVE", "DEFERRED")]
            ),
            "PROGRESSION_LOCAL_OPTIMUM_COUNT": self.goals.progression_local_optimum_count,
            "CRITICAL_FRONTIER_IGNORE_RATE": (
                float(self.frontiers.critical_frontier_ignore_count)
                / max(1, int(self.frontiers.critical_frontier_present_count))
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "ProgressionConvergenceRuntime":
        data = data or {}
        rt = cls(
            dual_stall=DualStallState.from_dict(data.get("dual_stall")),
            frontiers=FrontierPersistenceStore.from_dict(data.get("frontiers")),
            goals=GoalConvergenceTracker(),
            hidden_solution_signal=int(data.get("hidden_solution_signal") or 0),
            corbitt_specific_force_path=int(data.get("corbitt_specific_force_path") or 0),
            mandatory_top_frontier_selection=bool(data.get("mandatory_top_frontier_selection")),
        )
        gdata = data.get("goals") or {}
        for gid, g in (gdata.get("goals") or {}).items():
            if isinstance(g, Mapping):
                rt.goals.upsert_goal(g)
        rt.goals.progression_local_optimum_count = int(gdata.get("progression_local_optimum_count") or 0)
        rt.goals.local_optimum_active = bool(gdata.get("local_optimum_active"))
        rt.goals.escalation_hint = str(gdata.get("escalation_hint") or "G0")
        m = data.get("metrics") or {}
        if m:
            rt.metrics = ProgressionMetricsV2(
                meaningful_progress_count=int(m.get("meaningful_progress_count") or 0),
                goal_directed_progress_count=int(m.get("goal_directed_progress_count") or 0),
                lateral_exploration_progress_count=int(m.get("lateral_exploration_progress_count") or 0),
                total_cycles=int(m.get("total_cycles") or 0),
                frontier_switch_count=int(m.get("frontier_switch_count") or 0),
                location_visit_count=int(m.get("location_visit_count") or 0),
                location_revisit_count=int(m.get("location_revisit_count") or 0),
                goal_relevant_action_count=int(m.get("goal_relevant_action_count") or 0),
                action_count=int(m.get("action_count") or 0),
                visited_locations=list(m.get("visited_locations") or []),
                last_frontier_id=str(m.get("last_frontier_id") or ""),
            )
        ma = data.get("method_attempts") or {}
        rt.method_attempts.key_to_no_effect_streak = dict(ma.get("key_to_no_effect_streak") or {})
        return rt


def ensure_progression_runtime(state: dict) -> ProgressionConvergenceRuntime:
    runtime = state.setdefault("director_v2", {})
    blob = runtime.get("progression_convergence")
    if isinstance(blob, ProgressionConvergenceRuntime):
        return blob
    if isinstance(blob, Mapping):
        rt = ProgressionConvergenceRuntime.from_dict(blob)
    else:
        rt = ProgressionConvergenceRuntime()
    runtime["progression_convergence"] = rt.to_dict()
    return rt


def persist_progression_runtime(state: dict, rt: ProgressionConvergenceRuntime) -> None:
    runtime = state.setdefault("director_v2", {})
    runtime["progression_convergence"] = rt.to_dict()


def tick_progression_cycle(
    rt: ProgressionConvergenceRuntime,
    *,
    progress_events: Sequence[Mapping[str, Any]] = (),
    visible_goal_ids: Sequence[str] = (),
    unresolved_lead_ids: Sequence[str] = (),
    known_blocker_ids: Sequence[str] = (),
    known_frontier_ids: Sequence[str] = (),
    primary_goal_id: str = "",
    cycle: int | None = None,
    location: str = "",
    selected_frontier_id: str = "",
    goal_relevant_action: bool = False,
) -> dict:
    summary = summarize_cycle_progress(
        progress_events,
        visible_goal_ids=visible_goal_ids,
        unresolved_lead_ids=unresolved_lead_ids,
        known_blocker_ids=known_blocker_ids,
        known_frontier_ids=known_frontier_ids,
    )
    rt.last_progress_summary = dict(summary)
    rt.metrics.total_cycles += 1
    if summary["meaningful_progress"]:
        rt.metrics.meaningful_progress_count += 1
    if summary["goal_directed_progress"]:
        rt.metrics.goal_directed_progress_count += 1
    if summary["lateral_exploration_progress"]:
        rt.metrics.lateral_exploration_progress_count += 1

    if location:
        rt.metrics.location_visit_count += 1
        if location in rt.metrics.visited_locations:
            rt.metrics.location_revisit_count += 1
        else:
            rt.metrics.visited_locations.append(location)

    if selected_frontier_id:
        if rt.metrics.last_frontier_id and rt.metrics.last_frontier_id != selected_frontier_id:
            rt.metrics.frontier_switch_count += 1
        rt.metrics.last_frontier_id = selected_frontier_id
        rt.metrics.action_count += 1
        if goal_relevant_action:
            rt.metrics.goal_relevant_action_count += 1

    rates = rt.metrics.rates()
    local_opt = detect_local_optimum(
        meaningful_progress=bool(summary["meaningful_progress"]),
        goal_directed_progress=bool(summary["goal_directed_progress"]),
        location_revisit_rate=float(rates["LOCATION_REVISIT_RATE"]),
        frontier_switch_rate=float(rates["FRONTIER_SWITCH_RATE"]),
        goal_stall_streak=int(rt.dual_stall.goal_convergence_stall_streak),
    )
    note_local_optimum(rt.goals, local_opt)

    rt.dual_stall = apply_progress_to_dual_stall(
        rt.dual_stall,
        meaningful=bool(summary["meaningful_progress"]),
        goal_directed=bool(summary["goal_directed_progress"]),
        terminal=bool(summary["terminal_progress"]),
        cycle=cycle,
        local_optimum=local_opt,
    )

    gid = str(primary_goal_id or (visible_goal_ids[0] if visible_goal_ids else "default_goal"))
    tick_goal_convergence(
        rt.goals,
        goal_id=gid,
        goal_directed=bool(summary["goal_directed_progress"] or summary["terminal_progress"]),
        cycle=cycle,
        active_lead_count=len(list(unresolved_lead_ids or [])),
        active_frontier_count=len(
            [f for f in rt.frontiers.frontiers.values() if f.status in ("ACTIVE", "DEFERRED")]
        ),
    )

    apply_return_pressure(
        rt.frontiers,
        goal_stall_streak=rt.dual_stall.goal_convergence_stall_streak,
    )

    return {
        **summary,
        "dual_stall": rt.dual_stall.to_dict(),
        "local_optimum": local_opt,
        "return_pressure": rt.frontiers.return_pressure,
        "escalation_hint": rt.goals.escalation_hint,
        "metrics": rt.metrics.rates(),
        "remind_ignored_frontier": should_remind_ignored_frontier(rt.frontiers),
    }


def record_trace(
    rt: ProgressionConvergenceRuntime,
    *,
    goal_id: str,
    lead_ids: Sequence[str],
    frontier_ids: Sequence[str],
    action_candidates: Sequence[Mapping[str, Any]] | None = None,
    observed_effect: Mapping[str, Any] | None = None,
    action_executed: bool = False,
) -> list[str]:
    breaks = evaluate_chain_trace(
        goal_id=goal_id,
        lead_ids=lead_ids,
        frontier_ids=frontier_ids,
        action_candidates=action_candidates,
        observed_effect=observed_effect,
        action_executed=action_executed,
    )
    rt.last_trace_breaks = list(breaks)
    return breaks


# Re-exports for fixtures
__all__ = [
    "ProgressionConvergenceRuntime",
    "ProgressionMetricsV2",
    "ensure_progression_runtime",
    "persist_progression_runtime",
    "tick_progression_cycle",
    "record_trace",
    "upsert_frontier",
    "defer_frontier",
    "record_why_not_selected",
    "set_action_unavailable",
    "classify_observed_effect",
    "apply_return_pressure",
]
