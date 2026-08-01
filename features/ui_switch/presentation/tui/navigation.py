from textual.containers import Vertical
from textual.widgets import Button, Static


class NavigationSidebar(Vertical):
    """Persistent navigation sidebar shown on the main views.

    The Dashboard always stays at the base of the screen stack; the
    sub-views (Full System, Hardware Monitor) are pushed on top of it
    and replaced in place via ``switch_screen``. The App Store is always
    pushed as a full-screen overlay and is not part of this layout.
    """

    def compose(self):
        self.border_title = "Navigation"
        yield Static("[bold]Navigation[/bold]", id="sidebar-title")
        yield Button("Dashboard", id="btn_dashboard", variant="primary")
        yield Button("Full System", id="btn_full_system")
        yield Button("App Store", id="btn_store")
        yield Button("Hardware Monitor", id="btn_hardware")
        yield Button("Quit", id="btn_quit", variant="error")

    def _on_dashboard(self) -> bool:
        from features.system_info.presentation.dashboard_screen import DashboardScreen
        return isinstance(self.app.screen, DashboardScreen)

    def _push_main_view(self, screen) -> None:
        if self._on_dashboard():
            self.app.push_screen(screen)
        else:
            self.app.switch_screen(screen)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        app = self.app
        if bid == "btn_quit":
            app.exit()
        elif bid == "btn_store":
            from features.package_store.presentation.store_screen import StoreScreen
            app.push_screen(StoreScreen(app.package_service))
        elif bid == "btn_dashboard":
            if not self._on_dashboard():
                app.pop_screen()
        elif bid == "btn_full_system":
            from features.system_info.presentation.full_system_screen import FullSystemScreen
            self._push_main_view(FullSystemScreen(app.system_service, app.hardware_service))
        elif bid == "btn_hardware":
            from features.system_monitor.presentation.hardware_monitor_screen import HardwareMonitorScreen
            self._push_main_view(HardwareMonitorScreen(app.hardware_service))
