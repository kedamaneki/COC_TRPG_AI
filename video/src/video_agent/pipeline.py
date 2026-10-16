from pathlib import Path

from video_agent.assets import load_asset_manifest
from video_agent.characters import load_profiles
from video_agent.common.io import stable_digest, write_json
from video_agent.importer import import_evaluation_session
from video_agent.normalizer import normalize_session
from video_agent.validation import validate_all


def build_project(input_dir, output_dir, package_root=None):
    output = Path(output_dir)
    package_root = Path(package_root or Path(__file__).resolve().parents[2])
    source = import_evaluation_session(input_dir)
    session = normalize_session(source)
    profiles = load_profiles(package_root / "config")
    manifest = load_asset_manifest(package_root / "assets" / "manifest.json")
    validation = validate_all(session, profiles, manifest)
    tracked = sum(1 for x in session["events"] if x.get("source_event_ids"))
    expected_source_ids = set(session["provenance"].get("source_event_ids") or [])
    covered_source_ids = {
        str(source_id)
        for event in session["events"]
        for source_id in (event.get("source_event_ids") or [])
        if str(source_id) in expected_source_ids
    }
    provenance = {
        "normalized_events": len(session["events"]),
        "source_events": session["provenance"]["source_event_count"],
        "source_traceable_events": tracked,
        "source_traceability_rate": tracked / len(session["events"]) if session["events"] else 1.0,
        "unknown_speakers": sum(1 for x in session["events"] if x.get("speaker_id") is None and x.get("text")),
        "dropped_events": len(expected_source_ids - covered_source_ids),
        "conversion_warnings": session["metadata"]["conversion_warnings"],
        "deterministic_content_sha256": stable_digest(session),
    }
    character_map = {
        "schema_version": "0.1",
        "mappings": [
            {"source_actor_id": p["source_actor_id"], "character_profile_id": None}
            for p in session["participants"] if p["role"] in {"PC", "NPC"}
        ],
    }
    source_manifest = {"source_files": source["source_files"]}
    write_json(output / "normalized_session.json", session)
    write_json(output / "provenance_report.json", provenance)
    write_json(output / "validation_report.json", validation)
    write_json(output / "character_map.json", character_map)
    write_json(output / "source" / "source_manifest.json", source_manifest)
    return session, provenance, validation
