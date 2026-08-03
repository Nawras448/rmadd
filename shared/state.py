from typing import Callable


class PackageStateBus:
    """App-wide pub/sub for package status changes.

    Single source of truth for "a package was installed/removed/updated".
    Emitted by InstallProgressScreen on success; consumed by every view so
    all tabs stay synchronized without a restart.
    """

    def __init__(self):
        self._listeners: list[Callable[[str, str, object], None]] = []

    def subscribe(self, fn) -> None:
        if fn not in self._listeners:
            self._listeners.append(fn)

    def unsubscribe(self, fn) -> None:
        if fn in self._listeners:
            self._listeners.remove(fn)

    def emit(self, kind: str, name: str, mgr) -> None:
        for fn in list(self._listeners):
            fn(kind, name, mgr)
