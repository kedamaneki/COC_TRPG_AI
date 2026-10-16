# 評価器v2 Checkpoint / Resume

## 総合判定

`EVALUATOR_V2_NEEDS_ITERATION`

評価基盤のCheckpoint・resume・segment統合と決定的な60サイクル分割試験は完了した。外部LLMを実際に呼ぶ「悪霊の家」60サイクル連続RUN Aと20+20+20 RUN Bは、モデル使用量を消費する受入試験として未実行である。実LLM試験が一致すれば`EVALUATOR_V2_STABLE`へ移行できる。

## 実装概要

- `EvaluationCheckpoint.py`を評価専用の永続化層として追加した。
- 通常のStreamlitセーブ機能とTRPGルールには変更を加えていない。
- 正式Checkpointはrunnerの1サイクルが正常に戻った直後に作成する。
- temporary directoryへ全ファイルを書き、checksum検証後にatomic renameする。
- `COMPLETE` markerのないCheckpoint、checksum不一致、version不一致は読み込まない。
- `--resume`と`--resume-latest`を追加した。
- SIGINT/SIGTERMは`SAFE_STOP_REQUESTED`として扱い、実行中サイクルが戻った後に終了する。
- segmentイベントを統合し、duplicate、gap、overlap、resume chain不一致を検出する。

## 保存対象一覧

- runner session state全文
  - ログ、active actor、pending、探索状態、Goal/Stall、public knowledge、進行状態を含む
- `CharacterManager.export_to_dict()`
  - 全PC/NPC、HP/SAN/Luck/MP、inventory、状態異常、知識、関係状態を含む
- `GameStateManager.export_to_dict()`
  - scene、turn、flags、戦闘状態、initiative/queue、pending defense、stagnation trackerを含む
- `ScenarioManager.export_to_dict()`
  - phase、location、trigger counts、scenario flags、turn counterを含む
- Python `random.getstate()`
- NumPy RNG state（NumPyが存在する場合）
- LLM `chat_history`と`chat_session`
- 評価器カウンタとmetrics snapshot
- 隔離`runtime_data`全文（PC/NPCおよび評価中に更新され得るdataset）
- Unified Event Log offsetと末尾event ID
- code/scenario/prompt/PC/KP/model/evaluation config fingerprint

## 保存漏れ調査

探索権、Goal Manager、Stall Detectorは独立managerではなくrunner session state内の`investigation_flow`と`director_v2`に存在するため、session state全文保存で維持される。戦闘は`GameStateManager`とpending session fieldsの両方を保存する。シナリオ定義自体はCheckpointに複製せずscenario hashで同一性を強制し、mutable部分だけをScenario/GameState exportで保存する。

現在の`main.py`のAI履歴は`all_events_log`から再構築可能な構造だが、評価器v2では要約・再構築せず、グローバル履歴とログ全文をそのまま保存・復元する。

## Checkpoint Schema

```text
evaluation-output/
  runtime_data/
  checkpoints/
    cycle_000020/
      manifest.json
      state.json
      COMPLETE
  segments/
    segment_001/
      segment.json
  merged/
    events.jsonl
    evaluation.json
```

`manifest.json`にはcheckpoint ID/version、session ID、seed、cycle、turn、scene/location、各fingerprint、RNG/LLM/evaluator state存在フラグ、event offset、checksum、作成時刻、complete marker状態、pending警告を記録する。

## Resume Flow

1. 完全なCheckpointだけを選択する。
2. checksumとversionを検証する。
3. seed、scenario、source、prompt、PC、KP、model、evaluation configを照合する。
4. 不一致があれば`RESUME_BLOCKED`として終了する。
5. 隔離`runtime_data`をCheckpoint時点へロールバックする。
6. Character/Game/Scenario stateをロードして再bindする。
7. RNGとLLM履歴を復元する。
8. 評価器カウンタとevent offsetを復元する。
9. ゲーム状態には中断イベントを混入させず、評価用segment streamへ`EVALUATION_RESUMED`を記録する。
10. Checkpoint直後のcycleから続行する。

## 実行方法

初回20サイクル：

