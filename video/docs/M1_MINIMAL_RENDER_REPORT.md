# M1 Minimal Render Pipeline 実装・検証レポート

## 総合判定

**M1 NEEDS_ITERATION**

Minimal Render Pipelineの実装、実AquesTalk・実VOICEVOX統合、Synthetic/Real SessionのMP4生成、Technical QA、目視フレーム確認までは完了した。残件は、人間による最終的な音声再生確認だけである。自動検査では音声stream、全WAVの非無音、両engineの音量差、Timeline同期を確認しているが、聞き取りや発音の自然さは機械検査で代替しない。

## Environment

- Python: 3.12.10
- FFmpeg / ffprobe: YukkuriMovieMaker v4同梱版 `N-124026-g96f82f4fbb-20260417`
- Video codec: OpenH264 H.264
- Audio codec: AAC（project WAVは48kHz mono PCMへ正規化）
- AquesTalk: YukkuriMovieMaker v4同梱32bit `AquesTalk.dll`、voice type `f1`
- AquesTalk bridge: .NET Framework 32bit helperをローカルでコンパイルし、64bit Pythonから呼出
- VOICEVOX Engine: local `127.0.0.1:50021`、version 0.19.1
- 外部クラウドAPI / LLM呼出: 0
- TRPG本体変更: 0

## Voice Pipeline

`VoiceEngine`抽象の下に`AquesTalkAdapter`と`VoicevoxAdapter`を実装した。cache keyはengine、profile、text、settingsから決定論的に生成する。AquesTalkはCP932互換の読み上げ用textと設定済みvoice type/speedを32bit bridgeへ渡す。VOICEVOXはlocal Engineの`audio_query`と`synthesis`だけを使用する。

同じprofile/textではraw WAVを再生成しない。project WAVはFFmpeg `loudnorm`で48kHz mono PCMへ揃え、SyntheticでAquesTalk -19.45 dB / VOICEVOX -21.38 dB、RealでAquesTalk -19.55 dB / VOICEVOX -21.15 dBとなった。全WAVは非無音である。

VOICEVOXへ接続できない場合は`BLOCKED_VOICE_ENGINE`へ遷移し、silent fallbackを行わない。

## Subtitle Pipeline

話者名と本文を別fieldとしてASSへ出力した。本文は外側10px、内側5px、本文色の3 layerでmulti-outlineを構成する。34文字単位の自動改行、最大4行、100文字超で48pxへ縮小する。Synthetic/Realとも`subtitle_overflow_zero: PASS`である。

実Sessionの字幕本文はNormalized Eventの`text`を完全一致で保持した。AquesTalkの`voice_text`だけ、読みに必要なかな表記へ分離した。

## Portrait Pipeline

M1専用の決定論的な静止画を2点生成し、Asset Manifestで`TEST_ONLY`として管理した。AquesTalk話者を左、VOICEVOX話者を右へ表示し、KPは立ち絵なしとした。話者ごとに表示する画像を切り替える。

## Background Pipeline

決定論的なfallback背景を1点生成し、`TEST_ONLY`としてManifest経由で解決した。両QA reportに`FALLBACK_BACKGROUND_USED`と`NON_PUBLISHABLE_ASSET_USED`を記録した。成果物は公開可能判定ではない。

## Timeline

`video_timeline.json`にclip ID、Normalized Eventと元logのsource event ID、開始時刻、実WAV由来の長さ、speaker、voice engine、字幕、背景、立ち絵、dice overlayを保持した。同一入力ではTimeline SHA-256が一致する。

初回実装の画像concatでは、入力時刻基準と30fps出力の間に字幕・立ち絵切替の遅延が見つかった。各clipを実durationどおりのH.264/AAC segmentへ変換し、segment concat後に全体字幕を焼き込む方式へ修正した。最終目視では18秒時点のSynthetic Dice clipと20秒時点のReal KP clipがTimelineどおり一致した。

## Renderer

出力は1920×1080、30fps、H.264 video + AAC audioである。Pythonが固定commandを構築し、LLMはFFmpeg command生成に関与しない。FFmpeg/ffprobeの絶対pathはconfigで変更できる。

## Dice Overlay

Normalized Eventのdice fieldから、技能、目標値、1D100出目、成否を画面上部へ静的表示する。Synthetic `70 / 42 / 成功`、Real Session `65 / 93 / 失敗`と`50 / 95 / 失敗`を確認した。

## Resume

`NEW`、`SCRIPT_READY`、`VOICE_READY`、`TIMELINE_READY`、`RENDERED`、`QA_PASSED`、`COMPLETED`と異常状態を定義した。voice cacheによりRender再試行時もengine synthesisを再実行しない。Timeline/voice単独CLIを用意した。

## Technical QA

両fixtureで以下がPASSした。

- MP4存在、ffprobe読込
- 30–60秒
- 1920×1080 / 30fps
- H.264 video stream / AAC audio stream
- WAV、subtitle、portrait、background欠落0
- unresolved asset 0
- timeline overlap 0
- subtitle overflow 0
- black frameなし
- silent voice 0
- AquesTalk / VOICEVOX混在
- speaker/profile mapping一致
- clip provenance 100%
- engine別平均音量差6 dB未満

## Synthetic Test

- 出力: `projects/m1_synthetic/output/m1_synthetic.mp4`
- duration: 34.636秒
- 6 lines
- Timeline SHA-256: `3d98e07193de51776dc92dad61a959256acaf2f2ed3eb4b9378f7e10c88604f6`
- Technical QA: PASS

## Real Session Test

- 入力: `projects/corbitt_clear_001/normalized_session.json`
- 固定Normalized Event: `000161`、`000162`、`000165`、`000166`、`000167`、`000169`
- 出力: `projects/m1_real_session/output/m1_real_session.mp4`
- duration: 55.787秒
- 6 lines
- Timeline SHA-256: `00fbf6017a80a0e09e116de5ab7921f378a48850553a1f603182facb90d88d37`
- 発言本文改変: 0
- Technical QA: PASS

## M0 Regression

M0 18件を含む全41テストがPASSした。M0 formal normalized sessionのSHA-256は`02C30843753501B5718E0D1D03320489F13AEB958EE8FCB6A5C625BB07FEDB1F`のままである。

## Known Limitations

- 人間による最終音声再生確認が残っている。
- 仮背景・仮立ち絵は`TEST_ONLY`で、公開不可。
- AquesTalkの利用条件はYMM4同梱license noticeの記録に留め、収益化条件を推測していない。
- 実SessionのAquesTalk読みはfixtureに手動指定しており、任意漢字文の自動読み変換は未実装。
- 表情、口パク、瞬き、BGM、SE、編集判断はM1対象外。

## M2 Readiness

Normalized SessionからWAV、Timeline、字幕、画像、MP4、Technical QAまでの最小経路は成立している。ただしExit CriteriaのHuman Spot Checkが未完了なので、現時点ではM2へ移行しない。両MP4を人間が再生し、声、発音、字幕同期を確認して問題がなければ、判定を`M1 PASS / CLOSED`へ更新できる。
