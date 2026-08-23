"""Pure optimistic-lifecycle state machine for package operations.

Extracted from ``StoreScreen`` (Milestone 1). Owns the five in-memory
structures the screen used to hold:

- ``_installed_pkgs``  list[Package]                (hydrated from the service)
- ``_local_pkgs``      list[Package]               (LOCAL binary tab snapshot)
- ``_installed_set``   set[(name, manager)]        (O(1) membership)
- ``_pending_ops``     dict[key -> _PendingOp]     (action + pre-op snapshot)
- ``_removal_stash``   dict[key -> _RemovalStash]  (verbatim restore data)

Lifecycle contract (ARCHITECTURE.md §4):

    trigger -> remove_instantly()          [memory mutation before subprocess]
    pending -> register_pending(action)    [optimistic write]
    success -> settle_confirmed(action)    [keep the mutation]
    failure -> revert_pending(action)      [undo ONLY what this op changed]

Invariants enforced since the M1 quirk fixes:

1. Reverting an install restores the previous state exactly: packages that
   were already installed before the pending op are NEVER deleted; only the
   placeholder appended by this op is removed.
2. Reverting a removal re-adds the key to ``_installed_set`` only when it
   genuinely belonged there before the removal (LOCAL binaries restored to
   the local list do not pollute the managed-installed set).
3. A removal revert without a prior ``remove_instantly`` (e.g. the
   PackageDetailScreen flow) mutates nothing: no stash means no prior memory
   mutation, so there is nothing to undo beyond the pending marker.

The class has ZERO Textual/UI imports. Widget-facing decisions are returned
as plain values: ``register_pending`` yields the glyph status to paint (or
None), and ``revert_pending`` yields a :class:`RestoreDirective` for remove
operations so a controller can re-render the affected list.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from rmadd.models import Package, PackageManager, PackageStatus

PackageKey = tuple[str, PackageManager]


@dataclass(frozen=True)
class RestoreDirective:
    """Where a controller must re-insert a restored remove victim."""

    pkg: Package
    index: int
    is_local: bool


@dataclass(frozen=True)
class _PendingOp:
    """Optimistic op marker plus the pre-op snapshot needed to undo it."""

    action: str
    pre_existing: bool = False


@dataclass(frozen=True)
class _RemovalStash:
    """Verbatim restore data captured before an optimistic removal."""

    pkg: Package
    index: int
    was_managed_installed: bool


class OptimisticPackageState:
    """Single source of truth for optimistic install/remove/update writes."""

    def __init__(self) -> None:
        self._installed_pkgs: list[Package] = []
        self._local_pkgs: list[Package] = []
        self._installed_set: set[PackageKey] = set()
        self._pending_ops: dict[PackageKey, _PendingOp] = {}
        self._removal_stash: dict[PackageKey, _RemovalStash] = {}

    # ------------------------------------------------------------- queries --

    def installed_packages(self) -> list[Package]:
        return list(self._installed_pkgs)

    def local_packages(self) -> list[Package]:
        return list(self._local_pkgs)

    def is_installed(self, name: str, mgr: PackageManager) -> bool:
        """Pending install counts as installed; pending remove as not."""
        key = (name, mgr)
        pending = self._pending_ops.get(key)
        if pending is not None:
            return pending.action != "remove"
        return key in self._installed_set

    def version_map(self) -> dict[PackageKey, str]:
        """(name, mgr) -> version for installed packages carrying one.

        Only _installed_pkgs are consulted; LOCAL binaries never contribute.
        """
        return {
            (p.name, p.manager): p.version
            for p in self._installed_pkgs
            if p.version
        }

    def counts_by_manager(self) -> dict[str, int]:
        """Per-manager counts derived from the installed set only."""
        counts: dict[str, int] = {}
        for _name, mgr in self._installed_set:
            counts[mgr.value] = counts.get(mgr.value, 0) + 1
        return counts

    def pending_action(self, name: str, mgr: PackageManager) -> str | None:
        op = self._pending_ops.get((name, mgr))
        return op.action if op is not None else None

    def stash_entry(self, name: str, mgr: PackageManager) -> _RemovalStash | None:
        return self._removal_stash.get((name, mgr))

    # ------------------------------------------------------------ hydration --

    def hydrate_installed(self, packages: Iterable[Package]) -> None:
        self._installed_pkgs = list(packages)
        self._installed_set = {(p.name, p.manager) for p in self._installed_pkgs}

    def hydrate_local(self, packages: Iterable[Package]) -> None:
        self._local_pkgs = list(packages)

    # ------------------------------------------------------------ mutations --

    def remove_instantly(self, name: str, mgr: PackageManager) -> tuple[Package, int]:
        """Zero-latency optimistic removal (StoreScreen._remove_instantly).

        Stashes the original Package, its list index and whether the key
        genuinely belonged to the managed-installed set, then drops the key
        from every structure. Returns the stashed ``(pkg, index)`` pair.
        """
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
        self._removal_stash[key] = _RemovalStash(
            pkg=pkg,
            index=index,
            was_managed_installed=key in self._installed_set,
        )
        self._installed_set.discard(key)
        self._installed_pkgs = [
            p for p in self._installed_pkgs if (p.name, p.manager) != key
        ]
        self._local_pkgs = [
            p for p in self._local_pkgs if (p.name, p.manager) != key
        ]
        return (pkg, index)

    def register_pending(
        self, action: str, name: str, mgr: PackageManager
    ) -> PackageStatus | None:
        """Optimistic write before any subprocess result.

        Returns the row-status override a controller should paint:
        PENDING for installs (even when the package already exists),
        UPDATING for updates, None for removes.
        """
        key = (name, mgr)
        existing = self._pending_ops.get(key)
        if action == "install":
            pre_existing = (
                existing.pre_existing
                if existing is not None
                else key in self._installed_set
            )
        else:
            pre_existing = existing.pre_existing if existing is not None else False
        self._pending_ops[key] = _PendingOp(action=action, pre_existing=pre_existing)
        if action == "install":
            if not pre_existing:
                self._installed_set.add(key)
                self._installed_pkgs.append(
                    Package(name=name, manager=mgr, status=PackageStatus.PENDING)
                )
            return PackageStatus.PENDING
        if action == "update":
            return PackageStatus.UPDATING
        return None

    def settle_confirmed(self, action: str, name: str, mgr: PackageManager) -> None:
        """Settle the optimistic write after the operation succeeded."""
        key = (name, mgr)
        self._pending_ops.pop(key, None)
        if action == "install":
            if key not in self._installed_set:
                self._installed_set.add(key)
                self._installed_pkgs.append(Package(name=name, manager=mgr))
            for p in self._installed_pkgs:
                if (p.name, p.manager) == key:
                    p.status = PackageStatus.INSTALLED
        elif action == "remove":
            self._removal_stash.pop(key, None)
            self._installed_set.discard(key)
            self._installed_pkgs = [
                p for p in self._installed_pkgs if not (p.name == name and p.manager == mgr)
            ]
            self._local_pkgs = [
                p for p in self._local_pkgs if not (p.name == name and p.manager == mgr)
            ]
        else:  # update
            for p in self._installed_pkgs:
                if (p.name, p.manager) == key:
                    p.status = PackageStatus.INSTALLED

    def revert_pending(
        self, action: str, name: str, mgr: PackageManager
    ) -> RestoreDirective | None:
        """Undo the optimistic write on failure/cancel (in-memory only).

        Undoes ONLY what this operation changed:

        - install: removes the placeholder solely when this op added one;
          pre-existing installs survive untouched.
        - remove: restores the stashed Package at its clamped index and
          re-adds the key to the installed set only when it was a member
          before the removal. Without a stash (no prior remove_instantly)
          nothing is mutated.
        """
        key = (name, mgr)
        op = self._pending_ops.pop(key, None)
        if action == "install":
            if op is not None and op.pre_existing:
                return None  # nothing was added; previous state already intact
            self._installed_set.discard(key)
            self._installed_pkgs = [
                p for p in self._installed_pkgs if not (p.name == name and p.manager == mgr)
            ]
            return None
        if action == "remove":
            stashed = self._removal_stash.pop(key, None)
            if stashed is None:
                return None  # no remove_instantly happened: nothing to undo
            if stashed.was_managed_installed:
                self._installed_set.add(key)
            pkg = stashed.pkg
            index = stashed.index
            if pkg.manager == PackageManager.LOCAL:
                if not any((p.name, p.manager) == key for p in self._local_pkgs):
                    pos = index if 0 <= index < len(self._local_pkgs) else len(self._local_pkgs)
                    self._local_pkgs.insert(pos, pkg)
                    return RestoreDirective(pkg=pkg, index=pos, is_local=True)
            else:
                if not any((p.name, p.manager) == key for p in self._installed_pkgs):
                    pos = (
                        index
                        if 0 <= index < len(self._installed_pkgs)
                        else len(self._installed_pkgs)
                    )
                    self._installed_pkgs.insert(pos, pkg)
                    return RestoreDirective(pkg=pkg, index=pos, is_local=False)
            return None
        # update
        for p in self._installed_pkgs:
            if (p.name, p.manager) == key:
                p.status = PackageStatus.INSTALLED
        return None
