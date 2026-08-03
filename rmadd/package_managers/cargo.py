"""CargoAdapter adapter."""

import re
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.CARGO)

    def list_installed(self) -> list:
        out = self._run(["cargo", "install", "--list"])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^\s*(\S+)\s+v?([\w.\-+]+):", line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2), manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["cargo", "search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^(\S+)\s+=\s+\"([^\"]*)\"\s*(?:#\s*(.*))?$", line)
            if m:
                pkgs.append(Package(name=m.group(1), version=m.group(2),
                                    summary=(m.group(3) or "").strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["cargo", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["cargo", "uninstall", name]
    def _update_cmd(self, name: str) -> list: return ["cargo", "install", name]
