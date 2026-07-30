from textual.widgets import DataTable
from textual.containers import Vertical

from features.package_store.domain import PackageCollection, PackageStatus


class PackageTable(Vertical):
    can_focus = False

    def compose(self):
        self._table = DataTable(id="inner-table", cursor_type="row", show_cursor=True)
        yield self._table

    def show_packages(self, collection: PackageCollection):
        self._table.clear()
        self._table.add_columns("", "Name", "Version", "Arch", "Manager")
        for pkg in collection:
            status_char = "✓" if pkg.status == PackageStatus.INSTALLED else "○"
            self._table.add_row(
                status_char, pkg.name, pkg.version or "—", pkg.arch or "—", pkg.manager.value,
                key=f"{pkg.name}|{pkg.manager.value}"
            )

    def show_counts(self, counts: dict):
        self._table.clear()
        self._table.add_columns("Manager", "Count")
        for mgr, count in counts.items():
            self._table.add_row(mgr.upper(), str(count))
