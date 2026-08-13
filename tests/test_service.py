"""Tests for the SWR installed-package cache and O(1) status lookup."""

import json
import os
import time

import pytest

from rmadd.models import Package, PackageCollection, PackageManager, PackageStatus
from rmadd.package_managers.service import PackageManagerService


class FakeAdapter:
    def __init__(self, packages, *, fail=False):
        self._packages = list(packages)
        self._fail = fail
        self.calls = 0

    def list_installed(self):
        self.calls += 1
        if self._fail:
            raise RuntimeError("boom")
        return [p for p in self._packages]

    def get_status(self, name):
        if any(p.name == name for p in self._packages):
            return PackageStatus.INSTALLED
        return PackageStatus.AVAILABLE

    def count(self):
        return len(self._packages)


APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK


@pytest.fixture(autouse=True)
def _isolate_disk_cache(tmp_path, monkeypatch):
    """Point the on-disk cache at a per-test temp dir so tests never read or
    write the real user cache, and each test starts from an empty cache."""
    cache_dir = tmp_path / "xdg-cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_dir))
    return cache_dir


def _pkg(name, mgr):
    return Package(name=name, manager=mgr)


def _service(adapters=None):
    adapters = adapters or {
        APT: FakeAdapter([_pkg("htop", APT), _pkg("git", APT)]),
        FLATPAK: FakeAdapter([_pkg("spotify", FLATPAK)]),
    }
    return PackageManagerService(adapters)


def _force_changed_mtimes(svc, monkeypatch):
    """Patch _system_mtimes to report a fresh value on every call.

    This disables the mtime skip guard so background refreshes actually run
    (the real monitored paths on the host are typically unchanged).
    """
    monkeypatch.setattr(
        svc,
        "_system_mtimes",
        lambda: {APT: time.time()},
    )


def _wait_sync(svc):
    deadline = time.monotonic() + 5
    while svc._is_syncing_installed and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not svc._is_syncing_installed


def test_cold_boot_populates_cache_and_detaches():
    svc = _service()
    result = svc.list_installed()
    assert {p.name for p in result} == {"htop", "git", "spotify"}
    assert svc._installed_cache is not None
    assert svc._installed_names[APT] == frozenset({"htop", "git"})
    next(iter(result)).name = "mutated"
    cached = PackageCollection(
        [p for col in svc._installed_cache[1].values() for p in col]
    )
    assert all(p.name != "mutated" for p in cached)


def test_fresh_cache_returns_cached_data_without_refetch():
    svc = _service()
    svc.list_installed()
    before = sum(a.calls for a in svc._sources.values())
    again = svc.list_installed()
    assert {p.name for p in again} == {"htop", "git", "spotify"}
    after = sum(a.calls for a in svc._sources.values())
    assert after == before


def test_stale_cache_serves_immediately_and_refreshes_in_background(monkeypatch):
    svc = _service()
    svc.list_installed()
    _force_changed_mtimes(svc, monkeypatch)
    ts, _ = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, svc._installed_cache[1])

    start = time.monotonic()
    result = svc.list_installed()
    elapsed = time.monotonic() - start
    assert {p.name for p in result} == {"htop", "git", "spotify"}
    assert elapsed < 1.0

    _wait_sync(svc)
    ts2, _ = svc._installed_cache
    assert ts2 > ts


def test_concurrent_stale_calls_schedule_single_refresh(monkeypatch):
    svc = _service()
    svc.list_installed()
    _force_changed_mtimes(svc, monkeypatch)
    ts, data = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, data)

    from threading import Thread

    threads = [Thread(target=svc.list_installed) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    _wait_sync(svc)


def test_manager_specific_lookup_uses_cache():
    svc = _service()
    svc.list_installed()
    before = svc._sources[APT].calls
    col = svc.list_installed(APT)
    assert {p.name for p in col} == {"htop", "git"}
    assert svc._sources[APT].calls == before


def test_get_status_is_o1_set_lookup():
    svc = _service()
    svc.list_installed()
    adapter = svc._sources[APT]
    before = adapter.calls
    assert svc.get_status("htop", APT) == PackageStatus.INSTALLED
    assert svc.get_status("missing", APT) == PackageStatus.AVAILABLE
    assert adapter.calls == before


def test_get_status_falls_back_when_cache_empty():
    svc = _service()
    assert svc.get_status("htop", APT) == PackageStatus.INSTALLED


def test_invalidate_clears_cache():
    svc = _service()
    svc.list_installed()
    assert svc._installed_cache is not None
    svc.invalidate_installed()
    assert svc._installed_cache is None
    assert svc._installed_names == {}
    assert svc.list_installed().total == 3


def test_invalidate_counts_also_invalidates_installed():
    svc = _service()
    svc.list_installed()
    assert svc._installed_cache is not None
    svc.invalidate_counts()
    assert svc._installed_cache is None


def test_bg_refresh_emits_signal(monkeypatch):
    from rmadd.state import PackageStateBus

    emitted = []
    bus = PackageStateBus()
    bus.subscribe(lambda kind, name, mgr, phase: emitted.append((kind, name, mgr, phase)))
    svc = _service()
    svc.set_state_bus(bus)
    svc.list_installed()
    _force_changed_mtimes(svc, monkeypatch)
    ts, data = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, data)
    svc.list_installed()
    deadline = time.monotonic() + 5
    while not emitted and time.monotonic() < deadline:
        time.sleep(0.01)
    assert emitted and emitted[-1][0] == svc.INSTALLED_REFRESH_EVENT


