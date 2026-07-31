import time
import concurrent.futures
from typing import Optional

from features.package_store.ports import GetPackagesUseCase, InstallPackageUseCase, PackageDataSource
from features.package_store.domain import Package, PackageManager, Repo, PackageCollection


class PackageManagerService(GetPackagesUseCase, InstallPackageUseCase):
    SEARCH_TTL = 60
    SEARCH_LIMIT = 50

    def __init__(self, sources: dict[PackageManager, PackageDataSource]):
        self._sources = sources
        self._search_cache: dict[tuple, tuple[float, PackageCollection]] = {}

    @property
    def available_managers(self) -> list:
        return list(self._sources.keys())

    def _source(self, manager: PackageManager) -> PackageDataSource:
        return self._sources[manager]

    def list_installed(self, manager: PackageManager | None = None) -> PackageCollection:
        if manager:
            pkgs = self._source(manager).list_installed()
            return PackageCollection(pkgs)
        all_pkgs = []
        for mgr, src in self._sources.items():
            for p in src.list_installed():
                p.manager = mgr
                all_pkgs.append(p)
        return PackageCollection(all_pkgs)

    def search(self, query: str, manager: PackageManager | None = None) -> PackageCollection:
        key = (query.strip(), manager.value if manager else None)
        hit = self._search_cache.get(key)
        if hit and time.monotonic() - hit[0] < self.SEARCH_TTL:
            return hit[1]
        if manager:
            collection = PackageCollection(self._source(manager).search(query)[:self.SEARCH_LIMIT])
        else:
            collection = self._search_all(query)
        self._search_cache[key] = (time.monotonic(), collection)
        return collection

    def _search_all(self, query: str) -> PackageCollection:
        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(self._sources))) as ex:
            futures = {ex.submit(self._source(mgr).search, query): mgr for mgr in self._sources}
            for fut in concurrent.futures.as_completed(futures):
                mgr = futures[fut]
                try:
                    for p in fut.result()[:self.SEARCH_LIMIT]:
                        p.manager = mgr
                        results.append(p)
                except Exception:
                    continue
        return PackageCollection(results)

    def get_package_detail(self, name: str, manager: PackageManager) -> Package | None:
        return self._source(manager).get_info(name)

    def get_package_count(self, manager: PackageManager) -> int:
        return self._source(manager).count()

    def get_all_counts(self) -> dict:
        result = {}
        for mgr, src in self._sources.items():
            count = src.count()
            if count > 0:
                result[mgr.value] = str(count)
        return result

    def list_repos(self, manager: PackageManager) -> list:
        return self._source(manager).list_repos()

    def install(self, name: str, manager: PackageManager, progress_callback=None) -> bool:
        return self._source(manager).install(name)

    def remove(self, name: str, manager: PackageManager, progress_callback=None) -> bool:
        return self._source(manager).remove(name)

    def update(self, name: str, manager: PackageManager) -> bool:
        return self._source(manager).update(name)

    def update_all(self, manager: PackageManager) -> bool:
        return self._source(manager).update_all()
