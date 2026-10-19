# External Asset Manifest

`VIDEO_ASSET_ROOT` is the root that currently corresponds to the material collection. Its drive
letter is not part of the contract. Video 002 requires the following external files:

- `外部取得素材/backgrounds/basement/AIPICT/aipict_basement_ruins01.png`
- `外部取得素材/bgm/tension/itch.io/itch_arkeia_tension_as_the_light_fades.ogg`
- `効果音素材/nc42340_ダイス音・2（2D10）.wav`

Exact hashes, license state, approval state, and scope are in
`manifests/PORTABILITY_EXTERNAL_ASSETS.json`. The Corbitt portrait and V7 dialogue frame are small,
approved repository assets and are verified by the same tool. No external asset is automatically
approved merely because it exists on another PC.

Migration order: attach the existing external HDD, copy the tree, or choose another directory and
change only `VIDEO_ASSET_ROOT`.
