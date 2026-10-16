import os
from pathlib import Path
import socket
import subprocess
import sys

import pytest

from runtime_boundary import (
    BoundaryViolation, NetworkBoundary, RestrictedRepairEnvironment, RuntimeBoundary,
    assert_local_ollama_config, guarded_startup, verify_implementation_identity,
    verify_model_identity, require_release_gate,
)


def test_unknown_subprocess_denied(tmp_path):
    with RuntimeBoundary(tmp_path / "audit.jsonl", allowed_executables=[sys.executable]):
        with pytest.raises(BoundaryViolation, match="SUBPROCESS_DENIED_UNKNOWN"):
            subprocess.run([sys.executable, "-c", "print('unexpected')"], check=True)


def test_known_trusted_subprocess_requires_purpose(tmp_path):
    with RuntimeBoundary(tmp_path / "audit.jsonl", allowed_executables=[sys.executable]) as guard:
        with guard.purpose("PYTHON_STDLIB_SYSTEM_QUERY"):
            result = subprocess.run([sys.executable, "-c", "print('OK')"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "OK"


def test_external_network_denied(tmp_path):
    with NetworkBoundary(tmp_path / "audit.jsonl"):
        with pytest.raises(BoundaryViolation, match="NETWORK_DENIED"):
            socket.create_connection(("1.1.1.1", 443), timeout=0.01)


def test_paid_api_and_remote_ollama_denied():
    with pytest.raises(BoundaryViolation, match="PAID_API_BLOCKED"):
        assert_local_ollama_config({"primary_root_url": "http://127.0.0.1:11434", "api_key": "paid-key"})
    with pytest.raises(BoundaryViolation, match="REMOTE_OLLAMA_DENIED"):
        assert_local_ollama_config({"primary_root_url": "http://127.0.0.1:11434", "api_key": "ollama", "secondary_explicit": True})


def test_old_run_write_denied(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    old_run = tmp_path / "CORBITT_LONGRUN_ITERATION3_V4_HOME_001" / "result.json"
    old_run.parent.mkdir()
    with RestrictedRepairEnvironment(root, root / "audit.jsonl"):
        with pytest.raises(BoundaryViolation, match="WRITE_DENIED"):
            open(old_run, "w", encoding="utf-8")
        with pytest.raises(BoundaryViolation, match="WRITE_DENIED"):
            old_run.write_text("bad", encoding="utf-8")
        with pytest.raises(BoundaryViolation, match="WRITE_DENIED"):
            os.open(old_run, os.O_WRONLY | os.O_CREAT)


def test_repair_shell_and_network_denied(tmp_path):
    root = tmp_path / "candidate"
    root.mkdir()
    with RestrictedRepairEnvironment(root, root / "audit.jsonl"):
        with pytest.raises(BoundaryViolation, match="SUBPROCESS_DENIED_UNKNOWN"):
            subprocess.run("echo bad", shell=True)
        sock = socket.socket()
        with pytest.raises(BoundaryViolation, match="NETWORK_DENIED"):
            sock.connect(("127.0.0.1", 11434))
        sock.close()


def test_model_mismatch_stops():
    expected = {"name": "qwen2.5:14b", "family": "qwen2", "parameter_size": "14.8B", "quantization": "Q4_K_M", "digest": "good"}
    actual = {**expected, "digest": "different"}
    with pytest.raises(BoundaryViolation, match="MODEL_IDENTITY_MISMATCH"):
        verify_model_identity(actual, expected)


def test_implementation_drift_stops():
    with pytest.raises(BoundaryViolation, match="IMPLEMENTATION_IDENTITY_MISMATCH"):
        verify_implementation_identity({"core": "changed"}, {"core": "accepted"})


def test_runtime_error_stops_without_replacement():
    def crash():
        raise RuntimeError("injected")
    with pytest.raises(BoundaryViolation, match="STOP_RUNTIME_ERROR"):
        guarded_startup(crash)


def test_input_identity_failure_stops():
    with pytest.raises(BoundaryViolation, match="INPUT_IDENTITY_GATE_FAILED"):
        require_release_gate("input_identity", "FAIL")


def test_regression_failure_stops():
    with pytest.raises(BoundaryViolation, match="REGRESSION_GATE_FAILED"):
        require_release_gate("regression", "FAIL")
