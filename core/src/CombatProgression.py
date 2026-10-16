from __future__ import annotations

import copy
from EventIdentity import append_unified_event
import re


COMBAT_INACTIVE = "INACTIVE"
COMBAT_STARTING = "STARTING"
COMBAT_ACTIVE = "ACTIVE"
COMBAT_ENDING = "ENDING"
COMBAT_ENDED = "ENDED"

COMBAT_EVENT_TYPES = {
    "COMBAT_STARTED",
    "COMBAT_ROUND_STARTED",
    "COMBAT_ACTION_SELECTED",
    "COMBAT_ACTION_RESOLVED",
    "COMBAT_ACTION_REJECTED",
    "COMBATANT_INCAPACITATED",
    "ESCAPE_ATTEMPT",
    "ESCAPE_SUCCESS",
    "COMBAT_ENDING",
    "COMBAT_ENDED",
    "COMBAT_LOCATION_INCONSISTENCY",
    "NORMAL_PROGRESSION_RESUMED",
    "POST_COMBAT_RECOVERY_FAILURE",
    "SPECIAL_OBJECTIVE_COMPLETED",
}

SPECIAL_OBJECTIVE_EVENT_TYPE = "SPECIAL_OBJECTIVE_COMPLETED"
COMBAT_RESOLUTION_EVENTS = {
    "COMBAT_ACTION_RESOLVED", "ESCAPE_ATTEMPT", "SPECIAL_OBJECTIVE_COMPLETED",
}

NORMAL_ACTIONS_FORBIDDEN_IN_COMBAT = {
    "search", "inspect", "read", "talk", "persuade", "fast_talk",
    "charm", "intimidate", "move", "wait", "none", "",
}
ATTACK_ACTIONS = {"attack", "shoot", "fire", "gunshot"}
ESCAPE_ACTIONS = {"escape", "flee"}


def combat_is_active(state_mgr) -> bool:
    if not state_mgr:
        return False
    state = str(getattr(state_mgr, "combat_state", "") or "").upper()
    return bool(getattr(state_mgr, "in_combat", False)) and state in {
        "", COMBAT_STARTING, COMBAT_ACTIVE,
    }


def _event_action_target(condition: str):
    condition = str(condition or "")
    actions = []
    list_match = re.search(r"action_id\s+in\s+\[([^\]]+)\]", condition)
    if list_match:
        actions = re.findall(r"['\"]([^'\"]+)['\"]", list_match.group(1))
    else:
        one = re.search(r"action_id\s*==\s*['\"]([^'\"]+)['\"]", condition)
        if one:
            actions = [one.group(1)]
    target_match = re.search(r"target\s*==\s*['\"]([^'\"]+)['\"]", condition)
    location_match = re.search(r"location\s*==\s*['\"]([^'\"]+)['\"]", condition)
    return actions, target_match.group(1) if target_match else "", location_match.group(1) if location_match else ""


def _scenario_special_candidates(scenario_mgr, current_location: str):
    data = getattr(scenario_mgr, "scenario_data", None) or {}
    candidates = []
    for event in (data.get("event_triggers") or data.get("events") or []):
        payload = event.get("payload") or {}
        if not payload.get("combat_end"):
            continue
        actions, target, location = _event_action_target(event.get("trigger_condition"))
        if location and location != current_location:
            continue
        if not target:
            continue
        for action in actions:
            candidates.append({
                "action": action,
                "target": target,
                "skill": "",
                "category": "SPECIAL",
                "combat_goal": "SPECIAL_OBJECTIVE",
                "source_event_id": event.get("event_id") or "",
                "priority": 100,
            })
    return candidates


