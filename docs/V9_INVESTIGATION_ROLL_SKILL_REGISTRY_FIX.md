# V9 Investigation ROLL / Skill Registry Fix

## Frozen source

- Session: `CORBITT_LONGRUN_ITERATION3_V9_HOME_001`
- Disposition: `STOPPED_FORMAL_CONTRACT_ERROR_UNAUDITED`
- Last complete checkpoint: `CHECKPOINT_CYCLE_000008` (Cycle 8 / Turn 20)
- Checkpoint location: `corbitt_ground_floor`
- Frozen source: 128 files
- Expected aggregate SHA-256: `4f5ebeb63a3fcc2d6b0a96d71ffbdedb2f276687c69e5bb6bbea6b114fed1ba2`
- Resume, backfill, Raw edit, and same-session rerun were not performed.

The process continued transiently into Cycle 9 and failed while committing an
`INVESTIGATION_ROLLED` event.  The exception was correctly raised by
`AdjudicationEvidence.validate_evidence`: `target_value`, `roll`, and
`raw_result` were absent.  The failed action payload was not durably committed,
so its actor/action/target cannot be asserted from the frozen Raw as historical
facts.  LLM metrics prove calls through Cycle 9 / Turn 22, but intentionally do
not store response content.

## Boundary trace and classification

The deterministic historical fixture follows the failing producer path:

1. Scenario investigation selects `basement_planks` and canonical roll
   identifier `STR`.
2. The old producer treats every identifier as a skill and calls
   `CharacterManager.get_skill(actor, "STR")`.
3. `STR` is an attribute, not a `BASE_SKILLS` entry, so the old lookup returns
   the undefined-skill sentinel `0` even though the actor has STR 55.
4. `DiceEngine.execute_skill_roll` returns an error before producing the dice
   tuple.
5. The action remains classified as `ROLL`; the transient evidence therefore
   has no target, roll, or raw result.
6. `finalize_investigation` reaches the commit boundary and fails closed.

`FIRST_MISSING_BOUNDARY` is the scenario-selected roll identifier to
CharacterManager value-resolution boundary, before the Dice Engine call can
produce a tuple.

Root-cause classification: **`SKILL_CANONICALIZATION_GAP`**.

This is distinct from the V5 medicine defect.  The selected identifier exists
and the actor value exists; the defect is that the producer did not distinguish
characteristics from skills.

## Minimal production fix

- Add a central roll-identifier registry that classifies CoC characteristics,
  canonical skills, and explicit aliases.
- Resolve `STR/CON/DEX/APP/POW/SIZ/INT/EDU` through `get_attribute` and skills
  through `get_skill`.
- Distinguish an undefined name from a registered legal value of zero.
- Pass the resolved identity through normal and pushed investigation rolls.
- Do not mark characteristic rolls for skill growth.
- Add the missing standard CoC base entry `オカルト=5`, which is referenced
  by the authoritative scenario.

The Evidence Contract was not relaxed.  Undefined rolls still fail closed;
there is no ROLL-to-NO_ROLL downgrade and no downstream reconstruction.

## Deterministic acceptance

- Historical fixture: old resolver reproduces the exact incomplete-ROLL
  `EvidenceContractError` without reading or changing V9 Raw.
- Patched fixture: the same `STR` investigation resolves target 55, rolls 44,
  retains raw result and adjudication id, and commits exactly one
  `INVESTIGATION_ROLLED` event.
- Registry audit: every registered skill and all eight characteristics, for
  every PC, execute lookup -> target calculation -> Dice Engine -> Formal
  evidence builder and validate as a complete ROLL.
- Legal zero and undefined identifiers are covered separately.

Required audit metrics:

- `scenario_skill_unresolved=0`
- `skill_alias_ambiguous=0`
- `dice_unsupported_skill=0`
- `invalid_skill_default=0`
- `rollable_skill_contract_failure=0`

The full machine-readable audit is stored outside Raw under the V9 evaluation
control directory as `V10_SKILL_REGISTRY_AUDIT.json`.

## Acceptance state

V9 remains historical failed evidence and `VIDEO_SOURCE_ELIGIBLE=false`.
V10 may be allowed only after the complete Core, Video, Auditor, night/runtime,
focused regression suites and the post-work V9 custody hash all pass.
