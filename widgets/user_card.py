from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Label, Static
from textual.binding import Binding

# Import the sub-views
from widgets.About import About
from widgets.settings_view import SettingsView


class UserCard(Static):
    # Application name and subtitle
    TITLE = "rmadd"
    SUB_TITLE = "v0.1.0-dev | Package & System Monitor"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh Data", show=True),
        
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

        with Horizontal():
            # Sidebar
            with Vertical(id="tartib"):
                yield Static("option", id="sidebar-title")
                yield Button("program", id="btn_programs")
                yield Button("settings", id="btn_settings")
                yield Button("About", id="btn_About")

            # Area for the variable content view
            with Vertical(id="content"):
                yield Static("Programs View") 
                 # Default view shown when the app opens

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Event handler: navigate between pages based on the pressed button"""

        content_area = self.query_one("#content", Vertical)

        if event.button.id == "btn_programs":
            content_area.remove_children()
            content_area.mount(Static("Programs View"))

        elif event.button.id == "btn_settings":
            content_area.remove_children()
            content_area.mount(SettingsView())

        elif event.button.id == "btn_About":
            content_area.remove_children()
            content_area.mount(About())
            