# CORBITT_LONGRUN_ITERATION3_V3_HOME_001 Early Gate Result

- `FULL_LONG_RAW_RUN = STOPPED_EARLY_UNAUDITED`
- `EARLY_GATE = FAIL`
- `FULL_LONG_AUTONOMOUS_REEVALUATION = NEEDS_ITERATION`
- `NEXT_FULL_LONG_ALLOWED = false`
- `VIDEO_SOURCE_ELIGIBLE = false`

## Boundary

- Cycle / Turn: `5 / 7`
- Resume count: `0`
- Migration: `none`
- Execution profile: `SINGLE_PC`
- Routing: `PL / KP / JUDGE -> PRIMARY`
- Model: `qwen2.5:14b`, `qwen2`, `14.8B`, `Q4_K_M`
- The same process stopped at the Cycle 5 gate through `EARLY_GATE_ABORT.json`.
- No code/config change, resume, automatic fix, or replacement Run was performed.
- Formal full-session PASS/FAIL and Legacy Comparison were not run because the session is incomplete.

## Early Gate

- `ROLL_CONTRACT_INCOMPLETE = 0`
- `NORMALIZATION_SOURCE_CONTRADICTION = 0`
- `lifecycle_misclassification = 0`
- `movement_adjudications = 0`
- `linked_location_changes = 0`
- `simple_unified_location_changes = 4`
- `session_location_counterparts = 4`
- `normalized_location_change_events = 8`
- `duplicate_lifecycle_events = 4` **FAIL**
- `event_id_missing = 0`
- `raw_offset_missing = 0`
- `traceability = 1.0`
- `dropped_events = 0`
- `legacy_text_parse = 0`
- `Normalizer validation = PASS`
- Segment raw / covered: `32 / 32`
- Segment missing / duplicate / unexpected: `0 / 0 / 0`
- Segment coverage: `1.0`
- LLM calls: `31`
- LLM errors / retries / runtime fallbacks: `0 / 0 / 0`
- Input Identity: `PASS`

## Failure

The Core correctly emitted each unconditional move as one `LOCATION_CHANGE` without `resolution_mode`. The Session Log also emitted a display row for the same move. Because simple movement intentionally has no `adjudication_id` or `cause_adjudication_id`, the Normalizer's cause-ID deduplication did not pair those two streams.

Four actual moves therefore became eight normalized lifecycle events:

- Unified lifecycle transitions: 4
- Session Log counterparts: 4
- Duplicate lifecycle events: 4

The prior lifecycle classification fix itself held: no `LOCATION_CHANGE` retained `ROLL` or `NO_ROLL`.

## Read-only Staging

`C:\Users\ri4re\Documents\Codex\2026-10-04\referenced-chatgpt-conversation-this-is-an\video-production-agent\formal-analysis\CORBITT_LONGRUN_ITERATION3_V3_HOME_001_EARLY_CYCLE5`

The staging Normalizer/Auditor smoke did not write to the Raw logs or checkpoints.

## Required Next Work

The next change must give simple Unified/Session movement counterparts a deterministic relation or deduplication key that does not invent an adjudication. The known-bad lifecycle detector must remain active. This stopped Run must not be resumed or backfilled.
