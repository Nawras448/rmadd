import asyncio
import os
from collections.abc import Callable

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Footer, Header, Static


class AppImageInstallScreen(Screen):
    """Pick a local .AppImage file and install it into ~/Applications."""

    BINDINGS = [("escape", "dismiss", "Back")]

    def __init__(self, package_service, on_finish: Callable | None = None):
        super().__init__()
        self._ps = package_service
        self._on_finish = on_finish
        self._selected: str | None = None
        self._busy = False

    def compose(self):
        yield Header(show_clock=True)
        with Vertical(id="appimage-panel"):
            yield Static("Install AppImage from local file", id="appimage-title", classes="progress-title")
            yield Static(
                "Pick a .AppImage file below, then press Install Selected. "
                "The file is copied into ~/Applications and made executable.",
                id="appimage-hint",
            )
            yield DirectoryTree(id="appimage-tree", path=os.path.expanduser("~"))
            yield Static("", id="appimage-status")
            with Horizontal(id="appimage-buttons"):
                yield Button("Cancel", id="btn-appimage-cancel", variant="default")
                yield Button("Install Selected", id="btn-appimage-install", variant="primary", disabled=True)
        yield Footer()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected):
        event.stop()
        path = str(event.path)
        self._selected = path
        self.query_one("#btn-appimage-install", Button).disabled = not path.lower().endswith(".appimage")
        self.query_one("#appimage-status", Static).update(f"[cyan]Selected: {path}[/cyan]")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-appimage-cancel":
            self.dismiss()
        elif event.button.id == "btn-appimage-install":
            asyncio.create_task(self._install())

    async def _install(self):
        if self._busy or not self._selected:
            return
        self._busy = True
        self.query_one("#btn-appimage-install", Button).disabled = True
        status = self.query_one("#appimage-status", Static)
        name = os.path.basename(self._selected)
        status.update(f"[yellow]Installing {name}...[/yellow]")
        try:
            ok = await asyncio.to_thread(
                self._ps.install_appimage, self._selected
            )
        except Exception as e:
            ok = False
            status.update(f"[bold red]Error: {e}[/bold red]")
        if ok:
            status.update(f"[bold green]✓ Installed {name} into ~/Applications[/bold green]")
        else:
            status.update("[bold red]✗ Installation failed[/bold red]")
        if self._on_finish is not None:
            self._on_finish(ok, name)
        self.set_timer(1.5, self._schedule_dismiss)

    def _schedule_dismiss(self):
        self.dismiss()
