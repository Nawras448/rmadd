"""End-to-end smoke tests for the refactored StoreScreen composition root.

Exercises the full wiring (screen -> controllers -> state -> bus -> widgets)
with Textual's headless pilot: mount loads, live search rendering, an
optimistic remove CONFIRMED cycle and a FAILED-removal REVERT restore.
"""

import asyncio

import pytest

pytest.importorskip("textual")

from rmadd.hardware import HardwareMonitorService
from rmadd.models import (
    CpuInfo,
    Distribution,
    MemoryInfo,
    Package,
    PackageManager,
    PackageStatus,
)
from rmadd.package_managers.service import PackageManagerService
from rmadd.system_info import SystemInfoService
from rmadd.tui import RmaddTuiApp

APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK


@pytest.fixture(autouse=True)
def _isolate_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))


class FakeSource:
    """Duck-typed adapter satisfying PackageManagerService + LocalAdapter use."""

    def __init__(self, mgr, names, remove_ok=True):
        self._mgr = mgr
        self._names = list(names)
        self.remove_ok = remove_ok

    def _pkg(self, name):
        return Package(name=name, manager=self._mgr, version="1.0", summary=f"{name} tool")

    def list_installed(self):
        return [self._pkg(n) for n in self._names]

    def count(self):
        return len(self._names)

    def search(self, query):
        ql = query.lower()
        return [self._pkg(n) for n in self._names if ql in n.lower()]

    def get_info(self, name):
        return self._pkg(name) if name in self._names else None

    def get_status(self, name):
        return PackageStatus.INSTALLED if name in self._names else PackageStatus.AVAILABLE

    def install(self, name, on_output=None, cancel_event=None, **kw):
        return True

    def remove(self, name, on_output=None, cancel_event=None, **kw):
        if on_output is not None:
            on_output("fake removal output\n")
        return self.remove_ok

    def update(self, name, on_output=None, cancel_event=None, **kw):
        return True

    def update_all(self, on_output=None, cancel_event=None, **kw):
        return True

    def list_repos(self):
        return []


class FakeSystemDS:
    def get_hostname(self):
        return "smoke-host"

    def get_os_release(self):
        return "Smoke Linux"

    def get_kernel(self):
        return "6.0.0-smoke"

    def get_architecture(self):
        return "x86_64"

    def get_hostnamectl(self):
        return ""

    def get_uptime(self):
        return "1m"

    def get_distribution(self):
        return Distribution()


class FakeHardwareDS:
    def get_cpu_info(self):
        return CpuInfo()

    def get_memory_info(self):
        return MemoryInfo()

    def get_disk_info(self):
        return []

    def get_gpu_info(self):
        return None

    def get_network_info(self):
        return []


def make_app(remove_ok=True):
    sources = {
        APT: FakeSource(APT, ["git", "htop"], remove_ok=remove_ok),
        FLATPAK: FakeSource(FLATPAK, ["spotify"]),
    }
    system = SystemInfoService(FakeSystemDS())
    hardware = HardwareMonitorService(FakeHardwareDS())
    return RmaddTuiApp(system, PackageManagerService(sources), hardware)


async def _wait_until(predicate, timeout=8.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return False


def _label(widget) -> str:
    renderable = getattr(widget, "renderable", None)
    if renderable is None:
        renderable = widget.render()
    return str(renderable)


def _visible_names(store, table_id="#installed-table") -> set:
    table = store.query_one(table_id)
    return {
        str(table._table.get_row_at(r)[1]) for r in range(table._table.row_count)
    }


def test_mount_hydrates_state_and_counts():
    async def scenario():
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert store.query_one("#store-tabs") is not None
            assert await _wait_until(lambda: store.installed.loaded)
            names = {p.name for p in store.ops.state.installed_packages()}
            assert names == {"git", "htop", "spotify"}
            assert store.ops.state.counts_by_manager() == {"apt": 2, "flatpak": 1}
            await pilot.pause(0.2)

    asyncio.run(scenario())


def test_search_renders_and_action_bar_reflects_installed_state():
    async def scenario():
        app = make_app()
        async with app.run_test(size=(120, 40)) as _pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await store.search.run("htop")
            table = store.query_one("#search-table")
            assert table._table.row_count == 1
            assert str(table._table.get_row_at(0)[1]) == "htop"
            assert store.query_one("#btn-search-remove").display is True
            assert store.query_one("#btn-search-install").display is False
            assert "Already Installed" in _label(store.query_one("#search-status"))

    asyncio.run(scenario())


def test_optimistic_remove_confirmed_prunes_everywhere():
    async def scenario():
        app = make_app()
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")           # Installed tab
            await pilot.pause(0.2)
            await pilot.press("r")            # quick_remove on cursor row (git)
            ok = await _wait_until(
                lambda: store.ops.state.pending_action("git", APT) is None
                and "git" not in {p.name for p in store.ops.state.installed_packages()}
            )
            assert ok, "remove did not settle"
            assert store.ops.state.counts_by_manager() == {"apt": 1, "flatpak": 1}
            assert "git" not in _visible_names(store)
            assert "Remove succeeded" in _label(store.result("installed"))

    asyncio.run(scenario())


def test_failed_remove_reverts_and_restores_row():
    async def scenario():
        app = make_app(remove_ok=False)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")
            await pilot.pause(0.2)
            await pilot.press("r")            # remove 'git' -> adapter fails
            ok = await _wait_until(
                lambda: store.ops.state.pending_action("git", APT) is None
                and "git" in {p.name for p in store.ops.state.installed_packages()}
            )
            assert ok, "failed removal did not revert"
            assert "git" in _visible_names(store)   # row restored verbatim
            assert store.ops.state.counts_by_manager()["apt"] == 2

    asyncio.run(scenario())
