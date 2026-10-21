"""KP progress assessment — observe party understanding without solution binding."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence


MEANINGFUL_PROGRESS_KINDS = frozenset({
    "new_fact",
    "new_location",
    "hypothesis_resolved",
    "new_viable_lead",
    "critical_state_change",
    "objective_advancement",
    "major_risk_discovery",
    "useful_resource_acquisition",
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
) -> KPProgressAssessment:
    meaningful = any(classify_progress_event(e.get("kind", "")) for e in progress_events)
    hyp_test = bool(hypothesis_tests)
    alt_explore = bool(alternative_explorations)

    # repetition: last 3 actions same action+target
    merely = False
    if len(recent_actions) >= 3:
        keys = [
            (str(a.get("action") or ""), str(a.get("target") or ""))
            for a in recent_actions[-3:]
        ]
        merely = len(set(keys)) == 1

    remember = True
    if unresolved_leads and recent_actions:
        recent_targets = " ".join(str(a.get("target") or "") for a in recent_actions[-5:])
        # if no recent action mentions any unresolved lead, may have forgotten
        if not any(str(lead) in recent_targets for lead in unresolved_leads):
            # not conclusive forget — only flag when also merely repeating elsewhere
            remember = not merely

    if meaningful:
        trend = "advancing"
    elif hyp_test or alt_explore:
        trend = "exploring"
    elif merely:
        trend = "stalled"
    else:
        trend = "unknown"

    necessary = False
    least = 0
    if merely and not meaningful and not hyp_test and not alt_explore:
        necessary = True
        least = 1  # S1 self-review at minimum
        if not remember:
            least = max(least, 2)
        # further escalation left to InterventionPolicy with history

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
    if assessment.meaningful_progress_this_cycle:
        return 0.0
    if assessment.testing_valid_hypothesis or assessment.exploring_valid_alternative:
        return 0.25
    if assessment.merely_repeating:
        return 1.0
    return 0.5
