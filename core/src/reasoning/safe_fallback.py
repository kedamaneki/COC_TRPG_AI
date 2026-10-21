"""SAFE_LEGACY_PROGRESSION — guarded fallback, not full old behavior."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence, Set

from .knowledge_boundary import (
    FORBIDDEN_PL_INPUT_KEYS,
    KnowledgeBoundaryError,
    ReasoningKnowledgeBoundary,
)


REASONING_MODEL_FALLBACK = "REASONING_MODEL_FALLBACK"

MAX_FALLBACK_STREAK = 5


@dataclass
class FallbackEvidence:
    failure_reason: str
    fallback_mode: str = "SAFE_LEGACY_PROGRESSION"
    guards_active: list = field(default_factory=list)
    candidate_count_before: int = 0
    candidate_count_after: int = 0
    selected_action: Optional[dict] = None
    fallback_streak: int = 1
    code: str = REASONING_MODEL_FALLBACK

    def to_dict(self) -> dict:
        return asdict(self)


class FallbackUnboundedError(RuntimeError):
    code = "REPEATED_FALLBACK_UNBOUNDED"


class SafeLegacyProgression:
    """Fallback path that keeps safety guards active."""

    GUARDS = (
        "hidden_knowledge_prohibition",
        "attempt_exhausted_filtering",
        "location_legality",
        "required_location",
        "recent_repetition_penalty",
        "unresolved_lead_preservation",
        "implicit_forced_solution_prohibition",
        "invalid_action_exclusion",
        "resolved_objective_suppression",
    )

    def __init__(
        self,
        boundary: Optional[ReasoningKnowledgeBoundary] = None,
        *,
        max_streak: int = MAX_FALLBACK_STREAK,
    ):
        self.boundary = boundary or ReasoningKnowledgeBoundary()
        self.max_streak = int(max_streak)
        self.fallback_streak = 0

    def filter_candidates(
        self,
        candidates: Sequence[Mapping[str, Any]],
        *,
        known_fact_ids: Optional[Set[str]] = None,
        exhausted_attempts: Optional[Sequence[Mapping[str, Any]]] = None,
        legal_locations: Optional[Set[str]] = None,
        required_location: str = "",
        current_location: str = "",
        recent_actions: Optional[Sequence[Mapping[str, Any]]] = None,
        unresolved_lead_ids: Optional[Sequence[str]] = None,
        resolved_objectives: Optional[Set[str]] = None,
        hidden_candidate_ids: Optional[Set[str]] = None,
    ) -> list[dict]:
        known = set(known_fact_ids or self.boundary.known_fact_ids)
        exhausted = {
            (str(x.get("action") or ""), str(x.get("target") or ""))
            for x in (exhausted_attempts or [])
        }
        legal_locs = set(legal_locations or [])
        resolved = set(resolved_objectives or [])
        hidden = set(hidden_candidate_ids or [])
        recent = list(recent_actions or [])

        out: list[dict] = []
        for raw in candidates:
            item = dict(raw)
            # Hidden knowledge / solution candidates
            self.boundary.assert_no_forbidden_keys(item, code="REASONING_KNOWLEDGE_LEAK")
            cid = str(item.get("candidate_id") or item.get("id") or "")
            if cid and cid in hidden:
                continue
            if item.get("hidden_solution") or item.get("is_correct_path"):
                continue
            # Attempt exhausted
            key = (str(item.get("action") or ""), str(item.get("target") or ""))
            if key in exhausted:
                continue
            # Location legality
            loc = str(item.get("required_location") or item.get("location") or "")
            if legal_locs and loc and loc not in legal_locs:
                continue
            if required_location and loc and loc != required_location and str(item.get("action") or "") != "move":
                continue
            if required_location and current_location and required_location != current_location:
                if str(item.get("action") or "") not in {"move", "leave", "goto"}:
                    # Prefer transition toward required location rather than illegal local acts
                    if item.get("target") != required_location:
                        continue
            # Resolved objective suppression
            obj = str(item.get("objective_id") or "")
            if obj and obj in resolved:
                continue
            # Supporting knowledge must be known
            support = item.get("supporting_knowledge") or item.get("known_fact_ids") or []
            try:
                for fid in support:
                    if str(fid) not in known:
                        raise KnowledgeBoundaryError("REASONING_KNOWLEDGE_LEAK", f"unknown {fid}")
            except KnowledgeBoundaryError:
                continue
            # Recent repetition soft-penalty (keep but mark)
            if len(recent) >= 2:
                last = recent[-1]
                if (
                    str(last.get("action") or "") == key[0]
                    and str(last.get("target") or "") == key[1]
                ):
                    item = dict(item)
                    item["repeat_penalty"] = float(item.get("repeat_penalty") or 0) + 0.5
            # Preserve unresolved leads: do not drop attend/revisit to them
            out.append(item)

        # Ensure unresolved leads remain represented if present in original set
        lead_ids = set(unresolved_lead_ids or [])
        if lead_ids:
            present = {str(x.get("target") or "") for x in out}
            for raw in candidates:
                t = str(raw.get("target") or "")
                if t in lead_ids and t not in present:
                    # Re-add if only blocked by soft filters (not hidden/exhausted)
                    key = (str(raw.get("action") or ""), t)
                    if key not in exhausted and not raw.get("hidden_solution"):
                        out.append(dict(raw))
                        present.add(t)
        return out

    def select(
        self,
        candidates: Sequence[Mapping[str, Any]],
        *,
        failure_reason: str,
        **filter_kwargs: Any,
    ) -> tuple[Optional[dict], FallbackEvidence]:
        self.fallback_streak += 1
        if self.fallback_streak > self.max_streak:
            raise FallbackUnboundedError(
                f"fallback_streak={self.fallback_streak} exceeds max={self.max_streak}"
            )
        before = len(candidates)
        filtered = self.filter_candidates(candidates, **filter_kwargs)
        after = len(filtered)

        selected = None
        if filtered:
            # Prefer lower repeat_penalty then higher goal_relevance if present
            def util(c: Mapping[str, Any]) -> float:
                return float(c.get("goal_relevance") or 0) - float(c.get("repeat_penalty") or 0)

            selected = dict(sorted(filtered, key=util, reverse=True)[0])

        evidence = FallbackEvidence(
            failure_reason=str(failure_reason or "reasoning_failure"),
            fallback_mode="SAFE_LEGACY_PROGRESSION",
            guards_active=list(self.GUARDS),
            candidate_count_before=before,
            candidate_count_after=after,
            selected_action=selected,
            fallback_streak=self.fallback_streak,
        )
        return selected, evidence

    def reset_streak_on_success(self) -> None:
        self.fallback_streak = 0
