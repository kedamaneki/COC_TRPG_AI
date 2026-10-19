"""Replay location and actor-visibility contracts.

The module audits derived presentation data without changing accepted source
events.  Runtime candidates use explicit ``required_location``; replay layers
must preserve the same active-location sequence through the timeline.
"""

from __future__ import annotations

import copy


LOCATION_GATES = (
    "OBJECT_INTERACTION_OUTSIDE_LOCATION",
    "OUTCOME_LOCATION_MISMATCH",
    "STALE_FRONTIER_AFTER_LOCATION_CHANGE",
    "STALE_S4_PROPOSAL_AFTER_LOCATION_CHANGE",
    "VIDEO_LOCATION_CONTEXT_STALE",
)

ACTOR_GATES = (
    "PL_PERSISTENT_PORTRAIT",
    "PC_PERSISTENT_PORTRAIT",
    "NPC_MISSING_WHILE_PRESENT",
    "NPC_VISIBLE_WHILE_ABSENT",
    "KP_PERSISTENT_PORTRAIT",
    "SPEAKER_ICON_MISSING_WHILE_SPEAKING",
)

OBJECT_ACTIONS = frozenset({"search", "inspect", "use", "break", "force", "push", "pull", "open", "kick"})
OUTCOME_MARKERS = ("SUCCEEDED", "FAILED", "RESULT", "OUTCOME", "STATE_CHANGE")


def apply_actor_visibility(event: dict, *, npc_portrait_ids: dict[str, str] | None = None) -> dict:
    """Keep only present NPCs persistent; PL/PC/KP remain speaker icons."""
    result = copy.deepcopy(event)
    scene = result.setdefault("scene_state", {})
    present_npcs = [str(x) for x in scene.get("present_npc_ids") or []]
    scene["visible_scene_actor_ids"] = present_npcs
    mapping = npc_portrait_ids or {}
    result["scene_actor_asset_ids"] = [mapping[x] for x in present_npcs if mapping.get(x)]
    if str(result.get("speaker_class") or "").upper() == "SYSTEM":
        result["speaker_icon_asset_id"] = None
    return result


def audit_actor_visibility(events: list[dict]) -> dict:
    counts = {key: 0 for key in ACTOR_GATES}
    details = []
    for event in events:
        speaker_class = str(event.get("speaker_class") or "").upper()
        scene = event.get("scene_state") or {}
        visible = {str(x) for x in scene.get("visible_scene_actor_ids") or []}
        present_npcs = {str(x) for x in scene.get("present_npc_ids") or []}
        persistent_assets = list(event.get("scene_actor_asset_ids") or [])
        if visible & {"pl_01", "pl_02"}:
            counts["PL_PERSISTENT_PORTRAIT"] += 1
        if visible & {"pc_01", "pc_02"} or any("pc01" in x or "pc02" in x for x in persistent_assets):
            counts["PC_PERSISTENT_PORTRAIT"] += 1
        if "kp" in visible or any("kp_sakuya" in x for x in persistent_assets):
            counts["KP_PERSISTENT_PORTRAIT"] += 1
        counts["NPC_MISSING_WHILE_PRESENT"] += len(present_npcs - visible)
        counts["NPC_VISIBLE_WHILE_ABSENT"] += len(visible - present_npcs)
        icon = event.get("speaker_icon_asset_id")
        if speaker_class in {"PL", "PC", "KP"} and not icon:
            counts["SPEAKER_ICON_MISSING_WHILE_SPEAKING"] += 1
        if speaker_class == "SYSTEM" and icon:
            counts["SPEAKER_ICON_MISSING_WHILE_SPEAKING"] += 1
        if any(counts[key] for key in ACTOR_GATES):
            details.append(str(event.get("table_event_id") or event.get("clip_id") or ""))
    return {"status": "PASS" if sum(counts.values()) == 0 else "FAIL", "counts": counts, "details": details}


def _action(event: dict) -> str:
    action = event.get("action")
    if isinstance(action, dict):
        action = action.get("action_id")
    return str(action or event.get("selected_action") or "").lower()


def _required_location(event: dict, object_locations: dict[str, str]) -> str:
    explicit = str(event.get("required_location") or "")
    if explicit:
        return explicit
    target = str(event.get("target") or "")
    action = event.get("action")
    if isinstance(action, dict):
        target = str(action.get("target") or target)
    return str(object_locations.get(target) or "")


