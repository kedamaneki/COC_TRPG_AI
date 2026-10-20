# CORBITT_FINAL_BATTLE_RULE_MATRIX

Companion to `CORBITT_FINAL_BATTLE_SOURCE_ADAPTATION_AUDIT.md`.  
Legend: Y = present/supported/observed · P = partial · N = no · SNP = SOURCE_NOT_PRESENT · INV = invented in adaptation.

## Master matrix

| Rule ID | Feature | SOURCE | ADAPTATION | CORE | RUNTIME V13 finale | Adaptation enum | Classifications | Severity |
|---|---|---|---|---|---|---|---|---|
| R01 | NORMAL_ATTACK vs Corbitt | Y | P (enemy exists) | Y | N | ADAPTATION_PARTIAL | COMBAT_MODEL_GAP | CRITICAL |
| R02 | FIGHT_BACK (Corbitt) | Y | N | Y (generic) | N | ADAPTATION_MISSING | SOURCE_TO_ADAPTATION_LOSS, COMBAT_MODEL_GAP | CRITICAL |
| R03 | DODGE (Corbitt skill / defense) | Y | P (skill in NPC) | Y (generic) | N | ADAPTATION_PARTIAL | SOURCE_TO_ADAPTATION_LOSS | MAJOR |
| R04 | DOMINATE | Y | P (spell text in NPC) | N (no AI cast) | N | ADAPTATION_PARTIAL | SOURCE_TO_ADAPTATION_LOSS, DATA_MODEL_GAP | CRITICAL |
| R05 | BODY_ACTIVATION (2MP / 5 rounds) | Y | N | N | N | ADAPTATION_MISSING | SOURCE_TO_ADAPTATION_LOSS, DATA_MODEL_GAP | CRITICAL |
| R06 | MAGIC_DAGGER floating combat | Y | P | Y | earlier only | ADAPTATION_PARTIAL | INTENTIONAL_SIMPLIFICATION | MAJOR |
| R07 | DAGGER_SPECIAL_KILL_ROUTE | Y | N | N | N | ADAPTATION_MISSING | SOURCE_TO_ADAPTATION_LOSS | MAJOR |
| R08 | BODY_ARMOR 2D6 | Y | P (`roll_armor_for`) | Y | Y roll / N use | ADAPTATION_PARTIAL | ADAPTATION_TO_CORE_LOSS, COMBAT_MODEL_GAP | MINOR |
| R09 | BODY_HP / NORMAL_KILL_ROUTE | Y | P (HP in NPC) / CHANGED win | Y | N | ADAPTATION_CHANGED | UNJUSTIFIED_RULE_SUBSTITUTION | CRITICAL |
| R10 | HP0 → dust permanent | Y | N explicit | P | N | ADAPTATION_MISSING | SOURCE_TO_ADAPTATION_LOSS | CRITICAL |
| R11 | BREAK_CORBITT_BODY objective | SNP as NO_ROLL win | Y INV | Y | Y | ADAPTATION_CHANGED | UNJUSTIFIED_RULE_SUBSTITUTION, SPECIAL_OBJECTIVE_OVERREACH | CRITICAL |
| R12 | SPECIAL_OBJECTIVE_COMPLETED | SNP exact | Y | Y | Y | ADAPTATION_CHANGED | SPECIAL_OBJECTIVE_OVERREACH | CRITICAL |
| R13 | NO_ROLL_RESOLUTION body destroy | SNP | P (success_level gate) | Y fallthrough | Y | ADAPTATION_PARTIAL | UNSUPPORTED_NO_ROLL_RESOLUTION, ADAPTATION_TO_CORE_LOSS | CRITICAL |
| R14 | Corbitt non-resistance | SNP | emergent | emergent | Y | — | NARRATIVE_GAP | CRITICAL |
| R15 | ruined_altar purify/destroy hint | SNP | Y INV | Y flags | N (V13 unused) | ADAPTATION_CHANGED | NARRATIVE_GAP | MAJOR |

## Source citation index (Layer A)

| Rule ID | Source page / heading | Short paraphrase | Gameplay implication |
|---|---|---|---|
| R01–R03 | QS ~p.32–34 Room 4 combat | Melee opposed with fight back; Dodge 17%; DEX order | Body cannot be auto-broken |
| R04 | QS ~p.32, p.34–35 | Dominate anytime; POW opposed; DEX+50 when casting | Motionless still dangerous |
| R05 | QS ~p.32 | 2 MP → 5 rounds physical action | Activation is costly/conditional |
| R06–R07 | QS ~p.30, p.34; Loc.7 hint | Floating dagger; wrest+stab = instant ash | Magical instant kill route |
| R08–R10 | QS ~p.34–35 | 2D6 Flesh Ward armor; HP 17; HP0 = dust | Ordinary kill is damage attrition |
| R11–R14 | — | No “declare destroy / no roll / no resist” | SNP |

## Adaptation file map (Layer B)

| Rule ID | Primary files | Notes |
|---|---|---|
| R01–R10 data | `core/src/npcs.json` (`walter_corbitt`) | Stats largely faithful |
| R06 | `scenario_corbitt.json` knife encounter + `corbitt_floating_dagger` | Separate combat |
| R08 | `build_corbitt_scenario.py` / encounter `roll_armor_for` | Rolled at start |
| R11–R13 | `build_corbitt_scenario.py` lines ~551–628; `scenario_corbitt.json` defeat events | Invented clear path |
| R15 | `loc_14_corbitt_basement_room3.json` | Invented altar |

## Core path map (Layer C)

| Rule ID | Code locus | Behavior |
|---|---|---|
| R02–R03 generic | `main.py` defense modes; `GameStateManager` | Available for normal attacks |
| R08 apply | `main.py` `_apply_combat_payload_effects` armor roll; `GameStateManager._apply_hit_with_armor` | Works if damage applied |
| R11–R13 | `CombatProgression._scenario_special_candidates`; `main.py` roll fallthrough `roll_type=none`; `_apply_combat_payload_effects` special objective | Prefer SPECIAL; auto NO_ROLL |
| Completion | `CompletionAtomicity.py` | Formal clear requires special objective |

## Runtime observation map (Layer D — V13)

| Offset | Observation linked to rules |
|---|---|
| 266 | Combat started vs `walter_corbitt` (R01 setup) |
| session @ start | Armor=6 logged (R08 partial) |
| 271 | Spot Hidden HARD_SUCCESS (encounter, not attack) |
| 275–278 | SYSTEM_GUIDED `break` → NO_ROLL SPECIAL_OBJECTIVE (R11–R13) |
| 266–281 | No R02/R04/R05/R07/R09/R10 |

## Loss-stage counts (rule-level)

Counting rules with primary loss attributed (multi-label allowed; unique rules):

| Stage | Count (rules primarily lost here) | Rules |
|---|---|---|
| SOURCE_TO_ADAPTATION | 8 | R02,R04,R05,R07,R09,R10,R11,R15 |
| ADAPTATION_TO_CORE | 2 | R08 (unused), R13 (success_level gate bypassed) |
| CORE_TO_RUNTIME | 0 | Runtime matched adapted Core contract |
| MULTI_STAGE overall finding | 1 | Final battle as system |

`SOURCE_TO_ADAPTATION_LOSS_COUNT = 8`  
`ADAPTATION_TO_CORE_LOSS_COUNT = 2`  
`CORE_TO_RUNTIME_LOSS_COUNT = 0`
