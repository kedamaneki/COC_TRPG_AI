"""V18 Dual Stall — ACTIVITY_STALL vs GOAL_CONVERGENCE_STALL."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class DualStallState:
    activity_stall_streak: int = 0
    goal_convergence_stall_streak: int = 0
    max_activity_stall_streak: int = 0
    max_goal_convergence_stall_streak: int = 0
    last_meaningful_progress_cycle: int | None = None
    last_goal_directed_progress_cycle: int | None = None
    stall_class: str = "ACTIVE_EXPLORATION"
    # ACTIVE_EXPLORATION | ACTIVITY_STALL | GOAL_CONVERGENCE_STALL | LOCAL_OPTIMUM | FRONTIER_BLOCKED

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "DualStallState":
        data = data or {}
        return cls(
            activity_stall_streak=int(data.get("activity_stall_streak") or 0),
            goal_convergence_stall_streak=int(data.get("goal_convergence_stall_streak") or 0),
            max_activity_stall_streak=int(data.get("max_activity_stall_streak") or 0),
            max_goal_convergence_stall_streak=int(data.get("max_goal_convergence_stall_streak") or 0),
            last_meaningful_progress_cycle=data.get("last_meaningful_progress_cycle"),
            last_goal_directed_progress_cycle=data.get("last_goal_directed_progress_cycle"),
            stall_class=str(data.get("stall_class") or "ACTIVE_EXPLORATION"),
        )


def apply_progress_to_dual_stall(
    state: DualStallState,
    *,
    meaningful: bool,
    goal_directed: bool,
    terminal: bool = False,
    cycle: int | None = None,
    local_optimum: bool = False,
    frontier_blocked: bool = False,
) -> DualStallState:
    """
    Lateral (meaningful, not GD):
      ACTIVITY_STALL = reset
      GOAL_CONVERGENCE_STALL = increment
    GD or terminal:
      both reset
    Neither:
      both increment
    """
    out = DualStallState(
        activity_stall_streak=state.activity_stall_streak,
        goal_convergence_stall_streak=state.goal_convergence_stall_streak,
        max_activity_stall_streak=state.max_activity_stall_streak,
        max_goal_convergence_stall_streak=state.max_goal_convergence_stall_streak,
        last_meaningful_progress_cycle=state.last_meaningful_progress_cycle,
        last_goal_directed_progress_cycle=state.last_goal_directed_progress_cycle,
        stall_class=state.stall_class,
    )

    if goal_directed or terminal:
        out.activity_stall_streak = 0
        out.goal_convergence_stall_streak = 0
        if cycle is not None:
            out.last_meaningful_progress_cycle = int(cycle)
            out.last_goal_directed_progress_cycle = int(cycle)
        out.stall_class = "ACTIVE_EXPLORATION"
    elif meaningful:
        # Lateral or meaningful-without-GD
        out.activity_stall_streak = 0
        out.goal_convergence_stall_streak = int(out.goal_convergence_stall_streak) + 1
        if cycle is not None:
            out.last_meaningful_progress_cycle = int(cycle)
        out.stall_class = "GOAL_CONVERGENCE_STALL"
    else:
        out.activity_stall_streak = int(out.activity_stall_streak) + 1
        out.goal_convergence_stall_streak = int(out.goal_convergence_stall_streak) + 1
        out.stall_class = "ACTIVITY_STALL"

    out.max_activity_stall_streak = max(out.max_activity_stall_streak, out.activity_stall_streak)
    out.max_goal_convergence_stall_streak = max(
        out.max_goal_convergence_stall_streak, out.goal_convergence_stall_streak
    )

    if frontier_blocked:
        out.stall_class = "FRONTIER_BLOCKED"
    elif local_optimum and out.goal_convergence_stall_streak > 0:
        out.stall_class = "LOCAL_OPTIMUM"

    return out
