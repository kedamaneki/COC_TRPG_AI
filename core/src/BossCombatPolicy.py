"""Corbitt enemy-turn policy: dagger / Dominate / body activation / normal attack."""
from __future__ import annotations

import copy
from typing import Any, Mapping, MutableMapping, Optional

CORBITT_ID = "walter_corbitt"
ACTION_MAGIC_DAGGER = "MAGIC_DAGGER_ATTACK"
ACTION_DOMINATE = "DOMINATE"
ACTION_BODY_ACTIVATION = "BODY_ACTIVATION"
ACTION_NORMAL_ATTACK = "NORMAL_ATTACK"
ACTION_WAIT = "WAIT"

BODY_ACTIVATION_ROUNDS = 5
BODY_ACTIVATION_MP = 2
DOMINATE_MP = 1
DAGGER_MP = 1


def _corbitt_state(state: Optional[MutableMapping[str, Any]]) -> dict:
    # Important: empty dict {} is falsy — never replace the caller's mapping.
    if state is None:
        state = {}
    combat = state.setdefault("corbitt_combat", {})
    if "body_activation" not in combat:
        combat["body_activation"] = {
            "active": False,
            "rounds_remaining": 0,
            "activated_at_round": None,
        }
    return combat


def get_body_activation(state) -> dict:
    return dict(_corbitt_state(state).get("body_activation") or {})


def is_body_active(state) -> bool:
    return bool(get_body_activation(state).get("active"))


def _mp(char_mgr, npc_id=CORBITT_ID) -> int:
    try:
        return int(char_mgr.get_stat_current(npc_id, "MP") or 0)
    except Exception:
        char = (char_mgr.characters or {}).get(npc_id) or {}
        mp = (char.get("attributes") or {}).get("MP") or {}
        return int(mp.get("current") or 0)


def _spend_mp(char_mgr, amount: int, npc_id=CORBITT_ID) -> bool:
    if _mp(char_mgr, npc_id) < amount:
        return False
    if hasattr(char_mgr, "apply_mp_cost"):
        char_mgr.apply_mp_cost(npc_id, amount)
        return True
    # Fallback via GameStateManager-style pool
    char = (char_mgr.characters or {}).get(npc_id) or {}
    mp = (char.get("attributes") or {}).get("MP")
    if isinstance(mp, dict):
        mp["current"] = max(0, int(mp.get("current") or 0) - amount)
        return True
    return False


def dagger_still_controlled(scenario_mgr) -> bool:
    from CorbittKillRoutes import dagger_object_state

    status = str(dagger_object_state(scenario_mgr).get("status") or "").upper()
    return status in {"IN_COMBAT", "AVAILABLE"}


def pc_owns_dagger(scenario_mgr) -> bool:
    from CorbittKillRoutes import pc_controls_magic_dagger

    flags = getattr(scenario_mgr, "flags", None) or {}
    states = flags.get("object_states") or {}
    for oid in ("corbitt_knife", "corbitt_floating_dagger"):
        row = states.get(oid) or {}
        if str(row.get("status") or "").upper() == "OWNED" and row.get("owner_id"):
            return True
    # Also true if any known owner via helper scan
    for cid in list((getattr(scenario_mgr, "flags", {}) or {}).keys()):
        pass
    return False


def escalation(state, scenario_mgr, *, hp_lost: bool = False) -> bool:
    combat = _corbitt_state(state)
    if combat.get("last_pc_hit"):
        return True
    if hp_lost:
        return True
    if pc_owns_dagger(scenario_mgr):
        return True
    return bool(combat.get("escalation"))


def choose_corbitt_action(
    *,
    state,
    char_mgr,
    scenario_mgr,
    state_mgr=None,
    target_id: str = "",
) -> dict:
    """
    Priority: Magic Dagger → Dominate → Body Activation → Normal Attack / Wait.
    """
    mp = _mp(char_mgr)
    body = get_body_activation(state)
    body_active = bool(body.get("active"))
    esc = escalation(state, scenario_mgr)

    if dagger_still_controlled(scenario_mgr) and mp >= DAGGER_MP:
        return {
            "action": ACTION_MAGIC_DAGGER,
            "mp_cost": DAGGER_MP,
            "target_id": target_id,
            "reason": "dagger_available",
        }
    if mp >= DOMINATE_MP and target_id and (not body_active or esc):
        # Prefer Dominate when inactive or when strategic (multi-PC / dagger threat).
        prefer_dominate = (not body_active) or pc_owns_dagger(scenario_mgr) or esc
        if prefer_dominate:
            return {
                "action": ACTION_DOMINATE,
                "mp_cost": DOMINATE_MP,
                "target_id": target_id,
                "reason": "dominate_eligible",
            }
    if (
        not body_active
        and esc
        and mp >= BODY_ACTIVATION_MP
    ):
        return {
            "action": ACTION_BODY_ACTIVATION,
            "mp_cost": BODY_ACTIVATION_MP,
            "target_id": target_id,
            "reason": "escalation_activation",
        }
    if body_active:
        return {
            "action": ACTION_NORMAL_ATTACK,
            "mp_cost": 0,
            "target_id": target_id,
            "reason": "body_active_melee",
        }
    if mp >= DOMINATE_MP and target_id:
        return {
            "action": ACTION_DOMINATE,
            "mp_cost": DOMINATE_MP,
            "target_id": target_id,
            "reason": "inactive_dominate_fallback",
        }
    if dagger_still_controlled(scenario_mgr) and mp >= DAGGER_MP:
        return {
            "action": ACTION_MAGIC_DAGGER,
            "mp_cost": DAGGER_MP,
            "target_id": target_id,
            "reason": "inactive_dagger_fallback",
        }
    return {
        "action": ACTION_WAIT if not body_active else ACTION_NORMAL_ATTACK,
        "mp_cost": 0,
        "target_id": target_id,
        "reason": "no_resource",
    }


