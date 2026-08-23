"""XbpsAdapter adapter."""



from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter, _strip_version


class Adapter(BaseAdapter):
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
                token = parts[1]
                name = _strip_version(token)
                version = token[len(name) + 1:] if token.startswith(name + "-") else ""
                pkgs.append(Package(name=name, version=version,
                                    summary=" ".join(parts[2:]) if len(parts) > 2 else "",
                                    manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
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
