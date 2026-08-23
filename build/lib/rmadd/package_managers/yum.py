"""YumAdapter adapter."""



from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
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

    def get_info(self, name: str) -> Package | None:
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
