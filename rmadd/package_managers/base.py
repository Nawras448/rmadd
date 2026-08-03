"""Base package-manager abstraction, shared runner, discovery."""

import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from importlib import import_module
from typing import Callable, Optional

from rmadd.models import (
    Package,
    PackageManager,
    PackageManagerTier,
    PackageStatus,
    Repo,
    TIER_ORDER,
    meta,
    supports,
    tier,
)


def _strip_version(token: str) -> str:
    """Strip a trailing version suffix from a package token."""
    return re.sub(r"-\d.*$", "", token)


class BasePackageManager(ABC):
    """Uniform interface every package-manager backend implements."""

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
    def install(self, name, on_output=None, cancel_event=None) -> bool:
        pass

    @abstractmethod
    def remove(self, name, on_output=None, cancel_event=None) -> bool:
        pass

    @abstractmethod
    def update(self, name, on_output=None, cancel_event=None) -> bool:
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


class BaseAdapter(BasePackageManager):
    """Common backend: binary probing, command execution and privilege handling."""

    def __init__(self, manager: PackageManager):
        super().__init__(manager)
        self._available = any(
            shutil.which(binary) is not None for binary in self.binaries
        )

    @property
    def available(self) -> bool:
        return self._available

    def _run(self, cmd: list, timeout: int = 30) -> str:
        if not self._available:
            return ""
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout.strip()
        except Exception:
            return ""

    def _privilege_prefix(self) -> list:
        if os.geteuid() == 0:
            return []
        for tool in ("pkexec", "sudo"):
            if shutil.which(tool):
                return [tool]
        return []

    def _run_stream(
        self,
        cmd: list,
        on_output: Optional[Callable[[str], None]],
        cancel_event: Optional[threading.Event],
        timeout: int = 600,
        privileged: Optional[bool] = None,
    ) -> tuple:
        """Run a command, streaming output line by line.

        Returns (ok: bool, cancelled: bool). When cancel_event is set the
        process group is terminated (SIGTERM, then SIGKILL after a grace
        period). Output lines are delivered to on_output (may be None).
        The reader runs in a daemon thread so cancellation works even while
        the child process is silent (e.g. waiting at an auth prompt).
        """
        if not self._available:
            raise RuntimeError(f"{self._manager.value} is not available on this system")
        if privileged is None:
            privileged = self.needs_root
        if os.geteuid() == 0 or not privileged:
            candidates = [[]]
        else:
            candidates = [[t] for t in ("pkexec", "sudo") if shutil.which(t)]
        if not candidates:
            raise RuntimeError("No privilege escalation tool available (need pkexec or sudo)")

        tail: list[str] = []
        last_rc = 1
        last_cancelled = False
        for prefix in candidates:
            proc = None
            try:
                proc = subprocess.Popen(
                    prefix + cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                reader = threading.Thread(
                    target=self._drain, args=(proc, on_output, tail), daemon=True
                )
                reader.start()
                deadline = time.monotonic() + timeout
                while proc.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        last_cancelled = True
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError("Command timed out")
                    time.sleep(0.05)
                reader.join(timeout=2)
                last_rc = proc.returncode or 1
                if last_rc == 0:
                    return (True, False)
                err = "".join(tail).strip().lower()
                if last_cancelled:
                    return (False, True)
                if prefix and prefix[0] == "pkexec" and any(
                    w in err
                    for w in ("not authorized", "no authentication agent", "no polkit", "authentication required")
                ):
                    continue
                return (False, last_cancelled)
            finally:
                self._terminate(proc)
        return (False, last_cancelled)

    def _run_priv_stream(self, cmd, on_output=None, cancel_event=None, timeout=600) -> tuple:
        return self._run_stream(cmd, on_output, cancel_event, timeout, privileged=True)

    def _run_priv(self, cmd: list, timeout: int = 300) -> bool:
        ok, _ = self._run_stream(cmd, None, None, timeout)
        return ok

    @staticmethod
    def _drain(proc: subprocess.Popen, on_output, tail: list):
        strip_c0 = {7: None, 8: None, 27: None}  # \a \b \e
        try:
            for line in proc.stdout:
                line = line.translate(strip_c0)
                if tail is not None:
                    tail.append(line)
                    if len(tail) > 20:
                        tail.pop(0)
                if on_output is not None:
                    on_output(line)
        except Exception:
            pass

    @staticmethod
    def _terminate(proc: Optional[subprocess.Popen]):
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=2)
        except Exception:
            pass
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=2)
            except Exception:
                pass

    def install(self, name: str, on_output=None, cancel_event=None) -> bool:
        if not self.supports("install"):
            return False
        ok, _ = self._run_stream(self._install_cmd(name), on_output, cancel_event)
        return ok

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        if not self.supports("remove"):
            return False
        ok, _ = self._run_stream(self._remove_cmd(name), on_output, cancel_event)
        return ok

    def update(self, name: str, on_output=None, cancel_event=None) -> bool:
        if not self.supports("update"):
            return False
        ok, _ = self._run_stream(self._update_cmd(name), on_output, cancel_event)
        return ok

    def update_all(self, on_output=None, cancel_event=None) -> bool:
        if not self.supports("update_all"):
            return False
        ok, _ = self._run_stream(self._update_all_cmd(), on_output, cancel_event)
        return ok

    def search(self, query: str) -> list:
        if not self.supports("search"):
            return []
        return self._do_search(query)

    def _do_search(self, query: str) -> list:
        return []

    def _install_cmd(self, name: str) -> list:
        raise NotImplementedError

    def _remove_cmd(self, name: str) -> list:
        raise NotImplementedError

    def _update_cmd(self, name: str) -> list:
        raise NotImplementedError

    def _update_all_cmd(self) -> list:
        raise NotImplementedError

    def list_repos(self) -> list:
        return []


