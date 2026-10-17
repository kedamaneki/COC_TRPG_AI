"""Partial-v2 progress, goal, stall and intervention tracking.

This module is intentionally independent from dice/rules resolution.  It reads
the existing scenario structure and records a parallel, JSON-serialisable view
of why a session progressed and where it is trying to go.
"""

from __future__ import annotations

import copy
from EventIdentity import append_unified_event
import re
from collections import deque

from ProgressionPolicy import INFORMATION_ACTIONS, enrich_runtime
from ActionAvailability import filter_available_candidates


AUTONOMOUS = "AUTONOMOUS"
SYSTEM_GUIDED = "SYSTEM_GUIDED"
SYSTEM_FORCED = "SYSTEM_FORCED"
HUMAN_GUIDED = "HUMAN_GUIDED"
HUMAN_FORCED = "HUMAN_FORCED"
ACTION_ORIGINS = frozenset({
    AUTONOMOUS, SYSTEM_GUIDED, SYSTEM_FORCED, HUMAN_GUIDED, HUMAN_FORCED,
})
FORCED_ORIGINS = frozenset({SYSTEM_FORCED, HUMAN_FORCED})

_EQ_RE = re.compile(r"\b(action_id|target|location)\s*==\s*['\"]([^'\"]+)['\"]")
_FLAG_RE = re.compile(r"\bflags\.([A-Za-z0-9_]+)\s*==\s*(true|false)", re.I)
_ACTION_IN_RE = re.compile(r"\baction_id\s+in\s+\[([^\]]+)\]")
_QUOTED_RE = re.compile(r"['\"]([^'\"]+)['\"]")


def normalize_action_origin(value, default=AUTONOMOUS):
    value = str(value or "").strip().upper()
    return value if value in ACTION_ORIGINS else default


def migrate_legacy_action_origins(data):
    """Stamp old saves once so all later evaluation uses action_origin only."""
    if not isinstance(data, dict):
        return data
    app_state = data.get("app_state") if isinstance(data.get("app_state"), dict) else data
    for entry in app_state.get("all_events_log") or []:
        meta = entry.get("meta") or {}
        if not meta.get("action_id") or meta.get("action_origin"):
            continue
        if meta.get("forced_by_system") or meta.get("forced_progress"):
            meta["action_origin"] = SYSTEM_FORCED
        elif meta.get("human"):
            meta["action_origin"] = HUMAN_GUIDED
        elif meta.get("pc_id") or meta.get("actor_id"):
            meta["action_origin"] = AUTONOMOUS
        entry["meta"] = meta
    return data


def _scenario_dict(scenario_mgr):
    return getattr(scenario_mgr, "scenario_data", None) or {}


def _flags(scenario_mgr):
    return getattr(scenario_mgr, "flags", None) or {}


def parse_condition(condition):
    text = str(condition or "")
    parsed = {"flags": {}, "actions": [], "target": "", "location": ""}
    for field, value in _EQ_RE.findall(text):
        if field == "action_id":
            parsed["actions"] = [value]
        else:
            parsed[field] = value
    match = _ACTION_IN_RE.search(text)
    if match:
        parsed["actions"] = _QUOTED_RE.findall(match.group(1))
    for key, raw in _FLAG_RE.findall(text):
        parsed["flags"][key] = raw.lower() == "true"
    return parsed


def _event_spec(event):
    spec = parse_condition(event.get("trigger_condition"))
    spec["event_id"] = str(event.get("event_id") or "")
    spec["priority"] = int(event.get("priority") or 0)
    spec["payload"] = event.get("payload") or {}
    return spec


def _is_terminal_event(event):
    payload = event.get("payload") or {}
    phase = str(payload.get("new_phase") or "").lower()
    log = str(payload.get("system_log") or "")
    return (
        phase in {"clear", "cleared", "complete", "completed", "ending", "end"}
        or "【クリア】" in log
        or "シナリオクリア" in log
    )


def _requirements_met(spec, flags, location, *, include_location=True):
    for key, expected in (spec.get("flags") or {}).items():
        if bool(flags.get(key, False)) != bool(expected):
            return False
    if include_location and spec.get("location") and spec["location"] != location:
        return False
    return True


