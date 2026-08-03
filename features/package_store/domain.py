from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Callable


class PackageManager(str, Enum):
    # --- Tier 1: native system package managers ---
    APT = "apt"
    DPKG = "dpkg"
    PACMAN = "pacman"
    DNF = "dnf"
    YUM = "yum"
    RPM = "rpm"
    ZYPPER = "zypper"
    APK = "apk"
    XBPS = "xbps"
    EMERGE = "emerge"
    NIX = "nix"
    EOPKG = "eopkg"
    SLACKPKG = "slackpkg"
    # --- Tier 2: universal packaging formats ---
    FLATPAK = "flatpak"
    SNAP = "snap"
    APPIMAGE = "appimage"
    BREW = "brew"
    # --- Tier 3: language & developer ecosystem managers ---
    PIP = "pip"
    PIPX = "pipx"
    CARGO = "cargo"
    NPM = "npm"
    PNPM = "pnpm"
    YARN = "yarn"
    BUN = "bun"
    GO = "go"
    GEM = "gem"
    COMPOSER = "composer"
    # --- Standalone local binaries (not package-managed) ---
    LOCAL = "local"


class PackageManagerTier(str, Enum):
    NATIVE = "native"
    UNIVERSAL = "universal"
    ECOSYSTEM = "ecosystem"


class PackageStatus(str, Enum):
    INSTALLED = "installed"
    AVAILABLE = "available"
    UPDATING = "updating"
    ERROR = "error"


TIER_MAP: dict[PackageManager, PackageManagerTier] = {
    PackageManager.APT: PackageManagerTier.NATIVE,
    PackageManager.DPKG: PackageManagerTier.NATIVE,
    PackageManager.PACMAN: PackageManagerTier.NATIVE,
    PackageManager.DNF: PackageManagerTier.NATIVE,
    PackageManager.YUM: PackageManagerTier.NATIVE,
    PackageManager.RPM: PackageManagerTier.NATIVE,
    PackageManager.ZYPPER: PackageManagerTier.NATIVE,
    PackageManager.APK: PackageManagerTier.NATIVE,
    PackageManager.XBPS: PackageManagerTier.NATIVE,
    PackageManager.EMERGE: PackageManagerTier.NATIVE,
    PackageManager.NIX: PackageManagerTier.NATIVE,
    PackageManager.EOPKG: PackageManagerTier.NATIVE,
    PackageManager.SLACKPKG: PackageManagerTier.NATIVE,
    PackageManager.FLATPAK: PackageManagerTier.UNIVERSAL,
    PackageManager.SNAP: PackageManagerTier.UNIVERSAL,
    PackageManager.APPIMAGE: PackageManagerTier.UNIVERSAL,
    PackageManager.BREW: PackageManagerTier.UNIVERSAL,
    PackageManager.PIP: PackageManagerTier.ECOSYSTEM,
    PackageManager.PIPX: PackageManagerTier.ECOSYSTEM,
    PackageManager.CARGO: PackageManagerTier.ECOSYSTEM,
    PackageManager.NPM: PackageManagerTier.ECOSYSTEM,
    PackageManager.PNPM: PackageManagerTier.ECOSYSTEM,
    PackageManager.YARN: PackageManagerTier.ECOSYSTEM,
    PackageManager.BUN: PackageManagerTier.ECOSYSTEM,
    PackageManager.GO: PackageManagerTier.ECOSYSTEM,
    PackageManager.GEM: PackageManagerTier.ECOSYSTEM,
    PackageManager.COMPOSER: PackageManagerTier.ECOSYSTEM,
    PackageManager.LOCAL: PackageManagerTier.ECOSYSTEM,
}

TIER_LABELS: dict[PackageManagerTier, str] = {
    PackageManagerTier.NATIVE: "Native",
    PackageManagerTier.UNIVERSAL: "Universal",
    PackageManagerTier.ECOSYSTEM: "Ecosystem",
}

TIER_ORDER: dict[PackageManagerTier, int] = {
    PackageManagerTier.NATIVE: 0,
    PackageManagerTier.UNIVERSAL: 1,
    PackageManagerTier.ECOSYSTEM: 2,
}


def tier(manager: PackageManager) -> PackageManagerTier:
    return TIER_MAP.get(manager, PackageManagerTier.ECOSYSTEM)


ALL_CAPS = frozenset({"search", "install", "remove", "update", "update_all", "list_installed"})


@dataclass(frozen=True)
class ManagerMeta:
    display_name: str
    binaries: tuple[str, ...] = ()
    families: tuple[str, ...] = ()
    needs_root: bool = True
    capabilities: frozenset[str] = ALL_CAPS


