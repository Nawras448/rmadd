import asyncio

from rich.text import Text
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.widgets import DataTable

from rmadd.models import (
    STATUS_GLYPH,
    TIER_LABELS,
    TIER_ORDER,
    PackageCollection,
    PackageManager,
    PackageManagerTier,
    PackageStatus,
    tier,
)
from rmadd.ui_keys import encode_key

MIN_TABLE_ROWS = 10

_DIM_STATUSES = (PackageStatus.PENDING, PackageStatus.UPDATING)

_RESIZE_DEBOUNCE_SECONDS = 0.12

# Progressive population (M4 search responsiveness): very large collections
# paint an immediate head slice, then an exclusive worker drains the rest in
# chunks so the event loop never stalls on a single massive insert.
_PROGRESSIVE_THRESHOLD = 800
_IMMEDIATE_ROWS = 400
_BULK_CHUNK = 300


class ResponsiveMixin:
    """Trailing-edge debounced width handling with column-tier switching.

    Subclasses declare ``_COL_LABELS`` and ``_RESPONSIVE_TIERS``
    (``(min_width, indices)`` descending) and implement ``_tune_widths(w)``,
    ``_rebuild_columns(indices, w)`` plus cursor helpers when applicable.
    """

    _COL_LABELS: tuple = ()
    _RESPONSIVE_TIERS: tuple = ()

    def _init_responsive(self, total: int):
        self._active_indices: tuple[int, ...] = tuple(range(total))
        self._pending_width: int | None = None
        self._resize_timer = None

    def _desired_indices(self, width: int) -> tuple[int, ...]:
        for min_width, indices in self._RESPONSIVE_TIERS:
            if width >= min_width:
                return indices
        return self._RESPONSIVE_TIERS[-1][1]

    def on_resize(self, event):
        self._pending_width = int(event.size.width)
        if self._resize_timer is None:
            self._resize_timer = self.set_timer(
                _RESIZE_DEBOUNCE_SECONDS, self._flush_resize
            )

    def _flush_resize(self):
        self._resize_timer = None
        width = self._pending_width
        self._pending_width = None
        if width is None:
            return
        self._apply_width(width)

    def _apply_width(self, width: int):
        desired = self._desired_indices(width)
        if tuple(desired) != tuple(self._active_indices):
            self._switch_profile(desired, width)
        else:
            self._tune_widths(width)

    def _switch_profile(self, indices: tuple[int, ...], width: int):
        prev = self._snapshot_rows()
        self._rebuild_columns(indices, width)
        self._restore_snapshot(prev)

    def _snapshot_rows(self):
        prev_key, prev_row = self._capture_cursor()
        rows = [
            (k, self._display_cells(k, self._row_cells[k]))
            for k in list(self._row_keys)
        ]
        return (prev_key, prev_row), rows

    def _restore_snapshot(self, snap):
        (prev_key, prev_row), rows = snap
        for key, display in rows:
            try:
                self._table.add_row(*self._project(display), key=key)
            except Exception:
                pass
        self._restore_cursor(prev_key, prev_row)

    def _project(self, display: list) -> list:
        return [display[i] for i in self._active_indices]


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


