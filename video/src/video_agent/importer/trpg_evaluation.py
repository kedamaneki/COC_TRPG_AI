from pathlib import Path

from video_agent.common.io import read_json, sha256_file


class SessionInputError(ValueError):
    pass


def _latest_checkpoint(input_dir):
    checkpoints = Path(input_dir) / "checkpoints"
    candidates = sorted(p for p in checkpoints.glob("cycle_*" ) if p.is_dir())
    return candidates[-1] if candidates else None


def import_evaluation_session(input_dir):
    root = Path(input_dir).resolve()
    unified_path = root / "unified-event-log.json"
    session_path = root / "session-log.json"
    result_path = root / "result.json"
    missing = [str(p) for p in (unified_path, session_path, result_path) if not p.is_file()]
    if missing:
        raise SessionInputError(f"required input files missing: {missing}")
    checkpoint = _latest_checkpoint(root)
    pcs_path = checkpoint / "runtime_data" / "pcs.json" if checkpoint else None
    npcs_path = checkpoint / "runtime_data" / "npcs.json" if checkpoint else None
    datasets = checkpoint / "runtime_data" / "datasets" if checkpoint else None
    scenario_files = sorted(datasets.glob("*.json")) if datasets and datasets.is_dir() else []
    paths = [unified_path, session_path, result_path]
    for optional in (pcs_path, npcs_path):
        if optional and optional.is_file():
            paths.append(optional)
    return {
        "root": str(root),
        "unified_events": read_json(unified_path),
        "session_events": read_json(session_path),
        "result": read_json(result_path),
        "pcs": read_json(pcs_path) if pcs_path and pcs_path.is_file() else {},
        "npcs": read_json(npcs_path) if npcs_path and npcs_path.is_file() else {},
        "scenarios": [read_json(p) for p in scenario_files],
        "source_files": [
            {"path": str(p), "sha256": sha256_file(p), "kind": p.name}
            for p in paths
        ],
    }
