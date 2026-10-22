# V16 Precheck Gates

**Parent:** `V16_PREIMPLEMENTATION_FIX_DESIGN_V1`  
**When:** After implementation + L0/L1/L2 tests; **before** formal `CORBITT_LONGRUN_ITERATION3_V16_HOME_001`  
**CODE_CHANGED:** 0 in this design task

---

## 1. Gate groups

### G-HIST — Historical immutability

| Gate | Pass |
|---|---|
| V13 Raw rehash | 373 / `fd42df1d…e44d` |
| V14 Raw rehash | 862 / `d71f4a51…51fe` |
| V15 Raw rehash | 862 / `c8fe8b7c…2d9c` |
| V15 same-session rerun | still FORBIDDEN |

### G-DESIGN — Design approval

| Gate | Pass |
|---|---|
| `V16_PREIMPLEMENTATION_FIX_DESIGN_V1` Human Review | APPROVED |
| `DESIGN_APPROVED_FOR_IMPLEMENTATION` | true |
| Implementation commit exists on main (later) | recorded |

### G-COMBAT — Termination contract

| Gate | Pass |
|---|---|
| C1–C9 unit/fixture | PASS |
| CN1–CN7 intermediate-gap negatives | PASS |
| Corbitt positive path = full chain kill→defeat→SO→ENDING→validation→ENDED | proven (C2/C3) |
| Corbitt END without validated kill | impossible in tests |
| no-target / policy-none / empty-candidates end | 0 occurrences in tests |

### G-NDM — Production wiring

| Gate | Pass |
|---|---|
| W1–W10 | PASS |
| `NATURAL_DECISION_REQUIRED` default for V16 profile | true |
| Init failure → abort (no legacy Full-Long) | proven |
| Dual S-authority | 0 |
| Selected-action causal bind (`reasoning_id` + `decision_source=natural_decision_v1`) | proven |
| `LEGACY_DECISION_COMMIT_COUNT` | **= 0** (smoke / attestation) |

### G-TELEMETRY

| Gate | Pass |
|---|---|
| T1–T6 | PASS |
| Four rates numeric when runtime active | true |

### G-SMOKE — Night Guard production path (**mandatory**)

| Gate | Pass |
|---|---|
| Session ID matches `CORBITT_NDM_WIRING_SMOKE_V16PRE_*` | true |
| Formal V16 ID unused | true |
| `NATURAL_DECISION_RUNTIME_ACTIVE` | true |
| PL reasoning events | > 0 |
| KP progress assessments | > 0 |
| `S_LEVEL_AUTHORITY` | `natural_decision_v1` |
| `LEGACY_STALL_DETECTOR_PRIMARY` | false |
| `LEGACY_DECISION_COMMIT_COUNT` | **0** |
| ≥1 commit causally bound to NDM | true |
| Smoke report artifact present | true |

### G-LAUNCH — Formal V16 launch readiness

| Gate | Pass |
|---|---|
| All above PASS | true |
| Fresh identity plan for `CORBITT_LONGRUN_ITERATION3_V16_HOME_001` | documented |
| `V16_READY` | true only if all G-* PASS |

---

## 2. Aggregate

```text
V16_PRECHECK = PASS
  iff G-HIST ∧ G-DESIGN ∧ G-COMBAT ∧ G-NDM ∧ G-TELEMETRY ∧ G-SMOKE

V16_READY = V16_PRECHECK
```

If any gate FAIL → `V16_READY = false` → formal Full-Long **FORBIDDEN**.

---

## 3. Explicit non-gates (follow-on)

These may still be open without blocking PRIMARY precheck, but should be tracked:

- exterior↔ground loop suppression polish  
- CONTEXT_BLOAT pruning  
- dead-PC continuation beyond Corbitt end ban (partially closed by C1)

If smoke or unit shows they re-break A/B contracts, promote to blocking.
