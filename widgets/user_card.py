from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Label, Static
from textual.binding import Binding

# استيراد الواجهات الفرعية
from widgets.About import About
from widgets.settings_view import SettingsView


class UserCard(Static):
    # تعيين اسم التطبيق والعنوان الفرعي
    TITLE = "rmadd"
    SUB_TITLE = "v0.1.0-dev | Package & System Monitor"

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "refresh", "Refresh Data", show=True),
        
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

        with Horizontal():
            # الشريط الجانبي
            with Vertical(id="tartib"):
                yield Static("option", id="sidebar-title")
                yield Button("program", id="btn_programs")
                yield Button("settings", id="btn_settings")
                yield Button("About", id="btn_About")

            # منطقة عرض المحتوى المتغير
            with Vertical(id="content"):
                yield Static("Programs View") 
                 # العرض الافتراضي عند فتح التطبيق

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """مُعالج الأحداث: التنقل بين الصفحات بناءً على الزر المضغوط"""

        content_area = self.query_one("#content", Vertical)

        if event.button.id == "btn_programs":
            content_area.remove_children()
            content_area.mount(Static("Programs View"))

        elif event.button.id == "btn_settings":
            content_area.remove_children()
            content_area.mount(SettingsView())

        elif event.button.id == "btn_About":
            content_area.remove_children()
            content_area.mount(About())
            