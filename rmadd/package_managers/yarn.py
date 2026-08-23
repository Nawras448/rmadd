"""YarnAdapter adapter."""

import re

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.YARN)

    def list_installed(self) -> list:
        out = self._run(["yarn", "global", "list"])
        pkgs = []
        for line in out.split("\n"):
            m = re.search(r'info\s+"([^@"]+)@([^"]+)"', line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2), manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["yarn", "search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.search(r"^\s*\|\s*(\S+)", line)
            if m:
                pkgs.append(Package(name=m.group(1), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["yarn", "global", "add", name]
    def _remove_cmd(self, name: str) -> list: return ["yarn", "global", "remove", name]
    def _update_cmd(self, name: str) -> list: return ["yarn", "global", "upgrade", name]
    def _update_all_cmd(self) -> list: return ["yarn", "global", "upgrade"]