def _available_exit_ids(scenario_mgr, location):
    try:
        return [str(x.get("id")) for x in scenario_mgr.get_available_exits(location) or []]
    except Exception:
        return []


def _shortest_next_location(scenario_mgr, start, goal):
    if not start or not goal or start == goal:
        return ""
    data = _scenario_dict(scenario_mgr)
    locations = data.get("locations") or {}
    queue = deque([(start, [])])
    seen = {start}
    while queue:
        loc, path = queue.popleft()
        neighbours = set(_available_exit_ids(scenario_mgr, loc))
        if not neighbours:
            neighbours.update((locations.get(loc) or {}).get("connected_to") or [])
        for nxt in neighbours:
            nxt = str(nxt)
            if nxt in seen:
                continue
            next_path = path + [nxt]
            if nxt == goal:
                return next_path[0]
            seen.add(nxt)
            queue.append((nxt, next_path))
    return ""


class GoalManagerV2:
    """Derive the active goal and candidate actions from existing event data."""

    def __init__(self, scenario_mgr):
        self.scenario_mgr = scenario_mgr
        self.events = list(getattr(scenario_mgr, "event_triggers", None) or [])
        self.specs = [_event_spec(e) for e in self.events]
        self.by_id = {s["event_id"]: s for s in self.specs if s["event_id"]}
        self.producers = {}
        self.location_producers = {}
        for spec in self.specs:
            for key, value in (spec["payload"].get("flag_updates") or {}).items():
                if value is True:
                    self.producers.setdefault(str(key), []).append(spec)
            new_location = str(spec["payload"].get("new_location") or "")
            if new_location:
                self.location_producers.setdefault(new_location, []).append(spec)

    def terminal_specs(self):
        return [
            _event_spec(event) for event in self.events if _is_terminal_event(event)
        ]

    def _candidate_for_spec(self, spec, flags, location, visited=None):
        visited = set(visited or ())
        event_id = spec.get("event_id") or ""
        if event_id in visited:
            return None
        visited.add(event_id)

        missing_true = [
            key for key, expected in (spec.get("flags") or {}).items()
            if expected is True and not bool(flags.get(key, False))
        ]
        blocking_false = [
            key for key, expected in (spec.get("flags") or {}).items()
            if expected is False and bool(flags.get(key, False))
        ]
        if blocking_false:
            return None
        for key in missing_true:
            options = sorted(self.producers.get(key) or [], key=lambda x: -x.get("priority", 0))
            for producer in options:
                candidate = self._candidate_for_spec(producer, flags, location, visited)
                if candidate:
                    candidate["requirement"] = key
                    return candidate

        wanted_location = spec.get("location") or ""
        if wanted_location and wanted_location != location:
            # Prefer the scenario event that performs this transition.  Its
            # conditions encode gates that the static exit graph cannot express.
            options = sorted(
                self.location_producers.get(wanted_location) or [],
                key=lambda x: -x.get("priority", 0),
            )
            for producer in options:
                candidate = self._candidate_for_spec(producer, flags, location, visited)
                if candidate:
                    candidate["requirement"] = f"location:{wanted_location}"
                    return candidate
            next_loc = _shortest_next_location(self.scenario_mgr, location, wanted_location)
            if next_loc:
                return {
                    "action": "move", "target": next_loc, "skill": "",
                    "reason": f"goal_route:{event_id}", "event_id": event_id,
                }
            return None

        actions = list(spec.get("actions") or [])
        if actions:
            return {
                "action": actions[0], "target": spec.get("target") or "", "skill": "",
                "reason": f"goal_event:{event_id}", "event_id": event_id,
            }
        return None

    def build(self, location):
        flags = _flags(self.scenario_mgr)
        terminals = self.terminal_specs()
        title = str((_scenario_dict(self.scenario_mgr).get("scenario_meta") or {}).get("title") or "シナリオ目標")
        if not terminals:
            return {
                "current_goal": title,
                "subgoals": [],
                "completed_requirements": [],
                "remaining_requirements": [],
                "blocked_requirements": [],
                "candidate_next_actions": [],
                "terminal_event_id": "",
            }

        ranked = []
        for spec in terminals:
            unmet = sum(
                bool(flags.get(k, False)) != bool(v)
                for k, v in (spec.get("flags") or {}).items()
            )
            if spec.get("location") and spec["location"] != location:
                unmet += 1
            ranked.append((unmet, -spec.get("priority", 0), spec))
        terminal = sorted(ranked, key=lambda x: (x[0], x[1]))[0][2]

        completed = []
        remaining = []
        blocked = []
        for key, expected in (terminal.get("flags") or {}).items():
            label = f"flag:{key}={str(expected).lower()}"
            (completed if bool(flags.get(key, False)) == bool(expected) else remaining).append(label)
        wanted_location = terminal.get("location") or ""
        if wanted_location:
            label = f"location:{wanted_location}"
            (completed if location == wanted_location else remaining).append(label)
        action_label = "/".join(terminal.get("actions") or [])
        if action_label:
            remaining.append(f"action:{action_label}/{terminal.get('target') or ''}")

        candidate = self._candidate_for_spec(terminal, flags, location)
        candidates = [candidate] if candidate else []
        if not candidate:
            blocked.append(terminal.get("event_id") or "terminal_event")

        return {
            "current_goal": f"{title}を完了する",
            "subgoals": [terminal.get("event_id") or "ending"],
            "completed_requirements": completed,
            "remaining_requirements": remaining,
            "blocked_requirements": blocked,
            "candidate_next_actions": candidates[:3],
            "terminal_event_id": terminal.get("event_id") or "",
        }


