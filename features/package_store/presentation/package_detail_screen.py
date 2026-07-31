import asyncio

from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from textual.containers import Horizontal, Vertical

from features.package_store.domain import Package


class PackageDetailScreen(Screen):
    def __init__(self, pkg: Package, package_service):
        super().__init__()
        self._pkg = pkg
        self._ps = package_service

    def compose(self):
        yield Header(show_clock=True)
        with Vertical(id="detail-layout"):
            yield Static(id="package-info", classes="detail-card")
            with Horizontal(id="actions"):
                yield Button("Install", id="btn-install", variant="primary")
                yield Button("Remove", id="btn-remove", variant="error")
                yield Button("Update", id="btn-update", variant="default")
            yield Static(id="action-result")
        yield Footer()

    def on_mount(self):
        p = self._pkg
        info = (
            f"[bold]Package Details[/bold]\n\n"
            f"Name: {p.name}\n"
            f"Version: {p.version}\n"
            f"Architecture: {p.arch or 'N/A'}\n"
            f"Repository: {p.repo or 'N/A'}\n"
            f"Size: {p.size or 'N/A'}\n"
            f"Manager: {p.manager.value}\n"
            f"Summary: {p.summary or 'N/A'}\n"
        )
        self.query_one("#package-info", Static).update(info)

    async def on_button_pressed(self, event: Button.Pressed):
        result = self.query_one("#action-result", Static)
        name = self._pkg.name
        mgr = self._pkg.manager

        try:
            if event.button.id == "btn-install":
                result.update("[yellow]Installing...[/yellow]")
                ok = await asyncio.to_thread(self._ps.install, name, mgr)
                result.update(f"[bold]{'✓' if ok else '✗'} Install {'succeeded' if ok else 'failed'}[/bold]")
            elif event.button.id == "btn-remove":
                result.update("[yellow]Removing...[/yellow]")
                ok = await asyncio.to_thread(self._ps.remove, name, mgr)
                result.update(f"[bold]{'✓' if ok else '✗'} Remove {'succeeded' if ok else 'failed'}[/bold]")
            elif event.button.id == "btn-update":
                result.update("[yellow]Updating...[/yellow]")
                ok = await asyncio.to_thread(self._ps.update, name, mgr)
                result.update(f"[bold]{'✓' if ok else '✗'} Update {'succeeded' if ok else 'failed'}[/bold]")
        except Exception as e:
            result.update(f"[bold red]Error: {e}[/bold red]")
