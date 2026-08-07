"""EmergeAdapter adapter."""

import os
import re
from typing import Optional
from rmadd.models import Package, PackageManager, PackageStatus, Repo
from rmadd.package_managers.base import BaseAdapter, _strip_version

class Adapter(BaseAdapter):
    def __init__(self):
        super().__init__(PackageManager.EMERGE)

    def list_installed(self) -> list:
        pkgs = []
        try:
            base = "/var/db/pkg"
            for cat in os.listdir(base):
                cat_path = os.path.join(base, cat)
                if not os.path.isdir(cat_path):
                    continue
                for entry in os.listdir(cat_path):
                    pkgs.append(Package(name=f"{cat}/{entry}", manager=self._manager))
        except Exception:
            pass
        return pkgs

    def _do_search(self, query: str) -> list:
        out = self._run(["eix", "-e", query]) or self._run(["emerge", "--search", query])
        pkgs = []
        for line in out.split("\n"):
            m = re.match(r"^\[[^\]]*\]\s+(\S+)\s+(.*)$", line)
            if not m:
                continue
            token = m.group(1)
            name = _strip_version(token)
            version = token[len(name) + 1:] if token.startswith(name + "-") else ""
            pkgs.append(Package(name=name, version=version,
                                summary=m.group(2).strip(), manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Optional[Package]:
        out = self._run(["equery", "list", "-e", name]) or self._run(["emerge", "-pv", name])
        if not out:
            return None
        return Package(name=name, summary=out.split("\n")[0][:120], manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def _install_cmd(self, name: str) -> list: return ["emerge", "--ask=n", "--noreplace", name]
    def _remove_cmd(self, name: str) -> list: return ["emerge", "--ask=n", "--unmerge", name]
    def _update_cmd(self, name: str) -> list: return ["emerge", "--ask=n", "--update", name]
    def _update_all_cmd(self) -> list: return ["emerge", "--ask=n", "--update", "--deep", "@world"]
