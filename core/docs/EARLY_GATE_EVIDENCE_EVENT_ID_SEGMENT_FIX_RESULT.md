# Early Gate Evidence / Event ID / Segment Coverage Fix

## Decision

- `EARLY_GATE_EVIDENCE_FIX=PASS`
- `EVENT_ID_LIFECYCLE_FIX=PASS`
- `SEGMENT_COVERAGE_FIX=PASS`
- `NEXT_FULL_LONG_ALLOWED=false`

The three implementation fixes and their deterministic acceptance fixtures pass.  The Full Long gate remains closed because this workspace contains only the reduced Video Agent handoff suite (22 tests), not the recorded 186-test full regression suite.  No Full Long or old-run resume was started.

## Deterministic Early Gate acceptance

- Unified summaries reproduced: 3
- Social checks reproduced: 2
- LOCATION_CHANGE reproduced: 1
- `Unified_summary_missing_adjudication=0`
- `Social_check_missing_adjudication=0`
- `LOCATION_CHANGE_missing_reason=0` (plain lifecycle event excluded from ROLL/NO_ROLL)
- `ROLL_CONTRACT_INCOMPLETE_fixture=0`
- `NORMALIZATION_SOURCE_CONTRADICTION_fixture=0`
- `lifecycle_misclassification=0`
- `traceability=1.0`
- `legacy_text_parse=0`
- `segment_missing=0`
- `segment_duplicate=0`
- `segment_unexpected=0`
- `segment_coverage=1.0`

## Implementation

- Event IDs and zero-based raw offsets are finalized by the central `EventIdentity` allocator before Unified append.
- Checkpoint serialization validates IDs and offsets; it no longer creates IDs.
- Unified summaries inherit the source adjudication envelope. `dice_used=true` alone is not promoted to Formal ROLL.
- Social rolls retain the actual roll tuple and pass through the common ROLL evidence builder before the result can be committed.
- Plain LOCATION_CHANGE/MOVEMENT/STATE_TRANSITION records remain lifecycle events. Explicit NO_ROLL movement remains auditable only with an adjudication ID, reason, and final outcome.
- Segment publication uses temp write, manifest/checksum, COMPLETE marker, and atomic rename before checkpoint publication.
- Segment merge requires missing=0, duplicate=0, unexpected=0, and coverage=1.0. Missing IDs fail as `SEGMENT_EVENT_ID_MISSING`.
- Crash fixtures cover before segment write, during temp write, after segment COMPLETE, before checkpoint COMPLETE, and after checkpoint COMPLETE.

## Regression results

- Core: `579 passed, 23 subtests passed`, 0 FAIL.
- Core evidence/event/segment focus: `43 passed`, 0 FAIL before crash variants; final full Core includes all added fixtures.
- Video Agent handoff bundle: `22 passed`, 0 FAIL. This includes Formal Auditor v2 fixtures and the three new Early Gate normalizer/auditor fixtures.
- Recorded full Video Agent baseline: 186 tests. Those test files are not present in this workspace, so the 186-test gate was not claimable.

## Frozen old run

`CORBITT_LONGRUN_ITERATION3_V1_HOME_001` remains `STOPPED_EARLY_UNAUDITED / EARLY_GATE=FAIL / NEEDS_ITERATION`. Its 101 files were not used as an output destination, resumed, or backfilled.

- Failure record SHA-256: `52d82bfa7a3efc97c34c0d1cfacd689020140c0152a2792b8238635e4e10611b`
- Raw Unified partial log SHA-256: `ec8e29c62801988dcab78f4ec7d99e52df95cf35c409505ab3515cb4688e221a`

## Implementation identity

- Formal evidence contract: `74b97f04d9acd235b3662f82295c5e997227901ff73e8c9eb4e93560244a050e`
- Checkpoint/segment implementation: `1b9898872e6bdff805b6bedf3a029f22c6fb9dcda4543aae43206b2536966236`
- Normalizer: `a33ac9bc8d6b18d8465abb145c35e39a0c8eabdcc2674570b30dc771d4fa9b30`
- Formal Auditor v2: `bd5444dcd67f9e90c12f2723e7f307efce96456d1802ee345ed05c1ab46bb90e`

## Remaining gate

Restore or provide the full Video Agent source/test checkout that produced the 186-test baseline, then run it against these Normalizer and Auditor changes. `NEXT_FULL_LONG_ALLOWED` may become true only after that suite also reports 0 FAIL.
