"""M3 Step 1 tests: key-aware reconciliation with cursor continuity,
pending dim/glyph visuals (incl. LOCAL), and pending action guards."""

import asyncio
import time

import pytest

pytest.importorskip("textual")

from rich.text import Text
from textual.app import App
from textual.coordinate import Coordinate

from rmadd.controllers.operations_controller import _pending_tables
from rmadd.models import Package, PackageCollection, PackageManager
from rmadd.screens.widgets.package_table import PackageTable
from rmadd.ui_keys import encode_key

APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK
LOCAL = PackageManager.LOCAL


def _pkg(name, mgr, version="1.0"):
    return Package(name=name, manager=mgr, version=version)


# ------------------------------------------------- table harness (real DT) --

class TableHarness(App):
    def __init__(self):
        super().__init__()
        self.pt = PackageTable(id="pt")

    def compose(self):
        yield self.pt


def _rows(pt):
    return list(pt._row_keys)


def test_reconcile_scenarios():
    async def scenario():
        app = TableHarness()
        async with app.run_test(size=(100, 30)) as pilot:
            pt = app.pt
            await pilot.pause()
            A, B, C = encode_key("a", APT), encode_key("b", APT), encode_key("c", FLATPAK)
            col = lambda *names: PackageCollection(
                [_pkg(n, m) for n, m in names]
            )

            pt.show_packages(col(("a", APT), ("b", APT)))
            await pilot.pause()
            assert _rows(pt) == [A, B]
            removals = []
            orig_remove = pt._table.remove_row

            def counting_remove(key):
                removals.append(str(key))
                return orig_remove(key)

            pt._table.remove_row = counting_remove

            # append-only: zero churn on survivors
            pt.show_packages(col(("a", APT), ("b", APT), ("c", FLATPAK)))
            assert _rows(pt) == [A, B, C] and removals == []

            # middle trim: B removed, A/C untouched
            pt.show_packages(col(("a", APT), ("c", FLATPAK)))
            assert _rows(pt) == [A, C] and removals == [B]

            # canonical sorting dominates: reversed input changes nothing
            removals.clear()
            pt.show_packages(col(("c", FLATPAK), ("a", APT)))
            assert _rows(pt) == [A, C] and removals == []

            # pure content update: same keys, no removals
            fresh = PackageCollection([_pkg("c", FLATPAK, "9.9"), _pkg("a", APT, "2.0")])
            pt.show_packages(fresh)
            assert _rows(pt) == [A, C] and removals == []
            assert str(pt._table.get_row_at(1)[2]) == "9.9"

            # insertion shifts a survivor: new tier lands between them;
            # the shifted key is re-added, the untouched prefix stays put.
            NPM = PackageManager.NPM
            Z = encode_key("z", NPM)
            F = encode_key("f", FLATPAK)
            pt.show_packages(col(("a", APT), ("z", NPM)))
            assert _rows(pt) == [A, Z]
            removals.clear()
            pt.show_packages(col(("a", APT), ("f", FLATPAK), ("z", NPM)))
            assert _rows(pt) == [A, F, Z]
            assert removals == [Z]                       # shifted survivor rebuilt

    asyncio.run(scenario())


def test_pending_tables_mapping():
    assert _pending_tables(LOCAL) == ("installed-table", "local-table")
    assert _pending_tables(APT) == ("installed-table", "search-table")


# ------------------------------------------------ pilot: cursor stability --

from rmadd.hardware import HardwareMonitorService  # noqa: E402
from rmadd.package_managers.service import PackageManagerService  # noqa: E402
from rmadd.screens.install_progress_screen import InstallProgressScreen  # noqa: E402
from rmadd.system_info import SystemInfoService  # noqa: E402
from rmadd.tui import RmaddTuiApp  # noqa: E402
from tests.test_store_screen_smoke import (  # noqa: E402
    FakeHardwareDS,
    FakeSource,
    FakeSystemDS,
    _label,
    _wait_until,
)


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


def _cursor_key(dt):
    try:
        coord = dt.cursor_coordinate
        if coord is None or coord.row >= dt.row_count:
            return None
        return dt.coordinate_to_cell_key(coord).row_key.value
    except Exception:
        return None


