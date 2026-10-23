# V17_MULTI_COMPONENT_FIX_DESIGN_V1

**Design status:** `APPROVED`  
**DESIGN_APPROVED_FOR_IMPLEMENTATION:** true  
**IMPLEMENTATION_STARTED:** false (at design freeze; implementation is a separate task)  
**CODE_CHANGED:** 0 (design pack only)  
**DESIGN_DOCS_COMMITTED:** pending Phase 0 commit  
**V17_READY:** false  
**V17 Full-Long / smoke:** FORBIDDEN until implementation precheck PASS  

**Audit docs:** V16 fallback audit remains separate uncommitted set; **not** mixed into this design commit later without Human Review sequencing.

---

## 0. Formal premises (from V16_NDM_FALLBACK_ROOT_CAUSE_AUDIT_V1)

```text
V16 Natural Decision Runtime was active.

PL reasoning and candidate construction worked.

The dominant failure occurred between candidate construction and selection
(post-PL / at KP assess & exception policy — not “PL cannot reason”).

194 / 194 fallback-related failures were caused by:
  'list' object has no attribute 'get'

Root data contract mismatch:
  StallDetector recent_actions = [action, target]
  Natural Decision consumer = dict.get(...)

NDM reasoning model failure = NOT PROVEN
SAFE fallback safety = PASS
SAFE fallback availability = FAIL
```

**PRIMARY_ROOT_CAUSE** = `RECENT_ACTIONS_SCHEMA_MISMATCH`

**Secondary (in scope):**

1. recent_actions schema mismatch  
2. Programming error → SAFE_LEGACY exception policy  
3. SAFE_LEGACY dual-fault (fallback.select on bad recent_actions)  
4. Exception → fallback over-fire  
5. progress_events unwired  
6. LEGACY / SAFE_LEGACY counter conflation  

**Out of scope / frozen:** PL scoring, KP S0–S4 semantics, frontier value policy, personality weights, group decision model (`NDM_ALGORITHM_CHANGE_PLANNED = false`).

**Formal V17 session (later):** `CORBITT_LONGRUN_ITERATION3_V17_HOME_001`  
**Smoke id:** `CORBITT_NDM_SCHEMA_SMOKE_V17PRE_001` (must not use formal V17 id)

---

## 1. Purpose

Fix **contract / integration / telemetry / counters** before any V17 Full-Long so that:

- RecentAction is one canonical schema  
- Contract/programming errors **BLOCK** (never SAFE_LEGACY)  
- SAFE_LEGACY is availability-only, non-recursive  
- Progress + self-recovery evidence is wired and Full-Long metrics are non-null  
- Counters separate NDM / SAFE_LEGACY / UNSAFE_LEGACY / violations  

Detail packs:

| Doc | Track |
|---|---|
| [V17_RECENT_ACTION_SCHEMA_DESIGN.md](./V17_RECENT_ACTION_SCHEMA_DESIGN.md) | A |
| [V17_RUNTIME_CONTRACT_VIOLATION_POLICY.md](./V17_RUNTIME_CONTRACT_VIOLATION_POLICY.md) | B |
| [V17_SAFE_FALLBACK_POLICY.md](./V17_SAFE_FALLBACK_POLICY.md) | C |
| [V17_PROGRESS_TELEMETRY_WIRING_DESIGN.md](./V17_PROGRESS_TELEMETRY_WIRING_DESIGN.md) | D |
| [V17_DECISION_COUNTER_SEPARATION.md](./V17_DECISION_COUNTER_SEPARATION.md) | E |
| [V17_PREIMPLEMENTATION_TEST_PLAN.md](./V17_PREIMPLEMENTATION_TEST_PLAN.md) | G/H |
| [V17_PRECHECK_GATES.md](./V17_PRECHECK_GATES.md) | H |
| [V17_MULTI_COMPONENT_FIX_DESIGN_V1_QA.md](./V17_MULTI_COMPONENT_FIX_DESIGN_V1_QA.md) | QA |
| [V17_MULTI_COMPONENT_FIX_DESIGN_V1.json](./V17_MULTI_COMPONENT_FIX_DESIGN_V1.json) | machine-readable |

