"""Bridge Natural Decision Model → ProgressDirectorV2 (S4 frontier-set recovery)."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence


DESTRUCTIVE_ACTIONS = frozenset({
    "break", "destroy", "force", "attack", "kill", "win_combat", "force_break_planks",
})


def reorder_s4_candidates_for_frontier_recovery(
    candidates: Sequence[Mapping[str, Any]],
    *,
    frontier_ids: Sequence[str] = (),
    restore_location: str = "",
) -> list[dict]:
    """Prefer return-to-location / attend unresolved frontiers; never collapse to sole destructive solution."""
    items = [dict(c) for c in candidates]
    if not items:
        return items

    frontier = {str(x) for x in frontier_ids or []}
    restore = str(restore_location or "")

    def rank(item: Mapping[str, Any]) -> tuple:
        action = str(item.get("action") or "").lower()
        target = str(item.get("target") or "")
        req_loc = str(item.get("required_location") or "")
        # Lower is better
        if restore and action == "move" and (target == restore or req_loc == restore):
            return (0, 0)
        if frontier and target in frontier and action not in DESTRUCTIVE_ACTIONS:
            return (1, 0)
        if frontier and target in frontier:
            return (2, 0)
        if action in DESTRUCTIVE_ACTIONS and len(frontier) > 1:
            return (9, 0)  # deprioritize sole forced destruction when set exists
        if action in DESTRUCTIVE_ACTIONS:
            return (5, 0)
        return (3, 0)

    return sorted(items, key=rank)


def apply_natural_s4_override(
    state: Mapping[str, Any],
    pc_action: Mapping[str, Any],
    *,
    candidates: Sequence[Mapping[str, Any]],
) -> Optional[dict]:
    """
    If natural_decision_v1 is enabled and S4 is active, bind to frontier-set recovery
    rather than a hidden single solution. Returns None to defer to legacy override.
    """
    runtime = (state or {}).get("director_v2") or {}
    if not runtime.get("natural_decision_v1"):
        return None
    stall = runtime.get("stall") or {}
    if str(stall.get("intervention_level") or "S0") != "S4":
        return None

    nd = runtime.get("natural_decision") or {}
    frontier_ids = list(nd.get("frontier_set") or runtime.get("unresolved_high_value_frontiers") or [])
    restore_location = str(nd.get("restore_location") or runtime.get("s4_restore_location") or "")

    ordered = reorder_s4_candidates_for_frontier_recovery(
        candidates,
        frontier_ids=frontier_ids,
        restore_location=restore_location,
    )
    if not ordered:
        # Synthesize move-home recovery when no candidates but restore location known
        if restore_location:
            return {
                **dict(pc_action or {}),
                "original_action": dict(pc_action or {}),
                "action": "move",
                "target": restore_location,
                "skill": "",
                "dialogue": "",
                "message": "",
                "action_origin": "SYSTEM_FORCED",
                "director_forced": True,
                "intervention_level": "S4",
                "intervention_reason": "frontier_set_recovery",
                "force_solution": False,
                "s4_recovery_mode": "FRONTIER_SET_RECOVERY",
            }
        return None

    top = ordered[0]
    # Do not force destructive solution when multiple frontiers remain
    if (
        str(top.get("action") or "").lower() in DESTRUCTIVE_ACTIONS
        and len(frontier_ids) > 1
        and restore_location
    ):
        top = {
            "action": "move",
            "target": restore_location,
            "required_location": restore_location,
        }

    if (
        str((pc_action or {}).get("action") or "") == str(top.get("action") or "")
        and str((pc_action or {}).get("target") or "") == str(top.get("target") or "")
    ):
        return dict(pc_action or {})

    fixed = dict(pc_action or {})
    fixed["original_action"] = dict(pc_action or {})
    fixed["action"] = str(top.get("action") or "wait")
    fixed["target"] = str(top.get("target") or "")
    fixed["skill"] = str(top.get("skill") or "")
    fixed["dialogue"] = ""
    fixed["message"] = ""
    fixed["action_origin"] = "SYSTEM_FORCED"
    fixed["director_forced"] = True
    fixed["intervention_level"] = "S4"
    fixed["intervention_reason"] = "frontier_set_recovery"
    fixed["force_solution"] = False
    fixed["s4_recovery_mode"] = "FRONTIER_SET_RECOVERY"
    fixed["availability_snapshot"] = dict(top.get("availability_snapshot") or {})
    fixed["required_location"] = str(top.get("required_location") or restore_location or "")
    return fixed
