"""Source-faithful Corbitt kill routes (Route A HP0 / Route B dagger)."""
from __future__ import annotations

import copy
from typing import Any, Mapping, MutableMapping, Optional

ROUTE_A_HP0 = "ROUTE_A_HP0"
ROUTE_B_DAGGER = "ROUTE_B_DAGGER"
CORBITT_NPC_ID = "walter_corbitt"
CORBITT_BODY_ID = "corbitt_body"
DAGGER_OBJECT_IDS = frozenset({"corbitt_knife", "corbitt_floating_dagger"})
BREAK_REMAP_ACTIONS = frozenset({"break", "force", "kick", "push"})
SOURCE_RULE_HP0 = "CORBITT_HP0_DUST"
SOURCE_RULE_DAGGER = "DAGGER_SPECIAL_KILL_SOURCE_P34"


def source_world_fact(*, route: str, cause_event_ids=None, resolution_reason: str = "") -> dict:
    route = str(route or "").upper()
    if route == ROUTE_A_HP0:
        rule = SOURCE_RULE_HP0
        reason = resolution_reason or "DERIVED_AFTER_VALIDATED_KILL"
    elif route == ROUTE_B_DAGGER:
        rule = SOURCE_RULE_DAGGER
        reason = resolution_reason or "DAGGER_SPECIAL_KILL_SOURCE_P34"
    else:
        raise ValueError(f"unknown kill route: {route}")
    return {
        "event": "SPECIAL_OBJECTIVE_COMPLETED",
        "target": CORBITT_BODY_ID,
        "fact": "CORBITT_BODY_DESTROYED",
        "validated_kill_route_id": route,
        "fact_origin": "SOURCE",
        "source_rule_id": rule,
        "may_define_kill_route": True,
        "cause_event_ids": list(cause_event_ids or []),
        "resolution_reason": reason,
    }


def is_corbitt_npc(char_id: str) -> bool:
    return str(char_id or "").lower() == CORBITT_NPC_ID


def is_magic_dagger_weapon(weapon: Optional[Mapping[str, Any]]) -> bool:
    if not weapon:
        return False
    wid = str(weapon.get("id") or weapon.get("weapon_id") or "").lower()
    name = str(weapon.get("name") or "").lower()
    if wid in DAGGER_OBJECT_IDS or "dagger" in wid or "knife" in wid:
        return True
    if "ダガー" in name or "dagger" in name or "ナイフ" in name:
        return True
    return bool(weapon.get("magic_dagger") or weapon.get("corbitt_special_kill"))


def dagger_object_state(scenario_mgr) -> dict:
    flags = getattr(scenario_mgr, "flags", None) or {}
    states = flags.get("object_states") or {}
    for oid in ("corbitt_knife", "corbitt_floating_dagger"):
        row = states.get(oid)
        if isinstance(row, dict) and row:
            return dict(row)
    return {}


def pc_controls_magic_dagger(scenario_mgr, pc_id: str) -> bool:
    state = dagger_object_state(scenario_mgr)
    if str(state.get("status") or "").upper() != "OWNED":
        return False
    return str(state.get("owner_id") or "") == str(pc_id or "")


def should_remap_body_break(
    action_id: str,
    target: str,
    *,
    scenario_mgr=None,
) -> bool:
    action = str(action_id or "").lower()
    tgt = str(target or "").lower()
    if action not in BREAK_REMAP_ACTIONS or tgt != CORBITT_BODY_ID:
        return False
    flags = getattr(scenario_mgr, "flags", None) or {}
    if flags.get("corbitt_defeated"):
        return False
    return True


def remap_body_break_to_attack(action_id: str, target: str, *, scenario_mgr=None) -> dict:
    """Pre-defeat break|force|kick|push on corbitt_body → attack walter_corbitt."""
    if not should_remap_body_break(action_id, target, scenario_mgr=scenario_mgr):
        return {
            "remapped": False,
            "action_id": action_id,
            "target": target,
        }
    return {
        "remapped": True,
        "action_id": "attack",
        "target": CORBITT_NPC_ID,
        "skill": "近接戦闘",
        "original_action_id": str(action_id or "").lower(),
        "original_target": str(target or "").lower(),
        "remap_reason": "ACTION_REMAPPED",
        "remap_rule_id": "CORBITT_BODY_BREAK_TO_ATTACK",
    }


def armor_applied_fields(
    *,
    armor_before: int,
    armor_after: int,
    raw_damage: int,
    penetrating: int,
    mitigated: int,
    hp_before: int,
    hp_after: int,
) -> dict:
    return {
        "event_type": "ARMOR_APPLIED",
        "armor_before": int(armor_before),
        "armor_after": int(armor_after),
        "raw_damage": int(raw_damage),
        "penetrating_damage": int(penetrating),
        "armor_mitigated": int(mitigated),
        "hp_before": int(hp_before),
        "hp_after": int(hp_after),
    }


