import asyncio

from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button
from textual.containers import Horizontal, Vertical
from textual.binding import Binding

from features.package_store.domain import Package


class PackageDetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("i", "quick_install", "Install"),
    ]

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
        self.query_one("#package-info", Static).border_title = "Package Details"

    async def on_button_pressed(self, event: Button.Pressed):
        action = {
            "btn-install": "install",
            "btn-remove": "remove",
            "btn-update": "update",
        }.get(event.button.id)
        if action:
            await self._run_action(action)

    async def action_quick_install(self):
        await self._run_action("install")

    async def _run_action(self, action: str):
        result = self.query_one("#action-result", Static)
        name = self._pkg.name
        mgr = self._pkg.manager
        labels = {
            "install": ("📥 Installing", "Install"),
            "remove": ("🗑 Removing", "Remove"),
            "update": ("🔄 Updating", "Update"),
        }
        emoji, title = labels[action]
        try:
            result.update(f"[yellow]{emoji} {title} {name}...[/yellow]")
            method = getattr(self._ps, action)
            ok = await asyncio.to_thread(method, name, mgr)
            icon = "✓" if ok else "✗"
            result.update(f"[bold]{icon} {title} {'succeeded' if ok else 'failed'} ({name})[/bold]")
        except Exception as e:
            result.update(f"[bold red]Error: {e}[/bold red]")
