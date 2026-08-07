"""App-wide pub/sub bus for package status changes across views."""

from typing import Callable


class PackageStateBus:
    """Single source of truth for "a package was installed/removed/updated".

    Emitted by the UI on operation lifecycle changes; consumed by every tab so
    the whole UI stays synchronized without a restart.

    The `phase` qualifier expresses lifecycle:
      "pending"    -> op started (optimistic write), emitted before the modal opens
      "confirmed"  -> op succeeded (default), emitted on completion
      "reverted"   -> op failed or was cancelled, undo the optimistic write

    The 3-arg form `emit(kind, name, mgr)` is kept for backward compatibility
    and is equivalent to `phase="confirmed"`.
    """

    def __init__(self):
        self._listeners: list[Callable[[str, str, object, str], None]] = []

    def subscribe(self, fn) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    def unsubscribe(self, fn) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def emit(self, kind: str, name: str, mgr, phase: str = "confirmed") -> None:
        for fn in list(self._listeners):
            fn(kind, name, mgr, phase)