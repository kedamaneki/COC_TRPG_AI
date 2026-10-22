# V16 Preimplementation Fix — Implementation Report

**Status:** `V16_PREIMPLEMENTATION_FIX_IMPLEMENTATION_V1 = PASS`  
**Design commit:** `bcca870` (`docs: approve V16 preimplementation fix design`)  
**V16_EXECUTED:** false  
**V16 session reserved:** `CORBITT_LONGRUN_ITERATION3_V16_HOME_001` (not run)

## Summary

Production Natural Decision Model is wired into evaluation bootstrap and PL action path; Corbitt combat termination requires the full validated-kill chain; smoke proved causal bind with `LEGACY_DECISION_COMMIT_COUNT=0`.

## Gates

| Gate | Result |
|---|---|
| NDM production wiring | PASS |
| Causal action binding | PASS |
| S-level authority = natural_decision_v1 | PASS |
| LEGACY_DECISION_COMMIT_COUNT (smoke) | 0 |
| Combat full termination chain | PASS |
| CN / CT / NDM-C fixtures | PASS |
| Core tests | 725 passed |
| V13/V14/V15 rehash | PASS |
| Production smoke | PASS |
| V16_PRECHECK | PASS |
| V16_READY | true |

## Key modules

- `core/src/reasoning/runtime.py`
- `core/src/ndm_integration.py`
- `core/src/CombatTerminationContract.py`
- `core/src/test_v16_ndm_causal_and_combat.py`
- `tools/night_guard/ndm_wiring_smoke.py`
