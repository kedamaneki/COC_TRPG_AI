# CORBITT_FINAL_BATTLE_SOURCE_ADAPTATION_AUDIT

**Status:** PASS (audit complete; no implementation)  
**Date:** 2026-10-20  
**Work root:** `F:\制作物\その3\COC_TRPG_AI`  
**HEAD expected / observed:** `583ec1349821f2b9c815488f050ddd5dac42b62b` (`main`)  
**V13 Accepted source:** `CORBITT_LONGRUN_ITERATION3_V13_HOME_001`  
**V13 Raw aggregate SHA-256:** `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d`  
**Code changed:** 0  
**Historical artifacts changed:** 0  
**Implementation started:** false  

---

## 0. Preflight

| Check | Result |
|---|---|
| branch | `main` (`.git/HEAD` → `refs/heads/main`) |
| HEAD | `583ec1349821f2b9c815488f050ddd5dac42b62b` (matches baseline) |
| `git.exe` on PATH | **unavailable on this machine** — `git status` / `git diff` could not be executed; HEAD verified via `.git/refs/heads/main` |
| Working tree policy | Audit writes **docs only**; no code / scenario / V13 / migration |

Formal protection (read-only, not altered):

- `YMM4_VOICE_FIXTURE_PORTABILITY_V1 = PASS`
- `CROSS_PC_WORK_RESUME = PASS`
- `READY_TO_RESUME_DEVELOPMENT = true`
- V13 Formal Acceptance = **PRESERVED**

---

## 1. Authority / evidence roots

| Layer | Authority | Path / identity |
|---|---|---|
| A Source | Chaosium QuickStart scenario text (JP) | `core/src/悪霊の家.txt` (also mirrored as `core/src/scenario.txt`) — *The Haunting / 悪霊の家* |
| B Adaptation | Staged scenario + built scenario + NPC dataset | `core/scenario_sources/corbitt/e870e9f8fc96/*`, `core/src/build_corbitt_scenario.py`, `core/src/scenario_corbitt.json`, `core/src/npcs.json` |
| C Core | Combat / special-objective routing | `core/src/CombatProgression.py`, `core/src/ScenarioManager.py`, `core/src/main.py`, `core/src/CompletionAtomicity.py` |
| D Runtime | V13 Raw UEL | `F:\制作物\その3\evaluation-v2\CORBITT_LONGRUN_ITERATION3_V13_HOME_001\unified-event-log.json` (+ `session-log.json`) |

Video artifacts are **auxiliary only** and are not used as rule authority.

---

## 2. Layer A — Original source facts (cited)

Source citations use embedded QuickStart page markers in `悪霊の家.txt`. Short paraphrase only; no long verbatim reprint.

### CORBITT_STATS
- **Source:** QS ~p.34 / “ウォルター・コービットについて” / character block  
- **Fact:** STR 90, CON 115, SIZ 55, INT 80, POW 90, DEX 35, APP 5, EDU 80; HP 17; MP 18; DB +1D4; MOV 8; SAN 0  
- **Implication:** Boss has full combat attributes; not a prop corpse.

### CORBITT_BODY_ACTIVATION
- **Source:** QS ~p.32 / Room 4 / “コービットの攻撃”  
- **Fact:** Spending 2 MP activates the body for 5 combat rounds; Corbitt prefers not to move unless threatened.  
- **Implication:** Activation is conditional and costs MP; passivity is temporary, not permanent.

### CORBITT_FIGHT_BACK
- **Source:** QS ~p.32–33 / combat resolution bullets  
- **Fact:** On melee attack, Corbitt fights back with Fighting (Brawl) 50%; continues fighting back that round.  
- **Implication:** Investigator melee is opposed; no automatic body destruction.

### CORBITT_DODGE
- **Source:** QS ~p.34 stats  
- **Fact:** Dodge 17%.  
- **Implication:** Dodge exists as a defense option (PC-side vs floating dagger uses Dodge; Corbitt also has Dodge skill).

