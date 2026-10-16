"""Generic progression policy derived from scenario metadata and current flags."""

from __future__ import annotations

import copy
import re

from ActionAvailability import filter_available_candidates


INFORMATION_ACTIONS = frozenset({
    "search", "inspect", "read", "talk", "psychology", "insight",
})
STATE_CHANGING_ACTIONS = frozenset({
    "move", "use", "break", "force", "push", "pull", "climb", "open", "enter", "kick",
})
_ACTION_IN_RE = re.compile(r"\baction_id\s+in\s+\[([^\]]+)\]")
_ACTION_EQ_RE = re.compile(r"\baction_id\s*==\s*['\"]([^'\"]+)['\"]")
_TARGET_RE = re.compile(r"\btarget\s*==\s*['\"]([^'\"]+)['\"]")
_LOCATION_RE = re.compile(r"\blocation\s*==\s*['\"]([^'\"]+)['\"]")
_FLAG_RE = re.compile(r"\bflags\.([A-Za-z0-9_]+)\s*==\s*(true|false)", re.I)
_QUOTED_RE = re.compile(r"['\"]([^'\"]+)['\"]")
_STATE_ACTION_ORDER = ("use", "open", "enter", "push", "pull", "force", "break", "climb", "kick")
_INFORMATION_ACTION_ORDER = ("search", "inspect", "read", "talk", "psychology", "insight")


def _target_is_required(obj):
    """Return only explicit scenario-author intent; absence means optional."""
    for key in ("required", "required_for_completion", "objective_required"):
        if key in obj:
            return bool(obj.get(key))
    if "optional" in obj:
        return not bool(obj.get("optional"))
    return False


def _requirement_met(scenario_mgr, requirement, location):
    """Delegate flag semantics, including negation and scoped flags, to the scenario SSOT."""
    if not requirement:
        return True
    resolver = getattr(scenario_mgr, "_flag_requirement_met", None)
    if callable(resolver):
        return bool(resolver(str(requirement), location))
    # Compatibility for minimal test doubles. Production uses ScenarioManager above.
    flags = getattr(scenario_mgr, "flags", None) or {}
    requirement = str(requirement)
    return not bool(flags.get(requirement[1:])) if requirement.startswith("!") else bool(flags.get(requirement))


def derive_target_statuses(scenario_mgr, location):
    flags = getattr(scenario_mgr, "flags", None) or {}
    investigated = set(flags.get("investigated_targets") or [])
    info = scenario_mgr.get_location_info(location) if scenario_mgr else {}
    objects = (info or {}).get("objects") or {}
    statuses = {}
    for target, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        requirement = str(obj.get("requires_flag") or "")
        if not _requirement_met(scenario_mgr, requirement, location):
            statuses[str(target)] = (
                "BLOCKED_REQUIRED_OBJECTIVE" if _target_is_required(obj) else "UNAVAILABLE"
            )
            continue
        inv_flag = str(obj.get("investigated_flag") or "")
        done = target in investigated or bool(inv_flag and flags.get(inv_flag))
        usable = {str(x).lower() for x in (obj.get("usable_actions") or [])}
        followup = bool(usable & STATE_CHANGING_ACTIONS)
        effects = dict(obj.get("triggers_flag_on_success") or {})
        for event in getattr(scenario_mgr, "event_triggers", None) or []:
            condition = str(event.get("trigger_condition") or "")
            if f"target == '{target}'" not in condition or f"location == '{location}'" not in condition:
                continue
            actions = set(re.findall(r"['\"]([A-Za-z_]+)['\"]", condition.split("target", 1)[0]))
            if not (actions & STATE_CHANGING_ACTIONS):
                continue
            effects.update((event.get("payload") or {}).get("flag_updates") or {})
        scoped_flags = (
            scenario_mgr._flags_for_location(location)
            if hasattr(scenario_mgr, "_flags_for_location") else flags
        )
        pending_effect = any(
            bool(value) != bool(scoped_flags.get(str(key))) for key, value in effects.items()
        )
        if done and not (followup and pending_effect):
            statuses[str(target)] = "EXHAUSTED"
        elif done:
            statuses[str(target)] = "INVESTIGATED"
        else:
            statuses[str(target)] = "UNSEEN"
    return statuses


def derive_location_objective_status(target_statuses):
    if not target_statuses:
        return "ACTIVE"
    values = list(target_statuses.values())
    if "BLOCKED_REQUIRED_OBJECTIVE" in values:
        return "BLOCKED_REQUIRED_OBJECTIVE"
    available_values = [value for value in values if value != "UNAVAILABLE"]
    if not available_values or all(value == "EXHAUSTED" for value in available_values):
        return "EXHAUSTED"
    if all(value in {"INVESTIGATED", "EXHAUSTED"} for value in available_values):
        return "SATISFIED"
    return "ACTIVE"


