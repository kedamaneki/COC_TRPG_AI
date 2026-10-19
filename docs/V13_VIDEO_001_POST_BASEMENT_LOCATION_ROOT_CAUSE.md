# V13 Video 001 Post-Basement Location Root Cause

## Classification

`VIDEO_SCRIPT_BACKGROUND_COLLAPSE`

The accepted V13 source is historically valid for this slice. Unified and normalized event order contains an explicit basement exit, house movement, and a formal return before the next board interaction. TABLE LOG also contains the return caption. V2.4 introduced the visible contradiction by assigning the basement background to every Script and Timeline item regardless of `scene_state.current_location`.

## First divergence boundary

`video/tools/build_v13_video_001_v2_4.py` converted the correct `table_019/020` house context into `background_asset_id=aipict_basement_ruins01`. The renderer then displayed the basement continuously.

## Runtime prevention

Candidates, S4 bindings, and object interactions now carry `required_location`. A location mismatch becomes `REQUIRES_RETURN`, with `reachable=false` and `executable=false`. Execution rechecks the same required location. S4 may bind only a route that is executable at the current location and still does not force success.

## Presentation prevention

V2.5 audits table, script, timeline, and background location as one sequence. PL/PC/KP portraits are speaker icons only; persistent Scene Actor entries are reserved for source-present NPCs.
