"""Optimistic operation lifecycle: bus intake -> state mutation -> widgets.

Owns the OptimisticPackageState instance and translates its plain-value
deltas into widget updates. Every op path ends with a bus emit so the
Installed tab always settles or reverts (ARCHITECTURE.md §4 contract).
"""

import asyncio

from rmadd.controllers.base import Controller
from rmadd.controllers.optimistic_state import OptimisticPackageState
from rmadd.logging import get_logger
from rmadd.models import PackageManager
from rmadd.screens.install_progress_screen import InstallProgressScreen
from rmadd.screens.widgets.package_table import PackageTable
from rmadd.ui_keys import encode_key

logger = get_logger("operations")


def _pending_tables(mgr) -> tuple[str, ...]:
    """Tables that must render the optimistic state for a target."""
    if mgr == PackageManager.LOCAL:
        return ("installed-table", "local-table")
    return ("installed-table", "search-table")


class OperationsController(Controller):
    def __init__(self, ui):
        super().__init__(ui)
        self.state = OptimisticPackageState()
        self._rediscovering = False

    # ---------------------------------------------------------- op entry --

    def start(self, action: str, section: str, name: str, mgr):
        executor = None
        if section == "local":
            adapter = self.ui.local_bin.adapter
            executor = lambda n, m, on_output, cancel: adapter.remove(n, on_output, cancel)
        self.emit(action, name, mgr, phase="pending")
        self.ui.push_modal(
            InstallProgressScreen(
                self.ps,
                action,
                name,
                mgr,
                on_finish=self.ui.on_operation_finished,
                section=section,
                executor=executor,
            )
        )

    def emit(self, kind: str, name: str, mgr, phase: str = "confirmed"):
        self.bus.emit(kind, name, mgr, phase)

    def remove_instantly(self, section: str, name: str, mgr):
        """Zero-latency removal: state first, then every visible table."""
        self.state.remove_instantly(name, mgr)
        ui = self.ui
        for table_id in ("installed-table", "local-table", "search-table"):
            try:
                ui.query_one(f"#{table_id}", PackageTable).remove_package(name, mgr)
            except Exception:
                pass
        ui.installed.refresh_view()
        ui.stats.patch_from_state()
        ui.search.update_actions()
        ui.search.rerun_current()

    def _refresh_action_bars(self):
        """Re-evaluate every section's action bar (pending-aware disables)."""
        ui = self.ui
        ui.search.update_actions()
        ui.installed.update_actions()
        ui.local_bin.update_actions()

    # ------------------------------------------------------- bus intake --

    def on_bus_event(self, kind: str, name: str, mgr, phase: str = "confirmed"):
        if kind == "managers_changed":
            self.track(self.on_managers_changed())
            return
        if kind == self.ps.INSTALLED_REFRESH_EVENT:
            self.track(self.ui.installed.load())
            return
        if phase == "pending":
            self.apply_pending(kind, name, mgr)
        elif phase == "reverted":
            self.track(self.revert(kind, name, mgr))
        else:
            self.track(self.settle(kind, name, mgr))

    # --------------------------------------------------- pending phase --

    def apply_pending(self, action: str, name: str, mgr):
        override = self.state.register_pending(action, name, mgr)
        if action == "install":
            self.ui.installed.refresh_view()
            if override is not None:
                for table_id in _pending_tables(mgr):
                    self.paint_status(table_id, name, mgr, override)
        elif action == "remove":
            pass
        elif action == "update":
            if override is not None:
                for table_id in _pending_tables(mgr):
                    self.paint_status(table_id, name, mgr, override)
        self.ui.stats.patch_from_state()
        self._refresh_action_bars()

    # -------------------------------------------------- confirmed phase --

    async def settle(self, action: str, name: str, mgr):
        ui = self.ui
        if not ui.is_mounted:
            return
        self.state.settle_confirmed(action, name, mgr)
        self.clear_overrides(name, mgr)
        if action == "install":
            ui.installed.refresh_view()
            ui.track(ui.installed.rebuild_tabs())
            ui.track(self.rediscover_managers())
        elif action == "remove":
            for table_id in ("installed-table", "local-table", "search-table"):
                try:
                    ui.query_one(f"#{table_id}", PackageTable).remove_package(name, mgr)
                except Exception:
                    pass
            ui.installed.refresh_view()
            ui.track(ui.installed.rebuild_tabs())
        else:  # update
            ui.installed.refresh_view()
        self.ps.invalidate_counts()
        ui.stats.patch_from_state()
        ui.search.rerun_current()
        self._refresh_action_bars()

    # ---------------------------------------------------- reverted phase --

    async def revert(self, action: str, name: str, mgr):
        ui = self.ui
        if not ui.is_mounted:
            return
        directive = self.state.revert_pending(action, name, mgr)
        self.clear_overrides(name, mgr)
        if action == "install":
            for table_id in ("installed-table", "search-table"):
                try:
                    ui.query_one(f"#{table_id}", PackageTable).remove_package(name, mgr)
                except Exception:
                    pass
        elif action == "remove":
            if directive is not None and directive.is_local:
                ui.local_bin.render()
        else:  # update: statuses restored in state; view refresh below suffices
            pass
        ui.installed.refresh_view()
        ui.track(ui.installed.rebuild_tabs())
        ui.stats.patch_from_state()
        ui.search.rerun_current()
        self._refresh_action_bars()

    # -------------------------------------------------------- discovery --

    async def rediscover_managers(self):
        ui = self.ui
        if not ui.is_mounted or self._rediscovering:
            return
        self._rediscovering = True
        try:
            from rmadd.package_managers.base import discover_managers

            found = await asyncio.to_thread(discover_managers)
            added = False
            for mgr, adapter in found:
                if ui.ps.add_source(mgr, adapter):
                    added = True
            if added:
                self.emit("managers_changed", "", None)
        finally:
            self._rediscovering = False

    async def on_managers_changed(self):
        ui = self.ui
        if not ui.is_mounted:
            return
        await ui.search.rebuild_tabs()
        await ui.installed.load(force=True)
        await ui.installed.rebuild_tabs()
        ui.track(ui.stats.load())
        if ui.search.query:
            ui.track(ui.search.run(ui.search.query, ui.search.managers))

    # ------------------------------------------------- row glyph helpers --

    def paint_status(self, table_id: str, name: str, mgr, status):
        try:
            key = encode_key(name, mgr)
            self.ui.query_one(f"#{table_id}", PackageTable).set_row_status(key, status)
        except Exception:
            pass

    def clear_overrides(self, name: str, mgr):
        key = encode_key(name, mgr)
        for table_id in _pending_tables(mgr):
            try:
                self.ui.query_one(f"#{table_id}", PackageTable).clear_row_status(key)
            except Exception:
                pass
