"""Run a reproducible non-Streamlit investigation evaluation session.

The runner uses an isolated data directory so PC/NPC and learned datasets in
the working copy are not mutated by evaluation runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import signal
import statistics
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import main
import EvaluationCheckpoint as evaluation_checkpoint
from EventIdentity import append_unified_event
from ProgressDirectorV2 import count_forced_from_action_origin


def event_metrics(events):
    """Derive report metrics from committed unified events."""
    declared = [e for e in events if e.get("event_type") == "INVESTIGATION_DECLARED"]
    seen_exact = set()
    seen_target = set()
    seen_other = set()
    same_pc_retry = 0
    repeated_investigation = 0
    other_pc_retry = 0
    for event in declared:
        actor = str(event.get("actor") or "")
        target = str(event.get("target") or "")
        skill = str(event.get("kp_selected_skill") or "")
        version = str(event.get("context_version") or "")
        exact = (actor, target, skill, version)
        target_key = (actor, target, version)
        cross_key = (target, skill, version)
        if exact in seen_exact:
            same_pc_retry += 1
        if target_key in seen_target:
            repeated_investigation += 1
        prior_actors = {item[0] for item in seen_other if item[1:] == cross_key}
        if prior_actors and actor not in prior_actors:
            other_pc_retry += 1
        seen_exact.add(exact)
        seen_target.add(target_key)
        seen_other.add((actor, *cross_key))

    committed = [e for e in events if e.get("scene_id")]
    max_stall = max((int(e.get("stall_count") or 0) for e in committed), default=0)
    no_progress_count = sum(1 for e in committed if int(e.get("progress_delta") or 0) <= 0)
    location_inconsistency = 0
    backtracking_count = 0
    location_history = []
    for event in committed:
        location = str(event.get("location") or "")
        before = str((event.get("state_before") or {}).get("location") or "")
        after = str((event.get("state_after") or {}).get("location") or "")
        if location and (before or after) and location not in {before, after}:
            location_inconsistency += 1
        observed = after or location
        if observed and (not location_history or location_history[-1] != observed):
            if len(location_history) >= 2 and location_history[-2] == observed:
                backtracking_count += 1
            location_history.append(observed)

    blocked_ids = {
        str(e.get("investigation_id") or "")
        for e in events
        if e.get("event_type") == "ATTEMPT_EXHAUSTED" and e.get("result") == "BLOCKED"
    }
    alternative_ids = {
        str(e.get("investigation_id") or "")
        for e in events
        if e.get("alternative_skill_approved")
        and e.get("adjudication") in {"ROLL_WITH_ALTERNATIVE_SKILL", "ROLL_WITH_PROPOSED_SKILL"}
    }
    return {
        "max_stagnation": max_stall,
        "repeated_investigation": repeated_investigation,
        "same_pc_retry": same_pc_retry,
        "same_pc_retry_blocked": len(blocked_ids),
        "other_pc_retry": other_pc_retry,
        "alternative_skills": len(alternative_ids),
        "system_guided": sum(1 for e in committed if e.get("action_origin") == "SYSTEM_GUIDED"),
        "no_progress_count": no_progress_count,
        "backtracking_count": backtracking_count,
        "location_inconsistency": location_inconsistency,
    }


def _load_llm_environment():
    path = ROOT / ".streamlit" / "secrets.toml"
    if not path.is_file():
        return
    with path.open("rb") as fh:
        values = tomllib.load(fh)
    for key in (
        "LLM_BASE_URL", "LLM_API_KEY", "LLM_PL_MODEL", "LLM_KP_MODEL",
        "LLM_JUDGE_MODEL", "LLM_TIMEOUT", "LLM_MAX_TOKENS",
        "PRIMARY_OLLAMA_URL", "SECONDARY_OLLAMA_URL",
        "SECONDARY_FAILURE_POLICY", "EXECUTION_PROFILE",
    ):
        if key in values and key not in os.environ:
            os.environ[key] = str(values[key])


def _isolated_data_dir(output_dir, scenario_file=""):
    runtime = output_dir / "runtime_data"
    runtime.mkdir(parents=True, exist_ok=True)
    for name in ("pcs.json", "npcs.json"):
        shutil.copy2(ROOT / name, runtime / name)
    if scenario_file and (ROOT / scenario_file).is_file():
        shutil.copy2(ROOT / scenario_file, runtime / scenario_file)
    source_data = ROOT / "datasets"
    if source_data.is_dir():
        shutil.copytree(source_data, runtime / "datasets", dirs_exist_ok=True)
    else:
        (runtime / "datasets").mkdir(exist_ok=True)
    return runtime


def _sha256_file(path):
    path = Path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _write_input_manifest(output_dir, runtime, scenario_file):
    """Record exact source/runtime identity and every declared transformation."""
    rows = {}
    for key, source, derived in (
        ("scenario", ROOT / scenario_file, Path(runtime) / scenario_file),
        ("pcs", ROOT / "pcs.json", Path(runtime) / "pcs.json"),
        ("npcs", ROOT / "npcs.json", Path(runtime) / "npcs.json"),
    ):
        source_hash = _sha256_file(source)
        runtime_hash = _sha256_file(derived)
        changed = source_hash != runtime_hash
        rows[key] = {
            "source_path": str(source), "runtime_path": str(derived),
            "source_hash": source_hash, "runtime_hash": runtime_hash,
            "transform_id": "INIT_GAME_SYSTEM_V1" if changed else "IDENTITY",
            "transform_version": 1 if changed else 0,
            "identity_status": "DERIVED_DECLARED" if changed else "EXACT",
        }
    manifest = {
        "schema_version": 1,
        "inputs": rows,
        "run_input_identity": "PASS" if all(
            row["identity_status"] in {"EXACT", "DERIVED_DECLARED"} for row in rows.values()
        ) else "FAIL",
    }
    (Path(output_dir) / "input_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return manifest


def _percentile(values, percentile):
    values = sorted(float(value) for value in values)
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 6)
    position = (len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    weight = position - lower
    return round(values[lower] * (1.0 - weight) + values[upper] * weight, 6)


def _write_llm_performance_summary(output_dir, turns):
    metrics_path = Path(output_dir) / "llm_call_metrics.jsonl"
    rows = []
    if metrics_path.is_file():
        for line in metrics_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))

    def summarize(items):
        prompt = [int(row["prompt_eval_count"]) for row in items if row.get("prompt_eval_count") is not None]
        completion = [int(row["eval_count"]) for row in items if row.get("eval_count") is not None]
        prompt_seconds = [float(row["prompt_eval_duration"]) / 1_000_000_000 for row in items if row.get("prompt_eval_duration")]
        generation_seconds = [float(row["eval_duration"]) / 1_000_000_000 for row in items if row.get("eval_duration")]
        wall_seconds = [float(row.get("wall_duration_seconds") or 0.0) for row in items]
        return {
            "total_calls": len(items),
            "successful_calls": sum(1 for row in items if row.get("status") == "SUCCESS"),
            "failed_calls": sum(1 for row in items if row.get("status") != "SUCCESS"),
            "total_prompt_tokens": sum(prompt),
            "total_output_tokens": sum(completion),
            "average_prompt_tokens": round(statistics.mean(prompt), 6) if prompt else None,
            "average_output_tokens": round(statistics.mean(completion), 6) if completion else None,
            "average_prompt_eval_seconds": round(statistics.mean(prompt_seconds), 6) if prompt_seconds else None,
            "average_generation_seconds": round(statistics.mean(generation_seconds), 6) if generation_seconds else None,
            "average_total_seconds": round(statistics.mean(wall_seconds), 6) if wall_seconds else None,
            "p50_total_seconds": _percentile(wall_seconds, 0.50),
            "p95_total_seconds": _percentile(wall_seconds, 0.95),
            "retry_count": sum(int(row.get("retry_count") or 0) for row in items),
        }

    roles = {
        role: summarize([row for row in rows if row.get("role") == role])
        for role in ("PL", "KP", "JUDGE")
    }
    endpoints = {
        endpoint: summarize([row for row in rows if row.get("endpoint_class") == endpoint])
        for endpoint in ("PRIMARY", "SECONDARY")
    }
    overall = summarize(rows)
    turn_count = max(0, int(turns or 0))
    divisor = turn_count or 1
    summary = {
        "schema_version": 1,
        "duration_unit": "seconds unless field name states otherwise",
        "non_streaming_ttft_available": False,
        "roles": roles,
        "endpoints": endpoints,
        "overall": overall,
        "routing": {
            "REMOTE_JUDGE_CALLS": sum(
                1 for row in rows
                if row.get("llm_role", row.get("role")) == "JUDGE" and row.get("remote")
            ),
            "REMOTE_JUDGE_ERRORS": sum(
                1 for row in rows
                if row.get("llm_role", row.get("role")) == "JUDGE"
                and row.get("remote") and row.get("status") != "SUCCESS"
            ),
            "REMOTE_JUDGE_RETRIES": sum(
                int(row.get("retry_count") or 0) for row in rows
                if row.get("llm_role", row.get("role")) == "JUDGE" and row.get("remote")
            ),
            "REMOTE_JUDGE_FALLBACKS": sum(
                1 for row in rows
                if row.get("llm_role", row.get("role")) == "JUDGE"
                and row.get("fallback_triggered")
            ),
            "PL_REMOTE_CALLS": sum(1 for row in rows if row.get("role") == "PL" and row.get("remote")),
            "KP_REMOTE_CALLS": sum(1 for row in rows if row.get("role") == "KP" and row.get("remote")),
        },
        "per_turn": {
            "turns": turn_count,
            "llm_calls": round(len(rows) / divisor, 6),
            "prompt_tokens": round(overall["total_prompt_tokens"] / divisor, 6),
            "completion_tokens": round(overall["total_output_tokens"] / divisor, 6),
            "llm_seconds": round(sum(float(row.get("wall_duration_seconds") or 0.0) for row in rows) / divisor, 6),
        },
    }
    (Path(output_dir) / "llm_performance_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return summary


def _initial_state(scenario_file, char_mgr, scenario_mgr, state_mgr):
    active = main.default_active_pc_ids(char_mgr)
    char_mgr.set_active_pcs(active)
    actor = active[0] if active else "pc_01"
    for pc_id in active:
        char_mgr.begin_session_stats(pc_id)
    state = {
        "all_events_log": [{
            "channel": "OOC", "location": "all", "secret_to": None,
            "text": "[システム] 評価セッションを開始します。",
        }],
        "last_pl_action": None,
        "last_system_result": None,
        "pending_san_check": None,
        "pending_push_roll": None,
        "pending_luck_burn": None,
        "pending_combat_defense": None,
        "pending_decision": None,
        "public_knowledge_ids": [],
        "investigation_flow": {},
        "unified_event_log": [],
        "director_v2": {},
        "partial_system_log": None,
        "push_decision_required": False,
        "timeline_pending": None,
        "intervention_level": "standard",
        "kp_style": "collaborative",
        "stagnation_kp_nudge": None,
        "stagnation_pl_hint": None,
        "stagnation_streak": 0,
        "force_ic_action": False,
        "pl_id": actor,
        "char_name": char_mgr.get_pc_name(actor),
        "active_pcs": list(active),
        "active_pc_id": actor,
        "actor_id": actor,
        "decision_owner_id": actor,
        "pl_discussion_mode": False,
        "pl_discussion_rounds": 0,
        "current_loc": scenario_mgr.location or scenario_mgr.initial_state.get("location", "study"),
        "scenario_file": scenario_file,
        "autonomous_paused": False,
        "autonomous_pause_reason": None,
        "autonomous_pause_class": None,
        "autonomous_user_resumed": False,
        "runtime_load_normalized": True,
        "autonomous_guard": None,
        "autonomous_step_count": 0,
        "autonomous_progress_fp": None,
        "is_running": False,
        "stop_requested": False,
        "pending_action_id": None,
        "last_processed_action_id": None,
    }
    for pc_id in active:
        startup = main.apply_scenario_startup_effects(
            scenario_mgr, state_mgr, char_mgr, pc_id, char_mgr.get_pc_name(pc_id),
        )
        if startup:
            state["all_events_log"].append({
                "channel": "IC", "location": state["current_loc"], "secret_to": None,
                "text": f"システム: {startup['log']}",
                "meta": {"roll_type": "san_check", "kp_narrated": False, "pc_id": pc_id},
            })
    return state


def _summary(state, scenario_mgr, state_mgr, *, session_id, scenario_file, seed, cycles, elapsed):
    events = list(state.get("unified_event_log") or [])
    investigation_events = [e for e in events if str(e.get("event_type") or "").startswith((
        "INVESTIGATION_", "SKILL_", "ATTEMPT_", "INFORMATION_", "KP_RESCUE_", "ROLL_NOT_",
    ))]
    counts = Counter(str(e.get("event_type") or "") for e in investigation_events)
    origins = Counter(str(e.get("action_origin") or "") for e in events if e.get("action_origin"))
    report_metrics = event_metrics(events)
    combat_counts = Counter(
        str(e.get("event_type") or "") for e in events
        if str(e.get("event_type") or "").startswith("COMBAT_")
        or e.get("event_type") in {"NORMAL_PROGRESSION_RESUMED", "POST_COMBAT_RECOVERY_FAILURE"}
    )
    return {
        "session_id": session_id,
        "scenario_file": scenario_file,
        "seed": seed,
        "completed": bool(main.is_game_cleared(scenario_mgr)),
        "phase": scenario_mgr.current_phase,
        "location": scenario_mgr.location,
        "turns": int(state_mgr.turn_count or 0),
        "cycles": cycles,
        "elapsed_seconds": round(elapsed, 3),
        "pause_reason": state.get("autonomous_pause_reason"),
        "unified_events": len(events),
        "investigation_events": dict(counts),
        "skill_proposals": counts.get("SKILL_PROPOSED", 0),
        "skill_approved": counts.get("SKILL_APPROVED", 0),
        "skill_rejected": counts.get("SKILL_REJECTED", 0),
        "information_shared": counts.get("INFORMATION_SHARED", 0),
        "kp_rescue": counts.get("KP_RESCUE_ROUTE_CREATED", 0),
        "system_forced": count_forced_from_action_origin(state),
        "human_interventions": sum(
            1 for event in events if event.get("human_intervention")
        ),
        "action_origins": dict(origins),
        "final_flags": dict(scenario_mgr.flags or {}),
        "combat_ended": combat_counts.get("COMBAT_ENDED", 0),
        "normal_progression_resumed": combat_counts.get("NORMAL_PROGRESSION_RESUMED", 0),
        "post_combat_recovery_failure": combat_counts.get("POST_COMBAT_RECOVERY_FAILURE", 0),
        "combat_state": str(getattr(state_mgr, "combat_state", "") or ""),
        "combat_queue_remaining": len(state_mgr.get_combat_turn_queue()),
        "pending_combat_remaining": bool(
            state.get("pending_combat_defense") or state_mgr.get_pending_combat_defense()
        ),
        **report_metrics,
    }


def _write_partial_snapshot(output_dir, state, scenario_mgr, state_mgr, args, cycles, elapsed):
    summary = _summary(
        state, scenario_mgr, state_mgr, session_id=args.session_id,
        scenario_file=args.scenario, seed=args.seed, cycles=cycles,
        elapsed=elapsed,
    )
    (output_dir / "result.partial.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (output_dir / "unified-event-log.partial.json").write_text(
        json.dumps(state.get("unified_event_log") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "session-log.partial.json").write_text(
        json.dumps(state.get("all_events_log") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def _evaluation_config(args):
    """Configuration that must remain stable across resumed segments."""
    return {
        "scenario": args.scenario,
        "max_cycles": args.max_cycles,
        "max_chain": args.max_chain,
        "intervention_level": "standard",
        "kp_style": "collaborative",
        "runner_schema": 2,
    }


def _fingerprints(args):
    model_config = dict(main.get_llm_config())
    # API keys are credentials, not behavior.  Never persist them in manifests.
    model_config.pop("api_key", None)
    return evaluation_checkpoint.build_fingerprints(
        source_root=ROOT,
        scenario_path=ROOT / args.scenario,
        pc_paths=(ROOT / "pcs.json", ROOT / "npcs.json"),
        model_config=model_config,
        evaluation_config=_evaluation_config(args),
        prompt_paths=(ROOT / "main.py",),
        kp_config={"intervention_level": "standard", "kp_style": "collaborative"},
    )


def _llm_history():
    return {
        "chat_history": list(getattr(main, "_chat_history", []) or []),
        "chat_session": list(getattr(main, "chat_session", []) or [])
        if getattr(main, "chat_session", None) is not None else None,
    }


def _restore_llm_history(history):
    main._chat_history = list(history.get("chat_history") or [])
    saved_session = history.get("chat_session")
    main.chat_session = list(saved_session) if saved_session is not None else None


def _evaluator_state(summary, *, resume_count=0, event_log_offset=0, warnings=None, failures=None):
    return {
        "total_cycles_observed": int(summary.get("cycles") or 0),
        "total_turns_observed": int(summary.get("turns") or 0),
        "forced_action_count": int(summary.get("system_forced") or 0),
        "guided_action_count": int(summary.get("system_guided") or 0),
        "human_intervention_count": int(summary.get("human_interventions") or 0),
        "no_progress_count": int(summary.get("no_progress_count") or 0),
        "maximum_no_progress": int(summary.get("max_stagnation") or 0),
        "backtracking_count": int(summary.get("backtracking_count") or 0),
        "inconsistency_count": int(summary.get("location_inconsistency") or 0),
        "combat_count": int(summary.get("combat_ended") or 0),
        "resume_count": int(resume_count or 0),
        "completed_objectives": [
            key for key, value in (summary.get("final_flags") or {}).items() if value is True
        ],
        "failure_reasons": list(failures or []),
        "warning_counts": dict(Counter(warnings or [])),
        "event_log_offset": int(event_log_offset or 0),
        "metrics_snapshot": dict(summary),
        "elapsed_seconds": float(summary.get("elapsed_seconds") or 0.0),
    }


def _cycle_boundary_warnings(state, state_mgr):
    fields = (
        "pending_decision", "pending_san_check", "pending_push_roll",
        "pending_luck_burn", "pending_combat_defense", "partial_system_log",
        "timeline_pending", "pending_action_id",
    )
    warnings = [f"PENDING_AT_CYCLE_BOUNDARY:{name}" for name in fields if state.get(name)]
    if getattr(state_mgr, "pending_combat_defense", None):
        warnings.append("PENDING_AT_CYCLE_BOUNDARY:state_mgr.pending_combat_defense")
    return warnings


def _resolve_resume_path(args, output_dir):
    if args.resume_latest:
        path = evaluation_checkpoint.latest_checkpoint(output_dir)
        print(f"[evaluation-v2] resume-latest selected: {path}", flush=True)
        return path
    if not args.resume:
        return None
    candidate = Path(args.resume)
    if candidate.exists():
        return candidate.resolve()
    text = str(args.resume).strip()
    if text.startswith("CHECKPOINT_CYCLE_"):
        cycle = int(text.rsplit("_", 1)[-1])
        return output_dir / "checkpoints" / f"cycle_{cycle:06d}"
    if text.startswith("cycle_"):
        return output_dir / "checkpoints" / text
    raise evaluation_checkpoint.CheckpointInvalid(f"checkpoint not found: {args.resume}")


def _resume_audit_event(manifest, segment_id, prior_segment_id, fingerprints, validation=None):
    checkpoint_id = manifest["checkpoint_id"]
    validation = validation or {}
    return {
        "event_id": f"resume_{checkpoint_id}_{segment_id}",
        "event_type": "EVALUATION_RESUMED",
        "evaluation_only": True,
        "checkpoint_id": checkpoint_id,
        "resume_segment_id": segment_id,
        "cycle": manifest.get("cycle"),
        "turn": manifest.get("turn"),
        "prior_segment_id": prior_segment_id,
        "code_hash": fingerprints.get("source_hash"),
        "model": (fingerprints.get("model_config") or {}).get("pl_model"),
        "resume_validation_result": "PASS",
        "original_max_cycles": validation.get("original_max_cycles"),
        "resumed_max_cycles": validation.get("resumed_max_cycles"),
        "max_cycles_extended": bool(validation.get("max_cycles_extended")),
        "compatible_evaluator_migration": (
            (validation.get("compatible_evaluator_migration") or {}).get("migration_id")
        ),
    }


def _limit_extension_event(manifest, validation):
    return {
        "event_type": "EVALUATION_LIMIT_EXTENDED",
        "evaluation_only": True,
        "from_max_cycles": validation.get("original_max_cycles"),
        "to_max_cycles": validation.get("resumed_max_cycles"),
        "checkpoint_id": manifest.get("checkpoint_id"),
        "cycle": manifest.get("cycle"),
        "turn": manifest.get("turn"),
        "reason": "MONOTONIC_RUNTIME_LIMIT_EXTENSION",
    }


def run(args):
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    _load_llm_environment()
    llm_context = {"cycle": 0}
    llm_state = {"manager": None}

    def _llm_metric_context():
        manager = llm_state.get("manager")
        return {
            "cycle": int(llm_context["cycle"]),
            "turn": int(getattr(manager, "turn_count", 0) or 0),
        }

    main.configure_llm_metrics(
        output_dir / "llm_call_metrics.jsonl",
        context_provider=_llm_metric_context,
        reset=not bool(args.resume or args.resume_latest),
    )
    fingerprints = _fingerprints(args)
    resume_path = _resolve_resume_path(args, output_dir)
    loaded = evaluation_checkpoint.load_checkpoint(resume_path) if resume_path else None
    if loaded:
        evaluation_checkpoint.ensure_checkpoint_segment_coverage(output_dir, loaded)
    if loaded:
        saved_session_id = str(loaded["manifest"].get("session_id") or "")
        if args.session_id and args.session_id != saved_session_id:
            raise evaluation_checkpoint.ResumeBlocked(["CHECKPOINT_SESSION_MISMATCH"])
        args.session_id = saved_session_id
    elif not args.session_id:
        raise ValueError("--session-id is required for a new evaluation")

    runtime = output_dir / "runtime_data"
    if loaded and loaded["manifest"].get("runtime_data_present"):
        evaluation_checkpoint.restore_runtime_data(loaded, runtime)
    else:
        runtime = _isolated_data_dir(output_dir, args.scenario)
    runtime_scenario = runtime / args.scenario
    if not runtime_scenario.is_file() and (ROOT / args.scenario).is_file():
        shutil.copy2(ROOT / args.scenario, runtime_scenario)
    os.chdir(runtime)
    random.seed(args.seed)
    char_mgr, dice_engine, state_mgr, scenario_mgr = main.init_game_system(args.scenario)
    _write_input_manifest(output_dir, runtime, args.scenario)
    if loaded:
        state, evaluator_state, llm_history = evaluation_checkpoint.restore_checkpoint(
            loaded, char_mgr=char_mgr, state_mgr=state_mgr, scenario_mgr=scenario_mgr,
            current_fingerprints=fingerprints, seed=args.seed,
            compatible_migration=args.compatible_migration,
        )
        resume_validation = dict(loaded.get("resume_validation") or {})
        fingerprints.update({
            "original_max_cycles": resume_validation.get("original_max_cycles"),
            "resumed_max_cycles": resume_validation.get("resumed_max_cycles"),
            "max_cycles_extended": bool(resume_validation.get("max_cycles_extended")),
            "previous_limit": resume_validation.get("previous_limit"),
            "new_limit": resume_validation.get("new_limit"),
            "resume_checkpoint": loaded["manifest"].get("checkpoint_id"),
            "resume_validation_result": resume_validation.get("validation_result"),
            "compatible_evaluator_migration": resume_validation.get("compatible_evaluator_migration"),
        })
        (output_dir / "resume-validation.json").write_text(
            json.dumps(resume_validation, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        _restore_llm_history(llm_history)
        completed_cycles = int(loaded["manifest"]["cycle"])
        resume_count = int(evaluator_state.get("resume_count") or 0) + 1
        elapsed_before = float(evaluator_state.get("elapsed_seconds") or 0.0)
        start_event_offset = int(loaded["manifest"].get("event_log_offset") or 0)
        start_checkpoint_id = loaded["manifest"]["checkpoint_id"]
        prior_segment_id = loaded["manifest"].get("prior_segment_id")
        if resume_validation.get("max_cycles_extended"):
            append_unified_event(
                state, _limit_extension_event(loaded["manifest"], resume_validation)
            )
        main.begin_autonomous_runtime(state)
    else:
        state = _initial_state(args.scenario, char_mgr, scenario_mgr, state_mgr)
        # Keep ScenarioManager/GameStateManager flags as one source of truth.
        scenario_mgr.bind_game_state(state_mgr)
        main.start_new_ai_session()
        main.begin_autonomous_runtime(state)
        evaluator_state = {}
        completed_cycles = 0
        resume_count = 0
        elapsed_before = 0.0
        start_event_offset = 0
        start_checkpoint_id = None
        prior_segment_id = None

    managers = (char_mgr, dice_engine, state_mgr, scenario_mgr)
    llm_state["manager"] = state_mgr
    segment_id = evaluation_checkpoint.next_segment_id(output_dir)
    resume_event = (
        _resume_audit_event(
            loaded["manifest"], segment_id, prior_segment_id, fingerprints,
            loaded.get("resume_validation"),
        )
        if loaded else None
    )
    segment_start_cycle = completed_cycles + 1
    durable_event_offset = start_event_offset
    durable_start_checkpoint_id = start_checkpoint_id
    metrics_start = dict(evaluator_state.get("metrics_snapshot") or {})
    started = time.monotonic()
    pauses = []
    last_checkpoint_path = resume_path
    safe_stop = {"requested": False}

    def request_safe_stop(signum, _frame):
        safe_stop["requested"] = True
        print(f"[evaluation-v2] SAFE_STOP_REQUESTED signal={signum}", flush=True)

    previous_handlers = {}
    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            sig = getattr(signal, signal_name)
            previous_handlers[sig] = signal.getsignal(sig)
            signal.signal(sig, request_safe_stop)

    segment_budget = args.segment_cycles if args.segment_cycles is not None else args.max_cycles
    segment_end_target = min(args.max_cycles, completed_cycles + max(0, segment_budget))
    try:
        for cycle in range(completed_cycles + 1, segment_end_target + 1):
            llm_context["cycle"] = cycle
            pause = main.run_timeline_loop(
                state, managers, max_iterations=1, max_chain_per_tick=args.max_chain,
            )
            completed_cycles = cycle
            if pause:
                pauses.append(pause)
            elapsed = elapsed_before + (time.monotonic() - started)
            summary = _write_partial_snapshot(
                output_dir, state, scenario_mgr, state_mgr, args, completed_cycles, elapsed,
            )
            evaluator_state = _evaluator_state(
                summary, resume_count=resume_count,
                event_log_offset=len(state.get("unified_event_log") or []),
                warnings=_cycle_boundary_warnings(state, state_mgr),
                failures=[pause] if pause and pause not in {"max_iterations"} else None,
            )
            checkpoint_id = evaluation_checkpoint.checkpoint_id_for_cycle(completed_cycles)
            evaluation_checkpoint.write_durable_segment(
                output_dir, segment_id=segment_id, session_id=args.session_id,
                cycle=completed_cycles, start_event_offset=durable_event_offset,
                events=state.get("unified_event_log") or [],
                start_checkpoint_id=durable_start_checkpoint_id,
                end_checkpoint_id=checkpoint_id,
                resume_from_checkpoint_id=start_checkpoint_id if loaded else None,
                prior_segment_id=prior_segment_id,
            )
            last_checkpoint_path = evaluation_checkpoint.write_checkpoint(
                output_dir, cycle=completed_cycles, session_id=args.session_id,
                seed=args.seed, state=state, char_mgr=char_mgr, state_mgr=state_mgr,
                scenario_mgr=scenario_mgr, evaluator_state=evaluator_state,
                llm_history=_llm_history(), fingerprints=fingerprints,
                prior_segment_id=segment_id,
                runtime_data_dir=runtime,
            )
            durable_event_offset = len(state.get("unified_event_log") or [])
            durable_start_checkpoint_id = checkpoint_id
            print(
                json.dumps({
                    "cycle": cycle, "turn": state_mgr.turn_count,
                    "location": scenario_mgr.location, "phase": scenario_mgr.current_phase,
                    "pause": pause, "clear": main.is_game_cleared(scenario_mgr),
                    "checkpoint": last_checkpoint_path.name,
                }, ensure_ascii=False),
                flush=True,
            )
            if args.early_gate_cycle and cycle == args.early_gate_cycle:
                waiting_path = output_dir / "EARLY_GATE_WAITING.json"
                continue_path = output_dir / "EARLY_GATE_CONTINUE.json"
                abort_path = output_dir / "EARLY_GATE_ABORT.json"
                gate_payload = {
                    "schema_version": 1,
                    "status": "WAITING",
                    "session_id": args.session_id,
                    "cycle": cycle,
                    "checkpoint_id": checkpoint_id,
                    "resume_count": resume_count,
                    "required_continue_file": continue_path.name,
                    "abort_file": abort_path.name,
                }
                temporary_path = waiting_path.with_suffix(".json.tmp")
                temporary_path.write_text(
                    json.dumps(gate_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(temporary_path, waiting_path)
                print(
                    f"[evaluation-v2] EARLY_GATE_WAITING cycle={cycle} "
                    f"continue={continue_path.name}",
                    flush=True,
                )
                while not continue_path.exists():
                    if abort_path.exists() or safe_stop["requested"]:
                        raise RuntimeError(
                            f"early evidence gate aborted at cycle {cycle}"
                        )
                    time.sleep(1.0)
                gate_payload["status"] = "PASSED"
                gate_payload["continue_file_observed"] = continue_path.name
                temporary_path.write_text(
                    json.dumps(gate_payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                os.replace(temporary_path, waiting_path)
                print(
                    f"[evaluation-v2] EARLY_GATE_PASSED cycle={cycle}",
                    flush=True,
                )
            if main.is_game_cleared(scenario_mgr) or safe_stop["requested"]:
                break
            if pause and pause not in {"max_iterations"}:
                break
            if not state.get("is_running"):
                break
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)

    elapsed = elapsed_before + (time.monotonic() - started)
    summary = _summary(
        state, scenario_mgr, state_mgr, session_id=args.session_id,
        scenario_file=args.scenario, seed=args.seed, cycles=completed_cycles,
        elapsed=elapsed,
    )
    summary["pauses"] = pauses
    reached_target = completed_cycles >= args.max_cycles
    completed = bool(summary["completed"] or reached_target)
    if completed:
        run_status = evaluation_checkpoint.STATUS_COMPLETED
    elif last_checkpoint_path:
        run_status = evaluation_checkpoint.STATUS_PAUSED
    else:
        run_status = evaluation_checkpoint.STATUS_FAILED
    summary["evaluation_status"] = run_status
    summary["resume_count"] = resume_count
    summary["last_checkpoint"] = str(last_checkpoint_path) if last_checkpoint_path else None
    summary["segment_id"] = segment_id
    summary["target_cycles_reached"] = reached_target
    (output_dir / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    (output_dir / "unified-event-log.json").write_text(
        json.dumps(state.get("unified_event_log") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_dir / "session-log.json").write_text(
        json.dumps(state.get("all_events_log") or [], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    end_checkpoint_id = (
        evaluation_checkpoint.load_checkpoint(last_checkpoint_path)["manifest"]["checkpoint_id"]
        if last_checkpoint_path else None
    )
    merge_report = evaluation_checkpoint.merge_segments(
        output_dir, raw_events=state.get("unified_event_log") or [],
    )
    summary["segment_merge"] = merge_report
    summary["llm_performance"] = _write_llm_performance_summary(
        output_dir, summary.get("turns"),
    )
    summary["ollama_topology"] = main.get_ollama_topology_metadata()
    (output_dir / "result.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    if run_status == evaluation_checkpoint.STATUS_COMPLETED:
        return 0
    if run_status == evaluation_checkpoint.STATUS_PAUSED:
        return 3
    return 2


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default="scenario.json")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--max-cycles", type=int, default=60)
    parser.add_argument(
        "--segment-cycles", type=int,
        help="maximum cycles to execute in this process; --max-cycles remains the total target",
    )
    parser.add_argument("--max-chain", type=int, default=12)
    parser.add_argument(
        "--early-gate-cycle", type=int,
        help=(
            "after durably committing this cycle, wait for "
            "EARLY_GATE_CONTINUE.json in the output directory"
        ),
    )
    parser.add_argument("--session-id")
    parser.add_argument("--output", required=True)
    resume_group = parser.add_mutually_exclusive_group()
    resume_group.add_argument("--resume", help="checkpoint directory, ID, or cycle_N name")
    resume_group.add_argument("--resume-latest", action="store_true")
    parser.add_argument(
        "--compatible-migration",
        choices=[
            evaluation_checkpoint.MAX_CYCLES_EXTENSION_MIGRATION,
            evaluation_checkpoint.SPECIAL_OBJECTIVE_COMBAT_CONTRACT_MIGRATION,
        ],
        help="explicit one-time evaluator-only compatibility migration",
    )
    return parser.parse_args()


def main_cli():
    args = parse_args()
    try:
        return run(args)
    except evaluation_checkpoint.ResumeBlocked as exc:
        status = evaluation_checkpoint.STATUS_BLOCKED
        details = {"evaluation_status": status, "reasons": exc.reasons}
        code = 4
    except evaluation_checkpoint.CheckpointInvalid as exc:
        status = evaluation_checkpoint.STATUS_INVALID
        details = {"evaluation_status": status, "reasons": [str(exc)]}
        code = 5
    except main.RemoteOllamaInfrastructureError as exc:
        status = "BLOCKED_INFRA"
        details = {
            "evaluation_status": status,
            "reasons": [exc.error_class],
            "detail": str(exc),
            "ollama_topology": main.get_ollama_topology_metadata(),
        }
        code = 6
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    error_name = "infrastructure-error.json" if status == "BLOCKED_INFRA" else "resume-error.json"
    (output_dir / error_name).write_text(
        json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(json.dumps(details, ensure_ascii=False), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main_cli())
