# V7 Dialogue UI Default Promotion

## Cause

`V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_V7` applied its
layout through builder-local monkey patches. The shared `dialogue_ui` module and M3
layout configuration still contained the pre-prototype values. V2.7 correctly loaded
those shared defaults, which made the presentation appear to revert.

## Promoted Default

The accepted V7 presentation is now the shared video-production default:

- Dialogue frame: `(0, 660, 1920, 420)`
- Edge anchoring: left `0`, right `1920`, bottom `1080`
- Visible outer gap: left/right/bottom `0px`
- 9-slice boundaries: left `72`, right `72`, top `64`, bottom `72`
- Name plate: `(0, 660, 640, 68)`, centered at `(320, 694)`
- Name font: `62px`
- Dialogue font: `62px`
- Long dialogue minimum: `55px`
- Maximum dialogue lines: `2`
- Speaker icon: `(82, 784, 173, 173)`, scale `1.15`
- Dialogue safe area: `(287, 766, 1561, 278)`

The fully transparent eight-pixel top border was trimmed into a derived asset. The
original external asset was not changed. The accepted derived asset SHA-256 is
`86fc9ecebd4346d88b7ba4226f97a28ddffda87a87704cdb7760aa108fdd6a4b`.

## Implementation

- Shared dialogue layout defaults now contain the V7 geometry and font sizes.
- The M3 presentation configuration selects the trimmed V7 frame asset.
- Frame composition uses V7 9-slice boundaries instead of stretching the image.
- Relative asset sources resolve from the canonical repository root.
- The V2.6/V2.7 builder path now consumes the same shared defaults.
- Windows Unicode image paths are read and written through encoded buffers, keeping
  the production-path regression suite deterministic.

## Validation

- V7 default geometry fixture: PASS
- Name size parity (`name=62px`, `dialogue=62px`): PASS
- Visible left/right/bottom gap: `0/0/0`
- Name/dialogue/icon collision and overflow fixtures: PASS
- Video Agent regression: `274 passed`

Existing V13 source and V1 through V2.7 rendered artifacts were not modified. The new
defaults apply to subsequent video builds.
