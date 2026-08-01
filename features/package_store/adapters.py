import os
import signal
import subprocess
import shutil
import threading
import time
from typing import Callable, Optional

from features.package_store.ports import PackageDataSource
from features.package_store.domain import Package, PackageManager, PackageStatus, Repo


class _BaseAdapter(PackageDataSource):
    def __init__(self, binary: str, manager: PackageManager):
        self._available = shutil.which(binary) is not None
        self._manager = manager

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

    def _run_priv(self, cmd: list, timeout: int = 300) -> bool:
        ok, _ = self._run_priv_stream(cmd, None, None, timeout)
        return ok

    def _run_priv_stream(
        self,
        cmd: list,
        on_output: Optional[Callable[[str], None]],
        cancel_event: Optional[threading.Event],
        timeout: int = 600,
    ) -> tuple:
        """Run a privileged command, streaming output line by line.

        Returns (ok: bool, cancelled: bool). When cancel_event is set the
        process group is terminated (SIGTERM, then SIGKILL after a grace
        period). Output lines are delivered to on_output (may be None).
        The reader runs in a daemon thread so cancellation works even while
        the child process is silent (e.g. waiting at an auth prompt).
        """
        if not self._available:
            raise RuntimeError(f"{self._manager.value} is not available on this system")
        if os.geteuid() == 0:
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

    @staticmethod
    def _drain(proc: subprocess.Popen, on_output, tail: list):
        try:
            for line in proc.stdout:
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
        ok, _ = self._run_priv_stream(self._install_cmd(name), on_output, cancel_event)
        return ok

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        ok, _ = self._run_priv_stream(self._remove_cmd(name), on_output, cancel_event)
        return ok

    def update(self, name: str, on_output=None, cancel_event=None) -> bool:
        ok, _ = self._run_priv_stream(self._update_cmd(name), on_output, cancel_event)
        return ok

    def update_all(self, on_output=None, cancel_event=None) -> bool:
        ok, _ = self._run_priv_stream(self._update_all_cmd(), on_output, cancel_event)
        return ok

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


class DnfAdapter(_BaseAdapter):
    def __init__(self):
        super().__init__("dnf", PackageManager.DNF)

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

    def search(self, query: str) -> list:
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


class AptAdapter(_BaseAdapter):
    def __init__(self):
        super().__init__("apt", PackageManager.APT)

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

    def search(self, query: str) -> list:
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


class FlatpakAdapter(_BaseAdapter):
    def __init__(self):
        super().__init__("flatpak", PackageManager.FLATPAK)

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

    def search(self, query: str) -> list:
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


class SnapAdapter(_BaseAdapter):
    def __init__(self):
        super().__init__("snap", PackageManager.SNAP)

    def list_installed(self) -> list:
        out = self._run(["snap", "list"])
        pkgs = []
        for line in out.split("\n")[1:]:
            parts = line.split()
            if parts:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "", manager=self._manager))
        return pkgs

    def search(self, query: str) -> list:
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


class PacmanAdapter(_BaseAdapter):
    def __init__(self):
        super().__init__("pacman", PackageManager.PACMAN)

    def list_installed(self) -> list:
        out = self._run(["pacman", "-Qq"])
        return [Package(name=n, manager=self._manager) for n in out.split("\n") if n]

    def search(self, query: str) -> list:
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