```powershell
cd "F:\制作物\その3\src"
..\.venv\Scripts\python.exe run_investigation_evaluation.py `
  --scenario scenario_corbitt.json `
  --seed 2101 `
  --max-cycles 60 `
  --segment-cycles 20 `
  --session-id HAUNTED_2101_V2 `
  --output "..\evaluation-v2\seed_2101"
```

2回目と3回目：

```powershell
..\.venv\Scripts\python.exe run_investigation_evaluation.py `
  --scenario scenario_corbitt.json `
  --seed 2101 `
  --max-cycles 60 `
  --segment-cycles 20 `
  --output "..\evaluation-v2\seed_2101" `
  --resume-latest
```

`--max-cycles`は全segment共通の最終目標なので60のまま変更しない。1プロセスで実行する量だけを`--segment-cycles`で指定する。

特定Checkpointから再開する場合：

```powershell
..\.venv\Scripts\python.exe run_investigation_evaluation.py `
  --scenario scenario_corbitt.json `
  --seed 2101 `
  --max-cycles 60 `
  --segment-cycles 20 `
  --output "..\evaluation-v2\seed_2101" `
  --resume CHECKPOINT_CYCLE_000020
```

## RNG復元結果

Checkpoint保存直後に生成した次の8乱数と、別managerへロード後に生成した8乱数が完全一致した。

## LLM履歴復元結果

`chat_history`と`chat_session`のsave/reset/load一致テストに成功した。自然言語自体の外部モデル非決定性はこのテストの対象外である。

## Segment統合結果

- event IDによる重複除去：PASS
- cycle gap検出：PASS
- overlap検出ロジック：実装済み
- resume checkpoint chain検証：実装済み
- merged JSONL/evaluation JSON生成：PASS

## Unit Test

`test_evaluation_checkpoint.py`の9件が成功した。

- save/load主要状態
- RNG
- evaluator counters
- Attempt Rights
- Goal/Stall state
- LLM history
- event offset/ID
- incomplete/corrupt checkpoint拒否
- code/prompt/model/seed mismatch BLOCK
- duplicate/gap検出

## Integration Test

- 10連続 vs 5 + resume + 5：一致
- 60連続 vs 20 + resume + 20 + resume + 20：一致

比較対象にはstate全文、dice history、flags、metrics、RNG progressionを含む。評価用event IDだけはゲーム挙動に影響しないmetadataとして比較前に除外した。

## 既存テスト

全513件を実行した。510件成功、既知FAIL 3件、error 0件。3件は過去の保存済みfull-testログでも同じテスト名・同じ件数で失敗しており、今回の変更による新規回帰は0件。

既知FAIL：

- `test_autosave_tail_invariants`
- `test_legacy_autosave_search_is_enqueued_once`
- `test_15_old_save_load_continues_without_bulk_replay`

## 残存問題

- 実LLMを使う悪霊の家RUN A/RUN Bは未実行。
- 標準シナリオの実runnerスモークではcycle 1のCheckpoint作成と`PAUSED_RESUMABLE`終了に成功した。別プロセスの`--resume-latest`は同Checkpointを検出・検証・復元後、cycle 2のLLM待機へ進んだ。待機中に強制停止し、cycle 1の正式Checkpointが維持され、未完了cycle 2が正式Checkpoint/segmentとして公開されないことを確認した。
- 外部モデルの文章差が状態差へ波及した場合の分類は、現在はfingerprintと最終状態比較を基に人間が`TEXT_DIVERGENCE_ONLY`または`BEHAVIORAL_DIVERGENCE`と判定する必要がある。
- `.venv-new`は現在、存在しない別ユーザーのPython 3.12パスを参照している。今回の検証は動作する`.venv`（Python 3.14.3）で実施した。

## 次工程判定

決定的な基盤試験は`RESUME_EQUIVALENCE_PASS`。ただし実LLMによる60サイクルA/Bが未完了なので、現時点の総合判定は`EVALUATOR_V2_NEEDS_ITERATION`とする。実評価完了後、状態・メトリクス一致とsegment issue 0を確認できれば`EVALUATOR_V2_STABLE`へ更新する。
