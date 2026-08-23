"""About-tab stats: system card + per-manager package counts."""

import asyncio

from rmadd.controllers.base import Controller
from rmadd.logging import get_logger
from rmadd.screens.widgets.package_table import PackageTable
from rmadd.screens.widgets.system_card import SystemCard

logger = get_logger("stats_controller")


class StatsController(Controller):
    def __init__(self, ui):
        super().__init__(ui)
        self.busy = False
        self.loaded = False

    async def load(self):
        ui = self.ui
        if not ui.is_mounted or self.busy:
            return
        self.busy = True
        try:
            card = ui.query_one("#system-card", SystemCard)
            counts_table = ui.query_one("#package-table", PackageTable)
            if not self.loaded:
                card.update("[yellow]Fetching system info & package counts…[/yellow]")
                counts_table.show_counts({}, loading=True)
            self.ss.refresh()
            try:
                info = await asyncio.to_thread(self.ss.get_system_info)
                if ui.is_mounted:
                    card.display_info(info)
            except Exception as e:
                logger.exception("get_system_info failed")
                if ui.is_mounted:
                    card.update(f"[bold red]Error loading system info: {e}[/bold red]")
            try:
                counts = await asyncio.to_thread(self.ps.get_all_counts)
                if ui.is_mounted:
                    counts_table.show_counts(counts)
            except Exception as e:
                logger.exception("get_all_counts failed")
                if ui.is_mounted:
                    counts_table.show_counts({"error": str(e)})
            self.loaded = True
        finally:
            self.busy = False

    def patch_counts(self, counts: dict):
        """Render an exact counts mapping into the About table."""
        try:
            self.ui.query_one("#package-table", PackageTable).show_counts(counts)
        except Exception:
            pass

    def patch_from_state(self):
        """Fast path: derive counts from the optimistic set only (no I/O)."""
        counts = self.opt.counts_by_manager()
        if not counts:
            return
        self.patch_counts(counts)
