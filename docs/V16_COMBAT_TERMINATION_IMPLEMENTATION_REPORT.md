# V16 Combat Termination — Implementation Report

## Policy

`CORBITT_FINAL_BATTLE_TERMINATION_POLICY = VALIDATED_KILL_ONLY`

## Required chain

```text
VALIDATED_KILL
→ CORBITT_DEFEATED_STATE_COMMITTED
→ SPECIAL_OBJECTIVE_COMPLETED
→ COMBAT_ENDING
→ TERMINATION_CONTRACT_VALIDATED
→ COMBAT_ENDED
```

Module: `core/src/CombatTerminationContract.py`

## Fail-closed

- `living<=1` on Corbitt boss does not `end_combat` without chain
- BossPolicy none / no-target → `NO_ACTION_THIS_TURN` (no auto end)
- CN1–CN5, CN7, CT9–CT15 covered in `test_v16_ndm_causal_and_combat.py`
