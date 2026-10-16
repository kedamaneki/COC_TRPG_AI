# Video Production Agent v0.1

M0 implements the deterministic boundary between TRPG logs and future video production.

```powershell
$env:PYTHONPATH="src"
python -m video_agent import-session --input <evaluation-directory> --output <project-directory>
python -m video_agent validate <project-directory>/normalized_session.json
python -m video_agent list-characters
```

M0 performs no rendering, audio generation, LLM calls, or external network access.

## M1 minimal render

M1 renders a fixed 30–60 second fixture with local AquesTalk and local VOICEVOX audio,
speaker subtitles, test-only portraits, a fallback background, and a dice overlay.

```powershell
$env:PYTHONPATH="src"
python -m video_agent render-m1 --project projects/m1_synthetic
python -m video_agent render-m1 --project projects/m1_real_session
python -m video_agent render-voices --project projects/m1_synthetic
python -m video_agent render-video --project projects/m1_synthetic
python -m video_agent validate-render --project projects/m1_synthetic
```

The configured VOICEVOX endpoint is local-only (`127.0.0.1:50021`). If it is unavailable,
the project state becomes `BLOCKED_VOICE_ENGINE`; the pipeline never substitutes silent audio.
Machine-specific engine, FFmpeg, and font paths are kept in `config/render_m1.json`.

## M2 replay editing intelligence

M2 turns every normalized session event into an explicit edit decision, segments the
session into scenes, preserves protected story events, separates system results from
character voices, and builds a before/after review package. It uses deterministic local
rules and makes no external LLM or API call.

```powershell
$env:PYTHONPATH="src"
python -m video_agent edit-m2 --project projects/corbitt_clear_001
python -m video_agent validate-edit --project projects/corbitt_clear_001
```

The review package is written to `projects/corbitt_clear_001/review`. M2 does not render
a full-session video; `preview_before.mp4` and `preview_after.mp4` are short acceptance
samples. A machine `PASS` verifies coverage, provenance, protection, attribution, and
continuity. Human comparison viewing remains the release gate.

## M3 visual/audio presentation

M3 resolves user-provided portraits, backgrounds, BGM, and SE through asset IDs, builds
a full visual plan, and renders a 1–3 minute presentation preview. Unknown license data
is preserved as `UNKNOWN`: local preview is allowed, but the result is not publishable.

```powershell
$env:PYTHONPATH="src"
python -m video_agent present-m3 --project projects/corbitt_clear_001
python -m video_agent validate-presentation --project projects/corbitt_clear_001
```

The output is `projects/corbitt_clear_001/review/m3_scene_preview.mp4`. Missing
scenario backgrounds are reported in `missing_assets_report.json`; the pipeline does
not download or generate replacements.
