# V17 Progress Telemetry Implementation Report

**PROGRESS_TELEMETRY_WIRING = PASS**  
**PROGRESS_EVENTS_WIRED = true**

## Modules

- `reasoning/progress_events.py` — ProgressEvent factory + director delta emit + NDM buffer read
- `ProgressDirectorV2.record_unified_turn` — emits on progress_delta / flags / knowledge / requirements
- `ndm_integration.enrich_pc_action_with_ndm` — passes `progress_events_for_ndm(state)` into `rt.decide`

## Metrics non-null

`rates()` always returns floats for:

- UNEXPLAINED_ACTION_RATE  
- UNRESOLVED_LEAD_ABANDON_RATE  
- SELF_RECOVERY_RATE  
- MEANINGFUL_PROGRESS_RATE  

Smoke: `MEANINGFUL_PROGRESS_RATE = 1.0`, `PROGRESS_EVENT_COUNT = 1`.
