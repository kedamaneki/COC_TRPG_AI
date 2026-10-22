# V16_PREIMPLEMENTATION_FIX_DESIGN_V1

**Design status:** READY_FOR_HUMAN_REVIEW  
**DESIGN_APPROVED_FOR_IMPLEMENTATION:** false (pending Human Review)  
**IMPLEMENTATION_STARTED:** false  
**CODE_CHANGED:** 0  
**V16_RUN:** FORBIDDEN in this task  
**Commit:** FORBIDDEN (`DESIGN_DOCS_COMMITTED = false`)

**Audit premise (formal):**

| ID | Root cause |
|---|---|
| PRIMARY_A | `COMBAT_TERMINATION_GUARD_GAP` |
| PRIMARY_B | `NATURAL_DECISION_PRODUCTION_WIRING_GAP` |

**V15 disposition:** `CORBITT_LONGRUN_ITERATION3_V15_HOME_001` = immutable negative reference.  
**V15 Natural Decision Quality:** **not a valid evaluation** — production `main` did not wire NDM (`natural_decision_v1` unset; StallDetectorV2 was primary).

**Formal V16 session (later, not now):** `CORBITT_LONGRUN_ITERATION3_V16_HOME_001`  
**Smoke sessions must not use this ID.**

---

## 0. Purpose

Design (docs only) the pre-implementation fix set required before any V16 Full-Long:

1. Wire Natural Decision as the **required** production decision authority  
2. Close Corbitt combat termination without validated kill  
3. Make V15-null NDM metrics measurable on Full-Long Raw  
4. Prove wiring via Night Guard production-path smoke (not fixtures alone)

Detail packs:

- [V16_NDM_PRODUCTION_WIRING_DESIGN.md](./V16_NDM_PRODUCTION_WIRING_DESIGN.md)
- [V16_COMBAT_TERMINATION_CONTRACT_DESIGN.md](./V16_COMBAT_TERMINATION_CONTRACT_DESIGN.md)
- [V16_NDM_TELEMETRY_DESIGN.md](./V16_NDM_TELEMETRY_DESIGN.md)
- [V16_PREIMPLEMENTATION_TEST_PLAN.md](./V16_PREIMPLEMENTATION_TEST_PLAN.md)
- [V16_PRECHECK_GATES.md](./V16_PRECHECK_GATES.md)
- [V16_PREIMPLEMENTATION_FIX_DESIGN_V1_QA.md](./V16_PREIMPLEMENTATION_FIX_DESIGN_V1_QA.md)
- [V16_PREIMPLEMENTATION_FIX_DESIGN_V1.json](./V16_PREIMPLEMENTATION_FIX_DESIGN_V1.json)

---

## 1. Absolute prohibitions (this task)

- Core / Scenario / NDM / Combat / Telemetry **code** changes  
- V15 rerun / resume / Raw edit  
- Formal V16 Full-Long execution  
- Smoke using formal V16 session ID  
- fail-open to legacy Full-Long when NDM init fails  
- Dual S-level authority (NDM + StallDetector both primary)  
- Commit / accepted tag / Known-Good promotion  

---

## 2. Executive decisions

| Topic | Decision |
|---|---|
| NDM on V16 Full-Long | **REQUIRED** (`NATURAL_DECISION_REQUIRED=true`) |
| NDM init failure | **Fail-closed** — do not start / do not continue as legacy Full-Long |
| Single reasoning-cycle failure | Allow **one** `SAFE_LEGACY_PROGRESSION` step with evidence; not permanent demotion |
| S-level authority | **Only** `natural_decision_v1` (`KPInterventionPolicy`) |
| StallDetectorV2 | Demoted to **sensor / metric input only**; `legacy_stall_detector_primary=false` |
| Corbitt final combat end | **VALIDATED_KILL only** (escape/TPK policies explicitly out of band for boss clear path) |
| Non-kill end while `corbitt_defeated=false` | **Fail-closed:** forbid `COMBAT_ENDING` / `COMBAT_ENDED` |
| no-target / BossPolicy none / empty candidates | **Must not** terminate combat |
| Telemetry | Four formerly-null rates **must** be computable from Raw on Full-Long |
| Pre-V16 proof | Night Guard **production-path** short smoke + fixtures |

---

## 3. Work package map

| WP | Title | Closes |
|---|---|---|
| WP-N1 | Production path wiring + required init | PRIMARY_B |
| WP-N2 | Single S-level authority + StallDetector demotion | PRIMARY_B / S4 dual-authority |
| WP-N3 | Raw NDM telemetry + Full-Long aggregator | TELEMETRY_INCOMPLETE |
| WP-C1 | Explicit combat termination contract | PRIMARY_A |
| WP-C2 | Corbitt final-battle end = validated kill only | PRIMARY_A |
| WP-S1 | Night Guard NDM wiring smoke (non-V16 ID) | Precheck |

