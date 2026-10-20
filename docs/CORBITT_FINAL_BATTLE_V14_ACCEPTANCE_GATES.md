# CORBITT_FINAL_BATTLE_V14_ACCEPTANCE_GATES

**Status:** COMPLETE (design only)  
**Proposed run ID:** `CORBITT_LONGRUN_ITERATION3_V14_HOME_001`  
**Execution in this phase:** forbidden  

---

## 1. Run identity rules

| Field | Value |
|---|---|
| Session ID | `CORBITT_LONGRUN_ITERATION3_V14_HOME_001` |
| Seed | Prefer same seed family as V13 (`2101`) for comparability **or** document deliberate change |
| Branch | `main` at implementation-complete commit |
| Preflight tag | `v14-preflight-accepted` (new; do not move V13 tags) |
| Full acceptance tag | `v14-full-long-accepted` after gates |
| Relation to V13 | Sibling historical baseline; **does not rewrite** V13 |

---

## 2. Dual badge model

| Badge | Meaning |
|---|---|
| `FORMAL_KNOWN_GOOD` | Evidence/Normalizer/Auditor/lifecycle contracts |
| `SCENARIO_FIDELITY_KNOWN_GOOD` | Chaosium final-battle fidelity (WP-A/B/C) |

V13 remains: Formal yes / Fidelity no.  
V14 target: both yes.

---

## 3. Final-battle fidelity gates

| Gate ID | Requirement | Pass criterion |
|---|---|---|
| FB-01 | Valid kill route used | `validated_kill_route_id` ∈ {ROUTE_A_HP0, ROUTE_B_DAGGER} |
| FB-02 | Implicit combat NO_ROLL | count = 0 for irreversible actions |
| FB-03 | Armor applied | At least one `ARMOR_ROLLED` at Corbitt combat start; damaging hits show ARMOR_APPLIED when armor>0 |
| FB-04 | HP or dagger evidenced | Route A: HP path to 0 **or** Route B: dagger special kill event |
| FB-05 | Corbitt response | When threat predicates true: ≥1 of Dominate / Activation / Dagger attack / Fight Back / Normal Attack before clear (unless clear occurs on same first PC action after activation race — still require Corbitt had legal opportunity or reaction) |
| FB-06 | Special objective chain | SO only after kill; `cause_event_ids` valid; CompletionAtomicity PASS |
| FB-07 | Auditor blockers | critical=0, blocking=0 for new findings |
| FB-08 | Traceability | 1.0 |
| FB-09 | Provenance | Kill-route authority facts `fact_origin=SOURCE`; transforms only via `source_ref.rule_id` |
| FB-10 | No break-body auto-clear | Zero events with reason `SPECIAL_OBJECTIVE:CORBITT_BODY_DESTROYED` without validated kill |
| FB-11 | Victory provenance present | `VICTORY_CRITICAL_PROVENANCE_MISSING = 0` |
| FB-12 | SOURCE-only kill authority | `KILL_ROUTE_AUTHORITY_NON_SOURCE = 0` |
| FB-13 | SO source chain | `SPECIAL_OBJECTIVE_WITHOUT_SOURCE_KILL_CHAIN = 0` |
| FB-14 | Clear provenance | `CLEAR_WITHOUT_SOURCE_PROVENANCE = 0` |

---

## 4. Formal gates (retain V13-class)

Segment coverage 1.0; lifecycle relation clean; Skill Registry clean; Dice identity; Completion Atomicity; Normalizer PASS; Auditor v2 PASS; Raw freeze rehash PASS.

---

## 5. Video 002 policy

| Item | Policy |
|---|---|
| Existing Video 002 V1 | Keep; classify `HISTORICAL_RUNTIME_REPLAY` + `INVALID_AS_SCENARIO_FIDELITY_REFERENCE` |
| Delete | **No** |
| Remake | Only from V14 (or later) fidelity-accepted Raw |
| Citation | Docs must not cite V1 as source-faithful finale |

---

## 6. Historical compatibility

- V8–V13 Raw/control/normalizer/auditor: read-only  
- No backfill, resume, segment regen, Accepted overwrite  
- New findings do not retroactively invalidate Formal Acceptance tags of V13

---

## 7. NEW_FULL_LONG_RUN_REQUIRED

**true** — design confirms; execution deferred until Human Review + implementation.
