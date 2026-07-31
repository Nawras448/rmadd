from typing import Iterable, Optional, Set

from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Checkbox

from features.package_store.domain import PackageManager


class ManagerFilter(Horizontal):
    """Multi-select filter over package managers.

    A "الكل" (all) checkbox is checked by default and disables the per-manager
    checkboxes. Unchecking it enables the per-manager boxes (all initially
    checked). Selecting a subset posts Changed(selected) with selected=None
    meaning "all managers".
    """

    class Changed(Message):
        def __init__(self, filter: "ManagerFilter", selected: Optional[Set[PackageManager]]):
            super().__init__()
            self.filter = filter
            self.selected = selected

    def __init__(self, managers: Iterable[PackageManager], *, id: str | None = None, classes: str | None = None):
        super().__init__(id=id, classes=classes)
        self._managers = list(managers)
        self._all = True
        self._boxes: dict[PackageManager, Checkbox] = {}
        self._last_selected: Optional[Set[PackageManager]] = None

    def compose(self):
        yield Checkbox("الكل", value=True, id="all")
        for mgr in self._managers:
            yield Checkbox(mgr.value, value=False, disabled=True, id=f"mgr-{mgr.value}")

    def on_mount(self):
        self._boxes = {mgr: self.query_one(f"#mgr-{mgr.value}", Checkbox) for mgr in self._managers}
        self._last_selected = self.selected()

    def on_checkbox_changed(self, event: Checkbox.Changed):
        event.stop()
        cid = event.checkbox.id
        if cid == "all":
            self._all = event.value
            for box in self._boxes.values():
                box.disabled = self._all
                box.value = True
        else:
            if not any(box.value for box in self._boxes.values()):
                self._all = True
                self.query_one("#all", Checkbox).value = True
                for box in self._boxes.values():
                    box.disabled = True
        selected = self.selected()
        if selected != self._last_selected:
            self._last_selected = selected
            self.post_message(self.Changed(self, selected))

    def selected(self) -> Optional[Set[PackageManager]]:
        if self._all:
            return None
        return {mgr for mgr, box in self._boxes.items() if box.value}
