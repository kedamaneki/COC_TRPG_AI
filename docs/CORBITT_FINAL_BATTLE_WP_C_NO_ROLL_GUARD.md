# WP-C — Combat NO_ROLL Fail-Closed Design

**Package:** WP-C  
**Status:** COMPLETE (design only)  
**Failure mode prevented:** skill missing → `roll_type=none` → NO_ROLL → success on irreversible combat outcomes  
**Code locus (current):** `core/src/main.py` fallthrough assigning `SuccessLevel.REGULAR_SUCCESS` + `roll_type="none"`

---

## 1. Goal

Combat state-changing actions must declare an explicit resolution class. Implicit NO_ROLL success is forbidden for irreversible outcomes.

---

## 2. Contract: `COMBAT_ACTION_REQUIRES_EXPLICIT_RESOLUTION`

While `combat_is_active` **or** action is classified as combat-linked irreversible:

Every executor path MUST set exactly one of:

| Class | Meaning | Evidence |
|---|---|---|
| `ROLL` | Dice / opposed roll performed | `resolution_mode=ROLL`, dice fields present |
| `EXPLICIT_NO_ROLL` | Intentionally no dice | See §4 mandatory fields |
| `DETERMINISTIC_RULE` | Pure rule derivation (e.g. HP already 0 → dust) | `rule_id`, `precondition_snapshot` |

If none declared → **`UNRESOLVED_COMBAT_ACTION`** → **fail-closed** (block mutation; emit reject event; no HP/flags/combat_end change).

---

## 3. Scope of “state-changing combat action”

Includes (non-exhaustive):

- attack / shoot / fight_back / dodge resolution  
- damage / armor / HP mutation  
- spell cast affecting combatants  
- object control transitions in combat (dagger)  
- body activation  
- combat_end / escape success  
- any action that would emit `SPECIAL_OBJECTIVE_COMPLETED`  
- SPECIAL category candidates from scenario

Out of scope (may keep existing NO_ROLL):

- empty-clue investigation outside combat  
- unconditional location move (already stripped of synthetic NO_ROLL evidence)  
- post-combat narrative flourishes with explicit waiver

---

## 4. `EXPLICIT_NO_ROLL` requirements

All required:

```json
{
  "resolution_mode": "NO_ROLL",
  "resolution_class": "EXPLICIT_NO_ROLL",
  "explicit_no_roll_reason": "human readable",
  "source_rule_id": "POST_DEFEAT_NARRATIVE|DAGGER_RECOVERY|...",
  "deterministic_precondition": {
    "corbitt_defeated": true
  },
  "fact_origin": "SOURCE|SYSTEM_GENERATED"
}
```

Missing any field → treat as `UNRESOLVED_COMBAT_ACTION`.

---

## 5. Irreversible action protection

Actions/effects matching any:

- kill / destroy body  
- combat end  
- special objective complete  
- HP terminal (≤0)  
- critical object mutation (dagger OWNED/DESTROYED affecting kill)

**`implicit NO_ROLL` forbidden.**

Allowed terminal paths:

1. `ROLL` chain that yields kill, then `DETERMINISTIC_RULE` derived SO  
2. `DETERMINISTIC_RULE` only when preconditions already proven by prior ROLL evidence in same combat (`validated_kill_route_id`)  
3. Never: fallthrough `roll_type=none` auto success

---

## 6. Special Objective protection

`SPECIAL_OBJECTIVE_COMPLETED` may fire only if:

```text
validated_kill_route_id ∈ {ROUTE_A_HP0, ROUTE_B_DAGGER}
AND cause_event_ids non-empty
AND fact_origin == SOURCE (for Corbitt body destroy)
AND NOT (action_id match alone)
```

Scenario event triggers that currently fire SO on `break`+`corbitt_body`+`success_level` must be removed or converted to remap stubs (WP-A).

---

## 7. Executor algorithm (design)

```text
on process_system_action / combat resolve:
  if combat_active or irreversible_candidate(action):
     resolution = declare_resolution(action, required_check, skill, scenario)
     if resolution.class is None:
        reject UNRESOLVED_COMBAT_ACTION
        return blocked payload (no state mutation)
     if resolution.class == ROLL:
        perform dice; attach evidence
     elif resolution.class == EXPLICIT_NO_ROLL:
        validate §4 fields + preconditions
     elif resolution.class == DETERMINISTIC_RULE:
        validate rule_id + preconditions
     apply mutations only after validation
  else:
     existing non-combat path
```

**Delete / gate** the current fallthrough:

```python
# FORBIDDEN in combat/irreversible context:
success_level = REGULAR_SUCCESS
roll_type = "none"
```

---

## 8. New Auditor findings (design)

| Finding ID | Severity | Trigger |
|---|---|---|
| `UNSUPPORTED_COMBAT_NO_ROLL` | CRITICAL | Combat action resolved NO_ROLL without EXPLICIT fields |
| `COMBAT_KILL_WITHOUT_RESOLUTION` | CRITICAL | Body destroyed / defeated without ROLL or validated DERIVED chain |
| `SPECIAL_OBJECTIVE_WITHOUT_VALIDATED_KILL_ROUTE` | CRITICAL | SO without `validated_kill_route_id` |
| `SCENARIO_SOURCE_PROVENANCE_MISSING` | context-dependent | See §8.1 |

### 8.1 Provenance severity and fail-closed completion

| Context | Severity | Blocking | Runtime |
|---|---|---|---|
| `FLAVOR` (clue, presentation, non-terminal investigation, non-critical state) | MAJOR | false | record finding; do not block the run |
| `VICTORY_CRITICAL` (validated kill route, `corbitt_defeated`, body destroyed, SO, combat ending/ended, HP terminal, irreversible object destruction, victory condition) | CRITICAL | true | fail-closed: do not commit victory, `corbitt_defeated`, SO, or combat completion |

Finding payload: `fact_id`, `fact_origin`, `source_ref`, `consumer_event`, `victory_critical`.

Kill-route authority remains `SOURCE` only. An `ADAPTATION_TRANSFORM` may appear in the chain only with `source_ref.rule_id` pointing at that SOURCE rule. It cannot set `may_define_kill_route=true`.

`CompletionAtomicity` must not publish `clear` / `completed` unless a validated kill route and a valid SOURCE provenance chain are both present. Missing victory-critical provenance blocks publication.

Normalizer: pass through new fields; do not invent kill routes.

Historical V8–V13: Auditor reproduction remains read-only; new findings apply to **new** runs / gated reproduction modes, not rewrite Accepted.

---

## 9. Likely files (WP-C)

- `core/src/main.py` — fallthrough removal; resolution declaration  
- `core/src/CombatProgression.py` — SPECIAL candidate gating  
- `core/src/AdjudicationEvidence.py` — explicit NO_ROLL schema  
- `core/src/CompletionAtomicity.py` — validated kill route  
- Formal Auditor v2 implementation + docs  
- Normalizer session schema  
- tests: Fixture E + negative fixture

---

## 10. Acceptance for WP-C design

- [x] Explicit resolution classes defined  
- [x] Fail-closed UNRESOLVED path defined  
- [x] Irreversible + SO protections defined  
- [x] Auditor finding IDs listed  
- [x] Implicit NO_ROLL path designed to remaining = 0 after implementation  
