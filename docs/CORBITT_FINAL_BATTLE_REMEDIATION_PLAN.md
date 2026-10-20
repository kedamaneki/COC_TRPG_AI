# CORBITT_FINAL_BATTLE_REMEDIATION_PLAN

**Proposal only. IMPLEMENTATION_STARTED = false.**  
Do not modify V13 Raw / Accepted artifacts / tags.

---

## Principles

1. Preserve V13 as historical formal acceptance (`V13_FORMAL_ACCEPTANCE = PRESERVED`).
2. Restore scenario fidelity for **future** runs; do not backfill V13.
3. Separate formal engine correctness from Chaosium fidelity tests.
4. Prefer encoding source routes (HP+armor, fight back, Dominate, activation, dagger kill) over expanding special-objective shortcuts.

---

## Work packages

### WP-A — Restore source kill routes (CRITICAL)

| Item | Detail |
|---|---|
| Problem | Win = `break corbitt_body` NO_ROLL special objective |
| Recommended correction | Remove / demote body-break auto-clear. Win only via (1) Corbitt HP ≤ 0 after armor, or (2) successful dagger stab special kill. Optional narrative “destroy remains” after HP0 may be NO_ROLL **post-defeat only**. |
| Affected files | `core/src/build_corbitt_scenario.py`, `core/src/scenario_corbitt.json` (rebuild), possibly `loc_13`/`loc_14`, `CompletionAtomicity.py` contract |
| Expected tests | New fidelity tests: armor blocks damage; HP0 clears; break without damage does not clear; dagger special kill clears |
| New run required? | **yes** (full long run) |
| Historical artifacts impacted? | **no** (V13 untouched); new baseline supersedes fidelity claim only |

### WP-B — Corbitt combat AI / reactions (CRITICAL)

| Item | Detail |
|---|---|
| Problem | No Dominate / activation / fight back in finale |
| Recommended correction | Enemy turn policy: if threatened and MP≥2, consider BODY_ACTIVATION; else Dominate; when activated, melee with fight_back options per CoC opposed rules |
| Affected files | Combat AI / `GameStateManager` / scenario combat hooks / `npcs.json` consumption paths |
| Expected tests | Unit: Dominate opposed POW; activation MP spend + 5-round timer; fight_back vs PC melee |
| New run required? | **yes** |
| Historical impacted? | no |

### WP-C — Forbid unsupported NO_ROLL for body destroy (CRITICAL)

| Item | Detail |
|---|---|
| Problem | SPECIAL actions without required_check fall through to `roll_type=none` |
| Recommended correction | For combat SPECIAL targeting living Corbitt / `corbitt_body` pre-defeat: require Fighting/STR (or opposed) roll; never auto REGULAR_SUCCESS. Keep NO_ROLL only for post-defeat narrative or empty-clue objects. |
| Affected files | `core/src/main.py` (fallthrough), `CombatProgression.py`, scenario required_check definitions |
| Expected tests | `test_*`: break/corbitt_body in combat must emit ROLL evidence; NO_ROLL path rejected pre-defeat |
| New run required? | **yes** |
| Historical impacted? | no |

### WP-D — Dagger special kill route (MAJOR)

| Item | Detail |
|---|---|
| Problem | Floating dagger fight exists; stab-Corbitt kill missing |
| Recommended correction | If PC controls/neutralizes dagger, allow attack Corbitt with magic dagger → ignore Flesh Ward → instant defeat |
| Affected files | scenario events, object lifecycle for `corbitt_knife`, combat special rules |
| Expected tests | Dagger in PC control + successful attack → clear regardless of armor |
| New run required? | **yes** (at least combat-focused long/mini run covering finale) |
| Historical impacted? | no |

### WP-E — Altar / weakness text (MAJOR)

| Item | Detail |
|---|---|
| Problem | `ruined_altar` purify/destroy + Y’golonac hint is not source Room 4 |
| Recommended correction | Either mark as intentional house rule with explicit `INTENTIONAL_SIMPLIFICATION` flag, or replace with source-faithful Room 4 paper / Loc.7 dagger hint |
| Affected files | `loc_14_corbitt_basement_room3.json`, built scenario |
| Expected tests | Source-fidelity doc test / content audit |
| New run required? | only if it changes finale routing |
| Historical impacted? | no |

### WP-F — Documentation / acceptance taxonomy (INFORMATIONAL)

| Item | Detail |
|---|---|
| Problem | “Known-Good V13” conflated with scenario fidelity |
| Recommended correction | Split badges: `FORMAL_KNOWN_GOOD` vs `SCENARIO_FIDELITY_KNOWN_GOOD` |
| Affected files | `docs/KNOWN_GOOD_BASELINE_V13.md`, manifests |
| Expected tests | n/a |
| New run required? | no |
| Historical impacted? | docs only |

---

## Sequencing

1. WP-F docs taxonomy (safe, no code).  
2. WP-C NO_ROLL guard + WP-A win-condition rewrite (coupled).  
3. WP-B Corbitt AI.  
4. WP-D dagger kill.  
5. WP-E altar policy.  
6. New full long run → candidate **V14+** fidelity baseline.  
7. Video 002 remake only after new accepted fidelity run (optional product decision).

---

## NEW_FULL_LONG_RUN_REQUIRED

**true**

Reason: CRITICAL findings change finale win/loss logic and combat exchange structure. Segment/checkpoint regeneration on V13 is forbidden; a new session is required for any fidelity claim.

---

## VIDEO_002

| Field | Value |
|---|---|
| `VIDEO_002_CURRENT_VALIDITY` | `INVALID_AS_SCENARIO_FIDELITY_REFERENCE` |
| Action now | Do not delete/alter video; stop citing it as source-faithful final battle |
| Rebuild | Only after new fidelity-accepted run |

---

## Explicit non-actions (this audit)

- No code patches  
- No scenario source edits  
- No V13 Raw / Normalizer / Auditor overwrite  
- No commit unless user separately approves docs-only commit  
