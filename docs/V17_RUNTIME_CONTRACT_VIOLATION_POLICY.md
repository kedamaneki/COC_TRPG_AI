# V17 Runtime Contract Violation Policy

**Track B**  
**Status:** COMPLETE  
**ATTRIBUTE_ERROR_TO_SAFE_FALLBACK:** **forbidden**

## Premises

V16 hid 194 identical `AttributeError` schema mismatches behind SAFE_LEGACY.  
That collapses availability metrics and prevents diagnosing integration bugs.

## Exception classes (mandatory)

| Class | Meaning | SAFE_LEGACY? |
|---|---|---|
| `RECOVERABLE_REASONING_FAILURE` | Model/reasoning path failed in an expected way | **allowed** (subject to streak) |
| `INVALID_MODEL_OUTPUT` | Parse/schema of **model text** invalid | **allowed** (subject to streak) |
| `TRANSIENT_PROVIDER_FAILURE` | Timeout / temporary provider error | **allowed** (limited) |
| `RUNTIME_CONTRACT_VIOLATION` | Internal data contract broken | **forbidden** → BLOCK |
| `PROGRAMMING_ERROR` | AttributeError/TypeError/KeyError on internal contracts; impossible state | **forbidden** → BLOCK |

### Mapping rules (non-exhaustive, normative)

| Symptom | Class |
|---|---|
| `'list' object has no attribute 'get'` on recent_actions | PROGRAMMING_ERROR / RUNTIME_CONTRACT_VIOLATION |
| unsupported `recent_action_schema_version` | RUNTIME_CONTRACT_VIOLATION |
| missing required RecentAction field | RUNTIME_CONTRACT_VIOLATION |
| decision_transaction_id corruption / impossible NDM state | RUNTIME_CONTRACT_VIOLATION |
| UnexplainedActionError / KnowledgeBoundaryError (existing) | keep existing fail-closed / REJECT semantics (not SAFE_LEGACY) |
| PL/LLM empty or unparsable selection reason from model | INVALID_MODEL_OUTPUT or RECOVERABLE_REASONING_FAILURE |
| Ollama timeout | TRANSIENT_PROVIDER_FAILURE |

**Design QA target:** `CONTRACT_VIOLATION_TO_SAFE_FALLBACK_PATH = 0`.

## First-occurrence block

For `RUNTIME_CONTRACT_VIOLATION` and `PROGRAMMING_ERROR`:

```text
first occurrence
  → emit NDM_RUNTIME_CONTRACT_VIOLATION evidence
  → increment RUNTIME_CONTRACT_VIOLATION_COUNT
  → BLOCK run immediately
```

Do **not** wait for streak. Do **not** convert to SAFE_LEGACY.

Recoverable classes may use existing `fallback_streak` / `MAX_FALLBACK_STREAK` only.

## Error evidence (minimum)

```text
error_id
error_class                  # one of the five classes
module                       # e.g. reasoning.kp_assessment
schema_version               # recent_action_schema_version if relevant
input_shape                  # e.g. "list[2]", "dict", "list[3]", "unknown"
reasoning_id                 # if any
decision_transaction_id      # if any
cycle
turn
message                      # short str(exc) / classifier note
```

Persist on control/telemetry path suitable for Night Guard stop reason.

## Runtime decide control flow (design)

```text
try:
  validate RecentAction context
  pipeline.run_cycle(...)
  handle modes NATURAL | SAFE_LEGACY_PROGRESSION | REJECT | FAIL_CLOSED
except classified as RUNTIME_CONTRACT_VIOLATION | PROGRAMMING_ERROR:
  BLOCK
except classified as recoverable:
  SAFE_LEGACY once (policy Track C)
```

### FAIL_CLOSED handling (V16 secondary bug)

`mode == FAIL_CLOSED` must **not** be treated as NATURAL.

```text
FAIL_CLOSED
  → SAFE_FALLBACK_FAILURE or RUNTIME_CONTRACT_VIOLATION
  → BLOCK
  → never emit PL_REASONING_COMPLETED as success
```

## Broad `except Exception` policy

V16 used bare `except Exception → SAFE_LEGACY`. V17 design:

1. Classify exception before fallback.  
2. Only allowlisted recoverable classes enter SAFE_LEGACY.  
3. Unknown / programming / contract → BLOCK.  
4. No recursive fallback on fallback failure (Track C).
