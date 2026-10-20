# WP-B — Corbitt Response AI Design

**Package:** WP-B  
**Status:** COMPLETE (design only)  
**Source authority:** QS ~p.30 (dagger), p.32–33 (Room 4 combat / Dominate), p.34–35 (activation, spells, stats)  
**Audit basis:** Corbitt non-resistance = `SOURCE_NOT_PRESENT`; must not recur.

---

## 1. Goal

Prevent “declare destroy → Corbitt does nothing → clear.”  
Corbitt must spend enemy turns / reactions using source-supported capabilities.

---

## 2. Capability inventory vs Core support

| Capability | Source | Existing Core | Support enum |
|---|---|---|---|
| Fight Back (melee reaction) | Y | `choose_npc_defense_mode`, `resolve_melee_defense_outcome`, pending_combat_defense | **SUPPORTED** |
| Dodge | Y (17%) | defense_mode dodge path | **SUPPORTED** |
| Normal Attack (unarmed / claw) | Y | `queue_npc_combat_attack` / `begin_combat_attack` | **SUPPORTED** |
| Magic Dagger floating attack | Y | knife encounter combat + `corbitt_floating_dagger` NPC | **PARTIAL** (separate combat; not integrated into boss AI policy) |
| Dominate spell | Y | Spell text in `npcs.json` only; no cast scheduler | **MISSING** |
| Body Activation (2 MP / 5 rounds) | Y | No state machine | **MISSING** |
| Enemy turn scheduler | Y | DEX queue + `queue_npc_combat_attack` | **PARTIAL** (attack-only; no spell/activation choice) |
| Interrupt / reaction beyond defense | Y (fight back) | Fight back as defense, not free interrupt | **PARTIAL** |
| STR vs POW wrest for dagger | Y | No dedicated contest action wired to object OWNED | **MISSING** |

**COMBAT_MODEL_EXTENSION_REQUIRED = true**

Required extensions:

1. `BossCombatPolicy` / Corbitt decision node (spell vs activate vs dagger vs melee).  
2. `BodyActivationState` (mp cost, remaining rounds, expiry).  
3. `SpellCastAction` for Dominate (POW opposed, duration, effect flags).  
4. Integrate dagger floating attack into same combat session as body (or explicit handoff rules).  
5. Control-contest action for dagger wrest → OWNED.

---

## 3. Source-aligned priority (final)

Threat context = PCs in Room 4 / `corbitt_basement_room2` after encounter, or board-breaking toward body (source: dagger if wall broken).

```text
On Corbitt enemy turn (or when policy invoked):
  1. If dagger available AND Corbitt still controls it AND MP >= 1:
        prefer MAGIC_DAGGER_ATTACK (1 MP = this round's action)
  2. Else if Dominate eligible (target in house, MP >= 1) AND
        (body not activated OR activation not chosen) AND
        strategic value high (multiple PCs / PC about to strike / PC holding dagger):
        DOMINATE (1 MP; casting uses DEX+50 initiative rule when in combat)
  3. Else if danger escalates (PC successful hit last round OR PC owns dagger OR HP lost)
        AND body inactive AND MP >= 2:
        BODY_ACTIVATION (2 MP → 5 rounds)
  4. Else if body active:
        NORMAL_ATTACK (Fighting 50%, 1D3+DB, claw infection rules)
  5. Else (inactive, no Dominate/dagger chosen):
        Dominate fallback if MP>=1 else wait / dagger if any

On PC melee attack against Corbitt while body active OR activated this round:
  REACTION: FIGHT_BACK preferred (aggression high; source: fights back with Fighting)
  Firearm: no fight back; may Dodge (17%) or accept (source: does not dive for cover)

Passive motionless is allowed ONLY before threat escalates (source: prefers not to move unless necessary).
It is NOT a permanent state once PCs are engaged.
```

Rationale citations:

- Dagger costs 1 MP and counts as the round’s action (p.34).  
- Dominate needs no motion; DEX+50 when casting in combat (p.32).  
- Activation costs 2 MP for 5 rounds; reluctant unless danger (p.32).  
- Melee → Corbitt fights back with Fighting (p.32–33).

---

## 4. Fight Back design

