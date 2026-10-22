# V16 Natural Decision Production Wiring Design

**Parent:** `V16_PREIMPLEMENTATION_FIX_DESIGN_V1`  
**Closes:** `PRIMARY_B = NATURAL_DECISION_PRODUCTION_WIRING_GAP`  
**CODE_CHANGED:** 0 (design only)

---

## 1. Problem restatement

V15 Full-Long ran without production NDM:

- `main` did not call `run_natural_decision_cycle` / LeadTracker / HypothesisTracker  
- `director_v2.natural_decision_v1` was never set  
- StallDetectorV2 was the live S-level authority  
- Therefore **V15 NATURAL_DECISION_QUALITY is not a valid evaluation** of the NDM model

---

## 2. Required production path

Formal ordered path for every V16 Full-Long autonomous turn (non-combat investigation / exploration; combat has separate executor but NDM may still assess post-combat):

```text
[1] Night Guard
      launch_receipt, ACL, session identity, cycle budget
        ↓
[2] Runtime bootstrap
      GameStateManager, ScenarioManager, CharacterManager, LLM clients
        ↓
[3] NATURAL_DECISION_REQUIRED initialization
      construct NaturalDecisionPipeline + KnowledgeBoundary
      set session flags:
        natural_decision_v1 = true
        NATURAL_DECISION_RUNTIME_ACTIVE = true
        s_level_authority = "natural_decision_v1"
        legacy_stall_detector_primary = false
      ON FAILURE → abort session (no legacy Full-Long)
        ↓
[4] PL reasoning (per active capable PC)
      known facts → leads/hypotheses → scored candidates → selection_reason
      emit PL_REASONING_COMPLETED (or equivalent)
        ↓
[5] Group decision (multi-PC)
      proposals / dissent / consensus → group_decision_id
      emit GROUP_DECISION_COMPLETED when applicable
        ↓
[6] Progression safety
      ActionAvailability / exhausted targets / location legality
      may rewrite illegal picks; must not invent hidden solutions
        ↓
[7] KP progress assessment
      meaningful_progress / merely_repeating / exploration flags
      emit KP_PROGRESS_ASSESSMENT
        ↓
[8] S0–S4 intervention (authority = natural_decision_v1 ONLY)
      KPInterventionPolicy (+ recovery_grace_window)
      StallDetectorV2 may supply signals as INPUT FEATURES only
        ↓
[9] Executor
      apply legal action; mutate world; append adjudication / UEL
```

---

## 3. Init contract (fail-closed)

| Condition | Behavior |
|---|---|
| `NATURAL_DECISION_REQUIRED=true` (V16 default) | Must successfully init pipeline before cycle 0 advance |
| Missing reasoning modules / import error / boundary misconfig | **ABORT** with `NDM_INIT_FAILURE` |
| LLM unreachable at init | **ABORT** (same class) — do not start legacy path |
| Partial init (flag true but pipeline null) | **ABORT** |

```text
FAIL_OPEN_TO_LEGACY_FULL_LONG_ON_NDM_INIT_FAILURE = false
```

---

## 4. SAFE_LEGACY_PROGRESSION (narrow)

| Allowed | Forbidden |
|---|---|
| Single turn/cycle where PL reasoning raises model/parse/timeout after successful init | Using SAFE_LEGACY as default planner |
| Emit `REASONING_MODEL_FALLBACK` + `SAFE_LEGACY_PROGRESSION` evidence | Clearing `NATURAL_DECISION_RUNTIME_ACTIVE` |
| Resume NDM next cycle | Escalating StallDetector to primary S-authority |
| | Init-time fallback |
| | N consecutive fallbacks ≥ `NDM_FALLBACK_STREAK_LIMIT` (design default **3**) without recovery → pause/fail-closed |

Guards retained from V1 amendment: no knowledge leak, no direct solution S4, frontier-set recovery only.

---

## 5. Single S-level authority

```text
S_LEVEL_AUTHORITY = natural_decision_v1
DUAL_S_LEVEL_AUTHORITY = FORBIDDEN
```

| Component | Role after V16 wiring |
|---|---|
| `KPInterventionPolicy` | **Sole** writer of `intervention_level` / S0–S4 decisions |
| `StallDetectorV2` | Optional **sensor**: streak, pingpong signals → assessment inputs |
| `apply_s4_candidate_override` | Only when `natural_decision_v1=true` and policy issued S4; must use NDM frontier set |
| Legacy pressure thresholds writing S4 independently | **Disabled** when NDM active |

Runtime evidence field:

```json
{
  "s_level_authority": "natural_decision_v1",
  "legacy_stall_detector_primary": false,
  "NATURAL_DECISION_RUNTIME_ACTIVE": true
}
```

