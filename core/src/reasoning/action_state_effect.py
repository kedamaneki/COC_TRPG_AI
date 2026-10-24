"""V18 Action → Expected/Observed State Effect contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

EFFECT_EXPECTED = "EXPECTED_EFFECT_ACHIEVED"
EFFECT_PARTIAL = "PARTIAL_EFFECT"
EFFECT_NONE = "NO_EFFECT"
EFFECT_UNEXPECTED = "UNEXPECTED_EFFECT"
EFFECT_FAILED_BEFORE = "ACTION_FAILED_BEFORE_EFFECT"

METHOD_RECONSIDERATIONS = frozenset({
    "method_exhausted",
    "different_method",
    "different_pc",
    "tool_needed",
    "info_needed",
})


@dataclass
class ExpectedStateEffect:
    effect_id: str = ""
    description: str = ""
    target_state_keys: list = field(default_factory=list)
    success_not_guaranteed: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ObservedStateEffect:
    effect_id: str | None = None
    changed_keys: list = field(default_factory=list)
    classification: str = EFFECT_NONE
    lead_ids: list = field(default_factory=list)
    goal_ids: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def classify_observed_effect(
    *,
    expected: ExpectedStateEffect | Mapping[str, Any] | None,
    changed_keys: Sequence[str] = (),
    action_failed: bool = False,
) -> ObservedStateEffect:
    if action_failed:
        return ObservedStateEffect(classification=EFFECT_FAILED_BEFORE, changed_keys=list(changed_keys))

    exp = expected
    if isinstance(expected, Mapping):
        exp = ExpectedStateEffect(
            effect_id=str(expected.get("effect_id") or ""),
            description=str(expected.get("description") or ""),
            target_state_keys=[str(x) for x in (expected.get("target_state_keys") or [])],
            success_not_guaranteed=bool(expected.get("success_not_guaranteed", True)),
        )
    changed = [str(x) for x in changed_keys]
    if exp is None or not getattr(exp, "target_state_keys", None):
        if changed:
            return ObservedStateEffect(
                effect_id=getattr(exp, "effect_id", None) if exp else None,
                changed_keys=changed,
                classification=EFFECT_UNEXPECTED,
            )
        return ObservedStateEffect(classification=EFFECT_NONE)

    targets = {str(x) for x in exp.target_state_keys}
    hit = targets & set(changed)
    if not changed or not hit:
        return ObservedStateEffect(
            effect_id=exp.effect_id or None,
            changed_keys=changed,
            classification=EFFECT_NONE,
        )
    if hit == targets:
        return ObservedStateEffect(
            effect_id=exp.effect_id or None,
            changed_keys=changed,
            classification=EFFECT_EXPECTED,
        )
    if hit:
        return ObservedStateEffect(
            effect_id=exp.effect_id or None,
            changed_keys=changed,
            classification=EFFECT_PARTIAL,
        )
    return ObservedStateEffect(
        effect_id=exp.effect_id or None,
        changed_keys=changed,
        classification=EFFECT_UNEXPECTED,
    )


@dataclass
class MethodAttemptTracker:
    """Track repeated NO_EFFECT for same frontier/method."""

    key_to_no_effect_streak: dict = field(default_factory=dict)

    def record(self, frontier_id: str, method: str, classification: str) -> Optional[str]:
        key = f"{frontier_id}|{method}"
        if classification == EFFECT_NONE:
            self.key_to_no_effect_streak[key] = int(self.key_to_no_effect_streak.get(key) or 0) + 1
            if self.key_to_no_effect_streak[key] >= 2:
                return "method_exhausted"
            return None
        self.key_to_no_effect_streak[key] = 0
        return None

    def to_dict(self) -> dict:
        return {"key_to_no_effect_streak": dict(self.key_to_no_effect_streak)}
