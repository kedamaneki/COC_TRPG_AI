"""KP intervention policy — S0..S4 with de-escalation and no direct solution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .kp_assessment import KPProgressAssessment
from .knowledge_boundary import KnowledgeBoundaryError, ReasoningKnowledgeBoundary


S_LEVEL_NAMES = {
    0: "NONE",
    1: "PLAYER_SELF_REVIEW",
    2: "INFORMATION_REMINDER",
    3: "SOFT_GUIDANCE",
    4: "FAILSAFE_RECOVERY",
}


class InterventionLevel:
    """Named S-level constants."""
    S0 = 0
    S1 = 1
    S2 = 2
    S3 = 3
    S4 = 4
    NONE = 0
    PLAYER_SELF_REVIEW = 1
    INFORMATION_REMINDER = 2
    SOFT_GUIDANCE = 3
    FAILSAFE_RECOVERY = 4


class DirectSolutionS4Error(ValueError):
    code = "DIRECT_SOLUTION_S4_PATH"


@dataclass
class InterventionDecision:
    s_level: int
    name: str
    payload: dict = field(default_factory=dict)
    deescalated: bool = False
    recovery_grace_active: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class InterventionRuntimeState:
    current_s_level: int = 0
    stall_score: float = 0.0
    recovery_grace_remaining: int = 0
    last_intervention: Optional[dict] = None
    history: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class KPInterventionPolicy:
    """Escalate only when necessary; never force the solution action."""

    def __init__(
        self,
        *,
        boundary: Optional[ReasoningKnowledgeBoundary] = None,
        s1_threshold: float = 2.0,
        s2_threshold: float = 4.0,
        s3_threshold: float = 6.0,
        s4_threshold: float = 8.0,
        recovery_grace_cycles: int = 3,
    ):
        self.boundary = boundary or ReasoningKnowledgeBoundary()
        self.s1_threshold = s1_threshold
        self.s2_threshold = s2_threshold
        self.s3_threshold = s3_threshold
        self.s4_threshold = s4_threshold
        self.recovery_grace_cycles = recovery_grace_cycles

    def _build_s1(self, assessment: KPProgressAssessment) -> dict:
        return {
            "prompt_self_review": True,
            "known_summary_ids": list(assessment.party_understanding),
            "unresolved": list(assessment.unresolved_leads),
            "hint": None,
        }

    def _build_s2(self, assessment: KPProgressAssessment) -> dict:
        # Known information only — no new facts
        return {
            "remind_known": list(assessment.party_understanding),
            "remind_unresolved": list(assessment.unresolved_leads),
            "new_information": False,
        }

    def _build_s3(self, assessment: KPProgressAssessment, frontier_set: Sequence[str]) -> dict:
        # Soft attention to unresolved leads — never name the correct action
        return {
            "attention_leads": list(frontier_set or assessment.unresolved_leads)[:5],
            "forbid_correct_action_name": True,
        }

    def _build_s4(
        self,
        assessment: KPProgressAssessment,
        frontier_set: Sequence[str],
        *,
        restore_location: str = "",
    ) -> dict:
        if not frontier_set:
            raise DirectSolutionS4Error("S4 requires UNRESOLVED_HIGH_VALUE_FRONTIER_SET")
        # Never include forced solution actions
        forbidden_keys = {"force_action", "correct_action", "solution_action", "destroy_object", "win_combat"}
        payload = {
            "mode": "FRONTIER_SET_RECOVERY",
            "frontier_set": list(frontier_set),
            "restore_location": str(restore_location or ""),
            "restore_executable_frontier": True,
            "force_solution": False,
        }
        if any(k in payload for k in forbidden_keys):
            raise DirectSolutionS4Error("DIRECT_SOLUTION_S4_PATH")
        return payload

    def decide(
        self,
        assessment: KPProgressAssessment,
        runtime: InterventionRuntimeState,
        *,
        frontier_set: Sequence[str] = (),
        restore_location: str = "",
        stall_increment: float = 1.0,
        kp_hint_text: str = "",
        kp_hint_grounded_fact_ids: Sequence[str] = (),
    ) -> tuple[InterventionDecision, InterventionRuntimeState]:
        # Validate any KP hint grounding
        if kp_hint_text:
            self.boundary.assert_kp_hint_grounded(
                facts_referenced=list(kp_hint_grounded_fact_ids or []),
            )
            if not kp_hint_grounded_fact_ids:
                raise KnowledgeBoundaryError(
                    "UNGROUNDED_KP_HINT",
                    "KP hint text provided without grounded fact ids",
                )

        new_runtime = InterventionRuntimeState(
            current_s_level=runtime.current_s_level,
            stall_score=runtime.stall_score,
            recovery_grace_remaining=runtime.recovery_grace_remaining,
            last_intervention=runtime.last_intervention,
            history=list(runtime.history),
        )

        # De-escalation paths first
        if assessment.meaningful_progress_this_cycle:
            decision = InterventionDecision(
                s_level=0,
                name=S_LEVEL_NAMES[0],
                payload={},
                deescalated=True,
                reason="meaningful_progress",
            )
            new_runtime.current_s_level = 0
            new_runtime.stall_score = 0.0
            new_runtime.recovery_grace_remaining = 0
            new_runtime.last_intervention = decision.to_dict()
            new_runtime.history.append(decision.to_dict())
            return decision, new_runtime

        # S3 successful reorientation → S0 or S1
        if (
            runtime.current_s_level == 3
            and (assessment.testing_valid_hypothesis or assessment.exploring_valid_alternative)
            and not assessment.merely_repeating
        ):
            target = 0 if assessment.exploring_valid_alternative else 1
            decision = InterventionDecision(
                s_level=target,
                name=S_LEVEL_NAMES[target],
                payload=self._build_s1(assessment) if target == 1 else {},
                deescalated=True,
                reason="s3_successful_reorientation",
            )
            new_runtime.current_s_level = target
            new_runtime.stall_score = max(0.0, new_runtime.stall_score - 2.0)
            new_runtime.last_intervention = decision.to_dict()
            new_runtime.history.append(decision.to_dict())
            return decision, new_runtime

        # Suspend escalation on new rational hypothesis / valid alternative
        suspend = assessment.testing_valid_hypothesis or assessment.exploring_valid_alternative
        if suspend:
            decision = InterventionDecision(
                s_level=new_runtime.current_s_level,
                name=S_LEVEL_NAMES.get(new_runtime.current_s_level, "NONE"),
                payload={},
                reason="escalation_suspended_rational_exploration",
            )
            new_runtime.last_intervention = decision.to_dict()
            return decision, new_runtime

        # Recovery grace after S4
        if new_runtime.recovery_grace_remaining > 0:
            new_runtime.recovery_grace_remaining -= 1
            decision = InterventionDecision(
                s_level=0,
                name=S_LEVEL_NAMES[0],
                payload={},
                recovery_grace_active=True,
                reason="recovery_grace_window",
            )
            new_runtime.current_s_level = 0
            new_runtime.last_intervention = decision.to_dict()
            new_runtime.history.append(decision.to_dict())
            return decision, new_runtime

        # Accrue stall
        if assessment.merely_repeating or assessment.intervention_necessary:
            new_runtime.stall_score += float(stall_increment)
        elif assessment.current_progress_trend == "stalled":
            new_runtime.stall_score += float(stall_increment) * 0.5

        level = 0
        if new_runtime.stall_score >= self.s4_threshold:
            level = 4
        elif new_runtime.stall_score >= self.s3_threshold:
            level = 3
        elif new_runtime.stall_score >= self.s2_threshold:
            level = 2
        elif new_runtime.stall_score >= self.s1_threshold:
            level = 1

        # Prefer least intrusive when assessment says so
        if assessment.intervention_necessary and level < assessment.least_intrusive_level:
            level = assessment.least_intrusive_level

        payload: dict = {}
        if level == 1:
            payload = self._build_s1(assessment)
        elif level == 2:
            payload = self._build_s2(assessment)
        elif level == 3:
            payload = self._build_s3(assessment, frontier_set)
        elif level == 4:
            payload = self._build_s4(assessment, frontier_set, restore_location=restore_location)
            # After S4 decision, prepare grace for next cycles
            new_runtime.recovery_grace_remaining = self.recovery_grace_cycles
            new_runtime.stall_score = 0.0

        decision = InterventionDecision(
            s_level=level,
            name=S_LEVEL_NAMES[level],
            payload=payload,
            reason="stall_escalation" if level else "none",
        )
        # S4 recovery completes → next evaluate will de-escalate via grace then S0
        if level == 4:
            # Mark that recovery restores freedom; immediate level stays 4 this cycle only
            pass

        new_runtime.current_s_level = level
        new_runtime.last_intervention = decision.to_dict()
        new_runtime.history.append(decision.to_dict())
        return decision, new_runtime

    def complete_s4_recovery(self, runtime: InterventionRuntimeState) -> InterventionRuntimeState:
        """Call when frontier set restored — drop to S0 with grace."""
        new_runtime = InterventionRuntimeState(
            current_s_level=0,
            stall_score=0.0,
            recovery_grace_remaining=max(runtime.recovery_grace_remaining, self.recovery_grace_cycles),
            last_intervention={"s_level": 0, "name": "NONE", "reason": "s4_recovery_complete"},
            history=list(runtime.history) + [{"s_level": 0, "name": "NONE", "reason": "s4_recovery_complete"}],
        )
        return new_runtime
