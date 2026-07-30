from abc import ABC, abstractmethod
from typing import Callable, Optional

from features.package_store.domain import Package, PackageManager, Repo, PackageCollection


class GetPackagesUseCase(ABC):
    @abstractmethod
    def list_installed(self, manager: Optional[PackageManager] = None) -> PackageCollection:
        pass

    @abstractmethod
    def search(self, query: str, manager: Optional[PackageManager] = None) -> PackageCollection:
        pass

    @abstractmethod
    def get_package_detail(self, name: str, manager: PackageManager) -> Optional[Package]:
        pass

    @abstractmethod
    def get_package_count(self, manager: PackageManager) -> int:
        pass

    @abstractmethod
    def get_all_counts(self) -> dict:
        pass

    @abstractmethod
    def list_repos(self, manager: PackageManager) -> list:
        pass


class InstallPackageUseCase(ABC):
    @abstractmethod
    def install(self, name: str, manager: PackageManager, progress_callback: Optional[Callable] = None) -> bool:
        pass

    @abstractmethod
    def remove(self, name: str, manager: PackageManager, progress_callback: Optional[Callable] = None) -> bool:
        pass

    @abstractmethod
    def update(self, name: str, manager: PackageManager) -> bool:
        pass

    @abstractmethod
    def update_all(self, manager: PackageManager) -> bool:
        pass


class PackageDataSource(ABC):
    @abstractmethod
    def list_installed(self) -> list:
        pass

    @abstractmethod
    def search(self, query: str) -> list:
        pass

    @abstractmethod
    def get_info(self, name: str) -> Optional[Package]:
        pass

    @abstractmethod
    def count(self) -> int:
        pass

    @abstractmethod
    def install(self, name: str) -> bool:
        pass

    @abstractmethod
    def remove(self, name: str) -> bool:
        pass

    @abstractmethod
    def update(self, name: str) -> bool:
        pass

    @abstractmethod
    def update_all(self) -> bool:
        pass

    @abstractmethod
    def list_repos(self) -> list:
        pass