If StallDetector writes `intervention_level` while NDM active → `DUAL_S_AUTHORITY_VIOLATION` (hard gate).

---

## 6. Night Guard integration points (design)

Night Guard must:

1. Pass / set `NATURAL_DECISION_REQUIRED=true` for V16 profile  
2. Refuse launch if preflight cannot confirm NDM module hash / import  
3. Record in `launch_receipt.json`:
   - `natural_decision_required`
   - `natural_decision_runtime_active` (post-init)
   - `s_level_authority`
4. Early-gate / smoke profiles use **non-V16** session IDs  
5. On `NDM_INIT_FAILURE`, stop with explicit reason — no silent continue

---

## 7. Session / checkpoint persistence

Persist under `session_state` (or dedicated `ndm_runtime`):

- `natural_decision_v1: true`  
- LeadTracker / HypothesisTracker serializations  
- `InterventionRuntimeState` (stall_score, recovery_grace_remaining, history)  
- `NATURAL_DECISION_RUNTIME_ACTIVE`  
- `s_level_authority`  
- `legacy_stall_detector_primary: false`  
- fallback streak counter  

Resume (future) must restore authority flags; must not “resume as legacy.”

---

## 8. Likely implementation touchpoints (later — not now)

| Area | Files (expected) |
|---|---|
| Turn loop | `core/src/main.py` |
| Pipeline | `core/src/reasoning/pipeline.py` |
| Director bridge | `core/src/ProgressDirectorV2.py`, `reasoning/progress_bridge.py` |
| Eval runner | `run_investigation_evaluation.py` / Night Guard wrappers |
| Tests | extend `test_natural_decision_*`; add production-path smoke harness |

---

## 9. Causal commit binding (selected action → NDM)

Runtime **must not** treat “NDM ran somewhere this cycle” as sufficient. The **committed / executed** action is causally bound to NDM:

| Field on committed action / executor input | Required |
|---|---|
| `reasoning_id` | Non-empty; equals `PL_REASONING_COMPLETED.reasoning_id` (or group decision child id that references parent reasoning) |
| `decision_source` | `"natural_decision_v1"` for normal NDM commits |
| `selection_reason` | Non-empty when `decision_source=natural_decision_v1` |

```text
SELECTED_ACTION_CAUSAL_BIND =
  executor.selected_action
    ← decision_source == "natural_decision_v1"
    ← reasoning_id ∈ emitted PL/group reasoning events this cycle
```

Exceptions:

| Case | `decision_source` | Counts toward |
|---|---|---|
| Single-cycle SAFE_LEGACY_PROGRESSION | `"safe_legacy_progression"` | `LEGACY_DECISION_COMMIT_COUNT` / fallback evidence — **not** NDM causal bind |
| Human forced | `"human_forced"` | out of NDM rates; not legacy auto |

**Hard gate:** If `NATURAL_DECISION_RUNTIME_ACTIVE=true` and an autonomous commit has missing `reasoning_id` or `decision_source` not in `{natural_decision_v1, safe_legacy_progression, human_*}` → `UNBOUND_DECISION_COMMIT` fail-closed (do not execute / do not count as NDM success).

Smoke / precheck must verify at least one autonomous commit with `decision_source=natural_decision_v1` and matching `reasoning_id`.

---

## 10. LEGACY_DECISION_COMMIT_COUNT

```text
LEGACY_DECISION_COMMIT_COUNT =
  count of executor commits this session where decision_source ∈
    {safe_legacy_progression, legacy_stall_detector, legacy_director_primary, unbound_legacy}
```

| Profile | Gate |
|---|---|
| Night Guard NDM wiring smoke | `LEGACY_DECISION_COMMIT_COUNT = 0` preferred; if W3 single fallback exercised in unit only, smoke must still be **0** |
| Formal V16 Full-Long precheck sample / early gate | `LEGACY_DECISION_COMMIT_COUNT = 0` for the smoke attestation run |
| Full-Long long run | Prefer 0; each SAFE_LEGACY commit must be evidenced; streak policy still applies — **precheck attestation run requires 0** |

`LEGACY_DECISION_COMMIT_COUNT=0` is a **Precheck Gate** (see `V16_PRECHECK_GATES.md`).

---

## 11. Acceptance for this WP (design-level)

| Gate | Requirement |
|---|---|
| Path complete | All 9 stages named and ordered |
| Init fail-closed | Explicit |
| Dual authority ban | Explicit |
| Runtime evidence | Five fields specified |
| Causal bind | `reasoning_id` + `decision_source=natural_decision_v1` on commits |
| Legacy commit count | Precheck requires 0 on smoke |
| Smoke ID policy | Formal V16 ID forbidden |
