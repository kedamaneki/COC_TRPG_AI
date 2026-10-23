# V17 Decision Counter Separation

**Track E**  
**Status:** COMPLETE

## V16 defect

`_commit_safe_legacy` incremented **both**:

- `SAFE_LEGACY_PROGRESSION_COUNT`
- `LEGACY_DECISION_COMMIT_COUNT`

Acceptance then treated `LEGACY_DECISION_COMMIT_COUNT=194` as unbound/legacy-primary failure, conflating **guarded SAFE_LEGACY** with **unsafe legacy**.

Design QA target: `LEGACY_COUNTER_AMBIGUITY = 0`.

## Mandatory counters

| Counter | Increments when |
|---|---|
| `NDM_DECISION_COMMIT_COUNT` | ACTION_SELECTED with `decision_source=natural_decision_v1` and bound reasoning_id |
| `SAFE_LEGACY_DECISION_COMMIT_COUNT` | committed action with `decision_source=safe_legacy_progression` under policy |
| `UNSAFE_LEGACY_DECISION_COMMIT_COUNT` | any other legacy / unbound / forbidden primary commit under NDM authority |
| `REASONING_FALLBACK_COUNT` | each classified recoverable fallback entry (attempt), whether or not action commits |
| `RUNTIME_CONTRACT_VIOLATION_COUNT` | each contract/programming violation (expect 0 on healthy run; first blocks) |
| `SAFE_FALLBACK_FAILURE_COUNT` | fallback entry refused or fallback path throws / dual-fault |

### Deprecated / renamed

| Old | V17 |
|---|---|
| `LEGACY_DECISION_COMMIT_COUNT` as mixed bucket | **retire from gates**; if kept for compat, alias documentation must state it ≠ SAFE_LEGACY |
| `SAFE_LEGACY_PROGRESSION_COUNT` | prefer `SAFE_LEGACY_DECISION_COMMIT_COUNT` (may keep alias = same value) |
| `selected_action_with_ndm_reasoning_count` | keep; should equal `NDM_DECISION_COMMIT_COUNT` |

## Gate meanings (V17)

| Gate | Expectation |
|---|---|
| `UNSAFE_LEGACY_DECISION_COMMIT_COUNT` | **= 0** |
| `RUNTIME_CONTRACT_VIOLATION_COUNT` | **= 0** |
| `SAFE_FALLBACK_FAILURE_COUNT` | **= 0** |
| `SAFE_LEGACY_DECISION_COMMIT_COUNT` | **not required to be 0** |
| `NDM_DECISION_COMMIT_COUNT` | **> 0** on smoke / Full-Long with NDM active |

## NDM_DECISION_CAUSAL_COVERAGE (normative)

```text
NDM_DECISION_CAUSAL_COVERAGE =
  NDM_DECISION_COMMIT_COUNT
  /
  max(1, NDM_DECISION_COMMIT_COUNT + SAFE_LEGACY_DECISION_COMMIT_COUNT)
```

Notes:

- Denominator **excludes** blocked/non-committed attempts.  
- **Excludes** `UNSAFE_LEGACY` (those fail the run; coverage undefined/failed).  
- SAFE_LEGACY is availability fallback, **not** “legacy violation.”  
- V17 Full-Long acceptance may still require coverage ≥ threshold (e.g. 1.0 or design-chosen floor); smoke may require > 0 NDM commits + coverage reported.

Optional reporting companion:

```text
SAFE_FALLBACK_SHARE =
  SAFE_LEGACY_DECISION_COMMIT_COUNT
  / max(1, NDM_DECISION_COMMIT_COUNT + SAFE_LEGACY_DECISION_COMMIT_COUNT)
```
