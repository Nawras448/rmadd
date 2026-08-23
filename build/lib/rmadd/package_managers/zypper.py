"""ZypperAdapter adapter."""



from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
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

    def get_info(self, name: str) -> Package | None:
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
