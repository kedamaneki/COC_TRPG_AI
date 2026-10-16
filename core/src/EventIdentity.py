"""Allocate immutable identities before unified events are committed."""
from __future__ import annotations

import hashlib
import json


class EventIdentityError(ValueError):
    pass


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def allocate_event_id(state, event):
    """Finalize one event identity and raw offset without mutating it later."""
    if event.get("event_id"):
        event.setdefault("raw_event_offset", len(state.setdefault("unified_event_log", [])))
        return str(event["event_id"])
    unified = state.setdefault("unified_event_log", [])
    offset = len(unified)
    session_id = str(
        state.get("evaluation_session_id") or state.get("rp_session_id")
        or state.get("session_id") or "runtime"
    )
    body = {key: value for key, value in event.items() if key not in {"event_id", "raw_event_offset"}}
    token = hashlib.sha256(f"{session_id}:{offset}:{_canonical(body)}".encode("utf-8")).hexdigest()[:20]
    event["event_id"] = f"evt_{offset + 1:06d}_{token}"
    event["raw_event_offset"] = offset
    return event["event_id"]


def append_unified_event(state, event):
    allocate_event_id(state, event)
    if not event.get("event_id"):
        raise EventIdentityError("event_id is required before unified append")
    expected = len(state.setdefault("unified_event_log", []))
    if int(event.get("raw_event_offset", -1)) != expected:
        raise EventIdentityError("raw_event_offset is not contiguous")
    state["unified_event_log"].append(event)
    return event


def validate_event_stream(events):
    seen = set()
    for offset, event in enumerate(events):
        event_id = event.get("event_id")
        if not event_id:
            raise EventIdentityError(f"SEGMENT_EVENT_ID_MISSING:{offset}")
        if event_id in seen:
            raise EventIdentityError(f"SEGMENT_DUPLICATE_EVENT:{event_id}")
        seen.add(event_id)
        if int(event.get("raw_event_offset", -1)) != offset:
            raise EventIdentityError(f"SEGMENT_EVENT_OFFSET_INVALID:{event_id}")
    return True