DEBIAN = ("debian", "ubuntu", "linuxmint", "pop", "elementary", "raspbian", "kali", "devuan")
ARCH = ("arch", "manjaro", "endeavouros", "artix", "cachyos", "garuda")
REDHAT = ("fedora", "rhel", "centos", "rocky", "almalinux", "redhat", "ol")
SUSE = ("suse", "opensuse", "sles")
SLACKWARE = ("slackware", "slackpkg")

MANAGER_META: dict[PackageManager, ManagerMeta] = {
    # ---------- Tier 1: native ----------
    PackageManager.APT: ManagerMeta("apt", ("apt",), DEBIAN, True),
    PackageManager.DPKG: ManagerMeta(
        "dpkg",
        ("dpkg",),
        DEBIAN,
        True,
        frozenset({"list_installed", "remove"}),
    ),
    PackageManager.PACMAN: ManagerMeta("pacman", ("pacman",), ARCH, True),
    PackageManager.DNF: ManagerMeta("dnf", ("dnf",), REDHAT, True),
    PackageManager.YUM: ManagerMeta(
        "yum",
        ("yum",),
        REDHAT,
        True,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.RPM: ManagerMeta(
        "rpm",
        ("rpm",),
        REDHAT,
        True,
        frozenset({"list_installed", "remove"}),
    ),
    PackageManager.ZYPPER: ManagerMeta("zypper", ("zypper",), SUSE, True),
    PackageManager.APK: ManagerMeta("apk", ("apk",), ("alpine",), True),
    PackageManager.XBPS: ManagerMeta(
        "xbps",
        ("xbps-install", "xbps-query"),
        ("void",),
        True,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.EMERGE: ManagerMeta("emerge", ("emerge",), ("gentoo",), True),
    PackageManager.NIX: ManagerMeta(
        "nix",
        ("nix", "nix-env"),
        ("nixos",),
        False,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.EOPKG: ManagerMeta("eopkg", ("eopkg",), ("solus",), True),
    PackageManager.SLACKPKG: ManagerMeta(
        "slackpkg",
        ("slackpkg",),
        SLACKWARE,
        True,
        frozenset({"search", "install", "remove", "list_installed"}),
    ),
    # ---------- Tier 2: universal ----------
    PackageManager.FLATPAK: ManagerMeta("flatpak", ("flatpak",), (), True),
    PackageManager.SNAP: ManagerMeta("snap", ("snap",), (), True),
    PackageManager.APPIMAGE: ManagerMeta(
        "AppImage",
        (),
        (),
        False,
        frozenset({"install", "remove", "list_installed"}),
    ),
    PackageManager.BREW: ManagerMeta(
        "brew",
        ("brew",),
        (),
        False,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    # ---------- Tier 3: ecosystem ----------
    PackageManager.PIP: ManagerMeta(
        "pip",
        ("pip3", "pip"),
        (),
        False,
        frozenset({"install", "remove", "update", "list_installed"}),
    ),
    PackageManager.PIPX: ManagerMeta(
        "pipx",
        ("pipx",),
        (),
        False,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.CARGO: ManagerMeta(
        "cargo",
        ("cargo",),
        (),
        False,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.NPM: ManagerMeta(
        "npm",
        ("npm",),
        (),
        False,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.PNPM: ManagerMeta(
        "pnpm",
        ("pnpm",),
        (),
        False,
        frozenset({"install", "remove", "update", "list_installed"}),
    ),
    PackageManager.YARN: ManagerMeta(
        "yarn",
        ("yarn",),
        (),
        False,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.BUN: ManagerMeta(
        "bun",
        ("bun",),
        (),
        False,
        frozenset({"install", "remove", "update", "list_installed"}),
    ),
    PackageManager.GO: ManagerMeta(
        "go",
        ("go",),
        (),
        False,
        frozenset({"install", "remove", "update", "list_installed"}),
    ),
    PackageManager.GEM: ManagerMeta(
        "gem",
        ("gem",),
        (),
        False,
        frozenset({"search", "install", "remove", "update", "list_installed"}),
    ),
    PackageManager.COMPOSER: ManagerMeta(
        "composer",
        ("composer",),
        (),
        False,
        frozenset({"install", "remove", "update", "list_installed"}),
    ),
    PackageManager.LOCAL: ManagerMeta(
        "Local Binary",
        (),
        (),
        False,
        frozenset({"list_installed", "remove"}),
    ),
}


def meta(manager: PackageManager) -> ManagerMeta:
    return MANAGER_META[manager]


def supports(manager: PackageManager, operation: str) -> bool:
    return operation in MANAGER_META[manager].capabilities


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

    def sorted_by_tier(self) -> "PackageCollection":
        return PackageCollection(
            sorted(
                self._packages,
                key=lambda p: (TIER_ORDER[tier(p.manager)], p.manager.value, p.name),
            )
        )

    @property
    def total(self) -> int:
        return len(self._packages)
