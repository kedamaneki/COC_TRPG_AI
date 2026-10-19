# Runtime Dependency Manifest

- Python: 3.11 or newer; validated with 3.12.10.
- Python packages: `requirements-portability.txt`; install `video` with `pip install -e video`.
- FFmpeg and FFprobe: required for rendering; configure `FFMPEG_PATH` and `FFPROBE_PATH`.
- AquesTalk runtime: required for active voiced profiles; configure `VOICE_RUNTIME_PATH`. It is not included in Git and redistribution must follow its license.
- C# compiler: required to build the local AquesTalk bridge; configure `CSC_PATH`.
- Font: Noto Sans JP; configure `VIDEO_FONT_PATH`. Font files are not committed.
- VOICEVOX: only for profiles that use it; local endpoint configured by `VOICEVOX_URL`.
- Ollama: local Core runtime endpoint, normally `127.0.0.1:11434`; no cloud API is required.
- Node/npm: not required by the Core or Video test suites in this checkpoint.

Machine-readable details are in `manifests/RUNTIME_DEPENDENCIES.json`. Runtime binaries, voice
engines, fonts, videos, audio, Raw Runs, caches, and local configuration remain outside Git.
