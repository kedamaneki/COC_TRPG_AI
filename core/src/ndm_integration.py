"""Production hooks: bootstrap NDM and bind selected PL actions."""

from __future__ import annotations

import os
from typing import Any, Mapping, Optional, Sequence

from reasoning.runtime import (
    DECISION_SOURCE_NDM,
    NDMInitFailure,
    NaturalDecisionRuntime,
    UnboundDecisionCommit,
    bootstrap_natural_decision,
    get_active_runtime,
    set_active_runtime,
)


def ndm_required_from_env(default: bool = True) -> bool:
    raw = str(os.environ.get("NATURAL_DECISION_REQUIRED", "") or "").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def ensure_ndm_runtime(
    state: dict,
    *,
    required: Optional[bool] = None,
    enabled: bool = True,
    implementation_commit: str = "",
) -> NaturalDecisionRuntime:
    existing = get_active_runtime()
    runtime_meta = (state.get("ndm_runtime") or {})
    if existing and existing.active and runtime_meta.get("active"):
        return existing
    req = ndm_required_from_env(True) if required is None else bool(required)
    try:
        return bootstrap_natural_decision(
            state,
            enabled=enabled,
            required=req,
            implementation_commit=implementation_commit,
        )
    except NDMInitFailure:
        raise


def enrich_pc_action_with_ndm(
    state: dict,
    pc_action: Mapping[str, Any],
    *,
    actor_id: str,
    scenario_mgr=None,
) -> dict:
    """Bind LLM/proposed action through NDM causal path when runtime active."""
    rt = get_active_runtime()
    if rt is None or not rt.active:
        # Fail-closed if required
        if ndm_required_from_env(True) and bool((state.get("ndm_runtime") or {}).get("required", True)):
            raise NDMInitFailure("NATURAL_DECISION_RUNTIME_ACTIVE missing for required run")
        return dict(pc_action)

    runtime = state.setdefault("director_v2", {})
    goal = runtime.get("goal") or {}
    candidates = list(goal.get("candidate_next_actions") or [])
    # Always include the model proposal as a candidate
    proposal = dict(pc_action)
    proposal.setdefault(
        "reason",
        str(proposal.get("selection_reason") or proposal.get("message") or "pl_proposal"),
    )
    proposal.setdefault("candidate_id", "pl_proposal")
    candidates = [proposal] + [
        c for c in candidates
        if not (
            str(c.get("action") or "") == str(proposal.get("action") or "")
            and str(c.get("target") or "") == str(proposal.get("target") or "")
        )
    ]
    if not candidates:
        candidates = [proposal]

    selected = rt.decide(
        state,
        actor_id=actor_id,
        candidates=candidates,
        recent_actions=list((runtime.get("stall") or {}).get("recent_actions") or []),
        restore_location=str(
            (runtime.get("natural_decision") or {}).get("restore_location")
            or state.get("current_loc")
            or ""
        ),
    )
    # Merge identity onto outgoing action; prefer NDM selection fields
    out = dict(pc_action)
    out.update({
        "action": selected.get("action", out.get("action")),
        "target": selected.get("target", out.get("target")),
        "skill": selected.get("skill", out.get("skill")),
        "reasoning_id": selected.get("reasoning_id"),
        "decision_source": selected.get("decision_source"),
        "candidate_set_id": selected.get("candidate_set_id"),
        "selected_candidate_id": selected.get("selected_candidate_id"),
        "decision_transaction_id": selected.get("decision_transaction_id"),
        "selection_reason": selected.get("selection_reason") or selected.get("reason"),
        "ndm_assessment_id": selected.get("ndm_assessment_id"),
        "ndm_intervention_id": selected.get("ndm_intervention_id"),
    })
    if selected.get("s4_recovery_mode"):
        out["s4_recovery_mode"] = selected.get("s4_recovery_mode")
        out["director_forced"] = True
        out["intervention_level"] = str(
            ((state.get("director_v2") or {}).get("stall") or {}).get("intervention_level") or "S4"
        )
    rt.assert_commit_bound(out)
    return out


def guard_executor_commit(action: Mapping[str, Any], state: Optional[dict] = None) -> None:
    rt = get_active_runtime()
    if rt and rt.active:
        rt.assert_commit_bound(action)
        rt.mark_executed(action)


def maybe_end_combat_corbitt_safe(state_mgr, state: dict, *, reason: str = "resolved") -> bool:
    """Return True if end_combat was allowed/executed; False if blocked as no-action."""
    from CombatTerminationContract import (
        CombatEndedWithoutValidTermination,
        is_corbitt_final_battle,
        no_action_this_turn_result,
    )
    if not is_corbitt_final_battle(state_mgr, state=state):
        state_mgr.end_combat(reason, state=state, skip_corbitt_contract=True)
        return True
    try:
        state_mgr.end_combat(reason, state=state, skip_corbitt_contract=False)
        return True
    except CombatEndedWithoutValidTermination:
        return False
