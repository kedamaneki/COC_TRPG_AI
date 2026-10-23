# CORBITT V17 Production Wiring Acceptance

**Axis:** `PRODUCTION_WIRING_INTEGRITY = PASS`  
**Session:** `CORBITT_LONGRUN_ITERATION3_V17_HOME_001`  
**Overall Known-Good:** BLOCKED (other axes)

| Counter | Value |
|---|---|
| NATURAL_DECISION_RUNTIME_ACTIVE | true |
| NDM_DECISION_COMMIT_COUNT | 202 |
| SAFE_LEGACY_DECISION_COMMIT_COUNT | 0 |
| UNSAFE_LEGACY_DECISION_COMMIT_COUNT | 0 |
| REASONING_FALLBACK_COUNT | 0 |
| NDM_DECISION_CAUSAL_COVERAGE | 1.0 |
| SELECTED_ACTION_REASONING_ID_MISSING | 0 |
| ACTION_SELECTED decision_source | natural_decision_v1 × 202 |

Causal binding: every observed `ACTION_SELECTED` carried `reasoning_id` and `decision_source=natural_decision_v1`. No unsafe legacy commit path observed.
