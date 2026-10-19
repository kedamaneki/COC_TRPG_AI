# V13 Video 001 Location Consistency Trace

## Authoritative sequence

- Raw offset `95`: first `corbitt_basement -> corbitt_ground_floor` exit.
- Raw offset `97`: valid return to `corbitt_basement`; this is the first post-exit current-basement reference.
- Raw offset `146`: the basement exit selected for the replay's “house exploration” transition.
- Raw offsets `173, 225, 227, 229`: movement within the house while the board remains non-current context.
- Raw offset `231`: formal `corbitt_ground_floor -> corbitt_basement` return.
- Raw offset `232`: only after that return, `push / basement_planks` becomes available.
- Raw offset `233`: the push is adjudicated at `corbitt_basement` (`24 / 55`, hard success).

## Layer trace

- Raw / Unified: location order is valid; no board interaction occurs outside the basement.
- Formal Normalizer: preserves offset `146` exit and offset `231` return as separate `LOCATION_CHANGE` events.
- Progression / S4: offset `229` selects a move to the ground floor, offset `231` returns to the basement, then offset `232` exposes the push route.
- TABLE LOG: `table_019/020` represents house exploration, `table_021` explicitly represents the return, and `table_022+` resumes basement context.
- V2.4 Video Script / Timeline: overwrote every background with `aipict_basement_ruins01`, including `table_019/020`. This is the first stale visual-context boundary.
- V2.5: uses `bg_neutral_user` for `corbitt_house_interior`, restores the basement background only at `table_021`, and keeps every location gate at zero.
