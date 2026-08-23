"""M2 Step 3 tests: OpReport aggregation, batch isolation, executor
consolidation (named long-lived pools, shutdown) and timeout plumbing."""

import threading
import time

import pytest

from rmadd.config import Config
from rmadd.models import PackageManager
from rmadd.package_managers import base as base_mod
from rmadd.package_managers.base import (
    BaseAdapter,
    FailureReason,
    OpReport,
    OpResult,
)
from rmadd.package_managers.local import LocalBinaryScanner
from rmadd.package_managers.service import PackageManagerService

BASE = "rmadd.package_managers.base"
APT = PackageManager.APT
DPKG = PackageManager.DPKG
FLATPAK = PackageManager.FLATPAK


class ScriptAdapter(BaseAdapter):
    """Adapter whose mutating commands run configurable shell snippets."""

    def __init__(self, manager, update_all_cmd, available=True):
        super().__init__(manager)
        self._available = available
        self._update_all_cmd_shell = update_all_cmd
        self.seen_threads: list[str] = []

    def list_installed(self):
        self.seen_threads.append(threading.current_thread().name)
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
        return self._update_all_cmd_shell


def _ok_adapter(mgr):
    return ScriptAdapter(mgr, ["echo", "upgrading all"])


def _failing_adapter(mgr):
    return ScriptAdapter(mgr, ["sh", "-c", "echo boom; exit 3"])


@pytest.fixture()
def as_root(monkeypatch):
    monkeypatch.setattr(f"{BASE}.os.geteuid", lambda: 0)


