from typing import Optional

from features.package_store.ports import GetPackagesUseCase, InstallPackageUseCase, PackageDataSource
from features.package_store.domain import Package, PackageManager, Repo, PackageCollection


class PackageManagerService(GetPackagesUseCase, InstallPackageUseCase):
    def __init__(self, sources: dict[PackageManager, PackageDataSource]):
        self._sources = sources

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
        if manager:
            return PackageCollection(self._source(manager).search(query))
        results = []
        for mgr, src in self._sources.items():
            for p in src.search(query):
                p.manager = mgr
                results.append(p)
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
