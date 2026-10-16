# M3 Narrative Causality Report

## 総合判定

- Narrative QA: PASS
- M3 Status: PRESENTATION_NEEDS_ITERATION
- Publishability: BLOCKED_SOURCE_GAPS
- Human Review: PENDING

## World Event Classification

SYSTEM由来イベントをTECHNICAL_INTERNAL / GAME_MECHANIC / WORLD_EVENT / TABLETOP_INTERACTION / UNKNOWN_SYSTEM_EVENTへ決定論的に分類する。WORLD_EVENTはSYSTEM由来だけを理由に削除しない。

## Narrative Chains

- `chain_knife_encounter`: PARTIAL
- `chain_final_battle`: FULL

## Protected Narrative Coverage

- HARD_PROTECTED: 45
- FULL: 45
- SOURCE_INSUFFICIENT: 0
- QA: PASS

## SAN Causality

ナイフ怪異の既存KP描写をSAN結果より前へ局所移動する。数値・PL判断・source orderの歴史は変更しない。

## Combat Causality

最終戦はbreak / corbitt_body、scenario_condition達成、combat endを保守的なKP文へ変換する。ナイフ戦闘処理の欠落は上流SOURCE_GAMEPLAY_GAPとして残す。

## Ending Causality

遺体破壊 → 戦闘終結 → 呪い解除の順で提示する。

## Local Reordering

- `scene_048_script_009`: WORLD_EVENT_BEFORE_SAN

## Source Narrative Gaps

- `SOURCE_GAMEPLAY_GAP` / `knife_attack_resolution_missing`: ナイフ襲撃後のattack/evade/damage/combat_endがsourceに存在しない。
- `TRPG_CORE_SAN_LOSS_SCHEMA_BUG` / `trpg_core_san_loss_schema_bug`: 単一値1D4が失敗時損失として解釈されず、既定1d3へフォールバックする上流問題。

## Source Gameplay Gaps

- ナイフ襲撃後のattack / evade / damage / combat endが存在しない。Video Agentでは創作しない。

## Source Contradictions

- `SOURCE_STATE_INCONSISTENCY` / `knife_rediscovery_state_inconsistency`: 正体判明・襲撃後に操作不能となり、その後もう一度発見される。
- `SOURCE_CONTRADICTION` / `basement_door_open_closed`: SYSTEMは地下室の扉が開いたと記録し、直後のKPは閉じたままと説明する。

## Orphan System Responses

- 単独短答13件中、未解決: 4件
- `scene_037_script_005`: ORPHAN_SYSTEM_RESPONSE_CONTRADICTS_DECLINE_RESULT
- `scene_037_script_024`: ORPHAN_SYSTEM_RESPONSE_CONTRADICTS_DECLINE_RESULT
- `scene_038_script_013`: ORPHAN_SYSTEM_RESPONSE_CONTRADICTS_DECLINE_RESULT
- `scene_047_script_015`: ORPHAN_SYSTEM_RESPONSE_CONTRADICTS_DECLINE_RESULT

## Full 53 Scene Audit

- scene reports: 53
- 各sceneのcoverage、missing setup/result、source gap、contradiction、reorderをJSONへ記録した。

## Knife Encounter Result

- WORLD EVENTをSANより前へ提示する局所順序補正を実施。
- ナイフ戦闘の完結処理はsourceにないため公開可否をBLOCK。

## Final Battle Result

- 構造化事実から遺体破壊と戦闘終結を保守的に復元。
- 詳細な攻防はsourceにないため追加していない。

## Regression

- normalized_session.json / edited_script.jsonは変更しない。
- M0〜M3既存テストと新規Narrative QAで検証する。

## Publishability

- `BLOCKED_SOURCE_GAPS`
- critical SOURCE_GAMEPLAY_GAP / SOURCE_CONTRADICTIONが残るため公開不可。

## Remaining M3 Blockers

- M3 PRESENTATION_NEEDS_ITERATION
- M3 ASSET_INPUT_REQUIRED
- M3 LICENSE_REVIEW_REQUIRED
- Human Review = PENDING

## Runtime Verification

- Presentation QA: PASS
- Publishability: BLOCKED_SOURCE_GAPS
- SAN_CAUSE_VISIBLE: PASS
- COMBAT_START_CONTEXT_VISIBLE: PASS
- COMBAT_END_CONTEXT_VISIBLE: PASS
- ENDING_CAUSE_VISIBLE: PASS
- PROTECTED_NARRATIVE_COVERAGE: PASS
- UNGROUNDED_WORLD_EVENT_NARRATIVE: PASS
- Knife preview: `C:\Users\ri4re\Documents\Codex\2026-10-04\referenced-chatgpt-conversation-this-is-an\video-production-agent\projects\corbitt_clear_001\review\m3_knife_encounter_preview.mp4`
- Final battle preview: `C:\Users\ri4re\Documents\Codex\2026-10-04\referenced-chatgpt-conversation-this-is-an\video-production-agent\projects\corbitt_clear_001\review\m3_final_battle_preview.mp4`
- Human Review: PENDING
