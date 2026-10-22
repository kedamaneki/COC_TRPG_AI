# V16 Pre-Implementation Test Plan

**Parent:** `V16_PREIMPLEMENTATION_FIX_DESIGN_V1`  
**Status:** DESIGN ONLY — fixtures/smoke specs; **not executed** in this task  
**CODE_CHANGED:** 0

---

## 1. Layers

| Layer | Purpose |
|---|---|
| L0 Unit / fixture | Deterministic NDM + combat guard tests |
| L1 Controlled compare | Short multi-seed NDM quality (existing R/G/K) |
| L2 **Night Guard production smoke** | Prove live wiring under NG path |
| L3 Formal V16 Full-Long | **Out of scope until precheck PASS** |

Fixtures alone **do not** satisfy V16 precheck. L2 is mandatory.

---

## 2. Combat fixtures (C-*)

| ID | Setup | Expected |
|---|---|---|
| **C1** | Corbitt boss; both PCs HP→0; Corbitt HP>0 | **No** `COMBAT_ENDING`/`ENDED`; no `corbitt_defeated`; no normal progression resume |
| **C2** | Corbitt boss; Route A full chain | kill → defeat → derived SO → ENDING → termination validation PASS → ENDED |
| **C3** | Corbitt boss; Route B full chain | Same with `ROUTE_B_DAGGER` |
| **C4** | Corbitt boss; attempt end with reason resolved / living≤1 | **Blocked** — `COMBAT_END_WITHOUT_VALIDATED_KILL` |
| **C5** | NPC turn; no capable PC target | Combat **ACTIVE**; no end |
| **C6** | BossPolicy returns wait/none | Combat **ACTIVE**; turn advances |
| **C7** | Empty combat candidates | No end; guide/retry path |
| **C8** | Non-Corbitt enemy wipe | `ENEMIES_INCAPACITATED` end allowed with evidence |
| **C9** | Emit ENDING without `combat_end_evidence` | Rejected / fail-closed |

### 2.1 Corbitt chain negative fixtures (CN-*) — intermediate gaps

Positive chain (C2/C3):  
`VALIDATED_KILL → corbitt_defeated → DERIVED SO → COMBAT_ENDING → TERMINATION_VALIDATION → COMBAT_ENDED`

Each CN fixture **breaks one link** and asserts **no COMBAT_ENDED** (and no scenario clear):

| ID | Gap injected | Expected |
|---|---|---|
| **CN1** | Kill evidence present; **skip** `corbitt_defeated` commit | No ENDING/ENDED; validation fail if ENDING forced |
| **CN2** | Kill + defeat; **skip** derived `SPECIAL_OBJECTIVE_COMPLETED` | No ENDED; SO missing blocks termination validation |
| **CN3** | Kill + defeat + SO; **skip** `COMBAT_ENDING` then attempt `COMBAT_ENDED` | ENDED forbidden without prior ENDING |
| **CN4** | ENDING emitted; **termination validation FAIL** (e.g. strip kill id) | No ENDED; `COMBAT_TERMINATION_VALIDATION_FAILED` |
| **CN5** | Defeat + SO without validated_kill_route_id | Blocked (pre-existing SO guard); no ENDED |
| **CN6** | ENDING with reason VALIDATED_KILL but evidence points to wrong adjudication | Validation FAIL; no ENDED |
| **CN7** | Full chain except validation step bypassed in code under test | Must still refuse ENDED (guard at ENDED emitter) |

`G-COMBAT` precheck requires **C1–C9 and CN1–CN7** PASS.

---

## 3. NDM wiring fixtures (W-*)

