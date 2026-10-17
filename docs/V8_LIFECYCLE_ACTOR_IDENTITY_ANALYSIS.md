# V8 Lifecycle Actor Identity Analysis

## Disposition

- Frozen source: `CORBITT_LONGRUN_ITERATION3_V8_HOME_001`
- Source disposition remains `STOPPED_EARLY_UNAUDITED`.
- Resume, backfill, and same-session rerun were not performed.
- Frozen source verification: 84/84 files match the freeze manifest.
- Aggregate SHA-256 remains `7786ee3d13bf0d3aa83d0ab022b5de40c4694c926e5090c5f5590a0ff4674641`.

## Conflicting lifecycle

- Relation: `lifecycle_b51ee8ad2fe24ec7925b2eb3e2ec2dd9`
- Transition: `introduction -> boston_globe`
- Resolution actor: `pc_02`
- Session display actor: `pc_02`
- Unified authority actor: `pc_01`
- Unified event: `evt_000027_a211b612289db4eb1d40`, raw offset 26, turn 27
- Session source: `session_log:000035`
- Origin: `SYSTEM_FORCED`
- World-state mutation occurred once.

## Producer trace

1. The validation-retry path selected `pc_02` and called `apply_forced_progress_breakout(..., pl_id="pc_02")`.
2. `process_system_action` committed the location transition using that resolved actor context.
3. `append_system_log_entry` received the explicit `pl_id`, so the Session display row retained `pc_02`.
4. The logical forced action and lifecycle result did not store an actor identity.
5. `record_unified_turn` therefore fell through `action.actor_id`, `action.pc_id`, and finally used mutable `state.pl_id`; it recorded `pc_01`.

## Root cause

`ACTOR_NOT_STORED_IN_LOGICAL_LIFECYCLE`

The relation identity was frozen correctly, but actor identity was not part of the same immutable logical lifecycle. The Unified producer consequently used mutable runtime state after resolution.

## Candidate fix on feature branch

Branch: `feature/fix-lifecycle-actor-identity-v9`

- Freeze `lifecycle_actor_id` at the same producer boundary as `lifecycle_relation_id`.
- Reject a missing actor or an actor mutation after resolution.
- Pass the frozen actor to Session display and Unified authority records.
- Make Unified lifecycle output prefer the frozen actor and reject a contradictory action actor.
- Keep Normalizer contradiction detection unchanged and fail-closed.
- Add the V8 conflict fixture, actor-rotation fixture, next-actor fixture, and detailed actor contradiction audit output.

## Verification

- Focused lifecycle/introduction/audit suite: 23 passed.
- Core: 596 passed + 26 subtests, 0 failed/errors/skips.
- Video Agent: 212 passed, 0 failed/errors/skips.
- Formal Auditor group: 27 passed, 0 failed/errors/skips.
- night/runtime: 60 passed, 0 failed/errors/skips.
- V3/V6/V7 read-only normalization: validation PASS, traceability 1.0, dropped events 0.
- V8 frozen source: 84/84 hashes unchanged.

## Historical-source acceptance

Read-only V8 reanalysis correctly returns:

- `lifecycle_relation_missing=0`
- `lifecycle_relation_ambiguous=0`
- `lifecycle_relation_unmatched=0`
- `lifecycle_relation_contradictory=1`
- `lifecycle_actor_contradiction=1`

This exact historical finding is now the positive acceptance condition named
`V8_HISTORICAL_CONTRADICTION_REPRODUCED`. The frozen record is not expected to
become contradiction-free. Backfill and Normalizer/auditor correction remain
prohibited.

The patched producer is evaluated separately. Its forced-move fixture, actor
rotation fixture, and next-actor fixture require both relation contradiction and
actor contradiction to remain zero.

## Gate result

- `V8_SOURCE_INTEGRITY=PASS`
- `V8_HISTORICAL_CONTRADICTION_REPRODUCED=PASS`
- `LIFECYCLE_ACTOR_PRODUCER_FIX_CANDIDATE=PASS`
- `PATCHED_PRODUCER_FIXTURES=PASS`
- `VIDEO_SOURCE_ELIGIBLE=false`

The historical V8 finding is preserved as evidence and is no longer a blocker
for accepting the V9 producer fix.
