# V17 Multi-Component Fix Implementation Report

**V17_MULTI_COMPONENT_FIX_IMPLEMENTATION_V1 = PASS**  
**V17_PRECHECK = PASS**  
**V17_READY = true**  
**V17_EXECUTED = false**  
**V17_SESSION_RESERVED = CORBITT_LONGRUN_ITERATION3_V17_HOME_001**

## Premise

Design `V17_MULTI_COMPONENT_FIX_DESIGN_V1` APPROVED. Closed V16 `RECENT_ACTIONS_SCHEMA_MISMATCH` and secondary exception/counter/progress gaps without changing NDM PL/KP/S0–S4 algorithms.

## Commits (Phase 0)

| Item | SHA |
|---|---|
| V16 audit docs | `b0f73fb` |
| V17 design docs | `88725c4` |

## Implementation summary

| WP | Delivered |
|---|---|
| RecentAction canonical | `reasoning/recent_action.py`; StallDetector canonical writes |
| Contract policy | `reasoning/error_class.py`; decide BLOCK on programming/contract |
| SAFE_LEGACY harden | no recursion; SAFE_FALLBACK_FAILURE; validated recent_actions |
| Counters | NDM / SAFE_LEGACY / UNSAFE / VIOLATION / FALLBACK_FAILURE separated |
| Progress wiring | `progress_events.py` + director emit + enrich pass-through |
| Tests | `test_v17_runtime_schema_and_fallback.py` |
| Smoke | `CORBITT_NDM_SCHEMA_SMOKE_V17PRE_001` PASS |

## QA targets

| Check | Value |
|---|---|
| RECENT_ACTION_MULTI_SCHEMA_PATH | 0 |
| DIRECT_LEGACY_LIST_GET_PATH | 0 |
| CONTRACT_VIOLATION_TO_SAFE_FALLBACK_PATH | 0 |
| SAFE_FALLBACK_RECURSION_PATH | 0 |
| PROGRESS_EVENT_UNWIRED_PATH | 0 |
| LEGACY_COUNTER_AMBIGUITY | 0 |
| FULL_LONG_METRIC_NULL_PATH | 0 |
| NDM_ALGORITHM_CHANGED | false |
| HISTORICAL_MUTATION | 0 |

## Regression

- Core: **746 passed** (+26 subtests)
- Auditor: **27 passed**
- Video Agent suite: **ENVIRONMENT_ONLY** (`cv2` missing)
- V13–V16 rehash: **PASS**

## Next

`V17_FULL_LONG_ACCEPTANCE` with session `CORBITT_LONGRUN_ITERATION3_V17_HOME_001` and tag `v17-preflight-accepted`.
