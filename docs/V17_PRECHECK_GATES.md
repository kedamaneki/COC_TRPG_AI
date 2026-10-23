# V17 Precheck Gates

**Status:** COMPLETE  
**Formal V17 Full-Long:** blocked until gates PASS + Human Review of implementation  

## Gate table

| Gate | Operator | Expect |
|---|---|---|
| RECENT_ACTION_SCHEMA_CONSISTENT | == | true |
| RECENT_ACTION_SCHEMA_MISMATCH_COUNT | == | 0 |
| RUNTIME_CONTRACT_VIOLATION_COUNT | == | 0 |
| UNSAFE_LEGACY_DECISION_COMMIT_COUNT | == | 0 |
| SAFE_FALLBACK_FAILURE_COUNT | == | 0 |
| PROGRESS_EVENTS_WIRED | == | true |
| FULL_LONG_METRICS_NON_NULL_TEST | == | PASS |
| NDM_CAUSAL_ACTION_BINDING | == | PASS |
| NDM_DECISION_COMMIT_COUNT_SMOKE | > | 0 |
| HISTORICAL_TAG_RETARGET_REQUIRED | == | false |
| NDM_ALGORITHM_CHANGE_DETECTED | == | false |

### Notes

- `SAFE_LEGACY_DECISION_COMMIT_COUNT` is **reported** but **not** required zero.  
- `NDM_DECISION_CAUSAL_COVERAGE` must be **defined and numeric** on smoke; Full-Long threshold set at acceptance design (not this precheck doc’s hard 1.0 unless smoke proves only NDM commits).  
- Historical tags (v13–v16-*) must not be retargeted.

## Precheck inputs

1. Unit/integration fixtures RA*/RC*/SF*/PT*/CT*  
2. Smoke `CORBITT_NDM_SCHEMA_SMOKE_V17PRE_001`  
3. Negative smoke malformed RecentAction  
4. `git` identity clean; implementation commit annotated in smoke receipt  
5. V13/V14/V15/V16 Raw rehash PASS  

## Fail action

Any gate FAIL ⇒ `V17_READY = false`; no Full-Long; no Known-Good; no video.
