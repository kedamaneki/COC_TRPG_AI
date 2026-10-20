# CORBITT_FINAL_BATTLE_REMEDIATION_DESIGN_V1

**Design status:** PASS  
**DESIGN_APPROVED_FOR_IMPLEMENTATION:** true  
**IMPLEMENTATION_STARTED:** false  
**CODE_CHANGED:** 0  
**Amendment:** `CORBITT_FINAL_BATTLE_REMEDIATION_DESIGN_V1_AMENDMENT` (SOURCE-only kill authority; context-dependent provenance severity)

Approval means the design is accepted for a later implementation task. It does not mean implementation has started.

**Audit checkpoint (unchanged):** tag `corbitt-final-battle-audit-v1` → commit `8b9c2856af2ecc74a39b88c42c75c2d731ab5f40`  
**Prior audit:** `SCENARIO_FIDELITY=FAIL`, `PRIMARY_LOSS_STAGE=MULTI_STAGE`, `V13_FORMAL_ACCEPTANCE=PRESERVED`

---

## 1. Executive design decisions

| Topic | Decision |
|---|---|
| Kill routes | Exactly **Route A (HP after 2D6 armor)** and **Route B (magic dagger special kill)** |
| `break corbitt_body` | Pre-defeat: remap to attack **or** fail-closed; **never** SPECIAL auto-clear |
| `SPECIAL_OBJECTIVE_COMPLETED` | **Derived only** after validated kill |
| Corbitt AI | Fight Back, Dominate, Body Activation, Magic Dagger, Normal Attack with source priority |
| Combat NO_ROLL | Explicit classes only; irreversible implicit NO_ROLL **forbidden** |
| Provenance | Kill-route **authority** is `SOURCE` only. Transforms may express a SOURCE rule; they cannot define a new kill route |
| V13 / Video 002 | Untouched; fidelity badge withheld |
| Next run | `CORBITT_LONGRUN_ITERATION3_V14_HOME_001` (not executed) |

Detail packs:

- `docs/CORBITT_FINAL_BATTLE_WP_A_KILL_ROUTES.md`
- `docs/CORBITT_FINAL_BATTLE_WP_B_RESPONSE_AI.md`
- `docs/CORBITT_FINAL_BATTLE_WP_C_NO_ROLL_GUARD.md`
- `docs/CORBITT_FINAL_BATTLE_TEST_PLAN_V1.md`
- `docs/CORBITT_FINAL_BATTLE_V14_ACCEPTANCE_GATES.md`
- `docs/schemas/corbitt_scenario_provenance_draft_v1.json`

---

## 2. Scenario provenance design

### 2.1 Categories

| `fact_origin` | Meaning | Kill-route authority |
|---|---|---|
| `SOURCE` | Directly grounded in Chaosium text | **Yes.** Only this origin may set `may_define_kill_route=true` |
| `ADAPTATION_TRANSFORM` | Structural expression of an existing SOURCE rule | **No.** Must carry `source_ref.rule_id` when it represents a victory-related fact. Resolution traces to that SOURCE `rule_id`. The transform is not itself an authority |
| `ADAPTATION_INFERENCE` | Keeper flavor / inferred hint (e.g. altar purify text) | **No** |
| `SYSTEM_GENERATED` | Engine bookkeeping | **No** |
| `SYSTEM_GENERATED_BRIDGE` | Derived SO after a validated SOURCE kill | **No** |

`KILL_ROUTE_AUTHORITY = SOURCE_ONLY`  
`ADAPTATION_TRANSFORM_CAN_DEFINE_KILL_ROUTE = false`

### 2.2 Victory chain

```text
SOURCE kill rule (rule_id)
        ↓
optional ADAPTATION_TRANSFORM (source_ref.rule_id → same SOURCE rule)
        ↓
runtime validated kill route (ROUTE_A_HP0 | ROUTE_B_DAGGER)
        ↓
corbitt_defeated
        ↓
SPECIAL_OBJECTIVE_COMPLETED (derived)
```

Any flag/event that sets `corbitt_defeated` or emits body-destroy SO must resolve to a SOURCE kill rule (`ROUTE_A_HP0` or `ROUTE_B_DAGGER`). A transform without a reachable SOURCE `rule_id` is not a valid chain.

`ADAPTATION_INFERENCE` (altar / Y’golonac purify) may remain as optional investigation flavor with `may_define_kill_route=false`.

### 2.3 Provenance missing severity (context-dependent)

| Context | Examples | `SCENARIO_SOURCE_PROVENANCE_MISSING` |
|---|---|---|
| `FLAVOR` | clue, presentation hint, non-terminal investigation fact, non-critical state | **MAJOR**, not run-blocking |
| `VICTORY_CRITICAL` | validated kill route, `corbitt_defeated`, body destroyed, `SPECIAL_OBJECTIVE_COMPLETED`, combat ending/ended, HP terminal, irreversible object destruction, victory condition | **CRITICAL**, `blocking=true`, **fail-closed** |

Finding payload (design): `fact_id`, `fact_origin`, `source_ref`, `consumer_event`, `victory_critical`.

### 2.4 Fail-closed victory commit

If a victory-critical fact lacks SOURCE provenance (or its transform does not trace to a SOURCE `rule_id`):

- do not commit victory state
- do not commit `corbitt_defeated`
- do not emit `SPECIAL_OBJECTIVE_COMPLETED`
- do not publish combat completion / clear

`FAIL_CLOSED_VICTORY_COMMIT = DEFINED`

`CompletionAtomicity` must not publish `clear` / `completed` unless both a validated kill route and a valid SOURCE provenance chain are present.

### 2.5 Schema migration

