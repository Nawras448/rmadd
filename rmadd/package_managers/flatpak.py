"""FlatpakAdapter adapter."""


from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
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
