"""Frontier-set recovery — never bind to a single hidden solution."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .knowledge_boundary import (
    FORBIDDEN_FRONTIER_VALUE_KEYS,
    KnowledgeBoundaryError,
    ReasoningKnowledgeBoundary,
)
from .lead_tracker import Lead, LeadTracker


@dataclass
class FrontierSet:
    frontier_ids: list[str] = field(default_factory=list)
    restore_location: str = ""
    restore_executable: bool = True
    forced_solution: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class FrontierRecoveryPolicy:
    """Build UNRESOLVED_HIGH_VALUE_FRONTIER_SET for S4 recovery."""

    def __init__(self, boundary: Optional[ReasoningKnowledgeBoundary] = None):
        self.boundary = boundary or ReasoningKnowledgeBoundary()

    def build_set(
        self,
        leads: Sequence[Lead] | LeadTracker,
        *,
        restore_location: str = "",
        extra_signals: Optional[Mapping[str, Any]] = None,
    ) -> FrontierSet:
        signals = dict(extra_signals or {})
        for key in FORBIDDEN_FRONTIER_VALUE_KEYS:
            if key in signals and signals[key] not in (None, False, 0, "", []):
                raise KnowledgeBoundaryError(
                    "HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK",
                    f"forbidden frontier signal: {key}",
                )
        self.boundary.assert_no_forbidden_keys(signals, code="HIDDEN_CORRECT_PATH_SIGNAL")

        if isinstance(leads, LeadTracker):
            frontiers = leads.unresolved_high_value_frontier_set()
            selected = [str(f["frontier_id"]) for f in frontiers]
        else:
            selected = []
            for lead in leads:
                if not (lead.high_value and lead.unresolved and lead.visible_to_party):
                    continue
                self.boundary.assert_frontier_value_visible(lead.value_reasons)
                selected.append(lead.lead_id)

        return FrontierSet(
            frontier_ids=selected,
            restore_location=str(restore_location or ""),
            restore_executable=True,
            forced_solution=False,
            notes=["frontier_set_recovery", "no_single_solution_binding"],
        )

    def recovery_actions(self, frontier_set: FrontierSet) -> list[dict]:
        """S4 actions: return to location / restore frontier — not push/destroy/win."""
        actions = []
        if frontier_set.restore_location:
            actions.append({
                "action": "move",
                "target": frontier_set.restore_location,
                "reason": "S4 frontier-set recovery: return to meaningful location",
                "meaning_class": "TRANSITION",
                "s4_recovery": True,
                "force_solution": False,
            })
        for fid in frontier_set.frontier_ids:
            actions.append({
                "action": "attend",
                "target": fid,
                "reason": "S4 restore executable unresolved high-value frontier",
                "meaning_class": "REVISIT_WITH_NEW_INFO",
                "s4_recovery": True,
                "force_solution": False,
            })
        for a in actions:
            if a.get("force_solution"):
                raise KnowledgeBoundaryError("DIRECT_SOLUTION_S4_PATH", "forced solution in S4")
            act = str(a.get("action") or "").lower()
            if act in {"destroy", "win_combat", "force_break_planks"}:
                raise KnowledgeBoundaryError("DIRECT_SOLUTION_S4_PATH", f"banned S4 action: {act}")
        return actions


def basement_plank_frontier_example() -> FrontierSet:
    return FrontierSet(
        frontier_ids=["basement_planks", "magic_dagger", "basement_other_unresolved"],
        restore_location="corbitt_basement",
        restore_executable=True,
        forced_solution=False,
        notes=["vignette", "do_not_force_plank_destruction"],
    )