### CORBITT_DOMINATE
- **Source:** QS ~p.32 “その他の選択” + p.34–35 spell block  
- **Fact:** Unique Dominate; 1 MP; 1 round casting; POW 90 vs target POW; works while motionless; DEX+50 initiative when casting in combat.  
- **Implication:** Corbitt can act without body activation via Dominate.

### CORBITT_MAGIC_DAGGER
- **Source:** QS ~p.30 floating knife; p.34 weapons  
- **Fact:** Floating magic dagger; 1 MP / round as Corbitt’s action; autonomous attacks.  
- **Implication:** Separate combat threat before / during basement confrontation.

### CORBITT_DAGGER_SPECIAL_KILL
- **Source:** QS ~p.34 narrative + Location 7 hint (~sanitarium section)  
- **Fact:** If investigators wrest the dagger and stab Corbitt, he instantly becomes ash/dust **regardless of spells**. Sanitarium hint: “己の武器によって悪魔は滅びる!”  
- **Implication:** Instant-kill route exists and still requires successful control + attack — not a free declaration.

### CORBITT_BODY_ARMOR / FLESH_WARD
- **Source:** QS ~p.34–35 armor + 《肉体の保護》  
- **Fact:** Pre-cast Flesh Ward; roll **2D6** armor; non-magical damage reduced; armor depletes by damage blocked.  
- **Implication:** Ordinary hits do not auto-destroy the body.

### CORBITT_NORMAL_KILL_ROUTE (HP)
- **Source:** QS ~p.34  
- **Fact:** Damage exceeding armor reduces HP; Corbitt does not heal HP; cannot be knocked unconscious; at HP 0 he collapses to dust permanently.  
- **Implication:** Primary destruction is HP depletion through combat damage.

### CORBITT_NON_RESISTANCE / FEAR_PARALYSIS / UNCONSCIOUS
- **Source scan:** no matching rule text  
- **Classification:** `SOURCE_NOT_PRESENT`  
- **Implication:** Runtime total non-resistance has **no** source warrant.

### CORBITT_BREAK_BODY_NO_ROLL
- **Source scan:** no rule that “declare destroy body → automatic success / no roll”  
- **Classification:** `SOURCE_NOT_PRESENT`  
- **Implication:** V13 `NO_ROLL` body destruction is not source-supported.

### CORBITT_PURIFY_AND_DESTROY_ALTAR_HINT
- **Source scan:** Room 4 has a crumbling paper / horoscope, not a ruined altar teaching “cleanse and destroy the corpse”  
- **Classification:** `SOURCE_NOT_PRESENT` (as stated win recipe)  
- **Note:** Adaptation invents `ruined_altar` / Y’golonac / `learned_corbitt_weakness` purify-destroy text.

---

## 3. Layer B — Scenario adaptation

### Files resolved
| File | Role |
|---|---|
| `core/scenario_sources/corbitt/e870e9f8fc96/loc_13_corbitt_basement_room2.json` | Encounter object `corbitt_body` (search/inspect only) |
| `core/scenario_sources/corbitt/e870e9f8fc96/loc_14_corbitt_basement_room3.json` | Invented `ruined_altar` weakness hint |
| `core/src/build_corbitt_scenario.py` | **Synthesizes** encounter + `*__corbitt_body__defeat` special objectives |
| `core/src/scenario_corbitt.json` | Built runtime scenario used by engine / V13 input |
| `core/src/npcs.json` → `walter_corbitt` | Stats / armor_roll 2D6 / Dominate / dagger / Flesh Ward — largely source-faithful **data** |
| staged `events.json` | Does **not** contain final-battle defeat combat rules |

### Adaptation judgments (summary)

