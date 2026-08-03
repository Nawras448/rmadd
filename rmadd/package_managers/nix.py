"""NixAdapter adapter."""

import re
import shutil
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.NIX)
        self._profile = shutil.which("nix") is not None

    @staticmethod
    def _attr_name(token: str) -> str:
        if "#" in token:
            return token.rsplit("#", 1)[-1]
        if ":" in token:
            return token.rsplit(":", 1)[-1]
        return token

    def list_installed(self) -> list:
        if self._profile:
            out = self._run(["nix", "profile", "list"])
            pkgs = []
            for line in out.split("\n"):
                parts = line.split()
                if len(parts) >= 3:
                    token = parts[3] if len(parts) > 3 else parts[2]
                    name = self._attr_name(token)
                    if name and not name.startswith("/"):
                        pkgs.append(Package(name=name, manager=self._manager))
            return pkgs
        out = self._run(["nix-env", "-q"])
        return [Package(name=n, manager=self._manager) for n in out.split("\n") if n]

    def _do_search(self, query: str) -> list:
        if not self._profile:
            return []
        out = self._run(["nix", "search", "nixpkgs", query], timeout=60)
        pkgs = []
        for line in out.split("\n"):
            name_part, _, desc = line.partition("\t")
            if not name_part.strip():
                continue
            name = self._attr_name(name_part.strip().split()[0])
            m = re.search(r"\((.*?)\)", name_part)
            version = m.group(1) if m else ""
            pkgs.append(Package(name=name, version=version, summary=desc.strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        return None

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list:
        return ["nix", "profile", "install", f"nixpkgs#{name}"] if self._profile else ["nix-env", "-i", name]

    def _remove_cmd(self, name: str) -> list:
        return ["nix", "profile", "remove", name] if self._profile else ["nix-env", "-e", name]

    def _update_cmd(self, name: str) -> list:
        return ["nix", "profile", "upgrade", name] if self._profile else ["nix-env", "-u", name]

    def _update_all_cmd(self) -> list:
        return ["nix", "profile", "upgrade"] if self._profile else ["nix-env", "-u"]
