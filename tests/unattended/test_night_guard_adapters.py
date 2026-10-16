import os
from pathlib import Path
import subprocess
import sys

import pytest

from night_guard import (
    NetworkGuardAdapter, RepairAdapter, Stop, implementation_identity,
    dry_run_fault_injection,
)


def test_network_environment_is_single_pc_local_only():
    env = NetworkGuardAdapter().environment()
    assert env['EXECUTION_PROFILE'] == 'SINGLE_PC'
    assert env['PRIMARY_OLLAMA_URL'] == 'http://127.0.0.1:11434'
    assert env['SECONDARY_OLLAMA_URL'] == ''
    assert env['SECONDARY_FAILURE_POLICY'] == 'FAIL_CLOSED'
    assert all(key.upper() not in {'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'} for key in env)
    assert env['NO_PROXY'] == '127.0.0.1,localhost'


def test_paid_provider_is_rejected():
    with pytest.raises(Stop, match='PAID_API_BLOCKED'):
        NetworkGuardAdapter().provider('OPENAI_CLOUD')


def test_process_boundary_denies_external_socket():
    env = NetworkGuardAdapter().environment()
    code = "import socket; socket.create_connection(('1.1.1.1',443),.1)"
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'CORBITT_NETWORK_DENIED' in result.stderr


def test_process_boundary_denies_child_process():
    env = NetworkGuardAdapter().environment()
    code = "import subprocess; subprocess.run(['cmd','/c','exit','0'])"
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert 'CORBITT_PROCESS_BOUNDARY_DENIED' in result.stderr


def test_repair_registry_rejects_unknown(tmp_path):
    with pytest.raises(Stop, match='UNKNOWN_CAUSE'):
        RepairAdapter().stage('UNKNOWN', tmp_path / 'candidate')


def test_identity_is_nonempty_and_pinned():
    identity = implementation_identity()
    assert len(identity['aggregate']) == 64
    assert len(identity['files']) == 11


def test_all_fault_injections_stop(tmp_path):
    result = dry_run_fault_injection(tmp_path)
    assert result
    assert set(result.values()) == {'PASS'}