def test_bg_refresh_skips_subprocess_when_mtime_unchanged(monkeypatch):
    svc = _service()
    svc.list_installed()
    monkeypatch.setattr(svc, "_system_mtimes", lambda: {APT: 1.0})
    svc._installed_mtimes = {APT: 1.0}
    before = {m: a.calls for m, a in svc._sources.items()}
    ts, data = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, data)

    svc.list_installed()
    _wait_sync(svc)

    after = {m: a.calls for m, a in svc._sources.items()}
    assert after == before
    ts2, _ = svc._installed_cache
    assert ts2 > ts


def test_bg_refresh_fetches_when_mtime_changed(monkeypatch):
    svc = _service()
    svc.list_installed()
    monkeypatch.setattr(svc, "_system_mtimes", lambda: {APT: time.time()})
    svc._installed_mtimes = {APT: 1.0}
    before = {m: a.calls for m, a in svc._sources.items()}
    ts, data = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, data)

    svc.list_installed()
    _wait_sync(svc)

    after = {m: a.calls for m, a in svc._sources.items()}
    assert any(after[m] > before[m] for m in before)
    assert svc._installed_mtimes[APT] > 1.0


def test_unmonitored_manager_does_not_block_skip(monkeypatch):
    svc = _service({
        APT: FakeAdapter([_pkg("htop", APT)]),
        PackageManager.NPM: FakeAdapter([_pkg("lodash", PackageManager.NPM)]),
    })
    svc.list_installed()
    monkeypatch.setattr(svc, "_system_mtimes", lambda: {APT: 1.0})
    svc._installed_mtimes = {APT: 1.0}
    before = {m: a.calls for m, a in svc._sources.items()}
    ts, data = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, data)

    svc.list_installed()
    _wait_sync(svc)

    after = {m: a.calls for m, a in svc._sources.items()}
    assert after == before


def test_inaccessible_monitored_path_forces_fetch(monkeypatch):
    svc = _service()
    svc.list_installed()
    monkeypatch.setattr(svc, "_system_mtimes", lambda: {})
    svc._installed_mtimes = {APT: 1.0}
    before = {m: a.calls for m, a in svc._sources.items()}
    ts, data = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, data)

    svc.list_installed()
    _wait_sync(svc)

    after = {m: a.calls for m, a in svc._sources.items()}
    assert any(after[m] > before[m] for m in before)


def test_max_mtime_ignores_missing_paths(tmp_path):
    assert PackageManagerService._max_mtime(("/nonexistent/definitely/missing",)) is None

    a = tmp_path / "a"
    b = tmp_path / "b"
    a.write_text("a")
    b.write_text("b")
    os.utime(a, (1_000_000, 1_000_000))
    os.utime(b, (2_000_000, 2_000_000))
    assert PackageManagerService._max_mtime((str(a), str(b))) == 2_000_000
    assert PackageManagerService._max_mtime((str(a), str(b), str(tmp_path / "missing"))) == 2_000_000


def test_cold_boot_loads_from_disk_cache():
    svc1 = _service()
    svc1.list_installed()
    path = PackageManagerService._installed_disk_cache_path()
    assert os.path.exists(path)

    svc2 = _service()
    result = svc2.list_installed()
    assert {p.name for p in result} == {"htop", "git", "spotify"}
    assert all(a.calls == 0 for a in svc2._sources.values())
    assert svc2._installed_cache is not None


def test_cold_boot_schedules_background_refresh():
    svc = _service()
    svc.list_installed()
    svc2 = _service()
    svc2.list_installed()
    _wait_sync(svc2)
    assert not svc2._is_syncing_installed


def test_corrupted_disk_cache_falls_back():
    path = PackageManagerService._installed_disk_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("{not valid json!!!")

    svc = _service()
    result = svc.list_installed()
    assert {p.name for p in result} == {"htop", "git", "spotify"}
    assert all(a.calls == 1 for a in svc._sources.values())


def test_refresh_updates_disk_cache(monkeypatch):
    svc = _service()
    svc.list_installed()
    _force_changed_mtimes(svc, monkeypatch)
    ts, data = svc._installed_cache
    svc._installed_cache = (ts - svc.INSTALLED_TTL - 1, data)

    svc.list_installed()
    _wait_sync(svc)

    path = PackageManagerService._installed_disk_cache_path()
    with open(path) as fh:
        payload = json.load(fh)
    assert payload["version"] == PackageManagerService.DISK_CACHE_VERSION
    assert payload["mtimes"][APT.value] > 1.0
    assert APT.value in payload["managers"]


def test_disk_cache_load_skips_unregistered_managers():
    svc = _service()
    svc.list_installed()
    payload = {
        "version": PackageManagerService.DISK_CACHE_VERSION,
        "saved_at": time.time(),
        "mtimes": {APT.value: 1.0, "npm": 2.0},
        "managers": {
            APT.value: [
                {"name": "htop", "version": "3.3.0", "manager": APT.value,
                 "status": "installed"},
            ],
            "npm": [
                {"name": "lodash", "version": "4.17.21", "manager": "npm",
                 "status": "installed"},
            ],
        },
    }
    path = PackageManagerService._installed_disk_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(payload, fh)

    svc = _service()
    result = svc.list_installed()
    assert {p.name for p in result} == {"htop"}
    assert PackageManager.NPM not in svc._installed_names
