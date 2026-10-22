# V16_PREIMPLEMENTATION_FIX_DESIGN_V1 — Design QA

**Parent:** `V16_PREIMPLEMENTATION_FIX_DESIGN_V1`  
**Result:** `V16_PREIMPLEMENTATION_FIX_DESIGN_V1_QA = PASS` (design completeness)  
**DESIGN_APPROVED_FOR_IMPLEMENTATION:** false — **Human Review required**  
**IMPLEMENTATION_STARTED:** false  
**CODE_CHANGED:** 0  
**DESIGN_DOCS_COMMITTED:** false  

---

## 1. Premise check

| Item | Status |
|---|---|
| PRIMARY_A = COMBAT_TERMINATION_GUARD_GAP | Stated |
| PRIMARY_B = NATURAL_DECISION_PRODUCTION_WIRING_GAP | Stated |
| V15 NDM Quality = invalid eval (main unwired) | Stated |
| V15 Raw immutable / no rerun | Stated |

---

## 2. NDM path QA

| Requirement | Covered? | Doc |
|---|---|---|
| Night Guard → runtime → natural_decision_v1 → PL → group → Progression safety → KP → S0–S4 → Executor | Yes | `V16_NDM_PRODUCTION_WIRING_DESIGN.md` |
| NDM required on V16 | Yes | master + wiring |
| Init failure fail-closed (no legacy Full-Long) | Yes | wiring §3 |
| SAFE_LEGACY only for single reasoning failure | Yes | wiring §4 |
| Runtime evidence five fields | Yes | master §4 / wiring §5 |
| Dual S-authority forbidden | Yes | wiring §5 |
| StallDetector not primary | Yes | wiring §5 |
| selected_action causal bind (`reasoning_id` / `decision_source`) | Yes (amendment) | wiring §9 |
| `LEGACY_DECISION_COMMIT_COUNT=0` precheck | Yes (amendment) | precheck G-NDM / G-SMOKE |

---

## 3. Combat QA

| Requirement | Covered? | Doc |
|---|---|---|
| Explicit termination reason/evidence | Yes | combat §2 |
| no-target / Boss none / empty candidates non-ending | Yes | combat §2.2 |
| Corbitt end = validated kill only | Yes | combat §3 |
| Full chain kill→defeat→SO→ENDING→validation→ENDED | Yes (amendment) | combat §3.1 |
| Intermediate-gap negatives CN1–CN7 | Yes (amendment) | test plan §2.1 |
| No kill + corbitt_defeated=false → forbid ENDING/ENDED | Yes | combat §3.2 |
| TPK ≠ false progression resume | Yes | combat §3.3 |

---

## 4. Telemetry QA

| Requirement | Covered? | Doc |
|---|---|---|
| Four V15-null rates measurable on Full-Long | Yes | telemetry §3 |
| Raw emit types | Yes | telemetry §2 |
| Null-after-active = fail | Yes | telemetry §3.1 |

---

## 5. Smoke / precheck QA

| Requirement | Covered? | Doc |
|---|---|---|
| Night Guard production-path smoke | Yes | test plan §5 |
| Formal V16 session ID forbidden for smoke | Yes | test plan §5.1 |
| Precheck gates include smoke | Yes | `V16_PRECHECK_GATES.md` G-SMOKE |
| `LEGACY_DECISION_COMMIT_COUNT=0` in G-SMOKE / G-NDM | Yes (amendment) | precheck |
| V16_READY false until precheck | Yes | precheck §2 |

---

## 6. Prohibition compliance (this task)

| Prohibition | Observed |
|---|---|
| No code changes | Yes (docs only) |
| No V16 run | Yes |
| No V15 mutation | Yes |
| No commit | Yes |

---

## 7. Open Human Review questions

1. Confirm TPK holding policy preference: `COMBAT_PARTY_DOWN` pause vs `COMBAT_ABORT_EVALUATION` (both forbid clear).  
2. Confirm `NDM_FALLBACK_STREAK_LIMIT` default **3**.  
3. Confirm smoke cycle budget **5–8**.  
4. Confirm companion `ndm_evidence.jsonl` optional vs UEL-only.

---

## 8. Final QA block

```text
V16_PREIMPLEMENTATION_FIX_DESIGN_V1 = READY_FOR_HUMAN_REVIEW
V16_PREIMPLEMENTATION_FIX_DESIGN_V1_QA = PASS
DESIGN_APPROVED_FOR_IMPLEMENTATION = false
IMPLEMENTATION_STARTED = false
CODE_CHANGED = 0
V16_RUN = false
V15_RAW_CHANGED = 0
DESIGN_DOCS_COMMITTED = false
PRIMARY_A = COMBAT_TERMINATION_GUARD_GAP
PRIMARY_B = NATURAL_DECISION_PRODUCTION_WIRING_GAP
NDM_REQUIRED_ON_V16 = true
INIT_FAIL_OPEN_LEGACY = false
DUAL_S_AUTHORITY = FORBIDDEN
CORBITT_END_WITHOUT_VALIDATED_KILL = FORBIDDEN
SMOKE_USES_FORMAL_V16_ID = false
SELECTED_ACTION_CAUSAL_BIND = DEFINED
LEGACY_DECISION_COMMIT_COUNT_PRECHECK = 0
CORBITT_TERMINATION_FULL_CHAIN = DEFINED
CORBITT_CHAIN_GAP_NEGATIVES = CN1-CN7
V16_READY = false
RECOMMENDED_NEXT_STEP = HUMAN_REVIEW_THEN_IMPLEMENTATION
```
