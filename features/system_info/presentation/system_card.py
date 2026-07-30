from textual.widgets import Static

from features.system_info.domain import SystemInfo


class SystemCard(Static):
    def display_info(self, info: SystemInfo):
        self.update(
            f"[bold]System Information[/bold]\n\n"
            f"Hostname: {info.hostname}\n"
            f"OS: {info.os}\n"
            f"Kernel: {info.kernel}\n"
            f"Architecture: {info.architecture}\n"
        )
