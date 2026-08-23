"""StoreScreen: composition root wiring tab controllers to the widget tree.

Layout, bindings and event routing live here; domain behavior lives in
rmadd/controllers/* (stats, tools, local binaries, installed, search,
operations). The screen owns task tracking, the state-bus subscription and
thread marshalling, and delegates everything else.
"""

import asyncio

from textual.containers import Horizontal, VerticalScroll
from textual.coordinate import Coordinate
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Static,
    Tab,
    TabbedContent,
    TabPane,
    Tabs,
)

from rmadd import __version__
from rmadd.controllers.installed_controller import InstalledController
from rmadd.controllers.local_binaries_controller import LocalBinariesController
from rmadd.controllers.operations_controller import OperationsController
from rmadd.controllers.search_controller import SearchController
from rmadd.controllers.stats_controller import StatsController
from rmadd.controllers.tools_controller import ToolsController
from rmadd.models import PackageManager, supports
from rmadd.screens.package_detail_screen import PackageDetailScreen
from rmadd.screens.widgets.package_table import PackageTable, apply_pane_floor
from rmadd.screens.widgets.system_card import SystemCard
from rmadd.screens.widgets.tools_table import ToolsTable
from rmadd.ui_keys import decode_key as decode_row_key


class StoreScreen(Screen):
    def __init__(self, system_service, package_service):
        super().__init__()
        self._ss = system_service
        self._ps = package_service
        self._tasks: list[asyncio.Task] = []
        self._active_section = "search"
        self._stats_interval = None
        self.rebuild_lock = asyncio.Lock()
        self._confirm_removal: bool | None = None

        # Controllers (ops last: others reach it late-bound via ui.ops).
        self.stats = StatsController(self)
        self.tools = ToolsController(self)
        self.local_bin = LocalBinariesController(self)
        self.installed = InstalledController(self)
        self.search = SearchController(self)
        self.ops = OperationsController(self)

    @property
    def ps(self):
        return self._ps

    @property
    def ss(self):
        return self._ss

    @property
    def opt(self):
        return self.ops.state

    @property
    def optimistic(self):
        return self.ops.state

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
        ("escape", "cancel_search", "Cancel search"),
        ("question_mark", "show_help", "Help"),
    ]

    def compose(self):
        yield Header(show_clock=True)
        with Horizontal(id="store-topbar"):
            yield Static(f"rmadd v{__version__}", id="store-title")
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
                    yield Static("", id="search-status-chip", classes="search-chip")
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

    # ---------- shared UI helpers (controller-facing) ----------

    @property
    def active_section(self) -> str:
        return self._active_section

    def track(self, coro) -> asyncio.Task:
        self._tasks = [t for t in self._tasks if not t.done()]
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task

    def table_for(self, section: str):
        if section == "search":
            return self.query_one("#search-table", PackageTable)
        if section == "installed":
            return self.query_one("#installed-table", PackageTable)
        if section == "local":
            return self.query_one("#local-table", PackageTable)
        return self.query_one("#tools-table", ToolsTable)

    def cursor(self, section: str) -> tuple:
        dt = self.table_for(section)._table
        coord = dt.cursor_coordinate
        if coord is None or coord.row >= dt.row_count:
            return ("", "")
        cell_key = dt.coordinate_to_cell_key(coord)
        return decode_row_key(cell_key.row_key.value)

    def move_cursor_first_row(self, table):
        dt = table._table
        if dt.row_count > 0:
            try:
                dt.cursor_coordinate = Coordinate(0, 0)
            except Exception:
                pass

    def result(self, section: str) -> Static:
        ids = {
            "tools": "#tools-result",
            "search": "#search-result",
            "installed": "#installed-result",
            "local": "#local-result",
        }
        return self.query_one(ids[section], Static)

    def auto_scroll_result(self, section: str):
        self.query_one(f"#{section}-result-scroll").scroll_end(animate=False)

    # ---------- modal plumbing (focus capture / restoration) ----------

    def push_modal(self, screen, on_dismiss=None) -> None:
        """Push a modal, remembering focus and restoring it on dismissal.

        ``on_dismiss(result)`` runs after focus restoration so any modal it
        pushes itself captures the restored focus.
        """
        prev = getattr(self.app, "focused", None)

        def _restore(_result=None):
            if prev is not None:
                try:
                    if prev.is_mounted:
                        prev.focus()
                    else:
                        self.focus_active_section()
                except Exception:
                    self.focus_active_section()
            else:
                self.focus_active_section()
            if on_dismiss is not None:
                on_dismiss(_result)

        self.app.push_screen(screen, _restore)

    @property
    def confirm_removal(self) -> bool:
        """Opt-in removal confirmation (Config `ui.confirm_removal`)."""
        if self._confirm_removal is None:
            try:
                from rmadd.config import Config

                self._confirm_removal = bool(Config().confirm_removal)
            except Exception:
                self._confirm_removal = False
        return self._confirm_removal

    @confirm_removal.setter
    def confirm_removal(self, value) -> None:
        self._confirm_removal = bool(value)

    def focus_active_section(self):
        try:
            if self.active_section == "search":
                self.query_one("#search-input").focus()
            else:
                self.table_for(self.active_section)._table.focus()
        except Exception:
            pass

    def action_cancel_search(self):
        """Esc on the main screen: cancel/clear the live search (search tab)."""
        if self._active_section != "search":
            return
        self.search.cancel()
        self.focus_active_section()

    def action_show_help(self):
        from rmadd.screens.help_overlay import HelpOverlay

        self.push_modal(HelpOverlay())

    # ---------- lifecycle ----------

    async def on_mount(self):
        self.tools.load_initial()
        self.search.update_actions()
        self.installed.update_actions()
        self.track(self.installed.load())
        self.track(self.stats.load())
        self._stats_interval = self.set_interval(5.0, lambda: self.track(self.stats.load()))
        self.app.state_bus.subscribe(self._on_state_event_safe)

    def on_unmount(self):
        for task in self._tasks:
            if not task.done():
                task.cancel()
        self.search.cancel_debounce()
        self.installed.cancel_filter()
        if self._stats_interval is not None:
            self._stats_interval.stop()
        self.local_bin.shutdown()
        self.app.state_bus.unsubscribe(self._on_state_event_safe)

    def on_resize(self, event):
        for section in ("tools", "search", "installed", "local"):
            try:
                apply_pane_floor(self.table_for(section))
            except Exception:
                pass

    # ---------- state-bus marshalling ----------

    def _on_state_event_safe(self, kind: str, name: str, mgr: PackageManager, phase: str = "confirmed"):
        """Marshal bus events onto the TUI event loop.

        Emitters live on two threads: the UI thread (modal confirm/revert,
        AppImage finish) and pool workers (installed-refresh). Textual's
        call_from_thread refuses same-thread calls with RuntimeError, so
        dispatch inline in that case instead of dropping the event.
        """
        try:
            self.app.call_from_thread(self.ops.on_bus_event, kind, name, mgr, phase)
            return
        except RuntimeError:
            pass  # already on the app thread
        except Exception:
            return  # app shutting down
        try:
            self.ops.on_bus_event(kind, name, mgr, phase)
        except Exception:
            pass

    # ---------- events ----------

    def on_input_submitted(self, event: Input.Submitted):
        if event.input.id == "search-input":
            self.search.submitted(event.value)

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "installed-input":
            self.installed.schedule_filter(event.value)
        elif event.input.id == "search-input":
            self.search.schedule_live(event.value)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted):
        parent_id = event.data_table.parent.id
        if parent_id == "search-table":
            self.search.update_actions()
        elif parent_id == "installed-table":
            self.installed.update_actions()
        elif parent_id == "local-table":
            self.local_bin.update_actions()
        elif parent_id == "tools-table":
            self.tools.update_actions()

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
            self.installed.handle_tab_activated(event.tab.id)
        elif event.tabs.id == "search-filter-tabs":
            self.search.handle_tab(event.tab.id)

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-tools-install":
            self.track(self.tools.run_action("install"))
        elif bid == "btn-tools-update":
            self.track(self.tools.run_action("update"))
        elif bid == "btn-tools-appimage":
            self.tools.open_appimage()
        elif bid == "btn-search-install":
            self.track(self._do_pkg_action("install", "search"))
        elif bid == "btn-search-remove":
            self.track(self._do_pkg_action("remove", "search"))
        elif bid == "btn-search-update":
            self.track(self._do_pkg_action("update", "search"))
        elif bid == "btn-search-details":
            self._open_detail("search")
        elif bid == "btn-installed-remove":
            self.track(self._do_pkg_action("remove", "installed"))
        elif bid == "btn-installed-update":
            self.track(self._do_pkg_action("update", "installed"))
        elif bid == "btn-installed-details":
            self._open_detail("installed")
        elif bid == "btn-local-remove":
            self.track(self._do_pkg_action("remove", "local"))

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated):
        section = event.pane.id.removeprefix("pane-")
        self._active_section = section
        from textual.widgets._tabs import Tabs as _Tabs
        from textual.widgets._tabs import Underline

        tabs_widget = self.query_one(TabbedContent).query_one(_Tabs)
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
            self.track(self.local_bin.load())
            self.query_one("#local-table")._table.focus()
        elif section == "about":
            self.track(self.stats.load())
            self.query_one("#package-table")._table.focus()
        else:
            if self.installed.should_reload():
                self.track(self.installed.load())
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
            await self.tools.run_action("install")
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
            await self.tools.run_action("update")
        elif self._active_section == "installed":
            await self._do_pkg_action("update", "installed")
        elif self._active_section == "search":
            await self._do_pkg_action("update", "search")

    # ---------- detail & operations glue ----------

    def _open_detail(self, section: str):
        self.track(self._do_open_detail(section))

    async def _do_open_detail(self, section: str):
        if not self.is_mounted:
            return
        name, mgr_str = self.cursor(section)
        if not name or not mgr_str:
            return
        mgr = PackageManager(mgr_str)
        if mgr == PackageManager.LOCAL:
            pkg = await asyncio.to_thread(self.local_bin.adapter.get_info, name)
            installed = True
        else:
            pkg = await asyncio.to_thread(self._ps.get_package_detail, name, mgr)
            installed = self.optimistic.is_installed(name, mgr)
        if pkg:
            self.push_modal(
                PackageDetailScreen(
                    pkg,
                    self._ps,
                    is_installed=installed,
                    confirm_remove=self.confirm_removal,
                )
            )

    async def _do_pkg_action(self, action: str, section: str):
        if section == "local":
            await self.local_bin.ensure_loaded()
        name, mgr_str = self.cursor(section)
        result = self.result(section)
        if not name or not mgr_str:
            result.update("[bold red]No package selected — use ↑↓ to select one first[/bold red]")
            return
        mgr = PackageManager(mgr_str)
        if self.optimistic.pending_action(name, mgr) is not None:
            result.update(f"[yellow]An operation is already running for {name}[/yellow]")
            return
        if section == "search":
            installed = self.optimistic.is_installed(name, mgr)
            if action == "install" and installed:
                result.update("[yellow]Already installed — use Remove/Update instead[/yellow]")
                return
            if action in ("remove", "update") and not installed:
                result.update("[bold red]Not installed — use Install instead[/bold red]")
                return
        if action == "remove" and self.confirm_removal:
            from rmadd.screens.confirm_remove import ConfirmRemoveScreen

            def _after_confirmed(confirmed):
                if confirmed:
                    self._begin_removal(section, name, mgr)
                else:
                    self.result(section).update(
                        f"[yellow]Removal of {name} cancelled[/yellow]"
                    )

            self.push_modal(ConfirmRemoveScreen(name, mgr), _after_confirmed)
            return
        if action == "remove":
            self._begin_removal(section, name, mgr)
            return
        self.ops.start(action, section, name, mgr)

    def _begin_removal(self, section: str, name: str, mgr):
        self.ops.remove_instantly(section, name, mgr)
        self.ops.start("remove", section, name, mgr)

    def on_operation_finished(
        self,
        action: str,
        section: str,
        name: str,
        mgr: PackageManager,
        ok: bool,
        cancelled: bool,
        result=None,
    ):
        from rmadd.screens import op_feedback

        pane = self.result(section)
        label = action.title()
        if cancelled:
            pane.update(f"[bold red]✗ {label} cancelled ({name})[/bold red]")
        elif ok:
            pane.update(f"[bold green]✓ {label} succeeded ({name})[/bold green]")
        else:
            pane.update(op_feedback.failure_line(action, name, result))
        op_feedback.apply(self, action, name, mgr, result, cancelled)
        self.auto_scroll_result(section)
        if section == "tools":
            self.tools.refresh_after_op()
        elif section == "local" and ok and action == "remove":
            self.track(self.local_bin.load(force=True))

    # ---------- compatibility shims (tui.action_refresh) ----------

    def _refresh_stats(self):
        self.track(self.stats.load())

    async def _rediscover_managers(self):
        await self.ops.rediscover_managers()