def audit_location_consistency(
    raw_events: list[dict],
    table_events: list[dict],
    script_lines: list[dict],
    timeline_clips: list[dict],
    *,
    object_locations: dict[str, str] | None = None,
    background_locations: dict[str, str] | None = None,
) -> dict:
    object_locations = object_locations or {}
    background_locations = background_locations or {}
    counts = {key: 0 for key in LOCATION_GATES}
    details = {key: [] for key in LOCATION_GATES}

    for event in sorted(raw_events, key=lambda x: int(x.get("raw_event_offset", -1))):
        current = str(event.get("location") or "")
        required = _required_location(event, object_locations)
        action = _action(event)
        event_type = str(event.get("event_type") or "")
        mismatch = bool(required and current and required != current)
        if mismatch and action in OBJECT_ACTIONS:
            counts["OBJECT_INTERACTION_OUTSIDE_LOCATION"] += 1
            details["OBJECT_INTERACTION_OUTSIDE_LOCATION"].append(event.get("event_id"))
        if mismatch and any(marker in event_type for marker in OUTCOME_MARKERS):
            counts["OUTCOME_LOCATION_MISMATCH"] += 1
            details["OUTCOME_LOCATION_MISMATCH"].append(event.get("event_id"))
        if mismatch and (event.get("reachable") or event.get("executable")):
            counts["STALE_FRONTIER_AFTER_LOCATION_CHANGE"] += 1
            details["STALE_FRONTIER_AFTER_LOCATION_CHANGE"].append(event.get("event_id"))
        binding = event.get("progression_binding") or {}
        if mismatch and str(event.get("intervention_level") or "") == "S4" and (
            binding.get("selected") or binding.get("proposal_bound") or event.get("forced_action")
        ):
            counts["STALE_S4_PROPOSAL_AFTER_LOCATION_CHANGE"] += 1
            details["STALE_S4_PROPOSAL_AFTER_LOCATION_CHANGE"].append(event.get("event_id"))

    table_by_id = {str(x.get("table_event_id") or ""): x for x in table_events}
    script_by_id = {str(x.get("source_table_event_id") or ""): x for x in script_lines}
    for table_id, table in table_by_id.items():
        expected = str((table.get("scene_state") or {}).get("current_location") or "")
        required = str(table.get("required_location") or "")
        if required and expected and required != expected:
            counts["VIDEO_LOCATION_CONTEXT_STALE"] += 1
            details["VIDEO_LOCATION_CONTEXT_STALE"].append(f"{table_id}:table")
        line = script_by_id.get(table_id) or {}
        line_location = str((line.get("scene_state") or {}).get("current_location") or line.get("background_location_id") or "")
        if expected and line_location and expected != line_location:
            counts["VIDEO_LOCATION_CONTEXT_STALE"] += 1
            details["VIDEO_LOCATION_CONTEXT_STALE"].append(f"{table_id}:script")
        asset_location = str(background_locations.get(str(line.get("background_asset_id") or "")) or "")
        if expected and asset_location and expected != asset_location:
            counts["VIDEO_LOCATION_CONTEXT_STALE"] += 1
            details["VIDEO_LOCATION_CONTEXT_STALE"].append(f"{table_id}:background")
    for clip in timeline_clips:
        table_id = str(clip.get("source_table_event_id") or "")
        expected = str(((table_by_id.get(table_id) or {}).get("scene_state") or {}).get("current_location") or "")
        actual = str((clip.get("scene_state") or {}).get("current_location") or clip.get("background_location_id") or "")
        asset_location = str(background_locations.get(str(clip.get("background_asset_id") or "")) or "")
        if expected and actual and expected != actual:
            counts["VIDEO_LOCATION_CONTEXT_STALE"] += 1
            details["VIDEO_LOCATION_CONTEXT_STALE"].append(f"{table_id}:timeline")
        if expected and asset_location and expected != asset_location:
            counts["VIDEO_LOCATION_CONTEXT_STALE"] += 1
            details["VIDEO_LOCATION_CONTEXT_STALE"].append(f"{table_id}:timeline_background")
    return {"status": "PASS" if sum(counts.values()) == 0 else "FAIL", "counts": counts, "details": details}
