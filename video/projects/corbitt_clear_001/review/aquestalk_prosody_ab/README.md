# AquesTalk Prosody A/B Review

各話者の同じ番号を次の順で試聴する。

1. `agent_current`: Presentation Iteration 2相当。読点・長さ境界で分割後にWAV連結。
2. `agent_candidate`: Presentation Iteration 3候補。自然な発言または文を1回で合成。
3. `reference_yymm4`: インストール済みYMM4同梱の同一AquesTalk DLLへ直接入力したengine reference。

霊夢、魔理沙とも3台詞ある。文章、voice type、reading speed、pitch 100%は同一である。

`reference_yymm4`はYMM4アプリのフロントエンドから書き出した音声ではない。YMM4固有の読み・アクセント解析を
含む完全比較には、同じ文章をYMM4から書き出してこのフォルダの対応WAVと差し替える必要がある。
詳細な入力値とSHA-256は`manifest.json`に記録している。
