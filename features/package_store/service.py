import os
import time
import concurrent.futures
from dataclasses import replace
from threading import Event
from typing import Callable, Optional

from features.package_store.ports import GetPackagesUseCase, InstallPackageUseCase, BasePackageManager
from features.package_store.domain import (
    Package,
    PackageManager,
    PackageManagerTier,
    Repo,
    PackageCollection,
    supports,
    tier,
)


class PackageManagerService(GetPackagesUseCase, InstallPackageUseCase):
    SEARCH_TTL = 60
    SEARCH_LIMIT = 50
    COUNTS_TTL = 60
    MAX_POOL_WORKERS = 8

    def __init__(self, sources: dict[PackageManager, BasePackageManager]):
        self._sources = sources
        self._search_cache: dict[tuple, tuple[float, PackageCollection]] = {}
        self._counts_cache: tuple[float, dict] | None = None
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(self.MAX_POOL_WORKERS, len(sources)))
        )

    @property
    def available_managers(self) -> list:
        return list(self._sources.keys())

    def add_source(self, manager: PackageManager, source) -> bool:
        """Register a newly discovered manager at runtime (no-op if known)."""
        if manager in self._sources:
            return False
        self._sources[manager] = source
        self._counts_cache = None
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

    def list_installed(self, manager: PackageManager | None = None) -> PackageCollection:
        if manager:
            pkgs = self._source(manager).list_installed()
            return PackageCollection(pkgs)
        results = []
        futures = {self._pool.submit(self._source(mgr).list_installed): mgr for mgr in self._sources}
        for fut in concurrent.futures.as_completed(futures):
            mgr = futures[fut]
            try:
                for p in fut.result():
                    p.manager = mgr
                    results.append(p)
            except Exception:
                continue
        registered = {p.name for p in results if p.manager != PackageManager.LOCAL}
        results = [
            p for p in results
            if p.manager != PackageManager.LOCAL or p.name not in registered
        ]
        return PackageCollection(results)

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

    def invalidate_counts(self) -> None:
        """Drop the cached counts so the next get_all_counts() refetches."""
        self._counts_cache = None

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
