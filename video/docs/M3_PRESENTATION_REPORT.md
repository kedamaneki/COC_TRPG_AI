# M3 TRPG Visual / Audio Presentation 実装・評価報告

## 総合判定

**M3 PRESENTATION_NEEDS_ITERATION / M3 ASSET_INPUT_REQUIRED / M3 LICENSE_REVIEW_REQUIRED**

Presentation Iteration 5として同じsource区間の1分56.0秒Scene Previewを再生成し、機械Technical QAは
**34/34 PASS**となった。SYSTEM interactionをKP↔PLの卓上会話として文脈付きで提示したが、
人間の映像・音声受入確認は未完了である。悪霊の家に合う背景もなく、使用中7素材の権利情報が
UNKNOWNである。M3はCLOSEDにしない。

## Presentation Iteration 5

Iteration 4で隠した短答を、`SYSTEM_INTERACTION_RESOLVER`でprompt/responseのペアとして扱う構造へ更新した。
明示SYSTEM prompt、request/response関係、前後の確定結果を優先し、技術SYSTEMは非表示、曖昧な関係は
警告して変換しない。変換後も`presentation_origin`、`presentation_as`、`system_interaction_id`、元event IDを
Timelineへ保持する。

今回の対象`scene_048_script_006`は、上流のAI向け確認文と直後の確定ログを照合するとプッシュではなく、
目星失敗を成功へ変えるための幸運9ポイント消費確認だった。このため、元ログの意味を変えず、
KP「幸運を9ポイント消費して成功にしますか？」→ PL魔理沙「yes」として表示した。KPは`m1_vv_kp`、
魔理沙は`aq_marisa_default`を使い、voice fallbackは発生していない。Push YesとRetry Noは正式fixtureで
KP↔PL変換を検証している。

- `tabletop_interactions_detected`: 1
- `tabletop_interactions_presented`: 1
- `technical_interactions_hidden`: 0（対象preview内。fixtureでは1）
- `prompt_response_pairs`: 1
- `ambiguous_pairs`: 0
- `pl_voice_fallback_count`: 0
- `ungrounded_kp_prompt_count`: 0

追加QAの`TABLETOP_SYSTEM_INTERACTION_PRESENTED`、`SYSTEM_INTERACTION_PAIRING_VALID`、
`TECHNICAL_SYSTEM_INTERACTION_HIDDEN`、`SYSTEM_RESPONSE_CONTEXT_VISIBLE`、`PL_PC_IDENTITY_VALID`、
`UNGROUNDED_KP_PROMPT`はすべてPASSした。Before/After動画とfixtureを`review/`へ保存した。

## Presentation Iteration 4

M2の同一区間に残っていた`scene_048_script_006`の`yes`を、直前の技能結果と直後のシステム処理を使って
SYSTEM向け操作応答と確定し、Timeline生成前に非表示にした。文字列一致だけでは削除せず、明示relation、
SYSTEM prompt、前後system event、短答形式の複数条件を使う。曖昧な場合のsafe defaultは`KEEP`である。

- `system_response_candidates`: 1
- `system_responses_hidden`: 1
- `system_responses_subtitle_only`: 0
- `system_responses_overlay_only`: 0
- `false_positive_count`: 0
- `system_response_leak_count`: 0

SYSTEM Push Yes/Noは非表示、NPC会話とKP確認への「はい」はVOICED維持となるfixtureを保存した。
既存音声cacheは削除せず、新previewのTimelineから対象clipだけを除外した。

## Presentation Iteration 3

- M2の16 source lineを同一区間として読み込み、Presentation Layerで内部system表示2件だけを抑制した。
- previewは14 displayed source line、30 clip、113.3秒。M2 `edited_script.json`は変更していない。
- KP字幕、system表示、AquesTalk prosodyの専用fixtureとIteration 3動画を保存した。
- M3状態は`HUMAN_REVIEW_REQUIRED`で、3つのphase decisionを維持する。

## M0/M1/M2 Regression

- M0〜M3: **122/122 tests PASS**
- `normalized_session.json` SHA-256:
  `02C30843753501B5718E0D1D03320489F13AEB958EE8FCB6A5C625BB07FEDB1F`（不変）
- `edited_script.json` SHA-256:
  `79BFC1D59E732E219006D04A8AC62B0D845BA5253D1F9A8DE4AC8B461D3F47C0`（不変）
- M1 synthetic render: PASS、34.643秒、1920x1080、30fps、H.264/AAC
- M1 real-session render: PASS、55.384秒、1920x1080、30fps、H.264/AAC
- M2: 678イベントの全件説明、provenance、保護イベント、会話帰属、continuityを再検査してPASS
- M2既知警告 `NEARBY_REPETITION_REMAINS` は継続し、M3で台詞を変更していない。

