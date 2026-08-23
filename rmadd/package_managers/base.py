"""Base package-manager abstraction, shared runner, discovery."""

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from importlib import import_module

from rmadd.models import (
    TIER_ORDER,
    Package,
    PackageManager,
    PackageManagerTier,
    PackageStatus,
    meta,
    supports,
    tier,
)


def _strip_version(token: str) -> str:
    """Strip a trailing version suffix from a package token."""
    return re.sub(r"-\d.*$", "", token)


# =====================================================================
# Operation results: rich failure contexts (Milestone 2)
# =====================================================================

DEFAULT_AUTH_TIMEOUT_SECONDS: float = 120.0
DEFAULT_EXECUTION_TIMEOUT_SECONDS: float = 600.0

_PKEXEC_DENIAL_MARKERS = (
    "not authorized",
    "no authentication agent",
    "no polkit",
    "authentication required",
)


class FailureReason(str, Enum):
    """Why a streamed operation did not succeed (NONE implies success)."""

    NONE = "none"
    CANCELLED = "cancelled"
    AUTH_DENIED = "auth_denied"
    AUTH_UNAVAILABLE = "auth_unavailable"
    AUTH_TIMEOUT = "auth_timeout"
    TIMEOUT = "timeout"
    MANAGER_MISSING = "manager_missing"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


FAILURE_DESCRIPTIONS: dict[FailureReason, str] = {
    FailureReason.NONE: "completed",
    FailureReason.CANCELLED: "cancelled by user",
    FailureReason.AUTH_DENIED: "authentication denied",
    FailureReason.AUTH_UNAVAILABLE: "no privilege escalation tool available (need pkexec or sudo)",
    FailureReason.AUTH_TIMEOUT: "timed out waiting for authentication",
    FailureReason.TIMEOUT: "command timed out",
    FailureReason.MANAGER_MISSING: "package manager is not available on this system",
    FailureReason.UNSUPPORTED: "operation not supported by this package manager",
    FailureReason.FAILED: "command failed",
}


@dataclass(frozen=True)
class OpResult:
    """Rich outcome of a streamed command execution.

    ``ok``/``cancelled`` mirror the historical tuple semantics; ``reason``
    carries the failure context (see :class:`FailureReason`) and ``tail``
    the last output lines for diagnostics.
    """

    ok: bool
    cancelled: bool = False
    reason: FailureReason = FailureReason.NONE
    tail: str = ""

    def describe(self) -> str:
        return FAILURE_DESCRIPTIONS[self.reason]


@dataclass
class OpReport:
    """Aggregate of per-target OpResults for batch operations.

    Individual failures are isolated: one bad target never drops the rest
    of the report. `ok` is True for an empty batch (nothing to do).
    """

    entries: list[tuple[str, OpResult]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for _k, r in self.entries)

    @property
    def cancelled(self) -> bool:
        return any(r.cancelled for _k, r in self.entries)

    @property
    def failures(self) -> list[tuple[str, OpResult]]:
        return [(k, r) for k, r in self.entries if not r.ok]

    def describe(self) -> str:
        if not self.entries:
            return "nothing executed"
        parts: list[str] = []
        failed = self.failures
        parts.append(f"{len(self.entries) - len(failed)}/{len(self.entries)} succeeded")
        if self.cancelled:
            parts.append("cancelled")
        if failed:
            parts.append(
                "failed: " + ", ".join(f"{k} ({r.describe()})" for k, r in failed)
            )
        if self.skipped:
            parts.append("skipped: " + ", ".join(self.skipped))
        return "; ".join(parts)


def _tail_text(tail: list, limit: int = 2000) -> str:
    """Join the rolling output tail, bounded for result payloads."""
    return "".join(tail).strip()[-limit:]


_execution_timeout_override: float | None = None


def set_default_execution_timeout(seconds: float) -> None:
    """Runtime override applied to adapters created from now on.

    Used by `Config.op_timeout_seconds`'s setter; validation happens here so
    every entry point shares one guard.
    """
    global _execution_timeout_override
    value = float(seconds)
    if value <= 0:
        raise ValueError("op_timeout_seconds must be positive")
    _execution_timeout_override = value


