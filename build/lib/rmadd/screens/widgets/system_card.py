from textual.widgets import Static

from rmadd.models import SystemInfo


class SystemCard(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.border_title = "System Information"

    def display_info(self, info: SystemInfo):
        d = info.distribution
        distro = d.pretty_name or " ".join(x for x in (d.id, d.version) if x) or "N/A"
        self.update(
            f"[bold]System Information[/bold]\n\n"
            f"Hostname:      {info.hostname}\n"
            f"OS:            {info.os}\n"
            f"Distribution:  {distro}\n"
            f"Kernel:        {info.kernel}\n"
            f"Architecture:  {info.architecture}\n"
            f"Uptime:        {info.uptime or 'N/A'}\n"
        )
