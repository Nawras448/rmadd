from textual.widgets import DataTable
from textual.containers import Vertical


class ToolsTable(Vertical):
    can_focus = False

    def compose(self):
        self._table = DataTable(id="inner-tools-table", cursor_type="row", show_cursor=True, show_row_labels=False)
        yield self._table

    def show_tools(self, entries: list):
        self._table.clear(columns=True)
        self._add_tool_columns()
        for tool, installed in entries:
            mgr = tool.manager.value if tool.manager else "system"
            status = "✓ Installed" if installed else "✗ Not installed"
            self._table.add_row(
                "✓" if installed else "✗",
                tool.display,
                status,
                tool.purpose,
                key=f"{tool.name}|{mgr}",
            )
        self._fit_columns(self._table.size.width)

    def on_resize(self, event):
        self._fit_columns(event.size.width)

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
