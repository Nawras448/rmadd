"""NpmAdapter adapter."""

import json
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.NPM)

    def _parse_json_deps(self, out: str) -> list:
        pkgs = []
        try:
            data = json.loads(out)
            for name, info in (data.get("dependencies") or {}).items():
                pkgs.append(Package(name=name, version=str(info.get("version", "")), manager=self._manager))
        except Exception:
            pass
        return pkgs

    def list_installed(self) -> list:
        return self._parse_json_deps(self._run(["npm", "ls", "-g", "--depth=0", "--json"]))

    def _do_search(self, query: str) -> list:
        out = self._run(["npm", "search", query])
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 2 and parts[0].strip() and not parts[0].startswith("NAME"):
                pkgs.append(Package(name=parts[0].strip(), summary=parts[1].strip() if len(parts) > 1 else "",
                                    manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["npm", "view", name, "version", "description", "--json"])
        try:
            data = json.loads(out)
            version = data.get("version", "")
            if isinstance(version, list):
                version = version[0] if version else ""
            return Package(name=name, version=str(version), summary=str(data.get("description", "")),
                           manager=self._manager)
        except Exception:
            return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["npm", "install", "-g", name]
    def _remove_cmd(self, name: str) -> list: return ["npm", "uninstall", "-g", name]
    def _update_cmd(self, name: str) -> list: return ["npm", "update", "-g", name]
    def _update_all_cmd(self) -> list: return ["npm", "update", "-g"]