| ID | Setup | Expected |
|---|---|---|
| **W1** | `NATURAL_DECISION_REQUIRED=true`; pipeline import OK | Init sets runtime evidence flags |
| **W2** | Force init failure | Session **ABORT**; no legacy Full-Long cycles |
| **W3** | Single PL reasoning exception | One `SAFE_LEGACY_PROGRESSION`; `NATURAL_DECISION_RUNTIME_ACTIVE` stays true |
| **W4** | Fallback streak ≥ limit | Fail-closed / pause — not silent legacy |
| **W5** | StallDetector attempts to write S4 while NDM active | `DUAL_S_AUTHORITY_VIOLATION` or write ignored + hard gate |
| **W6** | Turn loop | Ordered: PL → group → progression safety → KP → S-level → executor |
| **W7** | Checkpoint resume mid-smoke | Authority flags restored; not demoted to legacy primary |
| **W8** | Autonomous commit | `decision_source=natural_decision_v1` AND `reasoning_id` matches emitted PL/group event |
| **W9** | Commit missing reasoning_id / wrong decision_source | `UNBOUND_DECISION_COMMIT` — not executed as NDM success |
| **W10** | Smoke / attestation run | `LEGACY_DECISION_COMMIT_COUNT = 0` |

---

## 4. Telemetry fixtures (T-*)

| ID | Expected |
|---|---|
| **T1** | After ≥1 PL reasoning + ≥1 KP assessment, four rates are **numeric** |
| **T2** | Unexplained path increments `UNEXPLAINED_ACTION_RATE` numerator |
| **T3** | Lead abandon without reason increments abandon rate |
| **T4** | Self-recovery marker increments `SELF_RECOVERY_RATE` |
| **T5** | Meaningful progress kinds drive `MEANINGFUL_PROGRESS_RATE` |
| **T6** | If runtime active but zero PL events → precheck FAIL (not silent null PASS) |

---

## 5. Night Guard production smoke (mandatory)

### 5.1 Identity

| Field | Value |
|---|---|
| Session ID pattern | `CORBITT_NDM_WIRING_SMOKE_V16PRE_<nnn>` |
| Example | `CORBITT_NDM_WIRING_SMOKE_V16PRE_001` |
| Formal V16 ID | **`CORBITT_LONGRUN_ITERATION3_V16_HOME_001` FORBIDDEN** |
| Profile | Night Guard production launch path (same entry as Full-Long, truncated budget) |
| Suggested cycles | **5–8** |
| Scenario | `scenario_corbitt.json` (or minimal Corbitt subset if NG profile allows) |

### 5.2 Smoke PASS bar

All must hold:

```text
NATURAL_DECISION_RUNTIME_ACTIVE = true
PL_REASONING_EVENT_COUNT > 0
KP_PROGRESS_ASSESSMENT_COUNT > 0
S_LEVEL_AUTHORITY = natural_decision_v1
LEGACY_STALL_DETECTOR_PRIMARY = false
LEGACY_DECISION_COMMIT_COUNT = 0
DUAL_S_AUTHORITY_VIOLATION = 0
NDM_INIT_FAILURE = 0
≥1 autonomous commit with decision_source=natural_decision_v1
  AND reasoning_id bound to PL/group reasoning event
SAFE_LEGACY commits in smoke = 0
Four telemetry rates numeric OR smoke too short documented exception —
  design preference: rates numeric even on short smoke
COMBAT: if boss not reached, combat gates deferred to unit C-*/CN-*; 
  if boss reached, full chain C2/C3 contracts apply
```

### 5.3 Smoke FAIL examples

- Started with formal V16 session ID  
- Init failed but cycles continued as legacy  
- StallDetector primary true  
- Zero PL reasoning events with “quality PASS”  
- Null four rates while runtime active  

### 5.4 Artifacts

```text
evaluation-v2/CORBITT_NDM_WIRING_SMOKE_V16PRE_001/
evaluation-control/CORBITT_NDM_WIRING_SMOKE_V16PRE_001/
  launch_receipt.json
  NDM_WIRING_SMOKE_REPORT.json
  NATURAL_DECISION_METRICS.json
```

---

## 6. Regression preservation

| Suite | Expectation |
|---|---|
| Existing `test_natural_decision_model_v1` | Still PASS |
| Corbitt kill route / completion atomicity tests | Still PASS; extended by C-* |
| V13/V14/V15 Raw | Unchanged (rehash gates) |

---

## 7. Execution order (future implementation task)

```text
L0 C-* W-* T-* 
  → L1 controlled compare 
  → L2 Night Guard smoke (non-V16 ID)
  → V16_PRECHECK gates
  → only then formal V16 Full-Long
```

**This design task stops before all execution.**
