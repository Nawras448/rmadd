import asyncio
import math
import queue
import re
import threading
import time
from collections.abc import Callable

from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ProgressBar, RichLog, Static

from rmadd.models import PackageManager
from rmadd.package_managers.base import FailureReason, OpResult
from rmadd.screens.op_feedback import is_auth_prompt


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
        on_finish: Callable[[str, str, PackageManager, bool, bool, bool, OpResult | None], None] | None = None,
        section: str = "",
        executor: Callable | None = None,
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
        self._real_pct: float | None = None
        self._tick_timer = None
        self._eta_timer = None
        self._auth_seen = False
        self._title_base = ""

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
        self._title_base = self.TITLE_LABELS[self._action].format(
            name=self._name, mgr=self._mgr.value
        )
        self.query_one("#progress-title", Static).update(self._title_base)
        try:
            self.query_one("#btn-progress-cancel", Button).focus()
        except Exception:
            pass
        self._tick_timer = self.set_interval(0.05, self._drain_queue)
        self._eta_timer = self.set_interval(0.5, self._update_eta)
        self._update_eta()
        asyncio.create_task(self._run())

    # ---------- operation ----------

    _RESULT_METHODS = {
        "install": "install_result",
        "remove": "remove_result",
        "update": "update_result",
    }

    async def _run(self):
        try:
            if self._executor is not None:
                ok = await asyncio.to_thread(
                    self._executor, self._name, self._mgr, self._queue.put, self._cancel_event
                )
                cancelled = self._cancel_event.is_set()
                result = OpResult(
                    ok=bool(ok),
                    cancelled=cancelled and not ok,
                    reason=(
                        FailureReason.NONE
                        if ok
                        else (FailureReason.CANCELLED if cancelled else FailureReason.FAILED)
                    ),
                )
            else:
                method = getattr(self._ps, self._RESULT_METHODS[self._action])
                result = await asyncio.to_thread(
                    method,
                    self._name,
                    self._mgr,
                    on_output=self._queue.put,
                    cancel_event=self._cancel_event,
                )
            self._finish(result)
        except Exception as e:
            self._queue.put(f"Error: {e}\n")
            self._finish(OpResult(False, reason=FailureReason.FAILED, tail=str(e)))

    def _emit(self, phase: str):
        bus = getattr(self.app, "state_bus", None)
        if bus is not None and self._action in ("install", "remove", "update"):
            bus.emit(self._action, self._name, self._mgr, phase)

    def _finish(self, result: OpResult):
        if self._done:
            return
        self._done = True
        if self._tick_timer is not None:
            self._tick_timer.stop()
        if self._eta_timer is not None:
            self._eta_timer.stop()
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.update(total=100, progress=100)
        ok = result.ok
        if ok:
            self._queue.put("Done.\n")
            self._emit("confirmed")
        elif self._cancel_event.is_set():
            self._queue.put("Operation cancelled.\n")
            self._emit("reverted")
        else:
            self._queue.put(f"Operation failed: {result.describe()}\n")
            self._emit("reverted")
        self._drain_queue()
        if self._on_finish is not None:
            self._on_finish(
                self._action,
                self._section,
                self._name,
                self._mgr,
                ok,
                self._cancel_event.is_set(),
                result,
            )
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
            if not self._auth_seen and is_auth_prompt(line):
                self._auth_seen = True
                try:
                    self.query_one("#progress-title", Static).update(
                        f"{self._title_base} — [yellow]awaiting authentication[/yellow]"
                    )
                except Exception:
                    pass
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
