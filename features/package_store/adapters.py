import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from typing import Callable, Optional

from features.package_store.ports import BasePackageManager
from features.package_store.domain import Package, PackageManager, PackageStatus, Repo


def _strip_version(token: str) -> str:
    """Strip a trailing version suffix from a package token."""
    return re.sub(r"-\d.*$", "", token)


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


class AptAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.APT)

    def list_installed(self) -> list:
        out = self._run(["dpkg-query", "-f", "${binary:Package}|${Version}|${Architecture}|${binary:Summary}\n", "-W"], timeout=60)
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["apt-cache", "search", query])
        pkgs = []
        for line in out.split("\n"):
            name, _, rest = line.partition(" - ")
            if name.strip():
                pkgs.append(Package(name=name.strip(), summary=rest.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["apt-cache", "show", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "package": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "architecture": pkg.arch = v
            elif k == "description": pkg.summary = v
            elif k == "filename-size": pkg.size = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["dpkg-query", "-f", "${binary:Package}\n", "-W"])
        return len(out.split("\n")) if out else 0

    def _install_cmd(self, name: str) -> list: return ["apt", "install", "-y", name]
    def _remove_cmd(self, name: str) -> list: return ["apt", "remove", "-y", name]
    def _update_cmd(self, name: str) -> list: return ["apt", "install", "--only-upgrade", "-y", name]
    def _update_all_cmd(self) -> list: return ["apt", "upgrade", "-y"]

    def list_repos(self) -> list:
        repos = []
        try:
            with open("/etc/apt/sources.list") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "deb " in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            repos.append(Repo(name=parts[1]))
        except Exception:
            pass
        return repos


class DpkgAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.DPKG)

    def list_installed(self) -> list:
        out = self._run(["dpkg-query", "-f", "${binary:Package}|${Version}|${Architecture}|${binary:Summary}\n", "-W"], timeout=60)
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["dpkg-query", "-s", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "package": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "architecture": pkg.arch = v
            elif k == "description": pkg.summary = v
            elif k == "installed-size": pkg.size = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["dpkg-query", "-f", "${binary:Package}\n", "-W"])
        return len(out.split("\n")) if out else 0

    def _remove_cmd(self, name: str) -> list: return ["dpkg", "-r", name]


class PacmanAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.PACMAN)

    def list_installed(self) -> list:
        out = self._run(["pacman", "-Qq"])
        return [Package(name=n, manager=self._manager) for n in out.split("\n") if n]

    def _do_search(self, query: str) -> list:
        out = self._run(["pacman", "-Ss", query])
        pkgs = []
        for line in out.split("\n"):
            if not line or line.startswith(" "):
                continue
            parts = line.split()
            if len(parts) >= 2:
                pkgs.append(Package(name=parts[1].split("/")[-1] if "/" in parts[1] else parts[1],
                                    summary=" ".join(parts[2:]) if len(parts) > 2 else "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["pacman", "-Qi", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "architecture": pkg.arch = v
            elif k == "description": pkg.summary = v
            elif k == "installed size": pkg.size = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["pacman", "-Qq"])
        return len(out.split("\n")) if out else 0

    def _install_cmd(self, name: str) -> list: return ["pacman", "-S", "--noconfirm", name]
    def _remove_cmd(self, name: str) -> list: return ["pacman", "-R", "--noconfirm", name]
    def _update_cmd(self, name: str) -> list: return ["pacman", "-S", "--noconfirm", name]
    def _update_all_cmd(self) -> list: return ["pacman", "-Syu", "--noconfirm"]

    def list_repos(self) -> list:
        repos = []
        try:
            with open("/etc/pacman.conf") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("[") and line.endswith("]") and line[1:-1] not in ("options", "options "):
                        repos.append(Repo(name=line[1:-1]))
        except Exception:
            pass
        return repos


class DnfAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.DNF)

    def list_installed(self) -> list:
        out = self._run(["rpm", "-qa", "--queryformat", "%{NAME}|%{VERSION}|%{ARCH}|%{SUMMARY}\n"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["dnf", "search", query, "--quiet"])
        pkgs = []
        for line in out.split("\n"):
            if not line or "====" in line:
                continue
            parts = line.split(":", 1)
            pkgs.append(Package(name=parts[0].strip(), summary=parts[1].strip() if len(parts) > 1 else "",
                                manager=self._manager, status=PackageStatus.AVAILABLE))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["dnf", "info", name, "--quiet"])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "arch": pkg.arch = v
            elif k == "summary": pkg.summary = v
            elif k == "repo": pkg.repo = v
            elif k == "size": pkg.size = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["rpm", "-qa"])
        return len(out.split("\n")) if out else 0

    def _install_cmd(self, name: str) -> list: return ["dnf", "install", "-y", name]
    def _remove_cmd(self, name: str) -> list: return ["dnf", "remove", "-y", name]
    def _update_cmd(self, name: str) -> list: return ["dnf", "update", "-y", name]
    def _update_all_cmd(self) -> list: return ["dnf", "update", "-y"]

    def list_repos(self) -> list:
        out = self._run(["dnf", "repolist", "--verbose"])
        repos = []
        for line in out.split("\n"):
            if "repo id" in line.lower():
                continue
            parts = line.split()
            if parts:
                repos.append(Repo(name=parts[0]))
        return repos


class YumAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.YUM)

    def list_installed(self) -> list:
        out = self._run(["rpm", "-qa", "--queryformat", "%{NAME}|%{VERSION}|%{ARCH}|%{SUMMARY}\n"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["yum", "search", query, "-q"])
        pkgs = []
        for line in out.split("\n"):
            if not line or "====" in line or ":" not in line:
                continue
            parts = line.split(":", 1)
            pkgs.append(Package(name=parts[0].strip(), summary=parts[1].strip() if len(parts) > 1 else "",
                                manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["yum", "info", name, "-q"])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "arch": pkg.arch = v
            elif k == "summary": pkg.summary = v
            elif k == "repo": pkg.repo = v
            elif k == "size": pkg.size = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["rpm", "-qa"])
        return len(out.split("\n")) if out else 0

    def _install_cmd(self, name: str) -> list: return ["yum", "install", "-y", name]
    def _remove_cmd(self, name: str) -> list: return ["yum", "remove", "-y", name]
    def _update_cmd(self, name: str) -> list: return ["yum", "update", "-y", name]
    def _update_all_cmd(self) -> list: return ["yum", "update", "-y"]


class RpmAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.RPM)

    def list_installed(self) -> list:
        out = self._run(["rpm", "-qa", "--queryformat", "%{NAME}|%{VERSION}|%{ARCH}|%{SUMMARY}\n"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["rpm", "-qi", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "architecture": pkg.arch = v
            elif k == "summary": pkg.summary = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["rpm", "-qa"])
        return len(out.split("\n")) if out else 0

    def _remove_cmd(self, name: str) -> list: return ["rpm", "-e", name]


class ZypperAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.ZYPPER)

    def list_installed(self) -> list:
        out = self._run(["rpm", "-qa", "--queryformat", "%{NAME}|%{VERSION}|%{ARCH}|%{SUMMARY}\n"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["zypper", "se", query])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 2 and parts[1].strip() and not parts[0].strip().upper().startswith("S"):
                pkgs.append(Package(name=parts[1].strip(),
                                    summary=parts[2].strip() if len(parts) > 2 else "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["zypper", "info", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "arch": pkg.arch = v
            elif k == "summary": pkg.summary = v
            elif k == "repository": pkg.repo = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["rpm", "-qa"])
        return len(out.split("\n")) if out else 0

    def _install_cmd(self, name: str) -> list: return ["zypper", "install", "-y", name]
    def _remove_cmd(self, name: str) -> list: return ["zypper", "remove", "-y", name]
    def _update_cmd(self, name: str) -> list: return ["zypper", "update", "-y", name]
    def _update_all_cmd(self) -> list: return ["zypper", "update", "-y"]


class ApkAdapter(BaseAdapter):
    _APK_ARCH = r"(x86_64|aarch64|armhf|armv7|ppc64le|s390x|riscv64)"

    def __init__(self):
        super().__init__(PackageManager.APK)

    @staticmethod
    def _parse_token(token: str) -> tuple:
        m = re.match(r"^(?P<name>.+?)-(?P<version>\d[\w.]*-r\d+)-(?P<arch>\w+)$", token)
        if m:
            return m.group("name"), m.group("version"), m.group("arch")
        return _strip_version(token), "", ""

    def list_installed(self) -> list:
        out = self._run(["apk", "list", "--installed"])
        pkgs = []
        for line in out.split("\n"):
            token = line.split()[0] if line.split() else ""
            if not token:
                continue
            name, version, arch = self._parse_token(token)
            pkgs.append(Package(name=name, version=version, arch=arch, manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["apk", "search", query])
        pkgs = []
        for line in out.split("\n"):
            token = line.split()[0] if line.split() else ""
            if token:
                pkgs.append(Package(name=_strip_version(token), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["apk", "info", "-a", name])
        if not out:
            return None
        pkg = Package(manager=self._manager, name=name)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "version": pkg.version = v
            elif k == "description": pkg.summary = v
            elif k == "size": pkg.size = v
        return pkg

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["apk", "add", name]
    def _remove_cmd(self, name: str) -> list: return ["apk", "del", name]
    def _update_cmd(self, name: str) -> list: return ["apk", "add", "-u", name]
    def _update_all_cmd(self) -> list: return ["apk", "upgrade"]


class XbpsAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.XBPS)
        self._query = "xbps-query"
        self._install = "xbps-install"
        self._remove = "xbps-remove"

    def list_installed(self) -> list:
        out = self._run([self._query, "-l"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                pkgs.append(Package(name=_strip_version(parts[1]), manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run([self._query, "-Rs", query])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                pkgs.append(Package(name=_strip_version(parts[1]),
                                    summary=" ".join(parts[2:]) if len(parts) > 2 else "",
                                    manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run([self._query, "-Si", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "pkgname": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "architecture": pkg.arch = v
            elif k == "short_desc": pkg.summary = v
        return pkg if pkg.name else None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return [self._install, "-y", name]
    def _remove_cmd(self, name: str) -> list: return [self._remove, "-y", name]
    def _update_cmd(self, name: str) -> list: return [self._install, "-y", "-u", name]
    def _update_all_cmd(self) -> list: return [self._install, "-Su", "-y"]


class EmergeAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.EMERGE)

    def list_installed(self) -> list:
        pkgs = []
        try:
            base = "/var/db/pkg"
            for cat in os.listdir(base):
                cat_path = os.path.join(base, cat)
                if not os.path.isdir(cat_path):
                    continue
                for entry in os.listdir(cat_path):
                    pkgs.append(Package(name=f"{cat}/{entry}", manager=self._manager))
        except Exception:
            pass
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["eix", "-e", query]) or self._run(["emerge", "--search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^\[[^\]]*\]\s+(\S+)\s+(.*)$", line)
            if not m:
                continue
            pkgs.append(Package(name=m.group(1), summary=m.group(2).strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["equery", "list", "-e", name]) or self._run(["emerge", "-pv", name])
        if not out:
            return None
        return Package(name=name, summary=out.split("\n")[0][:120], manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["emerge", "--ask=n", "--noreplace", name]
    def _remove_cmd(self, name: str) -> list: return ["emerge", "--ask=n", "--unmerge", name]
    def _update_cmd(self, name: str) -> list: return ["emerge", "--ask=n", "--update", name]
    def _update_all_cmd(self) -> list: return ["emerge", "--ask=n", "--update", "--deep", "@world"]


class NixAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.NIX)
        self._profile = shutil.which("nix") is not None

    @staticmethod
    def _attr_name(token: str) -> str:
        if "#" in token:
            return token.rsplit("#", 1)[-1]
        if ":" in token:
            return token.rsplit(":", 1)[-1]
        return token

    def list_installed(self) -> list:
        if self._profile:
            out = self._run(["nix", "profile", "list"])
            pkgs = []
            for line in out.split("\n"):
                parts = line.split()
                if len(parts) >= 3:
                    token = parts[3] if len(parts) > 3 else parts[2]
                    name = self._attr_name(token)
                    if name and not name.startswith("/"):
                        pkgs.append(Package(name=name, manager=self._manager))
            return pkgs
        out = self._run(["nix-env", "-q"])
        return [Package(name=n, manager=self._manager) for n in out.split("\n") if n]

    def _do_search(self, query: str) -> list:
        if not self._profile:
            return []
        out = self._run(["nix", "search", "nixpkgs", query], timeout=60)
        pkgs = []
        for line in out.split("\n"):
            name_part, _, desc = line.partition("\t")
            if not name_part.strip():
                continue
            name = self._attr_name(name_part.strip().split()[0])
            m = re.search(r"\((.*?)\)", name_part)
            version = m.group(1) if m else ""
            pkgs.append(Package(name=name, version=version, summary=desc.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list:
        return ["nix", "profile", "install", f"nixpkgs#{name}"] if self._profile else ["nix-env", "-i", name]

    def _remove_cmd(self, name: str) -> list:
        return ["nix", "profile", "remove", name] if self._profile else ["nix-env", "-e", name]

    def _update_cmd(self, name: str) -> list:
        return ["nix", "profile", "upgrade", name] if self._profile else ["nix-env", "-u", name]

    def _update_all_cmd(self) -> list:
        return ["nix", "profile", "upgrade"] if self._profile else ["nix-env", "-u"]


class EopkgAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.EOPKG)

    def list_installed(self) -> list:
        out = self._run(["eopkg", "list-installed"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split()
            if parts:
                pkgs.append(Package(name=_strip_version(parts[0]), manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["eopkg", "search", query])
        pkgs = []
        for line in out.split("\n"):
            name, _, rest = line.partition(" - ")
            if name.strip():
                pkgs.append(Package(name=name.strip(), summary=rest.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["eopkg", "info", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "summary": pkg.summary = v
        return pkg if pkg.name else None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["eopkg", "install", "-y", name]
    def _remove_cmd(self, name: str) -> list: return ["eopkg", "remove", "-y", name]
    def _update_cmd(self, name: str) -> list: return ["eopkg", "install", "-y", name]
    def _update_all_cmd(self) -> list: return ["eopkg", "upgrade", "-y"]


class SlackpkgAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.SLACKPKG)

    def list_installed(self) -> list:
        pkgs = []
        try:
            for entry in os.listdir("/var/log/packages"):
                pkgs.append(Package(name=entry, manager=self._manager))
        except Exception:
            pass
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["slackpkg", "search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.search(r"\[ installed \]|\[ uninstalled \]\s+(\S+)", line)
            if m:
                pkgs.append(Package(name=m.group(1) if m.group(1) else "", manager=self._manager))
                continue
            m2 = re.search(r"^(\S+):", line)
            if m2 and "Package" not in line:
                pkgs.append(Package(name=m2.group(1), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["slackpkg", "-batch=on", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["slackpkg", "remove", name]


# =====================================================================
# Tier 2: universal packaging formats
# =====================================================================


class FlatpakAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.FLATPAK)

    @staticmethod
    def _is_header(line: str) -> bool:
        first = line.split("\t")[0].lower()
        if first not in ("name", "application"):
            return False
        return any(w in line.lower() for w in ("application id", "description", "branch", "remotes", "options", "version"))

    def _iter_rows(self, out: str) -> list:
        lines = [ln for ln in out.split("\n") if ln.strip()]
        if lines and self._is_header(lines[0]):
            lines = lines[1:]
        return lines

    def list_installed(self) -> list:
        pkgs = []
        for line in self._iter_rows(self._run(["flatpak", "list", "--columns=application,version,arch", "--app"])):
            parts = line.split("\t")
            if parts[0].strip():
                pkgs.append(Package(name=parts[0].strip(), version=parts[1].strip() if len(parts) > 1 else "",
                                    arch=parts[2].strip() if len(parts) > 2 else "", manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        pkgs = []
        for line in self._iter_rows(self._run(["flatpak", "search", query])):
            parts = line.split("\t")
            if parts and parts[0].strip():
                name = parts[2].strip() if len(parts) > 2 else parts[0].strip()
                summary = parts[1].strip() if len(parts) > 1 else ""
                pkgs.append(Package(name=name, summary=summary, manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["flatpak", "info", name])
        if not out:
            return None
        pkg = Package(manager=self._manager, name=name)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "version": pkg.version = v
            elif k == "arch": pkg.arch = v
        return pkg

    def count(self) -> int:
        return len(self._iter_rows(self._run(["flatpak", "list", "--app"])))

    def _install_cmd(self, name: str) -> list: return ["flatpak", "install", "--noninteractive", "-y", name]
    def _remove_cmd(self, name: str) -> list: return ["flatpak", "uninstall", "--noninteractive", "-y", name]
    def _update_cmd(self, name: str) -> list: return ["flatpak", "update", "--noninteractive", "-y", name]
    def _update_all_cmd(self) -> list: return ["flatpak", "update", "--noninteractive", "-y"]

    def list_repos(self) -> list:
        return [Repo(name=line.split()[0]) for line in self._iter_rows(self._run(["flatpak", "remotes"]))]


class SnapAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.SNAP)

    def list_installed(self) -> list:
        out = self._run(["snap", "list"])
        pkgs = []
        for line in out.split("\n")[1:]:
            parts = line.split()
            if parts:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "", manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["snap", "find", query])
        pkgs = []
        for line in out.split("\n")[1:]:
            parts = line.split()
            if parts:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    summary=" ".join(parts[2:]) if len(parts) > 2 else "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["snap", "info", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k in ("version", "installed"): pkg.version = v.split("-")[0] if v else ""
            elif k == "summary": pkg.summary = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["snap", "list"])
        return max(0, len(out.split("\n")) - 1) if out else 0

    def _install_cmd(self, name: str) -> list: return ["snap", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["snap", "remove", name]
    def _update_cmd(self, name: str) -> list: return ["snap", "refresh", name]
    def _update_all_cmd(self) -> list: return ["snap", "refresh"]


class BrewAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.BREW)

    def list_installed(self) -> list:
        out = self._run(["brew", "list", "--formula"])
        return [Package(name=n, manager=self._manager) for n in out.split("\n") if n]

    def _do_search(self, query: str) -> list:
        out = self._run(["brew", "search", query])
        pkgs = []
        for line in out.split("\n"):
            if not line or "===" in line:
                continue
            for token in line.split():
                if token.startswith("formulae") or token.startswith("casks"):
                    continue
                pkgs.append(Package(name=token, manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["brew", "info", "--json=v2", name])
        if not out:
            return None
        try:
            data = json.loads(out)
            formulae = data.get("formulae") or []
            if not formulae:
                return None
            f = formulae[0]
            return Package(name=f.get("name", name), version=(f.get("versions") or {}).get("stable", ""),
                           summary=f.get("desc", ""), manager=self._manager)
        except Exception:
            return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["brew", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["brew", "uninstall", name]
    def _update_cmd(self, name: str) -> list: return ["brew", "upgrade", name]
    def _update_all_cmd(self) -> list: return ["brew", "upgrade"]


class AppImageAdapter(BaseAdapter):
    """File-based source: manages *.AppImage files on disk (no binary)."""

    DEFAULT_DIRS = ("~/Applications", "~/.local/bin", "/opt")

    def __init__(self, dirs=None, install_dir: Optional[str] = None):
        super().__init__(PackageManager.APPIMAGE)
        self._available = True
        self._dirs = dirs or self.DEFAULT_DIRS
        self._install_dir = install_dir or os.path.expanduser("~/Applications")

    def _expanded_dirs(self) -> list:
        return [os.path.expanduser(d) for d in self._dirs]

    def _find_path(self, name: str) -> Optional[str]:
        for d in self._expanded_dirs():
            if not os.path.isdir(d):
                continue
            for entry in os.listdir(d):
                if entry.lower().endswith(".appimage") and os.path.splitext(entry)[0] == name:
                    return os.path.join(d, entry)
        return None

    def list_installed(self) -> list:
        pkgs = []
        for d in self._expanded_dirs():
            if not os.path.isdir(d):
                continue
            for entry in sorted(os.listdir(d)):
                path = os.path.join(d, entry)
                if os.path.isfile(path) and entry.lower().endswith(".appimage"):
                    pkgs.append(Package(name=os.path.splitext(entry)[0], summary=path,
                                        size=f"{os.path.getsize(path) // (1024 * 1024)} MB",
                                        manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        path = self._find_path(name)
        if not path:
            return None
        return Package(name=name, summary=path,
                       size=f"{os.path.getsize(path) // (1024 * 1024)} MB", manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def install(self, name: str, on_output=None, cancel_event=None, source_path=None) -> bool:
        if not source_path or not os.path.isfile(source_path):
            if on_output is not None:
                on_output("Error: no valid .AppImage source file\n")
            return False
        try:
            target_dir = self._install_dir
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, os.path.basename(source_path))
            if not target.lower().endswith(".appimage"):
                target += ".AppImage"
            import shutil as _sh
            if on_output is not None:
                on_output(f"Installing {os.path.basename(target)} into {target_dir}\n")
            _sh.copy2(source_path, target)
            os.chmod(target, 0o755)
            return True
        except Exception as e:
            if on_output is not None:
                on_output(f"Error: {e}\n")
            return False

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        path = self._find_path(name)
        if not path:
            if on_output is not None:
                on_output(f"Error: {name}.AppImage not found\n")
            return False
        try:
            os.remove(path)
            return True
        except Exception as e:
            if on_output is not None:
                on_output(f"Error: {e}\n")
            return False

    def update(self, name: str, on_output=None, cancel_event=None) -> bool:
        return False

    def update_all(self, on_output=None, cancel_event=None) -> bool:
        return False


# =====================================================================
# Tier 3: language & developer ecosystem managers (user-level)
# =====================================================================


class PipAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.PIP)
        self._pip = "pip3" if shutil.which("pip3") else "pip"

    def list_installed(self) -> list:
        out = self._run([self._pip, "list", "--format=freeze"])
        pkgs = []
        for line in out.split("\n"):
            name, sep, version = line.partition("==")
            if name.strip() and sep:
                pkgs.append(Package(name=name.strip(), version=version.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run([self._pip, "show", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "summary": pkg.summary = v
            elif k == "home-page": pkg.repo = v
        return pkg if pkg.name else None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return [self._pip, "install", "--user", name]
    def _remove_cmd(self, name: str) -> list: return [self._pip, "uninstall", "-y", name]
    def _update_cmd(self, name: str) -> list: return [self._pip, "install", "--user", "--upgrade", name]


class PipxAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.PIPX)

    def list_installed(self) -> list:
        out = self._run(["pipx", "list", "--json"])
        pkgs = []
        try:
            data = json.loads(out)
            for name, info in (data.get("venvs") or {}).items():
                main = (info.get("metadata") or {}).get("main_package") or {}
                pkgs.append(Package(name=main.get("package") or name,
                                    version=main.get("package_version", ""), manager=self._manager))
        except Exception:
            pass
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["pipx", "list", "--json"])
        try:
            data = json.loads(out)
            for _name, info in (data.get("venvs") or {}).items():
                main = (info.get("metadata") or {}).get("main_package") or {}
                if main.get("package") == name:
                    return Package(name=name, version=main.get("package_version", ""), manager=self._manager)
        except Exception:
            pass
        return None

    def count(self) -> int:
        return len(self.list_installed())

    def _do_search(self, query: str) -> list:
        pkgs = []
        try:
            import socket
            import xmlrpc.client
            socket.setdefaulttimeout(10)
            proxy = xmlrpc.client.ServerProxy("https://pypi.org/pypi")
            for hit in proxy.search({"name": query}, "or")[:20]:
                pkgs.append(Package(
                    name=hit.get("name", ""),
                    version=str(hit.get("latest_version") or ""),
                    summary=str(hit.get("summary") or ""),
                    manager=self._manager,
                ))
        except Exception:
            pass
        return pkgs

    def _install_cmd(self, name: str) -> list: return ["pipx", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["pipx", "uninstall", name]
    def _update_cmd(self, name: str) -> list: return ["pipx", "upgrade", name]


class CargoAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.CARGO)

    def list_installed(self) -> list:
        out = self._run(["cargo", "install", "--list"])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^\s*(\S+)\s+v?([\w.\-+]+):", line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2), manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["cargo", "search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^(\S+)\s+=\s+\"([^\"]*)\"\s*(?:#\s*(.*))?$", line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2),
                                    summary=(m.group(3) or "").strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["cargo", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["cargo", "uninstall", name]
    def _update_cmd(self, name: str) -> list: return ["cargo", "install", name]


class NpmAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.NPM)

    def _parse_json_deps(self, out: str) -> list:
        pkgs = []
        try:
            data = json.loads(out)
            for name, info in (data.get("dependencies") or {}).items():
                pkgs.append(Package(name=name, version=str(info.get("version", "")), manager=self._manager))
        except Exception:
            pass
        return pkgs

    def list_installed(self) -> list:
        return self._parse_json_deps(self._run(["npm", "ls", "-g", "--depth=0", "--json"]))

    def _do_search(self, query: str) -> list:
        out = self._run(["npm", "search", query])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 2 and parts[0].strip() and not parts[0].startswith("NAME"):
                pkgs.append(Package(name=parts[0].strip(), summary=parts[1].strip() if len(parts) > 1 else "",
                                    manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["npm", "view", name, "version", "description", "--json"])
        try:
            data = json.loads(out)
            version = data.get("version", "")
            if isinstance(version, list):
                version = version[0] if version else ""
            return Package(name=name, version=str(version), summary=str(data.get("description", "")),
                           manager=self._manager)
        except Exception:
            return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["npm", "install", "-g", name]
    def _remove_cmd(self, name: str) -> list: return ["npm", "uninstall", "-g", name]
    def _update_cmd(self, name: str) -> list: return ["npm", "update", "-g", name]
    def _update_all_cmd(self) -> list: return ["npm", "update", "-g"]


class PnpmAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.PNPM)

    def list_installed(self) -> list:
        out = self._run(["pnpm", "ls", "-g", "--depth=0", "--json"])
        pkgs = []
        try:
            data = json.loads(out)
            for name, info in (data.get("dependencies") or {}).items():
                pkgs.append(Package(name=name, version=str(info.get("version", "")), manager=self._manager))
        except Exception:
            pass
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["pnpm", "add", "-g", name]
    def _remove_cmd(self, name: str) -> list: return ["pnpm", "remove", "-g", name]
    def _update_cmd(self, name: str) -> list: return ["pnpm", "update", "-g", name]
    def _update_all_cmd(self) -> list: return ["pnpm", "update", "-g"]


class YarnAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.YARN)

    def list_installed(self) -> list:
        out = self._run(["yarn", "global", "list"])
        pkgs = []
        for line in out.split("\n"):
            m = re.search(r'info\s+"([^@"]+)@([^"]+)"', line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2), manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["yarn", "search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.search(r"^\s*\|\s*(\S+)", line)
            if m:
                pkgs.append(Package(name=m.group(1), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["yarn", "global", "add", name]
    def _remove_cmd(self, name: str) -> list: return ["yarn", "global", "remove", name]
    def _update_cmd(self, name: str) -> list: return ["yarn", "global", "upgrade", name]
    def _update_all_cmd(self) -> list: return ["yarn", "global", "upgrade"]


class BunAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.BUN)

    def list_installed(self) -> list:
        out = self._run(["bun", "pm", "ls", "-g"])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^\s*(\S+?)(?:@([\w.\-+]+))?\s*$", line)
            if m and m.group(1) and m.group(1) not in ("name", ""):
                pkgs.append(Package(name=m.group(1), version=m.group(2) or "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["bun", "add", "-g", name]
    def _remove_cmd(self, name: str) -> list: return ["bun", "remove", "-g", name]
    def _update_cmd(self, name: str) -> list: return ["bun", "update", "-g", name]


class GoAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.GO)

    def _gobin(self) -> str:
        out = self._run(["go", "env", "GOBIN"]).strip()
        if out:
            return out
        gopath = self._run(["go", "env", "GOPATH"]).strip()
        return os.path.join(gopath, "bin") if gopath else os.path.expanduser("~/go/bin")

    def list_installed(self) -> list:
        pkgs = []
        bindir = self._gobin()
        try:
            for entry in sorted(os.listdir(bindir)):
                path = os.path.join(bindir, entry)
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    pkgs.append(Package(name=entry, manager=self._manager))
        except Exception:
            pass
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["go", "install", f"{name}@latest"]
    def _update_cmd(self, name: str) -> list: return ["go", "install", f"{name}@latest"]

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        bindir = self._gobin()
        path = os.path.join(bindir, name)
        if not os.path.isfile(path):
            return False
        try:
            os.remove(path)
            return True
        except Exception:
            return False


class GemAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.GEM)

    def list_installed(self) -> list:
        out = self._run(["gem", "list", "--local"])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^(\S+)\s+\(([^)]*)\)", line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2).split(",")[0].strip(),
                                    manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["gem", "search", "-r", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^(\S+)\s+\(([^)]*)\)", line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2).split(",")[0].strip(),
                                    manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["gem", "specification", name, "name", "version", "summary"])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        lines = [l for l in out.split("\n") if l.strip()]
        if lines:
            pkg.name = lines[0].strip()
        if len(lines) > 1:
            pkg.version = lines[1].strip()
        if len(lines) > 2:
            pkg.summary = " ".join(lines[2:]).strip()
        return pkg if pkg.name else None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["gem", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["gem", "uninstall", "-x", name]
    def _update_cmd(self, name: str) -> list: return ["gem", "update", name]
    def _update_all_cmd(self) -> list: return ["gem", "update"]


class ComposerAdapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.COMPOSER)

    def list_installed(self) -> list:
        out = self._run(["composer", "global", "show"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split()
            if parts and "/" in parts[0]:
                version = parts[1] if len(parts) > 1 else ""
                pkgs.append(Package(name=parts[0], version=version, manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["composer", "search", query])
        pkgs = []
        for line in out.split("\n"):
            name, _, rest = line.partition(" ")
            if name.strip() and "/" in name:
                pkgs.append(Package(name=name.strip(), summary=rest.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["composer", "global", "require", name]
    def _remove_cmd(self, name: str) -> list: return ["composer", "global", "remove", name]
    def _update_cmd(self, name: str) -> list: return ["composer", "global", "update", name]


from features.package_store.binary_scanner import LocalBinaryAdapter


ADAPTER_FACTORIES: dict[PackageManager, type] = {
    PackageManager.APT: AptAdapter,
    PackageManager.DPKG: DpkgAdapter,
    PackageManager.PACMAN: PacmanAdapter,
    PackageManager.DNF: DnfAdapter,
    PackageManager.YUM: YumAdapter,
    PackageManager.RPM: RpmAdapter,
    PackageManager.ZYPPER: ZypperAdapter,
    PackageManager.APK: ApkAdapter,
    PackageManager.XBPS: XbpsAdapter,
    PackageManager.EMERGE: EmergeAdapter,
    PackageManager.NIX: NixAdapter,
    PackageManager.EOPKG: EopkgAdapter,
    PackageManager.SLACKPKG: SlackpkgAdapter,
    PackageManager.FLATPAK: FlatpakAdapter,
    PackageManager.SNAP: SnapAdapter,
    PackageManager.APPIMAGE: AppImageAdapter,
    PackageManager.BREW: BrewAdapter,
    PackageManager.PIP: PipAdapter,
    PackageManager.PIPX: PipxAdapter,
    PackageManager.CARGO: CargoAdapter,
    PackageManager.NPM: NpmAdapter,
    PackageManager.PNPM: PnpmAdapter,
    PackageManager.YARN: YarnAdapter,
    PackageManager.BUN: BunAdapter,
    PackageManager.GO: GoAdapter,
    PackageManager.GEM: GemAdapter,
    PackageManager.COMPOSER: ComposerAdapter,
    PackageManager.LOCAL: LocalBinaryAdapter,
}
