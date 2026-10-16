"""Three-layer runtime boundary for unattended local evaluation.

This module is intentionally outside production ``src``.  It provides a
trusted runtime, a restricted repair environment, and a localhost-only
network boundary without adding one-off exceptions for ``platform.system``.
"""
from __future__ import annotations

import builtins
import contextlib
import datetime as dt
import ipaddress
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys


class BoundaryViolation(RuntimeError):
    pass


def _now():
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat()


def _exe(command):
    if isinstance(command, (str, bytes)):
        return str(command).strip().split()[0] if str(command).strip() else ""
    return str(command[0]) if command else ""


def _resolved_executable(executable):
    """Resolve PATH-based commands to the exact executable they invoke."""
    candidate = shutil.which(str(executable)) or str(executable)
    try:
        return str(Path(candidate).resolve()).casefold()
    except (OSError, ValueError):
        return str(candidate).casefold()


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event):
        row = {"timestamp": _now(), **event}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


class RuntimeBoundary:
    """Trusted parent + known purpose + exact executable process policy."""

    def __init__(self, audit_path, *, allowed_executables=()):
        self.audit = AuditLog(audit_path)
        self.allowed = {_resolved_executable(p) for p in allowed_executables}
        self._purpose = None
        self._original_popen = None

    @contextlib.contextmanager
    def purpose(self, reason):
        old = self._purpose
        self._purpose = str(reason)
        try:
            yield
        finally:
            self._purpose = old

    def install(self):
        if self._original_popen is not None:
            return self
        self._original_popen = subprocess.Popen
        boundary = self

        class GuardedPopen(boundary._original_popen):
            def __init__(self, args, *pargs, **kwargs):
                executable = _exe(args)
                shell = bool(kwargs.get("shell"))
                platform_ver_probe = (
                    shell
                    and boundary._purpose == "PYTHON_STDLIB_PLATFORM_SYSTEM"
                    and str(args).strip().casefold() == "ver"
                )
                if platform_ver_probe:
                    executable = os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe")
                resolved = _resolved_executable(executable)
                allowed = bool(boundary._purpose) and resolved in boundary.allowed and (
                    not shell or platform_ver_probe
                )
                boundary.audit.write({
                    "event": "subprocess",
                    "parent": sys.executable,
                    "child_executable": executable,
                    "arguments": list(args) if isinstance(args, (list, tuple)) else str(args),
                    "reason_category": boundary._purpose or "UNKNOWN",
                    "allowed": allowed,
                    "decision": "ALLOW" if allowed else "SUBPROCESS_DENIED_UNKNOWN",
                })
                if not allowed:
                    raise BoundaryViolation("SUBPROCESS_DENIED_UNKNOWN")
                super().__init__(args, *pargs, **kwargs)

        subprocess.Popen = GuardedPopen
        return self

    def uninstall(self):
        if self._original_popen is not None:
            subprocess.Popen = self._original_popen
            self._original_popen = None

    def __enter__(self):
        return self.install()

    def __exit__(self, *_):
        self.uninstall()


class NetworkBoundary:
    """Permit only local Ollama at 127.0.0.1:11434."""

    def __init__(self, audit_path):
        self.audit = AuditLog(audit_path)
        self._connect = None
        self._create = None

    @staticmethod
    def validate(address):
        if not isinstance(address, tuple) or len(address) < 2:
            raise BoundaryViolation("NETWORK_DENIED")
        host, port = str(address[0]), int(address[1])
        aliases = {"localhost": "127.0.0.1", "::1": "127.0.0.1"}
        normalized = aliases.get(host.casefold(), host)
        try:
            ip = ipaddress.ip_address(normalized)
        except ValueError as exc:
            raise BoundaryViolation("NETWORK_DENIED") from exc
        if not ip.is_loopback or str(ip) != "127.0.0.1" or port != 11434:
            raise BoundaryViolation("NETWORK_DENIED")
        return "127.0.0.1", 11434

    def install(self):
        if self._connect is not None:
            return self
        self._connect = socket.socket.connect
        self._create = socket.create_connection
        boundary = self

        def guarded_connect(sock, address):
            try:
                target = boundary.validate(address)
                allowed = True
            except BoundaryViolation:
                target, allowed = address, False
            boundary.audit.write({"event": "network", "target": str(address), "allowed": allowed})
            if not allowed:
                raise BoundaryViolation("NETWORK_DENIED")
            return boundary._connect(sock, target)

        def guarded_create(address, *args, **kwargs):
            target = boundary.validate(address)
            boundary.audit.write({"event": "network", "target": str(address), "allowed": True})
            return boundary._create(target, *args, **kwargs)

        socket.socket.connect = guarded_connect
        socket.create_connection = guarded_create
        return self

    def uninstall(self):
        if self._connect is not None:
            socket.socket.connect = self._connect
            socket.create_connection = self._create
            self._connect = self._create = None

    def __enter__(self):
        return self.install()

    def __exit__(self, *_):
        self.uninstall()


