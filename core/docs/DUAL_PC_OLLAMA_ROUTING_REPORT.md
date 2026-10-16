# Dual-PC Ollama Routing Report

## Result

- `DUAL_PC_OLLAMA_ROUTING = PASS`
- `VIDEO_SOURCE_ELIGIBLE = false`
- `FULL_LONG_AUTONOMOUS_REEVALUATION_V2 = NOT_STARTED`

学校PC環境で、PL/KPをPRIMARY、LLM JudgeをSECONDARYへ送るrole routingを実装した。既存のOpenAI-compatible `/v1/chat/completions`、prompt、model、temperature、max_tokens、output schema、retry上限は維持している。

## Configuration

- `PRIMARY_OLLAMA_URL`: PRIMARY endpoint。未設定時は旧単一endpoint設定を使用。
- `SECONDARY_OLLAMA_URL`: SECONDARY endpoint。未設定時はPRIMARYへ構成fallback。
- `SECONDARY_FAILURE_POLICY`: 正式評価では`FAIL_CLOSED`。
- `EXECUTION_PROFILE`: 学校Miniでは`SCHOOL_DUAL_PC`。

PRIMARYの後方互換優先順位は次のとおり。

1. `PRIMARY_OLLAMA_URL`
2. `OLLAMA_URL`
3. `OLLAMA_BASE_URL`
4. `OPENAI_BASE_URL`
5. `LLM_BASE_URL`
6. `http://127.0.0.1:11434`

URLはhttp/https、host必須、pathは空または`/v1`だけを受理する。学校固有IPはソース、README、example設定へ記録していない。

## Routing

| Role | Endpoint | Result |
|---|---|---|
| PL | PRIMARY / PC1 | PASS |
| KP | PRIMARY / PC1 | PASS |
| JUDGE | SECONDARY / PC2 | PASS |

`player`、`keeper`、大小文字のrole aliasは、resolver内で`PL / KP / JUDGE`へcanonicalizeする。endpoint選択は単一resolverへ集約した。

## Network

- PRIMARY `/api/tags`: PASS
- SECONDARY `/api/tags`: PASS
- PRIMARY model usable: PASS
- SECONDARY model usable: PASS
- CoreからFirewall変更: なし

両endpointのmodel identityは一致した。

| Field | PRIMARY | SECONDARY |
|---|---|---|
| model | `qwen2.5:14b` | `qwen2.5:14b` |
| family | `qwen2` | `qwen2` |
| parameters | `14.8B` | `14.8B` |
| quantization | `Q4_K_M` | `Q4_K_M` |

## Unit Tests

- 全Unit / regression: `560 PASS`
- Routing専用: `9 PASS`
- 計測非干渉: `2 PASS`
- Iteration 2決定論的受入テストを含む全suite: PASS

専用テストはPL/KP/Judge routing、SECONDARY未設定時の単一PC互換、正式時fail-closed、PRIMARY/SECONDARY環境設定、旧単一URL互換、URL validationを検証した。

## Integration

実接続fixture `CORBITT_DUAL_PC_ROUTING_FIXTURE_001`で次を確認した。

- PL response `PL_OK`: PRIMARY
- KP response `KP_OK`: PRIMARY
- Judge response `JUDGE_OK`: SECONDARY
- Remote Judge errors: 0
- Remote Judge retries: 0
- Remote Judge fallbacks: 0

## Mini Run

- Session: `CORBITT_DUAL_PC_ROUTING_MINI_001`
- Seed: `2301`
- Cycles: `5`
- Turns: `1`
- Human intervention: `0`
- Pause: `0`
- LLM connection errors: `0`
- Segment merge: `PASS`
- Duplicate events: `0`
- Merge issues: `0`

Miniの実Gameplay経路でJudgeが自然発火し、5 callすべてSECONDARYで成功した。

## Remote Judge Metrics

- Remote Judge calls: `5`
- Prompt tokens: `4170`
- Completion tokens: `377`
- Average total wall time: `13.173502 sec`
- p50 total wall time: `12.847068 sec`
- p95 total wall time: `13.850634 sec`
- Total estimated wall time: `65.867510 sec`
- Retries: `0`

PRIMARYは24 calls、SECONDARYは5 callsを処理した。PL remote callsとKP remote callsはともに0である。

OpenAI-compatible responseはOllama nativeの`total_duration`等を返さなかったため、今回はclient wall timeを採用した。request-to-responseとOllama native durationの差によるLAN overheadは算出不能である。この欠測はrouting PASSやGameplay判定には使用していない。

## Fallbacks

- Config fallback: SECONDARY未設定時だけPRIMARYを使用する単一PC互換を確認。
- Runtime fallback in fixture: `0`
- Runtime fallback in Mini: `0`
- Formal policy: `FAIL_CLOSED`

SECONDARYの接続、timeout、model不在はそれぞれ`REMOTE_OLLAMA_CONNECTION_ERROR`、`REMOTE_OLLAMA_TIMEOUT`、`REMOTE_MODEL_UNAVAILABLE`へ分類する。正式時は専用例外をrunnerまで伝播し、`BLOCKED_INFRA`として保存する。

## Errors

- Health check errors: `0`
- Fixture errors: `0`
- Mini remote Judge errors: `0`
- Unexpected fallback: `0`

## Gameplay Regression

- 全560 Unit tests: PASS
- Miniは既存Scenario semanticsとCore adjudicationを変更せず完了。
- Model、量子化、prompt、temperature、max_tokens、output schemaのrouting由来変更: なし。
- `LONG_AUTONOMOUS_ITERATION2_FIX = PASS`は別判定として維持。

## Recommendation

学校PCでの正式Full Runは次の固定構成を使用できる。

- PL/KP: PRIMARY
- Judge: SECONDARY
- Model: `qwen2.5:14b / Q4_K_M`
- Policy: `FAIL_CLOSED`
- Profile: `SCHOOL_DUAL_PC`

ただし、Full Long Autonomous Re-evaluation v2の既存Preflightでは正式NormalizerとEvidence Auditorが未提供のため、Full Long Runはまだ開始しない。`VIDEO_SOURCE_ELIGIBLE`はfalseを維持する。
