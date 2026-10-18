# CORBITT_KNOWN_GOOD_BASELINE_V13

- Baseline ID: `CORBITT_KNOWN_GOOD_BASELINE_V13`
- Session: `CORBITT_LONGRUN_ITERATION3_V13_HOME_001`
- Accepted run commit: `7e22972166a65539614e020e729e0baaefbca672`
- Preflight tag: `v13-preflight-accepted`
- Full-run acceptance tag: `v13-full-long-accepted`
- Scenario / PCs / NPCs SHA-256: `b6f0559ffca677b57bc3a69c16991bb24c483d30256cb6dfd30fc938ebd84ed7` / `f47bb03ff6406c228dd7c88f94c597d6e28785b47c6e0afe1322b7596c31c3dd` / `3c795e6098f97ae8e6240b9ed2412428ab332c91c30a1cb45b846d2f4628377c`
- Model: `qwen2.5:14b` (`PASS` input identity)
- Execution profile: `SINGLE_PC`
- Raw aggregate SHA-256: `fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d`
- Formal Auditor: `2.0.0` / `858b33c80d73c940ca2c8e9e6c5b63d34bb6e792e29307ed438fc2169f86608e`
- Formal Normalizer implementation SHA-256: `05d9b8f15680ff43b1c39b0731305cc2d93720231b1bcaa276e299c37bfdc2ea`
- Video source eligible: `true`

Known-Good means this run passed every current Formal Contract and gate. It does not assert that the run is ideal or erase historical defects. V8 actor contradiction, V9 Investigation ROLL failure, V10 formal blockers, V11 goal-sync failure, and V12 basement stagnation remain immutable negative references.

Future regression must preserve V13 evidence hashes and keep the V13 reference PASS. A new accepted run becomes a new candidate and does not delete V13.

## Accepted invariants

- Complete/clear completion envelope and atomic Special Objective synchronization.
- Complete ROLL/NO_ROLL evidence, Session ROLL evidence, canonical dice identity, and Skill Registry resolution.
- Pure combat lifecycle and terminated combat.
- Exact lifecycle relation/actor pairing.
- EventIdentity completeness and segment coverage `1.0`.
- Normalizer traceability `1.0`, dropped events `0`, legacy text parse `0`.
- Auditor Critical/Major/Blocking `0/0/0`.
- Raw hash stable before and after formal processing.

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