class ProgressTrackerV2:
    """Score scenario progress without treating ordinary movement as progress."""

    @staticmethod
    def snapshot(state, scenario_mgr, char_mgr=None):
        flags = copy.deepcopy(_flags(scenario_mgr))
        phase = str(getattr(scenario_mgr, "current_phase", "") or "")
        location = str((state or {}).get("current_loc") or getattr(scenario_mgr, "location", "") or "")
        public = sorted(str(x) for x in ((state or {}).get("public_knowledge_ids") or []))
        pc_knowledge = {}
        if char_mgr and hasattr(char_mgr, "get_known_knowledge_ids"):
            for pc_id in (state or {}).get("active_pcs") or getattr(char_mgr, "active_pc_list", []) or []:
                try:
                    pc_knowledge[str(pc_id)] = sorted(char_mgr.get_known_knowledge_ids(pc_id) or [])
                except Exception:
                    pass
        return {
            "location": location,
            "phase": phase,
            "flags": flags,
            "public_knowledge": public,
            "pc_knowledge": pc_knowledge,
        }

    @staticmethod
    def evaluate(before, after, goal_before=None, goal_after=None, result=None, visited_locations=None):
        before = before or {}
        after = after or {}
        before_flags = before.get("flags") or {}
        after_flags = after.get("flags") or {}
        flags_changed = {
            key: {"before": before_flags.get(key), "after": value}
            for key, value in after_flags.items()
            if before_flags.get(key) != value
        }
        new_flags = [
            key for key, change in flags_changed.items()
            if change["after"] is True
            and not str(key).startswith(("visit_", "turn_", "last_", "stagnation_"))
        ]
        before_knowledge = set(before.get("public_knowledge") or [])
        after_knowledge = set(after.get("public_knowledge") or [])
        for ids in (before.get("pc_knowledge") or {}).values():
            before_knowledge.update(ids or [])
        for ids in (after.get("pc_knowledge") or {}).values():
            after_knowledge.update(ids or [])
        knowledge_gained = sorted(after_knowledge - before_knowledge)

        before_remaining = set((goal_before or {}).get("remaining_requirements") or [])
        after_remaining = set((goal_after or {}).get("remaining_requirements") or [])
        requirements_completed = sorted(before_remaining - after_remaining)
        phase_after = str(after.get("phase") or "").lower()
        phase_before = str(before.get("phase") or "").lower()
        terminal = phase_after in {"clear", "cleared", "complete", "completed", "ending", "end"}
        score = 0
        reasons = []
        if terminal and phase_after != phase_before:
            score = 3
            reasons.append("scenario_completed")
        elif requirements_completed:
            score = 3
            reasons.extend(f"requirement_completed:{x}" for x in requirements_completed)
        elif new_flags or knowledge_gained:
            score = 2
            reasons.extend(f"important_flag:{x}" for x in new_flags)
            reasons.extend(f"knowledge_gained:{x}" for x in knowledge_gained)
        elif result and (
            result.get("combat_resolved") or result.get("relationship_improved")
            or result.get("resolved_event_ids")
        ):
            score = 1
            reasons.append("event_or_relationship_progress")
        elif after.get("location") != before.get("location"):
            visited = set(visited_locations or [])
            if after.get("location") and after.get("location") not in visited:
                score = 1
                reasons.append(f"new_location:{after.get('location')}")

        return {
            "progress_delta": score,
            "progress_reason": reasons or ["no_scenario_progress"],
            "flags_changed": flags_changed,
            "knowledge_gained": knowledge_gained,
            "requirements_completed": requirements_completed,
            "location_changed": before.get("location") != after.get("location"),
        }


