# Asset Manifest Schema

Each asset has `asset_id`, `type`, `file_path`, `source`, `author`, `license`, `commercial_use`, `credit_required`, `credit_text`, `status`, and `tags`.

Statuses are `APPROVED`, `NONCOMMERCIAL_ONLY`, `REQUIRES_CREDIT`, `UNKNOWN`, and `BLOCKED`. `UNKNOWN` is valid at M0 and emits a warning; future public rendering must not select it automatically.

Scenario asset packs separately group backgrounds, NPC portraits, UI, optional BGM/SE, generic mob tags, and fallback priority. M0 contains references and semantic tags only.
