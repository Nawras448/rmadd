"""Lightweight remove-confirmation modal (M3 Step 3, opt-in via config)."""

from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Static


class ConfirmRemoveScreen(ModalScreen):
    """Asks y/n before a destructive removal; dismisses with bool result."""

    BINDINGS = [
        ("y", "confirm", "Remove"),
        ("n", "cancel", "Keep"),
        ("escape", "cancel", "Keep"),
    ]

    def __init__(self, name: str, mgr, **kwargs):
        super().__init__(**kwargs)
        self._name = name
        self._mgr = mgr

    def compose(self):
        with Vertical(id="confirm-panel"):
            yield Static(
                f"Remove [bold]{self._name}[/bold] via {self._mgr.value}?",
                id="confirm-title",
            )
            yield Static("This cannot be undone.", id="confirm-hint")
            with Horizontal(id="confirm-buttons"):
                yield Button("Remove (y)", id="btn-confirm-yes", variant="error")
                yield Button("Keep (n)", id="btn-confirm-no", variant="default")
        yield Footer()

    def on_mount(self):
        try:
            self.query_one("#btn-confirm-no", Button).focus()
        except Exception:
            pass

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-confirm-yes":
            self.dismiss(True)
        elif event.button.id == "btn-confirm-no":
            self.dismiss(False)
