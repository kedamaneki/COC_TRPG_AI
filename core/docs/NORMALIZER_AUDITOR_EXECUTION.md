# Normalizer / Auditor 実行手順

## 回収結果

自宅PCで、過去の Video Production Agent が実際に使用した実行コードを確認した。

- Video Production Agent: `C:\Users\ri4re\Documents\Codex\2026-10-04\referenced-chatgpt-conversation-this-is-an\video-production-agent`
- Formal Normalizer CLI: `src\video_agent\cli.py` の `import-session`
- Normalizer本体: `src\video_agent\normalizer\session.py` の `normalize_session`
- import pipeline: `src\video_agent\pipeline.py` の `build_project`
- Full Long Run Evidence Auditor: `tools\audit_longrun_post_adjudication.py`
- Python要件: Python 3.11以上（自宅PC検証は Python 3.12）
- package定義: `pyproject.toml`

成果物JSONを実行ツールとして扱っていない。上記はいずれも実行可能なPythonコードである。

## 実装identity

| ファイル | SHA-256 |
|---|---|
| `src/video_agent/cli.py` | `90a061294a25bae4742397b2e5649a53cbc8ae973b1361c6a38be6038b32bb59` |
| `src/video_agent/pipeline.py` | `598d3aa56cb9513f699240146b09add6574a98f7e7f3df1e33a2571d0b69ae54` |
| `src/video_agent/importer/trpg_evaluation.py` | `8e05e604dd922d279d08d574c82d80e29533b9a22a66d2fd4c638f2e1b4312ab` |
| `src/video_agent/normalizer/session.py` | `12be34604d1977a2cbbe3e71622e6b8622fa0c8baf7f874394c79e046fc9f3bd` |
| `tools/audit_longrun_post_adjudication.py` | `24fe6187cf01f8b27340274c642712f0277ae9973917a787d979a6a72823499d` |
| `pyproject.toml` | `17fe7a7b0059dbcbc58502156602874386f8ef382fb610847d85b57107784e94` |

## Normalizer入力契約

`import-session` は入力ディレクトリから次を読む。

- `result.json`
- `session-log.json`
- `unified-event-log.json`
- `checkpoints/cycle_*/runtime_data/pcs.json`
- `checkpoints/cycle_*/runtime_data/npcs.json`
- `checkpoints/cycle_*/runtime_data/datasets/*.json`

現在のRaw Runは `session_log.json` / `unified_event_log.json` というアンダースコア名である。原本を改名せず、完走後に分析用stagingへコピーして、staging側だけを `session-log.json` / `unified-event-log.json` とする。

## Normalizerコマンド

Video Production Agentルートで実行する。

```powershell
$env:PYTHONPATH = "src"
python -m video_agent import-session `
  --input "<analysis-staging-run>" `
  --output "<new-normalizer-output>"
```

生成物は以下。

- `normalized_session.json`
- `provenance_report.json`
- `validation_report.json`
- `character_map.json`
- `source/source_manifest.json`

M3素材、外部API、音声エンジンはNormalizerに不要である。`config/` と `assets/manifest.json` はschema validationに必要なので分析bundleに含める。

## Evidence Auditor入力契約

```powershell
python tools\audit_longrun_post_adjudication.py `
  --core-run "<auditor-staging-run>" `
  --normalized "<new-normalizer-output>\normalized_session.json" `
  --legacy-project "<video-agent-root>\projects\corbitt_clear_001" `
  --report "<new-auditor-output>\FULL_SESSION_EVIDENCE_AUDIT.md"
```

必要ファイルは、Core stagingの `result.json`、`session-log.json`、`unified-event-log.json`、checkpoint、runtime data、Normalizer出力、Legacy projectの `normalized_session.json`、`adjudication_evidence_report.json`、`adjudication_gap_report.json`、`provenance_report.json` である。

Auditorは `core-run` 直下へ `normalized_session.json`、`pcs.json`、監査JSON等を保存する。このため、**Raw Run原本を `--core-run` に指定してはいけない**。必ずRunの隔離コピーを指定する。

## 自宅PCでのread-only検証

旧Session `CORBITT_LONGRUN_POST_ADJUDICATION_FIX_001` をCドライブの一時領域へ複製して実行した。

- Normalizer launch: PASS
- input accepted: PASS
- validation: PASS
- normalized events: 846
- provenance traceability: 1.0
- Auditor launch: PASS
- normalized input accepted: PASS
- report generated: PASS
- 旧Session原本388ファイルの検証前後SHA-256: 全件一致
- Raw Run `CORBITT_LONGRUN_ITERATION2_V2_001`: 実行対象外、未変更
- 検証出力: `normalizer-auditor-validation/`

旧Session監査が `NEEDS_ITERATION` / `VIDEO_SOURCE_ELIGIBLE=false` を返すことは、既知の旧Run問題を再検出した結果であり、ツール起動失敗ではない。

## Formal Auditor v2

旧AuditorはSHA-256 `24fe6187cf01f8b27340274c642712f0277ae9973917a787d979a6a72823499d` のまま保全した。現行Full Session対応版は別実装 `tools/audit_longrun_formal_v2.py` として追加済みである。

- Auditor v2 SHA-256: `8499ba51693e6b0f52dc94c2a19b4ef2243c9b819d2d66d0c789ce8bafd3f902`
- 固定Session ID: なし
- 固定checkpoint: なし
- 未完走Run: `RUN_INCOMPLETE` でFormal判定拒否
- Raw Run配下への出力: `RAW_RUN_PATH_GUARD` で拒否
- Iteration 2追加5分類: 実装済み

次回学校PCでは完走後のanalysis staging copyへFormal Normalizerを実行し、別の新規output directoryへAuditor v2を実行する。詳細は `docs/FORMAL_AUDITOR_V2.md` を参照する。

## 判定ルール

完走直後は `COMPLETED_UNAUDITED`、Normalizer後もAuditor v2後も `VIDEO_SOURCE_ELIGIBLE=false` とする。Legacy Comparisonと上位Formal判定を含む全gate確認が終わり、CRITICAL/MAJORがともに0になった場合だけ `VIDEO_SOURCE_ELIGIBLE=true` を検討する。