def test_pilot_cursor_locked_across_refresh(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            dt = store.query_one("#installed-table")._table
            spotify_idx = dt.get_row_index("spotify|flatpak")
            dt.cursor_coordinate = Coordinate(spotify_idx, 0)
            await pilot.pause()

            store.track(store.installed.load())          # background-style reload
            assert await _wait_until(lambda: not store.installed.busy)
            await pilot.pause(0.2)
            assert _cursor_key(dt) == "spotify|flatpak"

    asyncio.run(scenario())


def test_pilot_cursor_nearest_fallback_after_target_removed(tmp_path, monkeypatch):
    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            dt = store.query_one("#installed-table")._table
            dt.cursor_coordinate = Coordinate(0, 0)      # 'git'
            await pilot.pause()

            store.ops.remove_instantly("installed", "git", APT)
            app.state_bus.emit("remove", "git", APT, "confirmed")
            assert await _wait_until(
                lambda: "git" not in {p.name for p in store.ops.state.installed_packages()}
            )
            await pilot.pause(0.2)
            assert dt.row_count == 2
            assert _cursor_key(dt) == "htop|apt"         # clamped, never lost

    asyncio.run(scenario())


# ------------------------------------------- pending visuals + guards -----

from tests.test_op_feedback import SlowAuthFakeSource  # noqa: E402


class SlowUpdateFakeSource(SlowAuthFakeSource):
    """update() emits an auth prompt then fails slowly (row stays visible)."""

    def update(self, name, on_output=None, cancel_event=None, **kw):
        if on_output is not None:
            on_output("Password for tester: \n")
        time.sleep(0.8)
        return False


def _build_slow_update_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    svc = PackageManagerService({
        APT: SlowUpdateFakeSource(APT, ["git", "htop"]),
        FLATPAK: SlowAuthFakeSource(FLATPAK, ["spotify"]),
    })
    return RmaddTuiApp(
        SystemInfoService(FakeSystemDS()),
        svc,
        HardwareMonitorService(FakeHardwareDS()),
    )


def test_pilot_pending_glyph_dim_and_button_guards(tmp_path, monkeypatch):
    async def scenario():
        app = _build_slow_update_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            await pilot.press("f3")
            assert await _wait_until(
                lambda: "Loaded" in _label(store.result("installed"))
            )

            # ---- REMOVE flow: row vanishes instantly; buttons guard ----
            dt = store.query_one("#installed-table")._table
            dt.cursor_coordinate = Coordinate(dt.get_row_index(encode_key("git", APT)), 0)
            await pilot.press("r")
            assert await _wait_until(
                lambda: isinstance(app.screen, InstallProgressScreen)
            )
            pt = store.query_one("#installed-table", PackageTable)
            git_key = encode_key("git", APT)
            assert git_key not in pt._row_keys           # zero-latency removal
            assert store.query_one("#btn-installed-remove").disabled is False  # cursor fell to htop

            assert await _wait_until(
                lambda: store.ops.state.pending_action("git", APT) is None
                and "git" in {p.name for p in store.ops.state.installed_packages()}
            )
            await pilot.pause(0.3)
            assert git_key in pt._row_keys               # reverted verbatim
            # let the old modal finish its dismiss timer before the next op
            assert await _wait_until(
                lambda: not isinstance(app.screen, InstallProgressScreen)
            )
            assert await _wait_until(
                lambda: all(
                    store.ops.state.pending_action(n, m) is None
                    for n, m in [("git", APT), ("htop", APT), ("spotify", FLATPAK)]
                )
            )
            await pilot.pause(0.4)

            # ---- UPDATE flow: row stays, glyph ▲ + dim + guards --------
            htop_key = encode_key("htop", APT)
            htop_idx = pt._table.get_row_index(htop_key)
            dt.cursor_coordinate = Coordinate(htop_idx, 0)
            await pilot.pause(0.3)
            assert _cursor_key(dt) == htop_key, f"cursor on {_cursor_key(dt)!r}"
            await pilot.press("u")
            assert await _wait_until(
                lambda: isinstance(app.screen, InstallProgressScreen)
            )

            def htop_state():
                cells = pt._table.get_row_at(pt._table.get_row_index(encode_key("htop", APT)))
                dims = [isinstance(c, Text) and "dim" in str(c.style) for c in cells[1:]]
                return str(cells[0]), all(dims)

            _diag_done = {"v": False}

            def glyph_settled():
                try:
                    return htop_state()[0] == "\u25b2"
                except Exception:
                    return False

            try:
                _modal = app.screen
                _title = str(_modal.query_one("#progress-title").render()) \
                    if isinstance(_modal, InstallProgressScreen) else type(_modal).__name__
            except Exception as e:
                _title = f"<err {e!r}>"
            _snap = {
                "pend": store.ops.state.pending_action("htop", APT),
                "git_pend": store.ops.state.pending_action("git", APT),
                "status": pt._row_status.get(htop_key),
                "glyph_now": (htop_state()[0] if pt._table.row_count else "<empty>"),
                "keys": list(pt._row_keys),
                "title": _title,
                "label": _label(store.result("installed")),
            }
            assert await _wait_until(glyph_settled), f"UPDATING glyph never appeared: {_snap!r}"
            _, dimmed = htop_state()
            assert dimmed
            assert store.query_one("#btn-installed-update").disabled is True

            # screen-level double-fire guard on the pending (persisted) target
            await store._do_pkg_action("update", "installed")
            assert "already running" in _label(store.result("installed"))

            assert await _wait_until(
                lambda: store.ops.state.pending_action("htop", APT) is None
            )
            await pilot.pause(0.3)
            glyph, dimmed = htop_state()
            assert glyph == "\u2713" and not dimmed      # base restored verbatim
            assert store.query_one("#btn-installed-update").disabled is False

    asyncio.run(scenario())
