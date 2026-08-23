from textual.containers import Vertical
from textual.widgets import DataTable

from rmadd.screens.widgets.package_table import (
    ResponsiveMixin,
    apply_pane_floor,
)


class ToolsTable(ResponsiveMixin, Vertical):
    can_focus = False

    _COL_LABELS = ("", "Tool", "Status", "Purpose")
    _RESPONSIVE_TIERS = (
        (78, (0, 1, 2, 3)),
        (0, (0, 1, 2)),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._row_keys: list[str] = []
        self._row_cells: dict[str, list] = {}
        self._init_responsive(len(self._COL_LABELS))
        self._pkg_column_keys = None
        self._cols_ready = False

    _table: DataTable

    def compose(self):
        self._table = DataTable(id="inner-tools-table", cursor_type="row", show_cursor=True, show_row_labels=False)
        yield self._table

    def _capture_cursor(self):
        try:
            coord = self._table.cursor_coordinate
            if coord is None or self._table.row_count == 0:
                return (None, -1)
            return (self._table.coordinate_to_cell_key(coord).row_key.value, coord.row)
        except Exception:
            return (None, -1)

    def _restore_cursor(self, prev_key, prev_row: int):
        count = self._table.row_count
        if count == 0:
            return
        target = None
        if prev_key:
            try:
                target = self._table.get_row_index(prev_key)
            except Exception:
                target = None
        if target is None or not 0 <= target < count:
            base = prev_row if isinstance(prev_row, int) and prev_row >= 0 else 0
            target = min(base, count - 1)
        try:
            from textual.coordinate import Coordinate

            self._table.cursor_coordinate = Coordinate(target, 0)
        except Exception:
            pass

    def _project(self, display: list) -> list:
        return [display[i] for i in self._active_indices]

    def _display_cells(self, key: str, base: list) -> list:
        """No status overrides on the tools table."""
        return list(base)

    def _wanted_rows(self, entries: list) -> list:
        wanted = []
        for tool, installed in entries:
            key = f"{tool.name}|{tool.manager.value if tool.manager else 'system'}"
            status = "✓ Installed" if installed else "✗ Not installed"
            wanted.append([key, ["✓" if installed else "✗", tool.display, status, tool.purpose]])
        return wanted

    def show_tools(self, entries: list):
        expected = len(self._active_indices)
        if not self._cols_ready or len(self._table.columns) != expected:
            self._table.clear(columns=True)
            self._rebuild_columns(self._active_indices, 80)
        wanted = self._wanted_rows(entries)
        wanted_keys = [w[0] for w in wanted]
        if wanted_keys == self._row_keys:
            for key, cells in wanted:
                stored = self._row_cells.get(key)
                if stored and stored != cells:
                    try:
                        for col_key, value in zip(self._pkg_column_keys, self._project(cells)):
                            self._table.update_cell(key, col_key, value)
                    except Exception:
                        pass
                    self._row_cells[key] = list(cells)
        elif self._cols_ready and len(self._table.columns) == expected:
            self._table.clear()
            self._row_keys = []
            self._row_cells = {}
            for key, cells in wanted:
                try:
                    self._table.add_row(*self._project(cells), key=key)
                except Exception:
                    continue
                self._row_keys.append(key)
                self._row_cells[key] = list(cells)
        else:
            return
        self._tune_widths(self._table.size.width)

    def _rebuild_columns(self, indices: tuple[int, ...], width: int):
        dt = self._table
        rows = [(k, self._row_cells[k]) for k in list(self._row_keys)]
        dt.clear(columns=True)
        widths = self._tool_widths(max(20, int(width)))
        for i in indices:
            dt.add_column(self._COL_LABELS[i], width=max(1, widths[i]))
        self._active_indices = tuple(indices)
        self._pkg_column_keys = list(dt.columns.keys())
        self._cols_ready = True
        for key, base in rows:
            try:
                dt.add_row(*self._project(base), key=key)
            except Exception:
                pass

    def _flush_resize(self):
        super()._flush_resize()
        apply_pane_floor(self)

    def _tool_widths(self, width):
        available = max(20, width - 9)
        tool_w = max(8, available * 20 // 100)
        status_w = max(10, available * 20 // 100)
        purpose_w = max(10, available - 1 - tool_w - status_w)
        return (1, tool_w, status_w, purpose_w)

    def _tune_widths(self, width: int):
        dt = self._table
        if not self._cols_ready:
            return
        widths = self._tool_widths(max(20, int(width)))
        subset = [widths[i] for i in self._active_indices]
        try:
            for col_key, w in zip(self._pkg_column_keys, subset):
                dt.columns[col_key].width = w
            dt.refresh()
        except Exception:
            pass
