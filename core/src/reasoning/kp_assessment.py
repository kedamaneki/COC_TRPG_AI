"""KP progress assessment — observe party understanding without solution binding."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .recent_action import normalize_recent_actions, RecentActionContractError


MEANINGFUL_PROGRESS_KINDS = frozenset({
    "new_fact",
    "new_location",
    "hypothesis_resolved",
    "new_viable_lead",
    "critical_state_change",
    "objective_advancement",
    "major_risk_discovery",
    "useful_resource_acquisition",
    # V17 progress_type aliases (lowercase)
    "object_state_change",
    "risk_discovery",
    "resource_gain",
})


@dataclass
class KPProgressAssessment:
    party_understanding: list[str] = field(default_factory=list)
    party_misunderstandings: list[str] = field(default_factory=list)
    unresolved_leads: list[str] = field(default_factory=list)
    available_meaningful_frontiers: list[str] = field(default_factory=list)
    exhausted_frontiers: list[str] = field(default_factory=list)
    current_progress_trend: str = "unknown"  # advancing | exploring | stalled | regressing
    recent_repetition: bool = False
    intervention_history: list[dict] = field(default_factory=list)
    current_hint_level: int = 0  # S0..S4
    meaningful_progress_this_cycle: bool = False
    # V18 dual-stall inputs
    goal_directed_progress_this_cycle: bool = False
    lateral_exploration_progress_this_cycle: bool = False
    terminal_progress_this_cycle: bool = False
    activity_stall: int = 0
    goal_convergence_stall: int = 0
    local_optimum: bool = False
    frontier_ignore_streak: int = 0
    testing_valid_hypothesis: bool = False
    exploring_valid_alternative: bool = False
    merely_repeating: bool = False
    remember_unresolved_leads: bool = True
    intervention_necessary: bool = False
    least_intrusive_level: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def classify_progress_event(kind: str) -> bool:
    return str(kind or "").lower() in MEANINGFUL_PROGRESS_KINDS


def assess_party_progress(
    *,
    unresolved_leads: Sequence[str],
    available_frontiers: Sequence[str],
    exhausted_frontiers: Sequence[str] = (),
    recent_actions: Sequence[Mapping[str, Any]] = (),
    party_understanding: Sequence[str] = (),
    party_misunderstandings: Sequence[str] = (),
    intervention_history: Sequence[Mapping[str, Any]] = (),
    current_hint_level: int = 0,
    progress_events: Sequence[Mapping[str, Any]] = (),
    hypothesis_tests: Sequence[Mapping[str, Any]] = (),
    alternative_explorations: Sequence[Mapping[str, Any]] = (),
    visible_goal_ids: Sequence[str] = (),
    known_blocker_ids: Sequence[str] = (),
    activity_stall: int = 0,
    goal_convergence_stall: int = 0,
    local_optimum: bool = False,
    frontier_ignore_streak: int = 0,
) -> KPProgressAssessment:
    from .progress_semantics_v2 import summarize_cycle_progress

    summary = summarize_cycle_progress(
        [e for e in progress_events if isinstance(e, Mapping)],
        visible_goal_ids=visible_goal_ids or unresolved_leads,
        unresolved_lead_ids=unresolved_leads,
        known_blocker_ids=known_blocker_ids,
        known_frontier_ids=available_frontiers,
    )
    # Fallback: legacy kind-only meaningful if no v2 classes fired but kinds match
    legacy_meaningful = any(
        classify_progress_event(e.get("kind") or e.get("progress_type") or "")
        for e in progress_events
        if isinstance(e, Mapping)
    )
    meaningful = bool(summary["meaningful_progress"] or legacy_meaningful)
    goal_directed = bool(summary["goal_directed_progress"])
    lateral = bool(summary["lateral_exploration_progress"])
    if meaningful and not goal_directed and not lateral:
        # Explicit class / legacy kind without GD links → lateral exploration
        lateral = True
    terminal = bool(summary["terminal_progress"])
    hyp_test = bool(hypothesis_tests)
    alt_explore = bool(alternative_explorations)

    # V17: normalize recent_actions to canonical dicts before .get
    try:
        recent_canon = [r.to_dict() for r in normalize_recent_actions(recent_actions or [])]
    except RecentActionContractError:
        raise

    # repetition: last 3 actions same action+target
    merely = False
    if len(recent_canon) >= 3:
        keys = [
            (str(a.get("action") or ""), str(a.get("target") or ""))
            for a in recent_canon[-3:]
        ]
        merely = len(set(keys)) == 1

    remember = True
    if unresolved_leads and recent_canon:
        recent_targets = " ".join(str(a.get("target") or "") for a in recent_canon[-5:])
        # if no recent action mentions any unresolved lead, may have forgotten
        if not any(str(lead) in recent_targets for lead in unresolved_leads):
            # not conclusive forget — only flag when also merely repeating elsewhere
            remember = not merely

    if goal_directed:
        trend = "advancing"
    elif lateral or meaningful:
        trend = "exploring"
    elif hyp_test or alt_explore:
        trend = "exploring"
    elif merely:
        trend = "stalled"
    else:
        trend = "unknown"

    necessary = False
    least = 0
    # Activity stall: no meaningful at all
    if merely and not meaningful and not hyp_test and not alt_explore:
        necessary = True
        least = 1  # S1 self-review at minimum
        if not remember:
            least = max(least, 2)
    # Goal convergence stall with lateral-only progress → soft self-review, not S4
    if int(goal_convergence_stall) >= 3 and not goal_directed and unresolved_leads:
        necessary = True
        least = max(least, 1)
        if int(frontier_ignore_streak) >= 3:
            least = max(least, 2)
    if local_optimum:
        necessary = True
        least = max(least, 1)

    return KPProgressAssessment(
        party_understanding=list(party_understanding),
        party_misunderstandings=list(party_misunderstandings),
        unresolved_leads=[str(x) for x in unresolved_leads],
        available_meaningful_frontiers=[str(x) for x in available_frontiers],
        exhausted_frontiers=[str(x) for x in exhausted_frontiers],
        current_progress_trend=trend,
        recent_repetition=merely,
        intervention_history=[dict(x) for x in intervention_history],
        current_hint_level=int(current_hint_level),
        meaningful_progress_this_cycle=meaningful,
        goal_directed_progress_this_cycle=goal_directed,
        lateral_exploration_progress_this_cycle=lateral,
        terminal_progress_this_cycle=terminal,
        activity_stall=int(activity_stall),
        goal_convergence_stall=int(goal_convergence_stall),
        local_optimum=bool(local_optimum),
        frontier_ignore_streak=int(frontier_ignore_streak),
        testing_valid_hypothesis=hyp_test,
        exploring_valid_alternative=alt_explore,
        merely_repeating=merely,
        remember_unresolved_leads=remember,
        intervention_necessary=necessary,
        least_intrusive_level=least,
        notes=[],
    )


def stall_weight(assessment: KPProgressAssessment) -> float:
    """Reduce stall accrual when rational exploration continues without mutation."""
    # Goal-directed clears activity stall accrual
    if assessment.goal_directed_progress_this_cycle or assessment.terminal_progress_this_cycle:
        return 0.0
    # Lateral progress: activity stall weight 0, but goal convergence may still accrue via policy
    if assessment.lateral_exploration_progress_this_cycle:
        return 0.0
    if assessment.meaningful_progress_this_cycle and not assessment.unresolved_leads:
        return 0.0
    if assessment.testing_valid_hypothesis or assessment.exploring_valid_alternative:
        return 0.25
    if assessment.merely_repeating:
        return 1.0
    # Goal convergence pressure without activity progress
    if int(assessment.goal_convergence_stall) > 0 and assessment.unresolved_leads:
        return 0.35
    return 0.5
