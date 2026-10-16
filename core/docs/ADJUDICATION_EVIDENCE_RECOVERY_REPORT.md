# Adjudication Evidence Recovery Report

## Result

`ADJUDICATION_EVIDENCE_RECOVERY = PASS`

この判定は、決定論的なオフライン受入セッションで判定契約と因果鎖を検証した結果である。外部APIを使う長編自律プレイの再走は今回の検証には含めない。

## Root Causes

- 判定結果、状態変更、Narrativeが別々に生成され、同じ判定を示す安定IDがなかった。
- Unified Eventの判定行に成功度だけが残り、出目と目標値が落ちていた。
- 単一SAN式 `1D4` が失敗側の損失式として扱われず、既定値へフォールバックしていた。
- 幸運消費前の失敗と消費後の最終成功が別情報として残り、正規化層が結び付けられなかった。
- ナイフ遭遇は描写と開始予定だけで、戦闘開始から終了までの契約が不足していた。
- 壁板には `strength_check_type` があっても数値 `STR` がない場合、判定契約を返さない経路があった。

## Core Changes

- 判定ごとに `adjudication_id` を発行し、action、dice、modifier、final result、state change、world eventへ伝播する。
- `resolution_mode` を `ROLL` / `NO_ROLL` で明示し、判定不要とログ欠落を区別する。
- rolled checkは `target_value`、`roll`、`raw_result`、`final_result` を同時に保持する。
- 幸運消費は元の出目と目標値を維持し、resource before/afterを持つmodifierとして記録する。

## Logging Changes

- Unified / Session Logで `transaction_id` と `adjudication_id` を共有する。
- 状態遷移には `state_before` / `state_after`、因果には `cause_event_ids` / `result_event_ids` を付与する。
- SANはbefore、target、roll、result、各損失式、actual loss、after、triggerを構造化した。
- 戦闘はcombat ID、参加者、攻撃・防御判定、damage、HP差分、終了イベントを追跡する。

## Scenario Changes

- 壁板判定を `OPPOSED_STR_CHECK` として明示した。
- `required_skill: STR` または明示されたstrength contractからも判定要求を返す。
- ナイフ遭遇に `ENEMY_DEFEATED` と `ENEMY_INCAPACITATED` の終了条件を追加した。
- 最終戦は通常攻撃交換へ変更せず、`SPECIAL_OBJECTIVE_COMPLETED` / `CORBITT_BODY_DESTROYED` を維持した。

## Wall Board Result

- 成功: `basement_planks_broken: false -> true` と破壊Narrativeが同じresolutionから生成される。
- 失敗: 状態はfalseのまま、成功Narrativeは出ない。
- `NARRATIVE_STATE_CONTRADICTION = 0`

## SAN Result

- `0/1D4`、`0/1D3`、`1/1D6`、単一式`1D4`をfixtureで検証した。
- 単一式`1D4`は `success_loss=0`、`failure_loss=1D4` として解決する。
- 受入セッションでは `70 / roll 40 / SUCCESS / loss 0 / after 70` が全層で一致した。

## Luck Result

- `roll 59 / target 50 / raw FAILURE / Luck 9 / final REGULAR_SUCCESS / Luck 50 -> 41` を同一adjudicationとして保持した。

## Knife Combat Result

- encounter、combat start、attack/defense、damage、HP change、incapacitation、combat endを記録した。
- `COMBAT_WITHOUT_TERMINATION = 0`

## Final Battle Regression

- 最終戦の特殊目標による遺体破壊とシナリオクリアを維持した。
- 通常のattack exchangeを必須化していない。

## New Session Audit

対象: `evaluation-v2/corbitt_adjudication_fix_001`

- 形式: `OFFLINE_DETERMINISTIC_CONTRACT_SESSION`
- rolled checks: 7、欠落: 0
- `SOURCE_CONTRADICTION = 0`
- `NORMALIZATION_GAP = 0`
- `COMBAT_WITHOUT_TERMINATION = 0`
- legacy text parse: 0
- critical findings: 0

## Test Results

- Core全体: 545 tests PASS、failure 0、error 0、skip 0
- 外部通信は `_call_chat_completion` を失敗させるオフラインstubで遮断した。
- 判定回復専用: 8 tests PASS

## Remaining Issues

- 新しい長編自律プレイを実際に最後まで走らせる検証は未実施。今回の受入セッションは契約検証用であり、生成AIによる進行品質の評価を代替しない。
- 旧 `corbitt_clear_001` の壁矛盾とナイフ戦闘欠落は歴史的証拠として残し、推測補完していない。
- M3の素材投入、ライセンス確認、Human Reviewは別ゲートとして残る。
