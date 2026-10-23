# V17 RecentAction Schema Implementation Report

**RECENT_ACTION_CANONICAL_SCHEMA = PASS**  
**RECENT_ACTION_SCHEMA_VERSION = 1**  
**LEGACY_RECENT_ACTION_ADAPTER = PASS**  
**NEW_WRITE_FORMAT = CANONICAL_ONLY**

## Modules

- `core/src/reasoning/recent_action.py` — `RecentAction`, `normalize_recent_action(s)`, `make_recent_action`
- `ProgressDirectorV2.StallDetectorV2.update` — writes canonical dicts only
- `ProgressionPolicy` — reads via adapter → pair for scoring
- `kp_assessment` / `safe_fallback` — normalize before `.get`

## Behavior

| Input | Result |
|---|---|
| `[action, target]` | adapter → canonical |
| canonical dict v1 | PASS |
| malformed list | `RecentActionContractError` → runtime BLOCK |

Historical Raw not rewritten.
