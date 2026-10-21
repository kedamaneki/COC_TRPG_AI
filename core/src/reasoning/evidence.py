"""Structured reasoning evidence — no full chain-of-thought."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence


@dataclass
class ReasoningEvidence:
    reasoning_id: str
    actor_id: str
    cycle: Any = None
    turn: Any = None
    known_fact_ids: list = field(default_factory=list)
    goal_ids: list = field(default_factory=list)
    lead_ids: list = field(default_factory=list)
    hypothesis_ids: list = field(default_factory=list)
    considered_actions: list = field(default_factory=list)
    selected_action: Optional[dict] = None
    selection_reason: str = ""
    confidence: float = 0.0
    reasoning_mode: str = "PL"
    fallback_used: bool = False
    extras: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        # Never persist free-form CoT blobs if accidentally placed in extras.
        extras = dict(data.get("extras") or {})
        extras.pop("chain_of_thought", None)
        extras.pop("raw_llm_thought", None)
        data["extras"] = extras
        return data


def build_reasoning_evidence(
    *,
    actor_id: str,
    cycle: Any = None,
    turn: Any = None,
    known_fact_ids: Optional[Sequence[str]] = None,
    goal_ids: Optional[Sequence[str]] = None,
    lead_ids: Optional[Sequence[str]] = None,
    hypothesis_ids: Optional[Sequence[str]] = None,
    considered_actions: Optional[Sequence[Mapping[str, Any]]] = None,
    selected_action: Optional[Mapping[str, Any]] = None,
    selection_reason: str = "",
    confidence: float = 0.0,
    reasoning_mode: str = "PL",
    fallback_used: bool = False,
    extras: Optional[Mapping[str, Any]] = None,
    reasoning_id: Optional[str] = None,
) -> ReasoningEvidence:
    if not str(selection_reason or "").strip() and not fallback_used:
        # Callers should treat missing reason as UNEXPLAINED_ACTION; we still build
        # the record so tests can assert the gate.
        pass
    return ReasoningEvidence(
        reasoning_id=str(reasoning_id or f"plr_{uuid.uuid4().hex[:12]}"),
        actor_id=str(actor_id or ""),
        cycle=cycle,
        turn=turn,
        known_fact_ids=[str(x) for x in (known_fact_ids or [])],
        goal_ids=[str(x) for x in (goal_ids or [])],
        lead_ids=[str(x) for x in (lead_ids or [])],
        hypothesis_ids=[str(x) for x in (hypothesis_ids or [])],
        considered_actions=[dict(x) for x in (considered_actions or [])],
        selected_action=dict(selected_action) if selected_action else None,
        selection_reason=str(selection_reason or ""),
        confidence=float(confidence or 0.0),
        reasoning_mode=str(reasoning_mode or "PL"),
        fallback_used=bool(fallback_used),
        extras=dict(extras or {}),
    )
