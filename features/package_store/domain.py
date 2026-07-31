from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Callable


class PackageManager(str, Enum):
    APT = "apt"
    DNF = "dnf"
    PACMAN = "pacman"
    SNAP = "snap"
    FLATPAK = "flatpak"
    RPM = "rpm"


class PackageStatus(str, Enum):
    INSTALLED = "installed"
    AVAILABLE = "available"
    UPDATING = "updating"
    ERROR = "error"


@dataclass
class Package:
    name: str = ""
    version: str = ""
    arch: str = ""
    repo: str = ""
    size: str = ""
    status: PackageStatus = PackageStatus.INSTALLED
    manager: PackageManager = PackageManager.DNF
    summary: str = ""


@dataclass
class Repo:
    name: str = ""
    baseurl: str = ""
    enabled: bool = True
    gpgcheck: bool = True


class PackageCollection:
    def __init__(self, packages: Optional[List[Package]] = None):
        self._packages = packages or []

    def __len__(self) -> int:
        return len(self._packages)

    def __iter__(self):
        return iter(self._packages)

    def filter(self, predicate: Callable[[Package], bool]) -> "PackageCollection":
        return PackageCollection([p for p in self._packages if predicate(p)])

    def by_manager(self, manager: PackageManager) -> "PackageCollection":
        return self.filter(lambda p: p.manager == manager)

    def by_managers(self, managers) -> "PackageCollection":
        if not managers:
            return self
        return self.filter(lambda p: p.manager in managers)

    def search(self, query: str) -> "PackageCollection":
        q = query.lower()
        return self.filter(
            lambda p: q in p.name.lower() or q in (p.summary or "").lower()
        )

    def to_list(self) -> List[Package]:
        return list(self._packages)

    def count_by_manager(self) -> dict:
        counts = {}
        for mgr in PackageManager:
            counts[mgr.value] = sum(1 for p in self._packages if p.manager == mgr)
        return counts

    @property
    def total(self) -> int:
        return len(self._packages)
