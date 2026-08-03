"""PipxAdapter adapter."""

import json
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.PIPX)

    def list_installed(self) -> list:
        out = self._run(["pipx", "list", "--json"])
        pkgs = []
        try:
            data = json.loads(out)
            for name, info in (data.get("venvs") or {}).items():
                main = (info.get("metadata") or {}).get("main_package") or {}
                pkgs.append(Package(name=main.get("package") or name,
                                    version=main.get("package_version", ""), manager=self._manager))
        except Exception:
            pass
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["pipx", "list", "--json"])
        try:
            data = json.loads(out)
            for _name, info in (data.get("venvs") or {}).items():
                main = (info.get("metadata") or {}).get("main_package") or {}
                if main.get("package") == name:
                    return Package(name=name, version=main.get("package_version", ""), manager=self._manager)
        except Exception:
            pass
        return None

    def count(self) -> int:
        return len(self.list_installed())

    def _do_search(self, query: str) -> list:
        pkgs = []
        try:
            import socket
            import xmlrpc.client
            socket.setdefaulttimeout(10)
            proxy = xmlrpc.client.ServerProxy("https://pypi.org/pypi")
            for hit in proxy.search({"name": query}, "or")[:20]:
                pkgs.append(Package(
                    name=hit.get("name", ""),
                    version=str(hit.get("latest_version") or ""),
                    summary=str(hit.get("summary") or ""),
                    manager=self._manager,
                ))
        except Exception:
            pass
        return pkgs

    def _install_cmd(self, name: str) -> list: return ["pipx", "install", name]
    def _remove_cmd(self, name: str) -> list: return ["pipx", "uninstall", name]
    def _update_cmd(self, name: str) -> list: return ["pipx", "upgrade", name]
