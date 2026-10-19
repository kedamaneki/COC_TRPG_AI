from __future__ import annotations

from copy import deepcopy


RENDER_MODES = frozenset({
    "FULL_RENDER", "SUMMARY_RENDER", "OMIT",
    "SUMMARY_ENTRY_BRIDGE", "SUMMARY_EXIT_BRIDGE",
})
BRIDGE_RENDER_MODES = frozenset({"SUMMARY_ENTRY_BRIDGE", "SUMMARY_EXIT_BRIDGE"})
MAJOR_EVENT_TYPES = frozenset({"LOCATION_CHANGE", "SKILL_CHECK", "STATE_CHANGE", "WORLD_EVENT"})


def _offset(event: dict) -> int:
    return int(event.get("raw_event_offset", -1))


def classify_replay_events(events: list[dict], *, full_ranges: list[tuple[int, int]],
                           summary_ranges: list[tuple[int, int]], omit_event_types: set[str] | None = None,
                           bridge_offsets: dict[int, str] | None = None) -> list[dict]:
    """Classify every event without changing source order or source content."""
    omit_event_types = set(omit_event_types or ())
    bridge_offsets = dict(bridge_offsets or {})
    rows = []
    for source in sorted(events, key=_offset):
        event = deepcopy(source)
        offset = _offset(event)
        if offset in bridge_offsets:
            mode = bridge_offsets[offset]
            if mode not in BRIDGE_RENDER_MODES:
                raise ValueError(f"invalid bridge render mode: {mode}")
        elif any(start <= offset <= end for start, end in full_ranges):
            mode = "FULL_RENDER"
        elif any(start <= offset <= end for start, end in summary_ranges):
            mode = "OMIT" if str(event.get("event_type") or "") in omit_event_types else "SUMMARY_RENDER"
        else:
            mode = "OMIT"
        event["replay_render_mode"] = mode
        rows.append(event)
    return rows


def make_summary_block(block_id: str, events: list[dict], *, start: int, end: int,
                       text: str, locations: list[str], claims: list[dict]) -> dict:
    selected = [event for event in events if start <= _offset(event) <= end]
    return {
        "summary_block_id": block_id,
        "render_mode": "SUMMARY_RENDER",
        "speaker_class": "KP",
        "speaker_id": "kp",
        "truth_class": "FACT_SUMMARY",
        "text": text,
        "raw_event_offsets": [_offset(event) for event in selected],
        "source_event_ids": [str(event.get("event_id") or "") for event in selected if event.get("event_id")],
        "locations": locations,
        "claims": deepcopy(claims),
    }


def _claim_supported(events_by_offset: dict[int, dict], claim: dict) -> bool:
    candidates = [events_by_offset.get(int(value)) for value in claim.get("evidence_offsets") or []]
    candidates = [event for event in candidates if event]
    expected = claim.get("matches") or {}
    def nested_value(event: dict, path: str):
        value = event
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value

    return any(all(nested_value(event, key) == value for key, value in expected.items()) for event in candidates)


def make_summary_bridge(bridge_id: str, events: list[dict], *, bridge_type: str,
                        text: str, voice_text: str, evidence_offsets: list[int],
                        from_location: str, to_location: str, claims: list[dict],
                        reason_class: str = "BEHAVIORALLY_SUPPORTED_TRANSITION") -> dict:
    if bridge_type not in BRIDGE_RENDER_MODES:
        raise ValueError(f"invalid bridge type: {bridge_type}")
    events_by_offset = {_offset(event): event for event in events}
    selected = [events_by_offset[offset] for offset in evidence_offsets if offset in events_by_offset]
    return {
        "bridge_id": bridge_id,
        "render_mode": bridge_type,
        "speaker_class": "KP",
        "speaker_id": "kp",
        "truth_class": "FACT_BRIDGE",
        "reason_class": reason_class,
        "text": text,
        "voice_text": voice_text,
        "raw_event_offsets": list(evidence_offsets),
        "source_event_ids": [str(event.get("event_id") or "") for event in selected if event.get("event_id")],
        "from_location": from_location,
        "to_location": to_location,
        "claims": deepcopy(claims),
    }


