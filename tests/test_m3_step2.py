"""M3 Step 2 tests: search status chip (gen/k/M + ms), Esc cancel,
focus capture & restoration around modals, and the '?' help overlay."""

import asyncio
import time

import pytest

pytest.importorskip("textual")

from textual.widgets import Button, Input, Static

from rmadd.controllers.operations_controller import OperationsController  # noqa: F401
from rmadd.hardware import HardwareMonitorService
from rmadd.models import PackageManager
from rmadd.package_managers.service import PackageManagerService
from rmadd.screens.help_overlay import HelpOverlay
from rmadd.screens.install_progress_screen import InstallProgressScreen
from rmadd.system_info import SystemInfoService
from rmadd.tui import RmaddTuiApp
from tests.test_op_feedback import SlowAuthFakeSource
from tests.test_store_screen_smoke import (
    FakeHardwareDS,
    FakeSource,
    FakeSystemDS,
    _label,
    _wait_until,
)

APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK


class StaggeredSearchSource(FakeSource):
    """search() sleeps per-manager so chip intermediates are observable."""

    def __init__(self, mgr, names, delay=0.0):
        super().__init__(mgr, names)
        self._delay = delay

    def search(self, query):
        if self._delay:
            time.sleep(self._delay)
        return super().search(query)


def _build(tmp_path, monkeypatch, apt=None, flatpak=None):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    svc = PackageManagerService({
        APT: apt or FakeSource(APT, ["git", "htop"]),
        FLATPAK: flatpak or FakeSource(FLATPAK, ["spotify"]),
    })
    return RmaddTuiApp(
        SystemInfoService(FakeSystemDS()),
        svc,
        HardwareMonitorService(FakeHardwareDS()),
    )


def _chip(store) -> str:
    return _label(store.query_one("#search-status-chip", Static))


# ------------------------------------------------------------ status chip --

def test_chip_shows_generation_progress_and_elapsed_ms(tmp_path, monkeypatch):
    async def scenario():
        app = _build(
            tmp_path, monkeypatch,
            apt=StaggeredSearchSource(APT, ["git", "htop"], delay=0.02),
            flatpak=StaggeredSearchSource(FLATPAK, ["spotify"], delay=0.45),
        )
        async with app.run_test(size=(120, 40)) as _pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)

            task = asyncio.create_task(store.search.run("vim"))
            seen: list[str] = []
            while not task.done():
                seen.append(_chip(store))
                await asyncio.sleep(0.03)
            await task
            seen.append(_chip(store))

            assert any("1/2 managers" in s for s in seen), seen[:10]
            final = seen[-1]
            assert final.startswith("gen:")
            assert "2/2 managers done" in final
            assert final.endswith("ms")

    asyncio.run(scenario())


def test_chip_idle_on_empty_query_and_gen_stable(tmp_path, monkeypatch):
    async def scenario():
        app = _build(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as _pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            gen_before = store.search.generation
            await store.search.run("")
            assert "idle" in _chip(store)
            assert store.search.generation == gen_before  # empty runs don't bump

    asyncio.run(scenario())


# ------------------------------------------------------------- esc cancel --

def test_escape_cancels_search_and_clears_input(tmp_path, monkeypatch):
    async def scenario():
        app = _build(
            tmp_path, monkeypatch,
            flatpak=StaggeredSearchSource(FLATPAK, ["spotify"], delay=0.6),
        )
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            inp = store.query_one("#search-input", Input)
            gen_before = store.search.generation

            inp.focus()
            inp.value = "vim"                     # arms the debounced search
            await pilot.pause(0.05)
            await pilot.press("escape")           # logical cancel

            assert inp.value == ""
            assert store.search.generation > gen_before
            await pilot.pause(0.4)                # flush stray debounce timers
            assert "idle" in _chip(store)
            assert store.query_one("#search-table")._table.row_count == 0

    asyncio.run(scenario())


# ------------------------------------------- modal focus & restoration -----

def test_progress_modal_focuses_cancel_button(tmp_path, monkeypatch):
    async def scenario():
        app = _build(tmp_path, monkeypatch, apt=SlowAuthFakeSource(APT, ["git"]))
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")
            await pilot.pause(0.2)
            await pilot.press("r")                 # slow failing removal
            assert await _wait_until(
                lambda: isinstance(app.screen, InstallProgressScreen)
            )
            cancel_btn = app.screen.query_one("#btn-progress-cancel", Button)
            for _ in range(20):
                if app.focused is cancel_btn:
                    break
                await asyncio.sleep(0.02)
            assert app.focused is cancel_btn

    asyncio.run(scenario())


def test_focus_restored_after_modal_dismissal(tmp_path, monkeypatch):
    async def scenario():
        app = _build(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")
            await pilot.pause(0.2)
            dt = store.query_one("#installed-table")._table
            dt.focus()
            await pilot.pause(0.1)
            await pilot.press("r")                 # instant success fake
            assert await _wait_until(
                lambda: isinstance(app.screen, InstallProgressScreen)
            )
            assert await _wait_until(
                lambda: not isinstance(app.screen, InstallProgressScreen)
            )
            await pilot.pause(0.3)
            assert app.focused is dt

    asyncio.run(scenario())


# --------------------------------------------------------- help overlay ----

def test_question_mark_opens_help_overlay_and_restores_focus(tmp_path, monkeypatch):
    async def scenario():
        app = _build(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")
            await pilot.pause(0.2)
            dt = store.query_one("#installed-table")._table
            dt.focus()
            await pilot.pause(0.1)

            await pilot.press("question_mark")
            assert isinstance(app.screen, HelpOverlay)
            body = _label(app.screen.query_one("#help-body", Static))
            assert "Quit" in body
            assert "Force refresh" in body

            await pilot.press("escape")
            await pilot.pause(0.2)
            assert not isinstance(app.screen, HelpOverlay)
            assert app.focused is dt               # restored via push_modal

    asyncio.run(scenario())
