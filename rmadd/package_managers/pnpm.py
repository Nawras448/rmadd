"""PnpmAdapter adapter."""

import json
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.PNPM)

    def list_installed(self) -> list:
        out = self._run(["pnpm", "ls", "-g", "--depth=0", "--json"])
        pkgs = []
        try:
            data = json.loads(out)
            for name, info in (data.get("dependencies") or {}).items():
                pkgs.append(Package(name=name, version=str(info.get("version", "")), manager=self._manager))
        except Exception:
            pass
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["pnpm", "add", "-g", name]
    def _remove_cmd(self, name: str) -> list: return ["pnpm", "remove", "-g", name]
    def _update_cmd(self, name: str) -> list: return ["pnpm", "update", "-g", name]
    def _update_all_cmd(self) -> list: return ["pnpm", "update", "-g"]
