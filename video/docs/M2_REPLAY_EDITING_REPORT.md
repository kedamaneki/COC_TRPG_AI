# M2 Replay Editing Intelligence 実装・評価報告

## 総合判定

**M2 NEEDS_ITERATION（技術QA PASS、人間受入確認待ち）**

M2の編集判断層、全セッション処理、レビュー用プレビューまで実装した。機械判定では重大FAILは0件である。ただしM2の最終条件には人間による比較視聴が含まれるため、現時点ではCLOSEDとしない。また、屋敷1階・2階間の往復表現に近距離反復4組が残っており、編集候補として警告している。

## M0 / M1 Regression

- M0/M1/M2合計74テスト: **74/74 PASS**
- M0 `normalized_session.json` のファイルSHA-256: `02C30843753501B5718E0D1D03320489F13AEB958EE8FCB6A5C625BB07FEDB1F`（既存値から変化なし）
- M1 synthetic render: **PASS**、34.643秒、1920x1080、30fps、H.264/AAC
- M1 real-session render: **PASS**、55.800秒、1920x1080、30fps、H.264/AAC
- AquesTalk/VOICEVOX混在、音声、字幕、話者、provenance、無音誤生成、タイムライン重複を再検査しPASS
- 既存のテスト用背景・立ち絵に関する非公開用警告は継続する。M1の既知仕様でありM2の回帰ではない。

## Scene Segmentation

678イベントをルール優先で53シーンに分割した。内訳はINTRO 1、ROLEPLAY 1、SKILL_SEQUENCE 24、SAN_SEQUENCE 1、TRAVEL 21、COMBAT 3、ENDING 2である。location change、combat start/end、endingを明示境界とし、過剰な細分化を避けた。

自然なPart境界候補はscene 31、35、39、47、52の完了後に記録した。推定尺だけで切らず、シーン完了と主要遷移を条件にしている。

## Protected Content

- HARD_PROTECTED: 45
- SOFT_PROTECTED: 105
- NORMAL: 528
- HARD_PROTECTED保持: **45/45（100%）**
- protected event loss: **0**
- Ending、combat start/end、damage、clue、scenario state changeを保護対象にした。

## Edit Classification

- KEEP: 423
- COMPRESS: 4
- CUT: 251

CUTは内部制御・開発用テレメトリを中心に適用した。COMPRESSは根拠を同じに保てる近距離の完全重複に限定した。物語順を壊す可能性がある反復移動は自動削除していない。

## Presentation Classification

- VOICED: 235
- SUBTITLE_ONLY: 65
- OVERLAY_ONLY: 125

技能・ダイス・SAN等のシステム処理はPC音声から分離した。OVERLAY_ONLY区間は音声、下部字幕、PC立ち絵を出さず、構造化オーバーレイだけを表示する。PCの自然な行動宣言とKPの結果描写は音声として残した。

## Text Cleanup

- self-name removal: 235
- system metadata removal: 40
- system presentation separation: 76
- script上の機械的self-name prefix残存: 0

元文と編集後文を両方保存し、変更理由を各script lineへ記録した。意味のある自己言及は単純置換せず保持する。大規模な書き換えや感情・台詞の追加は行っていない。

## Causal Dependency Protection

state change、clue、location、item、combatから87件のdeterministic dependencyを抽出した。依存元がCUTされ、依存先だけが残る組合せは0件である。各依存にはrelation、origin、confidenceを記録した。

## Continuity QA

continuity statusは**PASS**。

- missing_context: 0
- orphan_reference: 0
- unexplained_location_change: 0
- missing_item_origin: 0
- missing_clue_origin: 0
- broken_combat_context: 0
- broken_ending_context: 0

Ending、戦闘開始・決着、主要clueの文脈は維持されている。

## Hallucination / Provenance QA

- 全678イベントをKEEP / COMPRESS / CUTのいずれかへ分類
- unaccounted source event: 0
- unsupported source: 0
- retained lineのsource provenance: 100%
- ungrounded generated dialogue: 0
- dialogue re-attribution: 0
- system処理のPC音声誤帰属: 0

SSOTは`normalized_session.json`である。M2はローカルの決定的ルールエディタを使用し、有料外部LLM/APIを呼び出していない。edit planにはprovider、model、prompt version、temperature、入力digestを記録した。

## Full Session Results

編集後scriptは425行、推定尺は約59.0分である。全編MP4はM2対象外のため生成していない。Part候補は5か所で、次工程で6区間へ分割できる構造になっている。

scene単位キャッシュを再実行し、53シーンすべてを再編集せず再利用できた（reused 53 / generated 0）。状態遷移はSCENES_READY、EDIT_PLAN_READY、SCRIPT_READY、CONTINUITY_CHECKED、QA_PASSED、COMPLETEDを実装した。

## Preview Before / After

- Before: 55.800秒、1,572,023 bytes
- After: 35.333秒、950,883 bytes

同じ実セッション区間をM1 rendererで比較可能にした。フレーム確認では、自己名prefixが下部字幕から除去され、技能結果はPCの読み上げ・名前字幕・立ち絵を伴わないオーバーレイ表示になっている。会話内容と出目は元イベントに一致する。

## Human Review

機械QAと静止画spot checkは完了した。人間による音声込みのBefore/After比較は未完了である。以下を確認して合格した時点でM2 PASS / CLOSEDへ移行できる。

- 元より動画らしいテンポになったか
- 自己名乗りの違和感が減ったか
- システム処理の読み上げがなくなったか
- 話の意味やキャラクターの判断が変わっていないか
- 重要情報が消えていないか

## Known Limitations

- semantic LLMは使用せず、ルールベースで保守的に編集した。暗黙の意味が同じ発言を横断的に要約する能力は限定的である。
- 近距離反復検査が、屋敷1階・2階間の往復4組を検出している。移動順序の因果を守るため自動CUTせず警告に留めた。
- 推定59分は素材全体として長い。Part化後の各話テンポと、反復移動を事実要約へ圧縮するかは人間確認後に調整する余地がある。
- 背景と立ち絵はM1のテスト用素材であり、公開用ではない。
- 発音辞書拡張、BGM、SE、表情、口パク、瞬き、本格演出、全編render、自動投稿は対象外である。

## M3 Readiness

技術的にはM3へ渡せる。編集契約、presentation mode、全件edit plan、scene plan、protected events、continuity QA、再開キャッシュ、比較プレビューが揃っている。M2をCLOSEDにする前に、比較プレビューの人間受入と、反復移動を現状のまま残すか追加圧縮するかの判断が必要である。
