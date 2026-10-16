# M3 Adjudication Evidence Audit — 判定証拠監査

監査日: 2026-10-12  
対象: `projects/corbitt_clear_001` 全53シーン、Normalized 678イベント、M2 425行

## 総合判定

`ADJUDICATION_EVIDENCE_AUDIT = GAPS_FOUND`

判定・SAN・戦闘の欠落はPresentationだけの問題ではない。代表的なSAN表示の `—` は、L1本文にある数値をNormalizerが構造化しなかったことが直接原因である。壁板はSTRロールの表示漏れではなく、ログと状態遷移が矛盾している。ナイフ戦闘はGameplay処理自体が完結していない。

M3はCLOSEDにしない。状態は `M3 PRESENTATION_NEEDS_ITERATION / M3 ASSET_INPUT_REQUIRED / M3 LICENSE_REVIEW_REQUIRED` を維持する。

## Audit Scope

- Truth Source: Core state transition → Unified Event Log / Source Log → Normalized Session → Presentation。
- 全 `SKILL_CHECK` 35件、全 `DICE_RESULT` 35件、SAN 1件、Luck変更1件、全Combat構造イベント7件を列挙した。
- M2/visual planは全編を監査した。M3の実レンダー確認範囲はナイフ遭遇と最終戦プレビューで、全編レンダーは存在しない。
- `normalized_session.json` と `edited_script.json` は変更していない。

## Skill Checks

監査表はUnified由来の `SKILL_CHECK` とSession Log由来の `DICE_RESULT` を別行で保持した。明示的なtransaction/relationがないレコードを近接だけで統合していない。

- Evidence rows: 70
- COMPLETE: 30
- SOURCE_LOGGING_GAP: 39
- NORMALIZATION_GAP: 1
- PRESENTATION_GAP: 0

Unified由来35件はすべて数値rollとtarget thresholdを欠く。結果レベルだけのレコードからダイス値は復元できない。Session Logの別レコードには多くの数値結果があるが、明示IDなしの対応を自動確定していない。

## STR / Opposed Checks

壁板について、PC1のSTR 55はcheckpointに存在する。しかし相手側STR、target threshold、rollは存在せず、対抗ロール・通常STR・Hard/Extremeのどれだったかは確定できない。

`evt_000238...` は `roll_required=true / kp_selected_skill=STR / result=2` を持つがrollを欠く。続くtransactionでは `basement_planks_broken` がfalseのままである。一方Session Logは同じ場面で板を壊したと語る。実際のfalse→trueは後の `evt_000275...` で、PC2の `push / basement_planks / dice_used=false` により発生する。

分類: **SOURCE_CONTRADICTION / CRITICAL**。STR成功を動画側で補完してはならない。

## SAN Checks

SANチェックは1件。

- trigger: コービットのナイフが自律攻撃を開始
- before/target: 70
- roll: 40
- result: 成功
- actual loss: 0
- after: 70

L1本文には上記があるが、L2の `san` とstate changeはnull/空で、M2 overlayも `before/after/loss/result=null` となる。分類は **NORMALIZATION_GAP / MAJOR**。表示の `—` をPresentationで推測補完するべきではない。

ナイフ遭遇のscenario builderは失敗損失を単一値 `1D4` として渡す。一方runtime resolverはslash形式だけを直接扱い、単一値では `fail_loss` がなければ `1d3` へfallbackする。これは **TRPG_CORE_SAN_LOSS_SCHEMA_BUG**。今回の実ロールは成功で損失0だったため、誤ったSAN減少値は実セッション上では発生していない。

## Luck Modifiers

Luck Spendは1件。目星50に59で失敗し、幸運9を消費してregular成功、残り41になった。L1本文は一つの結果文内で元判定を再掲しており孤立modifierではないが、最終レコードはtransaction_idを欠く。L2はraw failureだけを保持し、modifier/final resultを構造化していない。

分類: **NORMALIZATION_GAP / MAJOR**。M3 Iteration 6は明示的L1本文から「失敗→幸運-9→成功」を正しく表示するが、M2の元overlayは失敗のままである。

## Combat Adjudication

