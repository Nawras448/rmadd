"""Local Binaries tab: opt-in PATH scanner and physical deletion view."""

import asyncio

from textual.widgets import Static

from rmadd.controllers.base import Controller
from rmadd.models import PackageCollection
from rmadd.screens.widgets.package_table import PackageTable, apply_pane_floor


class LocalBinariesController(Controller):
    def __init__(self, ui):
        super().__init__(ui)
        self._adapter = None
        self._loaded_once = False

    @property
    def adapter(self):
        """The LOCAL scanner adapter, constructed on first access."""
        if self._adapter is None:
            from rmadd.package_managers.base import discover_local_scanner
            self._adapter = discover_local_scanner()
        return self._adapter

    # ------------------------------------------------------------- loading --

    async def load(self, force: bool = False):
        ui = self.ui
        if not ui.is_mounted:
            return
        result = self.result("local")
        if not force and (self._loaded_once and self.opt.local_packages()):
            self.render()
            return
        try:
            result.update("[cyan]Scanning local binaries...[/cyan]")
            pkgs = await asyncio.to_thread(self.adapter.list_installed)
            if not ui.is_mounted:
                return
            self.opt.hydrate_local(list(pkgs))
            self._loaded_once = True
            self.render()
            if pkgs:
                result.update(f"[green]Found {len(pkgs)} local binaries[/green]")
            else:
                result.update("[yellow]No local binaries found[/yellow]")
        except Exception as e:
            if ui.is_mounted:
                result.update(f"[bold red]Error scanning local binaries: {e}[/bold red]")

    async def ensure_loaded(self):
        """Original guard for remove-actions: scan only if never scanned."""
        if not self._loaded_once:
            await self.load()

    def render(self, pkgs=None):
        collection = PackageCollection(
            self.opt.local_packages() if pkgs is None else list(pkgs)
        )
        table = self.ui.query_one("#local-table", PackageTable)
        table.show_packages(collection)
        self.ui.move_cursor_first_row(table)
        self.update_actions()

    def shutdown(self):
        """Release the scanner's probe pool (no-op if the tab never opened)."""
        if self._adapter is not None:
            try:
                self._adapter.close()
            except Exception:
                pass

    # -------------------------------------------------------- action bar --

    def update_actions(self):
        ui = self.ui
        name, _mgr_str = ui.cursor("local")
        bar = ui.query_one("#local-action-bar")
        label = ui.query_one("#local-sel", Static)
        if name:
            bar.display = True
            label.update(f"[bold]{name}[/bold]")
            try:
                from rmadd.models import PackageManager

                busy = self.opt.pending_action(name, PackageManager.LOCAL) is not None
                ui.query_one("#btn-local-remove").disabled = busy
            except Exception:
                pass
        else:
            bar.display = False
        apply_pane_floor(ui.table_for("local"))
