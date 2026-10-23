# V17 SAFE_LEGACY_PROGRESSION Policy

**Track C**  
**Status:** COMPLETE  
**SAFE_FALLBACK_RECURSION:** **forbidden**

## Role (narrowed)

SAFE_LEGACY_PROGRESSION exists **only** to preserve availability after **recoverable** reasoning / model / transient provider failures.

It must **not**:

- hide internal contract bugs  
- absorb AttributeError / TypeError / schema mismatch  
- recurse when the fallback path itself fails  

V16: `SAFE_FALLBACK_SAFETY = PASS`, `SAFE_FALLBACK_AVAILABILITY = FAIL` — availability failed because fallback became the primary path under a contract bug.

## Entry contract (before selecting a legacy action)

All must hold:

1. `fallback_reason` classified as recoverable (`RECOVERABLE_REASONING_FAILURE` | `INVALID_MODEL_OUTPUT` | allowed `TRANSIENT_PROVIDER_FAILURE`)  
2. Runtime contract valid: `recent_actions` already canonical-validated  
3. Candidate legality preserved (existing SafeLegacy guards remain)  
4. NDM runtime still marked active (authority does not flip to unsafe legacy)

If any fail → **do not enter** SAFE_LEGACY; emit `SAFE_FALLBACK_FAILURE` or `NDM_RUNTIME_CONTRACT_VIOLATION` and **BLOCK**.

## Dual-fault elimination (V16「二重障害」)

V16 sequence:

```text
assess AttributeError
  → pipeline except Exception
  → fallback.select(recent_actions=list-shaped)
  → second AttributeError
  → propagate / FAIL_CLOSED chaos
```

V17 rules:

| Rule | Norm |
|---|---|
| `SAFE_FALLBACK_RECURSION` | **forbidden** |
| Fallback itself throws / contract-invalid | `SAFE_FALLBACK_FAILURE` → **BLOCK** |
| Never call fallback.select with unvalidated recent_actions | validate first or pass empty canonical window only if policy allows |

Design QA: `SAFE_FALLBACK_RECURSION_PATH = 0`.

## Streak policy

Keep `fallback_streak` / `MAX_FALLBACK_STREAK` for **recoverable** failures only.

| Failure class | Streak |
|---|---|
| Recoverable | increment; exceed max → FAIL_CLOSED / BLOCK (not silent NATURAL) |
| Contract / programming | **no streak**; immediate BLOCK |

## Commit evidence (required on SAFE_LEGACY action)

```text
decision_source = safe_legacy_progression
fallback_reason
fallback_error_class          # recoverable class enum
legacy_candidate_id           # or selected candidate_id
selected_action / target
decision_transaction_id
candidate_set_id              # if available
reasoning_id                  # optional; may be fallback_* token
```

## Counters (see Counter Separation)

- Increments `SAFE_LEGACY_DECISION_COMMIT_COUNT` and `REASONING_FALLBACK_COUNT`  
- Does **not** increment `UNSAFE_LEGACY_DECISION_COMMIT_COUNT`  
- Does **not** increment `NDM_DECISION_COMMIT_COUNT`  
- Must **not** inflate a generic “LEGACY_DECISION_COMMIT” that implies unbound violation

## Relationship to causal coverage

SAFE_LEGACY commits are **eligible** in the coverage denominator (see Counter Separation) but are **not** NDM causal numerators and are **not** unsafe legacy violations.