Secondary cascade items (location loop / dead-PC continuation / CONTEXT_BLOAT) are **in scope for design notes** but **not** blocking PRIMARY fix acceptance unless they reopen A/B. Recommended follow-on designs after V16 smoke PASS.

---

## 4. Natural Decision production path (summary)

```text
Night Guard launch
  → runtime bootstrap (session, scenario, LLM)
  → NATURAL_DECISION_REQUIRED init
       fail → ABORT (no legacy Full-Long)
  → set director_v2.natural_decision_v1 = true
  → set NATURAL_DECISION_RUNTIME_ACTIVE = true
  → per turn:
        PL reasoning (per active PC)
          → Group decision (when multi-PC)
          → Progression safety filter (legality / availability / exhausted)
          → KP progress assessment
          → S0–S4 (natural_decision_v1 authority ONLY)
          → Executor (world mutation)
          → emit Raw NDM evidence events
```

**SAFE_LEGACY_PROGRESSION:** allowed only for a **single reasoning-cycle exception** (model/parse/timeout), with `REASONING_MODEL_FALLBACK` evidence.  
Repeated or init-time fallback → fail-closed.

Runtime evidence contract (must hold for V16 / smoke PASS):

| Evidence | Required |
|---|---|
| `NATURAL_DECISION_RUNTIME_ACTIVE` | `true` |
| PL reasoning events | count > 0 |
| KP progress assessment events | count > 0 |
| `s_level_authority` | `natural_decision_v1` |
| `legacy_stall_detector_primary` | `false` |
| `LEGACY_DECISION_COMMIT_COUNT` | **0** (smoke / precheck attestation) |
| Selected-action causal bind | ≥1 commit with `decision_source=natural_decision_v1` **and** matching `reasoning_id` |

---

## 5. Combat termination contract (summary)

Every combat end must carry:

- `combat_end_reason` ∈ explicit enum (no bare `"resolved"` for Corbitt boss)
- `combat_end_evidence` (adjudication_id / kill route / escape proof / …)

**Forbidden sole causes of end:**

- no active target  
- BossCombatPolicy returns none / wait  
- empty combat action candidates  

**Corbitt final battle (`trigger_corbitt_boss_battle` active, enemy `walter_corbitt`):**

```text
ALLOW COMBAT_ENDED only after full chain:
  VALIDATED_KILL
    → corbitt_defeated
    → DERIVED SPECIAL_OBJECTIVE_COMPLETED
    → COMBAT_ENDING
    → TERMINATION_VALIDATION PASS
    → COMBAT_ENDED

ELSE
  FORBID COMBAT_ENDING/ENDED (fail-closed) when any link missing
  KEEP combat ACTIVE or enter explicit non-end holding state
```

Intermediate-gap negatives: **CN1–CN7** (test plan).  
TPK / party incapacitation during Corbitt boss must **not** emit lifecycle END as scenario progression success. Design holding policy: `COMBAT_PARTY_DOWN` pause / evaluation stop class — **not** `COMBAT_ENDED` with `normal progression may resume` while Corbitt undefeated.

---

## 6. Telemetry (summary)

Full-Long Raw must support non-null:

- `UNEXPLAINED_ACTION_RATE`
- `UNRESOLVED_LEAD_ABANDON_RATE`
- `SELF_RECOVERY_RATE`
- `MEANINGFUL_PROGRESS_RATE`

Emit per-cycle / per-decision evidence into unified event log (or dedicated `ndm_evidence.jsonl` referenced by Raw manifest). Aggregator reads Raw only (no backfill of historical V15).

---

## 7. Pre-V16 smoke (summary)

| Field | Value |
|---|---|
| Purpose | Prove NDM production wiring under Night Guard |
| Path | Night Guard → runtime → natural_decision_v1 → … → Executor |
| Session ID pattern | `CORBITT_NDM_WIRING_SMOKE_V16PRE_<nnn>` |
| Formal V16 ID | **forbidden** for smoke |
| Cycles | short (design default 5–8) |
| Pass bar | runtime evidence contract + PL/KP event counts + authority flags |

Fixtures alone are insufficient for `V16_PRECHECK`.

---

## 8. Out of scope for this design approval

- Implementing code  
- Running formal V16  
- Fixing location-loop / CONTEXT_BLOAT as primary (tracked as follow-on)  
- Changing V13/V14/V15 Raw  

---

## 9. Approval gates (Human Review)

Human Review must confirm:

1. PRIMARY_A/B premise accepted  
2. NDM required + init fail-closed accepted  
3. Dual S-authority ban accepted  
4. Corbitt validated-kill-only end accepted  
5. Telemetry non-null contract accepted  
6. Smoke ID policy accepted  

Then: `DESIGN_APPROVED_FOR_IMPLEMENTATION = true` (separate human mark).  
Implementation remains a **later** task.
