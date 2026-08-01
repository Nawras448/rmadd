from textual.widgets import DataTable
from textual.containers import Vertical

from features.package_store.domain import PackageCollection, PackageStatus


class PackageTable(Vertical):
    can_focus = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "Packages"

    def compose(self):
        self._table = DataTable(id="inner-table", cursor_type="row", show_cursor=True, show_row_labels=False)
        yield self._table

    def show_packages(self, collection: PackageCollection):
        self._table.clear(columns=True)
        self._add_package_columns()
        seen = set()
        for pkg in collection:
            key = f"{pkg.name}|{pkg.manager.value}"
            if key in seen:
                continue
            seen.add(key)
            status_char = "✓" if pkg.status == PackageStatus.INSTALLED else "○"
            self._table.add_row(
                status_char, pkg.name, pkg.version or "—", pkg.arch or "—", pkg.manager.value,
                key=key
            )
        self._fit_columns(self._table.size.width)

    def on_resize(self, event):
        self._fit_columns(event.size.width)

    def _package_widths(self, width):
        available = max(20, width - 11)
        ver_w = max(8, available * 16 // 100)
        arch_w = max(6, available * 10 // 100)
        mgr_w = max(7, available * 16 // 100)
        name_w = max(10, available - 1 - ver_w - arch_w - mgr_w)
        return (1, name_w, ver_w, arch_w, mgr_w)

    def _fit_columns(self, width):
        dt = self._table
        if len(dt.columns) < 5:
            return
        for col, w in zip(dt.columns.values(), self._package_widths(width)):
            col.width = w
        dt.refresh()

    def _add_package_columns(self):
        labels = ("", "Name", "Version", "Arch", "Manager")
        for label, w in zip(labels, self._package_widths(self._table.size.width)):
            self._table.add_column(label, width=w)

    def show_counts(self, counts: dict):
        self._table.clear(columns=True)
        self._table.add_columns("Manager", "Count")
        for mgr, count in counts.items():
            self._table.add_row(mgr.upper(), str(count))
