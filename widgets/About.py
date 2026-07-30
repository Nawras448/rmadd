from textual.app import ComposeResult
from textual.widgets import Static
from textual.containers import Vertical , Horizontal
from core.core import SystemInfo
from textual.widgets import Button, Label, Static


sys_info = SystemInfo()
system_info = sys_info.get_system_info()
system_info2 = sys_info.get_system_info()

class About(Static):

    def compose(self) -> ComposeResult:
        yield Label("                   Developer\n\n# Developed by Nawras - Software Developer\n# GitHub: https://github.com/Nawras448\n")
        yield Static(f"                 system info\n\nHostname: {system_info['hostname']}\nOS: {system_info['os']}\n")
        yield Static(f"hostnamectl : {system_info2['hostnamectl']}\n\n")
        yield Static("\nNumber of programs on the device\n", id="programs-title")
        yield Vertical(id="packages-list") ## خيار عرض برنامج
        yield Horizontal(id="About_system")

    
    def on_mount(self) -> None:

        
        container = self.query_one("#packages-list", Vertical)

        # جلب القاموس الذي يحتوي فقط على مديري الحزم الشغالين في جهاز المستخدم
        all_counts = sys_info.get_all_counts()

        for manager, count in all_counts.items():
            container.mount(Static(f"{manager.upper()} Count: {count}"))