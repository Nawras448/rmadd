from rich.text import Text
from textual.widgets import DataTable
from textual.containers import Vertical

from features.package_store.domain import (
    PackageCollection,
    PackageManager,
    PackageStatus,
    PackageManagerTier,
    TIER_LABELS,
    TIER_ORDER,
    tier,
)

MIN_TABLE_ROWS = 10


def apply_pane_floor(table, min_rows: int = MIN_TABLE_ROWS):
    parent = table.parent
    if parent is None:
        return
    try:
        fixed = sum(w.region.height for w in parent.children if w is not table and w.display)
        floor = max(min_rows, parent.region.height - fixed)
    except Exception:
        return
    want = str(floor)
    if table.styles.height != want:
        table.styles.height = want

TIER_STYLES = {
    PackageManagerTier.NATIVE: "bold #22c55e",
    PackageManagerTier.UNIVERSAL: "#22d3ee",
    PackageManagerTier.ECOSYSTEM: "#a78bfa",
}


def tier_tag(manager: PackageManager) -> Text:
    mgr_tier = tier(manager)
    return Text(
        f"{manager.value} [{TIER_LABELS[mgr_tier]}]",
        style=TIER_STYLES[mgr_tier],
    )


def _sort_key(pkg) -> tuple:
    return (TIER_ORDER[tier(pkg.manager)], pkg.manager.value, pkg.name)


class PackageTable(Vertical):
    can_focus = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "Packages"
        self._row_keys: list[str] = []
        self._row_cells: dict[str, list] = {}

    def compose(self):
        self._table = DataTable(id="inner-table", cursor_type="row", show_cursor=True, show_row_labels=False)
        yield self._table

    def _wanted_rows(self, collection: PackageCollection) -> list:
        wanted = []
        seen = set()
        for pkg in sorted(collection, key=_sort_key):
            key = f"{pkg.name}|{pkg.manager.value}"
            if key in seen:
                continue
            seen.add(key)
            status_char = "✓" if pkg.status == PackageStatus.INSTALLED else "○"
            wanted.append(
                [key, [status_char, pkg.name, pkg.version or "—", pkg.arch or "—", tier_tag(pkg.manager)]]
            )
        return wanted

    def show_packages(self, collection: PackageCollection):
        if len(self._table.columns) != 5:
            self._table.clear(columns=True)
            self._add_package_columns()
            self._row_keys = []
            self._row_cells = {}
        wanted = self._wanted_rows(collection)
        wanted_keys = [w[0] for w in wanted]
        if wanted_keys == self._row_keys:
            for key, cells in wanted:
                stored = self._row_cells.get(key)
                if stored and stored != cells:
                    try:
                        row_index = self._table.get_row_index(key)
                        for col, value in enumerate(cells):
                            self._table.update_cell(key, col, value)
                    except Exception:
                        pass
                    self._row_cells[key] = cells
        elif len(self._table.columns) == 5:
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

    def _package_widths(self, width):
        available = max(20, width - 11)
        ver_w = max(8, available * 16 // 100)
        arch_w = max(6, available * 10 // 100)
        mgr_w = max(10, available * 22 // 100)
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
        self._row_keys = []
        self._row_cells = {}
        self._table.add_columns("Manager", "Count")
        ordered = []
        for key, count in counts.items():
            try:
                mgr = PackageManager(key)
                rank = TIER_ORDER[tier(mgr)]
                label = tier_tag(mgr)
            except ValueError:
                rank = 99
                label = Text(key)
            ordered.append((rank, key, label, count))
        ordered.sort(key=lambda item: (item[0], item[1]))
        for _rank, _key, label, count in ordered:
            self._table.add_row(label, str(count))
