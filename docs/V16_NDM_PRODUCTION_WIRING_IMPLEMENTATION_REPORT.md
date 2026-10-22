# V16 NDM Production Wiring — Implementation Report

## Path

Night Guard / `run_investigation_evaluation` → `ensure_ndm_runtime` → `enrich_pc_action_with_ndm` → executor `guard_executor_commit`.

## Contracts

- `NATURAL_DECISION_REQUIRED=true` (env default via Night Guard / evaluation)
- Init failure → `NATURAL_DECISION_INIT_FAILED` (no legacy Full-Long)
- Per-turn reasoning failure → `SAFE_LEGACY_PROGRESSION` only
- Commit fields: `reasoning_id`, `decision_source`, `candidate_set_id`, `decision_transaction_id`
- Missing bind → `UNBOUND_DECISION_COMMIT`
- StallDetectorV2 = observer when NDM active (does not write S-level)

## Smoke evidence

See `evaluation-control/CORBITT_NDM_WIRING_SMOKE_V16PRE_001/V16_PRODUCTION_SMOKE_REPORT.json`.
