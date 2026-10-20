# WP-A — Kill Routes Design

**Package:** WP-A  
**Status:** COMPLETE (design only)  
**Source authority:** `core/src/悪霊の家.txt` QS ~p.30, p.32–35; Loc.7 dagger hint  
**Audit basis:** `corbitt-final-battle-audit-v1` @ `8b9c285`

---

## 1. Goal

Restore two source-faithful destruction routes. Abolish the V13 path:

```text
break corbitt_body → SPECIAL_OBJECTIVE → NO_ROLL → success
```

`SPECIAL_OBJECTIVE_COMPLETED` becomes a **derived event after** a validated kill, not a primary action outcome.

---

## 2. Route A — Normal kill (HP attrition)

```text
PC declares attack (melee / firearm / tool-as-weapon)
        ↓
Attack resolution (ROLL required)
        ↓
Corbitt defense if applicable (Fight Back / Dodge / accept)
        ↓
Damage roll (if hit)
        ↓
Apply BODY_ARMOR (Flesh Ward residual points)
        ↓
Penetrating damage = max(0, damage − armor_points)
        ↓
armor_points := max(0, armor_points − damage_blocked)
        ↓
HP := max(0, HP − penetrating)
        ↓
if HP <= 0:
        emit CORBITT_HP_DEPLETED
        emit CORBITT_BODY_DESTROYED (dust)
        emit SPECIAL_OBJECTIVE_COMPLETED (derived)
        combat_end
```

### 2.1 Attack action mapping

| PC intent | Canonical action | Target | Resolution |
|---|---|---|---|
| Attack living Corbitt | `attack` / `shoot` | `walter_corbitt` | ROLL (Fighting / Firearm) |
| Strike / smash body while Corbitt active | `attack` (preferred) | `walter_corbitt` | same as above |
| `break` / `force` / `kick` / `push` on `corbitt_body` **pre-defeat** | **remap** → `attack` vs `walter_corbitt` **or** reject as `UNRESOLVED` if remap unavailable | — | Must not SPECIAL auto-clear |

**Final design decision for `break corbitt_body`:**

- **Pre-defeat:** illegal as SPECIAL objective. Remap to `attack` targeting `walter_corbitt` with Fighting (Brawl) or STR-as-melee per engine judgment. Emit `ACTION_REMAPPED` provenance.
- **Post-defeat (HP0 already true):** optional narrative `break`/`inspect` remains with `EXPLICIT_NO_ROLL` + `source_rule_id=POST_DEFEAT_NARRATIVE` only.

### 2.2 Armor design (2D6 Flesh Ward)

| Field | Design |
|---|---|
| Formula | `2D6` (source) |
| Timing | Once at Corbitt combat start (`roll_armor_for`), when Flesh Ward already pre-cast |
| Persistence | Residual pool for this combat; **no mid-combat reroll**; no MP top-up while active ward remains (source) |
| Penetration | `blocked = min(armor_points, damage)`; `penetrating = damage − blocked`; `armor_points -= blocked` |
| Minimum damage | If penetrating = 0 → HP unchanged; combat continues |
| Magical / dagger special | Route B bypasses armor entirely |
| Extreme / Impale | Follow existing CoC damage multipliers **then** armor (unless Route B) |
| Logging | `ARMOR_ROLLED`, `ARMOR_APPLIED` with before/after points, damage in/out |
| Audit evidence | Must appear in Formal adjudication envelope for any damaging hit |

### 2.3 HP design

| Field | Design |
|---|---|
| Initial | From `npcs.json` `walter_corbitt.attributes.HP` (17) |
| Floor | 0 (no negative) |
| Healing | None during confrontation (source) |
| Unconscious | Not applicable (source: cannot KO) |
| Terminal | `HP <= 0` → dust; permanent; `corbitt_defeated=true` |
| Connection | Single SSOT: CharacterManager HP for `walter_corbitt`; do not maintain parallel “body HP” |

### 2.4 Events (Route A terminal)

| Order | Event | Notes |
|---|---|---|
| 1 | `COMBAT_ACTION_RESOLVED` (damaging hit) | ROLL |
| 2 | `ARMOR_APPLIED` (optional nested) | evidence |
| 3 | `COMBATANT_INCAPACITATED` / `CORBITT_HP_DEPLETED` | HP≤0 |
| 4 | `CORBITT_BODY_DESTROYED` | world fact |
| 5 | `SPECIAL_OBJECTIVE_COMPLETED` | **derived**, `cause_event_ids` → step 3/4 |
| 6 | `COMBAT_ENDING` / `COMBAT_ENDED` | |

---

## 3. Route B — Magic dagger special kill

