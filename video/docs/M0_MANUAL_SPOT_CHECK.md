# M0 Manual Spot Check

The generated normalized records retain each complete source payload, allowing direct comparison without reopening the original file.

## Start

- Normalized: `norm:session:000000`
- Source: `session_log:000000`
- Type: `SYSTEM_INTERNAL`
- Text matches the session start record exactly.

## Middle

- Normalized: `norm:session:000160`
- Source: `session_log:000160`
- Location: `corbitt_ground_floor`
- Type: `KP_DESCRIPTION`
- The complete KP description of the living room and basement door matches the source payload.

## Combat

- Normalized: `norm:unified:000280`
- Source: `evt_000281_8ba6d10a737f77975b2f`
- Type: `COMBAT_START`
- Combat ID and structured combat payload are retained from the Unified Event Log.

## Ending

- Normalized: `norm:session:000382`
- Source: `session_log:000382`
- Location: `corbitt_basement_room2`
- Type: `ENDING`
- The combat termination and curse-resolution text matches the final source log entry exactly.

No source record is dropped. All 383 session-log text records appear byte-for-byte as event text in the normalized output.