| Rule | Adaptation status | Evidence |
|---|---|---|
| Corbitt stats / HP / armor_roll / Dominate / dagger data | `ADAPTATION_PRESENT` | `npcs.json` |
| Body Activation (2 MP / 5 rounds) | `ADAPTATION_MISSING` | No event / AI / MP gate |
| Fight Back as Corbitt reaction | `ADAPTATION_MISSING` | No enemy reaction triggers on body attack |
| Dominate as Corbitt action choice | `ADAPTATION_MISSING` | Spell text only; no combat AI event |
| Magic dagger encounter combat | `ADAPTATION_PARTIAL` | Separate basement knife combat exists |
| Dagger special kill of Corbitt | `ADAPTATION_MISSING` | No stab-Corbitt-with-dagger clear route |
| 2D6 armor at boss start | `ADAPTATION_PARTIAL` | `combat_start.roll_armor_for: [walter_corbitt]` |
| HP depletion win | `ADAPTATION_CHANGED` | HP stored, but win is **not** HP-driven |
| `break corbitt_body` special objective | `ADAPTATION_CHANGED` / invented | `build_corbitt_scenario.py` defeat events + `SPECIAL_OBJECTIVE:CORBITT_BODY_DESTROYED` |
| Purify/destroy via altar | `ADAPTATION_CHANGED` | `loc_14` success_message — not in source Room 4 |

**Primary adaptation rewrite:** final win condition becomes  
`break|force|attack|use|push|kick` + `target=corbitt_body` + `success_level >= 2` → flag `corbitt_defeated` + `SPECIAL_OBJECTIVE_COMPLETED` + `combat_end`.

---

## 4. Layer C — Core implementation

### Paths that matter
1. **Special candidate generation** — `CombatProgression._scenario_special_candidates`: any event with `payload.combat_end` becomes combat category `SPECIAL` / goal `SPECIAL_OBJECTIVE`.
2. **Guidance** — `guide_combat_action` can steer PL to highest-priority special (`break`/`corbitt_body`).
3. **Resolution fallthrough** — `main.py` system action: if no skill / no required_check matching roll branches, defaults to:

```text
success_level = REGULAR_SUCCESS
roll_type = "none"   # becomes resolution_mode NO_ROLL
sys_log ≈ "判定なし（自動成功）"
```

4. **Scenario fire** — `ScenarioManager.process_action(..., success_level>=2)` matches `__corbitt_body__defeat`.
5. **Combat close** — `_apply_combat_payload_effects` logs `COMBAT_ACTION_RESOLVED` / `SPECIAL_OBJECTIVE_COMPLETED` with default `resolution_mode=NO_ROLL`, then `COMBAT_ENDING` / `COMBAT_ENDED`.
6. **Completion gate** — `CompletionAtomicity` requires special-objective evidence for formal clear (engine-correct under adapted contract).

### Core support matrix
| Capability | Core support for final battle |
|---|---|
| Normal attack vs `walter_corbitt` with armor/HP | Supported in general combat code |
| Enemy fight back / Dominate / body activation AI | **Not wired** for this boss finale |
| Special objective `break corbitt_body` | **Supported and preferred** |
| NO_ROLL auto-success for SPECIAL without check | **Supported by fallthrough** |
| Enforcing melee opposed roll / armor / HP before clear | **Bypassed** when special objective fires |

---

## 5. Layer D — V13 runtime (offsets 264..281)

Source: V13 `unified-event-log.json` (282 events; list index == `raw_event_offset`).

