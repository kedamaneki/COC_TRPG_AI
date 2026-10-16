# Long Autonomous Iteration 2 Fix Report

## Result

- `LONG_AUTONOMOUS_ITERATION2_FIX = PASS`
- `FULL_LONG_AUTONOMOUS_RUN = NOT_STARTED`
- `VIDEO_SOURCE_ELIGIBLE = false`

Iteration 2の前段ゲートを、Unit、Deterministic Integration、Mini Autonomous Runの順で実行した。すべてPASSした。旧runは変更していない。Full Long Autonomous Runは本判定の対象外であり、まだ開始していない。

## Repository State Review

この作業フォルダーにはGit管理情報がないため、commit差分による判定はできない。現存する実装、テスト、評価成果物を照合して状態を確定した。

Iteration 2の実装済み範囲:

- examineとmutationの分離
- ROLL / NO_ROLL契約とadjudication ID伝播
- opposed rollの双方tuple
- mandatory SAN effectのdispatch
- SAN snapshotとadjudicationの分離
- result canonicalizationとLuck phase分離
- Corbitt knife object lifecycle
- Final BattleのSPECIAL_OBJECTIVE維持
- evaluation input manifestとhash記録

今回の開始時点で未完了だった範囲:

- 現コードでの全Unit再実行
- 決定論的受入ゲートの再実行
- 接続可能なOllamaを使った有効なMini Autonomous Run
- 上記3ゲートを統合したIteration 2正式判定

既存実装を作り直さず、この未完了範囲だけを実行した。

## Gate 1: Unit

- Python: 3.14.3
- tests: 549
- failures: 0
- errors: 0
- result: `PASS`
- evidence: `outputs/latest_log_tests.txt`

## Gate 2: Deterministic Integration

- Iteration 2 dedicated tests: 12
- failures: 0
- errors: 0
- result: `PASS`
- acceptance artifact: `evaluation-v2/corbitt_iteration2_deterministic_001/iteration2_acceptance.json`

検証対象はdoor/wallのexamine整合、mandatory SAN dispatch、opposed roll completeness、knife lifecycle、Final Battle narrative grounding、SAN snapshot除外、Normalizer canonicalizationである。

決定論的受入指標:

- `NARRATIVE_STATE_CONTRADICTION = 0`
- `ROLL_CONTRACT_INCOMPLETE = 0`
- `MANDATORY_SAN_EFFECT_DROPPED = 0`
- `SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK = 0`
- `NORMALIZATION_SOURCE_CONTRADICTION = 0`
- `OBJECT_STATE_INVALID_TRANSITION = 0`
- `OBJECT_NARRATIVE_STATE_CONTRADICTION = 0`
- `UNGROUNDED_NARRATIVE_OPTION = 0`

## Gate 3: Mini Autonomous Run

- session: `CORBITT_ITERATION2_MINI_003`
- seed: 2204
- model: local Ollama `qwen2.5:14b`
- cycles: 5 / 5
- turns: 4
- unified events: 24
- human intervention: 0
- pause: none
- segment merge: PASS
- duplicate events: 0
- merge issues: 0
- input identity: PASS
- result: `PASS`

実行はintroductionからinvestigationへ進み、`boston_globe`を経由して`central_library`へ到達した。ROLL契約を持つ6イベントが生成され、全イベントで次の必須値を保持した。

- adjudication_id
- actor
- target
- skill_or_stat
- target_value
- roll
- raw_result
- final_result

Mini Run内の`ROLL_CONTRACT_INCOMPLETE`は0である。状態変更は`knott_letter_read: false -> true`と`case_accepted: false -> true`として記録され、Narrativeと一致した。

SAN、knife lifecycle、Final Battleは5 cycle内では発火しなかった。この3経路はDeterministic Integrationで実行済みであり、Mini Runで未発火だった事実を成功扱いへ読み替えてはいない。

## Acceptance Gate

- `NARRATIVE_STATE_CONTRADICTION = 0`
- `ROLL_CONTRACT_INCOMPLETE = 0`
- `MANDATORY_SAN_EFFECT_DROPPED = 0`
- `SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK = 0`
- `NORMALIZATION_SOURCE_CONTRADICTION = 0`
- `OBJECT_STATE_INVALID_TRANSITION = 0`
- `OBJECT_NARRATIVE_STATE_CONTRADICTION = 0`
- `UNGROUNDED_NARRATIVE_OPTION = 0`

## Next Gate

Full Long Autonomous Re-evaluation v2を実行できる前提は揃った。ただし本レポート作成時点では開始していない。Full Long Runが正式PASSするまでは`VIDEO_SOURCE_ELIGIBLE = false`を維持する。

学校PCに正式映像素材がないことは本判定に影響させておらず、M3の素材要件や正式仕様も変更していない。