class PackageTable(ResponsiveMixin, Vertical):
    can_focus = False

    _COL_LABELS = ("", "Name", "Version", "Arch", "Manager")
    # width tiers: >=88 full; drop Arch; drop Arch+Version; glyph+Name only
    _RESPONSIVE_TIERS = (
        (88, (0, 1, 2, 3, 4)),
        (72, (0, 1, 2, 4)),
        (56, (0, 1, 4)),
        (0, (0, 1)),
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "Packages"
        self._row_keys: list[str] = []
        self._row_cells: dict[str, list] = {}
        self._row_status: dict[str, PackageStatus] = {}
        self._init_responsive(len(self._COL_LABELS))
        self._pkg_column_keys = list(self._active_indices)  # placeholder
        self._pkg_mode = False
        self._last_collection: PackageCollection | None = None
        self._bulk_pending: list[tuple[str, list]] = []
        self._bulk_gen = 0
        self._last_prev: tuple = (None, -1)

    _table: DataTable

    def compose(self):
        self._table = DataTable(id="inner-table", cursor_type="row", show_cursor=True, show_row_labels=False)
        yield self._table

    def _wanted_rows(self, collection: PackageCollection) -> list:
        """Base (undimmed) rows in display order; overrides apply glyph."""
        wanted = []
        seen = set()
        for pkg in sorted(collection, key=_sort_key):
            key = encode_key(pkg.name, pkg.manager)
            if key in seen:
                continue
            seen.add(key)
            status = self._row_status.get(key, pkg.status)
            cells = [
                STATUS_GLYPH.get(status, "\u2022"),
                pkg.name,
                pkg.version or "—",
                pkg.arch or "—",
                tier_tag(pkg.manager),
            ]
            wanted.append([key, cells])
        return wanted

    @staticmethod
    def _dim_cells(cells: list) -> list:
        """Render non-glyph cells dimmed while an optimistic op is in flight."""
        dimmed = []
        for cell in cells:
            plain = cell.plain if isinstance(cell, Text) else str(cell)
            dimmed.append(Text(plain, style="dim"))
        return dimmed

    def _display_cells(self, key: str, base: list) -> list:
        """Base cells rendered through any active status override."""
        status = self._row_status.get(key)
        if status is None:
            return list(base)
        cells = list(base)
        cells[0] = STATUS_GLYPH.get(status, "\u2022")
        if status in _DIM_STATUSES:
            cells = [cells[0]] + self._dim_cells(cells[1:])
        return cells

    def set_row_status(self, key: str, status: PackageStatus) -> None:
        """Override the status glyph (+dimming) for an existing row.

        Base cells stay pristine so clearing restores the package's own
        status rendering verbatim.
        """
        self._row_status[key] = status
        base = self._row_cells.get(key)
        if base is None:
            return
        display = self._project(self._display_cells(key, base))
        try:
            for col_key, value in zip(self._column_keys(), display):
                self._table.update_cell(key, col_key, value)
        except Exception:
            pass

    def clear_row_status(self, key: str) -> None:
        had = self._row_status.pop(key, None)
        base = self._row_cells.get(key)
        if had is not None and base is not None:
            display = self._project(self._display_cells(key, base))
            try:
                for col_key, value in zip(self._column_keys(), display):
                    self._table.update_cell(key, col_key, value)
            except Exception:
                pass

    def show_packages(self, collection: PackageCollection):
        self._last_collection = collection
        prev_key, prev_row = self._capture_cursor()
        expected = len(self._active_indices)
        if not self._pkg_mode or len(self._table.columns) != expected:
            self._table.clear(columns=True)
            self._build_columns(self._active_indices)
            self._row_keys = []
            self._row_cells = {}
            self._row_status = {}
        wanted = self._wanted_rows(collection)
        wanted_keys = [w[0] for w in wanted]

        progressive = bool(
            self._pkg_mode and len(wanted) > _PROGRESSIVE_THRESHOLD
        )
        if progressive:
            # Supersede any running bulk flush, paint the head instantly and
            # stream the remainder through an exclusive batched worker.
            self._bulk_gen += 1
            self._bulk_pending = []
            head = wanted[:_IMMEDIATE_ROWS]
            self._reset_rows(head)
            self._bulk_pending = wanted[_IMMEDIATE_ROWS:]
            gen = self._bulk_gen
            self._last_prev = (prev_key, prev_row)
            try:
                self.run_worker(
                    self.drain_bulk(gen),
                    group="bulk-" + str(id(self)),
                    exclusive=True,
                    thread=False,
                )
            except Exception:
                self._drain_bulk_blocking()
        elif self._pkg_mode and wanted_keys != self._row_keys:
            self._reconcile_rows(wanted)
        elif self._pkg_mode:
            for key, base in wanted:
                stored = self._row_cells.get(key)
                if stored is not None and stored != base:
                    self._write_row(key, base)
                else:
                    self._row_cells[key] = list(base)

        self._apply_width(max(20, int(self._table.size.width)))
        self._restore_cursor(prev_key, prev_row)

    def _reset_rows(self, wanted_head: list):
        """Synchronous clean slate + immediate head insertion."""
        dt = self._table
        expected = len(self._active_indices)
        if not self._pkg_mode or len(dt.columns) != expected:
            dt.clear(columns=True)
            self._build_columns(self._active_indices)
            self._row_status = {}
        else:
            dt.clear()
        self._row_keys = []
        self._row_cells = {}
        for key, base in wanted_head:
            display = self._project(self._display_cells(key, base))
            try:
                dt.add_row(*display, key=key)
            except Exception:
                continue
            self._row_keys.append(key)
            self._row_cells[key] = list(base)

    def _bulk_step(self) -> bool:
        """Insert the next chunk of deferred rows. True when more remain."""
        chunk = self._bulk_pending[:_BULK_CHUNK]
        del self._bulk_pending[:_BULK_CHUNK]
        dt = self._table
        for key, base in chunk:
            display = self._project(self._display_cells(key, base))
            try:
                dt.add_row(*display, key=key)
            except Exception:
                continue
            self._row_keys.append(key)
            self._row_cells[key] = list(base)
        if not self._bulk_pending:
            self._tune_widths(max(20, int(self._table.size.width)))
            self._restore_cursor(*self._last_prev)
        return bool(self._bulk_pending)

    def _drain_bulk_blocking(self):
        """Deterministic flush (tests / no-worker fallback)."""
        gen = self._bulk_gen
        while self._bulk_pending and self._bulk_gen == gen:
            self._bulk_step()

    async def drain_bulk(self, gen: int):
        """Exclusive worker body: batch each chunk, yield between them."""
        while self._bulk_pending and self._bulk_gen == gen:
            async with self._table.batch():
                more = self._bulk_step()
            if more:
                await asyncio.sleep(0)

    def _write_row(self, key: str, base: list):
        """Persist base cells and push their current display rendering."""
        self._row_cells[key] = list(base)
        display = self._project(self._display_cells(key, base))
        try:
            for col_key, value in zip(self._column_keys(), display):
                self._table.update_cell(key, col_key, value)
        except Exception:
            pass

    def _column_keys(self) -> list:
        """Ordered visible column keys (DataTable needs keys, not indexes)."""
        cached = self._pkg_column_keys
        expected = len(self._active_indices)
        if cached and len(cached) == expected:
            return cached
        keys = list(self._table.columns.keys())[:expected]
        self._pkg_column_keys = keys
        return keys

    def _drop_row(self, key: str):
        try:
            self._table.remove_row(key)
        except Exception:
            pass
        if key in self._row_keys:
            self._row_keys.remove(key)
        self._row_cells.pop(key, None)
        self._row_status.pop(key, None)

    def _reconcile_rows(self, wanted: list):
        """Key-aware row reconciliation (M3 Step 1).

        - vanished keys are removed;
        - keys keeping their absolute position are updated in place;
        - new/moved keys are appended via add_row;
        - status overrides survive for surviving keys.
        """
        dt = self._table
        new_keys = [k for k, _ in wanted]

        # 1) global removals
        for k in [k for k in self._row_keys if k not in set(new_keys)]:
            self._drop_row(k)

        # 2) common prefix stays untouched
        p = 0
        old = self._row_keys
        while p < min(len(old), len(wanted)) and old[p] == new_keys[p]:
            p += 1

        # 3) tail: drop survivors whose absolute position changed (reorders
        #    need re-add since DataTable can only append).
        old_tail = old[p:]
        pos_old = {k: p + i for i, k in enumerate(old_tail)}
        kept_positions = {
            k: p + i
            for i, (k, _) in enumerate(wanted[p:])
            if k in pos_old
        }
        for k in [k for k in old_tail if pos_old.get(k) != kept_positions.get(k)]:
            self._drop_row(k)

        # 4) walk the tail: update stable survivors, append everything else
        remaining = self._row_keys[p:]
        for offset, (key, base) in enumerate(wanted[p:]):
            if offset < len(remaining) and remaining[offset] == key:
                stored = self._row_cells.get(key)
                if stored is None or stored != base:
                    self._write_row(key, base)
                else:
                    self._row_cells[key] = list(base)
            else:
                display = self._project(self._display_cells(key, base))
                try:
                    dt.add_row(*display, key=key)
                except Exception:
                    continue
                self._row_keys.insert(p + offset, key)
                self._row_cells[key] = list(base)

    def _capture_cursor(self) -> tuple:
        dt = self._table
        try:
            coord = dt.cursor_coordinate
            if coord is None or dt.row_count == 0:
                return (None, -1)
            key = dt.coordinate_to_cell_key(coord).row_key.value
            return (key, coord.row)
        except Exception:
            return (None, -1)

    def _restore_cursor(self, prev_key, prev_row: int):
        """Lock cursor/scroll: same key wins, else nearest index clamp."""
        dt = self._table
        count = dt.row_count
        if count == 0:
            return
        target = None
        if prev_key:
            try:
                target = dt.get_row_index(prev_key)
            except Exception:
                target = None
        if target is None or not 0 <= target < count:
            base = prev_row if isinstance(prev_row, int) and prev_row >= 0 else 0
            target = min(base, count - 1)
        try:
            dt.cursor_coordinate = Coordinate(target, 0)
            dt.scroll_visible(animate=False)
        except Exception:
            pass

    def _package_widths(self, width):
        available = max(20, width - 11)
        ver_w = max(8, available * 16 // 100)
        arch_w = max(6, available * 10 // 100)
        mgr_w = max(10, available * 22 // 100)
        name_w = max(10, available - 1 - ver_w - arch_w - mgr_w)
        return (1, name_w, ver_w, arch_w, mgr_w)

    def _tune_widths(self, width: int):
        dt = self._table
        if not self._pkg_mode:
            return
        widths = self._package_widths(max(20, int(width)))
        subset = [widths[i] for i in self._active_indices]
        try:
            for col_key, w in zip(self._column_keys(), subset):
                dt.columns[col_key].width = w
            dt.refresh()
        except Exception:
            pass

    def _rebuild_columns(self, indices: tuple[int, ...], width: int):
        dt = self._table
        dt.clear(columns=True)
        self._build_columns(indices, width)
        rows = [
            (k, self._display_cells(k, self._row_cells[k]))
            for k in list(self._row_keys)
        ]
        for key, display in rows:
            try:
                dt.add_row(*self._project(display), key=key)
            except Exception:
                pass

    def _build_columns(self, indices: tuple[int, ...], width: int | None = None):
        w = width if width is not None else self._table.size.width
        widths = self._package_widths(max(20, int(w)))
        for i in indices:
            label = self._COL_LABELS[i]
            self._table.add_column(label, width=max(1, widths[i]))
        self._active_indices = tuple(indices)
        self._pkg_column_keys = list(self._table.columns.keys())
        self._pkg_mode = True

    def remove_package(self, name: str, mgr) -> bool:
        key = encode_key(name, mgr)
        if key not in self._row_keys:
            return False
        try:
            self._table.remove_row(key)
        except Exception:
            return False
        self._row_keys.remove(key)
        self._row_cells.pop(key, None)
        self._row_status.pop(key, None)
        return True

    def show_counts(self, counts: dict, *, loading: bool = False):
        self._table.clear(columns=True)
        self._row_keys = []
        self._row_cells = {}
        self._row_status = {}
        self._pkg_mode = False
        self._table.add_columns("Manager", "Count")
        if loading:
            self._table.add_row("…", "Loading…")
            return
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