def _configured_execution_timeout() -> float:
    """Execution budget for new adapters: runtime override, else config."""
    if _execution_timeout_override is not None:
        return _execution_timeout_override
    try:
        from rmadd.config import Config

        value = float(Config().op_timeout_seconds)
    except Exception:
        return DEFAULT_EXECUTION_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_EXECUTION_TIMEOUT_SECONDS


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
    def get_info(self, name: str) -> Package | None:
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

    def __init__(
        self,
        manager: PackageManager,
        *,
        auth_timeout: float | None = None,
        execution_timeout: float | None = None,
    ):
        super().__init__(manager)
        self._available = any(
            shutil.which(binary) is not None for binary in self.binaries
        )
        # Two-phase deadlines: auth budget covers silent polkit/sudo prompts;
        # execution budget governs the run after the first output line.
        self.auth_timeout = (
            auth_timeout if auth_timeout is not None else DEFAULT_AUTH_TIMEOUT_SECONDS
        )
        self.execution_timeout = (
            execution_timeout
            if execution_timeout is not None
            else _configured_execution_timeout()
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

    def run_stream(
        self,
        cmd: list,
        on_output: Callable[[str], None] | None = None,
        cancel_event: threading.Event | None = None,
        timeout: float | None = None,
        privileged: bool | None = None,
    ) -> OpResult:
        """Run a command, streaming output line by line.

        Two-phase deadlines: while the child produces NO output the auth
        budget applies (polkit/sudo prompts stall silently); once the first
        line arrives the execution budget governs the remainder.

        Returns an OpResult instead of raising: preconditions surface as
        MANAGER_MISSING / AUTH_UNAVAILABLE, silent stalls as AUTH_TIMEOUT,
        overruns as TIMEOUT, user aborts as CANCELLED. A pkexec denial
        triggers a fallback attempt with the next escalation tool.

        The reader runs in a daemon thread so cancellation works even while
        the child process is silent (e.g. waiting at an auth prompt).
        """
        if not self._available:
            return OpResult(False, reason=FailureReason.MANAGER_MISSING)
        if privileged is None:
            privileged = self.needs_root
        if os.geteuid() == 0 or not privileged:
            candidates: list[list] = [[]]
        else:
            # Resolve each escalation tool to its absolute path at probe
            # time so Popen executes exactly the inspected binary rather
            # than re-resolving the name (and possibly a different one)
            # through PATH.
            candidates = []
            for tool in ("pkexec", "sudo"):
                resolved = shutil.which(tool)
                if resolved:
                    candidates.append([resolved])
            if not candidates:
                return OpResult(False, reason=FailureReason.AUTH_UNAVAILABLE)

        exec_budget = float(timeout) if timeout is not None else float(self.execution_timeout)
        auth_budget = float(self.auth_timeout)

        tail: list[str] = []
        lines_seen = [0]
        last_cancelled = False
        saw_denial = False

        for prefix in candidates:
            proc = None
            reader = None
            pgid: int | None = None
            try:
                proc = subprocess.Popen(
                    prefix + cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    start_new_session=True,
                )
                try:
                    pgid = os.getpgid(proc.pid)
                except OSError:
                    pgid = proc.pid  # process already reaped; fall back to pid
                reader = threading.Thread(
                    target=self._drain,
                    args=(proc, on_output, tail, lines_seen),
                    daemon=True,
                )
                reader.start()

                started = time.monotonic()
                timed_out: FailureReason | None = None
                while proc.poll() is None:
                    if cancel_event is not None and cancel_event.is_set():
                        last_cancelled = True
                        break
                    elapsed = time.monotonic() - started
                    budget = exec_budget if lines_seen[0] > 0 else auth_budget
                    if elapsed > budget:
                        timed_out = (
                            FailureReason.TIMEOUT
                            if lines_seen[0] > 0
                            else FailureReason.AUTH_TIMEOUT
                        )
                        break
                    time.sleep(0.05)

                if timed_out is not None:
                    return OpResult(False, last_cancelled, timed_out, _tail_text(tail))

                # Child exited on its own: let the drain thread finish
                # flushing the pipe so tail/lines_seen are complete before
                # the outcome is classified (avoids sampling an empty tail).
                if reader is not None:
                    reader.join(timeout=1.0)

                if proc.poll() is not None and proc.returncode == 0:
                    return OpResult(True, False, FailureReason.NONE, _tail_text(tail))
                if last_cancelled:
                    return OpResult(False, True, FailureReason.CANCELLED, _tail_text(tail))

                err = _tail_text(tail).lower()
                if (
                    prefix
                    and os.path.basename(prefix[0]) == "pkexec"
                    and any(w in err for w in _PKEXEC_DENIAL_MARKERS)
                ):
                    saw_denial = True
                    continue
                return OpResult(False, last_cancelled, FailureReason.FAILED, _tail_text(tail))
            finally:
                if reader is not None:
                    reader.join(timeout=2)
                self._terminate(proc, pgid)

        reason = (
            FailureReason.CANCELLED
            if last_cancelled
            else (FailureReason.AUTH_DENIED if saw_denial else FailureReason.FAILED)
        )
        return OpResult(False, last_cancelled, reason, _tail_text(tail))

    def _run_priv_stream(self, cmd, on_output=None, cancel_event=None, timeout=600) -> OpResult:
        return self.run_stream(cmd, on_output, cancel_event, timeout, privileged=True)

    def _run_priv(self, cmd: list, timeout: int = 300) -> bool:
        return self.run_stream(cmd, None, None, timeout).ok

    @staticmethod
    def _drain(proc: subprocess.Popen, on_output, tail: list, lines_seen: list | None = None):
        strip_c0 = {7: None, 8: None, 27: None}  # \a \b \e
        try:
            stream = proc.stdout
            if stream is None:
                return
            for line in stream:
                line = line.translate(strip_c0)
                if tail is not None:
                    tail.append(line)
                    if len(tail) > 20:
                        tail.pop(0)
                if lines_seen is not None:
                    lines_seen[0] += 1
                if on_output is not None:
                    on_output(line)
        except Exception:
            pass

    @staticmethod
    def _terminate(proc: subprocess.Popen | None, pgid: int | None = None):
        """SIGTERM the process group, then SIGKILL after a grace period.

        Termination targets the captured pgid (pid-reuse safe); falls back
        to proc.pid when no group was captured.
        """
        if proc is None or proc.poll() is not None:
            return
        target = pgid if pgid is not None else proc.pid
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(target, sig)
                proc.wait(timeout=2)
            except Exception:
                pass
            if proc.poll() is not None:
                return
        # Last resort if the group signal never landed.
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass

    def _run_op(
        self,
        op: str,
        name: str | None,
        on_output=None,
        cancel_event=None,
    ) -> OpResult:
        """Dispatch a mutating operation to its command builder + runner."""
        if not self.supports(op):
            return OpResult(False, reason=FailureReason.UNSUPPORTED)
        builders = {
            "install": lambda: self._install_cmd(name or ""),
            "remove": lambda: self._remove_cmd(name or ""),
            "update": lambda: self._update_cmd(name or ""),
            "update_all": self._update_all_cmd,
        }
        cmd = builders[op]()
        return self.run_stream(cmd, on_output, cancel_event)

    def install(self, name: str, on_output=None, cancel_event=None) -> bool:
        return self._run_op("install", name, on_output, cancel_event).ok

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        return self._run_op("remove", name, on_output, cancel_event).ok

    def update(self, name: str, on_output=None, cancel_event=None) -> bool:
        return self._run_op("update", name, on_output, cancel_event).ok

    def update_all(self, on_output=None, cancel_event=None) -> bool:
        return self._run_op("update_all", None, on_output, cancel_event).ok

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


def discover_managers(families: list | None = None, *, include_local: bool = False) -> list:
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


def resolve_system_manager(families: list | None = None) -> PackageManager | None:
    """Return the first available native manager (prefers host family match)."""
    if families is None:
        families = distro_family()
    for mgr, _adapter in discover_managers(families):
        if tier(mgr) == PackageManagerTier.NATIVE:
            return mgr
    return None
