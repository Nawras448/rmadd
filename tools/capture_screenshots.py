"""Headless screenshot generator for the README visual overview.

Run from the repository root:

    python tools/capture_screenshots.py

Produces docs/assets/search-view.png, docs/assets/installed-apps.png and
docs/assets/local-binaries.png from an in-memory run of the TUI.
Requires cairosvg (pip install cairosvg) to rasterize the SVG output.
"""

import asyncio
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textual.widgets import Input, TabbedContent

from rmadd.models import Package, PackageCollection, PackageManager, PackageStatus
from rmadd.package_managers.local import Adapter as LocalAdapter
from rmadd.tui import RmaddTuiApp

ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "assets")
HERO_SIZE = (140, 42)
GRID_SIZE = (110, 36)

APT = PackageManager.APT
FLATPAK = PackageManager.FLATPAK
PIP = PackageManager.PIP
INSTALLED = PackageStatus.INSTALLED


def pkg(name, version, manager, summary=""):
    return Package(name=name, version=version, manager=manager,
                   status=INSTALLED, summary=summary)


INSTALLED_PACKAGES = PackageCollection([
    pkg("htop", "3.3.0", APT, "Interactive process viewer"),
    pkg("firefox", "133.0", APT, "Fast, private web browser"),
    pkg("neovim", "0.10.2", APT, "Vim-fork focused on extensibility"),
    pkg("git", "2.47.0", APT, "Fast, scalable version control"),
    pkg("curl", "8.10.1", APT, "Command line data transfer tool"),
    pkg("vlc", "3.0.21", APT, "Versatile media player"),
    pkg("spotify", "1.2.42", FLATPAK, "Stream music from the Spotify catalog"),
    pkg("gimp", "3.0.2", FLATPAK, "GNU Image Manipulation Program"),
    pkg("telegram-desktop", "5.7.1", FLATPAK, "Official Telegram Desktop client"),
    pkg("requests", "2.32.3", PIP, "Python HTTP for humans"),
    pkg("flask", "3.1.0", PIP, "Simple WSGI web application framework"),
    pkg("pytest", "8.3.3", PIP, "Simple powerful testing with Python"),
])

SEARCH_RESULTS = {
    APT: PackageCollection([
        Package(name="neovim", version="0.10.2", manager=APT, status=INSTALLED,
                summary="Vim-fork focused on extensibility and usability"),
        Package(name="vim", version="9.1.0", manager=APT,
                summary="Vi IMproved - enhanced vi editor"),
        Package(name="vim-tiny", version="2:9.1.0016", manager=APT,
                summary="Vi IMproved - enhanced vi editor (tiny build)"),
        Package(name="vim-runtime", version="2:9.1.0016", manager=APT,
                summary="Vi IMproved - enhanced vi editor (runtime files)"),
    ]),
    FLATPAK: PackageCollection([]),
    PIP: PackageCollection([
        Package(name="vim-powerline", version="2.4.0", manager=PIP,
                summary="The ultimate Vim statusline generator"),
    ]),
}


class FakeSystem:
    def get_system_info(self):
        from rmadd.models import SystemInfo
        return SystemInfo(hostname="capture-host")

    def get_distribution(self):
        from rmadd.models import Distribution
        return Distribution()

    def refresh(self):
        pass


class FakeHardware:
    def get_cpu_info(self):
        return None

    def get_memory_info(self):
        return None


class FakePackageService:
    @property
    def available_managers(self):
        return [APT, FLATPAK, PIP]

    def add_source(self, manager, source):
        return False

    def list_installed(self, manager=None):
        if manager is not None:
            return INSTALLED_PACKAGES.by_manager(manager)
        return INSTALLED_PACKAGES

    def get_all_counts(self):
        return {str(m).split(".")[-1].lower(): str(n) for m, n in
                ((APT, 6), (FLATPAK, 3), (PIP, 3))}

    def default_search_managers(self):
        return [APT, FLATPAK, PIP]

    def search(self, query, manager=None):
        if manager is None:
            results = PackageCollection([])
            for col in SEARCH_RESULTS.values():
                results += col
            return results
        return SEARCH_RESULTS.get(manager, PackageCollection([]))

    def get_status(self, name, manager):
        for p in INSTALLED_PACKAGES:
            if p.name == name and p.manager == manager:
                return PackageStatus.INSTALLED
        return PackageStatus.NOT_INSTALLED

    def get_package_detail(self, name, manager):
        return Package(name=name, manager=manager)

    def invalidate_counts(self):
        pass


def make_local_binaries(directory):
    scripts = [
        ("myscript", "myscript 2.1.0"),
        ("build-tool", "build-tool 1.4.7"),
        ("devlink", "devlink 0.9.3"),
        ("config-fetch", "config-fetch 3.0.1"),
    ]
    for name, banner in scripts:
        path = os.path.join(directory, name)
        with open(path, "w") as fh:
            fh.write("#!/bin/sh\n")
            fh.write(f'echo "{banner}"\n')
        os.chmod(path, 0o755)
    return directory


def rasterize(svg_path, png_path):
    with open(svg_path) as fh:
        svg = fh.read()
    svg = svg.replace("Fira Code", "DejaVu Sans Mono")
    import cairosvg
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=png_path)


def save_screenshot(app, filename):
    svg = app.export_screenshot()
    svg_path = os.path.join(ASSETS, filename + ".svg")
    png_path = os.path.join(ASSETS, filename + ".png")
    with open(svg_path, "w") as fh:
        fh.write(svg)
    rasterize(svg_path, png_path)
    os.remove(svg_path)
    size = os.path.getsize(png_path)
    print(f"[ok] {filename}.png ({size} bytes)")
    if size < 10_000:
        raise RuntimeError(f"{filename}.png looks too small ({size} bytes)")


def set_tab(store, pane_id):
    tabbed = store.query_one(TabbedContent)
    tabbed.active = pane_id


async def capture_search(pilot, fake):
    store = pilot.app.screen
    await pilot.pause(0.4)
    input_widget = store.query_one("#search-input", Input)
    input_widget.value = "vim"
    await store.search.run("vim")
    await pilot.pause(0.4)
    save_screenshot(pilot.app, "search-view")


async def capture_installed(pilot, fake):
    store = pilot.app.screen
    set_tab(store, "pane-installed")
    for _ in range(20):
        await pilot.pause(0.1)
        if store.ops.state.installed_packages():
            break
    await pilot.pause(0.3)
    save_screenshot(pilot.app, "installed-apps")


async def capture_local(pilot, fake):
    store = pilot.app.screen
    set_tab(store, "pane-local")
    for _ in range(30):
        await pilot.pause(0.1)
        if store.ops.state.local_packages():
            break
    await pilot.pause(0.3)
    save_screenshot(pilot.app, "local-binaries")


async def main():
    os.makedirs(ASSETS, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        make_local_binaries(tmpdir)
        for name, size, capture in (
            ("search", HERO_SIZE, capture_search),
            ("installed", GRID_SIZE, capture_installed),
            ("local", GRID_SIZE, capture_local),
        ):
            app = RmaddTuiApp(FakeSystem(), FakePackageService(), FakeHardware())
            async with app.run_test(size=size) as pilot:
                if name == "local":
                    app.screen.local_bin._adapter = LocalAdapter(
                        search_dirs=[tmpdir], version_timeout=1, probe_limit=64
                    )
                await pilot.pause(0.3)
                await capture(pilot, FakePackageService())
    print("done ->", ASSETS)


if __name__ == "__main__":
    started = time.time()
    asyncio.run(main())
    print(f"took {time.time() - started:.1f}s")
