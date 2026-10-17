# V7 Lifecycle Relation Identity Fix

## Disposition

- Frozen source: `CORBITT_LONGRUN_ITERATION3_V7_HOME_001`
- Source disposition remains `STOPPED_EARLY_UNAUDITED`.
- Resume, backfill, and same-session rerun were not performed.
- Frozen source verification: 84/84 files match the freeze manifest; aggregate identity remains `0b42c8967efc8eba3a900016452456b0faf9e698154c2459cd5446bed600359c`.

## Producer classification

| Pair | First checkpoint | Unified authority | Session display | transaction | adjudication | relation before fix | actor | transition | origin | world-state effect |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | cycle_000003 | `ProgressDirectorV2.record_unified_turn`, `evt_000024_44a7eb7bae63bec39927`, raw offset 23 / turn_id 24 | `commit_system_resolution` → `_append_result_log_with_knowledge` → `append_system_log_entry`, `session_log:000016` | matching `637d099c-f558-4037-a07a-72341c761531` | none | missing on both | pc_01 | introduction → boston_globe | AUTONOMOUS | canonical location and `visit_boston_globe` changed once |
| 2 | cycle_000004 | `ProgressDirectorV2.record_unified_turn`, `evt_000037_45a9d2f4e845577af8f6`, raw offset 36 / turn_id 37 | `apply_forced_progress_breakout` → `append_system_log_entry`, `session_log:000037` | missing on both | none | missing on both | pc_02 only on Unified | boston_globe → central_library | SYSTEM_FORCED | canonical location and `visit_central_library` changed once |
| 3 | cycle_000005 | `ProgressDirectorV2.record_unified_turn`, `evt_000055_ce69976d8d4918ea60a1`, raw offset 54 / turn_id 55 | `commit_system_resolution` → `_append_result_log_with_knowledge` → `append_system_log_entry`, `session_log:000048` | matching `fca3ff1a-dec6-4213-83bd-928ae712cb8d` | none | missing on both | pc_01 | central_library → the_neighborhood | AUTONOMOUS | canonical location and `visit_the_neighborhood` changed once |

Session display rows have no independent raw offset or turn/cycle field. Their stable source identities above are the Normalizer source indices. The first containing checkpoints establish their cycle placement.

## Accepted Simple Move comparison

The accepted V3 fixture contains four Unified and four Session rows. Three pairs use matching transaction ids. Its one unkeyed forced pair is accepted only as the sole remaining complete ordered transition after keyed pairs are removed.

V7 pairs 1 and 3 had the same usable transaction identity. Pair 2 had neither a transaction nor a relation id, and its Session row had been marked `kp_narrated=true`. The old Normalizer evaluated all legacy movement rows as one batch. Pair 2 failed the old unkeyed condition, so the batch returned without merging pairs 1 and 3 as well. Three authority rows plus three display rows therefore became six normalized lifecycle rows.

## Root cause

`MULTIPLE_CAUSES`

1. `PRODUCER_RELATION_ID_MISSING`: the logical transition had no identity shared by its Unified authority and Session display records. This was unavoidable for the system-forced path and fragile for transaction-backed moves.
2. `NORMALIZER_RELATION_MATCH_GAP`: one unkeyed legacy mismatch cancelled otherwise valid transaction-backed pairs because matching was batch-wide and depended on the mutable `kp_narrated` display flag.

The Session counterpart did not lose an identity that had existed earlier. The producer never created a lifecycle relation identity.

## Changes

- A location-change producer now allocates `lifecycle_relation_id` before either stream is committed.
- A transaction-backed move receives `lifecycle_tx_<transaction_id>`; an unkeyed forced move receives one UUID relation, allocated once and reused.
- `append_system_log_entry` and `ProgressDirectorV2.record_unified_turn` copy the same producer value. Record-specific `event_id` values remain independent.
- The Normalizer preserves the relation in normalized events and pairs in this order:
  1. explicit `lifecycle_relation_id`;
  2. adjudication/cause relation in the existing movement-pair stage;
  3. accepted complete structured Simple Move bijection using transactions;
  4. one narrow historical forced transition only when it is the sole unkeyed remainder of a keyed complete stream.
- Relation many-to-one and one-to-many ambiguity fails closed. Route-only matching is not used.
- A merged normalized lifecycle retains both source ids and the complete Session display payload.

## Verification

- Dedicated V7 fixture: before evidence `3 logical → 6 normalized / duplicate=3`; fixed result `3 logical → 3 normalized / duplicate=0`, with all six source ids retained.
- Explicit same-route and reverse-route fixtures remain distinct through relation identity.
- Relation ambiguity fails closed.
- Legacy inferred relation-less rows remain separate.
- Accepted V3 `4 Unified + 4 Session → 4 normalized` remains PASS.
- Frozen V7 read-only reanalysis: duplicate 0, lifecycle misclassification 0, traceability 1.0, dropped 0, segment missing/duplicate/unexpected 0/0/0, coverage 1.0, Normalizer validation PASS.
- V3 read-only reanalysis: all Early Gate fields PASS.
- V6 read-only reanalysis: lifecycle duplicate 0, lifecycle misclassification 0, traceability 1.0, dropped 0, segment coverage 1.0. V6 retains two historical ROLL-contract findings unrelated to this patch.

## V8 gate addition

`tools/audit_lifecycle_relations.py` audits producer relations directly from Raw data. V8 Cycle 5 requires:

- `lifecycle_relation_missing=0`
- `lifecycle_relation_ambiguous=0`
- `lifecycle_relation_unmatched=0`
- `lifecycle_relation_contradictory=0`

This audit does not infer or synthesize relation identity.

## Regression totals

- Core: 593 passed, 0 failed/errors/skips.
- Video Agent: 212 passed, 0 failed/errors/skips.
- Formal Auditor: 24 passed, 0 failed/errors/skips.
- night/runtime: 60 passed, 0 failed/errors/skips.
- Focused Formal Evidence, medicine ROLL, V6 progression, checkpoint/segment, combat and Special Objective group: 68 passed.
- Lifecycle relation audit positive/negative fixtures: 2 passed.
