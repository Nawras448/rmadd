import asyncio
import time

from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Input, DataTable, Button, Tab, TabbedContent, TabPane, Tabs
from textual.containers import Horizontal, VerticalScroll
from textual.coordinate import Coordinate

from rmadd.screens.package_detail_screen import PackageDetailScreen
from rmadd.screens.install_progress_screen import InstallProgressScreen
from rmadd.screens.appimage_install_screen import AppImageInstallScreen
from rmadd.screens.widgets.package_table import PackageTable, apply_pane_floor
from rmadd.screens.widgets.tools_table import ToolsTable
from rmadd.tools import detect_tools
from rmadd.screens.widgets.system_card import SystemCard
from rmadd.models import (
    PackageManager,
    PackageStatus,
    Package,
    PackageCollection,
    supports,
)
from rmadd.logging import get_logger

logger = get_logger("store_screen")


class StoreScreen(Screen):
    def __init__(self, system_service, package_service):
        super().__init__()
        self._ss = system_service
        self._ps = package_service
        self._search_managers: set[PackageManager] | None = None
        self._installed_managers: set[PackageManager] | None = None
        self._installed_pkgs: list[Package] = []
        self._installed_set: set[tuple[str, PackageManager]] = set()
        self._pending_ops: dict[tuple[str, PackageManager], str] = {}
        self._removal_stash: dict[tuple[str, PackageManager], tuple[Package, int]] = {}
        self._tools: list = []
        self._active_section = "search"
        self._search_gen = 0
        self._search_query = ""
        self._debounce_task: asyncio.Task | None = None
        self._filter_task: asyncio.Task | None = None
        self._tasks: list[asyncio.Task] = []
        self._local_adapter = None
        self._local_pkgs: list[Package] = []
        self._stats_interval = None
        self._stats_busy = False
        self._stats_loaded = False
        self._installed_busy = False
        self._installed_loaded = False
        self._installed_loaded_at = 0.0
        self._rediscovering = False
        self._rebuild_lock = asyncio.Lock()

    BINDINGS = [
        ("enter", "select", "Details"),
        ("i", "quick_install", "Install"),
        ("r", "quick_remove", "Remove"),
        ("u", "quick_update", "Update"),
        ("f1", "tab_tools", "Tools"),
        ("f2", "tab_search", "Search"),
        ("f3", "tab_installed", "Installed"),
        ("f4", "tab_local", "Local Binaries"),
        ("f5", "tab_about", "About"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        with Horizontal(id="store-topbar"):
            yield Static("rmadd v0.1.0", id="store-title")
        with TabbedContent(initial="pane-search", id="store-tabs"):
            with TabPane("Download Tools", id="pane-tools") as pane_tools:
                pane_tools.border_title = "Tools"
                with VerticalScroll(id="pane-scroll-tools"):
                    yield ToolsTable(id="tools-table")
                    with Horizontal(id="tools-action-bar"):
                        yield Static(id="tools-sel", classes="sel-label")
                        yield Button("Install", id="btn-tools-install", variant="primary")
                        yield Button("Update", id="btn-tools-update", variant="default")
                        yield Button("Install AppImage...", id="btn-tools-appimage", variant="default")
                    with VerticalScroll(id="tools-result-scroll", classes="result-scroll"):
                        yield Static(id="tools-result")

            with TabPane("Search Programs", id="pane-search") as pane_search:
                pane_search.border_title = "Search"
                with VerticalScroll(id="pane-scroll-search"):
                    with Horizontal(id="search-top"):
                        yield Input(placeholder="Search programs (as you type)...", id="search-input")
                    yield Tabs(
                        Tab("All", id="tab-all"),
                        *[
                            Tab(m.value.upper(), id=f"tab-{m.value}")
                            for m in self._ps.available_managers
                            if supports(m, "search")
                        ],
                        id="search-filter-tabs",
                        active="tab-all",
                    )
                    yield PackageTable(id="search-table")
                    with Horizontal(id="search-action-bar"):
                        yield Static(id="search-sel", classes="sel-label")
                        yield Static(id="search-status", classes="sel-label")
                        yield Button("Install", id="btn-search-install", variant="primary")
                        yield Button("Remove", id="btn-search-remove", variant="error")
                        yield Button("Update", id="btn-search-update", variant="default")
                        yield Button("Details", id="btn-search-details", variant="default")
                    with VerticalScroll(id="search-result-scroll", classes="result-scroll"):
                        yield Static(id="search-result")

            with TabPane("Installed Apps", id="pane-installed") as pane_installed:
                pane_installed.border_title = "Installed"
                with VerticalScroll(id="pane-scroll-installed"):
                    with Horizontal(id="installed-top"):
                        yield Input(placeholder="Search installed programs...", id="installed-input")
                    yield Tabs(
                        Tab("All", id="tab-all"),
                        *[
                            Tab(m.value.upper(), id=f"tab-{m.value}")
                            for m in self._ps.available_managers
                            if supports(m, "list_installed")
                        ],
                        id="installed-filter-tabs",
                        active="tab-all",
                    )
                    yield PackageTable(id="installed-table")
                    with Horizontal(id="installed-action-bar"):
                        yield Static(id="installed-sel", classes="sel-label")
                        yield Button("Remove", id="btn-installed-remove", variant="error")
                        yield Button("Update", id="btn-installed-update", variant="default")
                        yield Button("Details", id="btn-installed-details", variant="default")
                    with VerticalScroll(id="installed-result-scroll", classes="result-scroll"):
                        yield Static(id="installed-result")

            with TabPane("Local Binaries", id="pane-local") as pane_local:
                pane_local.border_title = "Local Binaries"
                with VerticalScroll(id="pane-scroll-local"):
                    yield PackageTable(id="local-table")
                    with Horizontal(id="local-action-bar"):
                        yield Static(id="local-sel", classes="sel-label")
                        yield Button("Remove", id="btn-local-remove", variant="error")
                    with VerticalScroll(id="local-result-scroll", classes="result-scroll"):
                        yield Static(id="local-result")

            with TabPane("About / Stats", id="pane-about") as pane_about:
                pane_about.border_title = "About"
                with VerticalScroll(id="pane-scroll-about"):
                    yield SystemCard(id="system-card")
                    yield PackageTable(id="package-table")
        yield Footer()

    # ---------- helpers ----------

    def _table_for(self, section: str):
        if section == "search":
            return self.query_one("#search-table", PackageTable)
        if section == "installed":
            return self.query_one("#installed-table", PackageTable)
        if section == "local":
            return self.query_one("#local-table", PackageTable)
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

    def _is_installed(self, name: str, mgr: PackageManager) -> bool:
        """Single source of truth for "is this package currently installed".

        Consults the optimistic state: a pending install counts as installed,
        a pending remove counts as not (so the Install button can re-appear).
        """
        key = (name, mgr)
        pending = self._pending_ops.get(key)
        if pending is not None:
            return pending != "remove"
        return key in self._installed_set

    def _installed_version_map(self) -> dict:
        """Map (name, mgr) -> version for all known installed packages that
        carry a version, used to enrich search results at render time."""
        return {
            (p.name, p.manager): p.version
            for p in self._installed_pkgs
            if p.version
        }

    def _move_cursor_first_row(self, table):
        dt = table._table
        if dt.row_count > 0:
            try:
                dt.cursor_coordinate = Coordinate(0, 0)
            except Exception:
                pass

    def _result(self, section: str) -> Static:
        ids = {
            "tools": "#tools-result",
            "search": "#search-result",
            "installed": "#installed-result",
            "local": "#local-result",
        }
        return self.query_one(ids[section], Static)

    # ---------- data loading ----------

    async def on_mount(self):
        self._tools = detect_tools()
        self.query_one("#tools-table", ToolsTable).show_tools(self._tools)
        self._update_tools_actions()
        self._update_search_actions()
        self._update_installed_actions()
        self._track(self._do_load_installed())
        self._track(self._load_stats())
        self._stats_interval = self.set_interval(5.0, self._on_stats_tick)
        self.app.state_bus.subscribe(self._on_state_event)

    def _track(self, coro) -> asyncio.Task:
        self._tasks = [t for t in self._tasks if not t.done()]
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task

    def on_unmount(self):
        for task in self._tasks:
            if not task.done():
                task.cancel()
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
        if self._filter_task and not self._filter_task.done():
            self._filter_task.cancel()
        if self._stats_interval is not None:
            self._stats_interval.stop()
        self.app.state_bus.unsubscribe(self._on_state_event)

    def on_resize(self, event):
        for section in ("tools", "search", "installed", "local"):
            try:
                apply_pane_floor(self._table_for(section))
            except Exception:
                pass

    def _on_stats_tick(self):
        if self.is_mounted:
            self._track(self._load_stats())

    async def _load_stats(self):
        if not self.is_mounted or self._stats_busy:
            return
        self._stats_busy = True
        try:
            card = self.query_one("#system-card", SystemCard)
            counts_table = self.query_one("#package-table", PackageTable)
            if not self._stats_loaded:
                card.update("[yellow]Fetching system info & package counts…[/yellow]")
                counts_table.show_counts({}, loading=True)
            self._ss.refresh()
            try:
                info = await asyncio.to_thread(self._ss.get_system_info)
                if self.is_mounted:
                    card.display_info(info)
            except Exception as e:
                logger.exception("get_system_info failed")
                if self.is_mounted:
                    card.update(f"[bold red]Error loading system info: {e}[/bold red]")
            try:
                counts = await asyncio.to_thread(self._ps.get_all_counts)
                if self.is_mounted:
                    counts_table.show_counts(counts)
            except Exception as e:
                logger.exception("get_all_counts failed")
                if self.is_mounted:
                    counts_table.show_counts({"error": str(e)})
            self._stats_loaded = True
        finally:
            self._stats_busy = False

    def _refresh_stats(self):
        self._track(self._load_stats())

    async def _do_load_installed(self, force: bool = False):
        if not self.is_mounted or self._installed_busy:
            return
        self._installed_busy = True
        try:
            result = self._result("installed")
            table = self.query_one("#installed-table", PackageTable)
            if not self._installed_loaded:
                result.update("[yellow]Loading installed packages…[/yellow]")
            try:
                pkgs = await asyncio.to_thread(self._ps.list_installed)
                if not self.is_mounted:
                    return
                self._installed_pkgs = list(pkgs)
                self._installed_set = {(p.name, p.manager) for p in self._installed_pkgs}
                self._installed_loaded = True
                self._installed_loaded_at = time.monotonic()
                self._show_installed(PackageCollection(self._installed_pkgs))
                if not force:
                    result.update(f"[green]Loaded {pkgs.total} installed packages[/green]")
                await self._rebuild_installed_tabs()
                if self._active_section == "installed":
                    table._table.focus()
                if self._search_query:
                    self._track(self._do_search(self._search_query, self._search_managers))
            except Exception as e:
                logger.exception("list_installed failed")
                if self.is_mounted:
                    result.update(f"[bold red]Error loading packages: {e}[/bold red]")
        finally:
            self._installed_busy = False

    async def _rebuild_installed_tabs(self):
        async with self._rebuild_lock:
            tabs = self.query_one("#installed-filter-tabs", Tabs)
            managers = [
                m
                for m in self._ps.available_managers
                if any(p.manager == m for p in self._installed_pkgs)
            ]
            current = {
                tab.id
                for tab in tabs.query("#tabs-list > Tab").results(Tab)
                if tab.id and tab.id != "tab-all"
            }
            wanted = {f"tab-{m.value}" for m in managers}
            for tab_id in current - wanted:
                await tabs.remove_tab(tab_id)
            for m in managers:
                if f"tab-{m.value}" not in current:
                    await tabs.add_tab(Tab(m.value.upper(), id=f"tab-{m.value}"))
            active_id = tabs.active or "tab-all"
            if active_id == "tab-all":
                self._installed_managers = None
            else:
                self._installed_managers = {PackageManager(active_id.removeprefix("tab-"))}
            self._filter_installed(self.query_one("#installed-input", Input).value)

    async def _rebuild_search_tabs(self):
        async with self._rebuild_lock:
            tabs = self.query_one("#search-filter-tabs", Tabs)
            managers = [
                m for m in self._ps.available_managers if supports(m, "search")
            ]
            current = {
                tab.id
                for tab in tabs.query("#tabs-list > Tab").results(Tab)
                if tab.id and tab.id != "tab-all"
            }
            wanted = {f"tab-{m.value}" for m in managers}
            for tab_id in current - wanted:
                await tabs.remove_tab(tab_id)
            for m in managers:
                if f"tab-{m.value}" not in current:
                    await tabs.add_tab(Tab(m.value.upper(), id=f"tab-{m.value}"))
            if tabs.active is None:
                tabs.active = "tab-all"

    async def _rediscover_managers(self):
        if not self.is_mounted or self._rediscovering:
            return
        self._rediscovering = True
        try:
            from rmadd.package_managers.base import discover_managers
            found = await asyncio.to_thread(discover_managers)
            added = False
            for mgr, adapter in found:
                if self._ps.add_source(mgr, adapter):
                    added = True
            if added:
                self.app.state_bus.emit("managers_changed", "", None)
        finally:
            self._rediscovering = False

    async def _on_managers_changed(self):
        if not self.is_mounted:
            return
        await self._rebuild_search_tabs()
        await self._do_load_installed(force=True)
        await self._rebuild_installed_tabs()
        self._track(self._load_stats())
        if self._search_query:
            self._track(self._do_search(self._search_query, self._search_managers))

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

    def _schedule_filter(self, query: str):
        if self._filter_task and not self._filter_task.done():
            self._filter_task.cancel()
        self._filter_task = asyncio.create_task(self._delayed_filter(query))

    async def _delayed_filter(self, query: str):
        try:
            await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            return
        if not self.is_mounted:
            return
        self._filter_installed(query)

    def _show_local(self, collection: PackageCollection):
        table = self.query_one("#local-table", PackageTable)
        table.show_packages(collection)
        self._move_cursor_first_row(table)
        self._update_local_actions()

    async def _load_local(self, force: bool = False):
        if not self.is_mounted:
            return
        result = self._result("local")
        if self._local_adapter is None:
            from rmadd.package_managers.base import discover_local_scanner
            self._local_adapter = discover_local_scanner()
        if not force and self._local_pkgs:
            self._show_local(PackageCollection(self._local_pkgs))
            return
        try:
            result.update("[cyan]Scanning local binaries...[/cyan]")
            pkgs = await asyncio.to_thread(self._local_adapter.list_installed)
            if not self.is_mounted:
                return
            self._local_pkgs = list(pkgs)
            self._show_local(PackageCollection(self._local_pkgs))
            if pkgs:
                result.update(f"[green]Found {len(pkgs)} local binaries[/green]")
            else:
                result.update("[yellow]No local binaries found[/yellow]")
        except Exception as e:
            if self.is_mounted:
                result.update(f"[bold red]Error scanning local binaries: {e}[/bold red]")

    async def _do_search(self, query: str, managers=None):
        if not self.is_mounted:
            return
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
        if managers is None:
            manager_list = list(self._ps.default_search_managers())
        else:
            manager_list = list(managers)
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
        version_map = self._installed_version_map()
        for p in collection:
            if not p.version:
                p.version = version_map.get((p.name, p.manager), "")
            p.status = (
                PackageStatus.INSTALLED
                if self._is_installed(p.name, p.manager)
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
            self._track(self._do_search(event.value, self._search_managers))

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "installed-input":
            self._schedule_filter(event.value)
        elif event.input.id == "search-input":
            self._schedule_live_search(event.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        parent_id = event.data_table.parent.id
        if parent_id == "search-table":
            self._update_search_actions()
        elif parent_id == "installed-table":
            self._update_installed_actions()
        elif parent_id == "local-table":
            self._update_local_actions()
        elif parent_id == "tools-table":
            self._update_tools_actions()

    def on_data_table_row_selected(self, event: DataTable.RowSelected):
        parent_id = event.data_table.parent.id
        if parent_id == "package-table":
            return
        section = {
            "search-table": "search",
            "installed-table": "installed",
            "tools-table": "tools",
            "local-table": "local",
        }.get(parent_id, "installed")
        self._active_section = section
        self._open_detail(section)

    def on_tabs_tab_activated(self, event: Tabs.TabActivated):
        if event.tabs.id == "installed-filter-tabs":
            if event.tab.id == "tab-all":
                self._installed_managers = None
            else:
                self._installed_managers = {PackageManager(event.tab.id.removeprefix("tab-"))}
            self._filter_installed(self.query_one("#installed-input", Input).value)
        elif event.tabs.id == "search-filter-tabs":
            if event.tab.id == "tab-all":
                self._search_managers = None
            else:
                self._search_managers = {PackageManager(event.tab.id.removeprefix("tab-"))}
            if self._debounce_task and not self._debounce_task.done():
                self._debounce_task.cancel()
            self._track(
                self._do_search(self.query_one("#search-input", Input).value, self._search_managers)
            )

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-tools-install":
            self._track(self._do_tool_action("install"))
        elif bid == "btn-tools-update":
            self._track(self._do_tool_action("update"))
        elif bid == "btn-tools-appimage":
            self._open_appimage_install()
        elif bid == "btn-search-install":
            self._track(self._do_pkg_action("install", "search"))
        elif bid == "btn-search-remove":
            self._track(self._do_pkg_action("remove", "search"))
        elif bid == "btn-search-update":
            self._track(self._do_pkg_action("update", "search"))
        elif bid == "btn-search-details":
            self._open_detail("search")
        elif bid == "btn-installed-remove":
            self._track(self._do_pkg_action("remove", "installed"))
        elif bid == "btn-installed-update":
            self._track(self._do_pkg_action("update", "installed"))
        elif bid == "btn-installed-details":
            self._open_detail("installed")
        elif bid == "btn-local-remove":
            self._track(self._do_pkg_action("remove", "local"))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
        section = event.pane.id.removeprefix("pane-")
        self._active_section = section
        from textual.widgets._tabs import Tabs, Underline
        tabs_widget = self.query_one(TabbedContent).query_one(Tabs)
        underline = tabs_widget.query_one(Underline)
        underline.show_highlight = True
        span = event.tab.virtual_region.shrink(event.tab.styles.gutter).column_span
        underline.highlight_start = span[0]
        underline.highlight_end = span[1]
        if section == "tools":
            self.query_one("#tools-table")._table.focus()
        elif section == "search":
            self.query_one("#search-input").focus()
        elif section == "local":
            self._track(self._load_local())
            self.query_one("#local-table")._table.focus()
        elif section == "about":
            self._track(self._load_stats())
            self.query_one("#package-table")._table.focus()
        else:
            if not self._installed_loaded or time.monotonic() - self._installed_loaded_at > 15:
                self._track(self._do_load_installed())
            self.query_one("#installed-table")._table.focus()

    # ---------- keyboard actions ----------

    def action_tab_tools(self):
        self.query_one(TabbedContent).active = "pane-tools"

    def action_tab_search(self):
        self.query_one(TabbedContent).active = "pane-search"

    def action_tab_installed(self):
        self.query_one(TabbedContent).active = "pane-installed"

    def action_tab_local(self):
        self.query_one(TabbedContent).active = "pane-local"

    def action_tab_about(self):
        self.query_one(TabbedContent).active = "pane-about"

    def action_select(self):
        if self._active_section == "about":
            return
        self._open_detail(self._active_section)

    async def action_quick_install(self):
        if self._active_section == "about":
            return
        if self._active_section == "tools":
            await self._do_tool_action("install")
        elif self._active_section == "search":
            await self._do_pkg_action("install", "search")
        elif self._active_section == "installed":
            await self._do_pkg_action("install", "installed")

    async def action_quick_remove(self):
        if self._active_section == "about":
            return
        if self._active_section == "installed":
            await self._do_pkg_action("remove", "installed")
        elif self._active_section == "local":
            await self._do_pkg_action("remove", "local")
        elif self._active_section == "search":
            await self._do_pkg_action("remove", "search")

    async def action_quick_update(self):
        if self._active_section == "about":
            return
        if self._active_section == "tools":
            await self._do_tool_action("update")
        elif self._active_section == "installed":
            await self._do_pkg_action("update", "installed")
        elif self._active_section == "search":
            await self._do_pkg_action("update", "search")

    def _open_detail(self, section: str):
        self._track(self._do_open_detail(section))

    def _open_appimage_install(self):
        self.app.push_screen(
            AppImageInstallScreen(
                self._ps,
                on_finish=self._on_appimage_installed,
            )
        )

    def _on_appimage_installed(self, ok: bool, name: str):
        result = self._result("tools")
        if ok:
            result.update(f"[bold green]✓ AppImage installed: {name}[/bold green]")
            self.app.state_bus.emit("install", name, PackageManager.APPIMAGE)
            self._track(self._do_load_installed())
        else:
            result.update(f"[bold red]✗ AppImage install failed: {name}[/bold red]")
        self._auto_scroll_result("tools")

    async def _do_open_detail(self, section: str):
        if not self.is_mounted:
            return
        name, mgr_str = self._get_cursor_row(section)
        if not name or not mgr_str:
            return
        mgr = PackageManager(mgr_str)
        if mgr == PackageManager.LOCAL:
            pkg = await asyncio.to_thread(self._local_adapter.get_info, name)
            installed = True
        else:
            pkg = await asyncio.to_thread(self._ps.get_package_detail, name, mgr)
            installed = self._is_installed(name, mgr)
        if pkg:
            self.app.push_screen(PackageDetailScreen(pkg, self._ps, is_installed=installed))

    def _auto_scroll_result(self, section: str):
        self.query_one(f"#{section}-result-scroll").scroll_end(animate=False)

    def _start_operation(self, action: str, section: str, name: str, mgr: PackageManager):
        executor = None
        if section == "local":
            executor = lambda n, m, on_output, cancel: self._local_adapter.remove(n, on_output, cancel)
        self.app.state_bus.emit(action, name, mgr, phase="pending")
        self.app.push_screen(
            InstallProgressScreen(
                self._ps,
                action,
                name,
                mgr,
                on_finish=self._on_operation_finished,
                section=section,
                executor=executor,
            )
        )

    def _on_operation_finished(self, action: str, section: str, name: str, mgr: PackageManager, ok: bool, cancelled: bool):
        result = self._result(section)
        label = action.title()
        if cancelled:
            result.update(f"[bold red]✗ {label} cancelled ({name})[/bold red]")
            if action == "remove":
                self.notify(f"Remove cancelled ({name})", severity="warning")
        elif ok:
            result.update(f"[bold green]✓ {label} succeeded ({name})[/bold green]")
        else:
            result.update(f"[bold red]✗ {label} failed ({name})[/bold red]")
            if action == "remove":
                self.notify(f"Failed to remove {name} — it may still be present", severity="error")
        self._auto_scroll_result(section)
        if section == "tools":
            self._tools = detect_tools()
            self.query_one("#tools-table", ToolsTable).show_tools(self._tools)
            self._update_tools_actions()
        elif section == "local" and ok and action == "remove":
            self._track(self._load_local(force=True))

    async def _do_pkg_action(self, action: str, section: str):
        if section == "local" and self._local_adapter is None:
            await self._load_local()
        name, mgr_str = self._get_cursor_row(section)
        result = self._result(section)
        if not name or not mgr_str:
            result.update("[bold red]No package selected — use ↑↓ to select one first[/bold red]")
            return
        mgr = PackageManager(mgr_str)
        if section == "search":
            installed = self._is_installed(name, mgr)
            if action == "install" and installed:
                result.update("[yellow]Already installed — use Remove/Update instead[/yellow]")
                return
            if action in ("remove", "update") and not installed:
                result.update("[bold red]Not installed — use Install instead[/bold red]")
                return
        if action == "remove":
            self._remove_instantly(section, name, mgr)
        self._start_operation(action, section, name, mgr)

    def _remove_instantly(self, section: str, name: str, mgr: PackageManager):
        """Zero-latency optimistic removal: drop the row and all in-memory
        caches before any subprocess work. The original Package object is
        stashed so a failed removal can restore it verbatim."""
        key = (name, mgr)
        pkg = next((p for p in self._installed_pkgs if (p.name, p.manager) == key), None)
        if pkg is None:
            pkg = next((p for p in self._local_pkgs if (p.name, p.manager) == key), None)
        if pkg is None:
            pkg = Package(name=name, manager=mgr)
        source = self._installed_pkgs if key in self._installed_set else self._local_pkgs
        try:
            index = source.index(pkg)
        except ValueError:
            index = -1
        self._removal_stash[key] = (pkg, index)
        self._installed_set.discard(key)
        self._installed_pkgs = [p for p in self._installed_pkgs if (p.name, p.manager) != key]
        self._local_pkgs = [p for p in self._local_pkgs if (p.name, p.manager) != key]
        for table_id in ("installed-table", "local-table", "search-table"):
            try:
                self.query_one(f"#{table_id}", PackageTable).remove_package(name, mgr)
            except Exception:
                pass
        self._refresh_installed_view()
        self._fast_counts()
        self._update_search_actions()
        self._rerun_search()

    async def _do_tool_action(self, action: str):
        name, mgr_str = self._get_cursor_row("tools")
        result = self._result("tools")
        if not name or not mgr_str or mgr_str == "system":
            result.update("[bold red]No installable tool selected (no system package manager found)[/bold red]")
            return
        self._start_operation(action, "tools", name, PackageManager(mgr_str))

    # ---------- state bus ----------

    def _on_state_event(self, kind: str, name: str, mgr: PackageManager, phase: str = "confirmed"):
        if kind == "managers_changed":
            self._track(self._on_managers_changed())
            return
        if phase == "pending":
            self._register_pending(kind, name, mgr)
        elif phase == "reverted":
            self._track(self._revert_pending(kind, name, mgr))
        else:
            self._track(self._settle_confirmed(kind, name, mgr))

    def _register_pending(self, action: str, name: str, mgr: PackageManager):
        """Optimistic write: reflect the op in the UI instantly, before any
        subprocess result. The row is tinted with the pending glyph."""
        key = (name, mgr)
        self._pending_ops[key] = action
        if action == "install":
            if key not in self._installed_set:
                self._installed_set.add(key)
                self._installed_pkgs.append(
                    Package(name=name, manager=mgr, status=PackageStatus.PENDING)
                )
            self._refresh_installed_view()
            self._set_row_status("installed-table", name, mgr, PackageStatus.PENDING)
        elif action == "remove":
            pass
        elif action == "update":
            self._set_row_status("installed-table", name, mgr, PackageStatus.UPDATING)
        self._fast_counts()
        self._update_search_actions()

    async def _settle_confirmed(self, action: str, name: str, mgr: PackageManager):
        """Settle the optimistic write once the operation actually succeeded."""
        if not self.is_mounted:
            return
        key = (name, mgr)
        self._pending_ops.pop(key, None)
        self._clear_row_status_all(name, mgr)
        if action == "install":
            if key not in self._installed_set:
                self._installed_set.add(key)
                self._installed_pkgs.append(Package(name=name, manager=mgr))
            for p in self._installed_pkgs:
                if (p.name, p.manager) == key:
                    p.status = PackageStatus.INSTALLED
            self._refresh_installed_view()
            self._track(self._rebuild_installed_tabs())
            self._track(self._rediscover_managers())
        elif action == "remove":
            self._removal_stash.pop(key, None)
            self._installed_set.discard(key)
            self._installed_pkgs = [p for p in self._installed_pkgs if not (p.name == name and p.manager == mgr)]
            self._local_pkgs = [p for p in self._local_pkgs if not (p.name == name and p.manager == mgr)]
            for table_id in ("installed-table", "local-table", "search-table"):
                try:
                    self.query_one(f"#{table_id}", PackageTable).remove_package(name, mgr)
                except Exception:
                    pass
            self._refresh_installed_view()
            self._track(self._rebuild_installed_tabs())
        else:  # update
            for p in self._installed_pkgs:
                if (p.name, p.manager) == key:
                    p.status = PackageStatus.INSTALLED
            self._refresh_installed_view()
        self._ps.invalidate_counts()
        self._fast_counts()
        self._rerun_search()
        self._update_search_actions()

    async def _revert_pending(self, action: str, name: str, mgr: PackageManager):
        """Undo the optimistic write when the op failed or was cancelled.
        In-memory only; no subprocess rescan happens (error/cancel surfaces via
        the action-result message already emitted by the caller)."""
        if not self.is_mounted:
            return
        key = (name, mgr)
        self._pending_ops.pop(key, None)
        self._clear_row_status_all(name, mgr)
        if action == "install":
            self._installed_set.discard(key)
            self._installed_pkgs = [p for p in self._installed_pkgs if not (p.name == name and p.manager == mgr)]
            for table_id in ("installed-table", "search-table"):
                try:
                    self.query_one(f"#{table_id}", PackageTable).remove_package(name, mgr)
                except Exception:
                    pass
        elif action == "remove":
            pkg, index = self._removal_stash.pop(key, (None, -1))
            if pkg is None:
                pkg = Package(name=name, manager=mgr)
            self._installed_set.add(key)
            if pkg.manager == PackageManager.LOCAL:
                if not any((p.name, p.manager) == key for p in self._local_pkgs):
                    self._local_pkgs.insert(index if 0 <= index < len(self._local_pkgs) else len(self._local_pkgs), pkg)
                self._show_local(self._local_pkgs)
            else:
                if not any((p.name, p.manager) == key for p in self._installed_pkgs):
                    self._installed_pkgs.insert(index if 0 <= index < len(self._installed_pkgs) else len(self._installed_pkgs), pkg)
        else:  # update
            for p in self._installed_pkgs:
                if (p.name, p.manager) == key:
                    p.status = PackageStatus.INSTALLED
        self._refresh_installed_view()
        self._track(self._rebuild_installed_tabs())
        self._fast_counts()
        self._rerun_search()
        self._update_search_actions()

    def _clear_row_status_all(self, name: str, mgr: PackageManager):
        key = f"{name}|{mgr.value}"
        for table_id in ("installed-table", "search-table"):
            try:
                self.query_one(f"#{table_id}", PackageTable).clear_row_status(key)
            except Exception:
                pass

    def _set_row_status(self, table_id: str, name: str, mgr: PackageManager, status: PackageStatus):
        try:
            key = f"{name}|{mgr.value}"
            self.query_one(f"#{table_id}", PackageTable).set_row_status(key, status)
        except Exception:
            pass

    def _fast_counts(self):
        """Patch the counts table from the in-memory installed set only.

        Exact per-manager counts are reconciled later by the 5s stats tick,
        so an op does not trigger any subprocess call here."""
        counts: dict[str, int] = {}
        for _name, mgr in self._installed_set:
            counts[mgr.value] = counts.get(mgr.value, 0) + 1
        if not counts:
            return
        try:
            self.query_one("#package-table", PackageTable).show_counts(counts)
        except Exception:
            pass

    def _rerun_search(self):
        if self._search_query:
            self._track(self._do_search(self._search_query, self._search_managers))

    def _refresh_installed_view(self):
        query = self.query_one("#installed-input", Input).value
        self._filter_installed(query)

    # ---------- action bar state ----------

    def _update_search_actions(self):
        name, mgr_str = self._get_cursor_row("search")
        bar = self.query_one("#search-action-bar", Horizontal)
        label = self.query_one("#search-sel", Static)
        status = self.query_one("#search-status", Static)
        install_btn = self.query_one("#btn-search-install", Button)
        remove_btn = self.query_one("#btn-search-remove", Button)
        update_btn = self.query_one("#btn-search-update", Button)
        if name and mgr_str:
            bar.display = True
            mgr = PackageManager(mgr_str)
            installed = self._is_installed(name, mgr)
            label.update(f"[bold]{name}[/bold] ({mgr_str})")
            install_btn.display = not installed and supports(mgr, "install")
            remove_btn.display = installed and supports(mgr, "remove")
            update_btn.display = installed and supports(mgr, "update")
            status.update(
                "[bold green]✓ Already Installed[/bold green]"
                if installed
                else "[yellow]○ Available[/yellow]"
            )
        else:
            bar.display = False
        apply_pane_floor(self._table_for("search"))

    def _update_installed_actions(self):
        name, mgr_str = self._get_cursor_row("installed")
        bar = self.query_one("#installed-action-bar", Horizontal)
        label = self.query_one("#installed-sel", Static)
        if name and mgr_str:
            bar.display = True
            label.update(f"[bold]{name}[/bold] ({mgr_str})")
        else:
            bar.display = False
        apply_pane_floor(self._table_for("installed"))

    def _update_tools_actions(self):
        name, mgr_str = self._get_cursor_row("tools")
        bar = self.query_one("#tools-action-bar", Horizontal)
        label = self.query_one("#tools-sel", Static)
        if not name:
            bar.display = False
            apply_pane_floor(self._table_for("tools"))
            return
        bar.display = True
        label.update(f"[bold]{name}[/bold]")
        installed_names = {t.name for t, st in self._tools if st}
        self.query_one("#btn-tools-install", Button).disabled = name in installed_names
        self.query_one("#btn-tools-update", Button).disabled = name not in installed_names
        apply_pane_floor(self._table_for("tools"))

    def _update_local_actions(self):
        name, _mgr_str = self._get_cursor_row("local")
        bar = self.query_one("#local-action-bar", Horizontal)
        label = self.query_one("#local-sel", Static)
        if name:
            bar.display = True
            label.update(f"[bold]{name}[/bold]")
        else:
            bar.display = False
        apply_pane_floor(self._table_for("local"))
