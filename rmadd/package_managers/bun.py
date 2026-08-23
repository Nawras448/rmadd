"""BunAdapter adapter."""

import re

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.BUN)

    def list_installed(self) -> list:
        out = self._run(["bun", "pm", "ls", "-g"])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^\s*(\S+?)(?:@([\w.\-+]+))?\s*$", line)
            if m and m.group(1) and m.group(1) not in ("name", ""):
                pkgs.append(Package(name=m.group(1), version=m.group(2) or "", manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["bun", "add", "-g", name]
    def _remove_cmd(self, name: str) -> list: return ["bun", "remove", "-g", name]
    def _update_cmd(self, name: str) -> list: return ["bun", "update", "-g", name]
