"""DpkgAdapter adapter."""



from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.DPKG)

    def list_installed(self) -> list:
        fmt = "${binary:Package}|${Version}|${Architecture}|${binary:Summary}\n"
        out = self._run(["dpkg-query", "-f", fmt, "-W"], timeout=60)
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
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
