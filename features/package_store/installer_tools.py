import shutil
from dataclasses import dataclass
from typing import Optional

from features.package_store.domain import PackageManager


@dataclass
class InstallerTool:
    name: str
    display: str
    binary: str
    purpose: str
    manager: Optional[PackageManager] = None


INSTALLER_TOOLS: list[InstallerTool] = [
    InstallerTool("flatpak", "Flatpak", "flatpak", "App framework for Flatpak apps"),
    InstallerTool("snap", "Snap", "snap", "Snap app installer"),
    InstallerTool("gdebi", "GDebi", "gdebi", "GUI installer for .deb packages"),
    InstallerTool("gnome-software", "GNOME Software", "gnome-software", "Graphical app center"),
    InstallerTool("python3-pip", "Pip", "pip3", "Python package installer"),
    InstallerTool("pipx", "Pipx", "pipx", "Installs Python CLI apps in isolated environments"),
    InstallerTool("cargo", "Cargo", "cargo", "Rust package manager"),
    InstallerTool("npm", "NPM", "npm", "Node.js package manager"),
]


def resolve_system_manager() -> Optional[PackageManager]:
    for mgr, binary in (
        (PackageManager.APT, "apt"),
        (PackageManager.DNF, "dnf"),
        (PackageManager.PACMAN, "pacman"),
    ):
        if shutil.which(binary):
            return mgr
    return None


def detect_tools() -> list:
    system = resolve_system_manager()
    entries = []
    for tool in INSTALLER_TOOLS:
        tool.manager = tool.manager or system
        entries.append((tool, shutil.which(tool.binary) is not None))
    return entries