def audit_summary_bridges(events: list[dict], classified: list[dict], bridges: list[dict], *,
                          summary_ranges: list[tuple[int, int]]) -> dict:
    events_by_offset = {_offset(event): event for event in events}
    modes_by_offset = {_offset(event): event.get("replay_render_mode") for event in classified}
    bridges_by_type = {bridge.get("render_mode"): bridge for bridge in bridges}
    entry_missing = []
    exit_missing = []
    unsupported = []
    invented_reason = []
    location_mismatch = []
    unexplained = []
    presented_changes = []

    required_entry_offsets = []
    required_exit_offsets = []
    for start, end in summary_ranges:
        before = events_by_offset.get(start - 1)
        last = events_by_offset.get(end)
        if before and before.get("event_type") == "LOCATION_CHANGE":
            required_entry_offsets.append(start - 1)
        if last and last.get("event_type") == "LOCATION_CHANGE":
            required_exit_offsets.append(end)

    for offset in required_entry_offsets:
        bridge = bridges_by_type.get("SUMMARY_ENTRY_BRIDGE")
        if not bridge or offset not in bridge.get("raw_event_offsets", []):
            entry_missing.append(offset)
    for offset in required_exit_offsets:
        bridge = bridges_by_type.get("SUMMARY_EXIT_BRIDGE")
        if not bridge or offset not in bridge.get("raw_event_offsets", []):
            exit_missing.append(offset)

    banned_reason_terms = ("ため", "ので", "道具を", "方法を探", "作戦", "怖", "考え")
    for bridge in bridges:
        bridge_id = bridge.get("bridge_id") or "unknown"
        if bridge.get("speaker_class") != "KP" or bridge.get("speaker_id") != "kp":
            unsupported.append(f"{bridge_id}:speaker")
        if not bridge.get("source_event_ids") or not bridge.get("raw_event_offsets"):
            unsupported.append(f"{bridge_id}:traceability")
        for claim in bridge.get("claims") or []:
            if not _claim_supported(events_by_offset, claim):
                unsupported.append(f"{bridge_id}:{claim.get('claim_id')}")
            if claim.get("claim_type") == "REASON":
                invented_reason.append(f"{bridge_id}:{claim.get('claim_id')}")
        if bridge.get("reason_class") != "BEHAVIORALLY_SUPPORTED_TRANSITION":
            invented_reason.append(f"{bridge_id}:reason_class")
        if any(term in str(bridge.get("text") or "") for term in banned_reason_terms):
            invented_reason.append(f"{bridge_id}:text")

        transition_offsets = [
            offset for offset in bridge.get("raw_event_offsets") or []
            if events_by_offset.get(offset, {}).get("event_type") == "LOCATION_CHANGE"
        ]
        transition = events_by_offset.get(transition_offsets[-1]) if transition_offsets else None
        if not transition:
            location_mismatch.append(f"{bridge_id}:missing_transition")
        else:
            source_from = str((transition.get("state_before") or {}).get("location") or transition.get("location") or "")
            source_to = str((transition.get("state_after") or {}).get("location") or transition.get("target") or "")
            if source_from != bridge.get("from_location") or source_to != bridge.get("to_location"):
                location_mismatch.append(bridge_id)
            else:
                presented_changes.append(_offset(transition))

    required_changes = set(required_entry_offsets + required_exit_offsets)
    for offset in sorted(required_changes):
        if modes_by_offset.get(offset) not in BRIDGE_RENDER_MODES and modes_by_offset.get(offset) != "FULL_RENDER":
            unexplained.append(offset)
        elif offset not in presented_changes and modes_by_offset.get(offset) in BRIDGE_RENDER_MODES:
            unexplained.append(offset)

    presented_or_summarized = not unexplained and not entry_missing and not exit_missing
    counts = {
        "SUMMARY_ENTRY_CONTEXT_MISSING": len(entry_missing),
        "SUMMARY_EXIT_CONTEXT_MISSING": len(exit_missing),
        "UNGROUNDED_BRIDGE_FACT": len(unsupported),
        "BRIDGE_INVENTED_REASON": len(invented_reason),
        "BRIDGE_LOCATION_MISMATCH": len(location_mismatch),
        "UNEXPLAINED_SCENE_TRANSITION": len(unexplained),
    }
    return {
        "status": "PASS" if presented_or_summarized and not any(counts.values()) else "FAIL",
        "LOCATION_CHANGE_PRESENTED_OR_SUMMARIZED": presented_or_summarized,
        "counts": counts,
        "details": {
            "required_entry_offsets": required_entry_offsets,
            "required_exit_offsets": required_exit_offsets,
            "entry_missing": entry_missing,
            "exit_missing": exit_missing,
            "unsupported_claims": unsupported,
            "invented_reason": invented_reason,
            "location_mismatch": location_mismatch,
            "unexplained_transition_offsets": unexplained,
            "presented_location_change_offsets": sorted(presented_changes),
        },
    }


