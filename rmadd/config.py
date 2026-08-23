"""JSON-backed user configuration for rmadd."""

import copy
import json
import os

APP_NAME = "rmadd"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "ui": {
        "mode": "tui",
        "theme": "dark",
        "refresh_interval_seconds": 5,
        "confirm_removal": False,
    },
    "monitoring": {"enabled": True, "cpu_interval_seconds": 2, "memory_interval_seconds": 3},
    "package_managers": {
        "enabled": ["apt", "dnf", "pacman", "snap", "flatpak"],
        "privilege_escalation": "pkexec",
        "op_timeout_seconds": 600,
    },
    "cache": {"system_ttl_seconds": 60, "hardware_ttl_seconds": 3},
}


class Config:
    def __init__(self, path: str | None = None):
        self._path = path or CONFIG_FILE
        self._data: dict = copy.deepcopy(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        from rmadd.logging import get_logger
        logger = get_logger("config")
        try:
            if os.path.exists(self._path):
                with open(self._path) as f:
                    loaded = json.load(f)
                    self._deep_merge(self._data, loaded)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")

    def save(self):
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(self._data, f, indent=2)

    def _deep_merge(self, base: dict, override: dict):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v

    @property
    def ui_mode(self) -> str:
        return self._data["ui"]["mode"]

    @ui_mode.setter
    def ui_mode(self, value: str):
        self._data["ui"]["mode"] = value

    @property
    def refresh_interval(self) -> int:
        return self._data["ui"]["refresh_interval_seconds"]

    @property
    def enabled_managers(self) -> list:
        return self._data["package_managers"]["enabled"]

    @property
    def confirm_removal(self) -> bool:
        """Opt-in confirmation modal before package removals."""
        return bool(self._data["ui"].get("confirm_removal", False))

    @confirm_removal.setter
    def confirm_removal(self, value) -> None:
        self._data["ui"]["confirm_removal"] = bool(value)

    @property
    def op_timeout_seconds(self) -> float:
        """Execution budget for streamed package operations."""
        try:
            value = float(self._data["package_managers"].get("op_timeout_seconds", 600))
        except (TypeError, ValueError):
            return 600.0
        return value if value > 0 else 600.0

    @op_timeout_seconds.setter
    def op_timeout_seconds(self, value) -> None:
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"op_timeout_seconds must be numeric, got {value!r}") from None
        if num <= 0:
            raise ValueError("op_timeout_seconds must be positive")
        self._data["package_managers"]["op_timeout_seconds"] = num
        # Adapters read the module-level default at construction time; keep
        # both in sync so newly discovered managers pick the new budget.
        from rmadd.package_managers.base import set_default_execution_timeout

        set_default_execution_timeout(num)
