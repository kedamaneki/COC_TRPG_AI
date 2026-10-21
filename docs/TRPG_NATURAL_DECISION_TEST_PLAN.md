# TRPG Natural Decision — Deterministic Test / Fixture Plan V1

**Parent:** `TRPG_NATURAL_DECISION_MODEL_V1`  
**Status:** COMPLETE (design). Fixtures are specifications; not implemented in this phase.

## 1. Principles

- Fixtures are **deterministic scenarios** with expected **classes of outcomes**, not fixed prose  
- Each fixture asserts knowledge-boundary and anti-railroad gates  
- Historical Raw is never used as a mutable sandbox

## 2. Reasoning fixtures (R1–R10)

| ID | Setup | Expected |
|---|---|---|
| **R1** | Attempt failed; method may still work | PL considers **alternate method** (not instant impossible) |
| **R2** | Attempt failed; leave is reasonable | Justified leave + `leave_reason`; lead retained `unresolved_high_value` |
| **R3** | High-value lead open while elsewhere | Lead remains in state; abandon without reason fails metric gate |
| **R4** | New meaningful progress elsewhere | No KP escalation (S0) |
| **R5** | Meaningless repetition | S1 self-review triggers before content hints |
| **R6** | Party “forgets” known unbroken obstacle | S2 reminder cites **known** fact only |
| **R7** | Continued stall after reminder | S3 soft nudge to unresolved lead; no answer |
| **R8** | Complete stall | S4 frontier-set recovery (location/set), **not** solution action |
| **R9** | Multiple high-value frontiers | S4/recovery preserves choice set (≥2 options) |
| **R10** | PL cites unobserved fact | `REASONING_KNOWLEDGE_LEAK` → BLOCK |

### Basement plank vignette (required design fixture)

State:

```text
basement_planks_examined = true
basement_planks_broken = false
break attempt = ATTEMPT_FAILED / UNKNOWN_REASON
```

Natural PL candidate set must be able to include (not all required in one step):

- push / force alternate  
- other skill  
- other PC  
- seek tool  
- temporary leave with lead retained  

## 3. Group fixtures (G1–G4)

| ID | Expected |
|---|---|
| **G1** | Two divergent proposals recorded with reasons |
| **G2** | One PL disagrees on danger; action not auto-forced |
| **G3** | Consensus outcome + executor |
| **G4** | Role division plan recorded |

## 4. KP fixtures (K1–K5)

| ID | Expected |
|---|---|
| **K1** | Exploring with new hypotheses → intervention none |
| **K2** | Pure repetition → reminder (S2) |
| **K3** | Misunderstanding known facts → reframe |
| **K4** | True stuck → recovery (S4 frontier set) |
| **K5** | Direct solution hint (“push the planks to proceed”) → **FAIL** `UNGROUNDED`/`ANSWER` policy |

## 5. Amendment fixtures (A / H / F)

### S-level de-escalation

| ID | Setup | Expected |
|---|---|---|
| **A1** | S3 active → meaningful progress occurs | S-level → **S0**; stall reduced/reset |
| **A2** | S4 recovery returns party to frontier set | S-level → **S0**; no persistent S4 pressure |
| **A3** | New rational hypothesis / INFORMATION_PROGRESS, no state mutation yet | Escalation **suspended** (no immediate S2/S3 raise) |

### Hidden-solution frontier ban

| ID | Setup | Expected |
|---|---|---|
| **H1** | Frontier `value_reasons` only from hidden scenario truth | Rejected; not in recovery set (`HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK`) |
| **H2** | Known unresolved lead + current goal relevance + available actions | Eligible high-value frontier |

### Safe fallback

| ID | Setup | Expected |
|---|---|---|
| **F1** | Reasoning exception | `SAFE_LEGACY_PROGRESSION`; guards preserved |
| **F2** | Fallback + attempt-exhausted action present | Exhausted action **excluded** |
| **F3** | Fallback candidate requires hidden truth | **Blocked** |
| **F4** | Repeated reasoning failures | `fallback_streak` grows → warning / fail-safe (no infinite silent fallback) |

## 6. Design QA binding

Fixtures must keep:

- `PL_HIDDEN_KNOWLEDGE_PATH = 0`  
- `KP_UNGROUNDED_HINT_PATH = 0`  
- `DIRECT_SOLUTION_S4_PATH = 0`  
- `UNEXPLAINED_ACTION_PATH = 0`  
- `S_LEVEL_DEESCALATION_UNDEFINED = 0`  
- `POST_S4_PRESSURE_PERSISTENCE_PATH = 0`  
- `HIGH_VALUE_FRONTIER_HIDDEN_SOLUTION_LEAK = 0`  
- `HIDDEN_CORRECT_PATH_SIGNAL = 0`  
- `UNSAFE_LEGACY_FALLBACK_PATH = 0`  
- `FALLBACK_GUARD_UNDEFINED = 0`  

## 7. Implementation note (future)

Map each fixture to unit/integration tests under a future `tests/reasoning/` package — **not started** in this phase.
