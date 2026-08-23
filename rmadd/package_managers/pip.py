"""PipAdapter adapter."""

import shutil

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.PIP)
        self._pip = "pip3" if shutil.which("pip3") else "pip"

    def list_installed(self) -> list:
        out = self._run([self._pip, "list", "--format=freeze"])
        pkgs = []
        for line in out.split("\n"):
            name, sep, version = line.partition("==")
            if name.strip() and sep:
                pkgs.append(Package(name=name.strip(), version=version.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
        out = self._run([self._pip, "show", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "name": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "summary": pkg.summary = v
            elif k == "home-page": pkg.repo = v
        return pkg if pkg.name else None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return [self._pip, "install", "--user", name]
    def _remove_cmd(self, name: str) -> list: return [self._pip, "uninstall", "-y", name]
    def _update_cmd(self, name: str) -> list: return [self._pip, "install", "--user", "--upgrade", name]
