import asyncio

from textual.app import ComposeResult
from textual.widgets import Static, Label
from textual.containers import Vertical, Horizontal
from core.core import SystemInfo


class About(Static):
    def __init__(self):
        super().__init__()
        self._sys_info = SystemInfo()

    def compose(self) -> ComposeResult:
        yield Label("                   Developer\n\n# Developed by Nawras - Software Developer\n# GitHub: https://github.com/Nawras448\n")
        yield Static("[yellow]Loading system info...[/yellow]", id="about-system")
        yield Static("", id="about-hostnamectl")
        yield Static("\nNumber of programs on the device\n", id="programs-title")
        yield Vertical(id="packages-list")
        yield Horizontal(id="About_system")

    async def on_mount(self) -> None:
        asyncio.create_task(self._load_system_info())
        asyncio.create_task(self._load_package_counts())

    async def _load_system_info(self):
        info = await asyncio.to_thread(self._sys_info.get_system_info)
        self.query_one("#about-system", Static).update(
            f"                 system info\n\nHostname: {info['hostname']}\nOS: {info['os']}\n"
        )
        self.query_one("#about-hostnamectl", Static).update(
            f"hostnamectl : {info['hostnamectl']}\n\n"
        )

    async def _load_package_counts(self):
        container = self.query_one("#packages-list", Vertical)
        all_counts = await asyncio.to_thread(self._sys_info.get_all_counts)
        for manager, count in all_counts.items():
            container.mount(Static(f"{manager.upper()} Count: {count}"))
