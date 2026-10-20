"""Fail-closed combat resolution classes and victory provenance guards."""
from __future__ import annotations

from typing import Any, Mapping, Optional


ROLL = "ROLL"
EXPLICIT_NO_ROLL = "EXPLICIT_NO_ROLL"
DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
UNRESOLVED_COMBAT_ACTION = "UNRESOLVED_COMBAT_ACTION"

VALID_KILL_ROUTES = frozenset({"ROUTE_A_HP0", "ROUTE_B_DAGGER"})
SOURCE = "SOURCE"
ADAPTATION_TRANSFORM = "ADAPTATION_TRANSFORM"

IRREVERSIBLE_ACTIONS = frozenset({
    "kill", "destroy", "break", "force", "attack", "shoot", "kick", "push", "use",
})


class CombatResolutionError(ValueError):
    """Raised when a combat / irreversible action lacks an explicit resolution class."""

    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def is_irreversible_candidate(
    action_id: str = "",
    target: str = "",
    *,
    in_combat: bool = False,
    payload: Optional[Mapping[str, Any]] = None,
) -> bool:
    """True when the action can mutate kill / combat-end / victory state."""
    payload = payload or {}
    action = str(action_id or "").lower()
    target_l = str(target or "").lower()
    world_fact = payload.get("world_fact") or {}
    if str(world_fact.get("event") or "").upper() == "SPECIAL_OBJECTIVE_COMPLETED":
        return True
    if payload.get("combat_end"):
        return True
    if payload.get("new_phase") == "clear" or payload.get("completion_phase_deferred") == "clear":
        return True
    if (payload.get("flag_updates") or {}).get("corbitt_defeated") is True:
        return True
    if in_combat and action in IRREVERSIBLE_ACTIONS:
        return True
    if target_l in {"corbitt_body", "walter_corbitt"} and action in IRREVERSIBLE_ACTIONS:
        return True
    return False


def validate_explicit_no_roll(payload: Mapping[str, Any]) -> None:
    required = (
        "explicit_no_roll_reason",
        "source_rule_id",
        "deterministic_precondition",
        "resolution_class",
    )
    missing = [k for k in required if not _present(payload.get(k))]
    if missing:
        raise CombatResolutionError(
            UNRESOLVED_COMBAT_ACTION,
            f"EXPLICIT_NO_ROLL missing fields: {', '.join(missing)}",
        )
    if str(payload.get("resolution_class") or "").upper() != EXPLICIT_NO_ROLL:
        raise CombatResolutionError(
            UNRESOLVED_COMBAT_ACTION,
            "resolution_class must be EXPLICIT_NO_ROLL",
        )


def declare_resolution_class(
    *,
    resolution_class: str = "",
    in_combat: bool = False,
    action_id: str = "",
    target: str = "",
    payload: Optional[Mapping[str, Any]] = None,
    roll_type: str = "",
    dice_skipped: bool = False,
) -> str:
    """
    Return an allowed resolution class, or raise UNRESOLVED_COMBAT_ACTION.

    Non-combat non-irreversible paths may still use legacy NO_ROLL without
    combat resolution_class (caller decides).
    """
    payload = dict(payload or {})
    irreversible = is_irreversible_candidate(
        action_id, target, in_combat=in_combat, payload=payload,
    )
    declared = str(
        resolution_class
        or payload.get("resolution_class")
        or ""
    ).upper()

    if declared in {ROLL, EXPLICIT_NO_ROLL, DETERMINISTIC_RULE}:
        if declared == EXPLICIT_NO_ROLL:
            validate_explicit_no_roll({**payload, "resolution_class": declared})
        return declared

    # Infer ROLL from an actual dice path.
    if roll_type and roll_type not in {"none", "no_roll", "auto_success", "blocked", ""} and not dice_skipped:
        return ROLL
    if roll_type == "auto_success" and not irreversible and not in_combat:
        return DETERMINISTIC_RULE

    if irreversible or in_combat:
        # Combat / irreversible must never fall through to implicit success.
        raise CombatResolutionError(
            UNRESOLVED_COMBAT_ACTION,
            "combat state-changing action requires ROLL, EXPLICIT_NO_ROLL, or DETERMINISTIC_RULE",
        )
    return ""