@pytest.fixture(autouse=True)
def _isolate_disk_cache(tmp_path, monkeypatch):
    """Keep the service's disk cache off the real user cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


# ------------------------------------------------------------- OpReport --

def test_empty_report_is_ok_and_describes_nothing():
    r = OpReport()
    assert r.ok is True and r.cancelled is False and r.failures == []
    assert r.describe() == "nothing executed"


def test_report_aggregates_successes_failures_and_skips():
    r = OpReport()
    r.entries.append(("apt", OpResult(True)))
    r.entries.append(("flatpak", OpResult(False, reason=FailureReason.TIMEOUT)))
    r.entries.append(("cargo@cargo", OpResult(False, cancelled=True,
                                             reason=FailureReason.CANCELLED)))
    r.skipped.extend(["npm", "gem"])
    assert r.ok is False and r.cancelled is True
    assert [k for k, _ in r.failures] == ["flatpak", "cargo@cargo"]
    d = r.describe()
    assert "1/3 succeeded" in d and "cancelled" in d
    assert "command timed out" in d and "skipped: npm, gem" in d


# ------------------------------------------------------------ run_batch --

def _service_with(adapters):
    return PackageManagerService({m: a for m, a in adapters.items()})


def test_run_batch_isolates_individual_failures(as_root):
    apt, fpk = _ok_adapter(APT), _failing_adapter(FLATPAK)
    svc = _service_with({APT: apt, FLATPAK: fpk})
    try:
        out: list[str] = []
        report = svc.run_batch(
            "update_all", [(None, APT), (None, FLATPAK)], out.append
        )
        assert len(report.entries) == 2
        assert report.ok is False and not report.skipped
        assert dict(report.entries)[APT.value].ok is True
        failed = dict(report.failures)
        assert failed[FLATPAK.value].reason is FailureReason.FAILED
        assert "boom" in failed[FLATPAK.value].tail
        # streaming context headers reached the shared output sink
        assert out[0] == f"==> {APT.value}\n"
        assert f"==> {FLATPAK.value}\n" in out
    finally:
        svc.shutdown()


def test_run_batch_pre_cancelled_records_skips(as_root):
    svc = _service_with({APT: _ok_adapter(APT)})
    try:
        ev = threading.Event()
        ev.set()
        report = svc.run_batch("update_all", [(None, APT)], None, ev)
        assert report.entries == [] and report.skipped == [APT.value]
        assert report.describe() == "nothing executed"
    finally:
        svc.shutdown()


def test_run_batch_mid_cancel_finishes_entry_then_skips_rest(as_root, tmp_path):
    flag = tmp_path / "started.flag"
    slow = ScriptAdapter(APT, ["sh", "-c", f"touch {flag}; sleep 5"])
    svc = _service_with({APT: slow, FLATPAK: _ok_adapter(FLATPAK)})
    try:
        ev = threading.Event()
        deadline = time.monotonic() + 5
        result_box: list = []

        def runner():
            result_box.append(svc.run_batch(
                "update_all", [(None, APT), (None, FLATPAK)], None, ev
            ))

        worker = threading.Thread(target=runner)
        worker.start()
        while not flag.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        ev.set()
        worker.join(timeout=15)

        report: OpReport = result_box[0]
        apt_res = dict(report.entries)[APT.value]
        assert apt_res.cancelled is True
        assert apt_res.reason is FailureReason.CANCELLED
        assert report.skipped == [FLATPAK.value]
    finally:
        svc.shutdown()


def test_run_batch_survives_source_exceptions(as_root):
    class BrokenSource:
        def supports(self, op):
            return True

        # NOTE: no update_all attribute -> _op_result raises AttributeError

    svc = _service_with({APT: BrokenSource(), FLATPAK: _ok_adapter(FLATPAK)})
    try:
        report = svc.run_batch("update_all", [(None, APT), (None, FLATPAK)])
        assert report.ok is False
        broken = dict(report.failures)[APT.value]
        assert broken.reason is FailureReason.FAILED
        assert dict(report.entries)[FLATPAK.value].ok is True
    finally:
        svc.shutdown()


def test_batch_update_all_selects_capable_managers_only(as_root):
    svc = _service_with({APT: _ok_adapter(APT), DPKG: _ok_adapter(DPKG)})
    try:
        report = svc.batch_update_all()
        assert [k for k, _ in report.entries] == [APT.value]  # dpkg lacks cap
        assert report.ok is True
    finally:
        svc.shutdown()


# ------------------------------------------------ executor consolidation --

def test_fetch_pool_is_long_lived_and_named(as_root):
    apt = _ok_adapter(APT)
    fpk = _ok_adapter(FLATPAK)
    svc = _service_with({APT: apt, FLATPAK: fpk})
    try:
        svc.list_installed()
        first = set(apt.seen_threads) | set(fpk.seen_threads)
        svc.invalidate_installed()
        svc.list_installed()
        second = set(apt.seen_threads) | set(fpk.seen_threads)
        assert first and second
        assert first == second                       # same workers reused
        assert all(n.startswith("rmadd-fetch_") for n in second)
        query_thread_ok = True                       # query pool separately named
        assert svc._pool._thread_name_prefix == "rmadd-query"
        assert query_thread_ok
    finally:
        svc.shutdown()


def test_shutdown_releases_pools(as_root):
    svc = _service_with({APT: _ok_adapter(APT)})
    svc.shutdown()
    with pytest.raises(RuntimeError):
        svc._pool.submit(lambda: None)
    with pytest.raises(RuntimeError):
        svc._fetch_pool.submit(lambda: None)


# ------------------------------------------------------- scanner probes --

def _make_bin(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(f"#!/bin/sh\n{body}\n")
    p.chmod(0o755)
    return str(tmp_path)


def test_scanner_probe_pool_persisted_and_closable(tmp_path):
    _make_bin(tmp_path, "toolA", "echo toolA 1.0")
    _make_bin(tmp_path, "toolB", "echo toolB 2.0")
    scanner = LocalBinaryScanner(
        search_dirs=[str(tmp_path)], version_timeout=1, probe_limit=8
    )
    try:
        scanner.list_packages()
        pool_a = scanner._probe_pool
        assert pool_a is not None
        scanner.list_packages()
        assert scanner._probe_pool is pool_a         # reused, not recreated
        scanner.close()
        assert scanner._probe_pool is None
        with pytest.raises(RuntimeError):
            pool_a.submit(lambda: None)
    finally:
        scanner.close()


# ------------------------------------------------------ timeout plumbing --

def test_config_timeout_roundtrip_and_validation(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg = Config(str(cfg_file))
    cfg.op_timeout_seconds = 90
    assert cfg.op_timeout_seconds == 90.0
    cfg.save()
    assert Config(str(cfg_file)).op_timeout_seconds == 90.0
    for bad in (-5, 0, None, "abc"):
        with pytest.raises(ValueError):
            cfg.op_timeout_seconds = bad


def test_config_setter_propagates_to_new_adapters(tmp_path, monkeypatch):
    monkeypatch.setattr(base_mod, "_execution_timeout_override", None)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    cfg = Config(str(tmp_path / "config.json"))
    cfg.op_timeout_seconds = 77
    adapter = ScriptAdapter(APT, ["echo", "x"])
    assert adapter.execution_timeout == pytest.approx(77.0)
    # loader honours the override directly as well
    assert base_mod._configured_execution_timeout() == pytest.approx(77.0)


def test_default_fallback_when_unconfigured(monkeypatch):
    monkeypatch.setattr(base_mod, "_execution_timeout_override", None)
    from rmadd.config import Config as _C

    orig_get = _C.op_timeout_seconds.fget
    monkeypatch.setattr(
        _C, "op_timeout_seconds",
        property(lambda self: float("nan")), raising=True,
    )
    try:
        assert base_mod._configured_execution_timeout() == 600.0
    finally:
        monkeypatch.setattr(_C, "op_timeout_seconds", property(orig_get))
