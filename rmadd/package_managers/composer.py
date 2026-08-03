"""ComposerAdapter adapter."""

import re
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.COMPOSER)

    def list_installed(self) -> list:
        out = self._run(["composer", "global", "show"])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split()
            if parts and "/" in parts[0]:
                version = parts[1] if len(parts) > 1 else ""
                pkgs.append(Package(name=parts[0], version=version, manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["composer", "search", query])
        pkgs = []
        for line in out.split("\n"):
            name, _, rest = line.partition(" ")
            if name.strip() and "/" in name:
                pkgs.append(Package(name=name.strip(), summary=rest.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["composer", "global", "require", name]
    def _remove_cmd(self, name: str) -> list: return ["composer", "global", "remove", name]
    def _update_cmd(self, name: str) -> list: return ["composer", "global", "update", name]
