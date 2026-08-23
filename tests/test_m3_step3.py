"""M3 Step 3 tests: responsive column tiers (debounced, cursor-locked,
round-trip safe) and the config-gated removal confirmation modal."""

import asyncio

import pytest

pytest.importorskip("textual")

from textual.app import App
from textual.widgets import Static

from rmadd.config import Config
from rmadd.hardware import HardwareMonitorService
from rmadd.models import Package, PackageCollection, PackageManager
from rmadd.package_managers.service import PackageManagerService
from rmadd.screens.confirm_remove import ConfirmRemoveScreen
from rmadd.screens.install_progress_screen import InstallProgressScreen
from rmadd.screens.widgets.tools_table import ToolsTable
from rmadd.system_info import SystemInfoService
from rmadd.tui import RmaddTuiApp
from tests.test_m3_step1 import TableHarness
from tests.test_store_screen_smoke import (
    FakeHardwareDS,
    FakeSource,
    FakeSystemDS,
    _label,
    _wait_until,
)

APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK


def _pkg(name, mgr, version="1.0"):
    return Package(name=name, manager=mgr, version=version)


def _col():
    return PackageCollection([
        _pkg("git", APT),
        _pkg("htop", APT),
        _pkg("spotify", FLATPAK),
    ])


async def _resize(pilot, w, h):
    result = pilot.resize_terminal(w, h)
    if hasattr(result, "__await__"):
        await result
    await asyncio.sleep(0.25)          # flush the 0.12s debounce timer


def _column_names(pt):
    return [str(c.label) for c in pt._table.columns.values()]


# ------------------------------------------------------ responsive pkg ----

def test_responsive_column_tiers_and_roundtrip(tmp_path):
    async def scenario():
        app = TableHarness()
        async with app.run_test(size=(120, 30)) as pilot:
            pt = app.pt
            pt.show_packages(_col())
            await pilot.pause()
            assert len(pt._table.columns) == 5
            dt = pt._table
            dt.cursor_coordinate = Coordinate(dt.get_row_index("spotify|flatpak"), 0)
            await pilot.pause()

            await _resize(pilot, 75, 30)               # drop Arch (>=72)
            assert _column_names(pt) == ["", "Name", "Version", "Manager"]
            assert {p.name for p in pt._last_collection} == {"git", "htop", "spotify"}
            assert _cursor_key(pt._table) == "spotify|flatpak"

            await _resize(pilot, 48, 30)               # narrowest tier (<56)
            assert _column_names(pt) == ["", "Name"]
            assert _cursor_key(pt._table) == "spotify|flatpak"

            await _resize(pilot, 120, 30)              # restore everything
            assert len(pt._table.columns) == 5
            assert _cursor_key(pt._table) == "spotify|flatpak"
            row = pt._table.get_row_at(pt._table.get_row_index("spotify|flatpak"))
            assert str(row[2]) == "1.0"                # version survived trip

    asyncio.run(scenario())


from textual.coordinate import Coordinate  # noqa: E402


def _cursor_key(dt):
    try:
        coord = dt.cursor_coordinate
        if coord is None or coord.row >= dt.row_count:
            return None
        return dt.coordinate_to_cell_key(coord).row_key.value
    except Exception:
        return None


def test_resize_debounce_lands_on_final_width(tmp_path):
    async def scenario():
        app = TableHarness()
        async with app.run_test(size=(120, 30)) as pilot:
            pt = app.pt
            pt.show_packages(_col())
            await pilot.pause()
            pilot.resize_terminal(110, 30)             # inside debounce window
            pilot.resize_terminal(75, 30)
            await _resize(pilot, 75, 30)               # second call flushes
            assert len(pt._table.columns) == 4         # final width (75) wins

    asyncio.run(scenario())


# ------------------------------------------------------- tools response ---

class ToolsHarness(App):
    def __init__(self):
        super().__init__()
        self.tt = ToolsTable(id="tt")

    def compose(self):
        yield self.tt



def test_tools_table_hides_purpose_when_narrow(tmp_path):
    async def scenario():
        from rmadd.tools import InstallerTool

        tool = InstallerTool("npm", "NPM", "npm", "Node.js package manager")
        app = ToolsHarness()
        async with app.run_test(size=(120, 30)) as pilot:
            tt = app.tt
            tt.show_tools([(tool, True)])
            await pilot.pause()
            assert len(tt._table.columns) == 4
            await _resize(pilot, 60, 30)
            assert _column_names(tt) == ["", "Tool", "Status"]
            assert str(tt._table.get_row_at(0)[1]) == "NPM"
            await _resize(pilot, 120, 30)
            assert len(tt._table.columns) == 4

    asyncio.run(scenario())


# -------------------------------------------------- confirmation gating ---

def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    svc = PackageManagerService({
        APT: FakeSource(APT, ["git", "htop"]),
        FLATPAK: FakeSource(FLATPAK, ["spotify"]),
    })
    return RmaddTuiApp(
        SystemInfoService(FakeSystemDS()),
        svc,
        HardwareMonitorService(FakeHardwareDS()),
    )


def test_confirm_removal_default_off(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg = Config(str(cfg_file))
    assert cfg.confirm_removal is False
    cfg.confirm_removal = True
    cfg.save()
    assert Config(str(cfg_file)).confirm_removal is True
    cfg2 = Config(str(tmp_path / "missing.json"))
    cfg2.confirm_removal = "yes"                      # truthy coercion
    assert cfg2.confirm_removal is True


def test_gate_off_opens_progress_immediately(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")
            await pilot.pause(0.2)
            await pilot.press("r")
            assert await _wait_until(
                lambda: isinstance(app.screen, InstallProgressScreen)
            )

    asyncio.run(scenario())


def test_gate_on_requires_confirmation_before_removal(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            store.confirm_removal = True               # opt-in flip
            await pilot.press("f3")
            await pilot.pause(0.2)

            await pilot.press("r")                     # target: git
            assert isinstance(app.screen, ConfirmRemoveScreen)
            assert "git" in _label(app.screen.query_one("#confirm-title", Static))

            await pilot.press("n")                     # keep package
            await pilot.pause(0.2)
            assert not isinstance(app.screen, ConfirmRemoveScreen)
            assert "git" in {p.name for p in store.ops.state.installed_packages()}
            assert store.ops.state.pending_action("git", APT) is None
            assert "cancelled" in _label(store.result("installed")).lower()

            await pilot.press("r")                     # arm again...
            assert isinstance(app.screen, ConfirmRemoveScreen)
            await pilot.press("y")                     # ...and confirm
            assert await _wait_until(
                lambda: isinstance(app.screen, InstallProgressScreen)
            )
            assert await _wait_until(
                lambda: "git" not in {p.name for p in store.ops.state.installed_packages()}
            )
            assert "git" not in {
                str(store.query_one("#installed-table")._table.get_row_at(r)[1])
                for r in range(store.query_one("#installed-table")._table.row_count)
            }

    asyncio.run(scenario())


def test_detail_screen_respects_gate(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            store.confirm_removal = True
            await pilot.press("f3")
            await pilot.pause(0.2)
            await pilot.press("enter")                 # open detail for cursor row
            await pilot.pause(0.3)
            detail = app.screen
            await detail._run_action("remove")
            await pilot.pause(0.2)
            assert isinstance(app.screen, ConfirmRemoveScreen)
            await pilot.press("escape")                # keep
            await pilot.pause(0.2)
            assert not isinstance(app.screen, ConfirmRemoveScreen)
            assert "git" in {p.name for p in store.ops.state.installed_packages()}
            assert store.ops.state.pending_action("git", APT) is None

    asyncio.run(scenario())
