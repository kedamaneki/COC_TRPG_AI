import json
from pathlib import Path
d=json.loads(Path("save_autosave.json").read_text(encoding="utf-8"))
app=d["app_state"]
sm=d.get("scenario_manager") or {}
gs=d.get("game_state") or {}
lines=[]
lines.append("META")
lines.append("loc=%s / sm=%s" % (app.get("current_loc"), sm.get("location")))
lines.append("phase=%s" % sm.get("current_phase"))
lines.append("guard=%s" % app.get("autonomous_guard"))
lines.append("paused=%s reason=%s running=%s step=%s" % (app.get("autonomous_paused"), app.get("autonomous_pause_reason"), app.get("is_running"), app.get("autonomous_step_count")))
lines.append("hint=%r" % (app.get("stagnation_pl_hint"),))
lines.append("last_pl=%s" % json.dumps(app.get("last_pl_action"), ensure_ascii=False))
lsr=app.get("last_system_result")
if lsr:
    lines.append("last_sys status=%s blocked=%s action=%s target=%s roll=%s" % (lsr.get("status"), lsr.get("blocked"), lsr.get("action_id"), lsr.get("target"), lsr.get("roll_type")))
    lines.append("last_sys_log=%s" % str(lsr.get("log") or "")[:1000])
else:
    lines.append("last_sys=None")
lines.append("FLAGS_SM")
for k,v in sorted((sm.get("flags") or {}).items()):
    if v not in (False, 0, [], None, ""):
        lines.append("  %s = %s" % (k,v))
inv=(sm.get("flags") or {}).get("investigated_targets")
lines.append("investigated=%r" % (inv,))
lines.append("FLAGS_GS")
for k,v in sorted((gs.get("flags") or {}).items()):
    if v not in (False, 0, [], None, ""):
        lines.append("  %s = %s" % (k,v))
lines.append("EVENTS")
for i,e in enumerate(app.get("all_events_log") or []):
    meta=e.get("meta") or {}
    text=str(e.get("text") or "").replace("\n", " / ")
    if len(text)>280:
        text=text[:280]+"..."
    extra=[]
    for k in ("pc_id","forced_progress_breakout","forced_by_system","validation_retry_breakout","error_code","stagnation_interrupt","needs_system","system_processed","roll_type","validation_error","invalidated_by_move"):
        if meta.get(k) not in (None, False, ""):
            extra.append("%s=%s" % (k, meta.get(k)))
    lines.append("[%d] ch=%s loc=%s a=%s t=%s %s" % (i, e.get("channel"), e.get("location"), meta.get("action_id"), meta.get("target"), " ".join(extra)))
    lines.append("  "+text)
Path("_new_log_dump.txt").write_text("\n".join(lines), encoding="utf-8")
print("ok events", len(app.get("all_events_log") or []))
