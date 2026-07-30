from textual.app import ComposeResult
from textual.widgets import Static, Label
from textual.containers import Vertical


class SettingsView(Static):
    """عرض مخصص لإعدادات التطبيق والحزم"""

    def compose(self) -> ComposeResult:
        yield Label("Settings & Configuration", id="settings-title")
        yield Static("Here you can configure your package manager preferences.")
        yield Static("Feature coming soon...")