"""Aggregate package service with threaded querying and caching."""

import concurrent.futures
import json
import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from threading import Event
from typing import cast

from rmadd.logging import get_logger  # noqa: F401  (re-exported for tooling)
from rmadd.models import (
    Package,
    PackageCollection,
    PackageManager,
    PackageManagerTier,
    PackageStatus,
    supports,
    tier,
)
from rmadd.package_managers.base import (
    BasePackageManager,
    FailureReason,
    OpReport,
    OpResult,
)
from rmadd.state import PackageStateBus

MONITORED_PATHS: dict[PackageManager, tuple[str, ...]] = {
    PackageManager.APT: ("/var/lib/dpkg/status",),
    PackageManager.DPKG: ("/var/lib/dpkg/status",),
    PackageManager.FLATPAK: (
        "/var/lib/flatpak/app",
        os.path.join(os.path.expanduser("~"), ".local", "share", "flatpak", "app"),
    ),
    PackageManager.SNAP: (
        "/var/lib/snapd/snaps",
        "/var/lib/snapd/state.json",
    ),
}


class PackageManagerService:
    SEARCH_TTL = 60
    SEARCH_LIMIT = 50
    COUNTS_TTL = 60
    INSTALLED_TTL = 60.0
    INSTALLED_REFRESH_EVENT = "installed_refreshed"
    DISK_CACHE_VERSION = 1
    MAX_POOL_WORKERS = 8

    @staticmethod
    def _installed_disk_cache_path() -> str:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.join(
            os.path.expanduser("~"), ".cache"
        )
        return os.path.join(base, "rmadd", "installed_cache.json")

    def __init__(self, sources: dict[PackageManager, BasePackageManager]):
        self._sources = sources
        self._search_cache: dict[tuple, tuple[float, PackageCollection]] = {}
        self._counts_cache: tuple[float, dict] | None = None
        self._installed_cache: tuple[float, dict[PackageManager, PackageCollection]] | None = None
        self._installed_names: dict[PackageManager, frozenset[str]] = {}
        self._installed_mtimes: dict[PackageManager, float] = {}
        self._is_syncing_installed = False
        self._cache_lock = threading.Lock()
        self._state_bus: PackageStateBus | None = None
        # Two long-lived pools (M2 Step 3): queries share one; installed
        # fan-out gets its own so a background refresh running ON `_pool`
        # can fan out without self-nesting deadlock. No per-call churn.
        workers = max(1, min(self.MAX_POOL_WORKERS, len(sources)))
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="rmadd-query"
        )
        self._fetch_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="rmadd-fetch"
        )

    def shutdown(self, wait: bool = True) -> None:
        """Release pooled worker threads. The service is unusable after."""
        self._pool.shutdown(wait=wait)
        self._fetch_pool.shutdown(wait=wait)

    def set_state_bus(self, bus: PackageStateBus) -> None:
        self._state_bus = bus

    @property
    def available_managers(self) -> list:
        return list(self._sources.keys())

    def add_source(self, manager: PackageManager, source) -> bool:
        """Register a newly discovered manager at runtime (no-op if known)."""
        if manager in self._sources:
            return False
        self._sources[manager] = source
        self._counts_cache = None
        self.invalidate_installed()
        return True

    def default_search_managers(self) -> list:
        """Tier 1 + Tier 2 available managers that support search."""
        return [
            mgr for mgr in self._sources
            if tier(mgr) != PackageManagerTier.ECOSYSTEM and supports(mgr, "search")
        ]

    def _source(self, manager: PackageManager) -> BasePackageManager:
        return self._sources[manager]

    def _fresh(self, collection: PackageCollection) -> PackageCollection:
        """Return detached copies so callers may mutate results freely."""
        return PackageCollection([replace(p) for p in collection])

    def _fetch_all_installed(self) -> dict[PackageManager, PackageCollection]:
        """Run the concurrent adapter queries and bucket results per manager.

        Uses the dedicated long-lived fetch executor so this can safely run
        from a worker of ``self._pool`` (background refresh) without
        recursive pool deadlock, and without per-call executor churn.
        """
        futures = {
            self._fetch_pool.submit(self._source(mgr).list_installed): mgr
            for mgr in self._sources
        }
        by_manager: dict[PackageManager, list] = {mgr: [] for mgr in self._sources}
        for fut in concurrent.futures.as_completed(futures):
            mgr = futures[fut]
            try:
                for p in fut.result():
                    p.manager = mgr
                    by_manager[mgr].append(p)
            except Exception:
                continue
        return {mgr: PackageCollection(pkgs) for mgr, pkgs in by_manager.items()}

    @staticmethod
    def _max_mtime(paths: tuple[str, ...]) -> float | None:
        """Return the max modification time across stat-able paths (None if none)."""
        best = None
        for path in paths:
            try:
                current = os.stat(path).st_mtime
            except OSError:
                continue
            best = current if best is None else max(best, current)
        return best

    def _system_mtimes(self) -> dict[PackageManager, float]:
        """Snapshot of monitored system-state mtimes for registered managers.

        Managers without configured paths are unmonitored and excluded; managers
        whose paths are all inaccessible are also excluded (the caller treats a
        mismatch vs the stored snapshot as "changed" -> full fetch).
        """
        snapshot: dict[PackageManager, float] = {}
        for mgr in self._sources:
            paths = MONITORED_PATHS.get(mgr, ())
            if not paths:
                continue
            mtime = self._max_mtime(paths)
            if mtime is not None:
                snapshot[mgr] = mtime
        return snapshot

    def _store_installed(self, by_manager: dict[PackageManager, PackageCollection]) -> None:
        self._installed_cache = (time.monotonic(), by_manager)
        self._installed_names = {
            mgr: frozenset(p.name for p in col) for mgr, col in by_manager.items()
        }
        self._installed_mtimes = self._system_mtimes()

    @staticmethod
    def _package_to_dict(p: Package) -> dict:
        return {
            "name": p.name,
            "version": p.version,
            "arch": p.arch,
            "repo": p.repo,
            "size": p.size,
            "summary": p.summary,
            "status": p.status.value,
            "manager": p.manager.value,
        }

    @classmethod
    def _package_from_dict(cls, d: dict) -> Package:
        return Package(
            name=d.get("name", ""),
            version=d.get("version", ""),
            arch=d.get("arch", ""),
            repo=d.get("repo", ""),
            size=d.get("size", ""),
            summary=d.get("summary", ""),
            status=PackageStatus(d.get("status", PackageStatus.INSTALLED.value)),
            manager=PackageManager(d.get("manager", PackageManager.DPKG.value)),
        )

    def _load_installed_disk_cache(self):
        """Return (by_manager, mtimes) from the disk cache, or None on any failure.

        Managers that are no longer registered are dropped so a stale snapshot
        never resurrects a removed source.
        """
        try:
            path = self._installed_disk_cache_path()
            if not os.path.exists(path):
                return None
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict) or data.get("version") != self.DISK_CACHE_VERSION:
                return None
            by_manager: dict[PackageManager, PackageCollection] = {}
            for key, entries in (data.get("managers") or {}).items():
                try:
                    mgr = PackageManager(key)
                except ValueError:
                    continue
                if mgr not in self._sources or not isinstance(entries, list):
                    continue
                pkgs = [self._package_from_dict(e) for e in entries if isinstance(e, dict)]
                by_manager[mgr] = PackageCollection(pkgs)
            mtimes: dict[PackageManager, float] = {}
            for key, value in (data.get("mtimes") or {}).items():
                try:
                    mtimes[PackageManager(key)] = float(value)
                except (ValueError, TypeError):
                    continue
            if not by_manager:
                return None
            return by_manager, mtimes
        except Exception:
            return None

    def _save_installed_disk_cache(self) -> None:
        """Persist the current in-memory snapshot atomically (best-effort)."""
        try:
            with self._cache_lock:
                cache = self._installed_cache
                if cache is None:
                    return
                by_manager = cache[1]
                mtimes = dict(self._installed_mtimes)
            payload = {
                "version": self.DISK_CACHE_VERSION,
                "saved_at": cache[0],
                "mtimes": {m.value: mt for m, mt in mtimes.items()},
                "managers": {
                    mgr.value: [self._package_to_dict(p) for p in col]
                    for mgr, col in by_manager.items()
                },
            }
            path = self._installed_disk_cache_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(payload, fh)
            os.replace(tmp, path)
        except Exception:
            pass

    def _try_load_disk_cache(self) -> bool:
        """Populate the memory cache from disk on cold boot (idempotent)."""
        with self._cache_lock:
            if self._installed_cache is not None:
                return False
        loaded = self._load_installed_disk_cache()
        if loaded is None:
            return False
        by_manager, mtimes = loaded
        with self._cache_lock:
            if self._installed_cache is not None:
                return True
            self._installed_cache = (time.monotonic(), by_manager)
            self._installed_names = {
                mgr: frozenset(p.name for p in col)
                for mgr, col in by_manager.items()
            }
            self._installed_mtimes = mtimes
        self._schedule_refresh()
        return True

    def _schedule_refresh(self) -> None:
        """Submit a single background revalidation if none is already running."""
        with self._cache_lock:
            if self._is_syncing_installed:
                return
            self._is_syncing_installed = True
        self._pool.submit(self._bg_refresh_installed)

    def _mtimes_unchanged(self, current: dict[PackageManager, float]) -> bool:
        """True only when every monitored manager's mtime matches the snapshot.

        An empty stored snapshot (cold boot / invalidated) or any manager that
        previously had a readable mtime but no longer does forces a refetch.
        """
        if not self._installed_mtimes:
            return False
        for mgr, mtime in self._installed_mtimes.items():
            if current.get(mgr) != mtime:
                return False
        return True

    def _bg_refresh_installed(self) -> None:
        """Background sync worker: refetch all managers and repopulate the cache.

        Skips the subprocess pool entirely when every monitored system state is
        unchanged, extending the cache TTL instead of re-running queries.
        """
        try:
            with self._cache_lock:
                cache = self._installed_cache
            if cache is not None:
                current = self._system_mtimes()
                with self._cache_lock:
                    unchanged = self._mtimes_unchanged(current)
                if unchanged:
                    with self._cache_lock:
                        self._installed_cache = (time.monotonic(), cache[1])
                    return
            by_manager = self._fetch_all_installed()
            with self._cache_lock:
                self._store_installed(by_manager)
            self._save_installed_disk_cache()
        except Exception:
            pass
        finally:
            with self._cache_lock:
                self._is_syncing_installed = False
        if self._state_bus is not None:
            self._state_bus.emit(self.INSTALLED_REFRESH_EVENT, "", None)

    def _dedup_local(self, results: list) -> list:
        registered = {p.name for p in results if p.manager != PackageManager.LOCAL}
        return [
            p for p in results
            if p.manager != PackageManager.LOCAL or p.name not in registered
        ]

    def list_installed(self, manager: PackageManager | None = None) -> PackageCollection:
        with self._cache_lock:
            cache = self._installed_cache
            age = time.monotonic() - cache[0] if cache is not None else None

        if cache is None:
            self._try_load_disk_cache()
            with self._cache_lock:
                cache = self._installed_cache
                age = time.monotonic() - cache[0] if cache is not None else None

        if manager:
            if cache is not None:
                col = cache[1].get(manager)
                if col is not None:
                    if age is not None and age >= self.INSTALLED_TTL:
                        self._schedule_refresh()
                    return self._fresh(col)
            pkgs = self._source(manager).list_installed()
            for p in pkgs:
                p.manager = manager
            return PackageCollection(pkgs)

        if cache is None:
            by_manager = self._fetch_all_installed()
            with self._cache_lock:
                self._store_installed(by_manager)
            self._save_installed_disk_cache()
            return self._fresh(PackageCollection(
                self._dedup_local([p for col in by_manager.values() for p in col])
            ))

        if age is not None and age >= self.INSTALLED_TTL:
            self._schedule_refresh()
        return self._fresh(PackageCollection(
            self._dedup_local([p for col in cache[1].values() for p in col])
        ))

    def search(self, query: str, manager: PackageManager | None = None) -> PackageCollection:
        key = (query.strip(), manager.value if manager else None)
        hit = self._search_cache.get(key)
        if hit and time.monotonic() - hit[0] < self.SEARCH_TTL:
            return self._fresh(hit[1])
        if manager:
            collection = PackageCollection(self._source(manager).search(query)[:self.SEARCH_LIMIT])
        else:
            collection = self._search_all(query)
        self._search_cache[key] = (time.monotonic(), collection)
        return self._fresh(collection)

    def _search_all(self, query: str) -> PackageCollection:
        managers = [m for m in self._sources if supports(m, "search")]
        return self._search_managers(query, managers)

    def _search_managers(self, query: str, managers: list) -> PackageCollection:
        results = []
        futures = {self._pool.submit(self._source(mgr).search, query): mgr for mgr in managers}
        for fut in concurrent.futures.as_completed(futures):
            mgr = futures[fut]
            try:
                for p in fut.result()[:self.SEARCH_LIMIT]:
                    p.manager = mgr
                    results.append(p)
            except Exception:
                continue
        return PackageCollection(results).sorted_by_tier()

    def get_package_detail(self, name: str, manager: PackageManager) -> Package | None:
        return self._source(manager).get_info(name)

    def get_status(self, name: str, manager: PackageManager):
        with self._cache_lock:
            names = self._installed_names.get(manager)
        if names is not None:
            return (
                PackageStatus.INSTALLED if name in names else PackageStatus.AVAILABLE
            )
        if not self._installed_names:
            self._try_load_disk_cache()
            with self._cache_lock:
                names = self._installed_names.get(manager)
            if names is not None:
                return (
                    PackageStatus.INSTALLED if name in names else PackageStatus.AVAILABLE
                )
        try:
            return self._source(manager).get_status(name)
        except Exception:
            return None

    def get_package_count(self, manager: PackageManager) -> int:
        return self._source(manager).count()

    def get_all_counts(self) -> dict:
        now = time.monotonic()
        if self._counts_cache and now - self._counts_cache[0] < self.COUNTS_TTL:
            return dict(self._counts_cache[1])
        result = {}
        futures = {self._pool.submit(self._source(mgr).count): mgr for mgr in self._sources}
        for fut in concurrent.futures.as_completed(futures):
            mgr = futures[fut]
            try:
                count = fut.result()
                if count and count > 0:
                    result[mgr] = count
            except Exception:
                continue
        ordered = {mgr.value: str(result[mgr]) for mgr in self._sources if mgr in result}
        self._counts_cache = (now, ordered)
        return dict(ordered)

    def invalidate_installed(self) -> None:
        """Drop the cached installed list so the next read refetches."""
        with self._cache_lock:
            self._installed_cache = None
            self._installed_names = {}
            self._installed_mtimes = {}

    def invalidate_counts(self) -> None:
        """Drop the cached counts so the next get_all_counts() refetches."""
        self._counts_cache = None
        self.invalidate_installed()

    def list_repos(self, manager: PackageManager) -> list:
        return self._source(manager).list_repos()

    # ------------------------------------------------ op results (M2) --

    def _op_result(
        self,
        manager: PackageManager,
        op: str,
        name: str | None,
        on_output: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> OpResult:
        """Rich operation result; bool-only sources are synthesized."""
        source = self._source(manager)
        runner = getattr(source, "_run_op", None)
        if runner is not None:
            return runner(op, name, on_output, cancel_event)
        method = getattr(source, op)
        ok = bool(method(name, on_output, cancel_event))
        cancelled = bool(cancel_event is not None and cancel_event.is_set())
        if ok:
            return OpResult(True, False, FailureReason.NONE)
        reason = FailureReason.CANCELLED if cancelled else FailureReason.FAILED
        return OpResult(False, cancelled, reason)

    def install_result(self, name, manager, on_output=None, cancel_event=None) -> OpResult:
        return self._op_result(manager, "install", name, on_output, cancel_event)

    def remove_result(self, name, manager, on_output=None, cancel_event=None) -> OpResult:
        return self._op_result(manager, "remove", name, on_output, cancel_event)

    def update_result(self, name, manager, on_output=None, cancel_event=None) -> OpResult:
        return self._op_result(manager, "update", name, on_output, cancel_event)

    def update_all_result(self, manager, on_output=None, cancel_event=None) -> OpResult:
        return self._op_result(manager, "update_all", None, on_output, cancel_event)

    # ---------------------------------------------------- batch runner --

    def run_batch(
        self,
        op: str,
        targets,
        on_output: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> OpReport:
        """Execute ``op`` over ``(name|None, manager)`` targets sequentially.

        Failure isolation: a target raising or failing only marks its own
        entry; the batch continues. Cancellation is checked between targets
        (a running subprocess honours the event internally); remaining
        targets are recorded as skipped, never dropped silently.
        """
        report = OpReport()
        for name, manager in targets:
            key = manager.value if name is None else f"{name}@{manager.value}"
            if cancel_event is not None and cancel_event.is_set():
                report.skipped.append(key)
                continue
            if on_output is not None:
                on_output(f"==> {key}\n")
            try:
                result = self._op_result(manager, op, name, on_output, cancel_event)
            except Exception as e:  # isolation: never drop the batch report
                result = OpResult(False, reason=FailureReason.FAILED, tail=str(e))
            report.entries.append((key, result))
        return report

    def batch_update_all(
        self,
        managers=None,
        on_output=None,
        cancel_event=None,
    ) -> OpReport:
        """update_all across managers that declare the capability."""
        if managers is None:
            managers = [m for m in self._sources if supports(m, "update_all")]
        return self.run_batch("update_all", [(None, m) for m in managers], on_output, cancel_event)

    # ------------------------------------------------ legacy bool API --

    def install(
        self,
        name: str,
        manager: PackageManager,
        on_output: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> bool:
        return self.install_result(name, manager, on_output, cancel_event).ok

    def install_appimage(self, source_path: str, on_output=None, cancel_event=None) -> bool:
        from rmadd.package_managers.appimage import Adapter as _AppImageAdapter

        appimage = cast(_AppImageAdapter, self._source(PackageManager.APPIMAGE))
        return appimage.install(
            os.path.basename(source_path), on_output, cancel_event, source_path=source_path
        )

    def remove(
        self,
        name: str,
        manager: PackageManager,
        on_output: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> bool:
        return self.remove_result(name, manager, on_output, cancel_event).ok

    def update(
        self,
        name: str,
        manager: PackageManager,
        on_output: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> bool:
        return self.update_result(name, manager, on_output, cancel_event).ok

    def update_all(
        self,
        manager: PackageManager,
        on_output: Callable[[str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> bool:
        return self.update_all_result(manager, on_output, cancel_event).ok