def filter_exhausted_candidates(goal, target_statuses, location_status):
    goal = copy.deepcopy(goal or {})
    candidates = []
    for item in goal.get("candidate_next_actions") or []:
        action = str(item.get("action") or "").lower()
        target = str(item.get("target") or "")
        if action in INFORMATION_ACTIONS and target_statuses.get(target) == "EXHAUSTED":
            continue
        candidates.append(item)
    if location_status in {"SATISFIED", "EXHAUSTED"}:
        executable = [
            x for x in candidates
            if str(x.get("action") or "").lower() in STATE_CHANGING_ACTIONS
            and str(x.get("action") or "").lower() != "move"
        ]
        moves = [x for x in candidates if str(x.get("action") or "").lower() == "move"]
        candidates = executable + moves + [
            x for x in candidates if x not in executable and x not in moves
        ]
    goal["candidate_next_actions"] = candidates
    return goal


def _event_state_change_candidates(scenario_mgr, location, target_statuses):
    """Derive executable world-state changes from scenario event metadata."""
    flags = getattr(scenario_mgr, "flags", None) or {}
    scoped_flags = (
        scenario_mgr._flags_for_location(location)
        if hasattr(scenario_mgr, "_flags_for_location") else flags
    )
    candidates = []
    seen = set()
    for event in getattr(scenario_mgr, "event_triggers", None) or []:
        condition = str(event.get("trigger_condition") or "")
        target_match = _TARGET_RE.search(condition)
        location_match = _LOCATION_RE.search(condition)
        target = target_match.group(1) if target_match else ""
        event_location = location_match.group(1) if location_match else ""
        if not target or event_location != location:
            continue
        if target_statuses.get(target) != "INVESTIGATED":
            continue
        action_match = _ACTION_IN_RE.search(condition)
        actions = _QUOTED_RE.findall(action_match.group(1)) if action_match else _ACTION_EQ_RE.findall(condition)
        actions = [str(x).lower() for x in actions if str(x).lower() in STATE_CHANGING_ACTIONS]
        if not actions:
            continue
        requirements_met = all(
            bool(scoped_flags.get(key, False)) == (raw.lower() == "true")
            for key, raw in _FLAG_RE.findall(condition)
        )
        if not requirements_met:
            continue
        payload = event.get("payload") or {}
        effects = payload.get("flag_updates") or {}
        pending_effect = any(
            bool(value) != bool(scoped_flags.get(str(key))) for key, value in effects.items()
        ) or bool(payload.get("new_location")) or bool(payload.get("new_phase"))
        if not pending_effect:
            continue
        ordered = [x for x in _STATE_ACTION_ORDER if x in actions]
        action = (ordered or actions)[0]
        key = (action, target)
        if key in seen:
            continue
        seen.add(key)
        candidates.append({
            "action": action,
            "target": target,
            "skill": "",
            "reason": "state_change_after_investigation",
            "event_id": str(event.get("event_id") or ""),
        })
    return candidates


def _transition_candidates(scenario_mgr, location, runtime=None):
    if not scenario_mgr or not hasattr(scenario_mgr, "get_available_exits"):
        return []
    candidates = [
        {
            "action": "move", "target": str(item.get("id") or ""), "skill": "",
            "reason": "location_objective_complete",
        }
        for item in (scenario_mgr.get_available_exits(location) or [])
        if item.get("id")
    ]
    runtime = runtime or {}
    visited = {str(x) for x in (runtime.get("visited_locations") or [])}
    recent = list((runtime.get("stall") or {}).get("recent_locations") or [])
    previous_distinct = ""
    for item in reversed(recent):
        item = str(item or "")
        if item and item != str(location):
            previous_distinct = item
            break
    candidates.sort(key=lambda item: (
        str(item.get("target") or "") in visited,
        str(item.get("target") or "") == previous_distinct,
        str(item.get("target") or ""),
    ))
    return candidates


def _unseen_information_candidates(scenario_mgr, location, target_statuses):
    info = scenario_mgr.get_location_info(location) if scenario_mgr else {}
    objects = (info or {}).get("objects") or {}
    candidates = []
    seen_investigation_flags = set()
    for target, obj in objects.items():
        if target_statuses.get(str(target)) != "UNSEEN" or not isinstance(obj, dict):
            continue
        investigation_flag = str(obj.get("investigated_flag") or "")
        if investigation_flag and investigation_flag in seen_investigation_flags:
            continue
        if investigation_flag:
            seen_investigation_flags.add(investigation_flag)
        usable = {str(x).lower() for x in (obj.get("usable_actions") or [])}
        ordered = [x for x in _INFORMATION_ACTION_ORDER if x in usable]
        if not ordered:
            continue
        candidates.append({
            "action": ordered[0], "target": str(target), "skill": "",
            "reason": "unseen_target",
        })
    return candidates


