"""ApkAdapter adapter."""

import re
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter, _strip_version

class Adapter(BaseAdapter):
    _APK_ARCH = r"(x86_64|aarch64|armhf|armv7|ppc64le|s390x|riscv64)"

    def __init__(self):
        super().__init__(PackageManager.APK)

    @staticmethod
    def _parse_token(token: str) -> tuple:
        m = re.match(r"^(?P<name>.+?)-(?P<version>\d[\w.]*-r\d+)-(?P<arch>\w+)$", token)
        if m:
            return m.group("name"), m.group("version"), m.group("arch")
        return _strip_version(token), "", ""

    def list_installed(self) -> list:
        out = self._run(["apk", "list", "--installed"])
        pkgs = []
        for line in out.split("\n"):
            token = line.split()[0] if line.split() else ""
            if not token:
                continue
            name, version, arch = self._parse_token(token)
            pkgs.append(Package(name=name, version=version, arch=arch, manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["apk", "search", query])
        pkgs = []
        for line in out.split("\n"):
            token = line.split()[0] if line.split() else ""
            if token:
                pkgs.append(Package(name=_strip_version(token), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["apk", "info", "-a", name])
        if not out:
            return None
        pkg = Package(manager=self._manager, name=name)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "version": pkg.version = v
            elif k == "description": pkg.summary = v
            elif k == "size": pkg.size = v
        return pkg

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["apk", "add", name]
    def _remove_cmd(self, name: str) -> list: return ["apk", "del", name]
    def _update_cmd(self, name: str) -> list: return ["apk", "add", "-u", name]
    def _update_all_cmd(self) -> list: return ["apk", "upgrade"]
