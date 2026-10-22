# V16 Combat Termination Contract Design

**Parent:** `V16_PREIMPLEMENTATION_FIX_DESIGN_V1`  
**Closes:** `PRIMARY_A = COMBAT_TERMINATION_GUARD_GAP`  
**CODE_CHANGED:** 0 (design only)  
**Builds on:** Final Battle remediation (validated kill routes Route A/B)

---

## 1. Problem restatement (V15)

Corbitt boss combat ended via:

```text
resolve_melee_combat_exchange:
  living = capable participants
  if len(living) <= 1:
      end_combat()  # default reason "resolved"
```

Result: both PCs HP 0, Corbitt HP 17, `corbitt_defeated=false`, `COMBAT_ENDED`, then “normal progression” with dead PCs.  
**No validated kill.** Completion contract failed.

---

## 2. Global combat end contract

### 2.1 Explicit reason + evidence (all combats)

`end_combat` / `COMBAT_ENDING` / `COMBAT_ENDED` require:

| Field | Rule |
|---|---|
| `combat_end_reason` | Explicit enum value — **bare `"resolved"` forbidden** for new code paths |
| `combat_end_evidence` | Non-empty object: `{adjudication_id?, validated_kill_route_id?, side?, policy_id?, …}` |

Proposed reason enum (design):

```text
ENEMIES_INCAPACITATED
PARTY_INCAPACITATED          # non-Corbitt-boss only, or holding — see §3
ESCAPE_SUCCESS
SCENARIO_CONDITION           # non-victory-critical only when allowed
VALIDATED_KILL               # Corbitt final: ROUTE_A_HP0 | ROUTE_B_DAGGER
COMBAT_ABORT_EVALUATION      # operator/eval stop — not scenario clear
```

### 2.2 Forbidden sole terminators

The following **must not** by themselves call `end_combat` or emit `COMBAT_ENDING`/`COMBAT_ENDED`:

| Cause | Required behavior instead |
|---|---|
| No active target | Retarget / skip turn / `needs_pl_retry` / log `NO_COMBAT_TARGET` — **stay ACTIVE** |
| BossCombatPolicy returns none / wait | Advance turn — **stay ACTIVE** |
| Empty combat action candidates | Guide / forced legal combat action / retry — **stay ACTIVE** |
| `len(living) <= 1` without classified reason | **Forbidden** as written; must map through `evaluate_combat_end` + Corbitt guard |

---

## 3. Corbitt final-battle specialization

Applies when:

```text
scenario flags.trigger_corbitt_boss_battle == true
AND walter_corbitt is a combat participant
AND combat_goal implies ENEMY_DEFEATED / Corbitt boss
```

### 3.1 Only legal end → full ordered chain

Corbitt final-battle lifecycle end is **not** “kill flag then END”. It must follow this **complete chain** in order:

```text
[1] VALIDATED_KILL
      validated_kill_route_id ∈ {ROUTE_A_HP0, ROUTE_B_DAGGER}
      + SOURCE provenance / CombatResolutionGuard pass
        ↓
[2] corbitt_defeated commit
      flag + consistent body/defeat state
        ↓
[3] DERIVED SPECIAL_OBJECTIVE_COMPLETED
      SO payload carries validated_kill_route_id
      CompletionAtomicity accepts
        ↓
[4] COMBAT_ENDING
      combat_end_reason = VALIDATED_KILL
      combat_end_evidence references kill + SO adjudication ids
        ↓
[5] TERMINATION_VALIDATION
      dedicated check before state flip to ENDED:
        - chain [1]–[4] present and ordered
        - corbitt_defeated == true
        - validated_kill_route_id present
        - SO evidence present
      ON FAIL → forbid ENDED; remain ACTIVE or ENDED-blocked; emit COMBAT_TERMINATION_VALIDATION_FAILED
        ↓
[6] COMBAT_ENDED
      only after termination validation PASS
```

```text
CORBITT_BOSS_COMBAT_END_ALLOWED
  iff full chain [1]→[2]→[3]→[4]→[5]→[6] completes without gap
```

Skipping any intermediate step is a **chain break** (fail-closed).  
Reason on ENDING/ENDED must be `VALIDATED_KILL` (derived SO may use `SCENARIO_CONDITION` only as the SO event class, still under the same kill evidence).

### 3.2 Fail-closed ban

```text
IF corbitt_defeated == false
AND no validated_kill_route_id in this combat
THEN
  FORBID emit COMBAT_ENDING
  FORBID emit COMBAT_ENDED
  FORBID end_combat(...) that flips state to ENDED for progression resume
```

Violation class: `COMBAT_END_WITHOUT_VALIDATED_KILL` (hard / blocking).

### 3.3 Party incapacitation during Corbitt boss

**Must not** use current living≤1 → `end_combat("resolved")` → “normal progression may resume”.

Design holding policy:

| Option | Behavior |
|---|---|
| Preferred | Enter `COMBAT_PARTY_DOWN` / evaluation pause class; combat remains **not** scenario-cleared; `corbitt_defeated` stays false |
| Alternate | Explicit `COMBAT_ABORT_EVALUATION` with evidence `party_incapacitated` — **still forbids** scenario completion / SO |

Either way: **no** `NORMAL_PROGRESSION_RESUMED` that continues Full-Long investigation with HP 0 PCs shuttling locations.

### 3.4 Enemy-side wipe without kill route

If Corbitt somehow becomes incapacitated without Route A/B payload → **fail-closed** (do not END as victory). Must recover via kill-route builders or block.

---

## 4. Non-Corbitt combats

Floating dagger / generic enemies may still end on `ENEMIES_INCAPACITATED` / `PARTY_INCAPACITATED` / `ESCAPE_SUCCESS` with explicit evidence.  
Corbitt guard must be scoped so it does not break those fights.

---

## 5. Producer rewrite map (later implementation)

| Current producer | V16 contract |
|---|---|
| `resolve_melee/shoot` living≤1 → `end_combat()` | Replace with `evaluate_combat_end` + Corbitt guard |
| `reconcile_post_combat_timeline` | Must refuse ENDING/ENDED when Corbitt guard fails |
| `_apply_combat_payload_effects` combat_end | Already victory-critical guarded; keep + require evidence |
| `queue_npc_combat_attack` no target → `end_combat()` | **Remove end**; stay ACTIVE |
| `resolve_escape_action` | Only if wired; not Corbitt victory path |
| BossCombatPolicy | Never ends combat (confirm unchanged) |

---

## 6. Evidence payload sketch

```json
{
  "event_type": "COMBAT_ENDING",
  "combat_end_reason": "VALIDATED_KILL",
  "combat_end_evidence": {
    "validated_kill_route_id": "ROUTE_A_HP0",
    "adjudication_id": "adj_…",
    "defender_id": "walter_corbitt",
    "corbitt_defeated": true
  }
}
```

Illegal example (V15-like):

```json
{
  "event_type": "COMBAT_ENDED",
  "combat_end_reason": "resolved",
  "combat_end_evidence": null
}
```

---

## 7. Acceptance for this WP (design-level)

| Gate | Requirement |
|---|---|
| Explicit reason/evidence | Required on all ends |
| no-target / policy-none / empty-candidates | Non-terminating |
| Full chain [1]–[6] | Required for Corbitt ENDED |
| Termination validation step | Required between ENDING and ENDED |
| Corbitt END without kill | Fail-closed forbidden |
| TPK during boss | No false progression resume |
| Intermediate-gap negative fixtures | CN-* required (see test plan) |