| Offset | Event | Key facts |
|---|---|---|
| 264 | LOCATION_CHANGE | pc_02 → `corbitt_basement_room2` |
| 265 | ACTION_AVAILABILITY_CHECKED | search `corbitt_body` |
| 266 | COMBAT_STARTED | target `walter_corbitt`; goal `ENEMY_DEFEATED`; participants pc_01, pc_02, walter_corbitt |
| 267 | COMBAT_ROUND_STARTED | — |
| 268–270 | INVESTIGATION_* / SKILL_* | investigation declared on `corbitt_body` |
| 271 | INVESTIGATION_ROLLED | 目星 / target 65 / roll 23 / `HARD_SUCCESS` / `ROLL` |
| 272–273 | INVESTIGATION_SUCCEEDED / TARGET_EXHAUSTED | encounter complete |
| 274 | COMBAT_ACTION_REJECTED | wait rejected |
| 275 | COMBAT_ACTION_SELECTED | `break` → `corbitt_body`, origin `SYSTEM_GUIDED` |
| 276 | ACTION_AVAILABILITY_CHECKED | break / corbitt_body |
| 277 | COMBAT_ACTION_RESOLVED | `NO_ROLL`, `SPECIAL_OBJECTIVE_COMPLETED`, reason `SPECIAL_OBJECTIVE:CORBITT_BODY_DESTROYED` |
| 278 | SPECIAL_OBJECTIVE_COMPLETED | same adjudication |
| 279–280 | COMBAT_ENDING / COMBAT_ENDED | scenario_condition |
| 281 | NORMAL_PROGRESSION_RESUMED | — |

**Session-log corroboration (V13):**  
`【装甲】《肉体の保護》によりウォルター・コービットの装甲=6ポイント` appears at combat start, then PL declares body destruction, then `判定なし（自動成功）` → body destroyed / combat end.

**Not observed in 266..281:** Corbitt attack, fight back, Dominate, Dodge exchange, armor-mitigated damage to Corbitt HP, dagger special kill, HP→0 dust route.

Preceding offsets 250..261 are **floating dagger combat** (includes fight_back vs dagger), not the final body battle.

---

## 6. Four-layer comparison table

| Rule / Feature | SOURCE_PRESENT | ADAPTATION | CORE_SUPPORTED | RUNTIME_OBSERVED (V13 finale) | Classification |
|---|---|---|---|---|---|
| Fight Back (Corbitt) | yes | MISSING | general yes / finale unused | no | SOURCE_TO_ADAPTATION_LOSS, COMBAT_MODEL_GAP |
| Body Activation | yes | MISSING | no AI | no | SOURCE_TO_ADAPTATION_LOSS, DATA_MODEL_GAP |
| Dominate | yes | data only | no AI | no | SOURCE_TO_ADAPTATION_LOSS, COMBAT_MODEL_GAP |
| Magic Dagger (floating fight) | yes | PARTIAL | yes | earlier yes; not in finale | INTENTIONAL_SIMPLIFICATION (partial) |
| Dagger instant kill of Corbitt | yes | MISSING | no | no | SOURCE_TO_ADAPTATION_LOSS |
| 2D6 Armor | yes | PARTIAL (roll at start) | yes | rolled (=6) but unused | ADAPTATION_TO_CORE_LOSS / COMBAT_MODEL_GAP |
| HP depletion route | yes | CHANGED (unused for win) | yes if attacked | no | SOURCE_TO_ADAPTATION_LOSS, UNJUSTIFIED_RULE_SUBSTITUTION |
| break corbitt_body objective | no (as NO_ROLL win) | yes (invented) | yes | yes | UNJUSTIFIED_RULE_SUBSTITUTION, SPECIAL_OBJECTIVE_OVERREACH |
| NO_ROLL body destruction | no | gate says success_level≥2 | yes (fallthrough none) | yes | UNSUPPORTED_NO_ROLL_RESOLUTION, ADAPTATION_TO_CORE_LOSS |
| Corbitt total non-resistance | SOURCE_NOT_PRESENT | implicit via special path | emergent | yes | NARRATIVE_GAP, COMBAT_MODEL_GAP |

Full matrix: `docs/CORBITT_FINAL_BATTLE_RULE_MATRIX.md`.

---

## 7. Critical Q&A

### Q1 — Does source support “declare destroy body → NO_ROLL success”?
**NOT_SUPPORTED**

### Q2 — Does source support Corbitt offering no resistance in this situation?
**NOT_SUPPORTED** (`SOURCE_NOT_PRESENT` for permanent non-resistance; source instead specifies activation, fight back, Dominate, dagger, armor, HP).

