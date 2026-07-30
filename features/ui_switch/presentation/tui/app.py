import os

from textual.app import App
from textual.binding import Binding

from features.system_info.presentation.dashboard_screen import DashboardScreen

_CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "style.tcss")


class RmaddTuiApp(App):
    TITLE = "rmadd"
    SUB_TITLE = "Package & System Monitor"

    CSS_PATH = _CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "pop_screen", "Dashboard"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, container):
        super().__init__()
        self._container = container
        self.system_service = container.get_system_service()
        self.package_service = container.get_package_service()
        self.hardware_service = container.get_hardware_service()

    def on_mount(self):
        self.push_screen(DashboardScreen(self.system_service, self.package_service, self.hardware_service))

    def action_refresh(self):
        self.system_service.refresh()
        self.notify("Data refreshed", timeout=3)
