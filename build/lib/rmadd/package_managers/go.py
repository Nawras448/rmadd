"""GoAdapter adapter."""

import os

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.GO)

    def _gobin(self) -> str:
        out = self._run(["go", "env", "GOBIN"]).strip()
        if out:
            return out
        gopath = self._run(["go", "env", "GOPATH"]).strip()
        return os.path.join(gopath, "bin") if gopath else os.path.expanduser("~/go/bin")

    def list_installed(self) -> list:
        pkgs = []
        bindir = self._gobin()
        try:
            for entry in sorted(os.listdir(bindir)):
                path = os.path.join(bindir, entry)
                if os.path.isfile(path) and os.access(path, os.X_OK):
                    pkgs.append(Package(name=entry, manager=self._manager))
        except Exception:
            pass
        return pkgs

    def get_info(self, name: str) -> Package | None:
        return Package(name=name, manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["go", "install", f"{name}@latest"]
    def _update_cmd(self, name: str) -> list: return ["go", "install", f"{name}@latest"]

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        bindir = self._gobin()
        path = os.path.join(bindir, name)
        if not os.path.isfile(path):
            return False
        try:
            os.remove(path)
            return True
        except Exception:
            return False