---

## 2. Production path contract (Track F)

```text
Reasoning context
  → RecentActionSchema.validate / normalize (boundary)
  → candidate generation (unchanged algorithms)
  → selection (unchanged algorithms)
  → causal binding
  → executor
```

Schema validation FAIL ⇒ `NDM_RUNTIME_CONTRACT_VIOLATION` ⇒ **run BLOCK** (no SAFE_LEGACY).

`FAIL_CLOSED` from pipeline ⇒ BLOCK / SAFE_FALLBACK_FAILURE — **never** emit success `PL_REASONING_COMPLETED`.

---

## 3. Work packages (implementation later)

| WP | Title | Closes |
|---|---|---|
| WP-A | RecentActionNormalizer + StallDetector producer | PRIMARY |
| WP-B | Exception classifier + first-occurrence BLOCK | Sec 2/4 |
| WP-C | SAFE_LEGACY entry guards + no recursion | Sec 3 |
| WP-D | ProgressEvent buffer + enrich wiring | Sec 5 |
| WP-E | Counter split + coverage formula | Sec 6 |
| WP-T | RA/RC/SF/PT/CT tests + V17PRE smoke | gates |
| WP-G | Night Guard precheck updates | gates |

---

## 4. Impact files (implementation candidates)

| Area | Paths |
|---|---|
| StallDetector producer | `core/src/ProgressDirectorV2.py` (`StallDetectorV2`) |
| NDM consumer / decide | `core/src/reasoning/runtime.py`, `pipeline.py`, `kp_assessment.py` |
| SAFE_LEGACY | `core/src/reasoning/safe_fallback.py` |
| Production enrich | `core/src/ndm_integration.py` |
| Other recent_actions readers | `core/src/ProgressionPolicy.py` (tuple normalize already — align to canonical) |
| Telemetry / counters | `core/src/reasoning/runtime.py` (`NDMTelemetry`) |
| Error classifier (new module likely) | e.g. `core/src/reasoning/error_class.py` (name TBD) |
| RecentAction schema (new) | e.g. `core/src/reasoning/recent_action.py` |
| Progress bridge | `core/src/reasoning/progress_bridge.py`, ProgressDirector evaluate path |
| Night Guard | `tools/night_guard/ndm_wiring_smoke.py`, precheck helpers |
| Tests | `core/src/test_v16_ndm_*.py` extensions + new `test_v17_*.py` |

---

## 5. Historical compatibility

- V13–V16 Raw: **immutable**; no rewrite.  
- Read-only adapters OK for offline audit.  
- `RUNTIME_SCHEMA_MIGRATION_REQUIRED = true` for **live** stall.recent_actions element shape only.  
- `HISTORICAL_TAG_RETARGET_REQUIRED = false`.

---

## 6. Design QA summary

| Check | Target |
|---|---|
| RECENT_ACTION_MULTI_SCHEMA_PATH | 0 |
| CONSUMER_DIRECT_LEGACY_LIST_ACCESS | 0 |
| CONTRACT_VIOLATION_TO_SAFE_FALLBACK_PATH | 0 |
| SAFE_FALLBACK_RECURSION_PATH | 0 |
| PROGRESS_EVENT_UNWIRED_PATH | 0 |
| LEGACY_COUNTER_AMBIGUITY | 0 |
| FULL_LONG_METRIC_NULL_PATH | 0 |
| NDM_ALGORITHM_CHANGE_PLANNED | 0 / false |
| IMPLEMENTATION_STARTED | false |
| CODE_CHANGED | 0 |

**DESIGN_QA = PASS** (documentation completeness).

---

## 7. Recommended next step

**Human Review** of this design pack.  
Only after approval: implement WPs → smoke `CORBITT_NDM_SCHEMA_SMOKE_V17PRE_001` → precheck → then consider V17 Full-Long design/acceptance separately.

`V17_READY = false` until implementation + precheck PASS.