def _combat_escape_candidates(scenario_mgr, current_location: str):
    data = getattr(scenario_mgr, "scenario_data", None) or {}
    loc = (data.get("locations") or {}).get(current_location) or {}
    candidates = []
    exits = loc.get("exits") or {}
    for destination, info in exits.items():
        info = info or {}
        if not (info.get("combat_escape") or info.get("allow_during_combat")):
            continue
        candidates.append({
            "action": "escape",
            "target": destination,
            "skill": str(info.get("escape_skill") or "回避"),
            "category": "ESCAPE",
            "combat_goal": "ESCAPE",
            "priority": 60,
        })
    return candidates


def build_combat_action_candidates(
    state_mgr,
    char_mgr,
    scenario_mgr,
    actor_id: str,
    current_location: str,
    *,
    active_pc_ids=None,
):
    """Build legal high-level choices without replacing the existing combat resolver."""
    if not combat_is_active(state_mgr):
        return []
    if actor_id != state_mgr.get_current_actor():
        return []
    if state_mgr.is_combat_participant_incapacitated(actor_id):
        return []

    active_pcs = set(active_pc_ids or [])
    actor_is_pc = actor_id in active_pcs
    enemies = []
    for cid in state_mgr.get_combat_turn_queue():
        if cid == actor_id or state_mgr.is_combat_participant_incapacitated(cid):
            continue
        cid_is_pc = cid in active_pcs
        if cid_is_pc != actor_is_pc:
            enemies.append(cid)

    candidates = _scenario_special_candidates(scenario_mgr, current_location)
    for enemy_id in enemies:
        candidates.append({
            "action": "attack", "target": enemy_id, "skill": "",
            "category": "ATTACK", "combat_goal": "ENEMY_DEFEATED", "priority": 80,
        })
        firearm = state_mgr.get_default_firearm_weapon(actor_id)
        if firearm:
            candidates.append({
                "action": "shoot", "target": enemy_id,
                "skill": str(firearm.get("skill") or "射撃（拳銃）"),
                "category": "ATTACK", "combat_goal": "ENEMY_DEFEATED", "priority": 75,
            })
    candidates.extend(_combat_escape_candidates(scenario_mgr, current_location))

    rejected = set(getattr(state_mgr, "combat_illegal_actions", []) or [])
    unique = []
    seen = set()
    for candidate in sorted(candidates, key=lambda item: int(item.get("priority") or 0), reverse=True):
        signature = f"{candidate.get('action')}:{candidate.get('target')}"
        if signature in seen or signature in rejected:
            continue
        seen.add(signature)
        unique.append(candidate)
    return unique


def validate_combat_action(action, candidates):
    action_id = str((action or {}).get("action") or "").strip().lower()
    target = str((action or {}).get("target") or "").strip()
    legal = {
        (str(item.get("action") or "").lower(), str(item.get("target") or "")): item
        for item in candidates or []
    }
    if (action_id, target) in legal:
        return {"legal": True, "candidate": legal[(action_id, target)], "reason": ""}
    if action_id == "move":
        reason = "normal_location_move_forbidden_during_combat"
    elif action_id in NORMAL_ACTIONS_FORBIDDEN_IN_COMBAT:
        reason = "normal_action_forbidden_during_combat"
    elif action_id in ATTACK_ACTIONS:
        reason = "invalid_or_incapacitated_combat_target"
    elif action_id in ESCAPE_ACTIONS:
        reason = "escape_route_not_available"
    else:
        reason = "illegal_combat_action"
    return {"legal": False, "candidate": None, "reason": reason}


