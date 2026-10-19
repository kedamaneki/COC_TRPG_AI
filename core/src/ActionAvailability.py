"""Single-source action availability contract.

Candidate generation and execution both call this module.  It deliberately
delegates rule enforcement to ScenarioManager's existing pre-action guard so
the candidate side becomes as strict as the executor side.
"""
from __future__ import annotations

import copy
from EventIdentity import append_unified_event
import hashlib
import json

from InvestigationFlow import (
    INVESTIGATION_ACTIONS,
    check_attempt_right,
    context_version as investigation_context_version,
)


AVAILABLE = "AVAILABLE"
BLOCKED = "BLOCKED"
CONDITIONALLY_AVAILABLE = "CONDITIONALLY_AVAILABLE"

AVAILABILITY_EVENT_TYPES = frozenset({
    "ACTION_AVAILABILITY_CHECKED",
    "ACTION_BLOCKED",
    "ACTION_AVAILABILITY_DRIFT",
    "ACTION_AVAILABILITY_CONTRACT_VIOLATION",
    "SCENARIO_RUNTIME_AVAILABILITY_CONFLICT",
    "NO_AVAILABLE_PROGRESS_ACTION",
    "REACHABLE_FRONTIER_EXHAUSTED",
})


def action_context_version(state, scenario_mgr, actor="", location=""):
    """Stable fingerprint for state relevant to action execution."""
    state = state if isinstance(state, dict) else {}
    location = str(location or state.get("current_loc") or getattr(scenario_mgr, "location", "") or "")
    actor_state = {}
    char_mgr = state.get("char_mgr")
    if char_mgr and hasattr(char_mgr, "get_character") and actor:
        try:
            actor_state = copy.deepcopy(char_mgr.get_character(actor) or {})
        except Exception:
            actor_state = {}
    raw = {
        "location": location,
        "phase": str(getattr(scenario_mgr, "current_phase", "") or ""),
        "flags": copy.deepcopy(getattr(scenario_mgr, "flags", {}) or {}),
        "combat": bool(state.get("in_combat")),
        "actor": str(actor or ""),
        "actor_state": actor_state,
        "pending_san": bool(state.get("pending_san_check")),
    }
    digest = hashlib.sha1(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"action:{location}:{digest}"


def _reason_from_block(block, action, target, scenario_mgr, location):
    text = " ".join(str(block.get(k) or "") for k in ("system_log", "log", "kp_instruction"))
    if action == "move":
        return "BLOCKED_SCENARIO_CONDITION"
    if target and not scenario_mgr.get_object_info(location, target):
        return "BLOCKED_WRONG_LOCATION"
    if "調査済み" in text or "再確認" in text or "試行権" in text:
        return "BLOCKED_ATTEMPT_EXHAUSTED"
    if "アイテム" in text or "所持" in text:
        return "BLOCKED_MISSING_ITEM"
    if "戦闘" in text:
        return "BLOCKED_COMBAT_STATE"
    if "条件" in text or "状態" in text or "地階" in text:
        return "BLOCKED_STATE_CONFLICT"
    return "BLOCKED_TARGET_UNAVAILABLE"


def _append_event(state, event_type, result, *, candidate_status="", state_change=None):
    if not isinstance(state, dict):
        return None
    row = {
        "event_type": event_type,
        "actor": result.get("actor", ""),
        "action": result.get("action", ""),
        "target": result.get("target", ""),
        "status": result.get("status", ""),
        "reason_code": result.get("reason_code", ""),
        "reason_detail": result.get("reason_detail", ""),
        "context_version": result.get("context_version", ""),
        "cycle": state.get("evaluation_cycle", state.get("cycle", "")),
        "turn": state.get("turn", state.get("turn_count", "")),
        "location": result.get("location", ""),
        "required_location": result.get("required_location", ""),
        "scene": str(state.get("current_scene_id") or ""),
        "scenario_id": result.get("scenario_id", ""),
        "goal": str((((state.get("director_v2") or {}).get("goal") or {}).get("current_goal")) or ""),
        "source": result.get("source", ""),
    }
    if candidate_status:
        row["candidate_time_status"] = candidate_status
        row["execution_time_status"] = result.get("status", "")
    if state_change is not None:
        row["state_change"] = state_change
    return append_unified_event(state, row)


def check_action_availability(
    scenario_mgr,
    *,
    actor="",
    action="",
    target="",
    location="",
    state=None,
    source="autonomous",
    skill="",
    pending_san_check=None,
    required_location="",
    log_events=False,
):
    """Return an availability decision using the executor's guard rules."""
    state = state if isinstance(state, dict) else {}
    action = str(action or "").lower()
    target = str(target or "").strip()
    location = str(location or state.get("current_loc") or getattr(scenario_mgr, "location", "") or "")
    required_location = str(required_location or "")
    ctx = action_context_version(state, scenario_mgr, actor=actor, location=location)
    result = {
        "status": AVAILABLE,
        "reason_code": "AVAILABLE",
        "reason_detail": "",
        "required_preconditions": [],
        "context_version": ctx,
        "actor": str(actor or ""),
        "action": action,
        "target": target,
        "location": location,
        "required_location": required_location,
        "source": str(source or "autonomous").lower(),
        "scenario_runtime_conflict": False,
        "scenario_id": str(
            ((getattr(scenario_mgr, "meta", {}) or {}).get("id"))
            or ((getattr(scenario_mgr, "meta", {}) or {}).get("scenario_id"))
            or ""
        ),
    }
    if required_location and location != required_location:
        result.update({
            "status": BLOCKED,
            "reason_code": "REQUIRES_RETURN",
            "reason_detail": (
                f"This action requires location `{required_location}`; "
                f"the current location is `{location}`."
            ),
            "required_preconditions": [f"location:{required_location}"],
        })
        if log_events:
            _append_event(state, "ACTION_AVAILABILITY_CHECKED", result)
            _append_event(state, "ACTION_BLOCKED", result)
        return result
    if not scenario_mgr or not hasattr(scenario_mgr, "evaluate_pre_action_guard"):
        return result

    obj = scenario_mgr.get_object_info(location, target) if target else {}
    req = (obj or {}).get("requires_flag")
    req_failed = bool(req) and not scenario_mgr._flag_requirement_met(req, location)
    override = (
        scenario_mgr.find_applicable_action_event(action, target, loc_id=location)
        if req_failed and hasattr(scenario_mgr, "find_applicable_action_event") else None
    )
    if override:
        result.update({
            "reason_code": "SCENARIO_ACTION_OVERRIDE",
            "reason_detail": "A specific active scenario event permits the action despite a coarse object guard.",
            "scenario_runtime_conflict": True,
            "scenario_event_id": str(override.get("event_id") or ""),
            "scenario_condition": str(override.get("trigger_condition") or ""),
            "runtime_guard": f"requires_flag:{req}",
        })

    block = scenario_mgr.evaluate_pre_action_guard(
        action, target, loc_id=location, pending_san_check=pending_san_check,
    ) or {}
    if block.get("blocked"):
        code = _reason_from_block(block, action, target, scenario_mgr, location)
        conditional = code in {"BLOCKED_MISSING_ITEM", "BLOCKED_SCENARIO_CONDITION"}
        result.update({
            "status": CONDITIONALLY_AVAILABLE if conditional else BLOCKED,
            "reason_code": code,
            "reason_detail": str(block.get("system_log") or block.get("log") or ""),
            "required_preconditions": [str((obj or {}).get("requires_flag") or code)] if conditional else [],
            "no_roll": bool(block.get("no_roll")),
        })

    if result["status"] == AVAILABLE and action in INVESTIGATION_ACTIONS and actor and state:
        selected_skill = str(skill or "")
        if not selected_skill:
            try:
                resolved = scenario_mgr.resolve_investigation_skill(
                    action, target, proposed_skill="", loc_id=location,
                ) or {}
                selected_skill = str(resolved.get("skill_name") or "")
            except Exception:
                selected_skill = ""
        version = investigation_context_version(state, scenario_mgr, location, target)
        right = check_attempt_right(state, actor, target, selected_skill, version)
        if not right.get("allowed"):
            result.update({
                "status": BLOCKED,
                "reason_code": "BLOCKED_ATTEMPT_EXHAUSTED",
                "reason_detail": str(right.get("reason") or ""),
                "investigation_context_version": version,
            })

    if log_events:
        _append_event(state, "ACTION_AVAILABILITY_CHECKED", result)
        if result.get("scenario_runtime_conflict"):
            _append_event(state, "SCENARIO_RUNTIME_AVAILABILITY_CONFLICT", result)
        if result["status"] != AVAILABLE:
            _append_event(state, "ACTION_BLOCKED", result)
            cache = state.setdefault("action_availability_blocked_cache", [])
            key = {
                "actor": result["actor"], "action": action, "target": target,
                "context_version": ctx, "blocked_reason": result["reason_code"],
            }
            if key not in cache:
                cache.append(key)
    return result


def compare_candidate_and_execution(state, candidate_snapshot, execution_result):
    """Record drift or a same-context contract violation."""
    if not isinstance(candidate_snapshot, dict) or not isinstance(state, dict):
        return None
    if candidate_snapshot.get("status") != AVAILABLE or execution_result.get("status") == AVAILABLE:
        return None
    same_context = (
        str(candidate_snapshot.get("context_version") or "")
        == str(execution_result.get("context_version") or "")
    )
    event_type = (
        "ACTION_AVAILABILITY_CONTRACT_VIOLATION"
        if same_context else "ACTION_AVAILABILITY_DRIFT"
    )
    return _append_event(
        state, event_type, execution_result,
        candidate_status=str(candidate_snapshot.get("status") or ""),
        state_change=not same_context,
    )


def filter_available_candidates(goal, scenario_mgr, location, *, actor="", state=None, source="candidate"):
    """Remove non-immediate candidates and stamp availability snapshots."""
    goal = copy.deepcopy(goal or {})
    kept = []
    blocked = []
    for item in goal.get("candidate_next_actions") or []:
        required_location = str(item.get("required_location") or location or "")
        if not scenario_mgr or not hasattr(scenario_mgr, "evaluate_pre_action_guard"):
            stamped = dict(item)
            stamped["required_location"] = required_location
            if required_location and str(location or "") != required_location:
                stamped.update({
                    "reachable": False,
                    "executable": False,
                    "blocked_reason": "REQUIRES_RETURN",
                    "availability_status": BLOCKED,
                    "availability_reason": "REQUIRES_RETURN",
                })
                blocked.append(stamped)
                continue
            stamped["reachable"] = True
            stamped["executable"] = True
            stamped["blocked_reason"] = ""
            stamped.setdefault(
                "adjudication_route",
                f"ACTION_EXECUTOR:{stamped.get('action') or ''}",
            )
            stamped.setdefault("expected_state_effect", {})
            kept.append(stamped)
            continue
        result = check_action_availability(
            scenario_mgr,
            actor=actor,
            action=item.get("action"),
            target=item.get("target"),
            location=location,
            state=state,
            source=source,
            skill=item.get("skill", ""),
            required_location=required_location,
            log_events=False,
        )
        stamped = dict(item)
        stamped["required_location"] = required_location
        stamped["availability_status"] = result["status"]
        stamped["availability_context_version"] = result["context_version"]
        stamped["availability_reason"] = result["reason_code"]
        stamped["availability_snapshot"] = result
        if result["status"] == AVAILABLE:
            stamped["reachable"] = True
            stamped["executable"] = True
            stamped["blocked_reason"] = ""
            stamped.setdefault(
                "adjudication_route",
                f"ACTION_EXECUTOR:{stamped.get('action') or ''}",
            )
            stamped.setdefault("expected_state_effect", {})
            kept.append(stamped)
        else:
            stamped["reachable"] = False
            stamped["executable"] = False
            stamped["blocked_reason"] = result["reason_code"]
            stamped.setdefault(
                "adjudication_route",
                f"ACTION_EXECUTOR:{stamped.get('action') or ''}",
            )
            stamped.setdefault("expected_state_effect", {})
            blocked.append(stamped)
    goal["candidate_next_actions"] = kept
    goal["blocked_candidate_actions"] = blocked
    return goal