def build_derived_so_payload(
    *,
    route: str,
    adjudication_id: str = "",
    cause_event_ids=None,
    selected_action: str = "attack",
) -> dict:
    world_fact = source_world_fact(route=route, cause_event_ids=cause_event_ids)
    reason = world_fact.pop("resolution_reason")
    return {
        "combat_end": True,
        "flag_updates": {"corbitt_defeated": True},
        "new_phase": "clear",
        "completion_phase_deferred": "clear",
        "world_fact": world_fact,
        "human_readable_description": "ウォルター・コービットの遺体が灰と化し、屋敷の呪いが解けた。",
        "resolution_reason": reason,
        "resolution_class": "DETERMINISTIC_RULE",
        "resolution_mode": "NO_ROLL",
        "adjudication_id": adjudication_id,
        "selected_action": selected_action,
        "target": CORBITT_BODY_ID,
        "validated_kill_route_id": route,
        "san_check": {"required": False},
        "system_log": (
            "ウォルター・コービットの遺体が灰と化し、屋敷の呪いが解けた。"
            if route == ROUTE_A_HP0
            else "魔法のダガーがコービットを貫き、遺体は灰となって崩れ落ちた。"
        ),
        "kp_instruction": "コービット討伐とシナリオクリアを劇的に描写して、セッションを締めくくってください。",
    }


def try_route_b_on_hit(
    *,
    attacker_id: str,
    defender_id: str,
    weapon: Optional[Mapping[str, Any]],
    scenario_mgr,
) -> Optional[dict]:
    """Return derived SO payload when magic-dagger special kill should fire."""
    if not is_corbitt_npc(defender_id):
        return None
    if not (is_magic_dagger_weapon(weapon) or pc_controls_magic_dagger(scenario_mgr, attacker_id)):
        return None
    if not pc_controls_magic_dagger(scenario_mgr, attacker_id) and not is_magic_dagger_weapon(weapon):
        return None
    # Require OWNED control for Route B (source: wrest + stab).
    if not pc_controls_magic_dagger(scenario_mgr, attacker_id):
        return None
    return build_derived_so_payload(
        route=ROUTE_B_DAGGER,
        selected_action="attack",
        cause_event_ids=["CORBITT_DAGGER_SPECIAL_KILL"],
    )


def try_route_a_on_hp0(*, defender_id: str, new_hp: int, adjudication_id: str = "") -> Optional[dict]:
    if not is_corbitt_npc(defender_id):
        return None
    if int(new_hp) > 0:
        return None
    return build_derived_so_payload(
        route=ROUTE_A_HP0,
        adjudication_id=adjudication_id,
        selected_action="attack",
        cause_event_ids=["CORBITT_HP_DEPLETED", "CORBITT_BODY_DESTROYED"],
    )


def apply_kill_payload_to_scenario(scenario_mgr, payload: Mapping[str, Any]) -> None:
    if not scenario_mgr or not payload:
        return
    flags = getattr(scenario_mgr, "flags", None)
    if flags is None:
        return
    for key, value in (payload.get("flag_updates") or {}).items():
        flags[key] = value
    if payload.get("completion_phase_deferred") == "clear":
        # Defer clear publish to CompletionAtomicity; keep phase until commit.
        pass
    elif payload.get("new_phase"):
        scenario_mgr.current_phase = payload["new_phase"]


def grant_dagger_ownership(scenario_mgr, owner_id: str, object_id: str = "corbitt_knife") -> dict:
    """Transition dagger to OWNED by PC (via ON_FLOOR / INCAPACITATED path)."""
    from ObjectLifecycle import apply_object_transition

    flags = getattr(scenario_mgr, "flags", None)
    if flags is None:
        raise ValueError("scenario flags missing")
    states = flags.setdefault("object_states", {})
    current = dict(states.get(object_id) or {"object_id": object_id, "status": "ON_FLOOR"})
    status = str(current.get("status") or "ON_FLOOR").upper()
    path = []
    if status == "IN_COMBAT":
        path = ["INCAPACITATED", "ON_FLOOR", "OWNED"]
    elif status == "INCAPACITATED":
        path = ["ON_FLOOR", "OWNED"]
    elif status == "AVAILABLE":
        path = ["ON_FLOOR", "OWNED"]
    elif status == "ON_FLOOR":
        path = ["OWNED"]
    elif status == "OWNED":
        path = ["OWNED"]
    else:
        path = ["ON_FLOOR", "OWNED"]
    return apply_object_transition(
        states,
        object_id,
        {
            "status": "OWNED",
            "owner_id": owner_id,
            "exists": True,
            "available": False,
            "transition_path": path,
        },
    )
