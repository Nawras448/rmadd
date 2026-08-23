import asyncio

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from rmadd.models import Package, PackageStatus, supports
from rmadd.screens.install_progress_screen import InstallProgressScreen


class PackageDetailScreen(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
        Binding("i", "quick_install", "Install"),
    ]

    def __init__(self, pkg: Package, package_service, is_installed: bool | None = None,
                 confirm_remove: bool = False):
        super().__init__()
        self._pkg = pkg
        self._ps = package_service
        self._is_installed = is_installed
        self._confirm_remove = bool(confirm_remove)

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

    async def on_mount(self):
        p = self._pkg
        if self._is_installed is None:
            status = await asyncio.to_thread(self._ps.get_status, p.name, p.manager)
            status_label = {
                PackageStatus.INSTALLED: "Installed",
                PackageStatus.AVAILABLE: "Available",
            }.get(status, "Unknown")
        else:
            status_label = "Installed" if self._is_installed else "Available"
        info = (
            f"[bold]Package Details[/bold]\n\n"
            f"Name: {p.name}\n"
            f"Version: {p.version}\n"
            f"Architecture: {p.arch or 'N/A'}\n"
            f"Repository: {p.repo or 'N/A'}\n"
            f"Size: {p.size or 'N/A'}\n"
            f"Manager: {p.manager.value}\n"
            f"Status: {status_label}\n"
            f"Summary: {p.summary or 'N/A'}\n"
        )
        self.query_one("#package-info", Static).update(info)
        self.query_one("#package-info", Static).border_title = "Package Details"
        self._rebuild_actions()

    def _rebuild_actions(self):
        """Show only the actions that make sense for the current state:
        installed -> Remove/Update; available -> Install. Each gated by the
        manager's declared capabilities."""
        installed = self._is_installed is True
        self.query_one("#btn-install", Button).display = (
            not installed and supports(self._pkg.manager, "install")
        )
        self.query_one("#btn-remove", Button).display = (
            installed and supports(self._pkg.manager, "remove")
        )
        self.query_one("#btn-update", Button).display = (
            installed and supports(self._pkg.manager, "update")
        )

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
        if action == "install" and self._is_installed is True:
            self.notify("Already installed", severity="warning")
            return
        if action in ("remove", "update") and self._is_installed is False:
            self.notify("Not installed", severity="warning")
            return
        if action == "remove" and self._confirm_remove:
            from rmadd.screens.confirm_remove import ConfirmRemoveScreen

            def _after(confirmed):
                if confirmed:
                    self._launch(action)

            self.app.push_screen(
                ConfirmRemoveScreen(self._pkg.name, self._pkg.manager), _after
            )
            return
        self._launch(action)

    def _launch(self, action: str):
        self.app.state_bus.emit(action, self._pkg.name, self._pkg.manager, phase="pending")
        self.app.push_screen(
            InstallProgressScreen(
                self._ps,
                action,
                self._pkg.name,
                self._pkg.manager,
                on_finish=self._on_operation_finished,
            )
        )

    def _on_operation_finished(self, action: str, section: str, name, mgr, ok: bool, cancelled: bool, result=None):
        from rmadd.screens import op_feedback

        pane = self.query_one("#action-result", Static)
        label = action.title()
        if cancelled:
            pane.update(f"[bold red]✗ {label} cancelled ({name})[/bold red]")
        elif ok:
            pane.update(f"[bold green]✓ {label} succeeded ({name})[/bold green]")
        else:
            pane.update(op_feedback.failure_line(action, name, result))
        op_feedback.apply(self, action, name, mgr, result, cancelled)
        if ok and self._is_installed is not None:
            if action == "install":
                self._is_installed = True
            elif action == "remove":
                self._is_installed = False
            self._rebuild_actions()
