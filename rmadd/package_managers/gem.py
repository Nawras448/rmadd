"""GemAdapter adapter."""

import re

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
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

    def get_info(self, name: str) -> Package | None:
        out = self._run(["gem", "specification", name, "name", "version", "summary"])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        lines = [ln for ln in out.split("\n") if ln.strip()]
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
