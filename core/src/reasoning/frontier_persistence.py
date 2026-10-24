"""V18 Frontier Persistence + Critical Ignore Guard (no mandatory selection)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

ALLOWED_WHY_NOT_SELECTED = frozenset({
    "risk_too_high",
    "tool_missing",
    "location_unavailable",
    "other_explicit_goal_prioritized",
    "party_disagreement",
    "resource_recovery",
    "new_evidence",
    "method_exhausted",
    "info_required",
    "action_blocked",
})

FRONTIER_ACTION_UNAVAIL_REASONS = frozenset({
    "NO_ACTION_GENERATED",
    "ACTION_BLOCKED",
    "ACTION_EXHAUSTED",
    "LOCATION_MISMATCH",
    "TOOL_REQUIRED",
    "INFO_REQUIRED",
})


@dataclass
class PersistentFrontier:
    frontier_id: str
    goal_ids: list = field(default_factory=list)
    lead_ids: list = field(default_factory=list)
    location: str = ""
    available_actions: list = field(default_factory=list)
    expected_state_effects: list = field(default_factory=list)
    reachable: bool = True
    executable: bool = True
    status: str = "ACTIVE"  # ACTIVE | DEFERRED | EXHAUSTED | INVALIDATED | RESOLVED
    persistence_score: float = 0.0
    attempt_count: int = 0
    last_attempt_result: str = ""
    unresolved_importance: float = 0.0
    reason_to_leave: str = ""
    return_condition: str = ""
    last_selected_cycle: int | None = None
    why_not_selected: str = ""
    action_unavailable_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PersistentFrontier":
        return cls(
            frontier_id=str(data.get("frontier_id") or ""),
            goal_ids=[str(x) for x in (data.get("goal_ids") or [])],
            lead_ids=[str(x) for x in (data.get("lead_ids") or [])],
            location=str(data.get("location") or ""),
            available_actions=list(data.get("available_actions") or []),
            expected_state_effects=list(data.get("expected_state_effects") or []),
            reachable=bool(data.get("reachable", True)),
            executable=bool(data.get("executable", True)),
            status=str(data.get("status") or "ACTIVE"),
            persistence_score=float(data.get("persistence_score") or 0.0),
            attempt_count=int(data.get("attempt_count") or 0),
            last_attempt_result=str(data.get("last_attempt_result") or ""),
            unresolved_importance=float(data.get("unresolved_importance") or 0.0),
            reason_to_leave=str(data.get("reason_to_leave") or ""),
            return_condition=str(data.get("return_condition") or ""),
            last_selected_cycle=data.get("last_selected_cycle"),
            why_not_selected=str(data.get("why_not_selected") or ""),
            action_unavailable_reason=str(data.get("action_unavailable_reason") or ""),
        )


@dataclass
class FrontierPersistenceStore:
    frontiers: dict[str, PersistentFrontier] = field(default_factory=dict)
    frontier_ignore_streak: int = 0
    critical_frontier_silent_drop_count: int = 0
    critical_frontier_ignore_count: int = 0
    critical_frontier_present_count: int = 0
    return_pressure: float = 0.0

    def to_dict(self) -> dict:
        return {
            "frontiers": {k: v.to_dict() for k, v in self.frontiers.items()},
            "frontier_ignore_streak": self.frontier_ignore_streak,
            "critical_frontier_silent_drop_count": self.critical_frontier_silent_drop_count,
            "critical_frontier_ignore_count": self.critical_frontier_ignore_count,
            "critical_frontier_present_count": self.critical_frontier_present_count,
            "return_pressure": self.return_pressure,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "FrontierPersistenceStore":
        data = data or {}
        store = cls(
            frontier_ignore_streak=int(data.get("frontier_ignore_streak") or 0),
            critical_frontier_silent_drop_count=int(data.get("critical_frontier_silent_drop_count") or 0),
            critical_frontier_ignore_count=int(data.get("critical_frontier_ignore_count") or 0),
            critical_frontier_present_count=int(data.get("critical_frontier_present_count") or 0),
            return_pressure=float(data.get("return_pressure") or 0.0),
        )
        for k, v in (data.get("frontiers") or {}).items():
            if isinstance(v, Mapping):
                store.frontiers[str(k)] = PersistentFrontier.from_dict(v)
        return store


def upsert_frontier(store: FrontierPersistenceStore, frontier: PersistentFrontier | Mapping[str, Any]) -> PersistentFrontier:
    obj = frontier if isinstance(frontier, PersistentFrontier) else PersistentFrontier.from_dict(frontier)
    if not obj.frontier_id:
        raise ValueError("frontier_id required")
    store.frontiers[obj.frontier_id] = obj
    return obj


def defer_frontier(
    store: FrontierPersistenceStore,
    frontier_id: str,
    *,
    reason_to_leave: str,
    return_condition: str,
) -> PersistentFrontier:
    fr = store.frontiers.get(str(frontier_id))
    if fr is None:
        raise KeyError(f"unknown frontier: {frontier_id}")
    # Never silent-drop important unresolved — defer instead
    fr.status = "DEFERRED"
    fr.reason_to_leave = str(reason_to_leave or "temporary_leave")
    fr.return_condition = str(return_condition or "goal_stall_increased")
    store.frontiers[fr.frontier_id] = fr
    return fr


def mark_frontier_selected(store: FrontierPersistenceStore, frontier_id: str, *, cycle: int | None = None) -> None:
    fr = store.frontiers.get(str(frontier_id))
    if not fr:
        return
    fr.status = "ACTIVE"
    fr.attempt_count = int(fr.attempt_count) + 1
    fr.last_selected_cycle = cycle
    fr.why_not_selected = ""
    store.frontier_ignore_streak = 0
    store.frontiers[fr.frontier_id] = fr


def record_why_not_selected(
    store: FrontierPersistenceStore,
    frontier_id: str,
    why: str,
    *,
    important: bool = True,
) -> None:
    fr = store.frontiers.get(str(frontier_id))
    if fr is None:
        return
    reason = str(why or "")
    fr.why_not_selected = reason
    store.frontiers[fr.frontier_id] = fr
    if important:
        store.critical_frontier_present_count += 1
        if reason and reason in ALLOWED_WHY_NOT_SELECTED:
            store.frontier_ignore_streak = 0
        else:
            store.frontier_ignore_streak += 1
            store.critical_frontier_ignore_count += 1


def set_action_unavailable(
    store: FrontierPersistenceStore,
    frontier_id: str,
    reason: str,
) -> PersistentFrontier:
    fr = store.frontiers.get(str(frontier_id))
    if fr is None:
        raise KeyError(f"unknown frontier: {frontier_id}")
    r = str(reason or "NO_ACTION_GENERATED")
    if r not in FRONTIER_ACTION_UNAVAIL_REASONS:
        r = "NO_ACTION_GENERATED"
    fr.action_unavailable_reason = r
    fr.available_actions = list(fr.available_actions or [])
    # Keep frontier visible — do not delete
    store.frontiers[fr.frontier_id] = fr
    return fr


def apply_return_pressure(
    store: FrontierPersistenceStore,
    *,
    goal_stall_streak: int = 0,
    leave_reason_resolved: bool = False,
) -> float:
    deferred = [f for f in store.frontiers.values() if f.status == "DEFERRED"]
    pressure = 0.0
    if deferred:
        pressure += 0.5 * len(deferred)
    if leave_reason_resolved:
        pressure += 1.0
    if goal_stall_streak >= 3:
        pressure += min(2.0, 0.25 * float(goal_stall_streak))
    store.return_pressure = pressure
    return pressure


def should_remind_ignored_frontier(store: FrontierPersistenceStore, *, threshold: int = 3) -> bool:
    return int(store.frontier_ignore_streak) >= int(threshold)
