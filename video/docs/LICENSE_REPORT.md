# M3 License Report

## Current result

The preview uses seven assets whose license metadata could not be established from the
provided folders. They are retained as `UNKNOWN`. Local preview is allowed, but
`PUBLISHABLE = false` and `NON_PUBLISHABLE_ASSET_USED` is active.

The transition SE was imported and hashed but is not used by the current preview.

## Used assets requiring review

- `portrait_pc01_kitsune_reimu` — `200.png`; creator/license/commercial use/credit unknown
- `portrait_pc02_kitsune_marisa` — `200.png`; creator/license/commercial use/credit unknown
- `bg_neutral_user` — `nc321164_シンプル同系色モロッカン柄背景【紫】（1920×1080）.png`; metadata unknown
- `dialogue_frame_user` — `nc86017_【素材】セリフ枠.png`; metadata unknown
- `bgm_investigation_user` — `Recollections.mp3`; metadata unknown
- `se_dice_user` — `データ解析.mp3`; metadata unknown
- `se_san_user` — `心臓の鼓動1.mp3`; metadata unknown

Machine-readable file-by-file paths, hashes, tags, and gate results are in
`projects/corbitt_clear_001/license_report.json`. The generated provisional credit list
is in `projects/corbitt_clear_001/credits.txt`; it intentionally identifies unknown
metadata rather than inventing attribution.

## Publication gate

Publication requires verified creator/source, license, commercial-use permission, and
credit text for every used asset. Until then, the output remains `LOCAL_PREVIEW` even
when technical QA passes.
