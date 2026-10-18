# V13 Final Acceptance Report

## Final disposition

- `SOURCE_SESSION = CORBITT_LONGRUN_ITERATION3_V13_HOME_001`
- `V13_FINAL_DISPOSITION = ACCEPTED`
- `FULL_LONG_RAW_RUN = COMPLETED`
- `FULL_LONG_AUTONOMOUS_REEVALUATION = PASS`
- `V13_KNOWN_GOOD_CANDIDATE = true`
- `VIDEO_SOURCE_ELIGIBLE = true`

V13 is the first accepted reference run under the current Formal Evidence, lifecycle relation, skill registry, progression frontier, completion atomicity, Normalizer, and Auditor v2 contracts. Acceptance does not rewrite or supersede historical V8–V12 failures.

## Run identity

- Session: `CORBITT_LONGRUN_ITERATION3_V13_HOME_001`
- Seed: `2101`
- Execution profile: `SINGLE_PC`
- Routing: `PL/KP/JUDGE -> PRIMARY`
- Model: `qwen2.5:14b`, family `qwen2`, `14.8B`, `Q4_K_M`
- Model digest: `7cdf5a0187d5c58cc5d369b255592f7841d1c4696d45a8c8a9489440385b22f6`
- Resume count: `0`
- Migration: `null`
- Runtime PID: `9564`

## Git identity

- Run commit: `7e22972166a65539614e020e729e0baaefbca672`
- Run branch: `main`
- Run preflight tag: `v13-preflight-accepted`
- Run worktree: clean
- Full-run acceptance tag: `v13-full-long-accepted` on the acceptance metadata commit

The preflight tag identifies the code admitted to the run. The full-run tag identifies the later commit that records accepted evidence without changing that code or the Raw run.

## Input identity

- Gate: `PASS`
- Scenario SHA-256: `b6f0559ffca677b57bc3a69c16991bb24c483d30256cb6dfd30fc938ebd84ed7` (`EXACT`)
- PCs SHA-256: `f47bb03ff6406c228dd7c88f94c597d6e28785b47c6e0afe1322b7596c31c3dd` (`EXACT`)
- NPCs SHA-256: `3c795e6098f97ae8e6240b9ed2412428ab332c91c30a1cb45b846d2f4628377c` (`EXACT`)

## Completion

- Final cycle / turn: `25 / 65`
- `completed=true`, `phase=clear`
- `corbitt_defeated=true`
- `special_objective_evidence=true`
- `scenario_goal_completed=true`
- `goal_completion_synchronized=true`
- `combat_state=INACTIVE`
- `completion_atomicity_gate=PASS`
- Completion contradictions: `0`

## Early Gate

Cycle 5 / Turn 6 passed Formal Smoke, Segment, Input Identity, Lifecycle Relation, Skill Registry, Session ROLL Evidence, Combat Lifecycle Purity, Dice Identity, Completion Atomicity, executable frontier, and S4 recovery gates. Traceability and segment coverage were `1.0`; dropped events, duplicate lifecycle events, lifecycle contradictions, ROLL gaps, and runtime errors were all `0`.

## Progression

- First basement arrival: Cycle `10` / Turn `23`
- Final completion: Cycle `25` / Turn `65`
- Maximum no-progress streak: `7`
- Maximum progression intervention: `S4`
- `basement_planks` was resolved by the accepted S4-bound push route; final state is examined and broken.
- No `PROGRESSION_STAGNATION_UNRESOLVED`, frontier false positive, binding violation, or recovery contract violation survived the final gates.

## Final Raw Gates

- Segment missing / duplicate / unexpected: `0 / 0 / 0`
- Segment coverage: `1.0`
- Event ID missing / duplicate: `0 / 0`
- Raw offset missing: `0`
- Lifecycle relation missing / ambiguous / unmatched / contradictory: `0 / 0 / 0 / 0`
- Lifecycle actor contradiction: `0`
- Skill Registry unresolved / ambiguous / unsupported / invalid default / contract failure: `0 / 0 / 0 / 0 / 0`

## Formal Normalizer

- Validation: `PASS`
- Traceability: `1.0`
- Dropped events: `0`
- Legacy text parse: `0`
- Normalized event count: `617`
- Normalizer implementation SHA-256: `05d9b8f15680ff43b1c39b0731305cc2d93720231b1bcaa276e299c37bfdc2ea`

## Formal Auditor v2

- Status: `PASS`
- Version: `2.0.0`
- Implementation SHA-256: `858b33c80d73c940ca2c8e9e6c5b63d34bb6e792e29307ed438fc2169f86608e`
- Critical / Major / Minor / Blocking: `0 / 0 / 0 / 0`
- Traceability: `1.0`

## Legacy Comparison

- Status: `PASS`
- Missing major gameplay facts: `0`
- Fabricated facts: `0`
- Causal order preserved: `true`
- Scenario completion preserved: `true`
- Raw causal offsets: planks progress `233`, final room `264`, Special Objective `278`, completion after event log `282`.

## Raw Freeze and rehash

- Raw files: `373`
- Raw aggregate SHA-256: `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d`
- Raw rehash after audit: `PASS`
- The Raw run, checkpoints, segments, Normalizer output, Auditor output, Legacy Comparison, and acceptance receipt are immutable accepted evidence. Resume, backfill, regeneration, overwrite, and same-session rerun are prohibited.

## Baseline metrics

```json
{
  "final_cycle": 25,
  "final_turn": 65,
  "basement_first_arrival_cycle": 10,
  "basement_first_arrival_turn": 23,
  "max_no_progress_streak": 7,
  "max_intervention_level": "S4",
  "observed_intervention_levels": {
    "S2": 16,
    "S4": 8,
    "S3": 4,
    "COMBAT": 8
  },
  "llm_calls": 162,
  "llm_errors": 0,
  "llm_retries": 0,
  "llm_fallbacks": 0,
  "roll_count": 51,
  "san_count": 1,
  "push_count": 1,
  "luck_count": 0,
  "lifecycle_relation_count": 14,
  "special_objective_count": 1,
  "formal_findings": {
    "critical": 0,
    "major": 0,
    "minor": 0,
    "blocking": 0
  },
  "traceability": 1.0,
  "segment_coverage": 1.0
}
```

Performance differences are classified separately as `CORRECTNESS_REGRESSION`, `FORMAL_REGRESSION`, `PROGRESSION_REGRESSION`, `PERFORMANCE_DEGRADATION`, or `NON_BLOCKING_VARIANCE`. A one-cycle variance alone is not a correctness failure.

## Video eligibility

`VIDEO_SOURCE_ELIGIBLE=true`. Video work may use only the pinned V13 sources listed by the handoff manifests. It may change presentation, but it may not invent or alter actor, location, dialogue fact, event order, roll, SAN, combat, Special Objective, or ending facts. Source files remain read-only; derived output must use a separate output root. Auto-publish is prohibited and Human Review is required.