## Asset Import

提供フォルダから立ち絵2、背景1、セリフ枠1、BGM1、SE3の計8ファイルをプロジェクト内へコピーし、
ID、相対path、source、license、status、tags、SHA-256をmanifestへ保存した。TimelineはEドライブの
絶対pathを保持せずasset IDから解決する。ネット取得、AI背景生成、依存追加は行っていない。

## Portraits

PC1は旧きつね式れいむ、PC2は旧きつね式まりさを固定slotで表示する。KPとsystemには立ち絵を
表示しない。semantic expressionと`SCARED → SURPRISED → NORMAL`等のfallbackを実装したが、
今回の素材は各キャラクター1枚のみなので実表示はNORMALへfallbackする。PC2のシナリオ固有／
公式対応立ち絵は不足素材として報告した。

## Backgrounds

悪霊の家に適合する背景は提供12点から確認できなかった。紫色の抽象背景を
`bg_neutral_user`として採用し、10 locationすべてを明示的なneutral fallbackにした。対象は
introduction、Boston Globe、Central Library、Roxbury Sanitarium、近隣、Corbitt邸外観、
1階、2階、地下、地下第2室である。背景不足は`missing_assets_report.json`へ記録した。

## Subtitle Presentation

追加された透過セリフ枠を下部へ配置した。話者名は`speaker_name_region`、本文は独立した
`dialogue_text_region`へ表示し、どちらもconfigから座標を変更できる。本文は52px、長文46pxとした。
本文色に直接接する縁とのrelative luminance/contrast ratioをQAし、高輝度本文と高輝度隣接縁の組合せを
禁止した。魔理沙の黄色は維持し、隣接縁を濃灰4pxへ変更した。霊夢の赤、KPの白も識別色を維持している。
全登録色を暗いセリフ枠上で比較する`m3_subtitle_palette_fixture.png`を1920x1080で生成した。
Subtitle overflowは0件。

KPはneutral専用profileとして本文をoff-white、隣接縁をdark gray、最外縁をlight grayへ分離した。
本文と隣接縁のcontrast ratioは4.5以上、暗いセリフ枠へ接する最外縁はrelative luminance 0.45以上を
QA条件とし、`KP_SUBTITLE_CONTRAST`はPASSした。1920x1080の`m3_kp_subtitle_fixture.png`で確認できる。

VOICED長文は句読点、改行、意味境界を優先してspeech chunkへ分割する。各chunkを別WAVとして
合成し、その実durationへ1字幕を同期させる。元の`source_event_ids`と`source_script_line_id`は全chunkに
保持し、結合した本文は元文と一致する。発話より先行する字幕ページは0件。

## AquesTalk Internal Gap

原因をWAV端無音、profileの`post_silence`、Timeline gap、chunk境界、concat処理に分けて計測した。
profileの0.15秒`post_silence`は現在のadapter/bridgeでは使用されておらず、主因は同一発言の各chunk後に
Timelineが0.35秒を加えていたことだった。さらにVOICEVOXから得たaccent phrase間へ読点を一律挿入していたため、
読み内部にも不要な間が生じ得た。

同一発言内のchunk間は追加gapを0秒とし、0.35秒は発言末だけへ適用した。読みは明示的な
`pause_mora`がある境界だけに読点を残す。再生成WAVの端無音とTimelineを合算した内部無音は、
霊夢0.0612秒、魔理沙0.0592秒で、QA上限0.12秒以内だった。双方ともTimeline gapは0秒である。

Iteration 3では読点を音声境界にせず、句点・感嘆符・疑問符・発言末だけを自然な合成境界とした。
単語・任意文字位置での分割は禁止した。今回、霊夢には内部音声境界がなく、魔理沙の実在する1境界は
0.0592秒、Timeline gap 0秒だった。字幕ページと音声合成単位は別概念として保持する。

## AquesTalk Prosody Investigation

霊夢3台詞、魔理沙3台詞について`agent_current`、`agent_candidate`、`reference_yymm4`のWAVを生成した。
`agent_current`はIteration 2の読点・長さ分割とWAV concat、`agent_candidate`は自然な発言/文を1回で合成する。
referenceはインストール済みYMM4と同じ同梱AquesTalk DLL、voice type、reading speedを使うengine直結出力である。

