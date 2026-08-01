"""Dynamic package manager discovery with strict tier priority.

Detection pipeline:
1. Parse /etc/os-release to determine the host distribution family.
2. Probe every known manager binary with shutil.which().
3. Order available managers by tier (Native -> Universal -> Ecosystem);
   within the native tier, managers matching the host family come first.
"""

import shutil
from typing import Optional

from features.package_store.adapters import ADAPTER_FACTORIES
from features.package_store.domain import (
    PackageManager,
    PackageManagerTier,
    TIER_ORDER,
    meta,
    tier,
)

OS_RELEASE_PATH = "/etc/os-release"


def parse_os_release(path: str = OS_RELEASE_PATH) -> dict:
    """Parse an os-release file into a dict of key -> value (value lowercased).

    ID_LIKE is returned as a list. Unknown keys are ignored.
    """
    info: dict = {"id": "", "id_like": []}
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if not value:
                    continue
                if key == "ID":
                    info["id"] = value.lower()
                elif key == "ID_LIKE":
                    info["id_like"] = [v.strip().lower() for v in value.split() if v.strip()]
    except Exception:
        pass
    return info


def distro_family(path: str = OS_RELEASE_PATH) -> list:
    """Return the ordered list of distribution families (ID + ID_LIKE)."""
    info = parse_os_release(path)
    families = []
    if info["id"]:
        families.append(info["id"])
    families.extend(info["id_like"])
    return families


def is_available(manager: PackageManager) -> bool:
    if manager == PackageManager.APPIMAGE:
        return True
    return any(shutil.which(binary) is not None for binary in meta(manager).binaries)


def _family_rank(manager: PackageManager, families: list) -> int:
    if tier(manager) != PackageManagerTier.NATIVE or not families:
        return 0
    return 0 if any(f in meta(manager).families for f in families) else 1


def discover_managers(families: Optional[list] = None) -> list:
    """Discover available package managers in strict priority order.

    Returns a list of (PackageManager, adapter instance) ordered by:
    tier (Native first, then Universal, then Ecosystem), then host-family
    match for natives, then registry order.
    """
    if families is None:
        families = distro_family()
    found = [mgr for mgr in PackageManager if is_available(mgr)]
    found.sort(
        key=lambda mgr: (TIER_ORDER[tier(mgr)], _family_rank(mgr, families), mgr.value)
    )
    return [(mgr, ADAPTER_FACTORIES[mgr]()) for mgr in found]


def resolve_system_manager(families: Optional[list] = None) -> Optional[PackageManager]:
    """Return the first available native manager (prefers host family match)."""
    if families is None:
        families = distro_family()
    for mgr, _adapter in discover_managers(families):
        if tier(mgr) == PackageManagerTier.NATIVE:
            return mgr
    return None
