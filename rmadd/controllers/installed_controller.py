"""Installed Apps tab: load, filter, per-manager tab strip, action bar."""

import asyncio
import time

from textual.widgets import Input, Static, Tab, Tabs

from rmadd.controllers.base import Controller
from rmadd.logging import get_logger
from rmadd.models import PackageCollection, PackageManager
from rmadd.screens.widgets.package_table import PackageTable, apply_pane_floor

logger = get_logger("store_screen")


class InstalledController(Controller):
    def __init__(self, ui):
        super().__init__(ui)
        self.managers_filter: set | None = None
        self.busy = False
        self.loaded = False
        self.loaded_at = 0.0
        self._latest_filter_query = ""

    # ------------------------------------------------------------- loading --

    async def load(self, force: bool = False):
        ui = self.ui
        if not ui.is_mounted or self.busy:
            return
        self.busy = True
        try:
            result = ui.result("installed")
            table = ui.query_one("#installed-table", PackageTable)
            if not self.loaded:
                result.update("[yellow]Loading installed packages…[/yellow]")
            try:
                pkgs = await asyncio.to_thread(ui.ps.list_installed)
                if not ui.is_mounted:
                    return
                ui.optimistic.hydrate_installed(list(pkgs))
                self.loaded = True
                self.loaded_at = time.monotonic()
                self.show(PackageCollection(ui.opt.installed_packages()))
                if not force:
                    result.update(f"[green]Loaded {pkgs.total} installed packages[/green]")
                await self.rebuild_tabs()
                if ui.active_section == "installed":
                    table.focus_table()
                if ui.search.query:
                    ui.track(ui.search.run(ui.search.query, ui.search.managers))
            except Exception as e:
                logger.exception("list_installed failed")
                if ui.is_mounted:
                    result.update(f"[bold red]Error loading packages: {e}[/bold red]")
        finally:
            self.busy = False

    def should_reload(self) -> bool:
        """Pane-activation policy: first visit or stale beyond 15s."""
        return not self.loaded or time.monotonic() - self.loaded_at > 15

    # ------------------------------------------------------------- render --

    def show(self, collection: PackageCollection):
        if self.managers_filter:
            collection = collection.by_managers(self.managers_filter)
        table = self.ui.query_one("#installed-table", PackageTable)
        # Cursor continuity is handled inside show_packages (key match,
        # nearest-index fallback); no blanket snap-to-top here.
        table.show_packages(collection)
        self.update_actions()

    def apply_filter(self, query: str):
        collection = self._match(
            self.ui.opt.installed_packages(), query, self.managers_filter
        )
        self.show(collection)

    def refresh_view(self):
        query = self.ui.query_one("#installed-input", Input).value
        self.apply_filter(query)

    _FILTER_DEBOUNCE_SECONDS = 0.15
    _THREAD_FILTER_MIN_ROWS = 2000

    def schedule_filter(self, query: str):
        """Debounced filter: exclusive worker => only the final keystroke runs."""
        self._latest_filter_query = query
        self.ui.run_worker_ex(
            self._filter_pipeline(query), group="installed-filter"
        )

    async def _filter_pipeline(self, query: str):
        try:
            await asyncio.sleep(self._FILTER_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return
        if not self.ui.is_mounted:
            return
        packages = self.ui.opt.installed_packages()
        if len(packages) >= self._THREAD_FILTER_MIN_ROWS:
            # Heavy dataset: match off-loop, apply back on the UI thread.
            result = await asyncio.to_thread(
                self._match, packages, query, self.managers_filter
            )
            if query != self._latest_filter_query or not self.ui.is_mounted:
                return
            self.show(result)
        else:
            self.apply_filter(query)

    @staticmethod
    def _match(packages, query: str, managers_filter):
        """Pure in-memory matcher (never touches package managers)."""
        ql = query.strip().lower()
        out = []
        for p in packages:
            if managers_filter and p.manager not in managers_filter:
                continue
            if ql and ql not in p.name.lower() and ql not in (p.summary or "").lower():
                continue
            out.append(p)
        return PackageCollection(out)

    def cancel_filter(self):
        self._latest_filter_query = ""
        self.ui.cancel_worker_group("installed-filter")

    # ------------------------------------------------------------ tab strip --

    async def rebuild_tabs(self):
        ui = self.ui
        async with ui.rebuild_lock:
            tabs = ui.query_one("#installed-filter-tabs", Tabs)
            managers = [
                m
                for m in ui.ps.available_managers
                if any(p.manager == m for p in ui.opt.installed_packages())
            ]
            current = {
                tab.id
                for tab in tabs.query("#tabs-list > Tab").results(Tab)
                if tab.id and tab.id != "tab-all"
            }
            wanted = {f"tab-{m.value}" for m in managers}
            for tab_id in current - wanted:
                await tabs.remove_tab(tab_id)
            for m in managers:
                if f"tab-{m.value}" not in current:
                    await tabs.add_tab(Tab(m.value.upper(), id=f"tab-{m.value}"))
            active_id = tabs.active or "tab-all"
            if active_id == "tab-all":
                self.managers_filter = None
            else:
                self.managers_filter = {PackageManager(active_id.removeprefix("tab-"))}
            self.apply_filter(ui.query_one("#installed-input", Input).value)

    def handle_tab_activated(self, tab_id: str | None):
        if tab_id == "tab-all":
            self.managers_filter = None
        else:
            self.managers_filter = {PackageManager((tab_id or "").removeprefix("tab-"))}
        self.apply_filter(self.ui.query_one("#installed-input", Input).value)

    # -------------------------------------------------------- action bar --

    def update_actions(self):
        ui = self.ui
        name, mgr_str = ui.cursor("installed")
        bar = ui.query_one("#installed-action-bar")
        label = ui.query_one("#installed-sel", Static)
        if name and mgr_str:
            bar.display = True
            label.update(f"[bold]{name}[/bold] ({mgr_str})")
            busy = ui.opt.pending_action(name, PackageManager(mgr_str)) is not None
            for btn_id in ("#btn-installed-remove", "#btn-installed-update"):
                try:
                    ui.query_one(btn_id).disabled = busy
                except Exception:
                    pass
        else:
            bar.display = False
        apply_pane_floor(ui.table_for("installed"))