voice type、reading speed、pitch 100%、句読点入力、分割、後処理を記録した。AgentはF0を平坦化するpitch shiftや
time stretchを行っておらず、DLL/versionもYMM4同梱物と同一である。長いサンプル2件では旧分割が2 parts、
候補は1 invocationとなり、candidateはengine直結referenceとSHA-256一致した。今回改善できた要因は
不要な分割・concatの除去である。

YMM4アプリ自身のfrontend書き出しは自動取得していないため、YMM4とAgentの残る聴感差の候補はfrontend側の
読み・アクセント解析である。これはengine直結fixtureだけでは確定できず、Human A/B ReviewでYMM4実書出しを
同じ`reference_yymm4`へ差し替えて確認する。追加pitch加工は行っていない。

## HEAD_ONLY Portrait / Safe Areas

`PortraitProfile.portrait_kind`へ`FULL_BODY`、`BUST`、`HEAD_ONLY`を定義し、旧きつね式ゆっくり立ち絵を
`HEAD_ONLY`とした。左右それぞれに専用slotを設け、bounds、center anchor、最大face幅/高さ、safe margin、
speaker sideをconfig化した。`speaker_name_region`、`dialogue_text_region`、左右head portrait、
`dice_san_overlay_region`を独立領域として扱い、禁止overlapをQAする。

再生成結果ではHEAD_ONLYとdialogue frame、HEAD_ONLYとdialogue textのoverlapはともに0である。
将来の顔専用frameをslotへ追加できるが、今回のM3判定条件にはしていない。

## System Presentation Whitelist

M3 Presentation Layerにwhitelistを実装した。表示を許可するのはDICE/SKILL結果、SAN変化、HP変化、
明示的にviewer-essentialとされた構造化status changeだけである。M2の行は削除・変更しない。

今回のpreviewでは2件を非表示にした。内訳は`LOCATION_CHANGE`の自動成功・内部移動表示1件と、
構造化overlayを持たない技術的`DICE_RESULT`1件である。表示されたsystem種別は`SKILL_RESULT`と
`SAN_CHANGE`で、raw system字幕の漏出は0件だった。結果は`system_presentation_report.json`と
1920x1080の`m3_system_presentation_fixture.png`へ保存した。

SYSTEM_RESPONSE_FILTERはこのwhitelistより前に適用する。短答候補に対して前1〜3件、後1〜2件を参照し、
明示的SYSTEM target/promptがある場合、または前後のsystem処理で挟まれている場合だけSYSTEM responseとする。
今回の`yes`は前後の`DICE_RESULT`に挟まれていたためHIGH confidenceで`HIDE`となった。
`SYSTEM_RESPONSE_LEAK`とfalse-positive fixtureはいずれもPASSした。

## PL / PC Identity Compatibility

Presentation専用のPlayerProfile、PCProfile、speaker contextと`resolve_display_identity`を追加した。
同じAI話者でも`PL`なら「魔理沙」、`PC`なら「エレノア教授」を表示できる。現在のNormalized Sessionには
PL/PC modeがないため`UNKNOWN → CURRENT_MAPPING_FALLBACK`とし、既存のPC表示名・音声・立ち絵を維持した。
TRPG本体、Normalized Session、M2の意味は変更していない。

## Dice / SAN

技能名、目標値、1D100出目、文字による成否を表示するDice Overlayを維持した。SANは前後値と
増減を表示し、損失0は`±0`と表示する。previewには両overlayが含まれ、元の構造化値から決定的に
生成されている。

## BGM

SceneにはCALM、INVESTIGATION、TENSION、HORROR、COMBAT、CLIMAX、ENDINGのsemantic categoryを
割り当てる。現在利用可能な曲は`Recollections.mp3`のみなので、物理assetは全categoryで同曲へ
fallbackしている。Preview全長にloopし、発話中はsidechain duckingを行う。

## SE

Diceには`データ解析.mp3`、SANには`心臓の鼓動1.mp3`を疎に配置した。Scene切替SEもimportしたが、
現在のpreviewでは未使用である。SEは音声を妨げないよう-18 dBでmixする。

## Audio Mix

Voice、BGM、SEを別busとして扱う。Voice目標は-20 LUFS、BGMは-24 dB、SEは-18 dB、発話中BGM
ducking、最終limiter 0.95を設定した。出力最大音量は-0.8 dBでclippingなし。AquesTalkの長文・
漢字はローカルVOICEVOXから読みを取得し、元の話者音声profileで生成する。暗黙の異engine fallbackはなく、
expected/actual profile不一致は`VOICE_PROFILE_MISMATCH`でFAILする。

## License Gate

