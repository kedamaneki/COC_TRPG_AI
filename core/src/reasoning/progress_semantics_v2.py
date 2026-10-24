"""V18 Progress Semantics v2 — Meaningful ≠ Goal-Directed."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

PROGRESS_CLASS_MEANINGFUL = "MEANINGFUL_PROGRESS"
PROGRESS_CLASS_GOAL_DIRECTED = "GOAL_DIRECTED_PROGRESS"
PROGRESS_CLASS_LATERAL = "LATERAL_EXPLORATION_PROGRESS"
PROGRESS_CLASS_TERMINAL = "TERMINAL_PROGRESS"

# Types that are typically lateral when not linked to visible goals/leads/blockers
LATERAL_DEFAULT_TYPES = frozenset({
    "NEW_LOCATION",
    "new_location",
})

TERMINAL_TYPES = frozenset({
    "TERMINAL_PROGRESS",
    "GOAL_RESOLVED",
    "SCENARIO_CLEAR",
    "VALIDATED_KILL",
    "BOSS_TRIGGER",
})

# Forbidden signals for goal-directed classification
FORBIDDEN_GD_KEYS = frozenset({
    "correct_path",
    "distance_to_ending",
    "author_intended_route",
    "future_hidden_event",
    "hidden_objective",
    "hidden_solution",
    "ending_proximity",
})


def _has_forbidden_gd_signal(blob: Mapping[str, Any]) -> bool:
    for k in FORBIDDEN_GD_KEYS:
        if k in blob and blob[k] not in (None, False, 0, "", []):
            return True
    return False


def is_goal_directed_event(
    event: Mapping[str, Any],
    *,
    visible_goal_ids: Sequence[str] = (),
    unresolved_lead_ids: Sequence[str] = (),
    known_blocker_ids: Sequence[str] = (),
    known_frontier_ids: Sequence[str] = (),
) -> bool:
    """Classify GD using only legally visible links — never hidden solution."""
    if not isinstance(event, Mapping):
        return False
    if _has_forbidden_gd_signal(event):
        return False

    # Explicit class wins if present and not forbidden-path
    classes = event.get("progress_classes") or []
    if isinstance(event.get("progress_class"), str):
        classes = list(classes) + [event.get("progress_class")]
    classes_u = {str(c).upper() for c in classes}
    if PROGRESS_CLASS_TERMINAL in classes_u or "TERMINAL" in classes_u:
        return True
    if PROGRESS_CLASS_GOAL_DIRECTED in classes_u or event.get("progress_class") == "GOAL_DIRECTED":
        # Still require no forbidden keys
        return True

    ptype = str(event.get("progress_type") or event.get("kind") or "").upper()
    if ptype in {t.upper() for t in TERMINAL_TYPES}:
        return True

    eg = [str(x) for x in (event.get("goal_ids") or [])]
    if event.get("goal_id"):
        eg.append(str(event.get("goal_id")))
    el = [str(x) for x in (event.get("lead_ids") or [])]
    if event.get("lead_id"):
        el.append(str(event.get("lead_id")))
    ef = [str(x) for x in (event.get("frontier_ids") or [])]
    if event.get("frontier_id"):
        ef.append(str(event.get("frontier_id")))

    visible_g = {str(x) for x in visible_goal_ids if x}
    unresolved = {str(x) for x in unresolved_lead_ids if x}
    blockers = {str(x) for x in known_blocker_ids if x}
    frontiers = {str(x) for x in known_frontier_ids if x}

    if eg and visible_g and set(eg) & visible_g:
        return True
    if el and unresolved and set(el) & unresolved:
        return True
    if ef and frontiers and set(ef) & frontiers:
        return True

    # Observed state effect referencing known blocker/lead
    ose = event.get("observed_state_effect")
    if isinstance(ose, Mapping):
        if _has_forbidden_gd_signal(ose):
            return False
        changed = {str(x) for x in (ose.get("changed_keys") or [])}
        if blockers and changed & blockers:
            return True
        linked = {str(x) for x in (ose.get("lead_ids") or []) + (ose.get("goal_ids") or [])}
        if linked & (unresolved | visible_g):
            return True

    # OBJECTIVE_ADVANCEMENT with any visible lead/goal attachment
    if ptype in ("OBJECTIVE_ADVANCEMENT", "HYPOTHESIS_RESOLVED", "NEW_VIABLE_LEAD"):
        if eg or el or ef:
            return True

    return False


def is_meaningful_event(event: Mapping[str, Any]) -> bool:
    from .kp_assessment import classify_progress_event

    if not isinstance(event, Mapping):
        return False
    classes = event.get("progress_classes") or []
    if isinstance(event.get("progress_class"), str):
        classes = list(classes) + [event.get("progress_class")]
    for c in classes:
        cu = str(c).upper()
        if cu in (
            PROGRESS_CLASS_MEANINGFUL,
            PROGRESS_CLASS_GOAL_DIRECTED,
            PROGRESS_CLASS_LATERAL,
            PROGRESS_CLASS_TERMINAL,
            "MEANINGFUL",
            "GOAL_DIRECTED",
            "LATERAL",
            "TERMINAL",
        ):
            return True
    return classify_progress_event(str(event.get("kind") or event.get("progress_type") or ""))


def is_lateral_event(
    event: Mapping[str, Any],
    *,
    visible_goal_ids: Sequence[str] = (),
    unresolved_lead_ids: Sequence[str] = (),
    known_blocker_ids: Sequence[str] = (),
    known_frontier_ids: Sequence[str] = (),
) -> bool:
    if not is_meaningful_event(event):
        return False
    if is_goal_directed_event(
        event,
        visible_goal_ids=visible_goal_ids,
        unresolved_lead_ids=unresolved_lead_ids,
        known_blocker_ids=known_blocker_ids,
        known_frontier_ids=known_frontier_ids,
    ):
        return False
    return True


def classify_progress_event_v2(
    event: Mapping[str, Any],
    *,
    visible_goal_ids: Sequence[str] = (),
    unresolved_lead_ids: Sequence[str] = (),
    known_blocker_ids: Sequence[str] = (),
    known_frontier_ids: Sequence[str] = (),
) -> list[str]:
    """Return multi-label progress classes for one event."""
    out: list[str] = []
    if not is_meaningful_event(event):
        return out
    out.append(PROGRESS_CLASS_MEANINGFUL)
    if is_goal_directed_event(
        event,
        visible_goal_ids=visible_goal_ids,
        unresolved_lead_ids=unresolved_lead_ids,
        known_blocker_ids=known_blocker_ids,
        known_frontier_ids=known_frontier_ids,
    ):
        out.append(PROGRESS_CLASS_GOAL_DIRECTED)
        ptype = str(event.get("progress_type") or event.get("kind") or "").upper()
        if ptype in {t.upper() for t in TERMINAL_TYPES} or PROGRESS_CLASS_TERMINAL in {
            str(c).upper() for c in (event.get("progress_classes") or [])
        }:
            out.append(PROGRESS_CLASS_TERMINAL)
    else:
        out.append(PROGRESS_CLASS_LATERAL)
    return out


def summarize_cycle_progress(
    events: Sequence[Mapping[str, Any]],
    *,
    visible_goal_ids: Sequence[str] = (),
    unresolved_lead_ids: Sequence[str] = (),
    known_blocker_ids: Sequence[str] = (),
    known_frontier_ids: Sequence[str] = (),
) -> dict:
    meaningful = False
    goal_directed = False
    lateral = False
    terminal = False
    for e in events or []:
        if not isinstance(e, Mapping):
            continue
        classes = classify_progress_event_v2(
            e,
            visible_goal_ids=visible_goal_ids,
            unresolved_lead_ids=unresolved_lead_ids,
            known_blocker_ids=known_blocker_ids,
            known_frontier_ids=known_frontier_ids,
        )
        if PROGRESS_CLASS_MEANINGFUL in classes:
            meaningful = True
        if PROGRESS_CLASS_GOAL_DIRECTED in classes:
            goal_directed = True
        if PROGRESS_CLASS_LATERAL in classes:
            lateral = True
        if PROGRESS_CLASS_TERMINAL in classes:
            terminal = True
    return {
        "meaningful_progress": meaningful,
        "goal_directed_progress": goal_directed,
        "lateral_exploration_progress": lateral and not goal_directed,
        "terminal_progress": terminal,
    }
