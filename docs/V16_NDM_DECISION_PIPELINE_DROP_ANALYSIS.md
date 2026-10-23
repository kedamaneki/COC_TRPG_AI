# V16 NDM Decision Pipeline Drop Analysis

## Intended chain

```text
PL_REASONING_COMPLETED
  → candidate set
  → PL/GROUP decision
  → ACTION_SELECTED (bound)
  → ACTION_EXECUTED
```

## Observed attempt outcomes (197 decide-like outcomes)

| kind | count |
|---|---:|
| NDM_SUCCESS (full bind) | 3 |
| PURE_FALLBACK (no COMPLETED) | 5 |
| COMPLETED_THEN_FALLBACK | 189 |

`PL_REASONING_EVENT_COUNT=192` = 3 success + 189 COMPLETED_THEN_FALLBACK.  
`LEGACY_DECISION_COMMIT_COUNT=194` = 5 pure + 189 paired fallbacks.

## Stage classification (192 reasonings + 5 pure)

| Final stage | count | notes |
|---|---:|---|
| STAGE_5_EXECUTOR_ACCEPTED | 3 | NDM ACTION_SELECTED bound |
| STAGE_3_DECISION_SELECTED | 5 | PL select ran inside pipeline; KP assess then exploded; no COMPLETED |
| STAGE_1_REASONING_ONLY | 189 | COMPLETED emitted (often action=null) then KP assess fail → FALLBACK |

`UNKNOWN_PIPELINE_DROP_COUNT = 0`

## Drop aggregates (required)

| Metric | count |
|---|---:|
| PIPELINE_DROP_AFTER_REASONING | 189 |
| PIPELINE_DROP_AFTER_CANDIDATES | 0 |
| PIPELINE_DROP_AFTER_DECISION | 5 |
| PIPELINE_DROP_BEFORE_EXECUTOR | 0 |
| EXECUTOR_REJECT | 0 |
| SUCCESSFUL_NDM_COMMIT | 3 |

## Why 192 vs 3

1. **First ~3 decides:** `stall.recent_actions` empty/short → KP assess OK → full NDM commit.  
2. **Next 5 decides:** list-shaped `recent_actions` length ≥3 → `assess_party_progress` AttributeError inside pipeline → exception propagates (SAFE_LEGACY select also AttributeErrors on same lists) → runtime `_fallback_select` → **PURE_FALLBACK** (no COMPLETED). Pipeline fallback streak increments to 5.  
3. **Remaining 189:** pipeline assess AttributeError → `fallback.select` hits streak>`MAX_FALLBACK_STREAK` → **`FAIL_CLOSED`** return with PL `reasoning_evidence` but `selected_action=None`. Runtime ignores `FAIL_CLOSED`, emits **PL_REASONING_COMPLETED** (action/target null, reason text may exist), then KP assess AttributeErrors again → SAFE_LEGACY.  

Hence Reasoning events keep accruing without NDM ACTION_SELECTED.

## Transaction continuity

| Link | Rate |
|---|---:|
| REASONING_TO_CANDIDATE_BIND_RATE | 1.0 (192/192 COMPLETED have `candidate_set_id`) |
| CANDIDATE_TO_SELECTION_BIND_RATE | 0.0156 (3/192) |
| SELECTION_TO_EXECUTOR_BIND_RATE | 1.0 (3/3 ACTION_SELECTED) |
| END_TO_END_NDM_COMMIT_RATE | 0.0156 (3/192) |

For COMPLETED_THEN_FALLBACK, `decision_transaction_id` is continuous into FALLBACK; `selected_action_event_id` / executor bind absent.

## UNBOUND_DECISION_COMMIT guard

`UNBOUND_DECISION_COMMIT_REJECTION_COUNT = 0` among fallbacks.

Mass path is **not** “legal action rejected for missing metadata by unbound guard.”  
It is **schema AttributeError** swallowed into SAFE_LEGACY / FAIL_CLOSED.

| Class | Verdict |
|---|---|
| SAFETY_GUARD_CORRECT_REJECTION | no (not the mass path) |
| SAFETY_GUARD_OVER_REJECTION | **false** for unbound guard; **partial** for SAFE_LEGACY policy eagerness |
| MISSING_METADATA_PRODUCER | **true** — StallDetector produces list tuples, not dict metadata NDM expects |
| MISSING_BINDING_PROPAGATION | **true** — FAIL_CLOSED drops selected_action before runtime bind |

`SAFETY_GUARD_OVER_REJECTION = partial` (unbound guard OK; exception→fallback policy over-eager)
