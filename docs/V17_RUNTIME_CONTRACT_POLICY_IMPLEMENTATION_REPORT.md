# V17 Runtime Contract Policy Implementation Report

**RUNTIME_CONTRACT_VIOLATION_POLICY = PASS**  
**ATTRIBUTE_ERROR_TO_SAFE_FALLBACK = 0**  
**CONTRACT_VIOLATION_FAIL_CLOSED = PASS**  
**SAFE_FALLBACK_POLICY = PASS**  
**SAFE_FALLBACK_RECURSION_COUNT = 0** (policy enforced; smoke/tests)

## Modules

- `reasoning/error_class.py` — classify + `NDMRuntimeContractViolation` / `SafeFallbackFailure`
- `reasoning/runtime.py` — decide ingress validate; classified fallback gate; FAIL_CLOSED / SAFE_FALLBACK_FAILURE → BLOCK
- `reasoning/pipeline.py` — AttributeError/TypeError/KeyError/RecentActionContractError re-raised; fallback self-fault → `SAFE_FALLBACK_FAILURE`

## Counters

`RUNTIME_CONTRACT_VIOLATION_COUNT`, `SAFE_FALLBACK_FAILURE_COUNT`, `SAFE_FALLBACK_RECURSION_COUNT`, separated SAFE vs UNSAFE legacy.
