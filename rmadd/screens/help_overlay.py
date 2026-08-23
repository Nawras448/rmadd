"""Single-keystroke (?) keybinding help overlay (M3 Step 2)."""

from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Static

HELP_ROWS = (
    ("q", "Quit"),
    ("R", "Force refresh stats"),
    ("?", "Toggle this help"),
    ("F1-F5", "Tools / Search / Installed / Local / About"),
    ("enter", "Open package details"),
    ("i / r / u", "Quick install / remove / update"),
    ("type", "Live search as you type"),
    ("esc", "Cancel search · close panels"),
)


class HelpOverlay(ModalScreen):
    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("q", "dismiss", "Close"),  # screen wins over app quit while open
    ]

    def compose(self):
        with Vertical(id="help-panel"):
            yield Static("rmadd — Keybindings", id="help-title")
            body = "\n".join(f"[b]{key}[/b]   {desc}" for key, desc in HELP_ROWS)
            yield Static(body, id="help-body")
        yield Footer()
