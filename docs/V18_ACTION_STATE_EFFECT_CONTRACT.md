# V18 Action → State Effect Contract

**ACTION_STATE_EFFECT_CONTRACT = COMPLETE**

## V17 problem (generalized)

```text
same target searched repeatedly (e.g. basement_planks ×10)
→ examined/broken-like flags never advanced
→ ACTION_TO_STATE_EFFECT_GAP
```

Design addresses **generic** expected vs observed effect tracing — not a Corbitt hard-code.

## Expected State Effect

Each action candidate may declare:

```text
expected_state_effect
  effect_id
  description
  target_state_keys[]     # opaque keys known to scenario/runtime
  success_not_guaranteed  # always true semantically
```

Expected effect is a **hypothesis**, not a promise.

## Observed State Effect

After execution:

```text
observed_state_effect
  effect_id_or_null
  changed_keys[]
  classification
```

## Effect classification

```text
EXPECTED_EFFECT_ACHIEVED
PARTIAL_EFFECT
NO_EFFECT
UNEXPECTED_EFFECT
ACTION_FAILED_BEFORE_EFFECT
```

Every committed action must produce a classification (`ACTION_WITHOUT_STATE_EFFECT_TRACE_PATH = 0`).

## Repeated no-effect policy

Same frontier + same method class + repeated `NO_EFFECT`:

Consider (soft, ordered):

```text
method exhausted
different method
different PC
tool needed
new information needed
```

Update frontier availability reasons (`ACTION_EXHAUSTED` / `TOOL_REQUIRED` / `INFO_REQUIRED`) rather than infinite identical retries with silent non-progress.

## Link to progress classes

| Classification | Typical progress |
|---|---|
| EXPECTED / PARTIAL on GD-linked frontier | Goal-Directed (+ Meaningful) |
| NO_EFFECT | Meaningful only if other side effects; else none |
| UNEXPECTED | Meaningful; GD iff links visible goals/leads |

## Anti-patterns forbidden

- Hard-coding specific target IDs to force flag updates in NDM
- Treating missing expected effect as “player failed the correct route”
- Using future ending proximity as effect success criterion
