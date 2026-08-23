"""PacmanAdapter adapter."""


from rmadd.models import Package, PackageManager, Repo
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
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
                name = parts[0].split("/")[-1] if "/" in parts[0] else parts[0]
                pkgs.append(Package(name=name, version=parts[1],
                                    summary=" ".join(parts[2:]) if len(parts) > 2 else "",
                                    manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
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
