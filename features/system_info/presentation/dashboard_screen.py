import asyncio

from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from textual.containers import Horizontal, Vertical

from features.system_info.presentation.system_card import SystemCard
from features.system_info.presentation.full_system_screen import FullSystemScreen
from features.package_store.presentation.package_table import PackageTable
from features.system_monitor.presentation.hardware_monitor_screen import HardwareMonitorScreen
from features.package_store.presentation.store_screen import StoreScreen


class DashboardScreen(Screen):
    def __init__(self, system_service, package_service, hardware_service=None):
        super().__init__()
        self._ss = system_service
        self._ps = package_service
        self._hw = hardware_service

    def compose(self):
        yield Header(show_clock=True)
        with Horizontal():
            with Vertical(id="sidebar") as sidebar:
                sidebar.border_title = "Navigation"
                yield Static("[bold]Navigation[/bold]", id="sidebar-title")
                yield Button("Dashboard", id="btn_dashboard", variant="primary")
                yield Button("Full System", id="btn_full_system")
                yield Button("App Store", id="btn_store")
                yield Button("Hardware Monitor", id="btn_hardware")
                yield Button("Quit", id="btn_quit", variant="error")
            with Vertical(id="content"):
                yield SystemCard(id="system-card")
                yield PackageTable(id="package-table")
        yield Footer()

    async def on_mount(self):
        self.query_one("#system-card", SystemCard).update("[yellow]Loading system info...[/yellow]")
        self.query_one("#package-table", PackageTable).show_counts({})
        asyncio.create_task(self._load_system_info())
        asyncio.create_task(self._load_package_counts())

    async def _load_system_info(self):
        try:
            info = await asyncio.to_thread(self._ss.get_system_info)
            self.query_one("#system-card", SystemCard).display_info(info)
        except Exception as e:
            self.query_one("#system-card", SystemCard).update(f"[bold red]Error loading system info: {e}[/bold red]")

    async def _load_package_counts(self):
        try:
            counts = await asyncio.to_thread(self._ps.get_all_counts)
            self.query_one("#package-table", PackageTable).show_counts(counts)
        except Exception as e:
            self.query_one("#package-table", PackageTable).show_counts({"error": str(e)})

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn_full_system":
            self.app.push_screen(FullSystemScreen(self._ss, self._hw))
        elif event.button.id == "btn_store":
            self.app.push_screen(StoreScreen(self._ps))
        elif event.button.id == "btn_hardware":
            self.app.push_screen(HardwareMonitorScreen(self._hw))
        elif event.button.id == "btn_quit":
            self.app.exit()