def guide_combat_action(action, candidates, *, state_mgr=None):
    verdict = validate_combat_action(action, candidates)
    if verdict["legal"]:
        guided = dict(action or {})
        guided.pop("needs_pl_retry", None)
        guided.pop("validation_error", None)
        guided.pop("validation_error_code", None)
        guided.pop("suggested_fix", None)
        guided["combat_action_category"] = verdict["candidate"].get("category")
        guided["combat_goal"] = verdict["candidate"].get("combat_goal")
        guided["combat_legality"] = "LEGAL"
        return guided, verdict
    signature = f"{(action or {}).get('action', '')}:{(action or {}).get('target', '')}"
    if state_mgr is not None:
        rejected = list(getattr(state_mgr, "combat_illegal_actions", []) or [])
        if signature not in rejected:
            rejected.append(signature)
        state_mgr.combat_illegal_actions = rejected[-20:]
    if not candidates:
        rejected_action = dict(action or {})
        rejected_action.update({
            "combat_legality": "ILLEGAL",
            "combat_rejection_reason": verdict["reason"],
            "needs_pl_retry": True,
        })
        return rejected_action, verdict
    choice = dict(candidates[0])
    guided = dict(action or {})
    guided.update({
        "action": choice.get("action"),
        "target": choice.get("target"),
        "skill": choice.get("skill") or "",
        "combat_action_category": choice.get("category"),
        "combat_goal": choice.get("combat_goal"),
        "combat_legality": "LEGAL",
        "combat_guided": True,
        "director_guided": True,
        "intervention_level": "COMBAT",
        "intervention_reason": [verdict["reason"]],
    })
    guided.pop("needs_pl_retry", None)
    guided.pop("validation_error", None)
    guided.pop("validation_error_code", None)
    guided.pop("suggested_fix", None)
    return guided, verdict


def combat_prompt_block(candidates, state_mgr, char_mgr):
    actor = state_mgr.get_current_actor() if state_mgr else ""
    actor_name = (
        (char_mgr.characters.get(actor) or {}).get("profile", {}).get("name", actor)
        if char_mgr and actor else actor
    )
    rows = []
    for item in candidates or []:
        rows.append(
            f"- {item.get('category')}: action={item.get('action')} / "
            f"target={item.get('target')} / skill={item.get('skill') or '(自動選択)'}"
        )
    options = "\n".join(rows) or "- 有効な戦闘候補なし（システムへ再判定を要求）"
    return (
        "【戦闘ACTIVE・最優先】通常探索、search、inspect、talk、wait、通常moveは禁止。\n"
        f"現在の手番: {actor_name} / ラウンド: {getattr(state_mgr, 'round_number', 0)}\n"
        "以下の合法候補から1つを、その action と target を変えずに選ぶこと。\n"
        f"{options}\n"
    )


