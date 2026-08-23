"""M4 search-responsiveness tests: debounce collapse, exclusive workers,
thread-offloaded matching, no-requery guarantee and progressive tables."""

import asyncio
import time

import pytest

pytest.importorskip("textual")

from rmadd.hardware import HardwareMonitorService
from rmadd.models import Package, PackageCollection, PackageManager
from rmadd.package_managers.service import PackageManagerService
from rmadd.system_info import SystemInfoService
from rmadd.tui import RmaddTuiApp
from tests.test_m3_step1 import TableHarness
from tests.test_store_screen_smoke import (
    FakeHardwareDS,
    FakeSource,
    FakeSystemDS,
    _wait_until,
)

APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK


class CountingSource(FakeSource):
    """Tracks list_installed() invocations to prove no re-querying."""

    def __init__(self, mgr, names):
        super().__init__(mgr, names)
        self.list_calls = 0

    def list_installed(self):
        self.list_calls += 1
        return super().list_installed()


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    svc = PackageManagerService({
        APT: CountingSource(APT, ["git", "htop", "curl"]),
        FLATPAK: CountingSource(FLATPAK, ["spotify"]),
    })
    return RmaddTuiApp(
        SystemInfoService(FakeSystemDS()),
        svc,
        HardwareMonitorService(FakeHardwareDS()),
    )


def _big_collection(n=1200):
    pkgs = []
    for i in range(n):
        mgr = APT if i % 2 else FLATPAK
        pkgs.append(Package(name=f"pkg{i:05d}", manager=mgr, version="1.0"))
    return PackageCollection(pkgs)


async def _settle(pilot, seconds=0.6):
    await pilot.pause(seconds)


# ---------------------------------------------------- debounce collapse --

def test_rapid_typing_collapses_to_single_filter_run(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)

            applied: list[str] = []
            orig = store.installed.apply_filter

            def counting(query):
                applied.append(query)
                return orig(query)

            monkeypatch.setattr(store.installed, "apply_filter", counting)

            # 6 keystrokes back-to-back (zero gap => true rapid typing)
            for q in ("g", "gi", "git", "g", "gi", "git"):
                store.installed.schedule_filter(q)

            await _settle(pilot, 0.5)
            assert applied == ["git"], applied          # one run, final query

    asyncio.run(scenario())


def test_live_search_exclusive_worker_cancels_superseded_runs(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)

            ran: list[str] = []
            orig = store.search.run

            async def counting(query, managers=None):
                ran.append(query)
                return await orig(query, managers)

            monkeypatch.setattr(store.search, "run", counting)

            for q in ("a", "ap", "app", "appl"):
                store.search.schedule_live(q)
                await pilot.pause(0.04)

            await _settle(pilot, 1.0)
            assert ran == ["appl"], ran                 # only final query ran

    asyncio.run(scenario())


# --------------------------------------------------- no manager re-query --

def test_installed_filtering_never_requeries_managers(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            calls_before = sum(s.list_calls for s in app.package_service._sources.values())

            for q in ("g", "gi", "git", "gi", "g", ""):
                store.installed.schedule_filter(q)
                await pilot.pause(0.03)
            await _settle(pilot, 0.6)

            calls_after = sum(s.list_calls for s in app.package_service._sources.values())
            assert calls_after == calls_before         # pure in-memory filtering

    asyncio.run(scenario())


# ----------------------------------------------- thread-offload pathway --

def test_large_dataset_offloads_match_to_thread(tmp_path, monkeypatch):
    async def scenario():
        from rmadd.controllers.installed_controller import InstalledController

        monkeypatch.setattr(
            InstalledController, "_THREAD_FILTER_MIN_ROWS", 1
        )
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")
            await pilot.pause(0.2)

            store.installed.schedule_filter("git")
            ok = await _wait_until(
                lambda: _visible_names_are(store, {"git"})
            )
            assert ok, "thread-offloaded filter did not render"

    asyncio.run(scenario())


def _visible_names_are(store, expected):
    table = store.query_one("#installed-table")
    names = {
        str(table._table.get_row_at(r)[1])
        for r in range(table._table.row_count)
    }
    return names == expected


# ------------------------------------------------ progressive DataTable --

def test_progressive_population_batches_and_drains(tmp_path, monkeypatch):
    async def scenario():
        from textual.widgets import DataTable

        calls = {"batch": 0}
        orig_batch = DataTable.batch

        def counting_batch(self):
            calls["batch"] += 1
            return orig_batch(self)

        monkeypatch.setattr(DataTable, "batch", counting_batch)

        app = TableHarness()
        async with app.run_test(size=(120, 30)) as pilot:
            pt = app.pt
            big = _big_collection(1200)
            pt.show_packages(big)
            await pilot.pause()

            # Head painted instantly; remainder may still be draining.
            assert 400 <= pt._table.row_count <= 1200
            expected_head = [w[0] for w in pt._wanted_rows(big)[:400]]
            assert pt._row_keys[: len(expected_head)] == expected_head

            if pt._bulk_pending:
                pt._drain_bulk_blocking()
            assert pt._table.row_count == 1200
            assert len(pt._row_keys) == 1200
            # canonical order preserved through chunked adds
            expected_last = str(pt._wanted_rows(big)[-1][1][1])
            assert str(pt._table.get_row_at(1199)[1]) == expected_last
            assert calls["batch"] >= 1                  # mutations were batched

            # small subsequent update bypasses bulk path & supersedes cleanly
            small = PackageCollection([_pkg("solo", APT)])
            pt.show_packages(small)
            await pilot.pause()
            assert pt._table.row_count == 1
            assert pt._bulk_pending == []

    asyncio.run(scenario())


def _pkg(name, mgr, version="1.0"):
    return Package(name=name, manager=mgr, version=version)


def test_progressive_worker_flushes_without_blocking_call(tmp_path):
    async def scenario():
        app = TableHarness()
        async with app.run_test(size=(120, 30)):
            pt = app.pt
            pt.show_packages(_big_collection(1200))
            deadline = time.monotonic() + 5
            while pt._table.row_count < 1200 and time.monotonic() < deadline:
                await asyncio.sleep(0.02)               # worker drains alone
            assert pt._table.row_count == 1200

    asyncio.run(scenario())


# ------------------------------------------------------- perf soft-check --

def test_apply_filter_speed_on_5k_packages(tmp_path):
    async def scenario():
        app = TableHarness()
        async with app.run_test(size=(120, 30)):
            pt = app.pt
            big = PackageCollection([
                Package(name=f"pkg{i:05d}", manager=APT if i % 2 else FLATPAK)
                for i in range(5000)
            ])
            pt._last_collection = big
            started = time.monotonic()
            matched = InstalledController_match_helper(big, "00012")
            elapsed = time.monotonic() - started
            assert len(matched) > 0
            assert elapsed < 0.5                        # generous CI ceiling

    asyncio.run(scenario())


def InstalledController_match_helper(collection, query):
    from rmadd.controllers.installed_controller import InstalledController

    return InstalledController._match(list(collection), query, None)
