# V17 RecentAction Canonical Schema Design

**Track A**  
**Status:** COMPLETE  
**NDM_ALGORITHM_CHANGE_PLANNED:** false

## Premises (from V16 audit)

- StallDetector produced `recent_actions` as `[action, target]` lists.
- NDM / SAFE_LEGACY consumers called `.get("action")` / `.get("target")`.
- Result: `AttributeError: 'list' object has no attribute 'get'` ×194.

## Canonical type

```text
RecentAction {
  schema_version: int          # currently 1
  actor_id: str                # may be "" if unknown at stall time
  action: str                  # required, non-empty for scored entries
  target: str                  # required key; may be ""
  location: str                # optional; "" if unknown
  cycle: int | null
  turn: int | null
  result: str | null           # coarse outcome hint; not adjudication
  source_event_id: str | null
}
```

**Identity field:** `recent_action_schema_version` (= `schema_version`) must be present on every canonical instance written to runtime/telemetry.

### Required vs optional

| Field | Required |
|---|---|
| schema_version | yes (=1) |
| action | yes |
| target | yes (key present; empty string allowed) |
| actor_id | yes (key present; empty string allowed) |
| location | no (default "") |
| cycle / turn | no (default null) |
| result / source_event_id | no (default null) |

## Single schema rule

`RECENT_ACTION_MULTI_SCHEMA_PATH = 0` (design target).

The following **must** consume only canonical `RecentAction` (or sequences thereof):

- StallDetectorV2 (producer writes canonical)
- Natural Decision pipeline / runtime
- SAFE_LEGACY_PROGRESSION filter/select
- repetition scoring / KP assess recent window
- location-loop / stall signal helpers that read recent actions
- NDM telemetry aggregators
- Auditor/Normalizer adapters that inspect recent actions (read-only)

**Forbidden:** consumer-local `if isinstance(x, list): ...` legacy branches.

## Legacy adapter (boundary only)

```text
legacy input
  [action, target]
  or (action, target)
  or {"action","target"} without schema_version
        │
        ▼
RecentActionNormalizer.normalize(raw) -> RecentAction | ContractViolation
        │
        ▼
canonical RecentAction (schema_version=1)
```

### Normalization rules

| Input | Result |
|---|---|
| list/tuple length 2 of strings (or stringifyable) | RecentAction(action=s0, target=s1, schema_version=1, others default) |
| dict with schema_version==1 and required keys | validate + pass-through (fill defaults) |
| dict with action/target but no schema_version | treat as legacy dict → stamp schema_version=1 |
| unknown list length / nested structures | **RUNTIME_CONTRACT_VIOLATION** |
| missing required field / wrong type | **RUNTIME_CONTRACT_VIOLATION** |
| schema_version != 1 unsupported | **RUNTIME_CONTRACT_VIOLATION** |

Historical V13–V16 Raw: **not migrated**. Read-only adapters may normalize at read time for audits; production runtime never writes legacy list shape after V17.

## Producer change (design)

`StallDetectorV2.update` must append:

```text
{
  "schema_version": 1,
  "actor_id": <available or "">,
  "action": str,
  "target": str,
  "location": location_after or "",
  "cycle": null or known,
  "turn": null or known,
  "result": null,
  "source_event_id": null
}
```

Bounded window (e.g. last 8) unchanged in policy; only element shape changes.

## Validation call sites (design)

1. **Ingress to NDM decide:** normalize+validate entire `recent_actions` sequence before `pipeline.run_cycle`.  
2. **SAFE_LEGACY entry:** re-validate (must already be canonical; violation → not recoverable).  
3. **StallDetector write:** emit only canonical (no legacy write path).

Malformed → `NDM_RUNTIME_CONTRACT_VIOLATION` (see Runtime Contract Violation Policy). **Never** SAFE_LEGACY.

## Versioning

- `recent_action_schema_version = 1` for V17.
- Future versions require explicit adapter; unsupported version = contract violation (first occurrence block).

## Migration judgment

`RUNTIME_SCHEMA_MIGRATION_REQUIRED = true` for **live runtime state shape** (stall.recent_actions element type).  
`HISTORICAL_RAW_MIGRATION = forbidden`.
