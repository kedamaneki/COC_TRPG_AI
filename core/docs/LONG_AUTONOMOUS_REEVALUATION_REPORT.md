# Long Autonomous Run Re-evaluation Report

## Result

- `LONG_AUTONOMOUS_REEVALUATION = NEEDS_ITERATION`
- `VIDEO_SOURCE_ELIGIBLE = false`
- Gameplayは完走したが、正式PASS条件の証拠完全性とNarrative/State整合性を満たさない。
- CRITICAL 4件、MAJOR 5件、MINOR 1件。

## Run Identity

- Session: `CORBITT_LONGRUN_POST_ADJUDICATION_FIX_001`
- Seed: `2101`
- Core: Git worktreeではないためcommit固定値なし。run開始時のruntime dataとhashを保存。
- Resume: 1回。20 cycle地点のcheckpointから継続し、segment mergeは `PASS`。

## Model / API Configuration

- Provider: local Ollama OpenAI-compatible endpoint (`http://localhost:11434/v1`)
- PL / KP / Judge: `qwen2.5:14b`
- Timeout: 120秒、max_tokens: 2048
- 有料外部API: 不使用。外部API費用: 0。

## Scenario / PC Identity

- Runtime scenario SHA-256: `699773662a65e82e5507d711ac40338799b24467dd61a7df0bf30c13c043324d`
- Runtime PCs SHA-256: `492e216de1f9b2eafc1f8391f3c8cd6cc4b5748872f8e2da280f052c27d451ef`
- Preflight scenario hash: `621e6a996f31a802132ed37b14a4005fa12049eaee225a353f8c7a11837610d6`
- Preflight PC hash: `8b04641837d36786b541e2c3bbccead7b4ff025135b18765383c6e446861215e`
- Preflight NPC hash: `3c795e6098f97ae8e6240b9ed2412428ab332c91c30a1cb45b846d2f4628377c`

## Completion Result

- completed=true / phase=clear / ending=game_clear
- 33 cycles、99 turns、経過 7671.296秒。
- 最終地点は `corbitt_basement_room2`。`corbitt_defeated=true`。

## Human Intervention

- human_intervention = 0（合格）
- system forced = 7、system guided = 42。
- system forcedは正式機能として記録され、完走判定とは分離した。

## Action / Progress Statistics

- actions = 133 ({"SYSTEM_GUIDED": 47, "AUTONOMOUS": 79, "SYSTEM_FORCED": 7})
- location changes(normalized) = 72
- skill checks(normalized) = 46
- dice results(normalized) = 35
- rejected actions = 33
- maximum stagnation = 14
- combats = 2、resolved combat actions = 2

## Adjudication Integrity

- FAIL。ROLL契約欠落は9 adjudication。
- Unifiedの実resolution ROLLは19件、そのうち`INVESTIGATION_ROLLED` 2件がtarget/roll/raw result欠落。
- 対抗STRは本文に双方の出目があるが、meta/Unifiedではrollとtargetがnullであり、構造契約を満たさない。

## Skill Check Integrity

- `rolled_check_incomplete = 9`（必須値0に不合格）。
- 主な対象: `corbitt_house`, `wall_planks`, `basement_door`, `basement_planks`, `rotting_floorboards`。

## SAN Integrity

- FAIL。実際に構造化されたSAN判定は0件。
- `living_room_clutter`成功payloadの`force_san_check(0/1D3)`が実行されていない。
- Normalizerは戦闘状態のSAN snapshotをSAN判定と誤認し、7件の不完全なSANレコードを生成した。
- このrunではSAN単一式と`after = before - loss`を実運用検証できない。

## Luck Integrity

- Sourceでは2件ともoriginal roll/target/raw failure/Luck before-after/final successを保持。
- 71 vs 65、Luck 6、45→39、final REGULAR_SUCCESS。
- 39 vs 32、Luck 7、39→32、final HARD_SUCCESS。
- Normalizerは適用前FAILUREと適用後SUCCESSを2件のsource contradictionとして誤分類したため、Normalizer gateはFAIL。

## Combat Integrity

- 2 combatとも`COMBAT_STARTED`→action→`COMBAT_ENDED`へ到達。
- `COMBAT_WITHOUT_TERMINATION = 0`（合格）。
- ナイフ戦闘はattack 26/55、defense 99、damage 4、HP 1→0を保持。
- 最終戦はSPECIAL_OBJECTIVEのNO_ROLL解決を維持したが、Unified側のadjudication_idが空でSession側と結合できない。

## Wall Board Result

- FAIL。session[180-181]で破壊成功を描写するが、authoritative stateは`basement_planks_examined=true`だけで`broken=false`。
- session[189]の別STR対抗は失敗。session[439]のさらに別判定で初めて`basement_planks_broken: false→true`。
- `NARRATIVE_STATE_CONTRADICTION != 0`。

