"""Evaluation-only checkpoint, resume, and segment support.

This module deliberately does not participate in normal game save/load.  It
captures the complete evaluator boundary after a committed cycle and restores
that boundary before the next cycle is run.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import pickle
import random
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


CHECKPOINT_VERSION = 2
STATUS_RUNNING = "RUNNING"
STATUS_PAUSED = "PAUSED_RESUMABLE"
STATUS_COMPLETED = "COMPLETED"
RUNTIME_CONTROL_KEYS = frozenset({"max_cycles"})
MAX_CYCLES_EXTENSION_MIGRATION = "MAX_CYCLES_EXTENSION_V1"
SPECIAL_OBJECTIVE_COMBAT_CONTRACT_MIGRATION = "SPECIAL_OBJECTIVE_COMBAT_CONTRACT_FIX_V1"
COMPATIBLE_EVALUATOR_MIGRATIONS = {
    MAX_CYCLES_EXTENSION_MIGRATION: {
        # Exact source fingerprint recorded by the post-fix cycle 15 checkpoint.
        "from_source_hash": "ddf96d7041c1c469a83e4cded7ecf7d2ebe7f067dde3d8997c3bb465e149363d",
        # All non-test gameplay sources, excluding the evaluator module and runner.
        "protected_source_hash": "213ef61129973b2dba061238fb7e8c15f08f2b270188a1a3505181fc7eb11040",
        "allowed_changed_files": ["EvaluationCheckpoint.py", "run_investigation_evaluation.py"],
    },
    SPECIAL_OBJECTIVE_COMBAT_CONTRACT_MIGRATION: {
        "from_source_hash": "0becb4ace78706764bf5a99d98d9520b0359f1d5a4feb9efe79f5e0e846f7723",
        "protected_source_hash": "0a169103531f54137f430b59abd8242c626ed47716c510e13b256762a3a37124",
        "from_prompt_hash": "081564fd14d65f1cc26d5b140c8dd2bfd56a1d75c26a481891f78c7e802c329a",
        "to_prompt_hash": "4006cf12fa835b5a843c4b8f541ce6df01df352d968f5f2b6b6be9f9a8a270d6",
        "allowed_changed_files": ["CombatProgression.py", "main.py"],
    },
}
STATUS_FAILED = "FAILED"
STATUS_INVALID = "CHECKPOINT_INVALID"
STATUS_BLOCKED = "RESUME_BLOCKED"


class CheckpointError(RuntimeError):
    """Base class for evaluation checkpoint failures."""


class CheckpointInvalid(CheckpointError):
    """The checkpoint is incomplete, corrupt, or has an invalid checksum."""


class ResumeBlocked(CheckpointError):
    """The checkpoint belongs to incompatible code/configuration."""

    def __init__(self, reasons: Sequence[str]):
        self.reasons = list(reasons)
        super().__init__(", ".join(self.reasons))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def hash_value(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def hash_files(paths: Iterable[Path], *, root: Optional[Path] = None) -> str:
    digest = hashlib.sha256()
    normalized = sorted({Path(path).resolve() for path in paths if Path(path).is_file()})
    for path in normalized:
        try:
            label = path.relative_to(root.resolve()).as_posix() if root else path.name
        except ValueError:
            label = path.name
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def hash_tree(root: Path) -> str:
    root = Path(root).resolve()
    if not root.is_dir():
        return ""
    return hash_files((path for path in root.rglob("*") if path.is_file()), root=root)


def encode_python_state(value: Any) -> str:
    return base64.b64encode(pickle.dumps(value, protocol=4)).decode("ascii")


def decode_python_state(value: str) -> Any:
    return pickle.loads(base64.b64decode(value.encode("ascii")))


def capture_rng_state() -> Dict[str, Any]:
    result: Dict[str, Any] = {"python_random": encode_python_state(random.getstate())}
    try:
        import numpy as np  # type: ignore

        result["numpy_random"] = encode_python_state(np.random.get_state())
    except (ImportError, AttributeError):
        result["numpy_random"] = None
    return result


def restore_rng_state(data: Dict[str, Any]) -> None:
    encoded = data.get("python_random")
    if not encoded:
        raise CheckpointInvalid("python RNG state is missing")
    random.setstate(decode_python_state(encoded))
    numpy_state = data.get("numpy_random")
    if numpy_state:
        try:
            import numpy as np  # type: ignore

            np.random.set_state(decode_python_state(numpy_state))
        except ImportError as exc:
            raise CheckpointInvalid("NumPy RNG state is present but NumPy is unavailable") from exc


def ensure_event_ids(events: List[Dict[str, Any]], session_id: str) -> None:
    """Validate identities; serializers must never allocate event IDs."""
    from EventIdentity import validate_event_stream
    validate_event_stream(events)


def build_fingerprints(
    *,
    source_root: Path,
    scenario_path: Path,
    pc_paths: Sequence[Path],
    model_config: Dict[str, Any],
    evaluation_config: Dict[str, Any],
    prompt_paths: Optional[Sequence[Path]] = None,
    kp_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    source_root = source_root.resolve()
    source_paths = [
        path for path in source_root.glob("*.py")
        if not path.name.startswith("test_")
    ]
    evaluator_names = {"EvaluationCheckpoint.py", "run_investigation_evaluation.py"}
    evaluator_paths = [path for path in source_paths if path.name in evaluator_names]
    protected_source_paths = [path for path in source_paths if path.name not in evaluator_names]
    evaluation_semantics = {
        key: copy.deepcopy(value)
        for key, value in evaluation_config.items()
        if key not in RUNTIME_CONTROL_KEYS
    }
    runtime_controls = {
        key: copy.deepcopy(value)
        for key, value in evaluation_config.items()
        if key in RUNTIME_CONTROL_KEYS
    }
    return {
        "scenario_hash": hash_files([scenario_path], root=source_root),
        "source_hash": hash_files(source_paths, root=source_root),
        "protected_source_hash": hash_files(protected_source_paths, root=source_root),
        "evaluator_source_hash": hash_files(evaluator_paths, root=source_root),
        "prompt_hash": hash_files(prompt_paths or [source_root / "main.py"], root=source_root),
        "pc_config_hash": hash_files(pc_paths, root=source_root),
        "kp_config_hash": hash_value(kp_config or {}),
        "model_config": copy.deepcopy(model_config),
        "model_config_hash": hash_value(model_config),
        "evaluation_config_hash": hash_value(evaluation_semantics),
        "evaluation_semantics_hash": hash_value(evaluation_semantics),
        "evaluation_semantics": evaluation_semantics,
        "runtime_controls": runtime_controls,
        "evaluation_config": copy.deepcopy(evaluation_config),
    }


def _without_runtime_controls(config: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in (config or {}).items()
        if key not in RUNTIME_CONTROL_KEYS
    }


def assess_resume_compatibility(
    saved: Dict[str, Any],
    current: Dict[str, Any],
    seed: int,
    *,
    compatible_migration: Optional[str] = None,
) -> Dict[str, Any]:
    """Validate state semantics while allowing a monotonic runner-limit extension."""
    reasons: List[str] = []
    if saved.get("seed") != seed:
        reasons.append("CHECKPOINT_SEED_MISMATCH")

    migration_result = None
    migration = None
    source_matches = saved.get("source_hash") == current.get("source_hash")
    if not source_matches:
        migration = COMPATIBLE_EVALUATOR_MIGRATIONS.get(str(compatible_migration or ""))
        migration_ok = bool(
            migration
            and saved.get("source_hash") == migration.get("from_source_hash")
            and current.get("protected_source_hash") == migration.get("protected_source_hash")
        )
        if migration_ok:
            migration_result = {
                "migration_id": compatible_migration,
                "validation_result": "PASS",
                "from_source_hash": saved.get("source_hash"),
                "to_source_hash": current.get("source_hash"),
                "protected_source_hash": current.get("protected_source_hash"),
                "allowed_changed_files": copy.deepcopy(migration.get("allowed_changed_files") or []),
            }
        else:
            reasons.append("CHECKPOINT_CODE_MISMATCH")

    comparisons = (
        ("scenario_hash", "CHECKPOINT_SCENARIO_MISMATCH"),
        ("prompt_hash", "CHECKPOINT_PROMPT_MISMATCH"),
        ("pc_config_hash", "CHECKPOINT_PC_CONFIG_MISMATCH"),
        ("kp_config_hash", "CHECKPOINT_KP_CONFIG_MISMATCH"),
        ("model_config_hash", "CHECKPOINT_MODEL_MISMATCH"),
    )
    for field, code in comparisons:
        if (
            field == "prompt_hash"
            and migration_result
            and saved.get(field) == migration.get("from_prompt_hash")
            and current.get(field) == migration.get("to_prompt_hash")
        ):
            continue
        if saved.get(field) != current.get(field):
            reasons.append(code)

    saved_config = copy.deepcopy(saved.get("evaluation_config") or {})
    current_config = copy.deepcopy(current.get("evaluation_config") or {})
    if saved_config or current_config:
        if _without_runtime_controls(saved_config) != _without_runtime_controls(current_config):
            reasons.append("CHECKPOINT_EVALUATION_CONFIG_MISMATCH")
    elif saved.get("evaluation_config_hash") != current.get("evaluation_config_hash"):
        reasons.append("CHECKPOINT_EVALUATION_CONFIG_MISMATCH")

    saved_limit = saved_config.get("max_cycles")
    requested_limit = current_config.get("max_cycles")
    checkpoint_cycle = int(saved.get("cycle") or 0)
    extended = False
    if saved_limit is not None and requested_limit is not None:
        saved_limit = int(saved_limit)
        requested_limit = int(requested_limit)
        if requested_limit < checkpoint_cycle:
            reasons.append("CHECKPOINT_MAX_CYCLES_BELOW_CHECKPOINT")
        if requested_limit < saved_limit:
            reasons.append("CHECKPOINT_MAX_CYCLES_REDUCTION")
        extended = requested_limit > saved_limit

    return {
        "validation_result": "PASS" if not reasons else "BLOCKED",
        "reasons": list(dict.fromkeys(reasons)),
        "checkpoint_id": saved.get("checkpoint_id"),
        "checkpoint_cycle": checkpoint_cycle,
        "original_max_cycles": saved_limit,
        "resumed_max_cycles": requested_limit,
        "previous_limit": saved_limit,
        "new_limit": requested_limit,
        "max_cycles_extended": extended,
        "compatible_evaluator_migration": migration_result,
    }


def validate_fingerprints(
    saved: Dict[str, Any],
    current: Dict[str, Any],
    seed: int,
    *,
    compatible_migration: Optional[str] = None,
) -> List[str]:
    return assess_resume_compatibility(
        saved, current, seed, compatible_migration=compatible_migration,
    )["reasons"]


def checkpoint_id_for_cycle(cycle: int) -> str:
    return f"CHECKPOINT_CYCLE_{int(cycle):06d}"


def _checkpoint_dir(root: Path, cycle: int) -> Path:
    return root / "checkpoints" / f"cycle_{int(cycle):06d}"


def _pending_warnings(state: Dict[str, Any], state_mgr: Any) -> List[str]:
    fields = (
        "pending_decision", "pending_san_check", "pending_push_roll",
        "pending_luck_burn", "pending_combat_defense", "partial_system_log",
        "timeline_pending", "pending_action_id",
    )
    warnings = [f"PENDING_AT_CYCLE_BOUNDARY:{field}" for field in fields if state.get(field)]
    if getattr(state_mgr, "pending_combat_defense", None):
        warnings.append("PENDING_AT_CYCLE_BOUNDARY:state_mgr.pending_combat_defense")
    return warnings


def _checkpoint_payload(
    *,
    state: Dict[str, Any],
    char_mgr: Any,
    state_mgr: Any,
    scenario_mgr: Any,
    evaluator_state: Dict[str, Any],
    llm_history: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "session_state": copy.deepcopy(state),
        "character_manager": copy.deepcopy(char_mgr.export_to_dict()),
        "game_state_manager": copy.deepcopy(state_mgr.export_to_dict()),
        "scenario_manager": copy.deepcopy(scenario_mgr.export_to_dict()),
        "rng_state": capture_rng_state(),
        "llm_history": copy.deepcopy(llm_history),
        "evaluator_state": copy.deepcopy(evaluator_state),
    }


def write_checkpoint(
    root: Path,
    *,
    cycle: int,
    session_id: str,
    seed: int,
    state: Dict[str, Any],
    char_mgr: Any,
    state_mgr: Any,
    scenario_mgr: Any,
    evaluator_state: Dict[str, Any],
    llm_history: Dict[str, Any],
    fingerprints: Dict[str, Any],
    prior_segment_id: Optional[str],
    runtime_data_dir: Optional[Path] = None,
) -> Path:
    """Atomically write one complete cycle-boundary checkpoint directory."""
    root = Path(root).resolve()
    ensure_event_ids(state.setdefault("unified_event_log", []), session_id)
    final_dir = _checkpoint_dir(root, cycle)
    temp_dir = final_dir.with_name(final_dir.name + f".tmp-{os.getpid()}")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()

    payload = _checkpoint_payload(
        state=state, char_mgr=char_mgr, state_mgr=state_mgr,
        scenario_mgr=scenario_mgr, evaluator_state=evaluator_state,
        llm_history=llm_history,
    )
    payload_bytes = _canonical_bytes(payload)
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    checkpoint_id = checkpoint_id_for_cycle(cycle)
    manifest = {
        "checkpoint_id": checkpoint_id,
        "checkpoint_version": CHECKPOINT_VERSION,
        "session_id": session_id,
        "seed": seed,
        "cycle": int(cycle),
        "turn": int(getattr(state_mgr, "turn_count", 0) or 0),
        "scene": str(getattr(state_mgr, "current_scene_id", "") or ""),
        "location": str(getattr(scenario_mgr, "location", "") or ""),
        **copy.deepcopy(fingerprints),
        "rng_state_present": bool(payload["rng_state"].get("python_random")),
        "llm_history_present": "chat_history" in payload["llm_history"],
        "evaluator_state_present": bool(payload["evaluator_state"]),
        "event_log_offset": len(state.get("unified_event_log") or []),
        "event_id": (state.get("unified_event_log") or [{}])[-1].get("event_id") if state.get("unified_event_log") else None,
        "prior_segment_id": prior_segment_id,
        "warnings": _pending_warnings(state, state_mgr),
        "checksum": checksum,
        "created_at": _utc_now(),
        "completed": True,
        "complete": True,
    }
    (temp_dir / "state.json").write_bytes(payload_bytes)
    runtime_data_hash = None
    if runtime_data_dir is not None:
        runtime_data_dir = Path(runtime_data_dir).resolve()
        if not runtime_data_dir.is_dir():
            raise CheckpointInvalid(f"runtime data directory is missing: {runtime_data_dir}")
        shutil.copytree(runtime_data_dir, temp_dir / "runtime_data")
        runtime_data_hash = hash_tree(temp_dir / "runtime_data")
    manifest["runtime_data_present"] = runtime_data_hash is not None
    manifest["runtime_data_hash"] = runtime_data_hash
    (temp_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    # Validate before publishing the directory.
    if hashlib.sha256((temp_dir / "state.json").read_bytes()).hexdigest() != checksum:
        raise CheckpointInvalid("checkpoint checksum failed before publish")
    (temp_dir / "COMPLETE").write_text(checkpoint_id + "\n", encoding="utf-8")
    if final_dir.exists():
        existing = load_checkpoint(final_dir)
        if existing["manifest"].get("checksum") == checksum:
            shutil.rmtree(temp_dir)
            return final_dir
        raise CheckpointInvalid(f"checkpoint already exists with different content: {final_dir}")
    os.replace(temp_dir, final_dir)
    return final_dir


def load_checkpoint(path: Path) -> Dict[str, Any]:
    path = Path(path).resolve()
    if path.is_file() and path.name == "manifest.json":
        path = path.parent
    manifest_path = path / "manifest.json"
    state_path = path / "state.json"
    marker_path = path / "COMPLETE"
    if not (manifest_path.is_file() and state_path.is_file() and marker_path.is_file()):
        raise CheckpointInvalid(f"incomplete checkpoint: {path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload_bytes = state_path.read_bytes()
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CheckpointInvalid(f"unreadable checkpoint: {path}") from exc
    if not manifest.get("complete") or not manifest.get("completed"):
        raise CheckpointInvalid(f"checkpoint is not marked complete: {path}")
    if manifest.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise CheckpointInvalid("unsupported checkpoint version")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    if checksum != manifest.get("checksum"):
        raise CheckpointInvalid("checkpoint checksum mismatch")
    if marker_path.read_text(encoding="utf-8").strip() != manifest.get("checkpoint_id"):
        raise CheckpointInvalid("checkpoint COMPLETE marker mismatch")
    runtime_snapshot = path / "runtime_data"
    if manifest.get("runtime_data_present"):
        if not runtime_snapshot.is_dir():
            raise CheckpointInvalid("checkpoint runtime_data snapshot is missing")
        if hash_tree(runtime_snapshot) != manifest.get("runtime_data_hash"):
            raise CheckpointInvalid("checkpoint runtime_data checksum mismatch")
    return {"path": path, "manifest": manifest, "payload": payload}


def restore_runtime_data(loaded: Dict[str, Any], target: Path) -> None:
    """Roll the isolated evaluator data directory back to the cycle boundary."""
    snapshot = Path(loaded["path"]) / "runtime_data"
    if not loaded["manifest"].get("runtime_data_present"):
        return
    if not snapshot.is_dir():
        raise CheckpointInvalid("checkpoint runtime_data snapshot is missing")
    target = Path(target).resolve()
    if target.name != "runtime_data":
        raise CheckpointInvalid(f"refusing to replace unexpected runtime directory: {target}")
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(snapshot, target)


def latest_checkpoint(root: Path) -> Path:
    candidates: List[Tuple[int, Path]] = []
    for path in (Path(root).resolve() / "checkpoints").glob("cycle_*"):
        try:
            loaded = load_checkpoint(path)
            candidates.append((int(loaded["manifest"]["cycle"]), path))
        except (CheckpointError, KeyError, TypeError, ValueError):
            continue
    if not candidates:
        raise CheckpointInvalid("no complete checkpoint found")
    return max(candidates, key=lambda item: item[0])[1]


def restore_checkpoint(
    loaded: Dict[str, Any],
    *,
    char_mgr: Any,
    state_mgr: Any,
    scenario_mgr: Any,
    current_fingerprints: Dict[str, Any],
    seed: int,
    compatible_migration: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    manifest = loaded["manifest"]
    validation = assess_resume_compatibility(
        manifest,
        current_fingerprints,
        seed,
        compatible_migration=compatible_migration,
    )
    if validation["reasons"]:
        raise ResumeBlocked(validation["reasons"])
    loaded["resume_validation"] = validation
    payload = loaded["payload"]
    char_mgr.load_from_dict(copy.deepcopy(payload["character_manager"]))
    state_mgr.load_from_dict(copy.deepcopy(payload["game_state_manager"]))
    scenario_mgr.load_from_dict(copy.deepcopy(payload["scenario_manager"]))
    scenario_mgr.bind_game_state(state_mgr)
    restore_rng_state(payload["rng_state"])
    return (
        copy.deepcopy(payload["session_state"]),
        copy.deepcopy(payload["evaluator_state"]),
        copy.deepcopy(payload["llm_history"]),
    )


def next_segment_id(root: Path) -> str:
    numbers = []
    for path in (Path(root).resolve() / "segments").glob("segment_*"):
        match = re.match(r"^segment_(\d+)(?:_|$)", path.name)
        if match:
            numbers.append(int(match.group(1)))
    return f"segment_{max(numbers, default=0) + 1:03d}"


def write_segment(
    root: Path,
    *,
    segment_id: str,
    session_id: str,
    start_checkpoint_id: Optional[str],
    end_checkpoint_id: Optional[str],
    resume_from_checkpoint_id: Optional[str],
    prior_segment_id: Optional[str],
    start_cycle: int,
    end_cycle: int,
    start_event_offset: int,
    events: Sequence[Dict[str, Any]],
    metrics_start: Dict[str, Any],
    metrics_end: Dict[str, Any],
    status: str,
    resume_event: Optional[Dict[str, Any]] = None,
) -> Path:
    segment_dir = Path(root).resolve() / "segments" / segment_id
    temp_dir = segment_dir.with_name(segment_dir.name + f".tmp-{os.getpid()}")
    segment_dir.parent.mkdir(parents=True, exist_ok=True)
    segment_events = copy.deepcopy(list(events)[start_event_offset:])
    if resume_event:
        segment_events.insert(0, copy.deepcopy(resume_event))
    document = {
        "segment_id": segment_id,
        "session_id": session_id,
        "start_checkpoint_id": start_checkpoint_id,
        "end_checkpoint_id": end_checkpoint_id,
        "resume_from_checkpoint_id": resume_from_checkpoint_id,
        "prior_segment_id": prior_segment_id,
        "start_cycle": int(start_cycle),
        "end_cycle": int(end_cycle),
        "start_event_offset": int(start_event_offset),
        "end_event_offset": len(events),
        "events": segment_events,
        "metrics_start": copy.deepcopy(metrics_start),
        "metrics_end": copy.deepcopy(metrics_end),
        "metrics_delta": numeric_delta(metrics_start, metrics_end),
        "status": status,
        "created_at": _utc_now(),
    }
    payload = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    (temp_dir / "segment.json").write_bytes(payload)
    (temp_dir / "manifest.json").write_text(json.dumps({
        "segment_id": segment_id, "checksum": hashlib.sha256(payload).hexdigest(),
        "complete": True,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (temp_dir / "COMPLETE").write_text(segment_id + "\n", encoding="utf-8")
    os.replace(temp_dir, segment_dir)
    return segment_dir


def write_durable_segment(
    root: Path, *, segment_id: str, session_id: str, cycle: int,
    start_event_offset: int, events: Sequence[Dict[str, Any]],
    start_checkpoint_id: Optional[str], end_checkpoint_id: str,
    resume_from_checkpoint_id: Optional[str] = None,
    prior_segment_id: Optional[str] = None, status: str = "CHECKPOINT_COMMITTED",
    provenance: str = "RUNTIME_COMMIT",
) -> Path:
    """Atomically publish the event delta before its checkpoint is committed."""
    root = Path(root).resolve()
    artifact_id = f"{segment_id}_cycle_{int(cycle):06d}"
    final_dir = root / "segments" / artifact_id
    temp_dir = final_dir.with_name(final_dir.name + f".tmp-{os.getpid()}")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    from EventIdentity import validate_event_stream
    validate_event_stream(list(events))
    delta = copy.deepcopy(list(events)[int(start_event_offset):])
    start_id = delta[0]["event_id"] if delta else None
    end_id = delta[-1]["event_id"] if delta else None
    document = {
        "segment_id": artifact_id, "run_segment_id": segment_id,
        "session_id": session_id, "start_checkpoint_id": start_checkpoint_id,
        "end_checkpoint_id": end_checkpoint_id,
        "resume_from_checkpoint_id": resume_from_checkpoint_id,
        "prior_segment_id": prior_segment_id,
        "start_cycle": int(cycle), "end_cycle": int(cycle),
        "start_event_offset": int(start_event_offset),
        "end_event_offset": len(events), "events": delta,
        "start_event_id": start_id, "end_event_id": end_id,
        "event_count": len(delta), "start_raw_offset": int(start_event_offset),
        "end_raw_offset": len(events), "checkpoint_target": end_checkpoint_id,
        "source_run_id": session_id,
        "status": status, "provenance": provenance, "created_at": _utc_now(),
    }
    payload = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    checksum = hashlib.sha256(payload).hexdigest()
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir()
    (temp_dir / "segment.json").write_bytes(payload)
    (temp_dir / "manifest.json").write_text(json.dumps({
        "segment_id": artifact_id, "checksum": checksum, "complete": True,
        "provenance": provenance,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (temp_dir / "COMPLETE").write_text(artifact_id + "\n", encoding="utf-8")
    if final_dir.exists():
        existing = json.loads((final_dir / "segment.json").read_text(encoding="utf-8"))
        if existing == document:
            shutil.rmtree(temp_dir)
            return final_dir
        raise CheckpointInvalid(f"durable segment already exists with different content: {final_dir}")
    os.replace(temp_dir, final_dir)
    return final_dir


def ensure_checkpoint_segment_coverage(root: Path, loaded: Dict[str, Any]) -> Optional[Path]:
    """Recover a missing pre-resume segment only from the immutable checkpoint payload."""
    root = Path(root).resolve()
    events = list((loaded.get("payload") or {}).get("session_state", {}).get("unified_event_log") or [])
    manifest = loaded.get("manifest") or {}
    covered = set()
    max_offset = 0
    for segment in load_segments(root):
        max_offset = max(max_offset, int(segment.get("end_event_offset") or 0))
        covered.update(str(row.get("event_id")) for row in segment.get("events") or [] if row.get("event_id"))
    missing = [row for row in events if row.get("event_id") and str(row.get("event_id")) not in covered]
    if not missing:
        return None
    # A checkpoint is the authoritative crash recovery source.  Preserve exact rows.
    artifact = write_durable_segment(
        root, segment_id="segment_reconstructed", session_id=str(manifest.get("session_id") or ""),
        cycle=int(manifest.get("cycle") or 0), start_event_offset=max_offset,
        events=events, start_checkpoint_id=None,
        end_checkpoint_id=str(manifest.get("checkpoint_id") or ""),
        status="RECONSTRUCTED_FROM_RAW", provenance="RECONSTRUCTED_FROM_RAW",
    )
    return artifact


def numeric_delta(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in after.items():
        old = before.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isinstance(old, (int, float)) and not isinstance(old, bool):
            result[key] = value - old
    return result


def load_segments(root: Path) -> List[Dict[str, Any]]:
    result = []
    for path in sorted((Path(root).resolve() / "segments").glob("segment_*/segment.json")):
        marker = path.parent / "COMPLETE"
        manifest = path.parent / "manifest.json"
        if not (manifest.is_file() and marker.is_file()):
            continue
        metadata = json.loads(manifest.read_text(encoding="utf-8"))
        payload = path.read_bytes()
        if not metadata.get("complete"):
            continue
        if hashlib.sha256(payload).hexdigest() != metadata.get("checksum"):
            raise CheckpointInvalid(f"segment checksum mismatch: {path.parent}")
        if marker.read_text(encoding="utf-8").strip() != metadata.get("segment_id"):
            raise CheckpointInvalid(f"segment COMPLETE marker mismatch: {path.parent}")
        result.append(json.loads(payload.decode("utf-8")))
    return sorted(result, key=lambda row: (int(row.get("start_event_offset") or 0), str(row.get("segment_id") or "")))


def merge_segments(root: Path, raw_events: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Merge the evaluation event stream, detecting gaps, overlap and duplicates."""
    root = Path(root).resolve()
    segments = load_segments(root)
    issues: List[Dict[str, Any]] = []
    merged: List[Dict[str, Any]] = []
    seen_ids = set()
    previous = None
    duplicate_count = 0
    for segment in segments:
        if previous is not None:
            if previous.get("provenance") or segment.get("provenance"):
                expected_offset = int(previous.get("end_event_offset") or 0)
                actual_offset = int(segment.get("start_event_offset") or 0)
                if actual_offset > expected_offset:
                    issues.append({"code": "SEGMENT_GAP_DETECTED", "expected_offset": expected_offset, "actual_offset": actual_offset})
                elif actual_offset < expected_offset:
                    issues.append({"code": "SEGMENT_OVERLAP_DETECTED", "expected_offset": expected_offset, "actual_offset": actual_offset})
            else:
                expected = int(previous.get("end_cycle") or 0) + 1
                actual = int(segment.get("start_cycle") or 0)
                if actual > expected:
                    issues.append({"code": "SEGMENT_GAP_DETECTED", "expected_cycle": expected, "actual_cycle": actual})
                elif actual < expected:
                    issues.append({"code": "SEGMENT_OVERLAP_DETECTED", "expected_cycle": expected, "actual_cycle": actual})
        for event in segment.get("events") or []:
            event_id = event.get("event_id")
            if event_id and event_id in seen_ids:
                duplicate_count += 1
                continue
            if event_id:
                seen_ids.add(event_id)
            merged.append(event)
        previous = segment
    merged_dir = root / "merged"
    merged_dir.mkdir(parents=True, exist_ok=True)
    with (merged_dir / "events.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for event in merged:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    raw_rows = list(raw_events or [])
    raw_ids = [str(row.get("event_id")) for row in raw_rows if row.get("event_id")]
    merged_ids = [str(row.get("event_id")) for row in merged if row.get("event_id")]
    missing_identity = sum(not row.get("event_id") for row in merged)
    missing_ids = sorted(set(raw_ids) - set(merged_ids))
    extra_ids = sorted(set(merged_ids) - set(raw_ids)) if raw_events is not None else []
    coverage = (len(set(raw_ids) & set(merged_ids)) / len(set(raw_ids))) if raw_ids else 1.0
    if missing_ids:
        issues.append({"code": "SEGMENT_RAW_COVERAGE_GAP", "missing_count": len(missing_ids)})
    if extra_ids:
        issues.append({"code": "SEGMENT_RAW_COVERAGE_EXTRA", "extra_count": len(extra_ids)})
    if duplicate_count and raw_events is not None:
        issues.append({"code": "SEGMENT_DUPLICATE_EVENT", "duplicate_count": duplicate_count})
    if missing_identity:
        issues.append({"code": "SEGMENT_EVENT_ID_MISSING", "missing_count": missing_identity})
    report = {
        "segment_count": len(segments),
        "event_count": len(merged),
        "duplicate_events_removed": duplicate_count,
        "missing_events": len(missing_ids),
        "extra_events": len(extra_ids),
        "unexpected_events": len(extra_ids),
        "raw_event_count": len(raw_rows),
        "segment_event_count": len(merged_ids),
        "covered_event_count": len(set(raw_ids) & set(merged_ids)),
        "missing_event_ids": missing_ids,
        "duplicate_event_ids": duplicate_count,
        "unexpected_event_ids": extra_ids,
        "coverage_ratio": coverage,
        "issues": issues,
        "status": "PASS" if not issues else "FAILED",
        "final_metrics": copy.deepcopy(segments[-1].get("metrics_end") if segments else {}),
    }
    (merged_dir / "evaluation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return report
