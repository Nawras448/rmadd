from textual.widgets import Static

from features.system_monitor.domain import CpuInfo


class CpuGraph(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "CPU"

    def update_cpu(self, info: CpuInfo):
        bar_len = min(int(info.usage_percent / 5), 20)
        bar = "█" * bar_len + "░" * (20 - bar_len)
        temp = f"{info.temperature_celsius:.0f}" if info.temperature_celsius is not None else "N/A"
        self.update(
            f"[bold]CPU[/bold]\n"
            f"Model: {info.model}\n"
            f"Cores: {info.cores}  Threads: {info.threads}\n"
            f"Freq: {info.frequency_mhz:.0f} MHz\n"
            f"Temp: {temp}°C\n"
            f"[#2dd4bf on #0f111a]{bar}[/] {info.usage_percent:.1f}%\n"
        )
