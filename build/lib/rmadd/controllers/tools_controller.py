"""Download-Tools tab: installer tool catalog and AppImage installs."""

from textual.widgets import Static

from rmadd.controllers.base import Controller
from rmadd.models import PackageManager
from rmadd.screens.appimage_install_screen import AppImageInstallScreen
from rmadd.screens.widgets.package_table import apply_pane_floor
from rmadd.screens.widgets.tools_table import ToolsTable
from rmadd.tools import detect_tools


class ToolsController(Controller):
    def __init__(self, ui):
        super().__init__(ui)
        self.entries: list = []

    # ------------------------------------------------------------- loading --

    def load_initial(self):
        self.entries = detect_tools()
        self.ui.query_one("#tools-table", ToolsTable).show_tools(self.entries)
        self.update_actions()

    def refresh_after_op(self):
        """Re-probe the catalog after an install/update finished."""
        self.load_initial()

    # ------------------------------------------------------------ actions --

    async def run_action(self, action: str):
        name, mgr_str = self.ui.cursor("tools")
        result = self.result("tools")
        if not name or not mgr_str or mgr_str == "system":
            result.update("[bold red]No installable tool selected (no system package manager found)[/bold red]")
            return
        self.ui.ops.start(action, "tools", name, PackageManager(mgr_str))

    def open_appimage(self):
        self.ui.push_modal(
            AppImageInstallScreen(
                self.ps,
                on_finish=self.on_appimage_installed,
            )
        )

    def on_appimage_installed(self, ok: bool, name: str):
        result = self.result("tools")
        if ok:
            result.update(f"[bold green]✓ AppImage installed: {name}[/bold green]")
            self.emit_install_confirmed(name)
            self.track(self.ui.installed.load())
        else:
            result.update(f"[bold red]✗ AppImage install failed: {name}[/bold red]")
        self.ui.auto_scroll_result("tools")

    def emit_install_confirmed(self, name: str):
        self.bus.emit("install", name, PackageManager.APPIMAGE)

    # -------------------------------------------------------- action bar --

    def update_actions(self):
        ui = self.ui
        name, mgr_str = ui.cursor("tools")
        bar = ui.query_one("#tools-action-bar")
        label = ui.query_one("#tools-sel", Static)
        if not name:
            bar.display = False
            apply_pane_floor(ui.table_for("tools"))
            return
        bar.display = True
        label.update(f"[bold]{name}[/bold]")
        installed_names = {t.name for t, st in self.entries if st}
        ui.query_one("#btn-tools-install").disabled = name in installed_names
        ui.query_one("#btn-tools-update").disabled = name not in installed_names
        apply_pane_floor(ui.table_for("tools"))