NormalizedのCombat構造イベントは7件。ナイフ遭遇と最終戦は別扱いになる。

- ナイフ: scenario dataはcombat_startを要求するが、実行ログに開始、攻撃roll、回避、防御、damage、HP change、combat endがない。**SOURCE_GAMEPLAY_GAP / CRITICAL**。
- 最終戦: `combat-71-2483` を開始し、`break / corbitt_body` をSPECIAL_OBJECTIVEとしてscenario_conditionで解決し、戦闘終了まで記録している。通常攻撃rollやdamage exchangeではないため、それらを欠落値として創作しない。構造化ライフサイクルは成立するが人間向け本文がないため **SOURCE_NARRATIVE_GAP / MINOR**。M3は構造化事実だけから保守的な決着描写を作成済み。

## Wall Board Break

- Runtime check: CONTRADICTORY
- Source log: CONTRADICTORY
- Normalized: PARTIAL
- Presentation: PARTIAL
- ACTION evidence: MISSING
- RESULT/world-state evidence: PRESENT（ただし後の別transaction）
- Final classification: **SOURCE_CONTRADICTION / CRITICAL**

## Knife Encounter

ナイフ発見の目星はLuckで成功化され、怪異の発生とSANチェックまでは追跡できる。しかし「攻撃してきた」の後にCombat処理が存在しない。M3はSANの原因描写を前へ移したが、attack/evade/damageを生成していない。

## Final Battle

最終戦はnormal attackではなく特殊目標一回で終了する。開始、通常行動拒否、special objective選択、scenario_condition解決、終了は構造ログにある。数値攻撃を推測せず、この解決形式をそのまま報告する。

## Presentation Gaps

今回の代表問題には、L2が完全なのにL3だけ欠ける一次的な `PRESENTATION_GAP` は確認しなかった。SAN placeholderはNormalizer起因で、LuckのM2不一致もmodifier/final resultがL2で構造化されていないことが起点である。

## Normalization Gaps

1. SAN本文のbefore/target/roll/result/loss/afterがL2でnull。
2. Luck消費とfinal resultがL2に独立構造として存在しない。

## Source Logging Gaps

Unifiedの全35 `SKILL_CHECK` はrollとtarget thresholdを欠く。特に壁板は `result=2` だけで、何を振って成功したのかを証明できない。

## Source Gameplay Gaps

1. ナイフ戦闘の開始から終了までの処理が欠落。
2. SAN単一式 `1D4` が失敗側式として扱われず `1d3` fallbackになる実装不整合。

## Source Contradictions

壁板は、STR判定で壊したという本文、壊れていないstate、後の自動成功による実state changeが競合する。自動補正は禁止する。

## Severity Summary

- CRITICAL: 2
- MAJOR: 4
- MINOR: 1

## Recommended Fix Layer

1. **TRPG Core**: ナイフCombat処理とSAN loss resolver。
2. **TRPG Logging / Scenario Data**: 壁板の判定・状態遷移を一本化し、roll/target/result/world event relationを同じtransactionで記録。
3. **Normalizer**: SAN構造値、Luck modifier、raw/final resultを保持。
4. **Video Presentation**: 上流が揃った後に正規化値だけを表示。欠落ダイスは生成しない。

## M3 Impact

M3は現状の表示基盤を維持できるが、上流欠落があるため全編公開可能とは判定できない。Human Review、素材、ライセンス確認も残る。

## TRPG Core Impact

ナイフ戦闘欠落はシナリオ完走の事実とは別に、ゲーム上の危険と結果を消している。壁板は結果を先に語って後の別処理でstateを合わせており、再現可能な判定証拠になっていない。SAN 1D4問題は今回の成功rollでは顕在化しなかったが、失敗時に誤計算するコード経路が確認できる。

## 成果物

- `projects/corbitt_clear_001/adjudication_evidence_report.json`
- `projects/corbitt_clear_001/san_evidence_report.json`
- `projects/corbitt_clear_001/combat_evidence_report.json`
- `projects/corbitt_clear_001/modifier_evidence_report.json`
- `projects/corbitt_clear_001/adjudication_gap_report.json`
- `projects/corbitt_clear_001/adjudication_evidence_table.csv`
