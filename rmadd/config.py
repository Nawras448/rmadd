"""JSON-backed user configuration for rmadd."""

import json
import os
from typing import Optional

APP_NAME = "rmadd"
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", APP_NAME)
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULT_CONFIG = {
    "ui": {"mode": "tui", "theme": "dark", "refresh_interval_seconds": 5},
    "monitoring": {"enabled": True, "cpu_interval_seconds": 2, "memory_interval_seconds": 3},
    "package_managers": {"enabled": ["apt", "dnf", "pacman", "snap", "flatpak"], "privilege_escalation": "pkexec"},
    "cache": {"system_ttl_seconds": 60, "hardware_ttl_seconds": 3},
}


class Config:
    def __init__(self, path: Optional[str] = None):
        self._path = path or CONFIG_FILE
        self._data = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        try:
            if os.path.exists(self._path):
                with open(self._path) as f:
                    loaded = json.load(f)
                    self._deep_merge(self._data, loaded)
        except Exception:
            pass

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