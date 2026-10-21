"""PL reasoning state — PL/PC separated; failure classification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class FailureClass(str, Enum):
    ATTEMPT_FAILED = "ATTEMPT_FAILED"
    METHOD_FAILED = "METHOD_FAILED"
    INSUFFICIENT_SKILL = "INSUFFICIENT_SKILL"
    INSUFFICIENT_TOOL = "INSUFFICIENT_TOOL"
    INSUFFICIENT_INFORMATION = "INSUFFICIENT_INFORMATION"
    BAD_LUCK = "BAD_LUCK"
    TARGET_IMPOSSIBLE = "TARGET_IMPOSSIBLE"
    UNKNOWN_REASON = "UNKNOWN_REASON"


ACTION_MEANING_CLASSES = frozenset({
    "INVESTIGATE",
    "TEST_HYPOTHESIS",
    "PROGRESS_GOAL",
    "RECOVER_RESOURCE",
    "AVOID_RISK",
    "HELP_OTHER_PC",
    "REVISIT_WITH_NEW_INFO",
    "SOCIAL",
    "ROLEPLAY",
    "TRANSITION",
    "LOW_VALUE_REPEAT",
})


@dataclass
class FailedAttempt:
    action: str
    target: str = ""
    failure_class: FailureClass = FailureClass.UNKNOWN_REASON
    count: int = 1
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "target": self.target,
            "failure_class": self.failure_class.value,
            "count": self.count,
            "notes": self.notes,
        }


@dataclass
class PLReasoningState:
    actor_id: str
    known_facts: list = field(default_factory=list)
    unresolved_questions: list = field(default_factory=list)
    current_goals: list = field(default_factory=list)
    current_intent: str = ""
    recent_attempts: list = field(default_factory=list)
    recent_outcomes: list = field(default_factory=list)
    failed_attempts: list = field(default_factory=list)
    hypotheses: list = field(default_factory=list)
    high_value_leads: list = field(default_factory=list)
    low_value_leads: list = field(default_factory=list)
    reasons_to_stay: list = field(default_factory=list)
    reasons_to_leave: list = field(default_factory=list)
    risk_assessment: dict = field(default_factory=dict)
    resource_concerns: list = field(default_factory=list)
    other_pcs_suggestions: list = field(default_factory=list)
    confidence: float = 0.5
    pc_personality: dict = field(default_factory=dict)
    pl_style: list = field(default_factory=list)
    leave_reason: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["failed_attempts"] = [
            x.to_dict() if isinstance(x, FailedAttempt) else dict(x)
            for x in self.failed_attempts
        ]
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PLReasoningState":
        failed = []
        for item in data.get("failed_attempts") or []:
            if isinstance(item, FailedAttempt):
                failed.append(item)
            else:
                fc = item.get("failure_class") or FailureClass.UNKNOWN_REASON
                if not isinstance(fc, FailureClass):
                    fc = FailureClass(str(fc))
                failed.append(
                    FailedAttempt(
                        action=str(item.get("action") or ""),
                        target=str(item.get("target") or ""),
                        failure_class=fc,
                        count=int(item.get("count") or 1),
                        notes=str(item.get("notes") or ""),
                    )
                )
        return cls(
            actor_id=str(data.get("actor_id") or ""),
            known_facts=list(data.get("known_facts") or []),
            unresolved_questions=list(data.get("unresolved_questions") or []),
            current_goals=list(data.get("current_goals") or []),
            current_intent=str(data.get("current_intent") or ""),
            recent_attempts=list(data.get("recent_attempts") or []),
            recent_outcomes=list(data.get("recent_outcomes") or []),
            failed_attempts=failed,
            hypotheses=list(data.get("hypotheses") or []),
            high_value_leads=list(data.get("high_value_leads") or []),
            low_value_leads=list(data.get("low_value_leads") or []),
            reasons_to_stay=list(data.get("reasons_to_stay") or []),
            reasons_to_leave=list(data.get("reasons_to_leave") or []),
            risk_assessment=dict(data.get("risk_assessment") or {}),
            resource_concerns=list(data.get("resource_concerns") or []),
            other_pcs_suggestions=list(data.get("other_pcs_suggestions") or []),
            confidence=float(data.get("confidence") if data.get("confidence") is not None else 0.5),
            pc_personality=dict(data.get("pc_personality") or {}),
            pl_style=list(data.get("pl_style") or []),
            leave_reason=str(data.get("leave_reason") or ""),
        )

    def record_failure(
        self,
        *,
        action: str,
        target: str = "",
        failure_class: FailureClass | str = FailureClass.ATTEMPT_FAILED,
        notes: str = "",
    ) -> FailedAttempt:
        fc = failure_class if isinstance(failure_class, FailureClass) else FailureClass(str(failure_class))
        # Do not jump to TARGET_IMPOSSIBLE on first failure.
        if fc == FailureClass.TARGET_IMPOSSIBLE:
            prior = sum(
                1
                for x in self.failed_attempts
                if str(getattr(x, "action", "") or (x.get("action") if isinstance(x, dict) else "")) == action
                and str(getattr(x, "target", "") or (x.get("target") if isinstance(x, dict) else "")) == target
            )
            if prior < 2:
                fc = FailureClass.ATTEMPT_FAILED
                notes = (notes + " demoted from TARGET_IMPOSSIBLE (insufficient repeats)").strip()
        entry = FailedAttempt(action=action, target=target, failure_class=fc, notes=notes)
        for existing in self.failed_attempts:
            same_action = (
                isinstance(existing, FailedAttempt)
                and existing.action == action
                and existing.target == target
            ) or (
                isinstance(existing, dict)
                and existing.get("action") == action
                and existing.get("target") == target
            )
            if same_action:
                if isinstance(existing, FailedAttempt):
                    existing.count += 1
                    existing.failure_class = fc
                    existing.notes = notes or existing.notes
                    return existing
        self.failed_attempts.append(entry)
        return entry


def classify_failure_from_signals(
    *,
    same_method_count: int = 1,
    skill_gap: bool = False,
    missing_tool: bool = False,
    missing_info: bool = False,
    dice_failed: bool = False,
    strong_impossible_evidence: bool = False,
) -> FailureClass:
    if strong_impossible_evidence and same_method_count >= 3:
        return FailureClass.TARGET_IMPOSSIBLE
    if missing_tool:
        return FailureClass.INSUFFICIENT_TOOL
    if missing_info:
        return FailureClass.INSUFFICIENT_INFORMATION
    if skill_gap:
        return FailureClass.INSUFFICIENT_SKILL
    if dice_failed:
        return FailureClass.BAD_LUCK
    if same_method_count >= 2:
        return FailureClass.METHOD_FAILED
    return FailureClass.ATTEMPT_FAILED