```text
dagger state allows PC strike (OWNED by PC or controlled after contest)
        ↓
PC attacks Corbitt with magic dagger (ROLL)
        ↓
valid hit (success_level >= REGULAR) against Corbitt
        ↓
special kill trigger (source: wrest + stab → ash regardless of spells)
        ↓
bypass armor & remaining HP
        ↓
CORBITT_DAGGER_SPECIAL_KILL
        ↓
CORBITT_BODY_DESTROYED
        ↓
SPECIAL_OBJECTIVE_COMPLETED (derived)
        ↓
combat_end
```

### 3.1 Dagger state machine (extends ObjectLifecycle)

| State | Meaning | Allowed |
|---|---|---|
| `AVAILABLE` | On basement floor / found | pick → triggers floating combat |
| `IN_COMBAT` | Floating under Corbitt control | Corbitt dagger attack; PC may wrest |
| `INCAPACITATED` | Extreme success neutralized (existing) | may become `ON_FLOOR` |
| `ON_FLOOR` | Neutralized / dropped | PC may `OWN` |
| `OWNED` | PC controls dagger | Route B strike legal |
| `DESTROYED` | N/A unless narrative | — |

### 3.2 Control change

| Transition | Resolution | Cost |
|---|---|---|
| Corbitt keeps floating | Corbitt action; 1 MP / round (source) | MP |
| PC wrests while held | Opposed STR(PC) vs POW(Corbitt) (source knife section) | ROLL |
| After INCAPACITATED → OWNED | DETERMINISTIC_RULE or short pickup NO_ROLL with explicit reason `DAGGER_RECOVERY` | — |

### 3.3 Strike legality

- Actor owns / controls magic dagger.
- Target = `walter_corbitt`.
- Weapon id = `corbitt_floating_dagger` / `corbitt_knife` magic item.
- Required: Fighting roll (or scenario-declared skill).
- On success: Route B terminal (ignore armor/HP).
- On failure: no special kill; Corbitt may respond per WP-B.

### 3.4 Events (Route B terminal)

Same derived special-objective chain; `resolution_reason=DAGGER_SPECIAL_KILL_SOURCE_P34`.

---

## 4. SPECIAL_OBJECTIVE redefinition

| Aspect | Old (V13) | New (design) |
|---|---|---|
| Trigger | Action name match `break`+`corbitt_body` | Only after Route A or B validated |
| Resolution | Implicit NO_ROLL success | Derived; mode = `DETERMINISTIC_RULE` after validated kill |
| Direct action fire | Yes | **Forbidden** |
| CompletionAtomicity | Requires SO evidence | Publish `clear` only with `validated_kill_route_id` **and** a SOURCE provenance chain |

Schema sketch:

```json
{
  "event_type": "SPECIAL_OBJECTIVE_COMPLETED",
  "world_fact": {
    "event": "SPECIAL_OBJECTIVE_COMPLETED",
    "fact": "CORBITT_BODY_DESTROYED",
    "validated_kill_route_id": "ROUTE_A_HP0|ROUTE_B_DAGGER",
    "cause_event_ids": ["..."],
    "fact_origin": "SOURCE"
  },
  "resolution_mode": "DETERMINISTIC_RULE",
  "resolution_reason": "DERIVED_AFTER_VALIDATED_KILL"
}
```

---

## 5. Provenance constraint (kill routes)

| Kill route fact | Allowed `fact_origin` |
|---|---|
| HP0 dust | `SOURCE` |
| Dagger instant ash | `SOURCE` |
| Altar purify/destroy as win | **Forbidden** as kill route (`ADAPTATION_INFERENCE` may remain flavor only) |
| break-body NO_ROLL | **Forbidden** |

Kill-route authority is `SOURCE` only (`KILL_ROUTE_AUTHORITY = SOURCE_ONLY`). `ADAPTATION_TRANSFORM` may restate a SOURCE rule via `source_ref.rule_id` and cannot set `may_define_kill_route=true`. See master design §2.

---

## 6. Likely files (WP-A)

- `core/src/build_corbitt_scenario.py` — remove/rewrite defeat SPECIAL triggers
- `core/src/scenario_corbitt.json` — rebuild
- `core/scenario_sources/corbitt/e870e9f8fc96/loc_13_*.json` — usable_actions / combat notes
- `core/src/CombatProgression.py` — stop treating body-break as SPECIAL win
- `core/src/main.py` — remap break; armor/HP terminal; derived SO
- `core/src/CompletionAtomicity.py` — require validated_kill_route_id
- `core/src/ObjectLifecycle.py` / knife transitions — Route B
- `core/src/npcs.json` — consume armor_roll/HP (already present)
- tests: new fidelity suite (see Test Plan)

---

## 7. Acceptance for WP-A design

- [x] Route A fully specified  
- [x] Route B fully specified  
- [x] `break corbitt_body` redefined  
- [x] SPECIAL_OBJECTIVE derived-only  
- [x] Armor / HP / dagger fields specified  
