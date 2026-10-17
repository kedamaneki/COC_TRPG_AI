# V6 Investigation ROLL Evidence Fix

## Frozen V5 evidence

- Session: `CORBITT_LONGRUN_ITERATION3_V5_HOME_001`
- State: `STOPPED_RUNTIME_ERROR_UNAUDITED`; no resume, backfill, or mutation
- Last complete checkpoint: `cycle_000014`, turn 38, investigation, `roxbury_sanitarium`
- Failure: Cycle 15, turn 38, immediately before `INVESTIGATION_ROLLED`
- Exception: `incomplete ROLL evidence: target_value, roll, raw_result`
- Frozen inventory: 318 files
- Pre-fix aggregate SHA-256: `07dc4033607d2bc336ab9dd9020a0c41425eab75624c29f35e6b2d5dc467eddf`

The Cycle 15 PL response and action payload were not durably committed. The directly recoverable failure context therefore keeps action, target, transaction ID, adjudication ID, and dice tuple as `MISSING`. The checkpoint does directly establish actor `pc_01` (マクガフィン刑事), location `roxbury_sanitarium`, phase `investigation`, Cycle 15 / Turn 38, and the three missing ROLL fields.

## Root cause

`ROLL_REQUIRED_MISCLASSIFICATION` is false: Roxbury's `patient_records` requires a real skill roll. `ROLL_EVIDENCE_BUILD_MISSING` and `ROLL_EVIDENCE_PROPAGATION_GAP` are also false: a complete Dice result is already converted and propagated by `_attach_adjudication_evidence`.

The first missing boundary is the Dice producer. The scenario's authoritative first allowed skill is 〈医学〉. `pc_01` has no explicit 〈医学〉 entry, and `CharacterManager.BASE_SKILLS` omitted the CoC 7e untrained Medicine base chance. `get_skill()` therefore returned 0. `DiceEngine.execute_skill_roll()` was invoked but returned its skill-zero error object without executing 1D100 and without `target_value`, `roll`, or `success_level`. The caller retained `roll_type="skill"`, so commit correctly failed closed.

- `ROOT_CAUSE_CLASS = ROLL_EXECUTION_MISSING`
- `FIRST_MISSING_BOUNDARY = CharacterManager.get_skill("医学") -> 0; DiceEngine skill-zero early return`

## Patch

Production change is limited to `core/src/CharacterManager.py`: register the untrained 〈医学〉 base chance as 1. The roll is still executed by the existing Dice producer, and the existing evidence object is propagated unchanged. EvidenceContract, Normalizer, Auditor, Video, night_guard, runtime isolation, Scenario, PC/NPC, prompts, routing, Segment, EventIdentity, and Simple Move were not changed.

The dedicated deterministic fixture uses the frozen V5 actor/location and Roxbury patient-record contract. Before the patch it reproduced `resolution_mode=ROLL`, `skill_or_stat=医学`, and `target_value=None`. After the patch it produces one 1D100 resolution and one `INVESTIGATION_ROLLED`, retaining the same adjudication ID. Separate negative cases confirm that missing target, roll, or raw result still fails closed.

## Verification

- Dedicated V5 fixture: 6 passed + 3 subtests
- Core full suite: 588 passed + 26 subtests
- Video Agent full suite: 208 passed
- Formal Auditor gate: 24 passed
- night_guard/runtime isolation: 60 passed
- Targeted Core evidence/combat/checkpoint suite: 78 passed + 7 subtests
- Targeted Video Simple Move/Normalizer/Early Gate/formal semantics: 32 passed
- Isolated Cycle 14 input reproduction: target 1, roll 55, raw FAILURE, one `INVESTIGATION_ROLLED`, EvidenceContractError 0

All listed suites completed with 0 fail, 0 error, and 0 skip.