使用中7素材は、提供フォルダ内で出典・ライセンス文書を特定できなかったためUNKNOWNである。
BLOCKED素材は0、local previewは許可、review-ready相当の重大Technical Errorは0だが、公開判定は
falseである。推測によるライセンス補完は行っていない。

## Credits

使用asset ID、提供ファイル名、現在のlicense statusを`credits.txt`へ重複除去して出力した。
正式な作者名・出典・規約が確認できた時点でmanifestを更新し、creditsを再生成する必要がある。

## Fallbacks

- 背景: location-specific → category generic → neutral
- 表情: requested semantic expression →近似表情→NORMAL
- BGM: semantic categoryを保持したまま現在の1曲へ解決

Fallback使用でrenderは停止しないが、不足箇所を報告に残す。外部から代替素材を取得していない。

## Scene Render

`scene_047_script_017`から`scene_048_script_013`までの同じ16 source lineを入力とし、SYSTEM response filterとsystem whitelist適用後の
13 displayed source lineをspeech chunk展開して29 clip、112.5秒としてrenderした。RP、複数話者、
場所移動、技能判定、SAN判定を含む。1920x1080、映像・音声streamあり、missing voice 0、missing
asset 0、black frame 0、字幕overflow 0、timeline不整合0である。全425 edited lineのvisual planも生成済み。

## Human Review

静止画spot checkでは、場所字幕の重複除去、SAN `±0`、字幕の可読性、話者名と本文の領域分離、
セリフ枠、HEAD_ONLY専用slot、KP最外縁、system overlayの視認性を確認した。Iteration 4のBefore/After動画と
SYSTEM response fixtureを保存した。技能失敗後の単独`yes`はAfterのTimeline・字幕・音声に存在しない。
音声込みの最終受入は**PENDING**である。次を人間が確認して初めてPresentation QAを閉じる。

- 誰が話しているか分かり、字幕が読みやすい
- 立ち絵と中立背景が字幕を邪魔しない
- BGMが会話を潰さず、SEがうるさくない
- Dice/SAN表示を直感的に理解できる
- 低編集TRPGリプレイとして自然に最後まで見られる

## Publishability

`LOCAL_PREVIEW`、`PUBLISHABLE = false`。主因は使用中素材のlicense statusがUNKNOWNであること。
機械QA PASSとは独立した判定である。

## Known Limitations

- 悪霊の家および各調査地点の専用背景がなく、全区間が同じ中立背景である。
- 立ち絵は各PC1枚で、口パク、瞬き、実表情差分はない。
- PC2のキャラクターに対応した公式／オリジナル立ち絵が未提供である。
- BGMが1曲のため、semantic categoryは計画上のみ分離され、聴覚上のScene変化はない。
- sidechain compressorでduckingしているが、category別crossfadeとScene単位差分render cacheは次段階。
- HP overlayを必要とする区間は今回のpreviewに含まれず、実映像での受入確認は未実施。
- Full Session render、自動投稿、高度なanimationはM3対象外。
- Presentation Iteration 4のHuman Reviewは未完了であり、`M3 PRESENTATION_NEEDS_ITERATION`を維持する。

## M4 Readiness

全425行のvisual plan、portable asset manifest、license gate、credits、audio mix、resume state、
Scene Previewが揃い、技術的なM4入力構造は完成している。M4へ進む前の最小作業は、悪霊の家に
合う背景の提供またはneutral fallbackの受入、7使用素材の権利情報確定、previewの音声込み人間確認である。

## Presentation Iteration 6

- blank voice assets removed: Timeline参照0、新規生成0。既存cacheは`ORPHANED_INVALID_VOICE_CACHE`として非参照。
- noise regression result: Knife/Final Battleとも空白音声由来burst 0。既知bad fixtureの検出はPASS。
- luck override display result: `目星50 / 59 / 失敗 → 幸運9消費 → 成功扱い`をraw/final分離で表示。
- subtitle line-break changes: 文字数分割からピクセル幅・句読点・文節・禁則優先へ変更。音声chunkは変更していない。
- KP subtitle contrast: near-white本文と2.25px濃灰outlineへ調整。
- speaker-name readability: 38pxを維持し、識別色に高contrast outlineを追加。QA PASS。
- remaining source gaps: ナイフ戦闘処理欠落、ナイフ再発見、地下室扉矛盾、SAN 1D4/1D3、最終戦Narrative richness不足を維持。

M3はCLOSEDにせず、`M3 PRESENTATION_NEEDS_ITERATION / M3 ASSET_INPUT_REQUIRED / M3 LICENSE_REVIEW_REQUIRED`、Human Review PENDINGを維持する。
