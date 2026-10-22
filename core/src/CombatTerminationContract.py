"""Corbitt final-battle termination: full ordered chain, fail-closed gaps."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence


TERMINATION_VALIDATED_KILL = "VALIDATED_KILL"
TERMINATION_VALIDATED_ESCAPE = "VALIDATED_ESCAPE"
TERMINATION_ALL_HOSTILES_GONE = "ALL_HOSTILES_GONE"
TERMINATION_SCENARIO_DETERMINISTIC = "SCENARIO_DETERMINISTIC_TERMINATION"
TERMINATION_SYSTEM_ABORT = "SYSTEM_ABORT"

CORBITT_FINAL_BATTLE_TERMINATION_POLICY = "VALIDATED_KILL_ONLY"
LEGAL_CORBITT_ROUTES = frozenset({"ROUTE_A_HP0", "ROUTE_B_DAGGER"})


class CombatTerminationContractViolation(ValueError):
    code = "COMBAT_TERMINATION_CONTRACT_VIOLATION"


class CombatEndedWithoutValidTermination(ValueError):
    code = "COMBAT_ENDED_WITHOUT_VALID_TERMINATION"


class CombatTerminationChainIncomplete(ValueError):
    code = "COMBAT_TERMINATION_CHAIN_INCOMPLETE"


@dataclass
class TerminationEvidence:
    combat_id: str = ""
    termination_reason: str = ""
    validated_kill_route_id: str = ""
    source_rule_id: str = ""
    kill_event_id: str = ""
    defeat_event_id: str = ""
    special_objective_event_id: str = ""
    ending_event_id: str = ""
    validation_id: str = ""
    corbitt_defeated: bool = False
    special_objective_completed: bool = False
    termination_contract_validated: bool = False
    chain_steps: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def is_corbitt_final_battle(state_mgr=None, scenario_mgr=None, state: Optional[Mapping[str, Any]] = None) -> bool:
    flags = {}
    if state and isinstance(state.get("flags"), dict):
        flags = state.get("flags") or {}
    goal = str(getattr(state_mgr, "combat_goal", "") or "")
    if "corbitt" in goal.lower():
        return True
    if flags.get("trigger_corbitt_boss_battle") or flags.get("corbitt_body_encountered"):
        # Boss active if in combat with corbitt present
        queue = list(getattr(state_mgr, "combat_turn_queue", None) or getattr(state_mgr, "turn_order", None) or [])
        if any("corbitt" in str(x).lower() for x in queue):
            return True
        if getattr(state_mgr, "in_combat", False) and flags.get("trigger_corbitt_boss_battle"):
            return True
    return False


def _chain_store(state: dict) -> dict:
    return state.setdefault("combat_termination_chain", {})


def record_validated_kill(
    state: dict,
    *,
    validated_kill_route_id: str,
    source_rule_id: str = "",
    kill_event_id: str = "",
    combat_id: str = "",
) -> dict:
    if validated_kill_route_id not in LEGAL_CORBITT_ROUTES:
        raise CombatTerminationContractViolation(f"illegal kill route: {validated_kill_route_id}")
    store = _chain_store(state)
    if store.get("COMBAT_ENDED"):
        raise CombatTerminationContractViolation("idempotent reject: combat already ended")
    if store.get("VALIDATED_KILL") and store.get("validated_kill_route_id") != validated_kill_route_id:
        raise CombatTerminationContractViolation("duplicate conflicting VALIDATED_KILL")
    eid = kill_event_id or f"kill_{uuid.uuid4().hex[:10]}"
    store.update({
        "VALIDATED_KILL": True,
        "validated_kill_route_id": validated_kill_route_id,
        "source_rule_id": source_rule_id,
        "kill_event_id": eid,
        "combat_id": combat_id or store.get("combat_id") or "",
        "termination_reason": TERMINATION_VALIDATED_KILL,
        "chain_order": list(store.get("chain_order") or []) + ["VALIDATED_KILL"],
    })
    return store


def commit_corbitt_defeated(state: dict, *, defeat_event_id: str = "") -> dict:
    store = _chain_store(state)
    if not store.get("VALIDATED_KILL"):
        raise CombatTerminationChainIncomplete("defeat requires VALIDATED_KILL first")
    if store.get("COMBAT_ENDED"):
        raise CombatTerminationContractViolation("idempotent reject: already ended")
    flags = state.setdefault("flags", {})
    flags["corbitt_defeated"] = True
    eid = defeat_event_id or f"defeat_{uuid.uuid4().hex[:10]}"
    store["CORBITT_DEFEATED_STATE_COMMITTED"] = True
    store["defeat_event_id"] = eid
    store["corbitt_defeated"] = True
    order = list(store.get("chain_order") or [])
    if "CORBITT_DEFEATED_STATE_COMMITTED" not in order:
        order.append("CORBITT_DEFEATED_STATE_COMMITTED")
    store["chain_order"] = order
    return store


def commit_derived_special_objective(state: dict, *, so_event_id: str = "") -> dict:
    store = _chain_store(state)
    if not store.get("CORBITT_DEFEATED_STATE_COMMITTED"):
        raise CombatTerminationChainIncomplete("SO requires defeat state")
    if not store.get("validated_kill_route_id"):
        raise CombatTerminationChainIncomplete("SO requires validated_kill_route_id")
    if store.get("SPECIAL_OBJECTIVE_COMPLETED"):
        return store  # idempotent same payload
    eid = so_event_id or f"so_{uuid.uuid4().hex[:10]}"
    store["SPECIAL_OBJECTIVE_COMPLETED"] = True
    store["special_objective_event_id"] = eid
    store["special_objective_payload"] = {
        "validated_kill_route_id": store.get("validated_kill_route_id"),
        "defeat_event_id": store.get("defeat_event_id"),
        "source_rule_id": store.get("source_rule_id"),
        "derived": True,
    }
    order = list(store.get("chain_order") or [])
    if "SPECIAL_OBJECTIVE_COMPLETED" not in order:
        order.append("SPECIAL_OBJECTIVE_COMPLETED")
    store["chain_order"] = order
    return store


def assert_ending_preconditions(state: dict) -> dict:
    store = _chain_store(state)
    flags = state.get("flags") or {}
    missing = []
    if not store.get("VALIDATED_KILL"):
        missing.append("VALIDATED_KILL")
    if not store.get("validated_kill_route_id"):
        missing.append("validated_kill_route_id")
    if not (store.get("corbitt_defeated") or flags.get("corbitt_defeated")):
        missing.append("corbitt_defeated")
    if not store.get("SPECIAL_OBJECTIVE_COMPLETED"):
        missing.append("SPECIAL_OBJECTIVE_COMPLETED")
    if store.get("termination_reason") != TERMINATION_VALIDATED_KILL:
        missing.append("termination_reason==VALIDATED_KILL")
    if missing:
        raise CombatTerminationContractViolation(
            f"COMBAT_ENDING blocked; missing={missing}"
        )
    return store


def emit_combat_ending(state: dict, *, ending_event_id: str = "") -> dict:
    store = assert_ending_preconditions(state)
    if store.get("COMBAT_ENDING"):
        return store
    eid = ending_event_id or f"ending_{uuid.uuid4().hex[:10]}"
    store["COMBAT_ENDING"] = True
    store["ending_event_id"] = eid
    order = list(store.get("chain_order") or [])
    order.append("COMBAT_ENDING")
    store["chain_order"] = order
    return store


def validate_termination_contract(state: dict) -> dict:
    store = _chain_store(state)
    required = [
        "VALIDATED_KILL",
        "CORBITT_DEFEATED_STATE_COMMITTED",
        "SPECIAL_OBJECTIVE_COMPLETED",
        "COMBAT_ENDING",
    ]
    missing = [k for k in required if not store.get(k)]
    if missing:
        raise CombatTerminationChainIncomplete(f"validation missing steps: {missing}")
    order = list(store.get("chain_order") or [])
    expected_prefix = [
        "VALIDATED_KILL",
        "CORBITT_DEFEATED_STATE_COMMITTED",
        "SPECIAL_OBJECTIVE_COMPLETED",
        "COMBAT_ENDING",
    ]
    # Order check: each expected step appears in sequence
    try:
        idxs = [order.index(step) for step in expected_prefix]
    except ValueError as exc:
        raise CombatTerminationChainIncomplete(f"order incomplete: {order}") from exc
    if idxs != sorted(idxs):
        raise CombatTerminationChainIncomplete(f"order invalid: {order}")
    if store.get("validated_kill_route_id") not in LEGAL_CORBITT_ROUTES:
        raise CombatTerminationContractViolation("bad kill route at validation")
    if not store.get("corbitt_defeated"):
        raise CombatTerminationChainIncomplete("corbitt_defeated false at validation")
    vid = f"termval_{uuid.uuid4().hex[:10]}"
    store["TERMINATION_CONTRACT_VALIDATED"] = True
    store["termination_contract_validated"] = True
    store["validation_id"] = vid
    order = list(store.get("chain_order") or [])
    if "TERMINATION_CONTRACT_VALIDATED" not in order:
        order.append("TERMINATION_CONTRACT_VALIDATED")
    store["chain_order"] = order
    return store


def emit_combat_ended(state: dict) -> dict:
    store = _chain_store(state)
    if not store.get("termination_contract_validated"):
        raise CombatEndedWithoutValidTermination(
            "COMBAT_ENDED requires termination_contract_validated=true"
        )
    if store.get("COMBAT_ENDED"):
        raise CombatTerminationContractViolation("duplicate COMBAT_ENDED rejected")
    store["COMBAT_ENDED"] = True
    order = list(store.get("chain_order") or [])
    order.append("COMBAT_ENDED")
    store["chain_order"] = order
    return store


def run_full_corbitt_termination_chain(
    state: dict,
    *,
    validated_kill_route_id: str,
    source_rule_id: str = "",
    combat_id: str = "",
) -> TerminationEvidence:
    """Happy path helper for fixtures / production kill completion."""
    record_validated_kill(
        state,
        validated_kill_route_id=validated_kill_route_id,
        source_rule_id=source_rule_id,
        combat_id=combat_id,
    )
    commit_corbitt_defeated(state)
    commit_derived_special_objective(state)
    emit_combat_ending(state)
    validate_termination_contract(state)
    emit_combat_ended(state)
    store = _chain_store(state)
    return TerminationEvidence(
        combat_id=str(store.get("combat_id") or ""),
        termination_reason=TERMINATION_VALIDATED_KILL,
        validated_kill_route_id=str(store.get("validated_kill_route_id") or ""),
        source_rule_id=str(store.get("source_rule_id") or ""),
        kill_event_id=str(store.get("kill_event_id") or ""),
        defeat_event_id=str(store.get("defeat_event_id") or ""),
        special_objective_event_id=str(store.get("special_objective_event_id") or ""),
        ending_event_id=str(store.get("ending_event_id") or ""),
        validation_id=str(store.get("validation_id") or ""),
        corbitt_defeated=True,
        special_objective_completed=True,
        termination_contract_validated=True,
        chain_steps=list(store.get("chain_order") or []),
    )


def forbid_corbitt_auto_end_without_kill(state: dict, *, reason: str = "resolved") -> None:
    """Call before end_combat when Corbitt boss active and no validated kill chain."""
    store = _chain_store(state)
    flags = state.get("flags") or {}
    if store.get("termination_contract_validated") and store.get("VALIDATED_KILL"):
        return
    if flags.get("corbitt_defeated") and store.get("VALIDATED_KILL"):
        # Still require full chain before ENDED
        raise CombatEndedWithoutValidTermination(
            "Corbitt end requires full termination chain before end_combat"
        )
    raise CombatEndedWithoutValidTermination(
        f"COMBAT_END_WITHOUT_VALIDATED_KILL reason={reason}"
    )


def no_action_this_turn_result(*, reason: str = "NO_ACTION_THIS_TURN") -> dict:
    return {
        "ok": True,
        "outcome": reason,
        "combat_ended": False,
        "end_combat": False,
        "action": "wait",
        "reason": reason,
    }
