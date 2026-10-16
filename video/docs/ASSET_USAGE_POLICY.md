# Asset Usage Policy

## Principle

M3 v0.1 uses `USER_PROVIDED_FIRST`. The presentation pipeline combines assets supplied
or explicitly approved by the user. It does not search the web, download replacements,
or generate missing backgrounds.

The source order is:

1. user-provided assets
2. scenario-provided official assets
3. assets from a library with explicit permission
4. project generic assets
5. an identified fallback

## Import and identity

Supported imported formats are PNG, JPG/JPEG, WEBP, WAV, MP3, and OGG. Every imported
file receives an `asset_id`; render timelines refer to that ID and never to the original
absolute Windows path. Imported files are copied under the project's
`scenario_assets/<scenario>` tree and recorded with SHA-256 so the project can be moved
or resumed.

The manifest retains `asset_id`, type, project-relative path, source, creator, license,
commercial-use status, credit requirement/text, status, tags, and file hash. Missing
metadata remains `UNKNOWN`; the importer does not infer ownership or permission from a
file name.

## License gate

- `BLOCKED`: cannot be used for preview or publication.
- `UNKNOWN`: may be used only for local preview, emits `NON_PUBLISHABLE_ASSET_USED`, and
  requires human license review before publication.
- approved but noncommercial: cannot be marked publishable for commercial use.
- approved and commercially usable: may contribute to `PUBLISHABLE` when every used
  asset meets the same condition.

Machine presentation QA and publication status are separate. A technically valid
preview can remain `LOCAL_PREVIEW`.

## Fallbacks

Portrait expressions use semantic names. For example, `SCARED` falls back through
`SURPRISED` to `NORMAL`. Backgrounds fall back from a location-specific image to a
category image and then to a neutral background. Each fallback is recorded in the
visual plan or missing-assets report. A fallback keeps rendering available; it does not
silently claim that a requested asset exists.

## Human review

Before publication, a reviewer must verify the source, license, commercial-use terms,
required credits, and any character or scenario-specific conditions for every used
asset. Updating that metadata and accepting the rendered presentation are explicit
release gates.