def may_define_kill_route(fact_origin: str, may_define: bool = False) -> bool:
    if not may_define:
        return False
    return str(fact_origin or "").upper() == SOURCE


def validate_kill_route_authority(world_fact: Mapping[str, Any]) -> None:
    """Kill-route authority must be SOURCE; transforms may only cite source_ref.rule_id."""
    origin = str(world_fact.get("fact_origin") or "").upper()
    route = str(world_fact.get("validated_kill_route_id") or "").upper()
    if route and route not in VALID_KILL_ROUTES:
        raise CombatResolutionError(
            "INVALID_KILL_ROUTE",
            f"unknown validated_kill_route_id: {route}",
        )
    if world_fact.get("may_define_kill_route") and origin != SOURCE:
        raise CombatResolutionError(
            "KILL_ROUTE_AUTHORITY_NON_SOURCE",
            "may_define_kill_route requires fact_origin=SOURCE",
        )
    if origin == ADAPTATION_TRANSFORM:
        source_ref = world_fact.get("source_ref") or {}
        if not str(source_ref.get("rule_id") or "").strip():
            raise CombatResolutionError(
                "SCENARIO_SOURCE_PROVENANCE_MISSING",
                "ADAPTATION_TRANSFORM requires source_ref.rule_id",
            )
        if world_fact.get("may_define_kill_route"):
            raise CombatResolutionError(
                "KILL_ROUTE_AUTHORITY_NON_SOURCE",
                "ADAPTATION_TRANSFORM cannot define a kill route",
            )


def validate_victory_provenance(world_fact: Mapping[str, Any]) -> None:
    """Victory-critical world_fact must carry SOURCE chain + validated kill route."""
    if not world_fact:
        raise CombatResolutionError(
            "SCENARIO_SOURCE_PROVENANCE_MISSING",
            "victory-critical world_fact missing",
        )
    route = str(world_fact.get("validated_kill_route_id") or "").upper()
    if route not in VALID_KILL_ROUTES:
        raise CombatResolutionError(
            "SPECIAL_OBJECTIVE_WITHOUT_VALIDATED_KILL_ROUTE",
            "SPECIAL_OBJECTIVE requires validated_kill_route_id",
        )
    origin = str(world_fact.get("fact_origin") or "").upper()
    if origin == SOURCE:
        if not str(world_fact.get("source_rule_id") or (world_fact.get("source_ref") or {}).get("rule_id") or "").strip():
            # Allow source_rule_id at top level OR nested source_ref.rule_id
            raise CombatResolutionError(
                "SCENARIO_SOURCE_PROVENANCE_MISSING",
                "SOURCE kill fact requires source_rule_id",
            )
        return
    if origin == ADAPTATION_TRANSFORM:
        validate_kill_route_authority(world_fact)
        # Transform must still resolve to a SOURCE rule_id (cited).
        return
    raise CombatResolutionError(
        "SCENARIO_SOURCE_PROVENANCE_MISSING",
        f"victory-critical fact_origin must be SOURCE (got {origin or '<missing>'})",
    )


def is_corbitt_victory_critical(payload: Mapping[str, Any]) -> bool:
    """True only for Corbitt finale SO / kill-route combat_end (not generic SO)."""
    world_fact = payload.get("world_fact") or {}
    fact = str(world_fact.get("fact") or "").upper()
    target = str(
        world_fact.get("target") or payload.get("target") or ""
    ).lower()
    if world_fact.get("validated_kill_route_id"):
        return True
    if fact == "CORBITT_BODY_DESTROYED":
        return True
    if target in {"corbitt_body", "walter_corbitt"}:
        if str(world_fact.get("event") or "").upper() == "SPECIAL_OBJECTIVE_COMPLETED":
            return True
        if payload.get("combat_end") or (payload.get("flag_updates") or {}).get("corbitt_defeated"):
            return True
    if (payload.get("flag_updates") or {}).get("corbitt_defeated") is True:
        return True
    return False


def guard_special_objective_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Validate Corbitt victory-critical payloads before mutation."""
    if is_corbitt_victory_critical(payload):
        validate_victory_provenance(payload.get("world_fact") or {})
    return payload


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return bool(value)
    return True
