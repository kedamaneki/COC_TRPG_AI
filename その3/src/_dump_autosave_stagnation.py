# -*- coding: utf-8 -*-
import json
from pathlib import Path

d = json.loads(Path("save_autosave.json").read_text(encoding="utf-8"))
app = d.get("app_state") or {}
logs = app.get("all_events_log") or []

print("=== LAST SYSTEM RESULT ===")
print(json.dumps(app.get("last_system_result"), ensure_ascii=False, indent=2)[:3000])
print("=== AUTONOMOUS GUARD ===")
print(json.dumps(app.get("autonomous_guard"), ensure_ascii=False, indent=2))
print("=== TIMELINE PENDING ===")
print(json.dumps(app.get("timeline_pending"), ensure_ascii=False, indent=2)[:1000])
print("=== FLAGS (relevant) ===")
sm = d.get("scenario_manager") or {}
flags = sm.get("flags") or {}
for k in sorted(flags):
    v = flags[k]
    if v in (False, 0, [], None, ""):
        continue
    print(f"  {k} = {v}")
print("investigated_targets =", flags.get("investigated_targets"))
print("accessed_clipping_files =", flags.get("accessed_clipping_files"))
print("=== EVENTS (%d) ===" % len(logs))
for i, e in enumerate(logs):
    meta = e.get("meta") or {}
    text = str(e.get("text") or "").replace("\n", " | ")
    if len(text) > 240:
        text = text[:240] + "…"
    bits = [
        f"[{i}]",
        f"ch={e.get('channel')}",
        f"loc={e.get('location')}",
        f"action={meta.get('action_id')}",
        f"target={meta.get('target')}",
    ]
    for key in (
        "forced_progress_breakout",
        "forced_by_system",
        "validation_retry_breakout",
        "error_code",
        "validation_error_code",
        "needs_system",
        "system_processed",
        "blocked",
        "roll_type",
    ):
        if meta.get(key) not in (None, False, ""):
            bits.append(f"{key}={meta.get(key)}")
    print(" ".join(bits))
    print("   ", text)
