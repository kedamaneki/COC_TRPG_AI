# CORBITT_FINAL_BATTLE_TEST_PLAN_V1

**Status:** COMPLETE (design only)  
**IMPLEMENTATION_STARTED:** false  

---

## 1. Strategy

- Deterministic unit/integration fixtures first (no LLM).  
- Formal Auditor findings asserted on fixture envelopes.  
- Historical V8–V13: reproduction smoke only; **zero mutation**.  
- Full long run V14 after WP-A/B/C land (not in this design phase).

---

## 2. Deterministic fixtures

| ID | Name | Setup | Assert |
|---|---|---|---|
| A | Armor blocks all | Corbitt armor=12; hit damage=5 | penetrating=0; HP unchanged; combat continues; ARMOR_APPLIED logged |
| B | Damage penetrates | armor=3; damage=8 | armor→0; HP −5; combat continues |
| C | HP reaches zero | HP=2; penetrating=2+ | HP=0; BODY_DESTROYED; derived SO; COMBAT_ENDED; validated_kill_route=ROUTE_A_HP0 |
| D | Dagger special kill | dagger OWNED by PC; Fighting success | armor/HP bypass; BODY_DESTROYED; SO derived; route=ROUTE_B_DAGGER |
| E | Implicit NO_ROLL kill blocked | `break`/`corbitt_body` without explicit resolution | `UNRESOLVED_COMBAT_ACTION` or remap-to-attack requiring ROLL; **no** SO; HP unchanged |
| F | Fight back occurs | Body active; PC melee | defense_mode=fight_back; opposed resolution logged |
| G | Body activation | MP≥2; escalation true | MP−2; active 5 rounds; event CORBITT_BODY_ACTIVATED |
| H | Dominate route | Inactive body; MP≥1; eligible PC | POW opposed ROLL; on win dazed rounds applied |

### Negative fixture (mandatory)

| ID | Name | Assert |
|---|---|---|
| N1 | `break corbitt_body` without explicit resolution | FAIL_CLOSED; no `SPECIAL_OBJECTIVE_COMPLETED`; no `corbitt_defeated` |
| N2 | SO without validated_kill_route_id | Auditor CRITICAL `SPECIAL_OBJECTIVE_WITHOUT_VALIDATED_KILL_ROUTE` |
| N3 | Combat NO_ROLL missing explicit fields | `UNSUPPORTED_COMBAT_NO_ROLL` |
| N4 | ADAPTATION_INFERENCE altar hint used as kill | Rejected / cannot set defeated |

### Provenance fixtures (amendment)

| ID | Name | Assert |
|---|---|---|
| P1 | SOURCE kill route | `fact_origin=SOURCE` and `may_define_kill_route=true` → PASS |
| P2 | Transform cannot be authority | `fact_origin=ADAPTATION_TRANSFORM` and `may_define_kill_route=true` → schema/validator FAIL |
| P3 | Inference kill route rejected | `fact_origin=ADAPTATION_INFERENCE` used as kill route → BLOCK |
| P4 | Non-critical provenance missing | non-victory clue missing provenance → MAJOR; run not blocked |
| P5 | Victory-critical provenance missing | kill-route fact missing provenance → CRITICAL; completion blocked |
| P6 | Derived SO without SOURCE chain | `SPECIAL_OBJECTIVE_COMPLETED` without validated SOURCE chain → BLOCK |

---

## 3. Regression

| Suite | Policy |
|---|---|
| Existing combat tests (`test_coc7_rules`, `test_combat_progression_fix`, …) | Keep green; update only tests that asserted old break→SO auto-clear |
| `test_adjudication_evidence_recovery.test_final_battle_remains_special_objective` | **Must rewrite** to derived-SO-after-kill |
| V8–V13 historical Auditor reproduction | Read-only; no Raw rewrite |

---

## 4. Suggested test modules (names)

- `core/src/test_corbitt_kill_routes_v14.py` — Fixtures A–E, N1  
- `core/src/test_corbitt_response_ai_v14.py` — F–H  
- `core/src/test_combat_explicit_resolution_v14.py` — WP-C  
- `video/tests/test_formal_auditor_corbitt_kill_findings.py` — new findings  

---

## 5. Seed / determinism

- Fix RNG seed for armor 2D6 and damage.  
- Fixture A/B may set `armor_points` directly to avoid flaky rolls, while a separate test asserts armor **roll** distribution uses 2D6 formula.

---

## 6. Exit criteria for implementation phase

All fixtures A–H + N1–N4 + P1–P6 PASS; historical reproduction unchanged; CODE review confirms no combat fallthrough `roll_type=none` success.
