# Normalized Session Schema 0.1

Top-level fields are `schema_version`, `session_id`, `scenario`, `participants`, `events`, `metadata`, and `provenance`.

Every event contains `event_id`, non-empty `source_event_ids`, nullable `cycle` and `turn`, deterministic `timestamp_or_order`, `scene_id`, structured `location`, `speaker_id`, `actor_id`, `event_type`, `text`, `action`, `dice`, `san`, `combat`, `state_changes`, and `metadata`.

Missing facts remain `null`. Unknown source fields are retained under `metadata.source_payload`. Session-log records without a native ID use deterministic locators such as `session_log:000001`; these identify an exact source stream and index.

Supported event types:

`DIALOGUE`, `KP_DESCRIPTION`, `ACTION_DECLARATION`, `SKILL_CHECK`, `DICE_RESULT`, `SAN_CHECK`, `SAN_LOSS`, `DAMAGE`, `HEAL`, `COMBAT_START`, `COMBAT_ACTION`, `COMBAT_END`, `LOCATION_CHANGE`, `CLUE_FOUND`, `ITEM_GAINED`, `ITEM_LOST`, `SCENARIO_EVENT`, `ENDING`, `SYSTEM_INTERNAL`, `UNKNOWN`.

`created_at` is intentionally absent from deterministic content.
