"""Aggregate package service with threaded querying and caching."""

import os
import threading
import time
import concurrent.futures
from dataclasses import replace
from threading import Event
from typing import Callable, Optional

from rmadd.package_managers.base import BasePackageManager
from rmadd.models import (
    Package,
    PackageManager,
    PackageManagerTier,
    PackageStatus,
    Repo,
    PackageCollection,
    supports,
    tier,
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
    MAX_POOL_WORKERS = 8

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
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(self.MAX_POOL_WORKERS, len(sources)))
        )

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

        Uses a dedicated executor so this can safely run from a worker of
        ``self._pool`` (background refresh) without recursive pool deadlock.
        """
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(self.MAX_POOL_WORKERS, len(self._sources)))
        ) as ex:
            futures = {ex.submit(self._source(mgr).list_installed): mgr for mgr in self._sources}
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

    def install(
        self,
        name: str,
        manager: PackageManager,
        progress_callback=None,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        return self._source(manager).install(name, on_output, cancel_event)

    def install_appimage(self, source_path: str, on_output=None, cancel_event=None) -> bool:
        return self._source(PackageManager.APPIMAGE).install(
            os.path.basename(source_path), on_output, cancel_event, source_path=source_path
        )

    def remove(
        self,
        name: str,
        manager: PackageManager,
        progress_callback=None,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        return self._source(manager).remove(name, on_output, cancel_event)

    def update(
        self,
        name: str,
        manager: PackageManager,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        return self._source(manager).update(name, on_output, cancel_event)

    def update_all(
        self,
        manager: PackageManager,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        return self._source(manager).update_all(on_output, cancel_event)
