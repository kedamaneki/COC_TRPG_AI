"""Fail-closed completion commit for scenario special objectives."""

from __future__ import annotations


class CompletionAtomicityError(RuntimeError):
    """Raised when completion-related state cannot be committed coherently."""


def _special_objective_events(state):
    return [
        event for event in (state or {}).get("unified_event_log", [])
        if str(event.get("event_type") or "").upper() == "SPECIAL_OBJECTIVE_COMPLETED"
        and str((event.get("world_fact") or {}).get("event") or "").upper()
        == "SPECIAL_OBJECTIVE_COMPLETED"
    ]


def validate_completion_invariants(
    *, completed: bool, clear: bool, ending: bool, corbitt_defeated: bool,
    special_objective: bool, active_combat: bool,
):
    """Validate one authoritative completion envelope."""
    contradictions = []
    if corbitt_defeated and not special_objective:
        contradictions.append("DEFEATED_WITHOUT_SPECIAL_OBJECTIVE")
    if completed and active_combat:
        contradictions.append("COMPLETED_DURING_ACTIVE_COMBAT")
    if clear and not ending:
        contradictions.append("CLEAR_WITHOUT_ENDING")
    if completed and not all((clear, ending, corbitt_defeated, special_objective)):
        contradictions.append("INCOMPLETE_COMPLETION_ENVELOPE")
    if contradictions:
        raise CompletionAtomicityError(
            "COMPLETION_ATOMICITY_GATE failed: " + ",".join(contradictions)
        )
    return {
        "completed": bool(completed),
        "clear": bool(clear),
        "ending": bool(ending),
        "corbitt_defeated": bool(corbitt_defeated),
        "special_objective": bool(special_objective),
        "active_combat": bool(active_combat),
        "completion_state_contradictions": 0,
        "gate": "PASS",
    }


def commit_special_objective_completion(state, result, scenario_mgr, state_mgr):
    """Validate and atomically publish a deferred special-objective clear."""
    if not result or result.get("completion_phase_deferred") != "clear":
        return None

    adjudication_id = str(result.get("adjudication_id") or "")
    target = str(result.get("target") or (result.get("world_fact") or {}).get("target") or "")
    matching = [
        event for event in _special_objective_events(state)
        if (not adjudication_id or str(event.get("adjudication_id") or "") == adjudication_id)
        and (not target or str(event.get("target") or "") == target)
    ]
    active_combat = bool(getattr(state_mgr, "in_combat", False))
    envelope = validate_completion_invariants(
        completed=True,
        clear=True,
        ending=not active_combat,
        corbitt_defeated=bool((getattr(scenario_mgr, "flags", {}) or {}).get("corbitt_defeated")),
        special_objective=bool(matching),
        active_combat=active_combat,
    )
    scenario_mgr.current_phase = "clear"
    envelope.update({
        "adjudication_id": adjudication_id,
        "target": target,
        "source_event_ids": [str(event.get("event_id") or "") for event in matching],
    })
    state["completion_envelope"] = envelope
    result["completion_atomicity_gate"] = "PASS"
    result["completion_state_contradictions"] = 0
    result["special_objective_evidence"] = True
    return envelope