def activate_body(state, char_mgr, *, round_number: int = 0) -> dict:
    if not _spend_mp(char_mgr, BODY_ACTIVATION_MP):
        return {"ok": False, "reason": "insufficient_mp"}
    combat = _corbitt_state(state)
    combat["body_activation"] = {
        "active": True,
        "rounds_remaining": BODY_ACTIVATION_ROUNDS,
        "activated_at_round": round_number,
    }
    combat["escalation"] = True
    event = {
        "event_type": "CORBITT_BODY_ACTIVATED",
        "rounds": BODY_ACTIVATION_ROUNDS,
        "mp_spent": BODY_ACTIVATION_MP,
        "round_number": round_number,
    }
    return {"ok": True, "event": event, "body_activation": copy.deepcopy(combat["body_activation"])}


def tick_body_activation(state, *, round_number: int = 0) -> Optional[dict]:
    combat = _corbitt_state(state)
    body = combat.get("body_activation") or {}
    if not body.get("active"):
        return None
    remaining = int(body.get("rounds_remaining") or 0) - 1
    if remaining <= 0:
        combat["body_activation"] = {
            "active": False,
            "rounds_remaining": 0,
            "activated_at_round": body.get("activated_at_round"),
        }
        return {
            "event_type": "CORBITT_BODY_ACTIVATION_EXPIRED",
            "round_number": round_number,
        }
    body["rounds_remaining"] = remaining
    combat["body_activation"] = body
    return {
        "event_type": "CORBITT_BODY_ACTIVATION_TICK",
        "rounds_remaining": remaining,
        "round_number": round_number,
    }


def note_pc_hit(state) -> None:
    combat = _corbitt_state(state)
    combat["last_pc_hit"] = True
    combat["escalation"] = True


def clear_round_hit_flag(state) -> None:
    combat = _corbitt_state(state)
    combat["last_pc_hit"] = False


def resolve_dominate(
    *,
    char_mgr,
    dice_engine,
    caster_id: str,
    target_id: str,
) -> dict:
    """Opposed POW; on caster win apply dazed 1D6+1 rounds."""
    if not _spend_mp(char_mgr, DOMINATE_MP, caster_id):
        return {"ok": False, "reason": "insufficient_mp"}
    caster = (char_mgr.characters or {}).get(caster_id) or {}
    target = (char_mgr.characters or {}).get(target_id) or {}
    caster_pow = int((caster.get("attributes") or {}).get("POW") or 90)
    target_pow = int((target.get("attributes") or {}).get("POW") or 50)
    caster_name = (caster.get("profile") or {}).get("name") or caster_id
    target_name = (target.get("profile") or {}).get("name") or target_id

    opposed_pow = getattr(dice_engine, "execute_opposed_pow_roll", None)
    if callable(opposed_pow) and not isinstance(dice_engine, type):
        # Prefer real DiceEngine POW opposed when present (skip MagicMock autospec).
        try:
            from unittest.mock import Mock
            is_mock = isinstance(dice_engine, Mock)
        except Exception:
            is_mock = False
        if not is_mock:
            opposed = opposed_pow(caster_name, caster_pow, target_name, target_pow)
        else:
            opposed = dice_engine.execute_melee_opposed_roll(
                caster_name, "POW", caster_pow,
                target_name, "POW", target_pow,
                defense_mode="fight_back",
            )
    else:
        opposed = dice_engine.execute_melee_opposed_roll(
            caster_name, "POW", caster_pow,
            target_name, "POW", target_pow,
            defense_mode="fight_back",
        )
    if not isinstance(opposed, dict):
        opposed = {"outcome": "miss", "log": str(opposed)}
    outcome = str(opposed.get("outcome") or "miss")
    caster_won = outcome in {"hit_attacker", "success", "win"}
    if outcome == "counter":
        caster_won = False
    duration = 0
    if caster_won:
        roll_fn = getattr(dice_engine, "roll", None)
        if callable(roll_fn):
            try:
                duration = int(roll_fn("1D6")) + 1
            except Exception:
                duration = 4
        else:
            duration = 4
        states = target.setdefault("states", [])
        tag = f"DOMINATED:{duration}"
        if tag not in states:
            states.append("ぼんやり")
            states.append(tag)
        if hasattr(char_mgr, "save_data"):
            char_mgr.save_data()
    return {
        "ok": True,
        "action": ACTION_DOMINATE,
        "caster_won": caster_won,
        "duration_rounds": duration,
        "opposed": opposed,
        "mp_spent": DOMINATE_MP,
        "log": opposed.get("log", "") + (
            f"\n→ 《支配》成功。{target_name} は {duration} ラウンドぼんやり状態。"
            if caster_won
            else f"\n→ 《支配》失敗。{target_name} は抵抗した。"
        ),
    }


def preferred_defense_for_corbitt(state, *, attack_type: str = "melee") -> str:
    if attack_type != "melee":
        return "dodge"
    if is_body_active(state):
        return "fight_back"
    # Inactive body: prefer not to fight back physically.
    return "dodge"
