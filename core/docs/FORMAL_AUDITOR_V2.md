# Full Session Evidence Auditor v2

## 判定

- `FORMAL_AUDITOR_V2 = PASS`
- `VIDEO_SOURCE_ELIGIBLE = false`
- 停止中の `CORBITT_LONGRUN_ITERATION2_V2_001` にはFormal Auditを実行していない。

## 実装identity

- Auditor v2: `tools/audit_longrun_formal_v2.py`
- Version: `2.0.0`
- Schema: `2.0`
- SHA-256: `8499ba51693e6b0f52dc94c2a19b4ef2243c9b819d2d66d0c789ce8bafd3f902`
- Legacy Auditor: `tools/audit_longrun_post_adjudication.py`
- Legacy SHA-256: `24fe6187cf01f8b27340274c642712f0277ae9973917a787d979a6a72823499d`
- Formal Normalizer SHA-256: `12be34604d1977a2cbbe3e71622e6b8622fa0c8baf7f874394c79e046fc9f3bd`

Legacy Auditor原本は変更していない。

## 変更内容

Auditor v2はSession IDを入力成果物から取得する。コード中に旧Runまたは現行RunのSession IDを持たない。

Checkpointは `--checkpoint` で明示できる。未指定時は `COMPLETE`、`manifest.json`、`state.json`、`runtime_data` が揃い、manifestがcompleteであるcheckpointから、cycleと作成時刻で最終有効checkpointを選ぶ。

`--output-dir` は必須で、Raw Run、normalized input、その親ディレクトリ配下を指定すると `RAW_RUN_PATH_GUARD` で停止する。Auditorは入力側へファイルを複製・保存しない。

Raw Runが未完走の場合は `RUN_INCOMPLETE` で停止し、Formal PASS/FAILを出さない。

## 監査範囲

従来分類を維持した。

- `SOURCE_CONTRADICTION`
- `SOURCE_GAMEPLAY_GAP`
- `SOURCE_LOGGING_GAP`
- `SOURCE_NARRATIVE_GAP`
- `NORMALIZATION_GAP`
- `ROLL_CONTRACT_INCOMPLETE`
- `COMBAT_WITHOUT_TERMINATION`
- `NORMALIZATION_SOURCE_CONTRADICTION`

Iteration 2分類を追加した。

- `MANDATORY_SAN_EFFECT_DROPPED`
- `SAN_SNAPSHOT_MISCLASSIFIED_AS_CHECK`
- `OBJECT_STATE_INVALID_TRANSITION`
- `OBJECT_NARRATIVE_STATE_CONTRADICTION`
- `UNGROUNDED_NARRATIVE_OPTION`

さらに、ROLL/NO_ROLL契約、opposed roll双方のtuple、Luck raw/final phase、SAN lifecycle、Core `ObjectLifecycle.py` と同じ遷移graph、combat termination、final special objective、goal completion同期、Normalizer validation、traceability 1.0、input identity、legacy text parseをgate化した。

各findingはfinding ID、category、classification、severity、message、source event IDs、normalized event IDs、adjudication ID、checkpoint、cycle、evidence state、evidenceを保持する。

## 出力

指定した新規output directoryへ次を生成する。

- `FULL_SESSION_EVIDENCE_AUDIT.md`
- `full_session_evidence_audit.json`
- `audit_manifest.json`

manifestはSession、Auditor/Normalizer/Normalized/Raw logsのSHA-256、checkpoint、Legacy project、開始・終了時刻を保持する。Auditorは `VIDEO_SOURCE_ELIGIBLE=true` を設定しない。

## テスト結果

- Auditor v2専用: 19 PASS / 0 FAIL
- Video Production Agent全体: 182 PASS / 0 FAIL
- py_compile: PASS
- Existing Iteration 2 deterministic acceptance: PASS
- 新5分類negative fixtures: PASS
- 新5分類false-positive fixture: PASS
- Luck raw/final phase regression: PASS
- incomplete Raw Run rejection: PASS
- output guard: PASS

旧正式Run `CORBITT_LONGRUN_POST_ADJUDICATION_FIX_001` を、既存Formal Normalizerのread-only出力と新規output directoryで再監査した。結果は `NEEDS_ITERATION`、`VIDEO_SOURCE_ELIGIBLE=false`、traceability 1.0で、ROLL契約欠落、Normalizer source contradiction、completion/objective同期不整合を再検出した。旧Run原本へは書き込んでいない。

## 次回学校PCでのコマンド

Raw Run完走後、原本ではなくanalysis staging copyとFormal Normalizerの新規出力を使用する。

```powershell
$env:PYTHONPATH = "src"

python tools\audit_longrun_formal_v2.py `
  --core-run "<completed-analysis-staging-run>" `
  --normalized "<normalizer-output>\normalized_session.json" `
  --provenance "<normalizer-output>\provenance_report.json" `
  --validation "<normalizer-output>\validation_report.json" `
  --normalizer-implementation "src\video_agent\normalizer\session.py" `
  --legacy-project "projects\corbitt_clear_001" `
  --output-dir "<new-audit-output>"
```

特定checkpointを指定する場合は `--checkpoint CHECKPOINT_...` またはcheckpoint pathを追加する。

## 既知の制限

- `UNGROUNDED_NARRATIVE_OPTION` とobject narrative contradictionのFormal検出は、`narrative_options`、`narrative_claims`、`narrative_fact_tags` 等の構造化証拠を対象とする。自由文だけをLLM的に推測してFormal findingにはしない。
- 旧Runは現行契約導入前のため、Auditor v2では旧Auditorより多くのROLL契約欠落を列挙する。finding減少を改善とは扱わない。
- Auditor PASSは上位のLegacy ComparisonとFormal runner判定を代替しない。