def add_progression_candidates(goal, scenario_mgr, location, target_statuses, location_status, runtime=None):
    goal = copy.deepcopy(goal or {})
    existing = list(goal.get("candidate_next_actions") or [])
    derived = _event_state_change_candidates(scenario_mgr, location, target_statuses)
    derived.extend(_unseen_information_candidates(scenario_mgr, location, target_statuses))
    if location_status in {"SATISFIED", "EXHAUSTED"}:
        derived.extend(_transition_candidates(scenario_mgr, location, runtime))
    merged = []
    seen = set()
    for item in derived + existing:
        key = (str(item.get("action") or ""), str(item.get("target") or ""))
        if key in seen:
            continue
        seen.add(key)
        merged.append(item)
    goal["candidate_next_actions"] = merged
    return goal


def limit_available_candidates(goal, location_status, limit=3):
    """Apply the display/execution cap after availability filtering.

    During a completed-location transition, retain at least one executable move even
    if lower-priority candidates precede it.
    """
    goal = copy.deepcopy(goal or {})
    candidates = list(goal.get("candidate_next_actions") or [])
    if limit <= 0:
        goal["candidate_next_actions"] = []
        return goal
    selected = candidates[:limit]
    if location_status in {"SATISFIED", "EXHAUSTED"}:
        move = next(
            (item for item in candidates if str(item.get("action") or "").lower() == "move"),
            None,
        )
        has_move = any(str(item.get("action") or "").lower() == "move" for item in selected)
        if move is not None and not has_move:
            selected = (selected[: max(0, limit - 1)] + [move])[:limit]
    goal["candidate_next_actions"] = selected
    return goal


def derive_action_phase(goal, target_statuses, location_status):
    candidates = (goal or {}).get("candidate_next_actions") or []
    first_action = str(candidates[0].get("action") or "").lower() if candidates else ""
    if first_action in STATE_CHANGING_ACTIONS and first_action != "move":
        return "EXECUTE"
    if location_status in {"SATISFIED", "EXHAUSTED"}:
        return "TRANSITION"
    if first_action in STATE_CHANGING_ACTIONS:
        return "EXECUTE"
    if any(value == "UNSEEN" for value in target_statuses.values()):
        return "DISCOVER"
    if any(value == "INVESTIGATED" for value in target_statuses.values()):
        return "INVESTIGATE"
    return "DECIDE"


def enrich_runtime(runtime, goal, scenario_mgr, location, *, actor="", state=None):
    statuses = derive_target_statuses(scenario_mgr, location)
    location_status = derive_location_objective_status(statuses)
    goal = add_progression_candidates(goal, scenario_mgr, location, statuses, location_status, runtime)
    goal = filter_exhausted_candidates(goal, statuses, location_status)
    goal = filter_available_candidates(
        goal, scenario_mgr, location, actor=actor, state=state,
        source="candidate_generation",
    )
    goal = limit_available_candidates(goal, location_status)
    runtime["target_statuses"] = statuses
    runtime["location_objective_status"] = location_status
    runtime["action_phase"] = derive_action_phase(goal, statuses, location_status)
    return goal


def reconcile_location(state, scenario_mgr, *, canonical=None, log=True):
    """Synchronize location atomically and record any disagreement."""
    if not isinstance(state, dict) or scenario_mgr is None:
        return None
    state_loc = str(state.get("current_loc") or "")
    manager_loc = str(getattr(scenario_mgr, "location", "") or "")
    canonical = str(canonical or state_loc or manager_loc)
    mismatch = bool(state_loc and manager_loc and state_loc != manager_loc)
    if mismatch and log:
        state.setdefault("all_events_log", []).append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": (
                "[システム] LOCATION_INCONSISTENCY を検出し、"
                f"正規位置 `{canonical}` へ同期しました。"
            ),
            "meta": {
                "error_code": "LOCATION_INCONSISTENCY",
                "state_location": state_loc,
                "scenario_location": manager_loc,
                "canonical_location": canonical,
                "auto_repaired": True,
            },
        })
    state["current_loc"] = canonical
    scenario_mgr.location = canonical
    return {
        "inconsistent": mismatch,
        "canonical_location": canonical,
        "state_location": state_loc,
        "scenario_location": manager_loc,
    }
