# Presentation Mode Specification v0.1

## VOICED

Voice and subtitle. Used for ordinary KP, PC, and NPC speech after safe log-prefix cleanup.

## SUBTITLE_ONLY

Visible text without synthesized speech. Used for location transitions and system-origin narrative that should not be attributed to a PC voice.

## OVERLAY_ONLY

Structured UI without spoken text. Used for dice, SAN, HP, combat state, clues, and state-change telemetry retained for continuity.

## SILENT_VISUAL

Reserved for later visual staging. M2 does not normally emit it.

## NONE

No replay presentation. Required for `CUT` events. The source remains intact in the Normalized Session and in the event coverage report.

System calculation and result text must never be voiced as the rolling PC. A PC's natural action declaration may remain `VOICED`; the following numerical result is `OVERLAY_ONLY`.
