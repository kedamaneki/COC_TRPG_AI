# CORBITT V17 Full-Long Acceptance Decision

**V17_FULL_LONG_ACCEPTANCE = BLOCKED**  
**Session:** `CORBITT_LONGRUN_ITERATION3_V17_HOME_001`  
**Git / preflight:** `v17-preflight-accepted` @ `66d7aed` (main, clean)  
**Fresh:** cycle=0, resume_count=0, migration=null  
**Model:** `qwen2.5:14b` / OLLAMA=PASS  

Raw: 862 files / `ca7f5627007ec8e0452a6c6de11c4f2d893c28ccc2ab355557065cf0bfcacb9c`

```text
PRODUCTION_WIRING_INTEGRITY = PASS
RUNTIME_CONTRACT_INTEGRITY = PASS
FORMAL_CORRECTNESS = FAIL
SCENARIO_FIDELITY = FAIL
NATURAL_DECISION_QUALITY = PASS
KNOWN_GOOD_PROMOTION = BLOCKED
KNOWN_GOOD_BASELINE = none
ACCEPTANCE_TAG = none
V17_STATUS = IMMUTABLE_NEGATIVE_REFERENCE
V17_SAME_SESSION_RERUN = FORBIDDEN
NEXT_SESSION_HINT = CORBITT_LONGRUN_ITERATION3_V18_HOME_001
VIDEO_REGENERATION = NOT_AUTHORIZED
```

Stop: Night Guard `FULL_LONG_COMPLETION_CONTRACT_FAIL` after 60 cycles without scenario clear / Corbitt defeat / final battle.

V17 multi-component fix **did** hold on production Full-Long for wiring + runtime contract + NDM quality (NDM commits=202, SAFE/UNSAFE legacy=0, coverage=1.0, schema mismatch=0, list.get=0). Remaining blockers are scenario non-completion / fidelity (no basement boss path within max cycles).

See `docs/CORBITT_V17_NEGATIVE_REFERENCE_DECISION.md` for full 5-axis evidence.
