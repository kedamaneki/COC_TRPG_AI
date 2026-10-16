# Full Long Autonomous Re-evaluation v2 Report

## Result

- `FULL_LONG_AUTONOMOUS_REEVALUATION_V2 = BLOCKED_INFRA`
- `VIDEO_SOURCE_ELIGIBLE = false`
- `FULL_LONG_RUN_STARTED = false`

Full Long Run開始前Preflightの必須10項目中、8項目がPASSし、2項目がFAILした。指示書の開始条件に従い、Full Long Runは開始していない。Gameplay failureではない。

未達項目は、正式Video Production Agent NormalizerとFull Session Evidence Auditorの実行可能性である。現リポジトリ、`F:\制作物`配下の他プロジェクト、引継ぎ添付、ローカルCodex履歴を検索したが、実行ソース、実行ファイル、または正式な呼び出し先を確認できなかった。既存の`normalized_session.json`と`adjudication_evidence_report.json`は出力成果物であり、再実行可能なツールではない。

## Run Identity

- Session: `CORBITT_LONGRUN_ITERATION2_V2_001`
- Run state: `PREFLIGHT_BLOCKED_NOT_STARTED`
- Git commit: `unavailable`
- 旧Session変更: なし
- 詳細: `evaluation-v2/CORBITT_LONGRUN_ITERATION2_V2_001/run_identity.json`

## Input Identity

- Status: `PASS`
- Scenario: `EXACT`
- NPC: `EXACT`
- PC: `DERIVED_DECLARED` (`INIT_GAME_SYSTEM_V1`)
- 詳細: `evaluation-v2/CORBITT_LONGRUN_ITERATION2_V2_001/input_manifest.json`

## Model / Ollama Configuration

- Ollama reachable: `PASS`
- Model usable: `PASS`
- Model: `qwen2.5:14b`
- Parameter size: `14.8B`
- Quantization: `Q4_K_M`
- OpenAI-compatible probe response: `OK`

## Completion

- Full Long Run: `NOT_STARTED`
- 理由: `FORMAL_NORMALIZER_UNAVAILABLE`, `FORMAL_EVIDENCE_AUDITOR_UNAVAILABLE`

## Human Intervention

- Full Long Run: `NOT_MEASURED`
- Preflight中にGameplayへの人間介入は行っていない。

## Action / Progress Metrics

- `NOT_AVAILABLE`。Full Long Run未開始。

## ROLL Integrity

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## SAN Integrity

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## Luck Integrity

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## Combat Integrity

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## Wall Result

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## Basement Door Result

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## Knife Object Lifecycle

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## Final Battle

- Deterministic Integration: `PASS`
- `SPECIAL_OBJECTIVE_COMPLETED / CORBITT_BODY_DESTROYED`契約を維持。
- Full Session: `NOT_AUDITED`

## Narrative / State Consistency

- Deterministic Integration: `PASS`
- Full Session: `NOT_AUDITED`

## Goal Completion

- Full Session: `NOT_MEASURED`

## Logging Integrity

- Unit: `551 PASS`
- Iteration 2 Deterministic Integration: `12 PASS`
- Instrumentation non-interference: `2 PASS`
- Session Log writable: `PASS`
- Unified Event Log writable: `PASS`
- Checkpoint writable: `PASS`

## Normalizer Result

- Runnable: `FAIL`
- 正式Normalizerのコードまたは実行先が学校PC側の提供範囲に存在しない。
- 既存成果物を複製・推測変換して正式Normalizationの代用にはしていない。

## Evidence Audit

- Runnable: `FAIL`
- 正式Full Session Evidence Auditorのコードまたは実行先が学校PC側の提供範囲に存在しない。
- 既存レポートを新runの監査結果として再利用していない。

## LLM Performance

Gameplay、prompt、decision policyを変更しない計測を追加した。

各callについて次をJSONLへ記録する。

- `call_id`, `role`, `turn`, `cycle`, `purpose`, `model`
- `prompt_eval_count`, `prompt_eval_duration`
- `eval_count`, `eval_duration`, `total_duration`, `load_duration`
- `retry_count`, `tokens_per_second`, `time_to_first_token`
- client wall time、status、finish reason

Role別集計と1 turn当たり負荷は`llm_performance_summary.json`へ出力する。Ollama OpenAI-compatible応答がnative durationを返さない場合、prompt/generationのnative durationはnullで保持し、`total_duration`はclient wall timeとしてsourceを明示する。

Full Long Run未開始のため実測集計はまだ存在しない。

## Legacy Comparison

- `NOT_RUN`
- 比較対象となる新Full Sessionが存在しないため、旧runとの比較値は作成していない。

## Remaining Issues

1. 正式Video Production Agent Normalizerのプロジェクトパスまたは実行方法が必要。
2. 正式Full Session Evidence Auditorのプロジェクトパスまたは実行方法が必要。
3. 上記2ゲートをPASS後、同じSession IDでFull Long Runを1回だけ開始する。

## Video Source Eligibility

- `VIDEO_SOURCE_ELIGIBLE = false`
- M3状態を維持する。
  - `M3 PRESENTATION_NEEDS_ITERATION`
  - `M3 ASSET_INPUT_REQUIRED`
  - `M3 LICENSE_REVIEW_REQUIRED`
  - `HUMAN_REVIEW_REQUIRED`

