from textual.screen import Screen
from textual.widgets import Header, Footer, Static
from textual.containers import Vertical, Horizontal
from textual.binding import Binding


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
        with Vertical(id="full-system-content"):
            yield Static(id="fs-system", classes="fs-section")
            yield Static(id="fs-cpu", classes="fs-section")
            yield Static(id="fs-memory", classes="fs-section")
            yield Static(id="fs-disks", classes="fs-section")
            yield Static(id="fs-gpu", classes="fs-section")
            yield Static(id="fs-network", classes="fs-section")
        yield Footer()

    def on_mount(self):
        info = self._ss.get_system_info()
        self.query_one("#fs-system", Static).update(
            f"[bold underline]System[/bold underline]\n"
            f"Hostname:    {info.hostname}\n"
            f"OS:          {info.os}\n"
            f"Kernel:      {info.kernel}\n"
            f"Arch:        {info.architecture}\n"
        )

        cpu = self._hw.get_cpu_info()
        temp = f"{cpu.temperature_celsius:.0f}°C" if cpu.temperature_celsius is not None else "N/A"
        self.query_one("#fs-cpu", Static).update(
            f"[bold underline]CPU[/bold underline]\n"
            f"Model:       {cpu.model}\n"
            f"Vendor:      {cpu.vendor}\n"
            f"Cores:       {cpu.cores}  Threads: {cpu.threads}\n"
            f"Freq:        {cpu.frequency_mhz:.0f} MHz\n"
            f"Cache:       {cpu.cache_kb} KB\n"
            f"Temp:        {temp}\n"
            f"Usage:       {cpu.usage_percent}%\n"
        )

        mem = self._hw.get_memory_info()
        self.query_one("#fs-memory", Static).update(
            f"[bold underline]Memory[/bold underline]\n"
            f"Total:       {mem.total_gb:.1f} GB\n"
            f"Used:        {mem.used_gb:.1f} GB\n"
            f"Available:   {mem.available_gb:.1f} GB\n"
            f"Usage:       {mem.usage_percent}%\n"
            f"Swap Total:  {mem.swap_total_gb:.1f} GB\n"
            f"Swap Used:   {mem.swap_used_gb:.1f} GB\n"
        )

        disks = self._hw.get_disk_info()
        disk_lines = ["[bold underline]Disks[/bold underline]"]
        for d in disks:
            disk_lines.append(
                f"Device:      {d.device}\n"
                f"Mount:       {d.mount_point or 'N/A'}\n"
                f"Size:        {d.total_gb:.1f} GB  Used: {d.used_gb:.1f} GB ({d.usage_percent}%)\n"
            )
        self.query_one("#fs-disks", Static).update("\n".join(disk_lines) if disk_lines[1:] else "[bold underline]Disks[/bold underline]\nNo disk info")

        gpu = self._hw.get_gpu_info()
        if gpu:
            self.query_one("#fs-gpu", Static).update(
                f"[bold underline]GPU[/bold underline]\n"
                f"Model:       {gpu.model}\n"
                f"Vendor:      {gpu.vendor or 'N/A'}\n"
            )
        else:
            self.query_one("#fs-gpu", Static).update("[bold underline]GPU[/bold underline]\nNot detected")

        nets = self._hw.get_network_info()
        net_lines = ["[bold underline]Network[/bold underline]"]
        for n in nets:
            net_lines.append(f"{n.interface}:  MAC {n.mac_address or 'N/A'}")
        self.query_one("#fs-network", Static).update("\n".join(net_lines))
