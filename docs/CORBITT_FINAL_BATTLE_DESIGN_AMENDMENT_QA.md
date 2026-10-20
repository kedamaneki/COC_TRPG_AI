# CORBITT_FINAL_BATTLE_DESIGN_AMENDMENT_QA

**Amendment:** `CORBITT_FINAL_BATTLE_REMEDIATION_DESIGN_V1_AMENDMENT`  
**Design QA:** PASS  
**Implementation started:** false  
**Code changed:** 0  
**Schema status:** design draft; not wired into runtime  
**Audit tag `corbitt-final-battle-audit-v1`:** unchanged

---

## Amendment results

| Item | Result |
|---|---|
| Amendment 1 — SOURCE-only kill-route authority | **PASS** |
| Amendment 2 — context-dependent provenance severity | **PASS** |

## Authority contract

| Rule | Value |
|---|---|
| `KILL_ROUTE_AUTHORITY` | `SOURCE_ONLY` |
| `ADAPTATION_TRANSFORM_CAN_DEFINE_KILL_ROUTE` | `false` |
| Transform on victory facts | `source_ref.rule_id` required; resolution traces to SOURCE `rule_id` |
| Victory chain | SOURCE kill rule → optional transform → validated route → `corbitt_defeated` → derived SO |

## Severity contract

| Context | Finding | Severity |
|---|---|---|
| Flavor / non-victory clue | `SCENARIO_SOURCE_PROVENANCE_MISSING` | MAJOR, not run-blocking |
| Victory-critical / irreversible combat outcome | `SCENARIO_SOURCE_PROVENANCE_MISSING` | CRITICAL, blocking, fail-closed |

`FAIL_CLOSED_VICTORY_COMMIT = DEFINED`  
`CompletionAtomicity` must not publish clear/completed without a validated kill route and a SOURCE provenance chain.

## Design QA gates

| Gate | Result |
|---|---|
| SOURCE_RULE_UNACCOUNTED | 0 |
| KILL_ROUTE_UNDEFINED | 0 |
| CORBITT_RESPONSE_UNDEFINED | 0 |
| IMPLICIT_NO_ROLL_PATH_REMAINING | 0 |
| KILL_ROUTE_AUTHORITY_CONFLICT | 0 |
| VICTORY_PROVENANCE_SEVERITY_UNDEFINED | 0 |
| FAIL_CLOSED_COMPLETION_RULE_UNDEFINED | 0 |
| HISTORICAL_MUTATION_PLANNED | 0 |
| IMPLEMENTATION_STARTED | false |
| CODE_CHANGED | 0 |

## Fixtures and gates added (design only)

- Test plan P1–P6
- V14 gates FB-11..FB-14: provenance missing = 0, non-SOURCE kill authority = 0, SO without SOURCE chain = 0, clear without SOURCE provenance = 0

## Approval

```
DESIGN_QA = PASS
DESIGN_APPROVED_FOR_IMPLEMENTATION = true
IMPLEMENTATION_STARTED = false
CODE_CHANGED = 0
```

Next task is not started: `CORBITT_FINAL_BATTLE_REMEDIATION_IMPLEMENTATION_V1`.