# =====================================================================
# Tier 1: native system package managers
# =====================================================================

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
    if manager in (PackageManager.APPIMAGE, PackageManager.LOCAL):
        return True
    return any(shutil.which(binary) is not None for binary in meta(manager).binaries)


def _family_rank(manager: PackageManager, families: list) -> int:
    if tier(manager) != PackageManagerTier.NATIVE or not families:
        return 0
    return 0 if any(f in meta(manager).families for f in families) else 1


ADAPTER_MODULES: dict[PackageManager, str] = {
    PackageManager.APT: "apt",
    PackageManager.DPKG: "dpkg",
    PackageManager.PACMAN: "pacman",
    PackageManager.DNF: "dnf",
    PackageManager.YUM: "yum",
    PackageManager.RPM: "rpm",
    PackageManager.ZYPPER: "zypper",
    PackageManager.APK: "apk",
    PackageManager.XBPS: "xbps",
    PackageManager.EMERGE: "emerge",
    PackageManager.NIX: "nix",
    PackageManager.EOPKG: "eopkg",
    PackageManager.SLACKPKG: "slackpkg",
    PackageManager.FLATPAK: "flatpak",
    PackageManager.SNAP: "snap",
    PackageManager.APPIMAGE: "appimage",
    PackageManager.BREW: "brew",
    PackageManager.PIP: "pip",
    PackageManager.PIPX: "pipx",
    PackageManager.CARGO: "cargo",
    PackageManager.NPM: "npm",
    PackageManager.PNPM: "pnpm",
    PackageManager.YARN: "yarn",
    PackageManager.BUN: "bun",
    PackageManager.GO: "go",
    PackageManager.GEM: "gem",
    PackageManager.COMPOSER: "composer",
    PackageManager.LOCAL: "local",
}


def adapter_class(manager: PackageManager) -> type:
    """Return the adapter class for a manager, importing its module lazily."""
    module = f".{ADAPTER_MODULES[manager]}"
    return import_module(module, __package__).Adapter


def discover_managers(families: Optional[list] = None, *, include_local: bool = False) -> list:
    """Discover available package managers in strict priority order.

    Returns a list of (PackageManager, adapter instance) ordered by:
    tier (Native first, then Universal, then Ecosystem), then host-family
    match for natives, then registry order.

    ``PackageManager.LOCAL`` (the PATH binary scanner) is excluded by
    default: probing arbitrary PATH executables is slow and has side
    effects. Use ``discover_local_scanner`` explicitly for the opt-in
    "Local binaries" view instead.
    """
    if families is None:
        families = distro_family()
    found = [
        mgr for mgr in PackageManager
        if (include_local or mgr != PackageManager.LOCAL) and is_available(mgr)
    ]
    found.sort(
        key=lambda mgr: (TIER_ORDER[tier(mgr)], _family_rank(mgr, families), mgr.value)
    )
    return [(mgr, adapter_class(mgr)()) for mgr in found]


def discover_local_scanner():
    """Build the (hardened) LOCAL binary adapter for the opt-in view."""
    from rmadd.package_managers.local import Adapter
    return Adapter()


def resolve_system_manager(families: Optional[list] = None) -> Optional[PackageManager]:
    """Return the first available native manager (prefers host family match)."""
    if families is None:
        families = distro_family()
    for mgr, _adapter in discover_managers(families):
        if tier(mgr) == PackageManagerTier.NATIVE:
            return mgr
    return None