def append_combat_event(state, event_type: str, *, state_mgr=None, **fields):
    if event_type not in COMBAT_EVENT_TYPES:
        raise ValueError(f"unknown combat event type: {event_type}")
    unified = state.setdefault("unified_event_log", [])
    if event_type == SPECIAL_OBJECTIVE_EVENT_TYPE:
        world_fact = fields.get("world_fact")
        adjudication_id = str(fields.get("adjudication_id") or "").strip()
        combat_id = str(fields.get("combat_id") or getattr(state_mgr, "combat_id", "") or "").strip()
        target = str(fields.get("target") or "").strip()
        if not isinstance(world_fact, dict):
            raise ValueError("invalid SPECIAL_OBJECTIVE_COMPLETED payload: world_fact required")
        if str(world_fact.get("event") or "") != SPECIAL_OBJECTIVE_EVENT_TYPE:
            raise ValueError("invalid SPECIAL_OBJECTIVE_COMPLETED payload: world_fact.event mismatch")
        if not str(world_fact.get("fact") or "").strip():
            raise ValueError("invalid SPECIAL_OBJECTIVE_COMPLETED payload: world_fact.fact required")
        if not target or target != str(world_fact.get("target") or "").strip():
            raise ValueError("invalid SPECIAL_OBJECTIVE_COMPLETED payload: target mismatch")
        if not adjudication_id:
            raise ValueError("invalid SPECIAL_OBJECTIVE_COMPLETED payload: adjudication_id required")
        if not combat_id:
            raise ValueError("invalid SPECIAL_OBJECTIVE_COMPLETED payload: combat_id required")
        if any(
            row.get("event_type") == event_type
            and str(row.get("combat_id") or "") == combat_id
            and str(row.get("adjudication_id") or "") == adjudication_id
            and str(row.get("target") or "") == target
            for row in unified
        ):
            return None
    transaction_id = str(fields.get("transaction_id") or "")
    if transaction_id and any(
        row.get("event_type") == event_type
        and str(row.get("transaction_id") or "") == transaction_id
        for row in unified[-100:]
    ):
        return None
    action_origin = fields.pop("action_origin", "AUTONOMOUS")
    resolution_mode = fields.pop("resolution_mode", None)
    explicit_resolution_mode = resolution_mode is not None
    if event_type not in COMBAT_RESOLUTION_EVENTS:
        resolution_mode = None
    elif not resolution_mode and fields.get("roll") is not None:
        resolution_mode = "ROLL"
    if resolution_mode:
        from AdjudicationEvidence import normalize_modifier, validate_evidence
        if str(resolution_mode).upper() == "ROLL":
            fields.setdefault("skill_or_stat", fields.get("skill"))
            fields["modifier"] = normalize_modifier(fields.get("modifier"))
        try:
            validate_evidence({"resolution_mode": resolution_mode, **fields})
            fields["evidence_contract_status"] = "COMPLETE"
        except ValueError:
            if explicit_resolution_mode:
                raise
            # Compatibility for historical callers.  New producers must pass
            # resolution_mode explicitly and therefore fail closed above.
            fields["evidence_contract_status"] = "LEGACY_INCOMPLETE"
    event = {
        "turn_id": len(unified) + 1,
        "event_type": event_type,
        "event_id": fields.pop("event_id", None),
        "adjudication_id": fields.pop("adjudication_id", ""),
        "parent_adjudication_id": fields.pop("parent_adjudication_id", None),
        "interaction_id": fields.pop("interaction_id", ""),
        "combat_id": fields.pop("combat_id", "") or getattr(state_mgr, "combat_id", ""),
        "combat_state": getattr(state_mgr, "combat_state", COMBAT_INACTIVE) if state_mgr else COMBAT_INACTIVE,
        "round": fields.pop("round", None) or getattr(state_mgr, "round_number", 0),
        "actor": fields.pop("actor", ""),
        "actor_state": copy.deepcopy(fields.pop("actor_state", {})),
        "target": fields.pop("target", ""),
        "combat_goal": fields.pop("combat_goal", ""),
        "action_category": fields.pop("action_category", ""),
        "selected_action": fields.pop("selected_action", ""),
        "action_origin": action_origin,
        "legality": fields.pop("legality", "LEGAL"),
        "skill": fields.pop("skill", ""),
        "resolution_mode": resolution_mode,
        "base_target": fields.pop("base_target", None),
        "final_target": fields.pop("final_target", fields.get("target_value")),
        "target_value": fields.pop("target_value", None),
        "roll": fields.pop("roll", None),
        "raw_result": fields.pop("raw_result", None),
        "modifier": copy.deepcopy(fields.pop("modifier", None)),
        "final_result": fields.pop("final_result", None),
        "roll_result": fields.pop("roll_result", None),
        "effect_result": fields.pop("effect_result", None),
        "objective_outcome": fields.pop("objective_outcome", None),
        "result": fields.pop("result", None),
        "damage": fields.pop("damage", None),
        "HP_before": fields.pop("HP_before", None),
        "HP_after": fields.pop("HP_after", None),
        "SAN_before": fields.pop("SAN_before", None),
        "SAN_after": fields.pop("SAN_after", None),
        "position_before": fields.pop("position_before", ""),
        "position_after": fields.pop("position_after", ""),
        "effect": fields.pop("effect", ""),
        "combat_progress_delta": fields.pop("combat_progress_delta", 0),
        "combat_end_condition": fields.pop("combat_end_condition", ""),
        "transaction_id": transaction_id,
        "human_intervention": str(action_origin or "") in {"HUMAN_GUIDED", "HUMAN_FORCED"},
    }
    event.update(fields)
    return append_unified_event(state, event)


