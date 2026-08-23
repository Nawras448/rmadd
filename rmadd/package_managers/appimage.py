"""AppImageAdapter adapter."""

import os

from rmadd.models import Package, PackageManager
from rmadd.package_managers.base import BaseAdapter


class Adapter(BaseAdapter):
    """File-based source: manages *.AppImage files on disk (no binary)."""

    DEFAULT_DIRS = ("~/Applications", "~/.local/bin", "/opt")

    def __init__(self, dirs=None, install_dir: str | None = None):
        super().__init__(PackageManager.APPIMAGE)
        self._available = True
        self._dirs = dirs or self.DEFAULT_DIRS
        self._install_dir = install_dir or os.path.expanduser("~/Applications")

    def _expanded_dirs(self) -> list:
        return [os.path.expanduser(d) for d in self._dirs]

    def _find_path(self, name: str) -> str | None:
        for d in self._expanded_dirs():
            if not os.path.isdir(d):
                continue
            for entry in os.listdir(d):
                if entry.lower().endswith(".appimage") and os.path.splitext(entry)[0] == name:
                    return os.path.join(d, entry)
        return None

    def list_installed(self) -> list:
        pkgs = []
        for d in self._expanded_dirs():
            if not os.path.isdir(d):
                continue
            for entry in sorted(os.listdir(d)):
                path = os.path.join(d, entry)
                if os.path.isfile(path) and entry.lower().endswith(".appimage"):
                    pkgs.append(Package(name=os.path.splitext(entry)[0], summary=path,
                                        size=f"{os.path.getsize(path) // (1024 * 1024)} MB",
                                        manager=self._manager))
        return pkgs

    def get_info(self, name: str) -> Package | None:
        path = self._find_path(name)
        if not path:
            return None
        return Package(name=name, summary=path,
                       size=f"{os.path.getsize(path) // (1024 * 1024)} MB", manager=self._manager)

    def count(self) -> int:
        return len(self.list_installed())

    def install(self, name: str, on_output=None, cancel_event=None, source_path=None) -> bool:
        if not source_path or not os.path.isfile(source_path):
            if on_output is not None:
                on_output("Error: no valid .AppImage source file\n")
            return False
        try:
            target_dir = self._install_dir
            os.makedirs(target_dir, exist_ok=True)
            target = os.path.join(target_dir, os.path.basename(source_path))
            if not target.lower().endswith(".appimage"):
                target += ".AppImage"
            import shutil as _sh
            if on_output is not None:
                on_output(f"Installing {os.path.basename(target)} into {target_dir}\n")
            _sh.copy2(source_path, target)
            os.chmod(target, 0o755)
            return True
        except Exception as e:
            if on_output is not None:
                on_output(f"Error: {e}\n")
            return False

    def remove(self, name: str, on_output=None, cancel_event=None) -> bool:
        path = self._find_path(name)
        if not path:
            if on_output is not None:
                on_output(f"Error: {name}.AppImage not found\n")
            return False
        try:
            os.remove(path)
            return True
        except Exception as e:
            if on_output is not None:
                on_output(f"Error: {e}\n")
            return False

    def update(self, name: str, on_output=None, cancel_event=None) -> bool:
        return False

    def update_all(self, on_output=None, cancel_event=None) -> bool:
        return False


# =====================================================================
# Tier 3: language & developer ecosystem managers (user-level)
# =====================================================================
