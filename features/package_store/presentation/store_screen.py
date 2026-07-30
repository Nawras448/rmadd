from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, DataTable, Button
from textual.containers import Horizontal, Vertical

from features.package_store.presentation.package_detail_screen import PackageDetailScreen
from features.package_store.presentation.package_table import PackageTable
from features.package_store.domain import PackageManager


class StoreScreen(Screen):
    def __init__(self, package_service):
        super().__init__()
        self._ps = package_service
        self._current_manager: PackageManager | None = None

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("enter", "select", "Details"),
        ("i", "quick_install", "Install"),
        ("r", "quick_remove", "Remove"),
        ("u", "quick_update", "Update"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        with Vertical(id="store-layout"):
            yield Input(placeholder="Search packages...", id="search-input")
            with Horizontal(id="filter-bar"):
                yield Static("[bold]Filter:[/bold]", id="filter-label")
                for mgr in PackageManager:
                    yield Button(f"[{mgr.value}]", id=f"filter-{mgr.value}", classes="filter-tag")
            yield PackageTable(id="store-table")
            with Horizontal(id="action-bar"):
                yield Static(id="sel-pkg", classes="sel-label")
                yield Button("Install", id="btn-install", variant="primary")
                yield Button("Remove", id="btn-remove", variant="error")
                yield Button("Update", id="btn-update", variant="default")
                yield Button("Details", id="btn-details", variant="default")
            yield Static(id="action-result-store")
        yield Footer()

    def _get_cursor_row(self) -> tuple:
        table = self.query_one("#store-table", PackageTable)
        dt = table._table
        coord = dt.cursor_coordinate
        if coord is None or coord.row >= dt.row_count:
            return ("", "")
        row_key = dt.get_row_at(coord.row)
        if row_key is None:
            return ("", "")
        key = row_key.value if hasattr(row_key, "value") else str(row_key)
        parts = key.split("|", 1) if "|" in key else (key, "")
        return (parts[0], parts[1]) if len(parts) == 2 else ("", "")

    def on_mount(self):
        self._show_all()
        self._update_actions()
        self.query_one("#inner-table", DataTable).focus()

    def _show_all(self, manager=None):
        if manager:
            pkgs = self._ps.list_installed(manager)
        else:
            pkgs = self._ps.list_installed()
        self.query_one("#store-table", PackageTable).show_packages(pkgs)
        self._table_changed()

    def _show_search(self, query: str, manager=None):
        results = self._ps.search(query, manager)
        self.query_one("#store-table", PackageTable).show_packages(results)
        self._table_changed()

    def _table_changed(self):
        self.query_one("#action-result-store", Static).update("")
        self._update_actions()

    def on_input_submitted(self, event: Input.Submitted):
        query = event.value.strip()
        if not query:
            self._show_all(self._current_manager)
        else:
            self._show_search(query, self._current_manager)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        self._update_actions()

    def _update_actions(self):
        name, mgr_str = self._get_cursor_row()
        bar = self.query_one("#action-bar", Horizontal)
        label = self.query_one("#sel-pkg", Static)
        if name and mgr_str:
            bar.display = True
            label.update(f"[bold]{name}[/bold] ({mgr_str})")
        else:
            bar.display = False

    def action_select(self):
        self._open_detail()

    def _open_detail(self):
        name, mgr_str = self._get_cursor_row()
        if not name or not mgr_str:
            return
        pkg = self._ps.get_package_detail(name, PackageManager(mgr_str))
        if pkg:
            self.app.push_screen(PackageDetailScreen(pkg, self._ps))

    def on_button_pressed(self, event: Button.Pressed):
        for mgr in PackageManager:
            if event.button.id == f"filter-{mgr.value}":
                self._current_manager = mgr if self._current_manager != mgr else None
                self._refresh_filter_style()
                self._show_all(self._current_manager)
                return

        if event.button.id == "btn-install":
            self._do_action("install")
        elif event.button.id == "btn-remove":
            self._do_action("remove")
        elif event.button.id == "btn-update":
            self._do_action("update")
        elif event.button.id == "btn-details":
            self._open_detail()

    def _do_action(self, action: str):
        name, mgr_str = self._get_cursor_row()
        if not name or not mgr_str:
            return
        result = self.query_one("#action-result-store", Static)
        mgr = PackageManager(mgr_str)
        try:
            if action == "install":
                result.update("[yellow]Installing...[/yellow]")
                ok = self._ps.install(name, mgr)
                result.update(f"[bold]{'✓' if ok else '✗'} Install {'succeeded' if ok else 'failed'}[/bold]")
            elif action == "remove":
                result.update("[yellow]Removing...[/yellow]")
                ok = self._ps.remove(name, mgr)
                result.update(f"[bold]{'✓' if ok else '✗'} Remove {'succeeded' if ok else 'failed'}[/bold]")
            elif action == "update":
                result.update("[yellow]Updating...[/yellow]")
                ok = self._ps.update(name, mgr)
                result.update(f"[bold]{'✓' if ok else '✗'} Update {'succeeded' if ok else 'failed'}[/bold]")
        except Exception as e:
            result.update(f"[bold red]Error: {e}[/bold red]")

    def action_quick_install(self):
        self._do_action("install")

    def action_quick_remove(self):
        self._do_action("remove")

    def action_quick_update(self):
        self._do_action("update")

    def _refresh_filter_style(self):
        for mgr in PackageManager:
            tag = self.query_one(f"#filter-{mgr.value}", Button)
            tag.variant = "primary" if self._current_manager == mgr else "default"