def validate_combat_location(state, state_mgr, scenario_mgr):
    if not combat_is_active(state_mgr):
        return {"ok": True}
    canonical = str(getattr(state_mgr, "combat_location_id", "") or "")
    actual = str(getattr(scenario_mgr, "location", "") or state.get("current_loc") or "")
    if not canonical:
        state_mgr.combat_location_id = actual
        return {"ok": True, "canonical": actual}
    if actual == canonical and str(state.get("current_loc") or "") == canonical:
        return {"ok": True, "canonical": canonical}
    state["current_loc"] = canonical
    if scenario_mgr is not None:
        scenario_mgr.location = canonical
    append_combat_event(
        state, "COMBAT_LOCATION_INCONSISTENCY", state_mgr=state_mgr,
        legality="ILLEGAL", position_before=actual, position_after=canonical,
        effect="reconciled_to_combat_location",
    )
    return {"ok": False, "canonical": canonical, "actual": actual}


def evaluate_combat_end(state_mgr, active_pc_ids=None):
    if not combat_is_active(state_mgr):
        return {"ended": True, "reason": getattr(state_mgr, "combat_end_reason", "inactive")}
    pcs = set(active_pc_ids or [])
    capable_pcs = [
        cid for cid in state_mgr.get_combat_turn_queue()
        if cid in pcs and not state_mgr.is_combat_participant_incapacitated(cid)
    ]
    capable_enemies = [
        cid for cid in state_mgr.get_combat_turn_queue()
        if cid not in pcs and not state_mgr.is_combat_participant_incapacitated(cid)
    ]
    if not capable_enemies:
        return {"ended": True, "reason": "enemies_incapacitated"}
    if not capable_pcs:
        return {"ended": True, "reason": "party_incapacitated"}
    return {"ended": False, "reason": ""}


def resolve_escape_action(
    state,
    state_mgr,
    scenario_mgr,
    *,
    actor_id: str,
    destination: str,
    success: bool,
    action_origin="AUTONOMOUS",
    transaction_id="",
):
    current = str(getattr(state_mgr, "combat_location_id", "") or state.get("current_loc") or "")
    candidates = _combat_escape_candidates(scenario_mgr, current)
    legal_destinations = {str(item.get("target") or "") for item in candidates}
    append_combat_event(
        state, "ESCAPE_ATTEMPT", state_mgr=state_mgr,
        actor=actor_id, target=destination, combat_goal="ESCAPE",
        action_category="ESCAPE", selected_action="escape",
        action_origin=action_origin,
        legality="LEGAL" if destination in legal_destinations else "ILLEGAL",
        position_before=current, position_after=current,
        result=bool(success), transaction_id=transaction_id,
    )
    if destination not in legal_destinations:
        return {"ok": False, "reason": "escape_route_not_available"}
    if not success:
        return {"ok": False, "reason": "escape_failed"}
    append_combat_event(
        state, "ESCAPE_SUCCESS", state_mgr=state_mgr,
        actor=actor_id, target=destination, combat_goal="ESCAPE",
        action_category="ESCAPE", selected_action="escape",
        action_origin=action_origin, position_before=current, position_after=destination,
        combat_progress_delta=1, transaction_id=transaction_id,
    )
    append_combat_event(
        state, "COMBAT_ENDING", state_mgr=state_mgr,
        actor=actor_id, combat_end_condition="escape_success",
        position_before=current, position_after=destination,
    )
    state_mgr.end_combat("escape_success")
    state["current_loc"] = destination
    scenario_mgr.location = destination
    append_combat_event(
        state, "COMBAT_ENDED", state_mgr=state_mgr,
        actor=actor_id, combat_end_condition="escape_success",
        position_before=current, position_after=destination,
        effect="normal progression may resume",
    )
    return {"ok": True, "new_location": destination, "combat_ended": True}
