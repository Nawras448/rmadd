from abc import ABC, abstractmethod
from threading import Event
from typing import Callable, Optional

from features.package_store.domain import (
    Package,
    PackageManager,
    PackageManagerTier,
    PackageStatus,
    Repo,
    PackageCollection,
    meta,
    supports,
    tier,
)


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
    def install(
        self,
        name: str,
        manager: PackageManager,
        progress_callback: Optional[Callable] = None,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        pass

    @abstractmethod
    def remove(
        self,
        name: str,
        manager: PackageManager,
        progress_callback: Optional[Callable] = None,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        pass

    @abstractmethod
    def update(
        self,
        name: str,
        manager: PackageManager,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        pass

    @abstractmethod
    def update_all(
        self,
        manager: PackageManager,
        on_output: Optional[Callable[[str], None]] = None,
        cancel_event: Optional[Event] = None,
    ) -> bool:
        pass


class BasePackageManager(ABC):
    """Uniform abstract interface for every package manager backend.

    Concrete adapters implement the abstract methods; the base class owns
    binary availability, command execution (privileged or user-level) and
    tier metadata shared by all backends.
    """

    def __init__(self, manager: PackageManager):
        self._manager = manager

    @property
    def manager(self) -> PackageManager:
        return self._manager

    @property
    def tier(self) -> PackageManagerTier:
        return tier(self._manager)

    @property
    def display_name(self) -> str:
        return meta(self._manager).display_name

    @property
    def needs_root(self) -> bool:
        return meta(self._manager).needs_root

    @property
    def binaries(self) -> tuple:
        return meta(self._manager).binaries

    @property
    def families(self) -> tuple:
        return meta(self._manager).families

    def supports(self, operation: str) -> bool:
        return supports(self._manager, operation)

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
    def install(self, name: str, on_output=None, cancel_event=None) -> bool:
        pass

    @abstractmethod
    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        pass

    @abstractmethod
    def update(self, name: str, on_output=None, cancel_event=None) -> bool:
        pass

    @abstractmethod
    def update_all(self, on_output=None, cancel_event=None) -> bool:
        pass

    @abstractmethod
    def list_repos(self) -> list:
        pass

    def get_status(self, name: str) -> PackageStatus:
        try:
            installed_names = {p.name for p in self.list_installed()}
        except Exception:
            return PackageStatus.ERROR
        return PackageStatus.INSTALLED if name in installed_names else PackageStatus.AVAILABLE


# Backwards-compatible alias for existing imports.
PackageDataSource = BasePackageManager
