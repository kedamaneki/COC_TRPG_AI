# V16 NDM Fallback Root Cause Audit V1

**Session:** `CORBITT_LONGRUN_ITERATION3_V16_HOME_001`  
**Audit id:** `V16_NDM_FALLBACK_ROOT_CAUSE_AUDIT_V1`  
**Result:** `PASS`  
**CODE_CHANGED:** `0`  
**AUDIT_DOCS_COMMITTED:** `false` (Human Review前)  
**V17_READY:** `false`

## Immutable inputs

| Check | Result |
|---|---|
| Git branch | `main` @ includes `48a47a0` (V16 negative freeze) |
| V16 Raw rehash | **PASS** 862 / `ae254b70d595ca64dc24c24e0b23c481a56b0f88de95323da24ac8b338938b3a` |
| V13/V14/V15 rehash | **PASS** (unchanged) |
| Formal Normalizer | `NOT_RUN_DUE_TO_PREAUDIT_BLOCK` |
| Formal Auditor | `NOT_RUN_DUE_TO_PREAUDIT_BLOCK` |

## Symptom (from V16 acceptance)

| Metric | Value |
|---|---|
| NATURAL_DECISION_RUNTIME_ACTIVE | true |
| PL_REASONING_EVENT_COUNT | 192 |
| SELECTED_ACTION_WITH_NDM_REASONING_COUNT | 3 |
| LEGACY_DECISION_COMMIT_COUNT | 194 |
| SAFE_LEGACY_PROGRESSION_COUNT | 194 (equal; telemetry conflates SAFE_LEGACY into LEGACY counter) |
| SAFE_FALLBACK_RATE | ≈0.496 |
| NDM_DECISION_CAUSAL_COVERAGE | 0.0 |

## Central answer

NDM **did** start and **did** run PL candidate selection / evidence build for nearly every decide call. Almost every execution still fell to `SAFE_LEGACY_PROGRESSION` because:

1. `StallDetectorV2` stores `director_v2.stall.recent_actions` as **lists** `[action, target]`.
2. NDM `assess_party_progress` and `SafeLegacyProgression.filter_candidates` assume **dicts** and call `.get("action")` / `.get("target")`.
3. After ~3 early successes (while `recent_actions` was still empty/short), every later decide hits `AttributeError: 'list' object has no attribute 'get'`.
4. Broad `except Exception` converts that schema bug into SAFE_LEGACY / FAIL_CLOSED instead of fail-closed hard stop.
5. After `SafeLegacyProgression` streak exceeds `MAX_FALLBACK_STREAK=5`, pipeline returns `mode=FAIL_CLOSED` with PL evidence but **no** `selected_action`. Runtime does **not** special-case `FAIL_CLOSED`, emits `PL_REASONING_COMPLETED`, then fails again on KP assess → `_fallback_select` → another SAFE_LEGACY commit.

So Reasoning count stays high (192) while NDM-bound commits stay at 3.

## Track summary

| Track | Finding |
|---|---|
| A Fallback classification | **194/194 classified**; 100% same raw exception; 189/194 = FAIL_CLOSED mishandle subtype |
| B Commit failure stage | 3 SUCCESS; 5 DROP_AFTER_DECISION; 189 DROP_AFTER_REASONING |
| C NDM vs Legacy diff | Legacy actions executed outside NDM bind; 189 COMPLETED events have `selected_action=null` (intent fields lost) |
| D Progress telemetry =0 | **Instrumentation + NDM-not-controlling**; UEL still has 28 turns with `progress_delta>0` |

## Primary root cause

`PRIMARY_ROOT_CAUSE = RECENT_ACTIONS_SCHEMA_MISMATCH (list vs dict) between StallDetectorV2 and NDM KP/fallback consumers`

## Secondary root causes

1. `FAIL_CLOSED` not handled in `NaturalDecisionRuntime.decide` → false `PL_REASONING_COMPLETED` then SAFE_LEGACY  
2. Pipeline SAFE_LEGACY path reuses list-shaped `recent_actions` and double-faults on `.get`  
3. `LEGACY_DECISION_COMMIT_COUNT` increments on SAFE_LEGACY (telemetry semantics blur)  
4. `enrich_pc_action_with_ndm` never passes `progress_events` into NDM KP assess  
5. Extreme SAFE_LEGACY availability failure → NDM ceases to steer Full-Long progression

## Responsibility split (not “NDM failed” alone)

| Bucket | Applies? |
|---|---|
| NDM_REASONING_BAD | **partial** — early PL reasons exist; not the dominant breaker |
| NDM_BINDING_BAD | **yes** — end-to-end bind collapses after schema exception |
| EXECUTOR_CONTRACT_BAD | **no** — unbound guard not the mass path |
| FALLBACK_POLICY_TOO_EAGER | **yes** — AttributeError → SAFE_LEGACY instead of hard fail |
| TELEMETRY_BAD | **yes** — meaningful/self-recovery zeros; LEGACY counter conflation |
| LEGACY_PROGRESS_BAD | **partial** — house entry happened; basement/final battle did not |

## V16 failure interpretation

V16 is **not** primarily “PL model cannot reason.” It is a **production wiring/schema + exception-policy** failure: NDM reasoning runs, then a StallDetector/NDM contract mismatch forces SAFE_LEGACY dominance, causal coverage collapses to 0, and Full-Long completion fails before Corbitt final battle.

## V17

- `V17_FIX_SCOPE = MULTI_COMPONENT_FIX` (schema normalize + FAIL_CLOSED handling + fallback exception hygiene + telemetry semantics; optional progress_events wiring)
- `V17_READY = false` (needs fix design first)
- `RECOMMENDED_NEXT_STEP = V17_MULTI_COMPONENT_FIX_DESIGN_REQUIRED`

## Companion docs

- `docs/V16_NDM_FALLBACK_CLASSIFICATION.md` / `.json`
- `docs/V16_NDM_DECISION_PIPELINE_DROP_ANALYSIS.md`
- `docs/V16_NDM_VS_LEGACY_ACTION_DIFF.md`
- `docs/V16_NDM_PROGRESS_TELEMETRY_AUDIT.md`
- `docs/V16_NDM_FALLBACK_ROOT_CAUSE_TREE.md`
