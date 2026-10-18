# V11 Goal Completion Sync / V12 Preflight Report

## Historical integrity

- Session: `CORBITT_LONGRUN_ITERATION3_V11_HOME_001`
- Raw files: `387 / 387`
- Expected aggregate SHA-256: `94669499d24baa38c69038587c778edacd88560c8bf4ce158163d82f223173ab`
- Before-change manifest verification: PASS
- Raw edits, backfill, checkpoint regeneration, resume, and same-session rerun: none

The current Formal Auditor reproduced exactly one historical blocker:

- finding: `goal_completion_sync`
- classification: `SOURCE_CONTRADICTION`
- severity: `CRITICAL`
- completed / clear / ending / corbitt_defeated: `true`
- active_combat / special_objective: `false`

`V11_HISTORICAL_GOAL_SYNC_FAILURE_REPRODUCED = PASS`

## First divergence boundary

The final `break / corbitt_body` adjudication exists in the Session Log and mutates
`corbitt_defeated` to true. The Scenario layer also returned `new_phase=clear`.
The Unified log stops before the successful action and contains no matching
`SPECIAL_OBJECTIVE_COMPLETED` event.

`FIRST_DIVERGENCE_BOUNDARY` is:

`special objective detection -> SPECIAL_OBJECTIVE_COMPLETED Unified emission`

The producer emitted Special Objective evidence only inside the ordinary
`combat_end && in_combat` branch. V11 resolved the objective while the combat state
was already inactive, so that branch was skipped while Scenario state still advanced
to clear.

Root-cause classification:

- `SPECIAL_OBJECTIVE_EVENT_MISSING`
- `CLEAR_COMMITTED_BEFORE_OBJECTIVE_SYNC`
- `EVENT_STATE_SPLIT_BRAIN`
- aggregate classification: `MULTIPLE_CAUSES`

The Auditor correctly derived `special_objective=false` from the missing Unified
evidence. Its rule was not relaxed.

## Core changes

The Scenario layer now defers the clear phase when a Special Objective payload is
produced. The action producer records `COMBAT_ACTION_RESOLVED` and
`SPECIAL_OBJECTIVE_COMPLETED` even for a valid finale that does not use the ordinary
attack/defence exchange. Both records retain the target, adjudication identity,
transaction identity, resolution evidence, world fact, and state transition.

The completion commit then executes in this order:

1. persist Special Objective evidence;
2. confirm combat is inactive (or terminate it through the existing active-combat path);
3. validate the completion envelope;
4. atomically publish Scenario clear and the persisted completion envelope.

Deterministic transaction identity makes repeated application idempotent.

## Completion Atomicity Gate

`COMPLETION_ATOMICITY_GATE` rejects at least these contradictions:

- `corbitt_defeated=true` with `special_objective=false`;
- `completed=true` with `active_combat=true`;
- `clear=true` with `ending=false`;
- a partially populated completed envelope.

The evaluation summary exposes:

- `scenario_goal_completed`
- `goal_completion_synchronized`
- `special_objective_evidence`
- `completion_atomicity_gate`
- `completion_state_contradictions`

These values are derived from the persisted producer evidence and completion
envelope, rather than reconstructed by the Normalizer or Auditor.

## Verification

- dedicated completion / combat fixtures: `38 passed`
- Core full suite: `615 passed + 26 subtests passed`
- Video Agent full suite: `214 passed`
- Auditor suite: `30 passed`
- Core Formal Evidence suite: `17 passed`
- Auditor/Formal combined: `47 passed`
- night_guard / runtime isolation: `60 passed`

All reported suites completed with zero failures, errors, or skips. A final full
rerun and the post-change 387-file Raw manifest verification are required immediately
before commit and tag acceptance.

