"""Search tab: live multi-manager search, enrichment, dynamic action bar."""

import asyncio
import time

from textual.widgets import Input, Static, Tab

from rmadd.controllers.base import Controller
from rmadd.models import PackageCollection, PackageManager, PackageStatus, supports
from rmadd.screens.widgets.package_table import PackageTable, apply_pane_floor


class SearchController(Controller):
    def __init__(self, ui):
        super().__init__(ui)
        self.managers: set[PackageManager] | None = None
        self.query: str = ""
        self._gen = 0

    @property
    def generation(self) -> int:
        """Current search generation (bumped per run and on cancel)."""
        return self._gen

    # ---------------------------------------------------------- status chip --

    def _set_chip(self, text: str):
        try:
            self.ui.query_one("#search-status-chip", Static).update(text)
        except Exception:
            pass

    def _chip_progress(self, gen: int, done: int, total: int, t0: float) -> str:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return f"gen:{gen} · {done}/{total} managers done · {elapsed_ms}ms"

    # ------------------------------------------------------------- search --

    async def run(self, query: str, managers=None):
        ui = self.ui
        if not ui.is_mounted:
            return
        result = ui.result("search")
        table = ui.query_one("#search-table", PackageTable)
        q = query.strip()
        self.query = q
        if not q:
            result.update("[yellow]Type a search term — results appear as you type[/yellow]")
            table.show_packages(PackageCollection([]))
            self._set_chip(f"gen:{self._gen} · idle")
            return
        self._gen += 1
        gen = self._gen
        if managers is None:
            manager_list = list(ui.ps.default_search_managers())
        else:
            manager_list = list(managers)
        total = len(manager_list)
        merged: list = []
        done = 0
        t0 = time.monotonic()
        self._set_chip(self._chip_progress(gen, 0, total, t0))
        result.update(f"[cyan]Searching... 0/{total}[/cyan]")

        async def run_one(mgr: PackageManager):
            nonlocal done
            try:
                coll = await asyncio.to_thread(ui.ps.search, q, mgr)
            except Exception:
                coll = PackageCollection([])
            if gen != self._gen:
                return
            done += 1
            merged.extend(list(coll))
            self._set_chip(self._chip_progress(gen, done, total, t0))
            if done < total:
                result.update(f"[cyan]Searching... {done}/{total}[/cyan]")
            self.render_results(table, PackageCollection(merged), q, result, incremental=True)

        await asyncio.gather(*[asyncio.create_task(run_one(m)) for m in manager_list])
        if gen == self._gen and ui.is_mounted:
            self.render_results(table, PackageCollection(merged), q, result)

    def cancel(self):
        """Logical cancel: orphan in-flight completions and clear the input.

        Underlying read-only subprocesses finish detached; their results are
        discarded via the generation bump.
        """
        self._gen += 1
        self.cancel_debounce()
        self.query = ""
        self._set_chip(f"gen:{self._gen} · idle")
        try:
            self.ui.query_one("#search-input", Input).value = ""
        except Exception:
            pass

    def render_results(self, table, collection, q, result, incremental=False):
        version_map = self.opt.version_map()
        for p in collection:
            if not p.version:
                p.version = version_map.get((p.name, p.manager), "")
            p.status = (
                PackageStatus.INSTALLED
                if self.opt.is_installed(p.name, p.manager)
                else PackageStatus.AVAILABLE
            )
        table.show_packages(collection)
        self.ui.move_cursor_first_row(table)
        self.update_actions()
        if collection.total == 0:
            result.update(f"[yellow]No results for '{q}'[/yellow]")
            return
        installed_count = sum(1 for p in collection if p.status == PackageStatus.INSTALLED)
        if incremental:
            result.update(
                f"[green]{collection.total} results so far...[/green][cyan] ({installed_count} ✓)[/cyan]"
            )
        else:
            result.update(
                f"[green]{collection.total} results[/green][cyan] — {installed_count} already installed (✓)[/cyan]"
            )

    # ----------------------------------------------------------- debounce --

    _LIVE_DEBOUNCE_SECONDS = 0.2

    def schedule_live(self, query: str):
        """Debounced live search; exclusive worker cancels superseded waits."""
        self.ui.run_worker_ex(
            self._delayed_search(query), group="search-live"
        )

    async def _delayed_search(self, query: str):
        try:
            await asyncio.sleep(self._LIVE_DEBOUNCE_SECONDS)
        except asyncio.CancelledError:
            return
        await self.run(query, self.managers)

    def cancel_debounce(self):
        """Cancel the pending debounced run and any in-flight fan-out."""
        self.ui.cancel_worker_group("search-live")
        self.ui.cancel_worker_group("search-run")

    def submitted(self, value: str):
        """Enter in the search box bypasses the debounce."""
        self.cancel_debounce()
        self.start_run(value)

    def start_run(self, query: str, managers=None):
        """Run a search as an exclusive worker (superseded runs cancel)."""
        self.ui.run_worker_ex(
            self.run(query, managers if managers is not None else self.managers),
            group="search-run",
        )

    def rerun_current(self):
        if self.query:
            self.start_run(self.query, self.managers)

    # ------------------------------------------------------------ tab strip --

    async def rebuild_tabs(self):
        ui = self.ui
        async with ui.rebuild_lock:
            tabs = ui.query_one("#search-filter-tabs")
            managers = [m for m in ui.ps.available_managers if supports(m, "search")]
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
            if tabs.active is None:
                tabs.active = "tab-all"

    def handle_tab(self, tab_id: str | None):
        if tab_id == "tab-all":
            self.managers = None
        else:
            self.managers = {PackageManager((tab_id or "").removeprefix("tab-"))}
        current = self.ui.query_one("#search-input", Input).value
        self.start_run(current)

    # -------------------------------------------------------- action bar --

    def update_actions(self):
        ui = self.ui
        name, mgr_str = ui.cursor("search")
        bar = ui.query_one("#search-action-bar")
        label = ui.query_one("#search-sel", Static)
        status = ui.query_one("#search-status", Static)
        install_btn = ui.query_one("#btn-search-install")
        remove_btn = ui.query_one("#btn-search-remove")
        update_btn = ui.query_one("#btn-search-update")
        if name and mgr_str:
            bar.display = True
            mgr = PackageManager(mgr_str)
            installed = self.opt.is_installed(name, mgr)
            busy = self.opt.pending_action(name, mgr) is not None
            label.update(f"[bold]{name}[/bold] ({mgr_str})")
            install_btn.display = not installed and supports(mgr, "install")
            remove_btn.display = installed and supports(mgr, "remove")
            update_btn.display = installed and supports(mgr, "update")
            install_btn.disabled = busy
            remove_btn.disabled = busy
            update_btn.disabled = busy
            status.update(
                "[bold green]✓ Already Installed[/bold green]"
                if installed
                else "[yellow]○ Available[/yellow]"
            )
        else:
            bar.display = False
        apply_pane_floor(ui.table_for("search"))
