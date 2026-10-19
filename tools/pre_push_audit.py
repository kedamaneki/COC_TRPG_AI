from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


MAX_FILE_SIZE = 50 * 1024 * 1024
FORBIDDEN_MEDIA = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm",
    ".wav", ".mp3", ".ogg", ".flac", ".aac",
    ".zip", ".7z", ".rar", ".psd", ".exe", ".dll",
}
SECRET_PATTERNS = {
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(rb"\bgh[ps]_[A-Za-z0-9]{30,}\b"),
    "aws_access_key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "google_api_key": re.compile(rb"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "openai_api_key": re.compile(rb"\bsk-[0-9A-Za-z_-]{30,}\b"),
    "slack_token": re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
}


def git_candidates(repo: Path) -> list[Path]:
    raw = subprocess.check_output(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo,
    )
    return [repo / item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def audit(repo: Path) -> dict:
    files = git_candidates(repo)
    oversized: list[dict] = []
    forbidden_media: list[str] = []
    secret_findings: list[dict] = []
    missing: list[str] = []
    total_bytes = 0
    for path in files:
        relative = path.relative_to(repo).as_posix()
        if not path.is_file():
            missing.append(relative)
            continue
        size = path.stat().st_size
        total_bytes += size
        if size > MAX_FILE_SIZE:
            oversized.append({"path": relative, "size": size})
        if path.suffix.lower() in FORBIDDEN_MEDIA:
            forbidden_media.append(relative)
        if size <= 5 * 1024 * 1024:
            data = path.read_bytes()
            for kind, pattern in SECRET_PATTERNS.items():
                if pattern.search(data):
                    secret_findings.append({"path": relative, "kind": kind})
    status = "PASS" if not (oversized or forbidden_media or secret_findings or missing) else "FAIL"
    return {
        "status": status,
        "candidate_file_count": len(files),
        "candidate_total_bytes": total_bytes,
        "max_file_size_bytes": MAX_FILE_SIZE,
        "oversized": oversized,
        "forbidden_media_or_archive": forbidden_media,
        "secret_findings": secret_findings,
        "missing_candidates": missing,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--json-report", type=Path)
    args = parser.parse_args()
    result = audit(args.repo.resolve())
    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
