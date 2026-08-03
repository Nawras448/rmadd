import shutil
from dataclasses import dataclass
from typing import Optional

from rmadd.models import PackageManager
from rmadd.package_managers.base import resolve_system_manager


@dataclass
class InstallerTool:
    name: str
    display: str
    binary: str
    purpose: str
    manager: Optional[PackageManager] = None


INSTALLER_TOOLS: list[InstallerTool] = [
    InstallerTool("flatpak", "Flatpak", "flatpak", "Universal app framework (Flatpak apps)"),
    InstallerTool("snap", "Snap", "snap", "Universal snap app installer"),
    InstallerTool("appimage", "AppImage", "AppImage", "Portable AppImage apps (file based)"),
    InstallerTool("brew", "Homebrew", "brew", "Homebrew package manager for Linux"),
    InstallerTool("gdebi", "GDebi", "gdebi", "GUI installer for .deb packages"),
    InstallerTool("gnome-software", "GNOME Software", "gnome-software", "Graphical app center"),
    InstallerTool("python3-pip", "Pip", "pip3", "Python package installer"),
    InstallerTool("pipx", "Pipx", "pipx", "Installs Python CLI apps in isolated environments"),
    InstallerTool("cargo", "Cargo", "cargo", "Rust package manager"),
    InstallerTool("npm", "NPM", "npm", "Node.js package manager"),
    InstallerTool("pnpm", "PNPM", "pnpm", "Fast Node.js package manager"),
    InstallerTool("yarn", "Yarn", "yarn", "Node.js package manager (Yarn)"),
    InstallerTool("bun", "Bun", "bun", "JavaScript runtime + package manager"),
    InstallerTool("go", "Go", "go", "Go language toolchain installer"),
    InstallerTool("gem", "RubyGems", "gem", "Ruby package installer"),
    InstallerTool("composer", "Composer", "composer", "PHP package manager"),
]


def detect_tools() -> list:
    system = resolve_system_manager()
    entries = []
    for tool in INSTALLER_TOOLS:
        tool.manager = tool.manager or system
        entries.append((tool, shutil.which(tool.binary) is not None))
    return entries
