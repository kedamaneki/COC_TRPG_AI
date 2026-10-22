# CORBITT V16 Full-Long Acceptance Decision

**V16_FULL_LONG_ACCEPTANCE = BLOCKED**  
**KNOWN_GOOD_PROMOTION = BLOCKED**  
**KNOWN_GOOD_BASELINE = none**  
**ACCEPTANCE_TAG = none**  
**VIDEO_REGENERATION = NOT_AUTHORIZED**  
**FAILURE_AXIS = MULTI_AXIS**  
**Disposition = IMMUTABLE_NEGATIVE_REFERENCE**

See `docs/CORBITT_V16_NEGATIVE_REFERENCE_DECISION.md` for full evidence.

| Axis | Result |
|---|---|
| PRODUCTION_WIRING_INTEGRITY | FAIL (`NDM_DECISION_CAUSAL_COVERAGE=0.0`, `LEGACY_DECISION_COMMIT_COUNT=194`) |
| FORMAL_CORRECTNESS | FAIL (`SCENARIO_COMPLETED=false`, completion atomicity FAIL, formal normalizer/auditor not_run) |
| SCENARIO_FIDELITY | FAIL (no final battle / no validated kill / no termination chain) |
| NATURAL_DECISION_QUALITY | FAIL (coverage 0 + SAFE_LEGACY dominance + meaningful progress 0) |

Session: `CORBITT_LONGRUN_ITERATION3_V16_HOME_001`  
Preflight: `v16-preflight-accepted` @ `4917233`  
Raw: 862 files / `ae254b70d595ca64dc24c24e0b23c481a56b0f88de95323da24ac8b338938b3a`
