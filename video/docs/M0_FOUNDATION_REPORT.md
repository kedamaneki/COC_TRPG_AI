# Video Production Agent v0.1 — M0 Foundation Report

## 総合判定

`M0 PASS / CLOSED`

## Project Structure

TRPG本体から分離した独立プロジェクトとして構築した。実装は`src/video_agent`以下にImporter、Normalizer、Schema、Character/Profile、Asset、Validation、CLIを分離し、設定・素材参照・シナリオ素材・session・project・cache・test・docsを独立させた。

## Input Format

第一AdapterはTRPG evaluation v2を対象とする。`unified-event-log.json`、`session-log.json`、`result.json`を必須入力とし、最新正式checkpointのPC/NPC定義とscenario datasetを補助情報として読む。checkpointは動画化事実のSSOTにせず、会話・イベント事実は正式ログを優先する。

正式サンプルは`HAUNTED_2101_GOAL_SYNC_FIX`（cycle 29、turn 71、clear）を使用した。

## Session Importer

入力ファイルの存在確認、JSON読込、source SHA-256記録、最終checkpoint補助情報取得を実装した。TRPG側の内部moduleをimportせず、ファイルAdapterとして独立している。

## Normalized Schema

schema version `0.1`。Scenario、Participant、Event、Metadata、Provenanceを定義した。Eventはsource ID、cycle/turn、決定論的order、scene、location ID/display name、speaker/actor、標準event type、text、action、dice、SAN、combat、state change、metadataを持つ。不明値は推測せずnullとする。

## Event Mapping

678イベントを生成した。主な内訳はAction Declaration 179、Dialogue 88、KP Description 83、Location Change 46、Dice Result 35、Skill Check 35、Clue Found 16、Combat系7、Ending 2、SAN Loss 1。未知event typeは0。

元Session Logのtext 383件は全文を同じ順序で保持した。M0ではSYSTEM_INTERNALも削除していない。

## Provenance

- source events: 678
- normalized events: 678
- dropped events: 0
- source traceability: 100%
- unknown speaker: 0
- deterministic content digest: `cd3f99f74bf56763a2a933b3ffc0ad40e81ae36e0cd1c8030e5262bf4f868fb4`
- normalized JSON file SHA-256: `02C30843753501B5718E0D1D03320489F13AEB958EE8FCB6A5C625BB07FEDB1F`

ネイティブevent IDがないSession Logには`session_log:NNNNNN`というsource stream/index locatorを付けた。全recordの原文payloadもmetadataに保持する。

## Character / Voice Profiles

CharacterProfileと手動`character_map.json`を分離した。正式sessionのPC/NPCを霊夢等へ自動割当していない。AquesTalk代表preset（霊夢・魔理沙）、VOICEVOX nullable template、NONE/KP voiceをJSON設定として登録した。

## Subtitle Profiles

環境参照フォント「たぬき油性マジック」、変更可能なサイズ・位置・色・alignment・line height・letter spacing・opacity、複数outline layerをJSONで表現した。フォント本体は同梱していない。

## Portrait Profiles

旧きつね式ゆっくりへの外部asset pack参照、semantic expression、blink/mouth capabilityを定義した。KPはportrait `NONE`。実素材mappingと描画はM3対象のままである。

## Asset Manifest

ID、type、path、source、author、license、commercial use、credit、status、tagを定義した。ScenarioAssetPack、NPC fallback優先順位、汎用mob、BGM/SE semantic tagも登録した。画像・音源本体は追加していない。

## License Metadata

旧きつね式参照は権利情報を推測せず`UNKNOWN`として登録した。これはM0ではWarningであり、将来の公開renderでは自動採用不可とする。

## Validation

duplicate/missing event ID、provenance消失、participant、role、event type、profile参照、asset参照、色、voice profile、schema versionを検査する。正式projectはError 0、Warning 1（外部portrait packのlicense UNKNOWN）でPASSした。

## Unit Tests

18件PASS。Importer、schema、Dialogue/KP/Dice/SAN/Combat、Provenance、未知field、invalid event、profile、multi-outline、asset、決定性、profile参照、全文会話保持を検証した。

## Integration Test

正式完走session一式からprojectを生成し、crash 0、provenance loss 0、dialogue loss 0、combat/ending/location取得、validation error 0を確認した。同一入力から2回生成した`normalized_session.json`のSHA-256は一致した。

## First Session Conversion

`projects/corbitt_clear_001`に`normalized_session.json`、`character_map.json`、`provenance_report.json`、`validation_report.json`、source manifestを生成した。

## Remaining Unknowns

実portrait packの作者・license・商用利用・credit条件、VOICEVOX speaker/style、全AquesTalkキャラクターの厳密値、素材file mappingは未設定である。事実を推測せず、M1以降で利用者確認後に登録する。

## M1 Readiness

TRPG Session → Importer → Normalized Session → Video Productionの境界は完成した。M1ではnormalized sessionのみを入力として、30〜60秒のMinimal Render Pipelineへ進める。M0ではMP4、音声生成、FFmpeg、編集判断、LLM、素材描画を実行していない。
