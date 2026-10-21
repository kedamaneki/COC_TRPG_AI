"""Hypothesis tracking — never mixed with FACT."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class HypothesisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPPORTED = "SUPPORTED"
    WEAKENED = "WEAKENED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


@dataclass
class Hypothesis:
    hypothesis_id: str
    statement: str
    supporting_fact_ids: list = field(default_factory=list)
    contradicting_fact_ids: list = field(default_factory=list)
    confidence: float = 0.5
    status: HypothesisStatus = HypothesisStatus.ACTIVE
    owner: str = ""

    def to_dict(self) -> dict:
        data = asdict(self)
        data["status"] = self.status.value if isinstance(self.status, HypothesisStatus) else str(self.status)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Hypothesis":
        status = data.get("status") or HypothesisStatus.ACTIVE
        if not isinstance(status, HypothesisStatus):
            status = HypothesisStatus(str(status))
        return cls(
            hypothesis_id=str(data.get("hypothesis_id") or ""),
            statement=str(data.get("statement") or ""),
            supporting_fact_ids=[str(x) for x in (data.get("supporting_fact_ids") or [])],
            contradicting_fact_ids=[str(x) for x in (data.get("contradicting_fact_ids") or [])],
            confidence=float(data.get("confidence") if data.get("confidence") is not None else 0.5),
            status=status,
            owner=str(data.get("owner") or ""),
        )


class HypothesisTracker:
    def __init__(self):
        self._items: dict[str, Hypothesis] = {}

    def upsert(self, hyp: Hypothesis | Mapping[str, Any]) -> Hypothesis:
        obj = hyp if isinstance(hyp, Hypothesis) else Hypothesis.from_dict(hyp)
        if not obj.hypothesis_id:
            raise ValueError("hypothesis_id required")
        self._items[obj.hypothesis_id] = obj
        return obj

    def get(self, hypothesis_id: str) -> Optional[Hypothesis]:
        return self._items.get(str(hypothesis_id))

    def all(self) -> list[Hypothesis]:
        return list(self._items.values())

    def apply_outcome(
        self,
        hypothesis_id: str,
        outcome: str,
        *,
        fact_id: str = "",
        delta: float = 0.1,
    ) -> Hypothesis:
        """outcome in {support, contradict, unchanged, unknown}."""
        hyp = self._items[str(hypothesis_id)]
        kind = str(outcome or "unknown").lower()
        if kind == "support":
            if fact_id and fact_id not in hyp.supporting_fact_ids:
                hyp.supporting_fact_ids.append(fact_id)
            hyp.confidence = min(1.0, hyp.confidence + abs(delta))
            hyp.status = HypothesisStatus.SUPPORTED if hyp.confidence >= 0.7 else HypothesisStatus.ACTIVE
        elif kind == "contradict":
            if fact_id and fact_id not in hyp.contradicting_fact_ids:
                hyp.contradicting_fact_ids.append(fact_id)
            hyp.confidence = max(0.0, hyp.confidence - abs(delta))
            if hyp.confidence <= 0.2:
                hyp.status = HypothesisStatus.REJECTED
            else:
                hyp.status = HypothesisStatus.WEAKENED
        elif kind == "unchanged":
            pass
        else:  # unknown
            hyp.confidence = max(0.0, hyp.confidence - abs(delta) * 0.25)
        return hyp

    def to_dict(self) -> dict:
        return {k: v.to_dict() for k, v in self._items.items()}
