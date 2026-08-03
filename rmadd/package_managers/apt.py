"""AptAdapter adapter."""

import os
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.APT)

    def list_installed(self) -> list:
        out = self._run(["dpkg-query", "-f", "${binary:Package}|${Version}|${Architecture}|${binary:Summary}\n", "-W"], timeout=60)
        pkgs = []
        for line in out.split("\n"):
            parts = line.split("|")
            if len(parts) >= 1 and parts[0]:
                pkgs.append(Package(name=parts[0], version=parts[1] if len(parts) > 1 else "",
                                    arch=parts[2] if len(parts) > 2 else "",
                                    summary=parts[3] if len(parts) > 3 else "", manager=self._manager))
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["apt-cache", "search", query])
        pkgs = []
        for line in out.split("\n"):
            name, _, rest = line.partition(" - ")
            if name.strip():
                pkgs.append(Package(name=name.strip(), summary=rest.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["apt-cache", "show", name])
        if not out:
            return None
        pkg = Package(manager=self._manager)
        for line in out.split("\n"):
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "package": pkg.name = v
            elif k == "version": pkg.version = v
            elif k == "architecture": pkg.arch = v
            elif k == "description": pkg.summary = v
            elif k == "filename-size": pkg.size = v
        return pkg if pkg.name else None

    def count(self) -> int:
        out = self._run(["dpkg-query", "-f", "${binary:Package}\n", "-W"])
        return len(out.split("\n")) if out else 0

    def _install_cmd(self, name: str) -> list: return ["apt", "install", "-y", name]
    def _remove_cmd(self, name: str) -> list: return ["apt", "remove", "-y", name]
    def _update_cmd(self, name: str) -> list: return ["apt", "install", "--only-upgrade", "-y", name]
    def _update_all_cmd(self) -> list: return ["apt", "upgrade", "-y"]

    def list_repos(self) -> list:
        repos = []
        try:
            with open("/etc/apt/sources.list") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "deb " in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            repos.append(Repo(name=parts[1]))
        except Exception:
            pass
        return repos
