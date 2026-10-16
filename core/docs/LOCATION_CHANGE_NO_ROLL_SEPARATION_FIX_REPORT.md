# LOCATION_CHANGE / NO_ROLL Separation Fix Report

Date: 2026-10-15

## Decision

- `LOCATION_CHANGE_NO_ROLL_SEPARATION_FIX = PASS`
- `MOVE_ADJUDICATION_LIFECYCLE_SPLIT = PASS`
- `NEXT_FULL_LONG_ALLOWED = true`
- `VIDEO_SOURCE_ELIGIBLE = false`
- `CORBITT_LONGRUN_ITERATION3_V2_HOME_001` remains `STOPPED_EARLY_UNAUDITED`; no Formal PASS was issued.

## Scope

Only the movement adjudication/lifecycle boundary was changed. Segment persistence, EventIdentity allocation, routing, prompts, scenario data, PC/NPC conversion, and the stopped Raw Run were not changed.

## Root Cause and Fix

The Core attached a synthetic `NO_ROLL` envelope to every successful `move`. `record_unified_turn` then represented that row as movement state, and the Normalizer converted it to `LOCATION_CHANGE` while retaining the adjudication fields. Four Session Log counterparts repeated the same mistake, producing 9 lifecycle findings from 5 unique movement adjudications.

The corrected contract is:

- An unconditional move commits one `LOCATION_CHANGE` lifecycle event with no `resolution_mode`.
- A move that has an explicit adjudication commits `MOVE_ACTION_RESOLVED`, followed by `LOCATION_CHANGE` linked through `cause_adjudication_id`.
- The Normalizer splits complete legacy mixed rows, does not invent missing reason/outcome fields, coalesces Unified/Session counterparts, and retains every source ID.
- The Formal Auditor independently rejects any lifecycle event that still carries `ROLL` or `NO_ROLL`.

## Deterministic Fixtures

- Simple move -> one `LOCATION_CHANGE`, no adjudication fields: PASS.
- Complete movement `NO_ROLL` -> one `MOVE_ACTION_RESOLVED` plus one linked `LOCATION_CHANGE`: PASS.
- `LOCATION_CHANGE + NO_ROLL` known-bad input -> `LIFECYCLE_MISCLASSIFIED_AS_NO_ROLL`: PASS.
- Legacy Session Log movement text -> lifecycle only: PASS.
- 5 unique movement adjudications + 4 Session Log counterparts -> 5 adjudications, 5 linked lifecycle transitions, 0 duplicate lifecycle events: PASS.
- New Core split preserves explicit `cause_adjudication_id`: PASS.

## Regression Results

- Core: `582 passed, 23 subtests passed`, 0 failed. Previous baseline was 579 + 23.
- Video Production Agent: `193 passed`, 0 failed. Required baseline was 189.
- Formal Auditor fixtures: PASS, including valid/invalid ROLL and NO_ROLL, lifecycle known-bad rejection, existing Iteration 2 checks, and false-positive regression.
- Segment crash/resume and coverage fixtures: PASS as part of the Core suite.

## Read-only Reanalysis

Source: read-only copy of `CORBITT_LONGRUN_ITERATION3_V2_HOME_001`, Cycle 5.

- `ROLL_CONTRACT_INCOMPLETE = 0`
- `NORMALIZATION_SOURCE_CONTRADICTION = 0`
- `lifecycle_misclassification = 0`
- `unique_move_adjudications = 5`
- `normalized_lifecycle_events = 6` (5 linked transitions plus 1 independent lifecycle row)
- `duplicate_lifecycle_events = 0`
- `traceability = 1.0`
- `dropped_events = 0`
- `legacy_text_parse = 0`
- `segment missing / duplicate / unexpected = 0 / 0 / 0`
- `segment coverage = 1.0`
- Normalizer validation: PASS
- Formal verdict: `NOT_ISSUED_RUN_INCOMPLETE`

Staging output:

`C:\Users\ri4re\Documents\Codex\2026-10-04\referenced-chatgpt-conversation-this-is-an\video-production-agent\formal-analysis\CORBITT_LONGRUN_ITERATION3_V2_HOME_001_LOCATION_FIX_V2_20261015`

## Integrity

- Frozen Raw Run manifest: 96 files checked, 96 matched, 0 mismatches.
- No resume, backfill, migration, or Raw Run modification was performed.
- No Full Long Run was started.

## Implementation Identities

- `src/main.py`: `8cf1403ec36a9bf8f931429c4a3e172d2ecb5361decc08d28c96c480fc7393c6`
- `src/ProgressDirectorV2.py`: `e039fc71a736e48fbe4d73025b4212ea43ff1ca0988ada59cd9f4bab4e5632bc`
- Normalizer: `d3f4f9cf2933139c94e9133d69f989635ecc7e07fad13b277fed865fff58074b`
- Video pipeline: `0d1d34468f4501a6fbaa8a0240c6ecac385f4191e27b1a6e94f4c862f2bd5045`
- Formal Auditor v2: `858b33c80d73c940ca2c8e9e6c5b63d34bb6e792e29307ed438fc2169f86608e`

## Next Run Boundary

The next Full Long may use a new Session ID such as `CORBITT_LONGRUN_ITERATION3_V3_HOME_001`, starting at Cycle 0 with `resume_count=0` and no migration. It must still run the Cycle 3-5 Early Gate before continuing.
