"""Natural decision cycle — evidence → PL → group → KP → S0-S4 → executor handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .evidence import ReasoningEvidence
from .frontier_recovery import FrontierRecoveryPolicy, FrontierSet
from .group_decision import GroupDeliberation, GroupDecision, PlayerProposal
from .hypothesis_tracker import HypothesisTracker
from .knowledge_boundary import KnowledgeBoundaryError, ReasoningKnowledgeBoundary, KnownFactView
from .kp_assessment import KPProgressAssessment, assess_party_progress, stall_weight
from .kp_intervention import (
    InterventionDecision,
    InterventionRuntimeState,
    KPInterventionPolicy,
)
from .lead_tracker import LeadTracker
from .pl_policy import PLDecisionPolicy, UnexplainedActionError
from .pl_state import PLReasoningState
from .safe_fallback import SafeLegacyProgression, FallbackEvidence, FallbackUnboundedError
from .recent_action import RecentActionContractError


@dataclass
class NaturalDecisionResult:
    selected_action: Optional[dict] = None
    reasoning_evidence: Optional[dict] = None
    group_decision: Optional[dict] = None
    kp_assessment: Optional[dict] = None
    intervention: Optional[dict] = None
    frontier_set: Optional[dict] = None
    fallback: Optional[dict] = None
    mode: str = "NATURAL"
    errors: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class NaturalDecisionPipeline:
    def __init__(
        self,
        *,
        boundary: Optional[ReasoningKnowledgeBoundary] = None,
        lead_tracker: Optional[LeadTracker] = None,
        hypothesis_tracker: Optional[HypothesisTracker] = None,
    ):
        self.boundary = boundary or ReasoningKnowledgeBoundary()
        self.leads = lead_tracker or LeadTracker(self.boundary)
        self.hypotheses = hypothesis_tracker or HypothesisTracker()
        self.pl_policy = PLDecisionPolicy(self.boundary)
        self.kp_policy = KPInterventionPolicy(boundary=self.boundary)
        self.frontier_policy = FrontierRecoveryPolicy(self.boundary)
        self.fallback = SafeLegacyProgression(self.boundary)
        self.intervention_runtime = InterventionRuntimeState()

    def run_cycle(
        self,
        *,
        pl_states: Sequence[PLReasoningState | Mapping[str, Any]],
        candidate_actions_by_actor: Mapping[str, Sequence[Mapping[str, Any]]],
        cycle: Any = None,
        turn: Any = None,
        progress_events: Sequence[Mapping[str, Any]] = (),
        recent_actions: Sequence[Mapping[str, Any]] = (),
        hypothesis_tests: Sequence[Mapping[str, Any]] = (),
        alternative_explorations: Sequence[Mapping[str, Any]] = (),
        party_understanding: Sequence[str] = (),
        restore_location: str = "",
        use_group: bool = True,
        exhausted_attempts: Sequence[Mapping[str, Any]] = (),
        legal_locations: Optional[set] = None,
        current_location: str = "",
        resolved_objectives: Optional[set] = None,
        hidden_candidate_ids: Optional[set] = None,
    ) -> NaturalDecisionResult:
        result = NaturalDecisionResult()
        states: list[PLReasoningState] = []
        for s in pl_states:
            states.append(s if isinstance(s, PLReasoningState) else PLReasoningState.from_dict(s))

        try:
            # Per-PL selection
            proposals: list[PlayerProposal] = []
            evidences: list[ReasoningEvidence] = []
            for st in states:
                cands = list(candidate_actions_by_actor.get(st.actor_id) or [])
                # Ensure reasons
                enriched = []
                for c in cands:
                    if not str(c.get("reason") or "").strip():
                        raise UnexplainedActionError("UNEXPLAINED_ACTION_PATH")
                    support = c.get("supporting_knowledge") or []
                    self.boundary.validate_supporting_knowledge(support, allow_hypothesis=True)
                    enriched.append(c)
                chosen, evidence = self.pl_policy.select(st, enriched, cycle=cycle, turn=turn)
                evidences.append(evidence)
                proposals.append(
                    PlayerProposal(
                        actor_id=st.actor_id,
                        proposal=chosen,
                        reason=str(chosen.get("reason") or evidence.selection_reason),
                        confidence=float(evidence.confidence or 0.5),
                        risk=float((chosen.get("axes") or {}).get("risk") or 0.3),
                        role=str(chosen.get("role") or ""),
                    )
                )

            group_decision: Optional[GroupDecision] = None
            if use_group and len(proposals) > 1:
                gd = GroupDeliberation()
                for p in proposals:
                    gd.add_proposal(p)
                group_decision = gd.decide()
                selected = dict(group_decision.selected_proposal)
                result.group_decision = group_decision.to_dict()
            else:
                selected = dict(proposals[0].proposal) if proposals else None
                if evidences:
                    result.reasoning_evidence = evidences[0].to_dict()

            if evidences and not result.reasoning_evidence:
                result.reasoning_evidence = evidences[0].to_dict()

            frontier = self.frontier_policy.build_set(
                self.leads,
                restore_location=restore_location,
            )
            result.frontier_set = frontier.to_dict()

            assessment = assess_party_progress(
                unresolved_leads=[f["frontier_id"] for f in self.leads.unresolved_high_value_frontier_set()],
                available_frontiers=frontier.frontier_ids,
                recent_actions=recent_actions,
                party_understanding=party_understanding,
                intervention_history=self.intervention_runtime.history,
                current_hint_level=self.intervention_runtime.current_s_level,
                progress_events=progress_events,
                hypothesis_tests=hypothesis_tests,
                alternative_explorations=alternative_explorations,
            )
            result.kp_assessment = assessment.to_dict()

            weight = stall_weight(assessment)
            decision, self.intervention_runtime = self.kp_policy.decide(
                assessment,
                self.intervention_runtime,
                frontier_set=frontier.frontier_ids,
                restore_location=restore_location or frontier.restore_location,
                stall_increment=weight,
            )
            result.intervention = decision.to_dict()

            # S4 recovery actions override selection toward frontier set (not solution)
            if decision.s_level == 4:
                recovery = self.frontier_policy.recovery_actions(frontier)
                if recovery:
                    selected = recovery[0]
                self.intervention_runtime = self.kp_policy.complete_s4_recovery(
                    self.intervention_runtime
                )
                result.intervention = {
                    **decision.to_dict(),
                    "post_recovery_s_level": 0,
                    "recovery_grace_remaining": self.intervention_runtime.recovery_grace_remaining,
                }

            result.selected_action = selected
            result.mode = "NATURAL"
            self.fallback.reset_streak_on_success()
            return result

        except (KnowledgeBoundaryError, UnexplainedActionError, FallbackUnboundedError) as exc:
            result.errors.append({"type": type(exc).__name__, "code": getattr(exc, "code", ""), "msg": str(exc)})
            # Knowledge leaks and unexplained actions fail-closed (no unsafe legacy)
            if isinstance(exc, KnowledgeBoundaryError) and getattr(exc, "code", "") in {
                "REASONING_KNOWLEDGE_LEAK",
                "UNGROUNDED_KP_HINT",
                "HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK",
                "HIDDEN_CORRECT_PATH_SIGNAL",
                "DIRECT_SOLUTION_S4_PATH",
            }:
                result.mode = "REJECT"
                return result
            if isinstance(exc, UnexplainedActionError):
                result.mode = "REJECT"
                return result
            if isinstance(exc, FallbackUnboundedError):
                result.mode = "FAIL_CLOSED"
                return result
            return result

        except (RecentActionContractError, AttributeError, TypeError, KeyError):
            # V17: internal contract / programming errors never become SAFE_LEGACY here
            raise
        except Exception as exc:
            # Recoverable reasoning / model failure → SAFE_LEGACY_PROGRESSION
            result.errors.append({"type": type(exc).__name__, "msg": str(exc)})
            all_cands: list[dict] = []
            for cands in candidate_actions_by_actor.values():
                all_cands.extend(dict(x) for x in cands)
            try:
                selected, fb = self.fallback.select(
                    all_cands,
                    failure_reason=str(exc),
                    exhausted_attempts=exhausted_attempts,
                    legal_locations=legal_locations,
                    current_location=current_location,
                    resolved_objectives=resolved_objectives,
                    hidden_candidate_ids=hidden_candidate_ids,
                    unresolved_lead_ids=[
                        f["frontier_id"] for f in self.leads.unresolved_high_value_frontier_set()
                    ],
                    recent_actions=recent_actions,
                )
                result.selected_action = selected
                result.fallback = fb.to_dict()
                result.mode = "SAFE_LEGACY_PROGRESSION"
            except FallbackUnboundedError as fb_exc:
                result.errors.append({"type": "FallbackUnboundedError", "msg": str(fb_exc)})
                result.mode = "FAIL_CLOSED"
            except (RecentActionContractError, AttributeError, TypeError, KeyError) as fb_exc:
                # Fallback itself hit a contract bug → do not recurse; surface failure
                result.errors.append({"type": type(fb_exc).__name__, "msg": str(fb_exc)})
                result.mode = "SAFE_FALLBACK_FAILURE"
            return result


def run_natural_decision_cycle(**kwargs: Any) -> NaturalDecisionResult:
    pipeline = kwargs.pop("pipeline", None) or NaturalDecisionPipeline(
        boundary=kwargs.pop("boundary", None),
        lead_tracker=kwargs.pop("lead_tracker", None),
        hypothesis_tracker=kwargs.pop("hypothesis_tracker", None),
    )
    return pipeline.run_cycle(**kwargs)