def audit_summary_plan(events: list[dict], classified: list[dict], blocks: list[dict], *,
                       source_start: int, source_end: int) -> dict:
    events_by_offset = {_offset(event): event for event in events}
    summary_offsets = {value for block in blocks for value in block.get("raw_event_offsets") or []}
    explained_offsets = {
        _offset(event) for event in classified
        if event.get("replay_render_mode") in RENDER_MODES
    }
    unsupported = []
    location_mismatch = []
    invented_reason = []
    causal_order = []
    previous_end = -1
    for block in blocks:
        offsets = block.get("raw_event_offsets") or []
        if offsets and min(offsets) < previous_end:
            causal_order.append(block["summary_block_id"])
        if offsets:
            previous_end = max(offsets)
        allowed_locations = set(block.get("locations") or [])
        for claim in block.get("claims") or []:
            if not _claim_supported(events_by_offset, claim):
                unsupported.append(f"{block['summary_block_id']}:{claim.get('claim_id')}")
            if claim.get("claim_type") == "REASON" and not claim.get("explicit_source_reason"):
                invented_reason.append(f"{block['summary_block_id']}:{claim.get('claim_id')}")
        source_locations = {
            str(events_by_offset[offset].get("location") or "")
            for offset in offsets if offset in events_by_offset and events_by_offset[offset].get("location")
        }
        if allowed_locations and not source_locations.issubset(allowed_locations):
            location_mismatch.append(block["summary_block_id"])

    major_offsets = {
        _offset(event) for event in events
        if source_start <= _offset(event) <= source_end and (
            event.get("event_type") in MAJOR_EVENT_TYPES
            or int(event.get("progress_delta") or 0) > 0
            or bool(event.get("flags_changed"))
        )
    }
    represented = summary_offsets | {
        _offset(event) for event in classified
        if event.get("replay_render_mode") in {"FULL_RENDER", *BRIDGE_RENDER_MODES}
    }
    dropped_major = sorted(major_offsets - represented)
    unexplained = sorted(
        offset for offset in range(source_start, source_end + 1)
        if offset in events_by_offset and offset not in explained_offsets
    )
    traced = sum(bool(block.get("source_event_ids") and block.get("raw_event_offsets")) for block in blocks)
    traceability = traced / len(blocks) if blocks else 1.0
    counts = {
        "UNGROUNDED_SUMMARY_FACT": len(unsupported),
        "SUMMARY_CAUSAL_ORDER_MISMATCH": len(causal_order),
        "SUMMARY_LOCATION_MISMATCH": len(location_mismatch),
        "SUMMARY_DROPPED_MAJOR_STATE_CHANGE": len(dropped_major),
        "SUMMARY_INVENTED_REASON": len(invented_reason),
        "UNEXPLAINED_GAMEPLAY_GAP": len(unexplained),
    }
    return {
        "status": "PASS" if traceability == 1.0 and not any(counts.values()) else "FAIL",
        "SUMMARY_TRACEABILITY": traceability,
        "counts": counts,
        "details": {
            "unsupported_claims": unsupported,
            "causal_order": causal_order,
            "location_mismatch": location_mismatch,
            "dropped_major_offsets": dropped_major,
            "invented_reason": invented_reason,
            "unexplained_offsets": unexplained,
        },
    }
