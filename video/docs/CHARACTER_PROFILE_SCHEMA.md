# Character and Presentation Profiles

Character profiles reference three independent IDs: `voice_profile_id`, `subtitle_profile_id`, and `portrait_profile_id`. Source actors are assigned separately in each project's `character_map.json`; M0 performs no automatic casting.

Voice engines are `AQUESTALK`, `VOICEVOX`, and `NONE`. AquesTalk profiles carry voice type, reading speed, playback pitch, volume, pan, post-silence, and version. VOICEVOX profiles carry speaker UUID, style ID, speed, pitch, intonation, and volume scales. Nullable values mean unconfigured.

Subtitle profiles store font family by environment reference, size, color, alignment, line height, letter spacing, opacity, optional position, and ordered outline layers. Font files are not distributed.

Portrait profiles store source type, asset pack reference, character, default and supported semantic expressions, and optional blink/mouth capability. KP uses the `NONE` portrait.
