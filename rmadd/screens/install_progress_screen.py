import asyncio
import math
import queue
import re
import threading
import time
from typing import Callable, Optional

from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Button, ProgressBar, RichLog
from textual.containers import Horizontal, Vertical

from rmadd.models import PackageManager


class InstallProgressScreen(Screen):
    """Modal panel showing live progress of an install/remove/update operation.

    Displays a determinate progress bar (estimated, with real percentages
    parsed from manager output when available), a live ETA, a Cancel button,
    and an auto-scrolling console with the full command output.
    """

    TITLE_LABELS = {
        "install": "Installing {name} via {mgr}...",
        "remove": "Removing {name} via {mgr}...",
        "update": "Updating {name} via {mgr}...",
    }

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        package_service,
        action: str,
        name: str,
        manager: PackageManager,
        on_finish: Optional[Callable[[str, str, PackageManager, bool, bool], None]] = None,
        section: str = "",
        executor: Optional[Callable] = None,
    ):
        super().__init__()
        self._ps = package_service
        self._action = action
        self._name = name
        self._mgr = manager
        self._on_finish = on_finish
        self._section = section
        self._executor = executor
        self._cancel_event = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        self._start = time.monotonic()
        self._done = False
        self._pct = 0.0
        self._real_pct: Optional[float] = None
        self._tick_timer = None
        self._eta_timer = None

    def compose(self):
        yield Header(show_clock=True)
        with Vertical(id="progress-panel"):
            yield Static(id="progress-title", classes="progress-title")
            with Horizontal(id="progress-stats"):
                yield ProgressBar(total=100, show_percentage=True, show_eta=False, id="progress-bar")
                yield Static("ETA: --:--s", id="progress-eta", classes="progress-eta")
            with Horizontal(id="progress-buttons"):
                yield Button("Cancel", id="btn-progress-cancel", variant="error")
            yield RichLog(id="progress-console", highlight=True, wrap=True, max_lines=500)
        yield Footer()

    def on_mount(self):
        self.query_one("#progress-title", Static).update(
            self.TITLE_LABELS[self._action].format(name=self._name, mgr=self._mgr.value)
        )
        self._tick_timer = self.set_interval(0.05, self._drain_queue)
        self._eta_timer = self.set_interval(0.5, self._update_eta)
        self._update_eta()
        asyncio.create_task(self._run())

    # ---------- operation ----------

    async def _run(self):
        try:
            if self._executor is not None:
                ok = await asyncio.to_thread(
                    self._executor, self._name, self._mgr, self._queue.put, self._cancel_event
                )
            else:
                method = getattr(self._ps, self._action)
                ok = await asyncio.to_thread(
                    method, self._name, self._mgr, None, self._queue.put, self._cancel_event
                )
            self._finish(ok)
        except Exception as e:
            self._queue.put(f"Error: {e}\n")
            self._finish(False)

    def _finish(self, ok: bool):
        if self._done:
            return
        self._done = True
        if self._tick_timer is not None:
            self._tick_timer.stop()
        if self._eta_timer is not None:
            self._eta_timer.stop()
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.update(total=100, progress=100)
        if ok:
            self._queue.put("Done.\n")
            bus = getattr(self.app, "state_bus", None)
            if bus is not None and self._action in ("install", "remove", "update"):
                bus.emit(self._action, self._name, self._mgr)
        elif self._cancel_event.is_set():
            self._queue.put("Operation cancelled.\n")
        else:
            self._queue.put("Operation failed.\n")
        self._drain_queue()
        if self._on_finish is not None:
            self._on_finish(self._action, self._section, self._name, self._mgr, ok, self._cancel_event.is_set())
        self.set_timer(1.5, self._schedule_dismiss)

    def _schedule_dismiss(self):
        self.dismiss()

    def action_cancel(self):
        if self._done:
            self.dismiss()
            return
        if not self._cancel_event.is_set():
            self._cancel_event.set()
            self.query_one("#btn-progress-cancel", Button).disabled = True
            self._queue.put("Cancelling...\n")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "btn-progress-cancel":
            self.action_cancel()

    # ---------- UI updates ----------

    def _drain_queue(self):
        lines = []
        try:
            while True:
                lines.append(self._queue.get_nowait())
        except queue.Empty:
            pass
        if not lines:
            return
        for line in lines:
            match = re.search(r"(\d{1,3})\s*%", line)
            if match and match.group(1) != "100":
                self._real_pct = float(match.group(1))
            lowered = line.lower()
            if any(k in lowered for k in ("unpacking", "preparing", "configuring", "running postinstall")):
                self._pct = max(self._pct, 75.0)
        self.query_one("#progress-console", RichLog).write("".join(lines).rstrip("\n"))

    def _update_eta(self):
        if self._done:
            return
        elapsed = time.monotonic() - self._start
        base = 5.0 + 65.0 * (1.0 - math.exp(-elapsed / 15.0))
        pct = max(base, self._pct)
        if self._real_pct is not None:
            pct = max(pct, 5.0 + 0.65 * self._real_pct)
        pct = min(pct, 99.0)
        rate = (65.0 / 15.0) * math.exp(-elapsed / 15.0)
        eta = (100.0 - pct) / rate if rate > 0.01 else 0.0
        self.query_one("#progress-bar", ProgressBar).progress = pct
        minutes, seconds = divmod(int(eta), 60)
        self.query_one("#progress-eta", Static).update(f"ETA: {minutes:02d}:{seconds:02d}s")
