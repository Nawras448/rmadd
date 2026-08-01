import asyncio

from textual.screen import Screen
from textual.widgets import Header, Footer, Static
from textual.containers import Vertical, Horizontal
from textual.binding import Binding

from features.ui_switch.presentation.tui.navigation import NavigationSidebar


class FullSystemScreen(Screen):
    BINDINGS = [
        Binding("escape", "dismiss", "Back"),
    ]

    def __init__(self, system_service, hardware_service):
        super().__init__()
        self._ss = system_service
        self._hw = hardware_service

    def compose(self):
        yield Header(show_clock=True)
        with Horizontal():
            yield NavigationSidebar(id="sidebar")
            with Vertical(id="full-system-content"):
                yield Static(id="fs-system", classes="fs-section")
                yield Static(id="fs-cpu", classes="fs-section")
                yield Static(id="fs-memory", classes="fs-section")
                yield Static(id="fs-disks", classes="fs-section")
                yield Static(id="fs-gpu", classes="fs-section")
                yield Static(id="fs-network", classes="fs-section")
        yield Footer()

    async def on_mount(self):
        for section_id, title in (
            ("fs-system", "System"),
            ("fs-cpu", "CPU"),
            ("fs-memory", "Memory"),
            ("fs-disks", "Disks"),
            ("fs-gpu", "GPU"),
            ("fs-network", "Network"),
        ):
            self.query_one(f"#{section_id}", Static).border_title = title
        for section_id in ("fs-system", "fs-cpu", "fs-memory", "fs-disks", "fs-gpu", "fs-network"):
            self.query_one(f"#{section_id}", Static).update("[yellow]Loading...[/yellow]")
        asyncio.create_task(self._load_system())
        asyncio.create_task(self._load_cpu())
        asyncio.create_task(self._load_memory())
        asyncio.create_task(self._load_disks())
        asyncio.create_task(self._load_gpu())
        asyncio.create_task(self._load_network())

    async def _load_system(self):
        try:
            info = await asyncio.to_thread(self._ss.get_system_info)
            d = info.distribution
            distro = d.pretty_name or " ".join(x for x in (d.id, d.version) if x) or "N/A"
            self.query_one("#fs-system", Static).update(
                f"[bold underline]System[/bold underline]\n"
                f"Hostname:      {info.hostname}\n"
                f"OS:            {info.os}\n"
                f"Distribution:  {distro}\n"
                f"Kernel:        {info.kernel}\n"
                f"Architecture:  {info.architecture}\n"
                f"Uptime:        {info.uptime or 'N/A'}\n"
            )
        except Exception as e:
            self.query_one("#fs-system", Static).update(f"[bold red]Error: {e}[/bold red]")

    async def _load_cpu(self):
        try:
            cpu = await asyncio.to_thread(self._hw.get_cpu_info)
            temp = f"{cpu.temperature_celsius:.0f}°C" if cpu.temperature_celsius is not None else "N/A"
            self.query_one("#fs-cpu", Static).update(
                f"[bold underline]CPU[/bold underline]\n"
                f"Model:         {cpu.model}\n"
                f"Vendor:        {cpu.vendor}\n"
                f"Cores:         {cpu.cores}  Threads: {cpu.threads}\n"
                f"Frequency:     {cpu.frequency_mhz:.0f} MHz\n"
                f"Cache:         {cpu.cache_kb} KB\n"
                f"Temperature:   {temp}\n"
                f"Usage:         {cpu.usage_percent}%\n"
            )
        except Exception as e:
            self.query_one("#fs-cpu", Static).update(f"[bold red]Error: {e}[/bold red]")

    async def _load_memory(self):
        try:
            mem = await asyncio.to_thread(self._hw.get_memory_info)
            self.query_one("#fs-memory", Static).update(
                f"[bold underline]Memory[/bold underline]\n"
                f"Total:         {mem.total_gb:.1f} GB\n"
                f"Used:          {mem.used_gb:.1f} GB\n"
                f"Available:     {mem.available_gb:.1f} GB\n"
                f"Usage:         {mem.usage_percent}%\n"
                f"Swap Total:    {mem.swap_total_gb:.1f} GB\n"
                f"Swap Used:     {mem.swap_used_gb:.1f} GB\n"
            )
        except Exception as e:
            self.query_one("#fs-memory", Static).update(f"[bold red]Error: {e}[/bold red]")

    async def _load_disks(self):
        try:
            disks = await asyncio.to_thread(self._hw.get_disk_info)
            disk_lines = ["[bold underline]Disks[/bold underline]"]
            for d in disks:
                disk_lines.append(
                    f"Device:        {d.device}\n"
                    f"Mount:         {d.mount_point or 'N/A'}\n"
                    f"Size:          {d.total_gb:.1f} GB  Used: {d.used_gb:.1f} GB ({d.usage_percent}%)\n"
                )
            self.query_one("#fs-disks", Static).update("\n".join(disk_lines) if disk_lines[1:] else "[bold underline]Disks[/bold underline]\nNo disk info")
        except Exception as e:
            self.query_one("#fs-disks", Static).update(f"[bold red]Error: {e}[/bold red]")

    async def _load_gpu(self):
        try:
            gpu = await asyncio.to_thread(self._hw.get_gpu_info)
            if gpu:
                self.query_one("#fs-gpu", Static).update(
                    f"[bold underline]GPU[/bold underline]\n"
                    f"Model:         {gpu.model}\n"
                    f"Vendor:        {gpu.vendor or 'N/A'}\n"
                )
            else:
                self.query_one("#fs-gpu", Static).update("[bold underline]GPU[/bold underline]\nNot detected")
        except Exception as e:
            self.query_one("#fs-gpu", Static).update(f"[bold red]Error: {e}[/bold red]")

    async def _load_network(self):
        try:
            nets = await asyncio.to_thread(self._hw.get_network_info)
            net_lines = ["[bold underline]Network[/bold underline]"]
            for n in nets:
                net_lines.append(f"{n.interface}:  MAC {n.mac_address or 'N/A'}")
            self.query_one("#fs-network", Static).update("\n".join(net_lines))
        except Exception as e:
            self.query_one("#fs-network", Static).update(f"[bold red]Error: {e}[/bold red]")
