# HOME_001 Runtime Failure Report

## 判定

- SESSION_ID = CORBITT_LONGRUN_ITERATION2_V2_HOME_001
- EXECUTION_PROFILE = SINGLE_PC
- FULL_LONG_RAW_RUN = RUNTIME_FAILED_CHECKPOINTED
- FULL_LONG_AUTONOMOUS_REEVALUATION_V2_HOME = NEEDS_ITERATION
- VIDEO_SOURCE_ELIGIBLE = false

## 停止地点

- 最終確定checkpoint: CHECKPOINT_CYCLE_000039
- confirmed cycle / turn: 39 / 98
- attempted cycle: 40
- phase / location: investigation / corbitt_basement
- human intervention: 0
- resume_count: 0

## Runtime failure

最終戦開始直後、CombatProgression.append_combat_event が SPECIAL_OBJECTIVE_COMPLETED を未知のcombat event typeとして拒否した。

ValueError: unknown combat event type: SPECIAL_OBJECTIVE_COMPLETED

指示に従い、Core修正、resume、自動再Runは行っていない。Cycle 40はcheckpoint確定前に停止しており、Cycle 39が最後の復元可能地点である。

## Input / Routing

- Input Identity: PASS
- Scenario: EXACT
- NPC: EXACT
- PC: DERIVED_DECLARED / INIT_GAME_SYSTEM_V1
- PL / KP / JUDGE: PRIMARY
- PRIMARY calls: 240
- SECONDARY calls: 0
- errors: 0
- retries: 0
- fallbacks: 0

## Formal stages

Runが未完走のため、Formal Normalizer、Auditor v2、Legacy Comparison、Formal gateは実行していない。

## Isolation

学校Run CORBITT_LONGRUN_ITERATION2_V2_001 のhandoff 421ファイルは全SHA-256一致を再確認し、変更していない。
