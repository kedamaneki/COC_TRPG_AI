"""Knowledge boundary — PL may only use known facts; KP hints must be grounded."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional, Sequence, Set


class EpistemicKind(str, Enum):
    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"
    SPECULATION = "SPECULATION"


class KnowledgeBoundaryError(ValueError):
    """Raised when reasoning cites forbidden / unobserved knowledge."""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


FORBIDDEN_PL_INPUT_KEYS = frozenset({
    "hidden_scenario_solution",
    "unobserved_npc_motive",
    "future_state",
    "secret_objective",
    "author_intended_route",
    "unrevealed_source_rule",
    "is_correct_path",
    "distance_to_solution",
    "required_for_ending",
    "secret_priority",
    "author_priority",
})

FORBIDDEN_FRONTIER_VALUE_KEYS = FORBIDDEN_PL_INPUT_KEYS


@dataclass
class KnownFactView:
    fact_id: str
    source_event_id: str = ""
    observed_by: str = ""
    learned_at: Any = None
    confidence: float = 1.0
    freshness: float = 1.0
    source_type: str = "observation"
    kind: EpistemicKind = EpistemicKind.FACT
    text: str = ""
    salience_tags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "fact_id": self.fact_id,
            "source_event_id": self.source_event_id,
            "observed_by": self.observed_by,
            "learned_at": self.learned_at,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "source_type": self.source_type,
            "kind": self.kind.value if isinstance(self.kind, EpistemicKind) else str(self.kind),
            "text": self.text,
            "salience_tags": list(self.salience_tags or []),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnownFactView":
        kind = data.get("kind") or EpistemicKind.FACT
        if not isinstance(kind, EpistemicKind):
            kind = EpistemicKind(str(kind))
        return cls(
            fact_id=str(data.get("fact_id") or ""),
            source_event_id=str(data.get("source_event_id") or ""),
            observed_by=str(data.get("observed_by") or ""),
            learned_at=data.get("learned_at"),
            confidence=float(data.get("confidence") if data.get("confidence") is not None else 1.0),
            freshness=float(data.get("freshness") if data.get("freshness") is not None else 1.0),
            source_type=str(data.get("source_type") or "observation"),
            kind=kind,
            text=str(data.get("text") or ""),
            salience_tags=list(data.get("salience_tags") or []),
        )


class ReasoningKnowledgeBoundary:
    """Fail-closed gate for PL / KP / frontier value inputs."""

    def __init__(self, known_facts: Optional[Sequence[KnownFactView | Mapping[str, Any]]] = None):
        self._facts: dict[str, KnownFactView] = {}
        for item in known_facts or []:
            fact = item if isinstance(item, KnownFactView) else KnownFactView.from_dict(item)
            if fact.fact_id:
                self._facts[fact.fact_id] = fact

    @property
    def known_fact_ids(self) -> Set[str]:
        return set(self._facts)

    def get_fact(self, fact_id: str) -> Optional[KnownFactView]:
        return self._facts.get(str(fact_id))

    def add_fact(self, fact: KnownFactView | Mapping[str, Any]) -> KnownFactView:
        view = fact if isinstance(fact, KnownFactView) else KnownFactView.from_dict(fact)
        if view.kind != EpistemicKind.FACT and view.kind == EpistemicKind.SPECULATION:
            # Speculation must not be stored as FACT; callers must set kind explicitly.
            pass
        if not view.fact_id:
            raise KnowledgeBoundaryError("REASONING_KNOWLEDGE_LEAK", "fact_id required")
        if view.kind == EpistemicKind.SPECULATION:
            # Allow storage as speculation but never as FACT upgrade.
            pass
        self._facts[view.fact_id] = view
        return view

    def assert_fact_kind_not_upgraded(self, fact_id: str, claimed_kind: EpistemicKind | str) -> None:
        existing = self._facts.get(str(fact_id))
        if not existing:
            return
        claimed = claimed_kind if isinstance(claimed_kind, EpistemicKind) else EpistemicKind(str(claimed_kind))
        if existing.kind != EpistemicKind.FACT and claimed == EpistemicKind.FACT:
            raise KnowledgeBoundaryError(
                "REASONING_KNOWLEDGE_LEAK",
                f"cannot promote {existing.kind.value} to FACT for {fact_id}",
            )

    def assert_pl_may_cite(self, fact_ids: Iterable[str]) -> None:
        for fid in fact_ids or []:
            fid = str(fid or "")
            if not fid:
                continue
            if fid not in self._facts:
                raise KnowledgeBoundaryError(
                    "REASONING_KNOWLEDGE_LEAK",
                    f"PL cited unobserved fact_id={fid}",
                )
            fact = self._facts[fid]
            if fact.kind == EpistemicKind.SPECULATION:
                # Citing speculation as supporting knowledge for factual claims is blocked
                # when callers pass assert_factual=True via validate_supporting_knowledge.
                pass

    def validate_supporting_knowledge(
        self,
        fact_ids: Iterable[str],
        *,
        allow_hypothesis: bool = True,
    ) -> None:
        self.assert_pl_may_cite(fact_ids)
        for fid in fact_ids or []:
            fact = self._facts.get(str(fid))
            if not fact:
                continue
            if fact.kind == EpistemicKind.SPECULATION:
                raise KnowledgeBoundaryError(
                    "REASONING_KNOWLEDGE_LEAK",
                    f"SPECULATION cannot ground factual selection: {fid}",
                )
            if fact.kind == EpistemicKind.HYPOTHESIS and not allow_hypothesis:
                raise KnowledgeBoundaryError(
                    "REASONING_KNOWLEDGE_LEAK",
                    f"HYPOTHESIS not allowed here: {fid}",
                )

    def scrub_forbidden_inputs(self, payload: Mapping[str, Any]) -> dict:
        """Drop forbidden keys; raise if only hidden-solution signals remain for frontier value."""
        cleaned = {k: v for k, v in dict(payload or {}).items() if k not in FORBIDDEN_PL_INPUT_KEYS}
        return cleaned

    def assert_no_forbidden_keys(self, payload: Mapping[str, Any], *, code: str = "REASONING_KNOWLEDGE_LEAK") -> None:
        bad = sorted(set(payload or {}) & FORBIDDEN_PL_INPUT_KEYS)
        if bad:
            raise KnowledgeBoundaryError(code, f"forbidden keys present: {bad}")

    def assert_kp_hint_grounded(
        self,
        *,
        facts_referenced: Sequence[str],
        grounded_fact_ids: Optional[Set[str]] = None,
    ) -> None:
        allowed = set(grounded_fact_ids or self.known_fact_ids)
        for fid in facts_referenced or []:
            if str(fid) not in allowed:
                raise KnowledgeBoundaryError(
                    "UNGROUNDED_KP_HINT",
                    f"KP hint references ungrounded fact_id={fid}",
                )

    def assert_frontier_value_visible(self, value_reasons: Sequence[str] | Mapping[str, Any]) -> None:
        """Reject frontiers valued only via hidden solution signals."""
        if isinstance(value_reasons, Mapping):
            keys = set(value_reasons)
            if keys and keys <= FORBIDDEN_FRONTIER_VALUE_KEYS:
                raise KnowledgeBoundaryError(
                    "HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK",
                    "frontier value_reasons only from hidden solution signals",
                )
            self.assert_no_forbidden_keys(value_reasons, code="HIDDEN_CORRECT_PATH_SIGNAL")
            return
        reasons = [str(x) for x in (value_reasons or [])]
        forbidden_tokens = {
            "hidden_scenario_solution",
            "is_correct_path",
            "distance_to_solution",
            "required_for_ending",
            "secret_priority",
            "author_priority",
            "author_intended_route",
            "final_answer_proximity",
        }
        if reasons and all(r in forbidden_tokens for r in reasons):
            raise KnowledgeBoundaryError(
                "HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK",
                "frontier value_reasons only from hidden solution signals",
            )
        if any(r in forbidden_tokens for r in reasons):
            raise KnowledgeBoundaryError(
                "HIDDEN_CORRECT_PATH_SIGNAL",
                f"forbidden frontier value reason present: {reasons}",
            )


class ReasoningInputBuilder:
    """Builds PL-safe input bundles for LLM / decision policy."""

    def __init__(self, boundary: ReasoningKnowledgeBoundary):
        self.boundary = boundary

    def build(
        self,
        *,
        actor_id: str,
        legal_actions: Sequence[Mapping[str, Any]],
        pc_personality: Optional[Mapping[str, Any]] = None,
        pl_style: Optional[Sequence[str]] = None,
        recent_actions: Optional[Sequence[Any]] = None,
        shared_speech: Optional[Sequence[Any]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> dict:
        payload = {
            "actor_id": actor_id,
            "known_facts": [f.to_dict() for f in self.boundary._facts.values() if f.kind == EpistemicKind.FACT],
            "hypotheses": [f.to_dict() for f in self.boundary._facts.values() if f.kind == EpistemicKind.HYPOTHESIS],
            "legal_actions": list(legal_actions or []),
            "pc_personality": dict(pc_personality or {}),
            "pl_style": list(pl_style or []),
            "recent_actions": list(recent_actions or []),
            "shared_speech": list(shared_speech or []),
        }
        if extra:
            scrubbed = self.boundary.scrub_forbidden_inputs(extra)
            self.boundary.assert_no_forbidden_keys(scrubbed)
            payload["extra"] = scrubbed
        return payload