## Basement Door Result

- FAIL。session[161]内で「まだ閉ざされている」と「扉を開けた」が併存し、stateはexaminedだけ更新。
- session[164]/[247]でも閉鎖/開放の矛盾文を反復。実際のunlockはsession[167]の別判定。

## Knife Encounter Result

- Combat lifecycle自体は改善し、開始・攻防・damage・HP変化・終了を記録。
- ただし戦闘イベントのSAN状態フィールドがNormalizerでSAN checkに誤変換される。

## Knife State / Rediscovery Result

- FAIL。session[197]はflag=false時に「持っているナイフ」と「床に放置」を同時に描写。
- session[424]で初めて`has_corbitt_knife: false→true`。session[434]でダガー消滅を描写するが最終flagはtrueのまま。

## Final Battle Result

- `SPECIAL_OBJECTIVE_COMPLETED / CORBITT_BODY_DESTROYED`と`corbitt_defeated: false→true`は一致。
- Session側の事実ベースhuman_readable_descriptionも存在。
- Unified combat actionにはadjudication_idが伝播せず、NO_ROLL理由も欠落。
- 表示本文の「渾身の一撃、あるいは浄化の儀式」はsource factにない選択肢を加えている。

## Narrative / State Consistency

- FAIL。壁板、地下室扉、ナイフ所持/消滅で矛盾を確認。
- Core evaluatorの`inconsistency_count=0`はこれらを検出できていない。

## Goal Completion Sync

- PASS。`completed=true`, `phase=clear`, `pause_reason=game_clear`, `corbitt_defeated=true`が一致。

## Logging Integrity

- FAIL。9件のROLL判定で構造数値が欠落。
- 最終戦のSession/Unified adjudication linkも欠落。
- 時系列近接での推測補完は行わず、欠落として保持した。

## Normalizer Result

- Import/schema validationはPASS、events=846、traceability=1.0。
- `legacy_text_parse = 0`。
- `NORMALIZATION_SOURCE_CONTRADICTION = 22` のため正式gateはFAIL。
- 内訳: {"dice.result": 16, "dice.final_result": 3, "san.before": 1, "san.san_before": 1, "san.target": 1}。

## Evidence Audit

- `SOURCE_CONTRADICTION = 3`
- `SOURCE_GAMEPLAY_GAP = 1`
- `SOURCE_LOGGING_GAP = 2`
- `NORMALIZATION_GAP = 3`
- `COMBAT_WITHOUT_TERMINATION = 0`
- `rolled_check_incomplete = 9`
- `NORMALIZATION_SOURCE_CONTRADICTION = 22`
- `legacy_text_parse = 0`
- `traceability = 1.0`

## Legacy Run Comparison

- 旧run: combat termination欠落1、CRITICAL 2、MAJOR 4、壁板矛盾あり。
- 新run: 自律完走・human 0・2戦闘完結は改善。
- 壁板矛盾は再発し、地下室扉/ナイフ状態の矛盾、ROLL証拠欠落、Normalizer矛盾22件が残る。

## Test / Validation Results

- Preflight Core: 545 PASS。
- Preflight Video Agent: 160 PASS。
- Normalizer import/schema validation: PASS。
- Segment merge: PASS、duplicate event 0、issues 0。
- 長編Evidence gate: FAIL。単体テスト合格と長時間自由運用の契約維持が一致しなかった。

## Cost / API Usage

- ローカルOllamaのみ。外部有料API費用0。

## Remaining Issues

1. シナリオのexamine clueとstate mutationを分離し、未開放時に開放済み本文を返さない。
2. opposed STRを含む全ROLLでactor/target双方の閾値と出目を構造化し、Unifiedへ同一adjudication_idで出す。
3. success payload内`force_san_check`を実行し、完全なSAN tupleを記録する。
4. Normalizerで成功度表現をcanonical化し、Luckのphase transitionを矛盾扱いしない。
5. 戦闘participant stateのSAN snapshotとSAN adjudicationをschema上で分離する。
6. knifeのowned/available/destroyed状態を明示し、消滅後にowned=trueを残さない。
7. final battleのadjudication_idをUnified combat lifecycleへ伝播する。

## Video Source Eligibility

- `VIDEO_SOURCE_ELIGIBLE = false`
- CRITICAL/MAJOR gapが残るため、正式Video Production Agent projectへは投入しない。今回のNormalizer処理は監査用stagingに限定した。
- M3状態は継続: `M3 PRESENTATION_NEEDS_ITERATION`, `M3 ASSET_INPUT_REQUIRED`, `M3 LICENSE_REVIEW_REQUIRED`, `HUMAN_REVIEW_REQUIRED`。
