"""SnapAdapter adapter."""



from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
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

    def get_info(self, name: str) -> Package | None:
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
