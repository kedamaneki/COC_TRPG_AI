# CORBITT_FINAL_BATTLE_ROOT_CAUSE_TREE

Evidence-based loss tree for Walter Corbitt final battle fidelity.  
No remediation executed in this audit.

---

## Tree 1 — NO_ROLL body destruction (CRITICAL)

```
Original Rule (Layer A)
  HP attrition through armor  OR  dagger special kill
  (QS ~p.34; Loc.7 dagger hint)
        │
        ▼
Scenario conversion (Layer B)  ← PRIMARY SOURCE_TO_ADAPTATION
  build_corbitt_scenario.py invents:
    event corbitt_basement_room2__corbitt_body__defeat
    actions: break/force/attack/use/push/kick
    world_fact: SPECIAL_OBJECTIVE:CORBITT_BODY_DESTROYED
    combat_end: true
  (success_level >= 2 still written into trigger)
        │
        ▼
Simplified objective (Layer B/C interface)
  CombatProgression treats combat_end events as SPECIAL candidates
  Priority 100 > normal ATTACK
        │
        ▼
Core action routing (Layer C)  ← ADAPTATION_TO_CORE
  SYSTEM_GUIDED selects break/corbitt_body
  No required_check / no skill on SPECIAL break
  main.py fallthrough:
    success_level = REGULAR_SUCCESS
    roll_type = "none"  →  resolution_mode = NO_ROLL
        │
        ▼
NO_ROLL auto-resolution (Layer C → D)
  process_action matches defeat event
  _apply_combat_payload_effects emits
    COMBAT_ACTION_RESOLVED / SPECIAL_OBJECTIVE_COMPLETED
  defaults resolution_mode NO_ROLL
        │
        ▼
Runtime auto-resolution (Layer D — V13 275..280)
  Observed: SYSTEM_GUIDED break → NO_ROLL → clear
```

**PRIMARY_LOSS_STAGE for this tree:** MULTI_STAGE  
**Unsupported substitution:** UNJUSTIFIED_RULE_SUBSTITUTION + UNSUPPORTED_NO_ROLL_RESOLUTION + SPECIAL_OBJECTIVE_OVERREACH

---

## Tree 2 — Missing Corbitt resistance (CRITICAL)

```
Original Rule (Layer A)
  Body Activation (2 MP / 5 rounds)
  + Fight Back on melee
  + Dominate (even while motionless)
  + Armor 2D6 / HP 17
        │
        ▼
Scenario conversion (Layer B)  ← PRIMARY SOURCE_TO_ADAPTATION
  npcs.json keeps stats/spells/armor_roll  (data PRESENT)
  loc_13 usable_actions = search/inspect only
  No events for Dominate cast / activation MP / enemy turns
        │
        ▼
Combat model gap (Layer C)
  Generic fight_back/dodge/armor/HP exist
  Boss finale prefers SPECIAL objective path
  Enemy AI never spends turn to Dominate/activate/attack in V13 finale
        │
        ▼
Runtime (Layer D)
  Armor rolled (=6) then unused
  No Corbitt action between 266 and 278
  Non-resistance OBSERVED but SOURCE_NOT_PRESENT as a rule
```

**PRIMARY_LOSS_STAGE:** SOURCE_TO_ADAPTATION (behavior), with COMBAT_MODEL_GAP amplifying at Core.

---

## Tree 3 — Dagger special kill omission (MAJOR)

```
Original Rule
  Wrest dagger + stab Corbitt → instant ash (ignores spells)
        │
        ▼
Adaptation
  Floating dagger combat PRESENT as separate encounter
  Stab-Corbitt-with-dagger clear route MISSING
        │
        ▼
Runtime
  Dagger fight completed earlier (offsets ~250..261)
  Finale never offers dagger kill of body
```

---

## Where it was “lost” (single answer)

**PRIMARY_LOSS_STAGE = MULTI_STAGE**

If forced to name the **first decisive break**:

> **SOURCE_TO_ADAPTATION** — replacing source kill routes with an invented `break corbitt_body` special objective inside `build_corbitt_scenario.py`.

The Core NO_ROLL fallthrough is the **second decisive break** that made the invented objective resolve without even the adapted `success_level` roll.

Runtime did **not** invent a third divergent rule; it executed the adapted+Core contract.

---

## Formal vs fidelity fork

```
V13 Formal gates / CompletionAtomicity / Auditor
        │
        ├─ PASS under adapted SPECIAL_OBJECTIVE contract
        │     → V13_FORMAL_ACCEPTANCE = PRESERVED
        │
        └─ FAIL vs Chaosium final-battle rules
              → V13_SCENARIO_FIDELITY = FAIL
```

Do not rewrite V13 Raw to “fix” fidelity. Preserve as historical accepted formal run; document limitation.