class RestrictedRepairEnvironment:
    """Deny shell/process/network/install/pull and writes outside candidate root."""

    BLOCKED_TOKENS = {"pip", "uv", "conda", "npm", "winget", "ollama"}

    def __init__(self, candidate_root, audit_path):
        self.root = Path(candidate_root).resolve()
        self.audit = AuditLog(audit_path)
        self._open = None
        self._io_open = None
        self._os_open = None
        self._popen = None
        self._connect = None

    def _check_write(self, path, mode):
        if not any(flag in str(mode) for flag in ("w", "a", "x", "+")):
            return
        resolved = Path(path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            self.audit.write({"event": "write", "path": str(resolved), "allowed": False})
            raise BoundaryViolation("WRITE_DENIED") from exc

    def __enter__(self):
        self._open, self._io_open, self._os_open = builtins.open, io.open, os.open
        self._popen, self._connect = subprocess.Popen, socket.socket.connect
        env = self

        def guarded_open(file, mode="r", *args, **kwargs):
            env._check_write(file, mode)
            return env._open(file, mode, *args, **kwargs)

        def guarded_io_open(file, mode="r", *args, **kwargs):
            env._check_write(file, mode)
            return env._io_open(file, mode, *args, **kwargs)

        def guarded_os_open(file, flags, *args, **kwargs):
            write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC
            if flags & write_flags:
                env._check_write(file, "w")
            return env._os_open(file, flags, *args, **kwargs)

        def deny_process(*args, **kwargs):
            env.audit.write({"event": "repair_subprocess", "arguments": str(args[0] if args else ""), "allowed": False})
            raise BoundaryViolation("SUBPROCESS_DENIED_UNKNOWN")

        def deny_network(sock, address):
            env.audit.write({"event": "repair_network", "target": str(address), "allowed": False})
            raise BoundaryViolation("NETWORK_DENIED")

        builtins.open, io.open, os.open = guarded_open, guarded_io_open, guarded_os_open
        subprocess.Popen, socket.socket.connect = deny_process, deny_network
        return self

    def __exit__(self, *_):
        builtins.open, io.open, os.open = self._open, self._io_open, self._os_open
        subprocess.Popen, socket.socket.connect = self._popen, self._connect


def assert_local_ollama_config(config):
    endpoint = str(config.get("primary_root_url") or config.get("base_url") or "")
    endpoint = endpoint.replace("localhost", "127.0.0.1")
    if not endpoint.startswith("http://127.0.0.1:11434"):
        raise BoundaryViolation("NETWORK_DENIED")
    if config.get("secondary_explicit"):
        raise BoundaryViolation("REMOTE_OLLAMA_DENIED")
    if str(config.get("api_key") or "ollama") != "ollama":
        raise BoundaryViolation("PAID_API_BLOCKED")


def verify_model_identity(actual, expected):
    keys = ("name", "family", "parameter_size", "quantization", "digest")
    if any(expected.get(key) and actual.get(key) != expected.get(key) for key in keys):
        raise BoundaryViolation("MODEL_IDENTITY_MISMATCH")
    return True


def verify_implementation_identity(actual, expected):
    if actual != expected:
        raise BoundaryViolation("IMPLEMENTATION_IDENTITY_MISMATCH")
    return True


def guarded_startup(callable_):
    try:
        return callable_()
    except BoundaryViolation:
        raise
    except Exception as exc:
        raise BoundaryViolation("STOP_RUNTIME_ERROR") from exc


def require_release_gate(name, status):
    if str(status).upper() != "PASS":
        raise BoundaryViolation(f"{str(name).upper()}_GATE_FAILED")
    return True
