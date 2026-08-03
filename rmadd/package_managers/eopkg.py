"""EopkgAdapter adapter."""


from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter, _strip_version

class Adapter(BaseAdapter):
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
