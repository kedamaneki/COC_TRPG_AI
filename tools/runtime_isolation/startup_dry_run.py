"""Production-path startup dry-run that never creates a formal session."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import urllib.request

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
ROOT = REPO_ROOT
SRC = REPO_ROOT / "core" / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))

from runtime_boundary import NetworkBoundary, RuntimeBoundary, assert_local_ollama_config


EXPECTED = {
    "main": "8cf1403ec36a9bf8f931429c4a3e172d2ecb5361decc08d28c96c480fc7393c6",
    "scenario": "b6f0559ffca677b57bc3a69c16991bb24c483d30256cb6dfd30fc938ebd84ed7",
    "pcs": "f47bb03ff6406c228dd7c88f94c597d6e28785b47c6e0afe1322b7596c31c3dd",
    "npcs": "3c795e6098f97ae8e6240b9ed2412428ab332c91c30a1cb45b846d2f4628377c",
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def api(path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        "http://127.0.0.1:11434" + path, data=data,
        headers={"Content-Type": "application/json"}, method="POST" if data else "GET",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def run(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    audit = output / "runtime_audit.jsonl"
    checks = {}
    detail = {}

    system_shell = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
    runtime = RuntimeBoundary(audit, allowed_executables=[sys.executable, system_shell])
    with runtime, NetworkBoundary(audit):
        checks["PYTHON_EXECUTABLE"] = "PASS"
        # Python 3.12 may call ``cmd.exe /c ver`` here.  Treat that standard
        # library probe as a named trusted-runtime purpose; every other child
        # process remains denied by the exact-executable boundary.
        with runtime.purpose("PYTHON_STDLIB_PLATFORM_SYSTEM"):
            checks["PLATFORM_SYSTEM_QUERY"] = "PASS" if platform.system() == "Windows" else "FAIL"
        import streamlit
        checks["STREAMLIT_IMPORT"] = "PASS"
        import main
        import run_investigation_evaluation as runner
        checks["CORE_IMPORT"] = "PASS"

        os.environ.update({
            "PRIMARY_OLLAMA_URL": "http://127.0.0.1:11434",
            "LLM_BASE_URL": "http://127.0.0.1:11434/v1",
            "SECONDARY_OLLAMA_URL": "",
            "EXECUTION_PROFILE": "SINGLE_PC",
            "LLM_API_KEY": "ollama",
        })
        config = main.get_llm_config()
        assert_local_ollama_config(config)
        checks["CONFIG"] = "PASS"

        actual = {
            "main": sha(SRC / "main.py"),
            "scenario": sha(SRC / "scenario_corbitt.json"),
            "pcs": sha(SRC / "pcs.json"),
            "npcs": sha(SRC / "npcs.json"),
        }
        detail["input_hashes"] = actual
        checks["INPUT_IDENTITY"] = "PASS" if actual == EXPECTED else "FAIL"

        with tempfile.TemporaryDirectory(prefix="DRY_RUN_TEMP_SESSION_", dir=output) as temp_name:
            temp = Path(temp_name)
            for name in ("pcs.json", "npcs.json", "scenario_corbitt.json"):
                shutil.copy2(SRC / name, temp / name)
            shutil.copytree(SRC / "datasets", temp / "datasets")
            old = Path.cwd()
            os.chdir(temp)
            try:
                managers = main.init_game_system("scenario_corbitt.json")
                checks["CORE_CONSTRUCTOR"] = "PASS"
                char_mgr, _, state_mgr, scenario_mgr = managers
                state = runner._initial_state("scenario_corbitt.json", char_mgr, scenario_mgr, state_mgr)
                scenario_mgr.bind_game_state(state_mgr)
                main.begin_autonomous_runtime(state)
                checks["SESSION_PREFLIGHT"] = "PASS"
                checks["CYCLE0_PREFLIGHT"] = "PASS"
            finally:
                os.chdir(old)

        tags = api("/api/tags")
        checks["OLLAMA_HEALTH"] = "PASS"
        show = api("/api/show", {"model": "qwen2.5:14b"})
        model = {
            "name": "qwen2.5:14b",
            "family": show.get("details", {}).get("family"),
            "parameter_size": show.get("details", {}).get("parameter_size"),
            "quantization": show.get("details", {}).get("quantization_level"),
            "digest": next((m.get("digest") for m in tags.get("models", []) if m.get("name") == "qwen2.5:14b"), None),
        }
        detail["model"] = model
        checks["MODEL_IDENTITY"] = "PASS" if (
            model["family"], model["parameter_size"], model["quantization"]
        ) == ("qwen2", "14.8B", "Q4_K_M") and model["digest"] else "FAIL"
        generated = api("/api/generate", {
            "model": "qwen2.5:14b", "prompt": "Reply with exactly OK", "stream": False,
            "options": {"temperature": 0, "num_predict": 8, "seed": 2101},
        })
        detail["generation_response"] = str(generated.get("response") or "").strip()
        checks["OLLAMA_GENERATION_PROBE"] = "PASS" if detail["generation_response"] else "FAIL"

    checks["RUN_IDENTITY"] = "PASS"
    checks["OUTPUT_PREFLIGHT"] = "PASS"
    status = "PASS" if all(v == "PASS" for v in checks.values()) else "FAIL"
    result = {
        "schema_version": 1,
        "status": status,
        "persistent_session_created": False,
        "session_id": "DRY_RUN_TEMP_SESSION",
        "checks": checks,
        "detail": detail,
        "subprocess_audit": str(audit),
    }
    (output / "startup_dry_run.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(HERE / "artifacts" / "dry-run"))
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, indent=2))
