"""Standalone local-binary detection.

Scans user-level bin directories and the system $PATH for executables that
are not tracked by any registered package manager (e.g. manually downloaded
CLI/TUI tools like moviebox-tui) and exposes them through a file-based
PackageManager source (PackageManager.LOCAL).
"""

import os
import platform
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from features.package_store.ports import BasePackageManager
from features.package_store.domain import Package, PackageManager, PackageStatus

PRIORITY_DIRS = ("~/.local/bin", "~/bin", "/usr/local/bin")
FALLBACK_VERSION = "Standalone Binary"
MAX_PROBE_WORKERS = 8


class LocalBinaryScanner:
    """Collects and describes standalone executables in PATH-like dirs."""

    def __init__(self, search_dirs=None, extra_path=None, version_timeout=2, probe_limit=256):
        self._priority_dirs = [os.path.expanduser(d) for d in (search_dirs or PRIORITY_DIRS)]
        self._extra_path = extra_path
        self._version_timeout = version_timeout
        self._probe_limit = probe_limit
        self._version_cache: dict[str, tuple[int, str]] = {}
        self._lock = threading.Lock()

    def _search_directories(self) -> list:
        dirs = []
        seen = set()
        for d in self._priority_dirs:
            r = os.path.realpath(d)
            if r not in seen:
                seen.add(r)
                dirs.append(d)
        if self._extra_path is not None:
            path_entries = self._extra_path
        else:
            path_entries = os.environ.get("PATH", "").split(os.pathsep)
        for d in path_entries:
            d = d.strip()
            if not d:
                continue
            r = os.path.realpath(d)
            if r in seen:
                continue
            seen.add(r)
            dirs.append(d)
        return dirs

    def scan(self) -> list:
        """Return [(name, path)] candidates, first occurrence per name wins."""
        found = []
        names = set()
        for d in self._search_directories():
            if not os.path.isdir(d):
                continue
            try:
                entries = sorted(os.listdir(d))
            except OSError:
                continue
            for entry in entries:
                if entry.startswith(".") or entry in names:
                    continue
                path = os.path.join(d, entry)
                if os.path.isdir(path):
                    continue
                if not (os.path.isfile(path) or os.path.islink(path)):
                    continue
                if not os.access(path, os.X_OK):
                    continue
                names.add(entry)
                found.append((entry, path))
        return found

    def list_packages(self) -> list:
        candidates = self.scan()
        arch = platform.machine()
        to_probe = candidates[: self._probe_limit]
        rest = candidates[self._probe_limit :]
        versions = {}
        if to_probe:
            workers = min(MAX_PROBE_WORKERS, len(to_probe))
            with ThreadPoolExecutor(max_workers=workers) as ex:
                for (name, path), version in zip(
                    to_probe, ex.map(lambda item: self.probe_version(item[1]), to_probe)
                ):
                    versions[name] = version
        pkgs = []
        for name, path in to_probe:
            pkgs.append(self._make_package(name, path, versions[name], arch))
        for name, path in rest:
            pkgs.append(self._make_package(name, path, FALLBACK_VERSION, arch))
        return pkgs

    def find_path(self, name: str) -> Optional[str]:
        for _name, path in self.scan():
            if _name == name:
                return path
        return None

    @staticmethod
    def _make_package(name: str, path: str, version: str, arch: str) -> Package:
        return Package(
            name=name,
            version=version,
            arch=arch,
            summary=path,
            status=PackageStatus.INSTALLED,
            manager=PackageManager.LOCAL,
        )

    def probe_version(self, path: str) -> str:
        try:
            mtime = os.stat(path).st_mtime_ns
        except OSError:
            mtime = -1
        with self._lock:
            cached = self._version_cache.get(path)
            if cached is not None and cached[0] == mtime:
                return cached[1]
        version = self._probe(path)
        with self._lock:
            self._version_cache[path] = (mtime, version)
        return version

    def _probe(self, path: str) -> str:
        for flag in ("--version", "-v"):
            try:
                proc = subprocess.run(
                    [path, flag],
                    capture_output=True,
                    text=True,
                    timeout=self._version_timeout,
                )
            except Exception:
                continue
            for stream in (proc.stdout, proc.stderr):
                for raw in stream.splitlines():
                    line = raw.strip()
                    if line:
                        return line[:120]
        return FALLBACK_VERSION

    def invalidate(self, path: str):
        with self._lock:
            self._version_cache.pop(path, None)


class LocalBinaryAdapter(BasePackageManager):
    """File-based source: standalone executables found on PATH-like dirs."""

    def __init__(self, search_dirs=None, extra_path=None, version_timeout=2, probe_limit=256):
        super().__init__(PackageManager.LOCAL)
        self._scanner = LocalBinaryScanner(search_dirs, extra_path, version_timeout, probe_limit)

    def list_installed(self) -> list:
        return self._scanner.list_packages()

    def get_info(self, name: str) -> Optional[Package]:
        for pkg in self.list_installed():
            if pkg.name == name:
                return pkg
        return None

    def count(self) -> int:
        return len(self.list_installed())

    def search(self, query: str) -> list:
        return []

    def install(self, name: str, on_output=None, cancel_event=None) -> bool:
        return False

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        path = self._scanner.find_path(name)
        if not path:
            return False
        try:
            os.unlink(path)
            self._scanner.invalidate(path)
            return True
        except Exception as e:
            if on_output is not None:
                on_output(f"Error: {e}\n")
            return False

    def update(self, name: str, on_output=None, cancel_event=None) -> bool:
        return False

    def update_all(self, on_output=None, cancel_event=None) -> bool:
        return False

    def list_repos(self) -> list:
        return []
