import argparse
import json
from pathlib import Path

from video_agent.characters import load_profiles
from video_agent.common.io import read_json
from video_agent.editing import M2Pipeline
from video_agent.pipeline import build_project
from video_agent.presentation import M3Pipeline
from video_agent.rendering import M1Pipeline
from video_agent.validation import validate_session


def _root():
    return Path(__file__).resolve().parents[2]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="video-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import-session")
    imp.add_argument("--input", required=True)
    imp.add_argument("--output", required=True)
    val = sub.add_parser("validate")
    val.add_argument("path")
    sub.add_parser("list-characters")
    for name in ("render-m1", "render-voices", "render-video", "validate-render"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
    for name in ("edit-m2", "validate-edit"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
    for name in ("present-m3", "validate-presentation"):
        command = sub.add_parser(name)
        command.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    if args.command == "import-session":
        session, provenance, validation = build_project(args.input, args.output, _root())
        print(json.dumps({
            "status": validation["status"], "session_id": session["session_id"],
            "events": len(session["events"]), "traceability_rate": provenance["source_traceability_rate"],
            "output": str(Path(args.output).resolve()),
        }, ensure_ascii=False))
        return 0 if validation["status"] == "PASS" else 2
    if args.command == "validate":
        issues = validate_session(read_json(args.path))
        errors = [x for x in issues if x["level"] == "ERROR"]
        print(json.dumps({"status": "PASS" if not errors else "FAIL", "issues": issues}, ensure_ascii=False, indent=2))
        return 0 if not errors else 2
    if args.command == "list-characters":
        profiles = load_profiles(_root() / "config")
        print(json.dumps(profiles["characters"], ensure_ascii=False, indent=2))
        return 0
    if args.command == "edit-m2":
        result = M2Pipeline(_root(), Path(args.project)).run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "validate-edit":
        result = read_json(Path(args.project) / "editing_qa_report.json")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "present-m3":
        result = M3Pipeline(_root(), Path(args.project)).run()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    if args.command == "validate-presentation":
        result = read_json(Path(args.project) / "presentation_qa_report.json")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 2
    pipeline = M1Pipeline(_root(), Path(args.project))
    if args.command == "render-m1":
        result = pipeline.run()
    elif args.command == "render-voices":
        lines = pipeline.prepare_script()
        result = pipeline.render_voices(lines)
    elif args.command == "render-video":
        timeline = pipeline.build_timeline()
        output = pipeline.render_video(timeline)
        result = {"output": str(output)}
    else:
        result = pipeline.qa()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status", "PASS") == "PASS" else 2