### Q3 — What source rule does `SPECIAL_OBJECTIVE_COMPLETED` abstract?
**Loose abstraction of “Corbitt destroyed / house curse broken”** (HP→0 dust **or** dagger special kill / conclusion “葬り去った”).  
It does **not** faithfully encode armor, opposed combat, or dagger control. Mapping quality: **OVERREACH**.

### Q4 — Is V13 runtime scenario-faithful?
**No.** Formal-engine consistent with adapted special-objective contract; **scenario fidelity FAIL**.

### Q5 — Known-Good scope of V13 finale
**Known-good for:** Formal Evidence / Normalizer / Auditor / Completion Atomicity / lifecycle purity under **adapted** rules.  
**Not known-good for:** Chaosium *The Haunting* final-battle fidelity.

Distinction preserved:

- `V13_FORMAL_ACCEPTANCE = PRESERVED` / may remain `FORMALLY CONSISTENT`
- `V13_SCENARIO_FIDELITY = FAIL`

---

## 8. PRIMARY_LOSS_STAGE

**PRIMARY_LOSS_STAGE = MULTI_STAGE**

1. **SOURCE_TO_ADAPTATION** — win condition rewritten to `break corbitt_body` special objective; Corbitt AI rules omitted.  
2. **ADAPTATION_TO_CORE** — adaptation still gates on `success_level >= 2`, but Core SPECIAL path auto-grants success with `roll_type=none` → `NO_ROLL`.  
3. **CORE_TO_RUNTIME** — V13 executed that contract faithfully (not an accidental runtime regression).

Root cause tree: `docs/CORBITT_FINAL_BATTLE_ROOT_CAUSE_TREE.md`.

---

## 9. Severity

| ID | Finding | Severity |
|---|---|---|
| F1 | NO_ROLL body destruction unsupported by source | **CRITICAL** |
| F2 | Corbitt non-resistance / missing fight back–Dominate–activation | **CRITICAL** |
| F3 | HP/armor win route replaced by special objective | **CRITICAL** |
| F4 | Dagger special kill route missing | **MAJOR** |
| F5 | Altar purify/destroy invention | **MAJOR** |
| F6 | Armor rolled but unused in finale | **MINOR** |
| F7 | Formal acceptance vs fidelity confusion risk | **INFORMATIONAL** |

---

## 10. New run / video impact

- `NEW_FULL_LONG_RUN_REQUIRED = true` — final battle win logic must change for fidelity.  
- `VIDEO_002_CURRENT_VALIDITY = INVALID_AS_SCENARIO_FIDELITY_REFERENCE` (video itself unchanged).  
- V13 Raw / tags / accepted artifacts: **do not modify**.

Remediation (proposal only): `docs/CORBITT_FINAL_BATTLE_REMEDIATION_PLAN.md`.  
QA checklist: `docs/CORBITT_FINAL_BATTLE_AUDIT_QA.md`.

---

## 11. Final disposition block

```
CORBITT_FINAL_BATTLE_SOURCE_ADAPTATION_AUDIT = PASS
SCENARIO_FIDELITY = FAIL
PRIMARY_LOSS_STAGE = MULTI_STAGE
CRITICAL_FINDINGS = F1,F2,F3
MAJOR_FINDINGS = F4,F5
NO_ROLL_BODY_DESTRUCTION_SUPPORTED = false
CORBITT_NON_RESISTANCE_SUPPORTED = false
SPECIAL_OBJECTIVE_MAPPING = OVERREACH_ABSTRACT_OF_HP0_OR_DAGGER_KILL
V13_FORMAL_ACCEPTANCE = PRESERVED
V13_SCENARIO_FIDELITY = FAIL
NEW_FULL_LONG_RUN_REQUIRED = true
VIDEO_002_CURRENT_VALIDITY = INVALID_AS_SCENARIO_FIDELITY_REFERENCE
IMPLEMENTATION_STARTED = false
```
