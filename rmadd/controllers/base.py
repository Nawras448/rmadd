"""Shared plumbing for StoreScreen sub-controllers."""



class Controller:
    """Base class wiring a controller to its host StoreScreen.

    Controllers never talk to each other directly; sibling coordination goes
    through ``self.ui.<controller>`` resolved at call time, which keeps
    construction order trivial and mirrors how widgets reach each other.
    """

    def __init__(self, ui):
        self.ui = ui

    @property
    def ps(self):
        return self.ui._ps

    @property
    def ss(self):
        return self.ui._ss

    @property
    def app(self):
        return self.ui.app

    @property
    def bus(self):
        return self.ui.app.state_bus

    @property
    def opt(self):
        """The shared OptimisticPackageState owned by OperationsController."""
        return self.ui.optimistic

    def track(self, coro):
        return self.ui.track(coro)

    def result(self, section: str):
        return self.ui.result(section)
