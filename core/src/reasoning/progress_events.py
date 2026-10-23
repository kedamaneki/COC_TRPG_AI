"""V17 production ProgressEvent helpers."""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Optional, Sequence


PROGRESS_TYPES = frozenset({
    "NEW_FACT",
    "NEW_LOCATION",
    "HYPOTHESIS_RESOLVED",
    "NEW_VIABLE_LEAD",
    "OBJECT_STATE_CHANGE",
    "OBJECTIVE_ADVANCEMENT",
    "RISK_DISCOVERY",
    "RESOURCE_GAIN",
})

# Map to kp_assessment MEANINGFUL_PROGRESS_KINDS (lowercase)
TYPE_TO_KIND = {
    "NEW_FACT": "new_fact",
    "NEW_LOCATION": "new_location",
    "HYPOTHESIS_RESOLVED": "hypothesis_resolved",
    "NEW_VIABLE_LEAD": "new_viable_lead",
    "OBJECT_STATE_CHANGE": "object_state_change",
    "OBJECTIVE_ADVANCEMENT": "objective_advancement",
    "RISK_DISCOVERY": "risk_discovery",
    "RESOURCE_GAIN": "resource_gain",
}


def make_progress_event(
    *,
    progress_type: str,
    actor_id: str = "",
    cycle: Any = None,
    turn: Any = None,
    goal_id: str = "",
    lead_id: str = "",
    source_event_id: str = "",
    progress_class: str = "MEANINGFUL",
) -> dict:
    ptype = str(progress_type or "").upper()
    if ptype not in PROGRESS_TYPES:
        ptype = "OBJECTIVE_ADVANCEMENT"
    return {
        "schema_version": 1,
        "progress_event_id": f"pev_{uuid.uuid4().hex[:12]}",
        "progress_type": ptype,
        "progress_class": progress_class,
        "kind": TYPE_TO_KIND.get(ptype, "objective_advancement"),
        "source_event_id": source_event_id or None,
        "actor_id": str(actor_id or ""),
        "cycle": cycle,
        "turn": turn,
        "goal_id": goal_id or None,
        "lead_id": lead_id or None,
    }


def append_progress_event(state: dict, event: Mapping[str, Any], *, maxlen: int = 64) -> dict:
    runtime = state.setdefault("director_v2", {})
    buf = list(runtime.get("progress_events") or [])
    buf.append(dict(event))
    runtime["progress_events"] = buf[-maxlen:]
    return dict(event)


def progress_events_for_ndm(state: Mapping[str, Any], *, limit: int = 32) -> list[dict]:
    runtime = (state or {}).get("director_v2") or {}
    buf = list(runtime.get("progress_events") or [])
    return [dict(x) for x in buf[-limit:] if isinstance(x, Mapping)]


def emit_progress_from_director_delta(
    state: dict,
    *,
    progress: Mapping[str, Any],
    actor_id: str = "",
    cycle: Any = None,
    turn: Any = None,
) -> list[dict]:
    """Derive ProgressEvent(s) from ProgressTrackerV2.evaluate output."""
    emitted: list[dict] = []
    delta = int(progress.get("progress_delta") or 0)
    reasons = list(progress.get("progress_reason") or [])
    if delta <= 0 and not progress.get("flags_changed") and not progress.get("requirements_completed"):
        return emitted

    def _emit(ptype: str) -> None:
        ev = make_progress_event(
            progress_type=ptype,
            actor_id=actor_id,
            cycle=cycle,
            turn=turn,
            goal_id=str(((state.get("director_v2") or {}).get("goal") or {}).get("goal_id") or ""),
        )
        append_progress_event(state, ev)
        emitted.append(ev)

    if progress.get("location_changed"):
        _emit("NEW_LOCATION")
    if progress.get("knowledge_gained"):
        _emit("NEW_FACT")
    if progress.get("requirements_completed"):
        _emit("OBJECTIVE_ADVANCEMENT")
    if progress.get("flags_changed") and not emitted:
        _emit("OBJECT_STATE_CHANGE")
    if delta > 0 and not emitted:
        # Generic meaningful advancement
        joined = " ".join(str(r) for r in reasons).lower()
        if "location" in joined:
            _emit("NEW_LOCATION")
        elif "fact" in joined or "knowledge" in joined:
            _emit("NEW_FACT")
        else:
            _emit("OBJECTIVE_ADVANCEMENT")
    return emitted
