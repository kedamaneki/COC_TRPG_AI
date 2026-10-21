"""Lead / high-value frontier tracking without hidden solution scores."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence

from .knowledge_boundary import ReasoningKnowledgeBoundary


class LeadStatus(str, Enum):
    NEW = "NEW"
    ACTIVE = "ACTIVE"
    DEFERRED = "DEFERRED"
    RESOLVED = "RESOLVED"
    EXHAUSTED = "EXHAUSTED"
    INVALIDATED = "INVALIDATED"


ALLOWED_VALUE_REASONS = frozenset({
    "known_unresolved_lead",
    "current_goal_relevance",
    "source_backed_observed_clue",
    "recent_observation",
    "unresolved_state",
    "new_action_possibility",
    "information_gain_potential",
    "risk_relevance",
    "party_stated_interest",
    "goal_relevance",
    "available_actions_remain",
})


@dataclass
class Lead:
    lead_id: str
    source_fact_ids: list = field(default_factory=list)
    goal_ids: list = field(default_factory=list)
    status: LeadStatus = LeadStatus.NEW
    value_reasons: list = field(default_factory=list)
    visible_to_party: bool = True
    unresolved: bool = True
    available_action_count: int = 0
    last_relevant_event: Any = None
    high_value: bool = False

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, LeadStatus) else str(self.status)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Lead":
        status = data.get("status") or LeadStatus.NEW
        if not isinstance(status, LeadStatus):
            status = LeadStatus(str(status))
        return cls(
            lead_id=str(data.get("lead_id") or ""),
            source_fact_ids=[str(x) for x in (data.get("source_fact_ids") or [])],
            goal_ids=[str(x) for x in (data.get("goal_ids") or [])],
            status=status,
            value_reasons=[str(x) for x in (data.get("value_reasons") or [])],
            visible_to_party=bool(data.get("visible_to_party", True)),
            unresolved=bool(data.get("unresolved", True)),
            available_action_count=int(data.get("available_action_count") or 0),
            last_relevant_event=data.get("last_relevant_event"),
            high_value=bool(data.get("high_value", False)),
        )


class LeadTracker:
    def __init__(self, boundary: Optional[ReasoningKnowledgeBoundary] = None):
        self.boundary = boundary or ReasoningKnowledgeBoundary()
        self._leads: dict[str, Lead] = {}

    def upsert(self, lead: Lead | Mapping[str, Any]) -> Lead:
        obj = lead if isinstance(lead, Lead) else Lead.from_dict(lead)
        if not obj.lead_id:
            raise ValueError("lead_id required")
        self.boundary.assert_frontier_value_visible(obj.value_reasons)
        unknown = [r for r in obj.value_reasons if r not in ALLOWED_VALUE_REASONS]
        # Allow only designed tokens for high-value promotion.
        if obj.high_value and unknown:
            raise ValueError(f"unknown value_reasons for high-value lead: {unknown}")
        if obj.high_value:
            self._assert_high_value_eligible(obj)
        self._leads[obj.lead_id] = obj
        return obj

    def _assert_high_value_eligible(self, lead: Lead) -> None:
        if not lead.visible_to_party or not lead.unresolved:
            raise ValueError("high-value lead must be visible and unresolved")
        if not lead.value_reasons:
            raise ValueError("high-value lead requires value_reasons")
        self.boundary.assert_frontier_value_visible(lead.value_reasons)

    def get(self, lead_id: str) -> Optional[Lead]:
        return self._leads.get(str(lead_id))

    def all(self) -> list[Lead]:
        return list(self._leads.values())

    def set_status(self, lead_id: str, status: LeadStatus | str) -> Lead:
        lead = self._leads[str(lead_id)]
        lead.status = status if isinstance(status, LeadStatus) else LeadStatus(str(status))
        if lead.status in {LeadStatus.RESOLVED, LeadStatus.EXHAUSTED, LeadStatus.INVALIDATED}:
            lead.unresolved = False
            lead.high_value = False
        return lead

    def defer(self, lead_id: str, *, leave_reason: str) -> Lead:
        if not str(leave_reason or "").strip():
            raise ValueError("leave_reason required when deferring a lead")
        lead = self.set_status(lead_id, LeadStatus.DEFERRED)
        lead.last_relevant_event = {"leave_reason": leave_reason}
        # Deferred high-value leads remain unresolved for recovery.
        lead.unresolved = True
        return lead

    def unresolved_high_value_frontier_set(self) -> list[dict]:
        out = []
        for lead in self._leads.values():
            if not (lead.high_value and lead.unresolved and lead.visible_to_party):
                continue
            if lead.status in {LeadStatus.RESOLVED, LeadStatus.INVALIDATED, LeadStatus.EXHAUSTED}:
                continue
            self.boundary.assert_frontier_value_visible(lead.value_reasons)
            out.append({
                "frontier_id": lead.lead_id,
                "known_fact_ids": list(lead.source_fact_ids),
                "goal_ids": list(lead.goal_ids),
                "lead_ids": [lead.lead_id],
                "value_reasons": list(lead.value_reasons),
                "visible_to_party": True,
                "unresolved": True,
                "available_action_count": int(lead.available_action_count),
            })
        return out

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self._leads.items()}
