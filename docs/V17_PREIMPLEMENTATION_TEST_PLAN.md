# V17 Preimplementation Test Plan

**Track G + Smoke design (Track H excerpts)**  
**Status:** COMPLETE  
**IMPLEMENTATION_STARTED:** false

## Scope

Deterministic unit/integration tests + production-path smoke design.  
**No NDM algorithm changes** (PL scoring, KP S0–S4, frontiers, personality, group model).

## RecentAction (RA*)

| ID | Case | Expect |
|---|---|---|
| RA1 | legacy `[action, target]` → Normalizer | canonical RecentAction PASS |
| RA2 | canonical dict schema_version=1 | PASS |
| RA3 | unknown list shape (len≠2 / nested) | RUNTIME_CONTRACT_VIOLATION |
| RA4 | required field missing / wrong type | RUNTIME_CONTRACT_VIOLATION |

## Runtime contract (RC*)

| ID | Case | Expect |
|---|---|---|
| RC1 | internal AttributeError / schema mismatch | SAFE_LEGACY **forbidden**; run **BLOCK**; RUNTIME_CONTRACT_VIOLATION_COUNT≥1 |
| RC2 | provider timeout (simulated) | SAFE_LEGACY **allowed** (recoverable) |

## SAFE fallback (SF*)

| ID | Case | Expect |
|---|---|---|
| SF1 | recoverable reasoning failure | SAFE_LEGACY commit; counters separated |
| SF2 | SAFE fallback itself fails | SAFE_FALLBACK_FAILURE; **BLOCK**; no recursion |
| SF3 | contract violation | **first occurrence BLOCK** (no streak) |

## Progress telemetry (PT*)

| ID | Case | Expect |
|---|---|---|
| PT1 | new fact signal | ProgressEvent MEANINGFUL / NEW_FACT |
| PT2 | object/location state change | ProgressEvent emitted |
| PT3 | stall → self-review → meaningful action before KP escalate | self_recovery evidence + count |

## Counters (CT*)

| ID | Case | Expect |
|---|---|---|
| CT1 | NDM bound commit | only `NDM_DECISION_COMMIT_COUNT` (+ not SAFE/UNSAFE) |
| CT2 | SAFE_LEGACY commit | `SAFE_LEGACY_DECISION_COMMIT_COUNT` distinct; not UNSAFE |
| CT3 | unsafe legacy commit attempt | `UNSAFE_LEGACY_DECISION_COMMIT_COUNT`++; gate fail / reject |

## Production smoke design

**Session id (not formal V17 Full-Long):**  
`CORBITT_NDM_SCHEMA_SMOKE_V17PRE_001`

### Positive smoke must show

- RecentAction canonical schema PASS  
- `NDM_DECISION_COMMIT_COUNT > 0`  
- SAFE fallback classification normal (0 or recoverable-only)  
- `RUNTIME_CONTRACT_VIOLATION_COUNT = 0`  
- `UNSAFE_LEGACY_DECISION_COMMIT_COUNT = 0`  
- `SAFE_FALLBACK_FAILURE_COUNT = 0`  
- Progress events > 0  
- MEANINGFUL_PROGRESS_RATE numeric (non-null)  
- SELF_RECOVERY_RATE computable (numeric; 0.0 OK)  
- NDM causal binding on NDM commits  

### Negative smoke (synthetic)

- Inject malformed RecentAction → **first occurrence BLOCK**  
- Prove no SAFE_LEGACY absorption of contract violation  

## Regression floor

- Existing core pytest suite remains green (≥ prior V16 baseline count)  
- V13–V16 Raw rehash unchanged  
- NDM algorithm unit tests unchanged in intent  

## Implementation touch list (for later; not now)

See master design § Impact files.
