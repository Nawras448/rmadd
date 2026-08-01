import asyncio

from textual.screen import Screen
from textual.widgets import Header, Footer, Static
from textual.containers import Horizontal, Vertical

from features.ui_switch.presentation.tui.navigation import NavigationSidebar
from features.system_monitor.presentation.cpu_graph import CpuGraph
from features.system_monitor.domain import HardwareReport


class HardwareMonitorScreen(Screen):
    BINDINGS = [
        ("escape", "dismiss", "Back"),
    ]

    def __init__(self, hardware_service):
        super().__init__()
        self._hw = hardware_service
        self._timer = None

    def compose(self):
        yield Header(show_clock=True)
        with Horizontal():
            yield NavigationSidebar(id="sidebar")
            with Vertical(id="left-panel"):
                yield CpuGraph(id="cpu-graph")
                yield Static(id="memory-info", classes="monitor-card")
            with Vertical(id="right-panel"):
                yield Static(id="disk-info", classes="monitor-card")
                yield Static(id="gpu-info", classes="monitor-card")
                yield Static(id="network-info", classes="monitor-card")
        yield Footer()

    async def on_mount(self):
        for widget_id, title in (
            ("#memory-info", "Memory"),
            ("#disk-info", "Disks"),
            ("#gpu-info", "GPU"),
            ("#network-info", "Network"),
        ):
            self.query_one(widget_id, Static).border_title = title
        await self._refresh()
        self._timer = self.set_interval(2, self._refresh)

    async def _refresh(self):
        report = await asyncio.to_thread(self._hw.get_full_report)
        self._update_ui(report)

    def _update_ui(self, report: HardwareReport):
        cpu_graph = self.query_one("#cpu-graph", CpuGraph)
        cpu_graph.update_cpu(report.cpu)

        mem = report.memory
        mem_w = self.query_one("#memory-info", Static)
        mem_bar = "█" * min(int(mem.usage_percent / 5), 20) + "░" * (20 - min(int(mem.usage_percent / 5), 20))
        mem_w.update(
            f"[bold]Memory[/bold]\n"
            f"Total: {mem.total_gb:.1f} GB\n"
            f"Used: {mem.used_gb:.1f} GB  Available: {mem.available_gb:.1f} GB\n"
            f"Swap: {mem.swap_used_gb:.1f} / {mem.swap_total_gb:.1f} GB\n"
            f"[#2dd4bf on #0f111a]{mem_bar}[/] {mem.usage_percent}%\n"
        )

        disk_w = self.query_one("#disk-info", Static)
        disk_lines = ["[bold]Disks[/bold]"]
        for d in report.disks:
            bar = "█" * min(int(d.usage_percent / 5), 20) + "░" * (20 - min(int(d.usage_percent / 5), 20))
            disk_lines.append(
                f"{d.device} ({d.mount_point or '?'}):\n"
                f"{d.used_gb}/{d.total_gb} GB\n"
                f"[#2dd4bf on #0f111a]{bar}[/] {d.usage_percent}%\n"
            )
        disk_w.update("\n".join(disk_lines))

        gpu_w = self.query_one("#gpu-info", Static)
        if report.gpu:
            gpu_w.update(f"[bold]GPU[/bold]\n{report.gpu.model}\nVendor: {report.gpu.vendor or 'N/A'}")
        else:
            gpu_w.update("[bold]GPU[/bold]\nNot detected")

        net_w = self.query_one("#network-info", Static)
        net_lines = ["[bold]Network[/bold]"]
        for n in report.networks:
            net_lines.append(f"{n.interface}: MAC {n.mac_address or 'N/A'}")
        net_w.update("\n".join(net_lines))