| Field | Spec |
|---|---|
| Trigger | PC melee hit attempt vs Corbitt while Corbitt can physically respond (body active **or** source allows fight back when engaged — design: require body active OR activation this round; if inactive, Corbitt should Dominate/dagger instead of fight back) |
| Target | Attacking PC |
| Roll | Fighting 50% vs attacker success levels (existing opposed compare) |
| Success | Counter / hit_attacker / miss per `resolve_melee_defense_outcome` |
| Damage | 1D3+DB (+ infection on successful unarmed hit) |
| Logging | `COMBAT_ACTION_RESOLVED` defense_mode=`fight_back` |
| Turn ownership | Reaction within attacker’s resolution; does not consume separate full turn beyond CoC fight-back rules |

Reuse: `GameStateManager.choose_npc_defense_mode` with `preferred_defense=fight_back`, `aggression>=80` on `walter_corbitt.combat_profile`.

---

## 5. Body Activation design

| Field | Spec |
|---|---|
| Cost | 2 MP |
| Duration | 5 combat rounds from activation inclusive |
| Storage | `combat_state.corbitt.body_activation = {active, rounds_remaining, activated_at_round}` |
| Allowed while active | Normal attack, fight back, move within room; dagger still available if controlled |
| Allowed while inactive | Dominate, dagger (if controlled), haunt-like non-physical (out of scope if not in combat) |
| AI choose when | Escalation predicates in §3 step 3 |
| Expiry | End of round: `rounds_remaining -= 1`; at 0 → inactive; may reactivate if MP≥2 and threat remains |
| Logging | `CORBITT_BODY_ACTIVATED`, `CORBITT_BODY_ACTIVATION_TICK`, `CORBITT_BODY_ACTIVATION_EXPIRED` |
| SAN | When first rises: 1/1D8 (source) — already partially on encounter; if activation later, ensure SAN once per “seen moving” |

---

## 6. Dominate design

| Field | Spec |
|---|---|
| Eligibility | Target PC physically in Corbitt house; Corbitt MP≥1 |
| Cost | 1 MP |
| Time | 1 round casting; in combat initiative DEX+50 |
| Resolution | Opposed POW 90 vs target POW — **ROLL** |
| Effect on Corbitt win | Target dazed 1D6+1 rounds; telepathic control; no suicide; may force reckless/attack; no memory after |
| Duration | 1D6+1 rounds |
| AI rule | Prefer when dagger unavailable / body inactive / need to stop dagger-holder or primary attacker |
| Reuse | No full spell engine found — **new** `SpellResolution` mini-module or combat action category `SPELL` |

---

## 7. Magic Dagger AI

| Field | Spec |
|---|---|
| Initial | Basement find → IN_COMBAT under Corbitt; or mid-boss if still controlled |
| Floating attack | 1/round; Corbitt POW vs PC Dodge compare (source knife section) **or** Fighting 40% autonomous profile — design: when Corbitt directs, use Corbitt-directed opposed POW/Dodge per source p.30; when autonomous NPC, keep existing profile |
| Target | Highest threat PC (dagger owner candidate / lowest HP / last attacker) |
| Damage | Per source knife table |
| Control contest | PC STR vs Corbitt POW to retain / seize |
| Loss of control | Extreme success incap → ON_FLOOR → PC OWNED |
| Reuse vs Corbitt | Route B (WP-A) |

---

## 8. NPC action scheduler evaluation

| Concern | Status | Extension |
|---|---|---|
| enemy turn | PARTIAL | Policy chooses action type before `begin_combat_attack` |
| reaction (fight back) | SUPPORTED | Wire preferred_defense on Corbitt |
| interrupt | PARTIAL | Dominate initiative bump |
| spell use | MISSING | SPELL action category |
| fight back | SUPPORTED | — |

---

## 9. Likely files (WP-B)

- `core/src/main.py` — `queue_npc_combat_attack` → policy dispatch  
- `core/src/GameStateManager.py` — activation state; defense prefs  
- New: `core/src/BossCombatPolicy.py` (or `CorbittCombatAI.py`)  
- New: spell opposed helper (or extend `CoCRules.py`)  
- `core/src/npcs.json` — set `preferred_defense`, `aggression`, policy hooks  
- `core/src/ObjectLifecycle.py` — dagger wrest  
- Formal Auditor — expect Corbitt response evidence when threat predicates true  
- tests: Fixtures F/G/H

---

## 10. Acceptance for WP-B design

- [x] Priority ordered with source basis  
- [x] Fight Back / Activation / Dominate / Dagger specified  
- [x] Core support matrix + COMBAT_MODEL_EXTENSION_REQUIRED=true  
- [x] Scheduler gaps listed  