class StallDetectorV2:
    """Detect loops from progress score, action repetition and ABAB movement."""

    @staticmethod
    def update(runtime, *, action, target, location_before, location_after, progress_delta):
        runtime = dict(runtime or {})
        actions = list(runtime.get("recent_actions") or [])
        locations = list(runtime.get("recent_locations") or [])
        failed = list(runtime.get("recent_failed_actions") or [])
        key = [str(action or ""), str(target or "")]
        actions.append(key)
        actions = actions[-8:]
        if not locations and location_before:
            locations.append(str(location_before))
        if location_after:
            locations.append(str(location_after))
        locations = locations[-10:]

        if int(progress_delta or 0) > 0:
            no_progress = 0
            failed = []
            s4_override_used = False
        else:
            no_progress = int(runtime.get("no_progress_streak") or 0) + 1
            s4_override_used = bool(runtime.get("s4_override_used", False))
            if key[0] and key[0] not in {"move", "wait", "none"}:
                failed.append(key)
                failed = failed[-8:]

        same_action = 1
        for prior in reversed(actions[:-1]):
            if prior == key:
                same_action += 1
            else:
                break

        alternating_len = 1 if locations else 0
        for i in range(len(locations) - 1, 0, -1):
            if locations[i] == locations[i - 1]:
                break
            if i >= 2 and locations[i] != locations[i - 2]:
                break
            alternating_len += 1
        roundtrip_count = max(0, (alternating_len - 1) // 2)

        signals = []
        if no_progress >= 3:
            signals.append("consecutive_no_progress")
        if same_action >= 3:
            signals.append("repeated_action")
        if roundtrip_count >= 2:
            signals.append("location_pingpong")
        if key in failed[:-1]:
            signals.append("known_failed_action_reselected")

        pressure = max(
            no_progress,
            3 if same_action >= 3 else 0,
            4 if roundtrip_count >= 2 else 0,
        )
        if pressure >= 6:
            level = "S4"
        elif pressure >= 5:
            level = "S3"
        elif pressure >= 3:
            level = "S2"
        elif pressure >= 2:
            level = "S1"
        else:
            level = "S0"

        runtime.update({
            "no_progress_streak": no_progress,
            "max_no_progress_streak": max(int(runtime.get("max_no_progress_streak") or 0), no_progress),
            "recent_actions": actions,
            "recent_locations": locations,
            "recent_failed_actions": failed,
            "same_action_streak": same_action,
            "roundtrip_count": roundtrip_count,
            "max_roundtrip_count": max(int(runtime.get("max_roundtrip_count") or 0), roundtrip_count),
            "signals": signals,
            "intervention_level": level,
            "s4_override_used": s4_override_used,
        })
        return runtime


def ensure_director_state(state, scenario_mgr, char_mgr=None):
    runtime = state.setdefault("director_v2", {})
    location = str(state.get("current_loc") or getattr(scenario_mgr, "location", "") or "")
    goal = GoalManagerV2(scenario_mgr).build(location)
    actor = str(
        state.get("actor_id") or state.get("active_pc_id")
        or state.get("pl_id") or ""
    )
    goal = enrich_runtime(
        runtime, goal, scenario_mgr, location, actor=actor, state=state,
    )
    runtime["goal"] = goal
    runtime.setdefault("visited_locations", [])
    if location and location not in runtime["visited_locations"]:
        runtime["visited_locations"].append(location)
    runtime.setdefault("stall", {})
    runtime.setdefault("recorded_transactions", [])
    runtime["state_before"] = ProgressTrackerV2.snapshot(state, scenario_mgr, char_mgr)
    runtime["goal_before"] = copy.deepcopy(goal)
    return runtime


def build_director_prompt(state, scenario_mgr, char_mgr=None):
    runtime = ensure_director_state(state, scenario_mgr, char_mgr)
    goal = runtime["goal"]
    stall = runtime.get("stall") or {}
    completed = goal.get("completed_requirements") or []
    remaining = goal.get("remaining_requirements") or []
    candidates = goal.get("candidate_next_actions") or []
    lines = [
        "【Session Director v2・進行判断】",
        f"- 現在目標: {goal.get('current_goal') or 'シナリオを前進させる'}",
        f"- 達成済み条件: {', '.join(completed) if completed else 'なし'}",
        f"- 未達成条件: {', '.join(remaining) if remaining else 'なし'}",
        f"- 場所目的: {runtime.get('location_objective_status') or 'ACTIVE'}",
        f"- 行動フェーズ: {runtime.get('action_phase') or 'DISCOVER'}",
    ]
    if candidates:
        rendered = []
        for item in candidates[:3]:
            rendered.append(f"{item.get('action')} / {item.get('target')} ({item.get('reason')})")
        lines.append("- 進展可能性が高い候補: " + "、".join(rendered))
        lines.append("- 候補は強制ではないが、ルール上またはキャラクター上の明確な理由がなければ最優先で実行すること。")
    if runtime.get("action_phase") == "EXECUTE" and candidates:
        top = candidates[0]
        lines.append(
            f"- 調査は十分です。情報収集を繰り返さず、世界状態を変える "
            f"{top.get('action')} / {top.get('target')} を実行してください。"
        )
    level = str(stall.get("intervention_level") or "S0")
    if level != "S0":
        lines.append(f"- 停滞介入: {level} / {', '.join(stall.get('signals') or ['no_progress'])}")
        if level == "S1":
            lines.append("- 現在目標と未達成条件を再確認すること。")
        elif level == "S2":
            lines.append("- 未達成条件に直接関係する候補だけを3つ以内で比較すること。")
        elif level in {"S3", "S4"} and candidates:
            top = candidates[0]
            lines.append(f"- 最優先候補は {top.get('action')} / {top.get('target')}。この手番で実行を強く推奨する。")
    return "\n".join(lines) + "\n"


def classify_action_origin(state, action, target, *, human=False, forced=False):
    if human:
        return HUMAN_FORCED if forced else HUMAN_GUIDED
    if forced:
        return SYSTEM_FORCED
    goal = ((state.get("director_v2") or {}).get("goal") or {})
    for item in goal.get("candidate_next_actions") or []:
        if str(item.get("action") or "") == str(action or "") and str(item.get("target") or "") == str(target or ""):
            return SYSTEM_GUIDED
    return AUTONOMOUS


def apply_stall_candidate_guidance(state, pc_action, scenario_mgr=None, actor=""):
    """At S2/S3, replace exhausted or wrong-phase choices with the top candidate."""
    runtime = (state or {}).get("director_v2") or {}
    stall = runtime.get("stall") or {}
    level = str(stall.get("intervention_level") or "S0")
    if level not in {"S2", "S3", "S4"}:
        return pc_action
    goal = runtime.get("goal") or {}
    if scenario_mgr is not None:
        goal = filter_available_candidates(
            goal, scenario_mgr, state.get("current_loc") or getattr(scenario_mgr, "location", ""),
            actor=actor, state=state, source="guided",
        )
        runtime["goal"] = goal
    candidates = goal.get("candidate_next_actions") or []
    if not candidates:
        return pc_action
    action = str((pc_action or {}).get("action") or "").lower()
    target = str((pc_action or {}).get("target") or "")
    target_status = (runtime.get("target_statuses") or {}).get(target)
    phase = str(runtime.get("action_phase") or "")
    exhausted_repeat = action in INFORMATION_ACTIONS and target_status == "EXHAUSTED"
    wrong_phase = (
        level in {"S3", "S4"}
        and (
            (phase == "EXECUTE" and (action in INFORMATION_ACTIONS or action in {"wait", "none", ""}))
            or (phase == "TRANSITION" and action != "move")
        )
    )
    if not exhausted_repeat and not wrong_phase:
        return pc_action
    top = candidates[0]
    if action == str(top.get("action") or "") and target == str(top.get("target") or ""):
        return pc_action
    fixed = dict(pc_action or {})
    fixed["original_action"] = dict(pc_action or {})
    fixed["action"] = str(top.get("action") or "wait")
    fixed["target"] = str(top.get("target") or "")
    fixed["skill"] = str(top.get("skill") or "")
    fixed["dialogue"] = ""
    fixed["message"] = ""
    fixed["action_origin"] = SYSTEM_GUIDED
    fixed["director_guided"] = True
    fixed["intervention_level"] = level
    fixed["intervention_reason"] = (
        "exhausted_target_reselected" if exhausted_repeat else "action_phase_mismatch"
    )
    fixed["availability_snapshot"] = copy.deepcopy(top.get("availability_snapshot") or {})
    return fixed


def apply_s4_candidate_override(state, pc_action, scenario_mgr=None, actor=""):
    """Use the top candidate only after an S3 prompt was ignored.

    The caller has already given the model the S1/S2/S3 progression across
    preceding no-progress turns.  This function is the final S4 boundary and
    deliberately performs at most one action replacement per stalled streak.
    """
    runtime = (state or {}).get("director_v2") or {}
    stall = runtime.get("stall") or {}
    goal = runtime.get("goal") or {}
    if scenario_mgr is not None:
        goal = filter_available_candidates(
            goal, scenario_mgr, state.get("current_loc") or getattr(scenario_mgr, "location", ""),
            actor=actor, state=state, source="forced",
        )
        runtime["goal"] = goal
    candidates = goal.get("candidate_next_actions") or []
    forced_history = set(runtime.get("forced_action_contexts") or [])
    candidates = [
        item for item in candidates
        if "|".join((
            str(item.get("action") or ""), str(item.get("target") or ""),
            str(item.get("availability_context_version") or ""),
        )) not in forced_history
    ]
    if str(stall.get("intervention_level") or "S0") != "S4" or bool(stall.get("s4_override_used", False)):
        return pc_action
    if not candidates:
        context = str((goal.get("blocked_candidate_actions") or [{}])[0].get("availability_context_version") or "")
        marker = f"{actor}|{context}"
        emitted = runtime.setdefault("no_available_progress_contexts", [])
        if marker not in emitted:
            append_unified_event(state, {
                "event_type": "NO_AVAILABLE_PROGRESS_ACTION",
                "actor": actor,
                "action": "",
                "target": "",
                "status": "BLOCKED",
                "reason_code": "NO_AVAILABLE_PROGRESS_ACTION",
                "context_version": context,
                "cycle": state.get("evaluation_cycle", state.get("cycle", "")),
                "turn": state.get("turn", state.get("turn_count", "")),
                "location": state.get("current_loc") or getattr(scenario_mgr, "location", ""),
                "scene": state.get("current_scene_id", ""),
                "scenario_id": str(
                    ((getattr(scenario_mgr, "meta", {}) or {}).get("id"))
                    or ((getattr(scenario_mgr, "meta", {}) or {}).get("scenario_id"))
                    or ""
                ),
                "goal": str(goal.get("current_goal") or ""),
                "source": "forced",
            })
            emitted.append(marker)
        return pc_action
    top = candidates[0]
    if (
        str((pc_action or {}).get("action") or "") == str(top.get("action") or "")
        and str((pc_action or {}).get("target") or "") == str(top.get("target") or "")
    ):
        return pc_action
    fixed = dict(pc_action or {})
    fixed["original_action"] = dict(pc_action or {})
    fixed["action"] = str(top.get("action") or "wait")
    fixed["target"] = str(top.get("target") or "")
    fixed["skill"] = str(top.get("skill") or "")
    fixed["dialogue"] = ""
    fixed["message"] = ""
    fixed["action_origin"] = SYSTEM_FORCED
    fixed["director_forced"] = True
    fixed["intervention_level"] = "S4"
    fixed["intervention_reason"] = "s3_candidate_ignored"
    fixed["availability_snapshot"] = copy.deepcopy(top.get("availability_snapshot") or {})
    forced_key = "|".join((
        str(top.get("action") or ""), str(top.get("target") or ""),
        str(top.get("availability_context_version") or ""),
    ))
    runtime.setdefault("forced_action_contexts", []).append(forced_key)
    stall["s4_override_used"] = True
    return fixed


def stamp_action_origin(logs, transaction_id, origin):
    origin = normalize_action_origin(origin)
    for entry in reversed(logs or []):
        meta = entry.get("meta") or {}
        if transaction_id and str(meta.get("transaction_id") or "") != str(transaction_id):
            continue
        if meta.get("action_id") and (meta.get("pc_id") or meta.get("actor_id")):
            meta["action_origin"] = origin
            entry["meta"] = meta
            return entry
    return None


def record_unified_turn(state, scenario_mgr, state_mgr=None, char_mgr=None, *, result=None, action=None, origin=None):
    runtime = state.setdefault("director_v2", {})
    action = action or state.get("last_pl_action") or {}
    txn = str(action.get("transaction_id") or (result or {}).get("transaction_id") or "")
    recorded = list(runtime.get("recorded_transactions") or [])
    if txn and txn in recorded:
        return None
    before = copy.deepcopy(
        action.get("_director_state_before")
        or runtime.get("state_before")
        or ProgressTrackerV2.snapshot(state, scenario_mgr, char_mgr)
    )
    goal_before = copy.deepcopy(
        action.get("_director_goal_before")
        or runtime.get("goal_before")
        or GoalManagerV2(scenario_mgr).build(before.get("location") or "")
    )
    after = ProgressTrackerV2.snapshot(state, scenario_mgr, char_mgr)
    goal_after = GoalManagerV2(scenario_mgr).build(after.get("location") or "")
    progress = ProgressTrackerV2.evaluate(
        before, after, goal_before, goal_after, result=result,
        visited_locations=runtime.get("visited_locations"),
    )
    achieved = set(runtime.get("achieved_requirements") or [])
    newly_achieved = [
        item for item in progress.get("requirements_completed") or []
        if item not in achieved
    ]
    if progress.get("requirements_completed") and not newly_achieved:
        other_reasons = [
            reason for reason in progress.get("progress_reason") or []
            if not str(reason).startswith("requirement_completed:")
        ]
        if not other_reasons:
            progress["progress_delta"] = 0
            progress["progress_reason"] = ["no_scenario_progress"]
    achieved.update(newly_achieved)
    runtime["achieved_requirements"] = sorted(achieved)
    if after.get("location") and after["location"] not in runtime.setdefault("visited_locations", []):
        runtime["visited_locations"].append(after["location"])

    selected_action = str(action.get("action") or (result or {}).get("action_id") or "")
    target = str(action.get("target") or (result or {}).get("target") or "")
    origin = normalize_action_origin(origin or action.get("action_origin"))
    stall = StallDetectorV2.update(
        runtime.get("stall"), action=selected_action, target=target,
        location_before=before.get("location"), location_after=after.get("location"),
        progress_delta=progress["progress_delta"],
    )
    runtime["stall"] = stall
    runtime["goal"] = goal_after

    dice = (result or {}).get("dice") or {}
    source_evidence = (result or {}).get("adjudication") or {}
    canonical_roll_identifier = str(
        source_evidence.get("canonical_identifier")
        or source_evidence.get("skill_or_stat")
        or (result or {}).get("canonical_identifier")
        or (result or {}).get("skill_or_stat")
        or ""
    ).strip()
    location_changed = (
        selected_action == "move"
        or before.get("location") != after.get("location")
        or bool((result or {}).get("location_changed") or (result or {}).get("new_location"))
    )
    lifecycle_actor = str((result or {}).get("lifecycle_actor_id") or "").strip()
    action_actor = str(action.get("actor_id") or action.get("pc_id") or "").strip()
    if location_changed and lifecycle_actor and action_actor and lifecycle_actor != action_actor:
        raise ValueError("lifecycle actor contradicts resolved action actor")
    event = {
        "turn_id": len(state.setdefault("unified_event_log", [])) + 1,
        "scene_id": getattr(state_mgr, "current_scene_id", "") if state_mgr else "",
        "actor": lifecycle_actor or action_actor or state.get("pl_id") or "",
        "location": before.get("location") or "",
        "current_goal": goal_before.get("current_goal") or "",
        "action_intent": action.get("dialogue") or action.get("message") or "",
        "selected_action": selected_action,
        "target": target,
        "action_origin": origin,
        "dice_used": bool(dice or (result or {}).get("roll_type") in {"skill", "opposed_str", "luck"}),
        "skill": (
            canonical_roll_identifier
            if str(source_evidence.get("resolution_mode") or "").upper() == "ROLL"
            else action.get("skill") or (result or {}).get("skill") or ""
        ),
        "canonical_identifier": canonical_roll_identifier or None,
        "requested_roll_identifier": action.get("skill") or (result or {}).get("requested_roll_identifier") or "",
        "target_value": dice.get("target_value") or (result or {}).get("target_value"),
        "roll": dice.get("roll") or (result or {}).get("roll"),
        "result": (result or {}).get("status"),
        "state_before": before,
        "state_after": after,
        "knowledge_gained": progress["knowledge_gained"],
        "flags_changed": progress["flags_changed"],
        "progress_delta": progress["progress_delta"],
        "progress_reason": progress["progress_reason"],
        "stall_count": stall["no_progress_streak"],
        "intervention_level": action.get("intervention_level") or stall["intervention_level"],
        "intervention_reason": action.get("intervention_reason") or stall["signals"],
        "forced_action": origin in FORCED_ORIGINS,
        "human_intervention": origin in {HUMAN_GUIDED, HUMAN_FORCED},
        "transaction_id": txn,
    }
    if location_changed:
        event["lifecycle_relation_id"] = (result or {}).get("lifecycle_relation_id")
        event["lifecycle_actor_id"] = lifecycle_actor
    if location_changed and source_evidence:
        adjudication_event = copy.deepcopy(event)
        adjudication_event["event_type"] = "MOVE_ACTION_RESOLVED"
        adjudication_event.update(copy.deepcopy(source_evidence))
        adjudication_event["source_event_ids"] = list((result or {}).get("source_event_ids") or [])
        append_unified_event(state, adjudication_event)
        event["event_type"] = "LOCATION_CHANGE"
        event["cause_adjudication_id"] = source_evidence.get("adjudication_id")
    elif location_changed:
        event["event_type"] = "LOCATION_CHANGE"
    elif source_evidence:
        event.update(copy.deepcopy(source_evidence))
        event["source_event_ids"] = list((result or {}).get("source_event_ids") or [])
    append_unified_event(state, event)
    if txn:
        recorded.append(txn)
        runtime["recorded_transactions"] = recorded[-200:]
    runtime["state_before"] = after
    runtime["goal_before"] = copy.deepcopy(goal_after)
    return event


def count_forced_from_action_origin(state=None, logs=None):
    state = state or {}
    unified = state.get("unified_event_log") or []
    if unified:
        return sum(normalize_action_origin(e.get("action_origin")) in FORCED_ORIGINS for e in unified)
    return sum(
        normalize_action_origin((entry.get("meta") or {}).get("action_origin")) in FORCED_ORIGINS
        for entry in (logs or state.get("all_events_log") or [])
        if (entry.get("meta") or {}).get("action_id")
        and ((entry.get("meta") or {}).get("pc_id") or (entry.get("meta") or {}).get("actor_id"))
    )