**SCENARIO_SCHEMA_MIGRATION_REQUIRED = true** (additive):

- Optional `provenance` / `fact_origin` on event_triggers & clues  
- `validated_kill_route_id` on SO payloads  
- Combat resolution class fields on adjudication evidence  

Draft schema: `docs/schemas/corbitt_scenario_provenance_draft_v1.json`  
Status: **design draft; not wired into runtime.**

Contract in the draft:

- `may_define_kill_route=true` requires `fact_origin=SOURCE`
- `ADAPTATION_TRANSFORM` requires `source_ref.rule_id` and forbids `may_define_kill_route=true`

---

## 3. Combat model extension

**COMBAT_MODEL_EXTENSION_REQUIRED = true**

| Gap | Extension |
|---|---|
| Spell cast (Dominate) | SPELL combat action + POW opposed |
| Body activation timer | Combat-scoped state machine |
| Boss action policy | Beyond attack-only `queue_npc_combat_attack` |
| Dagger wrest → OWNED → special kill | ObjectLifecycle + Route B |
| Derived SO | CompletionAtomicity input change |

Existing **SUPPORTED** pieces to reuse: fight back/dodge, armor apply, HP, dagger floating combat NPC, DEX turn queue.

---

## 4. LIKELY_FILES_TO_CHANGE (repo-confirmed)

| Area | Paths |
|---|---|
| Scenario build | `core/src/build_corbitt_scenario.py`, `core/src/scenario_corbitt.json`, `core/scenario_sources/corbitt/e870e9f8fc96/loc_13_*.json`, `loc_14_*.json` |
| NPC data | `core/src/npcs.json` |
| Combat / resolve | `core/src/main.py`, `core/src/CombatProgression.py`, `core/src/GameStateManager.py`, `core/src/CoCRules.py` |
| Objects | `core/src/ObjectLifecycle.py` |
| Completion | `core/src/CompletionAtomicity.py` |
| Evidence | `core/src/AdjudicationEvidence.py` |
| New AI module | `core/src/BossCombatPolicy.py` (proposed) |
| Formal | Formal Auditor v2 + Normalizer (video package) |
| Tests | new `test_corbitt_*_v14.py`; rewrite `test_final_battle_remains_special_objective` |

**Not changed:** any V8–V13 Raw/control trees; Video 002 binaries.

---

## 5. Normalizer / Auditor

| Layer | Design |
|---|---|
| Normalizer | Forward new event types (`CORBITT_BODY_ACTIVATED`, `ARMOR_APPLIED`, dagger special kill); preserve traceability |
| Auditor | New findings per WP-C §8; fidelity gates FB-01..10 as optional scenario pack |
| Historical | Reproduction mode unchanged; Accepted artifacts immutable |

**NEW_AUDITOR_FINDINGS_REQUIRED:**

- `UNSUPPORTED_COMBAT_NO_ROLL`
- `COMBAT_KILL_WITHOUT_RESOLUTION`
- `SPECIAL_OBJECTIVE_WITHOUT_VALIDATED_KILL_ROUTE`
- `SCENARIO_SOURCE_PROVENANCE_MISSING`

---

## 6. Migration / historical

| Item | Decision |
|---|---|
| Scenario schema | Additive migration; rebuild `scenario_corbitt.json` after source edits |
| V8–V13 | read-only; no reinterpret-as-Accepted |
| V13 Formal | PRESERVED |
| Video 002 V1 | `HISTORICAL_RUNTIME_REPLAY` + `INVALID_AS_SCENARIO_FIDELITY_REFERENCE` |

---

## 7. Design QA

| Gate | Result |
|---|---|
| SOURCE_RULE_UNACCOUNTED | **0** (stats, armor, HP0, dagger kill, fight back, Dominate, activation, dagger float covered) |
| KILL_ROUTE_UNDEFINED | **0** |
| CORBITT_RESPONSE_UNDEFINED | **0** |
| IMPLICIT_NO_ROLL_PATH_REMAINING | **0** (designed closed; implementation pending) |
| KILL_ROUTE_AUTHORITY_CONFLICT | **0** |
| VICTORY_PROVENANCE_SEVERITY_UNDEFINED | **0** |
| FAIL_CLOSED_COMPLETION_RULE_UNDEFINED | **0** |
| HISTORICAL_MUTATION_PLANNED | **0** |
| IMPLEMENTATION_STARTED | **false** |
| CODE_CHANGED | **0** |
| DESIGN_QA | **PASS** |

---

## 8. Package completion

| Package | Status |
|---|---|
| WP_A_KILL_ROUTES | COMPLETE |
| WP_B_RESPONSE_AI | COMPLETE |
| WP_C_NO_ROLL_GUARD | COMPLETE |
| SCENARIO_PROVENANCE_DESIGN | COMPLETE |
| TEST_PLAN | COMPLETE |
| V14_ACCEPTANCE_GATE_DESIGN | COMPLETE |

---

## 9. Amendment status

Human Review amendments applied:

1. Kill-route authority is `SOURCE` only. `ADAPTATION_TRANSFORM` cannot define a kill route.
2. `SCENARIO_SOURCE_PROVENANCE_MISSING` is MAJOR for flavor and CRITICAL/BLOCKING plus fail-closed for victory-critical facts.

`DESIGN_APPROVED_FOR_IMPLEMENTATION = true`  
`IMPLEMENTATION_STARTED = false`  
`CODE_CHANGED = 0`

Next task (not started here): `CORBITT_FINAL_BATTLE_REMEDIATION_IMPLEMENTATION_V1`.  
QA record: `docs/CORBITT_FINAL_BATTLE_DESIGN_AMENDMENT_QA.md`.
