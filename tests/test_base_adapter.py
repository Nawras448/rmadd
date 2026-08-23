"""Tests for BaseAdapter.run_stream: OpResult plumbing, two-phase deadlines,
pgid-directed cleanup and pkexec->sudo fallback (Milestone 2 Step 1)."""

import concurrent.futures
import os
import shutil
import stat
import threading
import time

import pytest

from rmadd.models import PackageManager
from rmadd.package_managers.base import (
    BaseAdapter,
    FailureReason,
    OpResult,
)

BASE = "rmadd.package_managers.base"


class DummyAdapter(BaseAdapter):
    """Minimal concrete adapter whose commands are plain shell invocations."""

    def __init__(self, *, available=True, **kwargs):
        super().__init__(PackageManager.APT, **kwargs)
        self._available = available

    def list_installed(self):
        return []

    def get_info(self, name):
        return None

    def count(self):
        return 0

    def _install_cmd(self, name):
        return ["echo", f"install {name}"]

    def _remove_cmd(self, name):
        return ["echo", f"remove {name}"]

    def _update_cmd(self, name):
        return ["echo", f"update {name}"]

    def _update_all_cmd(self):
        return ["echo", "upgrade all"]


@pytest.fixture()
def as_root(monkeypatch):
    """Force the direct-exec path (no escalation prefixes)."""
    monkeypatch.setattr(f"{BASE}.os.geteuid", lambda: 0)


def _script(path, body):
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


@pytest.fixture()
def escalators(tmp_path, monkeypatch):
    """Fake pkexec/sudo tooling + fake non-root euid.

    Usage: escalators(pkexec="deny"|"pass"|None, sudo="deny"|"pass"|None)
    """
    created: dict[str, str] = {}

    def setup(pkexec=None, sudo=None):
        real_which = shutil.which
        for name, mode in (("pkexec", pkexec), ("sudo", sudo)):
            if mode is not None:
                body = {
                    "pass": 'exec "$@"',
                    "deny": 'echo "not authorized"; exit 9',
                    "fail": 'echo "weird nonmarker error"; exit 4',
                }[mode]
                created[name] = _script(tmp_path / name, body)

        def fake_which(binary):
            if binary in ("pkexec", "sudo"):
                return created.get(binary)
            return real_which(binary)

        monkeypatch.setattr(f"{BASE}.os.geteuid", lambda: 1000)
        monkeypatch.setattr("rmadd.package_managers.base.shutil.which", fake_which)
        return created

    return setup


# ------------------------------------------------------------------ happy --

def test_success_returns_ok_opresult(as_root):
    adapter = DummyAdapter()
    lines = []
    result = adapter.run_stream(["echo", "hello"], lines.append)
    assert isinstance(result, OpResult)
    assert result.ok is True
    assert result.reason is FailureReason.NONE
    assert "hello" in result.tail
    assert lines == ["hello\n"]


def test_run_stream_result_is_dataclass(as_root):
    adapter = DummyAdapter()
    result = adapter.run_stream(["echo", "hi"])
    assert (result.ok, result.cancelled, result.reason.name) == (True, False, "NONE")


def test_install_wrapper_returns_bool(as_root):
    adapter = DummyAdapter()
    assert adapter.install("vim") is True


# ---------------------------------------------------------------- failures --

def test_failure_reason_failed_with_tail(as_root):
    adapter = DummyAdapter()
    result = adapter.run_stream(["sh", "-c", "echo boom; exit 3"])
    assert result.ok is False
    assert result.reason is FailureReason.FAILED
    assert "boom" in result.tail
    assert result.describe() == "command failed"


def test_manager_missing_no_longer_raises():
    adapter = DummyAdapter(available=False)
    result = adapter.run_stream(["echo", "x"])
    assert result.ok is False
    assert result.reason is FailureReason.MANAGER_MISSING
    assert adapter.run_stream(["echo", "x"]).reason is FailureReason.MANAGER_MISSING


def test_auth_unavailable_when_no_escalation_tool(escalators):
    escalators(pkexec=None, sudo=None)
    adapter = DummyAdapter()
    result = adapter.run_stream(["echo", "x"])
    assert result.ok is False
    assert result.reason is FailureReason.AUTH_UNAVAILABLE


# ------------------------------------------------------------- deadlines --

def test_execution_timeout_after_first_output(as_root):
    adapter = DummyAdapter(execution_timeout=0.5)
    started = time.monotonic()
    result = adapter.run_stream(["sh", "-c", "echo warm; sleep 30"])
    elapsed = time.monotonic() - started
    assert result.ok is False
    assert result.reason is FailureReason.TIMEOUT
    assert elapsed < 10  # far below the 30s child sleep
    assert "warm" in result.tail


def test_auth_timeout_while_silent(as_root):
    adapter = DummyAdapter(auth_timeout=0.5)
    started = time.monotonic()
    result = adapter.run_stream(["sleep", "30"])
    elapsed = time.monotonic() - started
    assert result.ok is False
    assert result.reason is FailureReason.AUTH_TIMEOUT
    assert elapsed < 10


# ------------------------------------------------------------- cancelling --

def test_cancel_kills_entire_process_group(as_root, tmp_path, monkeypatch):
    adapter = DummyAdapter(execution_timeout=60)
    lines: list[str] = []
    cancel = threading.Event()
    pidfile = tmp_path / "leader.pid"
    # sh block-buffers stdout to pipes, so hand the leader pid over via file.
    monkeypatch.setenv("RMADD_TEST_PIDFILE", str(pidfile))
    cmd = ["sh", "-c", 'echo $$ > "$RMADD_TEST_PIDFILE"; sleep 30 & sleep 30']


    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(adapter.run_stream, cmd, lines.append, cancel)
        deadline = time.monotonic() + 5
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert pidfile.exists(), "child never wrote its pid"
        cancel.set()
        result = future.result(timeout=15)

    assert result.cancelled is True
    assert result.reason is FailureReason.CANCELLED
    leader_pid = int(pidfile.read_text().strip())
    # The whole group (incl. backgrounded sibling sleep) must die.
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        try:
            os.killpg(leader_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("process group survived cancellation")
    with pytest.raises(ProcessLookupError):
        os.killpg(leader_pid, 0)


# ------------------------------------------------------------- escalation --

def test_pkexec_denial_falls_back_to_sudo(escalators):
    escalators(pkexec="deny", sudo="pass")
    adapter = DummyAdapter()
    result = adapter.run_stream(["echo", "done"])
    assert result.ok is True
    assert result.reason is FailureReason.NONE


def test_single_denied_candidate_reports_auth_denied(escalators):
    # Only pkexec exists: denial exhausts the candidate list.
    escalators(pkexec="deny", sudo=None)
    adapter = DummyAdapter()
    result = adapter.run_stream(["echo", "x"])
    assert result.ok is False
    assert result.reason is FailureReason.AUTH_DENIED
    assert result.describe() == "authentication denied"


def test_nonmarker_failure_on_final_candidate_reports_failed(escalators):
    # pkexec denied (retry), sudo failed WITHOUT marker words -> FAILED.
    escalators(pkexec="deny", sudo="fail")
    adapter = DummyAdapter()
    result = adapter.run_stream(["echo", "x"])
    assert result.ok is False
    assert result.reason is FailureReason.FAILED


def test_sudo_passthrough_executes_command(escalators):
    created = escalators(sudo="pass")
    adapter = DummyAdapter()
    lines = []
    result = adapter.run_stream(["echo", "via-sudo"], lines.append)
    assert result.ok is True
    assert "via-sudo" in "".join(lines)
    assert created["sudo"]
