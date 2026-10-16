"""Authoritative lifecycle contract for scenario objects."""
from __future__ import annotations

import copy


ALLOWED_TRANSITIONS = {
    "UNDISCOVERED": {"AVAILABLE"},
    "AVAILABLE": {"IN_COMBAT", "ON_FLOOR", "OWNED", "REMOVED"},
    "IN_COMBAT": {"INCAPACITATED", "ON_FLOOR", "DESTROYED"},
    "INCAPACITATED": {"ON_FLOOR", "DESTROYED"},
    "ON_FLOOR": {"OWNED", "DESTROYED", "REMOVED"},
    "OWNED": {"ON_FLOOR", "DESTROYED", "REMOVED"},
    "DESTROYED": set(),
    "REMOVED": set(),
}


def apply_object_transition(states, object_id, update):
    current = copy.deepcopy((states or {}).get(object_id) or {})
    old_status = str(current.get("status") or "UNDISCOVERED").upper()
    path = list((update or {}).get("transition_path") or [])
    new_status = str((update or {}).get("status") or old_status).upper()
    if not path or str(path[-1]).upper() != new_status:
        path.append(new_status)
    previous = old_status
    for item in path:
        status = str(item).upper()
        if status == previous:
            continue
        if status not in ALLOWED_TRANSITIONS.get(previous, set()):
            raise ValueError(f"OBJECT_STATE_INVALID_TRANSITION:{object_id}:{previous}->{status}")
        previous = status
    clean = {k: copy.deepcopy(v) for k, v in (update or {}).items() if k != "transition_path"}
    current.update(clean)
    current["object_id"] = object_id
    current["status"] = new_status
    if current.get("destroyed") or new_status in {"DESTROYED", "REMOVED"}:
        current.update({"exists": new_status != "DESTROYED", "owner_id": None, "available": False})
        current["destroyed"] = new_status == "DESTROYED"
    if new_status != "OWNED":
        current["owner_id"] = None if new_status in {"ON_FLOOR", "DESTROYED", "REMOVED"} else current.get("owner_id")
    if new_status == "OWNED" and not current.get("owner_id"):
        raise ValueError(f"OBJECT_STATE_INVALID_TRANSITION:{object_id}:OWNED_WITHOUT_OWNER")
    states[object_id] = current
    return current
