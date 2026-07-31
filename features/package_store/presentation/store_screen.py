import asyncio

from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, DataTable, Button, TabbedContent, TabPane
from textual.containers import Horizontal
from textual.coordinate import Coordinate

from features.package_store.presentation.package_detail_screen import PackageDetailScreen
from features.package_store.presentation.package_table import PackageTable
from features.package_store.presentation.tools_table import ToolsTable
from features.package_store.presentation.manager_filter import ManagerFilter
from features.package_store.installer_tools import detect_tools
from features.package_store.domain import PackageManager, PackageStatus, Package, PackageCollection


class StoreScreen(Screen):
    def __init__(self, package_service):
        super().__init__()
        self._ps = package_service
        self._search_managers: set[PackageManager] | None = None
        self._installed_managers: set[PackageManager] | None = None
        self._installed_pkgs: list[Package] = []
        self._installed_set: set[tuple[str, PackageManager]] = set()
        self._tools: list = []
        self._active_section = "search"
        self._search_gen = 0
        self._search_query = ""
        self._debounce_task: asyncio.Task | None = None

    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("enter", "select", "Details"),
        ("i", "quick_install", "Install"),
        ("r", "quick_remove", "Remove"),
        ("u", "quick_update", "Update"),
        ("f1", "tab_tools", "Tools"),
        ("f2", "tab_search", "Search"),
        ("f3", "tab_installed", "Installed"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        with TabbedContent(initial="pane-search", id="store-tabs"):
            with TabPane("أدوات التحميل", id="pane-tools"):
                yield ToolsTable(id="tools-table")
                with Horizontal(id="tools-action-bar"):
                    yield Static(id="tools-sel", classes="sel-label")
                    yield Button("Install", id="btn-tools-install", variant="primary")
                    yield Button("Update", id="btn-tools-update", variant="default")
                yield Static(id="tools-result")

            with TabPane("البحث عن برنامج", id="pane-search"):
                with Horizontal(id="search-top"):
                    yield Input(placeholder="Search programs (as you type)...", id="search-input")
                yield ManagerFilter(self._ps.available_managers, id="search-managers")
                yield PackageTable(id="search-table")
                with Horizontal(id="search-action-bar"):
                    yield Static(id="search-sel", classes="sel-label")
                    yield Button("Install", id="btn-search-install", variant="primary")
                    yield Button("Details", id="btn-search-details", variant="default")
                yield Static(id="search-result")

            with TabPane("البرامج المثبتة", id="pane-installed"):
                with Horizontal(id="installed-top"):
                    yield Input(placeholder="Search installed programs...", id="installed-input")
                yield ManagerFilter(self._ps.available_managers, id="installed-managers")
                yield PackageTable(id="installed-table")
                with Horizontal(id="installed-action-bar"):
                    yield Static(id="installed-sel", classes="sel-label")
                    yield Button("Remove", id="btn-installed-remove", variant="error")
                    yield Button("Update", id="btn-installed-update", variant="default")
                    yield Button("Details", id="btn-installed-details", variant="default")
                yield Static(id="installed-result")
        yield Footer()

    # ---------- helpers ----------

    def _table_for(self, section: str):
        if section == "search":
            return self.query_one("#search-table", PackageTable)
        if section == "installed":
            return self.query_one("#installed-table", PackageTable)
        return self.query_one("#tools-table", ToolsTable)

    def _get_cursor_row(self, section: str) -> tuple:
        dt = self._table_for(section)._table
        coord = dt.cursor_coordinate
        if coord is None or coord.row >= dt.row_count:
            return ("", "")
        cell_key = dt.coordinate_to_cell_key(coord)
        key = cell_key.row_key.value
        parts = key.split("|", 1) if "|" in key else (key, "")
        return (parts[0], parts[1]) if len(parts) == 2 else ("", "")

    def _move_cursor_first_row(self, table):
        dt = table._table
        if dt.row_count > 0:
            try:
                dt.cursor_coordinate = Coordinate(0, 0)
            except Exception:
                pass

    def _result(self, section: str) -> Static:
        ids = {"tools": "#tools-result", "search": "#search-result", "installed": "#installed-result"}
        return self.query_one(ids[section], Static)

    # ---------- data loading ----------

    async def on_mount(self):
        self._tools = detect_tools()
        self.query_one("#tools-table", ToolsTable).show_tools(self._tools)
        self._update_tools_actions()
        self._update_search_actions()
        self._update_installed_actions()
        asyncio.create_task(self._do_load_installed())

    async def _do_load_installed(self):
        result = self._result("installed")
        table = self.query_one("#installed-table", PackageTable)
        try:
            pkgs = await asyncio.to_thread(self._ps.list_installed)
            self._installed_pkgs = list(pkgs)
            self._installed_set = {(p.name, p.manager) for p in self._installed_pkgs}
            self._show_installed(PackageCollection(self._installed_pkgs))
            result.update(f"[green]Loaded {pkgs.total} installed packages[/green]")
            if self._active_section == "installed":
                table._table.focus()
            if self._search_query:
                asyncio.create_task(self._do_search(self._search_query, self._search_managers))
        except Exception as e:
            result.update(f"[bold red]Error loading packages: {e}[/bold red]")

    def _show_installed(self, collection: PackageCollection):
        if self._installed_managers:
            collection = collection.by_managers(self._installed_managers)
        table = self.query_one("#installed-table", PackageTable)
        table.show_packages(collection)
        self._move_cursor_first_row(table)
        self._update_installed_actions()

    def _filter_installed(self, query: str):
        q = query.strip().lower()
        collection = PackageCollection(self._installed_pkgs)
        if self._installed_managers:
            collection = collection.by_managers(self._installed_managers)
        if q:
            collection = collection.search(q)
        self._show_installed(collection)

    async def _do_search(self, query: str, managers=None):
        result = self._result("search")
        table = self.query_one("#search-table", PackageTable)
        q = query.strip()
        self._search_query = q
        if not q:
            result.update("[yellow]Type a search term — results appear as you type[/yellow]")
            table.show_packages(PackageCollection([]))
            return
        self._search_gen += 1
        gen = self._search_gen
        manager_list = list(self._ps.available_managers) if managers is None else list(managers)
        merged: list[Package] = []
        done = 0
        result.update(f"[cyan]Searching... 0/{len(manager_list)}[/cyan]")

        async def run(mgr: PackageManager):
            nonlocal done
            try:
                coll = await asyncio.to_thread(self._ps.search, q, mgr)
            except Exception:
                coll = PackageCollection([])
            if gen != self._search_gen:
                return
            done += 1
            merged.extend(list(coll))
            if done < len(manager_list):
                result.update(f"[cyan]Searching... {done}/{len(manager_list)}[/cyan]")
            self._render_search_results(table, PackageCollection(merged), q, result, incremental=True)

        await asyncio.gather(*[asyncio.create_task(run(m)) for m in manager_list])
        if gen == self._search_gen:
            self._render_search_results(table, PackageCollection(merged), q, result)

    def _render_search_results(self, table, collection, q, result, incremental=False):
        for p in collection:
            p.status = (
                PackageStatus.INSTALLED
                if (p.name, p.manager) in self._installed_set
                else PackageStatus.AVAILABLE
            )
        table.show_packages(collection)
        self._move_cursor_first_row(table)
        self._update_search_actions()
        if collection.total == 0:
            result.update(f"[yellow]No results for '{q}'[/yellow]")
            return
        installed_count = sum(1 for p in collection if p.status == PackageStatus.INSTALLED)
        if incremental:
            result.update(
                f"[green]{collection.total} results so far...[/green][cyan] ({installed_count} ✓)[/cyan]"
            )
        else:
            result.update(
                f"[green]{collection.total} results[/green][cyan] — {installed_count} already installed (✓)[/cyan]"
            )

    def _schedule_live_search(self, query: str):
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        self._debounce_task = asyncio.create_task(self._delayed_search(query))

    async def _delayed_search(self, query: str):
        try:
            await asyncio.sleep(0.25)
        except asyncio.CancelledError:
            return
        await self._do_search(query, self._search_managers)

    # ---------- events ----------

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "search-input":
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            asyncio.create_task(self._do_search(event.value, self._search_managers))

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "installed-input":
            self._filter_installed(event.value)
        elif event.input.id == "search-input":
            self._schedule_live_search(event.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        parent_id = event.data_table.parent.id
        if parent_id == "search-table":
            self._update_search_actions()
        elif parent_id == "installed-table":
            self._update_installed_actions()
        elif parent_id == "tools-table":
            self._update_tools_actions()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        section = {
            "search-table": "search",
            "installed-table": "installed",
            "tools-table": "tools",
        }.get(event.data_table.parent.id, "installed")
        self._active_section = section
        self._open_detail(section)

    def on_manager_filter_changed(self, event: ManagerFilter.Changed):
        if event.filter.id == "search-managers":
            self._search_managers = event.selected
            query = self.query_one("#search-input", Input).value
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            asyncio.create_task(self._do_search(query, self._search_managers))
        elif event.filter.id == "installed-managers":
            self._installed_managers = event.selected
            self._filter_installed(self.query_one("#installed-input", Input).value)

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-tools-install":
            asyncio.create_task(self._do_tool_action("install"))
        elif bid == "btn-tools-update":
            asyncio.create_task(self._do_tool_action("update"))
        elif bid == "btn-search-install":
            asyncio.create_task(self._do_pkg_action("install", "search"))
        elif bid == "btn-search-details":
            self._open_detail("search")
        elif bid == "btn-installed-remove":
            asyncio.create_task(self._do_pkg_action("remove", "installed"))
        elif bid == "btn-installed-update":
            asyncio.create_task(self._do_pkg_action("update", "installed"))
        elif bid == "btn-installed-details":
            self._open_detail("installed")

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
        section = event.pane.id.removeprefix("pane-")
        self._active_section = section
        if section == "tools":
            self.query_one("#tools-table")._table.focus()
        elif section == "search":
            self.query_one("#search-input").focus()
        else:
            self.query_one("#installed-table")._table.focus()

    # ---------- keyboard actions ----------

    def action_tab_tools(self):
        self.query_one(TabbedContent).active = "pane-tools"

    def action_tab_search(self):
        self.query_one(TabbedContent).active = "pane-search"

    def action_tab_installed(self):
        self.query_one(TabbedContent).active = "pane-installed"

    def action_select(self):
        self._open_detail(self._active_section)

    async def action_quick_install(self):
        if self._active_section == "tools":
            await self._do_tool_action("install")
        elif self._active_section == "search":
            await self._do_pkg_action("install", "search")
        elif self._active_section == "installed":
            await self._do_pkg_action("install", "installed")

    async def action_quick_remove(self):
        if self._active_section == "installed":
            await self._do_pkg_action("remove", "installed")

    async def action_quick_update(self):
        if self._active_section == "tools":
            await self._do_tool_action("update")
        elif self._active_section == "installed":
            await self._do_pkg_action("update", "installed")

    def _open_detail(self, section: str):
        asyncio.create_task(self._do_open_detail(section))

    async def _do_open_detail(self, section: str):
        name, mgr_str = self._get_cursor_row(section)
        if not name or not mgr_str:
            return
        pkg = await asyncio.to_thread(self._ps.get_package_detail, name, PackageManager(mgr_str))
        if pkg:
            self.app.push_screen(PackageDetailScreen(pkg, self._ps))

    async def _do_pkg_action(self, action: str, section: str):
        name, mgr_str = self._get_cursor_row(section)
        result = self._result(section)
        if not name or not mgr_str:
            result.update("[bold red]No package selected — use ↑↓ to select one first[/bold red]")
            return
        mgr = PackageManager(mgr_str)
        labels = {
            "install": ("📥 Installing", "Install"),
            "remove": ("🗑 Removing", "Remove"),
            "update": ("🔄 Updating", "Update"),
        }
        emoji, title = labels[action]
        try:
            result.update(f"[yellow]{emoji} {title} {name}...[/yellow]")
            ok = await asyncio.to_thread(getattr(self._ps, action), name, mgr)
            icon = "✓" if ok else "✗"
            result.update(f"[bold]{icon} {title} {'succeeded' if ok else 'failed'} ({name})[/bold]")
            if ok:
                if action == "install":
                    self._mark_installed(name, mgr)
                elif action == "remove":
                    self._mark_removed(name, mgr)
        except Exception as e:
            result.update(f"[bold red]Error: {e}[/bold red]")

    async def _do_tool_action(self, action: str):
        name, mgr_str = self._get_cursor_row("tools")
        result = self._result("tools")
        if not name or not mgr_str or mgr_str == "system":
            result.update("[bold red]No installable tool selected (no system package manager found)[/bold red]")
            return
        mgr = PackageManager(mgr_str)
        labels = {"install": ("📥 Installing", "Install"), "update": ("🔄 Updating", "Update")}
        emoji, title = labels[action]
        try:
            result.update(f"[yellow]{emoji} {title} {name}...[/yellow]")
            ok = await asyncio.to_thread(getattr(self._ps, action), name, mgr)
            icon = "✓" if ok else "✗"
            result.update(f"[bold]{icon} {title} {'succeeded' if ok else 'failed'} ({name})[/bold]")
            if ok:
                self._tools = detect_tools()
                self.query_one("#tools-table", ToolsTable).show_tools(self._tools)
                self._update_tools_actions()
        except Exception as e:
            result.update(f"[bold red]Error: {e}[/bold red]")

    def _mark_installed(self, name, mgr):
        if (name, mgr) not in self._installed_set:
            self._installed_set.add((name, mgr))
            self._installed_pkgs.append(Package(name=name, manager=mgr))
        self._refresh_installed_view()

    def _mark_removed(self, name, mgr):
        self._installed_set.discard((name, mgr))
        self._installed_pkgs = [p for p in self._installed_pkgs if not (p.name == name and p.manager == mgr)]
        self._refresh_installed_view()

    def _refresh_installed_view(self):
        query = self.query_one("#installed-input", Input).value
        self._filter_installed(query)

    # ---------- action bar state ----------

    def _update_search_actions(self):
        name, mgr_str = self._get_cursor_row("search")
        bar = self.query_one("#search-action-bar", Horizontal)
        label = self.query_one("#search-sel", Static)
        if name and mgr_str:
            bar.display = True
            label.update(f"[bold]{name}[/bold] ({mgr_str})")
        else:
            bar.display = False

    def _update_installed_actions(self):
        name, mgr_str = self._get_cursor_row("installed")
        bar = self.query_one("#installed-action-bar", Horizontal)
        label = self.query_one("#installed-sel", Static)
        if name and mgr_str:
            bar.display = True
            label.update(f"[bold]{name}[/bold] ({mgr_str})")
        else:
            bar.display = False

    def _update_tools_actions(self):
        name, mgr_str = self._get_cursor_row("tools")
        bar = self.query_one("#tools-action-bar", Horizontal)
        label = self.query_one("#tools-sel", Static)
        if not name:
            bar.display = False
            return
        bar.display = True
        label.update(f"[bold]{name}[/bold]")
        installed_names = {t.name for t, st in self._tools if st}
        self.query_one("#btn-tools-install", Button).disabled = name in installed_names
        self.query_one("#btn-tools-update", Button).disabled = name not in installed_names
