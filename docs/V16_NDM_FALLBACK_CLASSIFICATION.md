# V16 NDM Fallback Classification

**FALLBACKS_CLASSIFIED = 194 / 194**  
**UNCLASSIFIED_FALLBACK_COUNT = 0**  
**EXPECTED_LEGACY_DECISION_COMMIT_COUNT = 194** (matches `PL_REASONING_FALLBACK` count)

Machine-readable: `docs/V16_NDM_FALLBACK_CLASSIFICATION.json` (1 record / fallback).

## Raw failure_reason (100%)

| failure_reason | count | % |
|---|---:|---:|
| `'list' object has no attribute 'get'` | 194 | 100.0 |

## Taxonomy mapping

Required buckets used; concrete subtype added from Raw:

| fallback_reason | subtype | count | % |
|---|---|---:|---:|
| OTHER | `RECENT_ACTIONS_SCHEMA_MISMATCH_FAIL_CLOSED_MISHANDLED` | 189 | 97.42 |
| OTHER | `RECENT_ACTIONS_SCHEMA_MISMATCH_PIPELINE_PROPAGATED` | 5 | 2.58 |

No evidence for mass:

- REASONING_GENERATION_FAILURE / PARSE_FAILURE  
- NO_CANDIDATE_* / SELECTED_CANDIDATE_*  
- *_BINDING_FAILURE as primary  
- GROUP_DECISION_UNRESOLVED / KP_POLICY_REJECTION  
- EXECUTOR_LEGALITY_REJECTION / UNBOUND_DECISION_COMMIT_PREVENTED  

`UNBOUND_DECISION_COMMIT_REJECTION_COUNT = 0` in this fallback population.

## Pattern split (event order)

| pattern | count | meaning |
|---|---:|---|
| `NDM_SUCCESS` | 3 | COMPLETED → KP → ACTION_SELECTED |
| `PURE_FALLBACK` | 5 | FALLBACK only (pipeline AttributeError propagated; runtime `_fallback_select`) |
| `COMPLETED_THEN_FALLBACK` | 189 | COMPLETED then same `decision_transaction_id` FALLBACK |

The 5 pure fallbacks match `SafeLegacyProgression.MAX_FALLBACK_STREAK = 5`: pipeline `fallback.select` increments streak then throws on list `.get`; on the 6th pipeline failure, `FallbackUnboundedError` yields `mode=FAIL_CLOSED`, which runtime mishandles as a pseudo-success path (emits COMPLETED with null action) before falling back again.

## TOP causes

| rank | cause | count |
|---:|---|---:|
| 1 | OTHER / FAIL_CLOSED mishandle after schema mismatch | 189 |
| 2 | OTHER / pipeline AttributeError propagated | 5 |

**TOP_CAUSES_COVERAGE (top1) = 189/194 = 0.974**  
**TOP_CAUSES_COVERAGE (top2 / all) = 194/194 = 1.0** → Pareto: single root exception class covers 100%.

## Per-record fields

Each JSON record includes required fields; absent Raw fields are explicitly `MISSING` (no invented values):

`cycle` is an ordinal approximation mapped onto C0–60 bands for distribution only; exact per-fallback cycle/turn were not on `PL_REASONING_FALLBACK` events.

## Cycle-band distribution (approx)

| band | fallback count |
|---|---:|
| C0–10 | 30 |
| C11–20 | 33 |
| C21–30 | 33 |
| C31–40 | 34 |
| C41–50 | 33 |
| C51–60 | 31 |

**Time pattern:** `EARLY_BURST_THEN_UNIFORM` — 3 NDM successes, 5 pure fallbacks, then sustained COMPLETED→FALLBACK for the rest of the Full-Long.

## Safety vs availability

| Gate | Result |
|---|---|
| SAFE_FALLBACK_SAFETY | **PASS** (`FALLBACK_GUARD_VIOLATION=0`; no knowledge-leak path) |
| SAFE_FALLBACK_AVAILABILITY | **FAIL** (fallback used as primary decision path) |
