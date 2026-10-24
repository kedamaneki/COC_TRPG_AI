"""V18 Goal Convergence Tracker + Local Optimum detection."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass
class GoalConvergenceEntry:
    goal_id: str
    last_goal_directed_progress_cycle: int | None = None
    goal_no_progress_streak: int = 0
    active_lead_count: int = 0
    active_frontier_count: int = 0
    unresolved_blockers: list = field(default_factory=list)
    recent_attempts: list = field(default_factory=list)
    statement: str = ""
    status: str = "ACTIVE"
    priority_class: str = "normal"
    source: str = ""
    visible_to_party: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GoalConvergenceTracker:
    goals: dict[str, GoalConvergenceEntry] = field(default_factory=dict)
    progression_local_optimum_count: int = 0
    local_optimum_active: bool = False
    escalation_hint: str = "G0"  # G0..G4 conceptual

    def to_dict(self) -> dict:
        return {
            "goals": {k: v.to_dict() for k, v in self.goals.items()},
            "progression_local_optimum_count": self.progression_local_optimum_count,
            "local_optimum_active": self.local_optimum_active,
            "escalation_hint": self.escalation_hint,
            "max_goal_no_progress_streak": self.max_goal_no_progress_streak(),
        }

    def max_goal_no_progress_streak(self) -> int:
        if not self.goals:
            return 0
        return max(int(g.goal_no_progress_streak) for g in self.goals.values())

    def upsert_goal(self, entry: GoalConvergenceEntry | Mapping[str, Any]) -> GoalConvergenceEntry:
        if isinstance(entry, Mapping):
            obj = GoalConvergenceEntry(
                goal_id=str(entry.get("goal_id") or ""),
                last_goal_directed_progress_cycle=entry.get("last_goal_directed_progress_cycle"),
                goal_no_progress_streak=int(entry.get("goal_no_progress_streak") or 0),
                active_lead_count=int(entry.get("active_lead_count") or 0),
                active_frontier_count=int(entry.get("active_frontier_count") or 0),
                unresolved_blockers=list(entry.get("unresolved_blockers") or []),
                recent_attempts=list(entry.get("recent_attempts") or []),
                statement=str(entry.get("statement") or ""),
                status=str(entry.get("status") or "ACTIVE"),
                priority_class=str(entry.get("priority_class") or "normal"),
                source=str(entry.get("source") or ""),
                visible_to_party=bool(entry.get("visible_to_party", True)),
            )
        else:
            obj = entry
        if not obj.goal_id:
            raise ValueError("goal_id required")
        self.goals[obj.goal_id] = obj
        return obj


def tick_goal_convergence(
    tracker: GoalConvergenceTracker,
    *,
    goal_id: str,
    goal_directed: bool,
    cycle: int | None = None,
    active_lead_count: int | None = None,
    active_frontier_count: int | None = None,
) -> GoalConvergenceEntry:
    g = tracker.goals.get(str(goal_id))
    if g is None:
        g = tracker.upsert_goal({"goal_id": goal_id})
    if goal_directed:
        g.goal_no_progress_streak = 0
        if cycle is not None:
            g.last_goal_directed_progress_cycle = int(cycle)
    else:
        g.goal_no_progress_streak = int(g.goal_no_progress_streak) + 1
    if active_lead_count is not None:
        g.active_lead_count = int(active_lead_count)
    if active_frontier_count is not None:
        g.active_frontier_count = int(active_frontier_count)
    tracker.goals[g.goal_id] = g
    tracker.escalation_hint = escalation_hint_for_streak(g.goal_no_progress_streak)
    return g


def escalation_hint_for_streak(streak: int) -> str:
    """Soft ladder — never maps directly to forced S4 / correct action."""
    s = int(streak)
    if s <= 0:
        return "G0"
    if s <= 2:
        return "G1"  # self-review
    if s <= 4:
        return "G2"  # lead reminder
    if s <= 7:
        return "G3"  # frontier persistence nudge
    return "G4"  # frontier *set* recovery input (not single solution)


def detect_local_optimum(
    *,
    meaningful_progress: bool,
    goal_directed_progress: bool,
    location_revisit_rate: float = 0.0,
    frontier_switch_rate: float = 0.0,
    goal_stall_streak: int = 0,
    revisit_threshold: float = 0.5,
    switch_threshold: float = 0.5,
    stall_threshold: int = 3,
) -> bool:
    if goal_directed_progress:
        return False
    if not meaningful_progress:
        return False
    if int(goal_stall_streak) < int(stall_threshold):
        return False
    if float(location_revisit_rate) < float(revisit_threshold) and float(frontier_switch_rate) < float(
        switch_threshold
    ):
        return False
    return True


def note_local_optimum(tracker: GoalConvergenceTracker, detected: bool) -> None:
    if detected and not tracker.local_optimum_active:
        tracker.progression_local_optimum_count += 1
    tracker.local_optimum_active = bool(detected)


# Trace break reasons (silent drop forbidden)
TRACE_GOAL_WITHOUT_LEAD = "GOAL_WITHOUT_LEAD"
TRACE_LEAD_WITHOUT_FRONTIER = "LEAD_WITHOUT_FRONTIER"
TRACE_FRONTIER_WITHOUT_ACTION = "FRONTIER_WITHOUT_ACTION"
TRACE_ACTION_WITHOUT_EFFECT = "ACTION_WITHOUT_EFFECT"


def evaluate_chain_trace(
    *,
    goal_id: str,
    lead_ids: Sequence[str],
    frontier_ids: Sequence[str],
    action_candidates: Sequence[Mapping[str, Any]] | None = None,
    observed_effect: Mapping[str, Any] | None = None,
    action_executed: bool = False,
) -> list[str]:
    """Return list of explicit break reasons (empty = intact or N/A)."""
    breaks: list[str] = []
    if goal_id and not lead_ids:
        breaks.append(TRACE_GOAL_WITHOUT_LEAD)
    if lead_ids and not frontier_ids:
        breaks.append(TRACE_LEAD_WITHOUT_FRONTIER)
    if frontier_ids and action_candidates is not None and len(list(action_candidates)) == 0:
        breaks.append(TRACE_FRONTIER_WITHOUT_ACTION)
    if action_executed and observed_effect is None:
        breaks.append(TRACE_ACTION_WITHOUT_EFFECT)
    return breaks
