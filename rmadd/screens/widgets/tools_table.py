from textual.widgets import DataTable
from textual.containers import Vertical

from rmadd.screens.widgets.package_table import apply_pane_floor


class ToolsTable(Vertical):
    can_focus = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._row_keys: list[str] = []
        self._row_cells: dict[str, list] = {}

    def compose(self):
        self._table = DataTable(id="inner-tools-table", cursor_type="row", show_cursor=True, show_row_labels=False)
        yield self._table

    def _wanted_rows(self, entries: list) -> list:
        wanted = []
        for tool, installed in entries:
            key = f"{tool.name}|{tool.manager.value if tool.manager else 'system'}"
            status = "✓ Installed" if installed else "✗ Not installed"
            wanted.append([key, ["✓" if installed else "✗", tool.display, status, tool.purpose]])
        return wanted

    def show_tools(self, entries: list):
        if len(self._table.columns) != 4:
            self._table.clear(columns=True)
            self._add_tool_columns()
            self._row_keys = []
            self._row_cells = {}
        wanted = self._wanted_rows(entries)
        wanted_keys = [w[0] for w in wanted]
        if wanted_keys == self._row_keys:
            for key, cells in wanted:
                stored = self._row_cells.get(key)
                if stored and stored != cells:
                    try:
                        for col, value in enumerate(cells):
                            self._table.update_cell(key, col, value)
                    except Exception:
                        pass
                    self._row_cells[key] = cells
        elif len(self._table.columns) == 4:
            self._table.clear()
            self._row_keys = []
            self._row_cells = {}
            for key, cells in wanted:
                self._table.add_row(*cells, key=key)
                self._row_keys.append(key)
                self._row_cells[key] = list(cells)
        else:
            return
        self._fit_columns(self._table.size.width)

    def on_resize(self, event):
        self._fit_columns(event.size.width)
        apply_pane_floor(self)

    def _tool_widths(self, width):
        available = max(20, width - 9)
        tool_w = max(8, available * 20 // 100)
        status_w = max(10, available * 20 // 100)
        purpose_w = max(10, available - 1 - tool_w - status_w)
        return (1, tool_w, status_w, purpose_w)

    def _fit_columns(self, width):
        dt = self._table
        if len(dt.columns) < 4:
            return
        for col, w in zip(dt.columns.values(), self._tool_widths(width)):
            col.width = w
        dt.refresh()

    def _add_tool_columns(self):
        labels = ("", "Tool", "Status", "Purpose")
        for label, w in zip(labels, self._tool_widths(self._table.size.width)):
            self._table.add_column(label, width=w)
