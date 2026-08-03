import os

from textual.app import App
from textual.binding import Binding
from textual.theme import Theme

from features.package_store.presentation.store_screen import StoreScreen

_CSS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "..", "style.tcss")

CYBERPUNK_THEME = Theme(
    name="cyberpunk",
    primary="#a855f7",
    secondary="#2dd4bf",
    accent="#10b981",
    warning="#fbbf24",
    error="#f43f5e",
    success="#22c55e",
    foreground="#e2e8f0",
    background="#0b0e14",
    surface="#0f111a",
    panel="#131626",
    boost="#131626",
    dark=True,
    luminosity_spread=0.15,
    variables={
        "footer-key-background": "#a855f7",
        "footer-key-foreground": "#0b0e14",
        "footer-description-foreground": "#94a3b8",
        "footer-description-background": "transparent",
        "footer-item-background": "transparent",
        "block-cursor-background": "#10b981",
        "block-cursor-foreground": "#0b0e14",
        "block-cursor-text-style": "bold",
        "input-selection-background": "#10b981 35%",
        "scrollbar": "#a855f7",
        "scrollbar-hover": "#c084fc",
        "scrollbar-background": "#0f111a",
        "scrollbar-background-hover": "#131626",
        "scrollbar-background-active": "#131626",
        "button-color-foreground": "#0b0e14",
        "screen-selection-background": "#134e4a",
        "screen-selection-foreground": "#e2e8f0",
    },
)


class RmaddTuiApp(App):
    TITLE = "rmadd"
    SUB_TITLE = "Package & System Monitor"

    CSS_PATH = _CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, container):
        super().__init__()
        self._container = container
        self.register_theme(CYBERPUNK_THEME)
        self.theme = "cyberpunk"
        self.system_service = container.get_system_service()
        self.package_service = container.get_package_service()
        self.hardware_service = container.get_hardware_service()

    def bell(self) -> None:
        """Silence all framework bells (CSS errors, restricted input, fatal errors)."""



    def on_mount(self):
        self.push_screen(StoreScreen(self.system_service, self.package_service))

    def action_refresh(self):
        self.system_service.refresh()
        screen = self.screen
        if hasattr(screen, "_refresh_stats"):
            screen._refresh_stats()
        self.notify("Data refreshed", timeout=3)
