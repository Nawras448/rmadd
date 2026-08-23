"""BrewAdapter adapter."""

import json

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.BREW)

    def list_installed(self) -> list:
        out = self._run(["brew", "list", "--formula"])
        return [Package(name=n, manager=self._manager) for n in out.split("\n") if n]

    def _do_search(self, query: str) -> list:
        out = self._run(["brew", "search", query])
        pkgs = []
        for line in out.split("\n"):
            if not line or "===" in line:
                continue
            for token in line.split():
                if token.startswith("formulae") or token.startswith("casks"):
                    continue
                pkgs.append(Package(name=token, manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
        out = self._run(["brew", "info", "--json=v2", name])
        if not out:
            return None
        try:
            data = json.loads(out)
            formulae = data.get("formulae") or []
            if not formulae:
                return None
            f = formulae[0]
            return Package(name=f.get("name", name), version=(f.get("versions") or {}).get("stable", ""),
                           summary=f.get("desc", ""), manager=self._manager)
        except Exception:
            return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["brew", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["brew", "uninstall", name]
    def _update_cmd(self, name: str) -> list: return ["brew", "upgrade", name]
    def _update_all_cmd(self) -> list: return ["brew", "upgrade"]
