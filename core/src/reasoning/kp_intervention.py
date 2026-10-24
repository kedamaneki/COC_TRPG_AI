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
    # V18 dual stall mirrors (activity vs goal convergence)
    activity_stall_streak: int = 0
    goal_convergence_stall_streak: int = 0
    frontier_ignore_streak: int = 0
    local_optimum: bool = False

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
            activity_stall_streak=int(
                getattr(assessment, "activity_stall", None)
                if getattr(assessment, "activity_stall", None) is not None
                else runtime.activity_stall_streak
            ),
            goal_convergence_stall_streak=int(
                getattr(assessment, "goal_convergence_stall", None)
                if getattr(assessment, "goal_convergence_stall", None) is not None
                else runtime.goal_convergence_stall_streak
            ),
            frontier_ignore_streak=int(
                getattr(assessment, "frontier_ignore_streak", None)
                if getattr(assessment, "frontier_ignore_streak", None) is not None
                else runtime.frontier_ignore_streak
            ),
            local_optimum=bool(
                getattr(assessment, "local_optimum", False) or runtime.local_optimum
            ),
        )
        # Prefer assessment dual-stall fields when provided
        if hasattr(assessment, "activity_stall"):
            new_runtime.activity_stall_streak = int(assessment.activity_stall or 0)
        if hasattr(assessment, "goal_convergence_stall"):
            new_runtime.goal_convergence_stall_streak = int(assessment.goal_convergence_stall or 0)
        if hasattr(assessment, "frontier_ignore_streak"):
            new_runtime.frontier_ignore_streak = int(assessment.frontier_ignore_streak or 0)
        if hasattr(assessment, "local_optimum"):
            new_runtime.local_optimum = bool(assessment.local_optimum)

        gd = bool(getattr(assessment, "goal_directed_progress_this_cycle", False))
        lateral = bool(getattr(assessment, "lateral_exploration_progress_this_cycle", False))
        terminal = bool(getattr(assessment, "terminal_progress_this_cycle", False))
        unresolved = list(assessment.unresolved_leads or [])

        # De-escalation: goal-directed / terminal → full reset (legacy + V18)
        if gd or terminal:
            decision = InterventionDecision(
                s_level=0,
                name=S_LEVEL_NAMES[0],
                payload={},
                deescalated=True,
                reason="goal_directed_progress",
            )
            new_runtime.current_s_level = 0
            new_runtime.stall_score = 0.0
            new_runtime.activity_stall_streak = 0
            new_runtime.goal_convergence_stall_streak = 0
            new_runtime.local_optimum = False
            new_runtime.recovery_grace_remaining = 0
            new_runtime.last_intervention = decision.to_dict()
            new_runtime.history.append(decision.to_dict())
            return decision, new_runtime

        # Lateral meaningful progress: ACTIVITY stall relief only; goal stall continues
        if lateral and unresolved:
            new_runtime.activity_stall_streak = 0
            new_runtime.goal_convergence_stall_streak = max(
                1, int(new_runtime.goal_convergence_stall_streak) + 1
            )
            # Soften activity-driven S but do not wipe goal-convergence pressure
            if new_runtime.current_s_level <= 1 and not new_runtime.local_optimum:
                new_runtime.current_s_level = 0
            # Keep a floor on stall_score so goal-convergence can still escalate gently
            new_runtime.stall_score = max(float(new_runtime.stall_score) * 0.5, 0.5)
            decision = InterventionDecision(
                s_level=new_runtime.current_s_level,
                name=S_LEVEL_NAMES.get(new_runtime.current_s_level, "NONE"),
                payload=self._build_s1(assessment) if new_runtime.goal_convergence_stall_streak >= 3 else {},
                deescalated=new_runtime.current_s_level == 0,
                reason="lateral_progress_activity_reset_goal_stall_continues",
            )
            new_runtime.last_intervention = decision.to_dict()
            new_runtime.history.append(decision.to_dict())
            return decision, new_runtime

        # Legacy full reset: meaningful with no unresolved goal/lead pressure
        if assessment.meaningful_progress_this_cycle and not unresolved:
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

        # Meaningful without explicit lateral/gd flags but with unresolved leads:
        # treat as lateral (V18) — do not full-reset goal stall
        if assessment.meaningful_progress_this_cycle and unresolved and not gd:
            new_runtime.activity_stall_streak = 0
            new_runtime.goal_convergence_stall_streak = max(
                1, int(new_runtime.goal_convergence_stall_streak) + 1
            )
            new_runtime.stall_score = max(float(new_runtime.stall_score) * 0.5, 0.5)
            if new_runtime.current_s_level <= 1:
                new_runtime.current_s_level = 0
            decision = InterventionDecision(
                s_level=new_runtime.current_s_level,
                name=S_LEVEL_NAMES.get(new_runtime.current_s_level, "NONE"),
                payload={},
                deescalated=True,
                reason="lateral_progress_activity_reset_goal_stall_continues",
            )
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

        # V18: never jump to S4 solely from goal_convergence_stall / local_optimum.
        # Soft ladder: S1 self-review → S2 lead reminder → S3 frontier persistence nudge → S4 set recovery.
        if new_runtime.local_optimum and level >= 4:
            level = max(1, min(level, 2))
        if (
            int(new_runtime.goal_convergence_stall_streak) > 0
            and not assessment.merely_repeating
            and level >= 4
            and int(new_runtime.activity_stall_streak) < 3
        ):
            # Goal stall alone → cap at S3 persistence nudge (not direct solution S4)
            level = min(level, 3)
        if int(new_runtime.frontier_ignore_streak) >= 3 and level < 2:
            level = max(level, 1)
            if int(new_runtime.frontier_ignore_streak) >= 5:
                level = max(level, 2)

        payload: dict = {}
        if level == 1:
            payload = self._build_s1(assessment)
        elif level == 2:
            payload = self._build_s2(assessment)
        elif level == 3:
            payload = self._build_s3(assessment, frontier_set)
            payload["mode"] = payload.get("mode") or "FRONTIER_PERSISTENCE_NUDGE"
            payload["forbid_correct_action_name"] = True
            payload["mandatory_top_frontier"] = False
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
