"""Fail-closed completion commit for scenario special objectives."""

from __future__ import annotations

from CombatResolutionGuard import (
    VALID_KILL_ROUTES,
    CombatResolutionError,
    validate_victory_provenance,
)


class CompletionAtomicityError(RuntimeError):
    """Raised when completion-related state cannot be committed coherently."""


def _special_objective_events(state):
    return [
        event for event in (state or {}).get("unified_event_log", [])
        if str(event.get("event_type") or "").upper() == "SPECIAL_OBJECTIVE_COMPLETED"
        and str((event.get("world_fact") or {}).get("event") or "").upper()
        == "SPECIAL_OBJECTIVE_COMPLETED"
    ]


def _event_has_validated_source_kill(event) -> bool:
    world_fact = (event or {}).get("world_fact") or {}
    try:
        validate_victory_provenance(world_fact)
    except CombatResolutionError:
        return False
    route = str(world_fact.get("validated_kill_route_id") or "").upper()
    return route in VALID_KILL_ROUTES


def validate_completion_invariants(
    *, completed: bool, clear: bool, ending: bool, corbitt_defeated: bool,
    special_objective: bool, active_combat: bool,
    validated_source_kill: bool = True,
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
    if (completed or clear or corbitt_defeated) and special_objective and not validated_source_kill:
        contradictions.append("VICTORY_WITHOUT_SOURCE_PROVENANCE")
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
        "validated_source_kill": bool(validated_source_kill),
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
    if not matching:
        raise CompletionAtomicityError(
            "COMPLETION_ATOMICITY_GATE failed: MISSING_SPECIAL_OBJECTIVE_EVENT"
        )

    validated = any(_event_has_validated_source_kill(event) for event in matching)
    # Also accept validated kill on the result payload itself (derived SO commit path).
    result_fact = result.get("world_fact") or {}
    if not validated and result_fact:
        try:
            validate_victory_provenance(result_fact)
            validated = True
            # Ensure the logged event carries the same authority fields.
            for event in matching:
                wf = dict(event.get("world_fact") or {})
                for key in (
                    "validated_kill_route_id", "fact_origin", "source_rule_id",
                    "source_ref", "may_define_kill_route",
                ):
                    if key in result_fact and key not in wf:
                        wf[key] = result_fact[key]
                event["world_fact"] = wf
            validated = any(_event_has_validated_source_kill(event) for event in matching)
        except CombatResolutionError as exc:
            raise CompletionAtomicityError(
                f"COMPLETION_ATOMICITY_GATE failed: {exc.code}"
            ) from exc

    if not validated:
        raise CompletionAtomicityError(
            "COMPLETION_ATOMICITY_GATE failed: VICTORY_WITHOUT_SOURCE_PROVENANCE"
        )

    active_combat = bool(getattr(state_mgr, "in_combat", False))
    envelope = validate_completion_invariants(
        completed=True,
        clear=True,
        ending=not active_combat,
        corbitt_defeated=bool((getattr(scenario_mgr, "flags", {}) or {}).get("corbitt_defeated")),
        special_objective=True,
        active_combat=active_combat,
        validated_source_kill=True,
    )
    scenario_mgr.current_phase = "clear"
    envelope.update({
        "adjudication_id": adjudication_id,
        "target": target,
        "source_event_ids": [str(event.get("event_id") or "") for event in matching],
        "validated_kill_route_id": str(
            ((matching[0].get("world_fact") or {}).get("validated_kill_route_id"))
            or result_fact.get("validated_kill_route_id")
            or ""
        ),
    })
    state["completion_envelope"] = envelope
    result["completion_atomicity_gate"] = "PASS"
    result["completion_state_contradictions"] = 0
    result["special_objective_evidence"] = True
    return envelope
