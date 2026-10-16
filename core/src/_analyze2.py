import json
from pathlib import Path
d=json.loads(Path("save_autosave.json").read_text(encoding="utf-8"))
app=d["app_state"]
sm=d.get("scenario_manager") or {}
gs=d.get("game_state") or {}
lines=[]
lines.append("META loc=%s step=%s paused=%s reason=%s running=%s" % (app.get("current_loc"), app.get("autonomous_step_count"), app.get("autonomous_paused"), app.get("autonomous_pause_reason"), app.get("is_running")))
lines.append("guard=%s" % app.get("autonomous_guard"))
lines.append("hint=%r" % (app.get("stagnation_pl_hint"),))
lines.append("last_pl=%s" % json.dumps(app.get("last_pl_action"), ensure_ascii=False))
lsr=app.get("last_system_result")
lines.append("last_sys=%s" % (None if not lsr else json.dumps({k:lsr.get(k) for k in ("status","blocked","action_id","target","roll_type")}, ensure_ascii=False)))
if lsr: lines.append("last_sys_log=%s" % str(lsr.get("log") or "")[:700])
flags=sm.get("flags") or gs.get("flags") or {}
lines.append("FLAGS truthy:")
for k,v in sorted(flags.items()):
    if v not in (False,0,[],None,""):
        lines.append("  %s=%s" % (k,v))
lines.append("investigated=%r" % flags.get("investigated_targets"))
lines.append("accessed=%r" % flags.get("accessed_clipping_files"))
lines.append("EVENTS")
for i,e in enumerate(app.get("all_events_log") or []):
    meta=e.get("meta") or {}
    text=str(e.get("text") or "").replace("\n"," / ")
    if len(text)>240: text=text[:240]+"..."
    extra=[]
    for k in ("pc_id","forced_progress_breakout","forced_by_system","validation_retry_breakout","error_code","stagnation_interrupt","needs_system","system_processed","roll_type","validation_error"):
        if meta.get(k) not in (None,False,""):
            extra.append("%s=%s" % (k,meta.get(k)))
    lines.append("[%d] ch=%s loc=%s a=%s t=%s %s" % (i,e.get("channel"),e.get("location"),meta.get("action_id"),meta.get("target")," ".join(extra)))
    lines.append("  "+text)
Path("_new_log_dump2.txt").write_text("\n".join(lines), encoding="utf-8")
print("events", len(app.get("all_events_log") or []))
