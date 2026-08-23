"""SlackpkgAdapter adapter."""

import os
import re

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.SLACKPKG)

    def list_installed(self) -> list:
        pkgs = []
        try:
            for entry in os.listdir("/var/log/packages"):
                pkgs.append(Package(name=entry, manager=self._manager))
        except Exception:
            pass
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["slackpkg", "search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.search(r"\[ installed \]|\[ uninstalled \]\s+(\S+)", line)
            if m:
                pkgs.append(Package(name=m.group(1) if m.group(1) else "", manager=self._manager))
                continue
            m2 = re.search(r"^(\S+):", line)
            if m2 and "Package" not in line:
                pkgs.append(Package(name=m2.group(1), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["slackpkg", "-batch=on", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["slackpkg", "remove", name]


# =====================================================================
# Tier 2: universal packaging formats
# =====================================================================
