"""Create a read-only V6 progression timeline and intervention audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def classify(event: dict) -> list[str]:
    if int(event.get("progress_delta") or 0) <= 0:
        return []
    kind = str(event.get("event_type") or "")
    action = str(event.get("selected_action") or "")
    labels = []
    if kind == "LOCATION_CHANGE" or action == "move":
        labels.append("ACCESS")
    if kind.startswith("COMBAT") or action in {"attack", "evade", "damage"}:
        labels.append("COMBAT")
    before = ((event.get("state_before") or {}).get("flags") or {})
    after = ((event.get("state_after") or {}).get("flags") or {})
    if any(before.get(key) != value for key, value in after.items()):
        labels.append("FACT")
    if kind in {"SPECIAL_OBJECTIVE_COMPLETED", "GOAL_COMPLETED", "SCENARIO_COMPLETED"}:
        labels.append("GOAL")
    if not labels:
        labels.append("FACT")
    return labels


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run = args.run.resolve()
    output = args.output.resolve()

    watched = [run / "result.json", run / "session-log.json", run / "unified-event-log.json"]
    before = {str(path): sha256(path) for path in watched}
    events = read_json(run / "unified-event-log.json")
    session = read_json(run / "session-log.json")

    timeline = []
    previous_offset = 0
    event_to_cycle = {}
    for cycle_dir in sorted((run / "checkpoints").glob("cycle_*")):
        state = read_json(cycle_dir / "state.json")
        evaluator = state["evaluator_state"]
        scenario = state["scenario_manager"]
        session_state = state["session_state"]
        director = session_state.get("director_v2") or {}
        offset = int(evaluator.get("event_log_offset") or 0)
        cycle_events = events[previous_offset:offset]
        cycle_number = int(cycle_dir.name.rsplit("_", 1)[1])
        for item in cycle_events:
            if item.get("event_id"):
                event_to_cycle[item["event_id"]] = cycle_number
        progress = []
        counts = {key: 0 for key in ("FACT", "ACCESS", "GOAL", "COMBAT")}
        for item in cycle_events:
            labels = classify(item)
            if not labels:
                continue
            for label in labels:
                counts[label] += 1
            progress.append({
                "event_id": item.get("event_id"),
                "turn_id": item.get("turn_id"),
                "types": labels,
                "action": item.get("selected_action"),
                "target": item.get("target"),
                "origin": item.get("action_origin"),
                "progress_delta": item.get("progress_delta"),
            })
        goal = director.get("goal") or {}
        timeline.append({
            "cycle": cycle_number,
            "turn": scenario.get("turn_counter"),
            "event_offset": offset,
            "location": scenario.get("location"),
            "phase": scenario.get("current_phase"),
            "progress_counts": counts,
            "progress_events": progress,
            "no_progress_streak": ((director.get("stall") or {}).get("no_progress_streak")),
            "intervention_level": ((director.get("stall") or {}).get("intervention_level")),
            "location_objective_status": director.get("location_objective_status"),
            "action_phase": director.get("action_phase"),
            "candidate_next_actions": goal.get("candidate_next_actions") or [],
            "blocked_requirements": goal.get("blocked_requirements") or [],
            "remaining_requirements": goal.get("remaining_requirements") or [],
        })
        previous_offset = offset

    action_meta = {}
    for row in session:
        meta = row.get("meta") or {}
        tx = meta.get("transaction_id")
        if tx and meta.get("original_action"):
            action_meta[tx] = {
                "original_action": meta.get("original_action"),
                "intent_replaced": bool(meta.get("intent_replaced")),
                "forced_progress": bool(meta.get("forced_progress")),
                "auto_corrected": bool(meta.get("auto_corrected")),
            }
    interventions = []
    for item in events:
        origin = item.get("action_origin")
        if origin not in {"SYSTEM_GUIDED", "SYSTEM_FORCED"}:
            continue
        details = action_meta.get(item.get("transaction_id"), {})
        interventions.append({
            "cycle": event_to_cycle.get(item.get("event_id")),
            "turn_id": item.get("turn_id"),
            "event_id": item.get("event_id"),
            "origin": origin,
            "recommended_or_selected": {
                "action": item.get("selected_action"), "target": item.get("target")
            },
            "original_pl_action": details.get("original_action"),
            "was_rewrite": bool(
                origin == "SYSTEM_FORCED"
                or details.get("intent_replaced")
                or details.get("auto_corrected")
            ),
            "progress_delta": int(item.get("progress_delta") or 0),
            "progress_result": "PROGRESS" if int(item.get("progress_delta") or 0) > 0 else "NO_PROGRESS",
        })

    meaningful = [row for row in timeline if sum(row["progress_counts"].values())]
    last_progress = meaningful[-1]["cycle"] if meaningful else None
    sustained = next((
        row["cycle"] for row in timeline
        if row["cycle"] >= (last_progress or 0)
        and int(row.get("no_progress_streak") or 0) >= 3
    ), None)
    after = {str(path): sha256(path) for path in watched}
    report = {
        "session_id": run.name,
        "classification_contract": {
            "FACT": "new scenario/world-state fact",
            "ACCESS": "location or route access change",
            "GOAL": "goal/terminal completion",
            "COMBAT": "combat lifecycle or combat result",
        },
        "last_meaningful_progress_cycle": last_progress,
        "first_sustained_stagnation_cycle": sustained,
        "timeline": timeline,
        "interventions": interventions,
        "intervention_summary": {
            "system_guided": sum(x["origin"] == "SYSTEM_GUIDED" for x in interventions),
            "system_forced": sum(x["origin"] == "SYSTEM_FORCED" for x in interventions),
            "guided_progress": sum(x["origin"] == "SYSTEM_GUIDED" and x["progress_delta"] > 0 for x in interventions),
            "forced_progress": sum(x["origin"] == "SYSTEM_FORCED" and x["progress_delta"] > 0 for x in interventions),
        },
        "raw_read_only_hash_check": {"before": before, "after": after, "unchanged": before == after},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
