"""PL decision policy — multi-axis enrichment; why-now required."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from .evidence import ReasoningEvidence, build_reasoning_evidence
from .knowledge_boundary import KnowledgeBoundaryError, ReasoningKnowledgeBoundary
from .pl_state import ACTION_MEANING_CLASSES, FailureClass, PLReasoningState


AXIS_KEYS = (
    "goal_relevance",
    "information_gain",
    "continuity",
    "novelty",
    "risk",
    "cost",
    "reversibility",
    "social_value",
    "character_fit",
    "recent_failure_penalty",
    "repeat_penalty",
)


class UnexplainedActionError(ValueError):
    code = "UNEXPLAINED_ACTION_PATH"


class PLDecisionPolicy:
    def __init__(self, boundary: Optional[ReasoningKnowledgeBoundary] = None):
        self.boundary = boundary or ReasoningKnowledgeBoundary()

    def classify_meaning(self, action: Mapping[str, Any], pl_state: PLReasoningState) -> str:
        act = str(action.get("action") or "").lower()
        target = str(action.get("target") or "")
        meaning = str(action.get("meaning_class") or "").upper()
        if meaning in ACTION_MEANING_CLASSES:
            return meaning
        if act in {"move", "leave", "goto"}:
            return "TRANSITION"
        if act in {"talk", "ask", "persuade"}:
            return "SOCIAL"
        if act in {"wait", "none"}:
            return "LOW_VALUE_REPEAT"
        # Repeat penalty signal
        for failed in pl_state.failed_attempts:
            fa = failed.action if hasattr(failed, "action") else failed.get("action")
            ft = failed.target if hasattr(failed, "target") else failed.get("target")
            if fa == act and ft == target:
                return "LOW_VALUE_REPEAT"
        if act in {"search", "inspect", "examine", "listen"}:
            return "INVESTIGATE"
        if act in {"break", "push", "force", "attack"}:
            return "TEST_HYPOTHESIS"
        return "PROGRESS_GOAL"

    def score_axes(
        self,
        action: Mapping[str, Any],
        pl_state: PLReasoningState,
        *,
        open_high_value_leads: Optional[Sequence[str]] = None,
    ) -> dict:
        act = str(action.get("action") or "").lower()
        target = str(action.get("target") or "")
        meaning = self.classify_meaning(action, pl_state)
        axes = {k: 0.0 for k in AXIS_KEYS}

        if meaning in {"INVESTIGATE", "TEST_HYPOTHESIS", "PROGRESS_GOAL", "REVISIT_WITH_NEW_INFO"}:
            axes["goal_relevance"] = 0.7
            axes["information_gain"] = 0.6
        if meaning == "TRANSITION":
            axes["goal_relevance"] = 0.3
            axes["reversibility"] = 0.5
        if meaning == "LOW_VALUE_REPEAT":
            axes["repeat_penalty"] = 0.9
            axes["novelty"] = -0.5
        else:
            axes["novelty"] = 0.4

        # Continuity with high-value leads
        leads = set(open_high_value_leads or pl_state.high_value_leads or [])
        if any(str(lead) in target or target and target in str(lead) for lead in leads):
            axes["continuity"] = 0.8
            axes["goal_relevance"] = max(axes["goal_relevance"], 0.85)

        # Recent failure penalty for same method
        for failed in pl_state.failed_attempts:
            fa = failed.action if hasattr(failed, "action") else failed.get("action")
            ft = failed.target if hasattr(failed, "target") else failed.get("target")
            fc = failed.failure_class if hasattr(failed, "failure_class") else failed.get("failure_class")
            if fa == act and ft == target:
                axes["recent_failure_penalty"] = 0.7
                if str(fc) in {FailureClass.ATTEMPT_FAILED.value, "ATTEMPT_FAILED"}:
                    # Prefer alternate methods: de-weight exact repeat
                    axes["repeat_penalty"] = max(axes["repeat_penalty"], 0.8)

        # Personality soft weights
        caution = float((pl_state.pc_personality or {}).get("caution") or 0.5)
        curiosity = float((pl_state.pc_personality or {}).get("curiosity") or 0.5)
        persistence = float((pl_state.pc_personality or {}).get("persistence") or 0.5)
        axes["risk"] = caution * 0.5
        axes["information_gain"] += curiosity * 0.2
        if axes["recent_failure_penalty"] > 0 and persistence > 0.6 and meaning != "LOW_VALUE_REPEAT":
            axes["continuity"] += 0.1

        axes["character_fit"] = 0.5 + (curiosity - caution) * 0.1
        return axes

    def enrich_candidate(
        self,
        action: Mapping[str, Any],
        pl_state: PLReasoningState,
        *,
        reason: str,
        expected_purpose: str = "",
        supporting_knowledge: Optional[Sequence[str]] = None,
        uncertainty: float = 0.5,
        alternative_considered: Optional[Mapping[str, Any]] = None,
        open_high_value_leads: Optional[Sequence[str]] = None,
    ) -> dict:
        if not str(reason or "").strip():
            raise UnexplainedActionError("selection reason required")
        support = [str(x) for x in (supporting_knowledge or [])]
        self.boundary.validate_supporting_knowledge(support, allow_hypothesis=True)
        enriched = dict(action)
        enriched.update({
            "reason": str(reason),
            "expected_purpose": str(expected_purpose or ""),
            "supporting_knowledge": support,
            "uncertainty": float(uncertainty),
            "alternative_considered": dict(alternative_considered or {}),
            "meaning_class": self.classify_meaning(action, pl_state),
            "axes": self.score_axes(action, pl_state, open_high_value_leads=open_high_value_leads),
        })
        return enriched

    def require_leave_reason(
        self,
        pl_state: PLReasoningState,
        action: Mapping[str, Any],
        *,
        leave_reason: str = "",
    ) -> str:
        meaning = self.classify_meaning(action, pl_state)
        if meaning != "TRANSITION":
            return ""
        open_hv = list(pl_state.high_value_leads or [])
        if not open_hv:
            return str(leave_reason or "")
        reason = str(leave_reason or pl_state.leave_reason or "").strip()
        if not reason:
            raise ValueError("leave_reason required when open high-value leads exist")
        return reason

    def select(
        self,
        pl_state: PLReasoningState,
        candidates: Sequence[Mapping[str, Any]],
        *,
        cycle: Any = None,
        turn: Any = None,
    ) -> tuple[dict, ReasoningEvidence]:
        if not candidates:
            raise ValueError("no candidates")
        enriched = []
        for raw in candidates:
            if "reason" not in raw or not str(raw.get("reason") or "").strip():
                raise UnexplainedActionError("candidate missing reason")
            item = dict(raw)
            if "axes" not in item:
                item["axes"] = self.score_axes(item, pl_state)
            if "meaning_class" not in item:
                item["meaning_class"] = self.classify_meaning(item, pl_state)
            # leave reason gate
            if item["meaning_class"] == "TRANSITION" and pl_state.high_value_leads:
                self.require_leave_reason(pl_state, item, leave_reason=item.get("leave_reason") or pl_state.leave_reason)
            support = item.get("supporting_knowledge") or []
            self.boundary.validate_supporting_knowledge(support, allow_hypothesis=True)
            enriched.append(item)

        def utility(item: Mapping[str, Any]) -> float:
            axes = item.get("axes") or {}
            return (
                float(axes.get("goal_relevance") or 0)
                + float(axes.get("information_gain") or 0)
                + float(axes.get("continuity") or 0)
                + float(axes.get("novelty") or 0)
                + float(axes.get("character_fit") or 0)
                + float(axes.get("social_value") or 0)
                + float(axes.get("reversibility") or 0) * 0.3
                - float(axes.get("risk") or 0)
                - float(axes.get("cost") or 0)
                - float(axes.get("recent_failure_penalty") or 0)
                - float(axes.get("repeat_penalty") or 0)
            )

        ranked = sorted(enriched, key=utility, reverse=True)
        chosen = ranked[0]
        alt = ranked[1] if len(ranked) > 1 else {"action": "wait", "rejected_because": "no_alternative"}
        if not chosen.get("alternative_considered"):
            chosen["alternative_considered"] = {
                "action": alt.get("action"),
                "target": alt.get("target"),
                "rejected_because": "lower_utility",
            }
        evidence = build_reasoning_evidence(
            actor_id=pl_state.actor_id,
            cycle=cycle,
            turn=turn,
            known_fact_ids=list(pl_state.known_facts or []),
            goal_ids=[str(g) for g in (pl_state.current_goals or [])],
            lead_ids=[str(x) for x in (pl_state.high_value_leads or [])],
            hypothesis_ids=[str(x) for x in (pl_state.hypotheses or [])],
            considered_actions=ranked,
            selected_action={
                "action": chosen.get("action"),
                "target": chosen.get("target"),
                "meaning_class": chosen.get("meaning_class"),
                "leave_reason": chosen.get("leave_reason") or pl_state.leave_reason or "",
            },
            selection_reason=str(chosen.get("reason") or ""),
            confidence=float(pl_state.confidence or chosen.get("uncertainty") or 0.5),
            reasoning_mode="PL",
        )
        if not evidence.selection_reason.strip():
            raise UnexplainedActionError("UNEXPLAINED_ACTION_PATH")
        return chosen, evidence

    def suggest_after_failure(
        self,
        pl_state: PLReasoningState,
        *,
        failed_action: str,
        failed_target: str,
        failure_class: FailureClass | str,
    ) -> list[dict]:
        """Basement-plank style recovery suggestions (candidates, not forced)."""
        fc = failure_class if isinstance(failure_class, FailureClass) else FailureClass(str(failure_class))
        suggestions = []
        if fc in {FailureClass.ATTEMPT_FAILED, FailureClass.BAD_LUCK, FailureClass.UNKNOWN_REASON}:
            suggestions.append({
                "action": "push",
                "target": failed_target,
                "reason": "prior break/attempt failed; try alternate force method",
                "expected_purpose": "test whether method differs from previous attempt",
                "meaning_class": "TEST_HYPOTHESIS",
            })
        if fc in {FailureClass.INSUFFICIENT_SKILL, FailureClass.ATTEMPT_FAILED}:
            suggestions.append({
                "action": failed_action or "break",
                "target": failed_target,
                "reason": "another PC may succeed where this attempt failed",
                "expected_purpose": "retry with different actor",
                "meaning_class": "HELP_OTHER_PC",
                "actor_hint": "other_pc",
            })
        if fc in {FailureClass.INSUFFICIENT_TOOL, FailureClass.METHOD_FAILED, FailureClass.ATTEMPT_FAILED}:
            suggestions.append({
                "action": "move",
                "target": "corbitt_ground_floor",
                "reason": "seek better tool or approach before retry",
                "expected_purpose": "resource / method recovery",
                "meaning_class": "TRANSITION",
                "leave_reason": "seek_better_tool",
            })
        suggestions.append({
            "action": "search",
            "target": failed_target,
            "reason": "gather more information before forcing the obstacle",
            "expected_purpose": "reduce uncertainty",
            "meaning_class": "INVESTIGATE",
        })
        return suggestions
