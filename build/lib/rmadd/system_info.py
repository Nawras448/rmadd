"""System information: display adapter and cached info service."""

import subprocess
from abc import ABC, abstractmethod

from rmadd.models import Distribution, SystemInfo


class SystemDataSource(ABC):
    @abstractmethod
    def get_hostname(self) -> str:
        pass

    @abstractmethod
    def get_os_release(self) -> str:
        pass

    @abstractmethod
    def get_kernel(self) -> str:
        pass

    @abstractmethod
    def get_architecture(self) -> str:
        pass

    @abstractmethod
    def get_hostnamectl(self) -> str:
        pass

    @abstractmethod
    def get_uptime(self) -> str:
        pass

    @abstractmethod
    def get_distribution(self) -> Distribution:
        pass


_RUN_TIMEOUT = 5


def _run_cmd(cmd: list) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=_RUN_TIMEOUT).stdout.strip()
    except Exception:
        return "Unknown"


def _read_uptime() -> str:
    try:
        with open("/proc/uptime") as f:
            seconds = float(f.read().split()[0])
        days, rem = divmod(int(seconds), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, secs = divmod(rem, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if secs or not parts:
            parts.append(f"{secs}s")
        return " ".join(parts)
    except Exception:
        return "Unknown"


class HostnamectlAdapter(SystemDataSource):
    def get_hostname(self) -> str:
        return _run_cmd(["hostname"])

    def get_os_release(self) -> str:
        out = _run_cmd(["lsb_release", "-d"])
        return out.split(":", 1)[-1].strip() if ":" in out else out

    def get_kernel(self) -> str:
        return _run_cmd(["uname", "-r"])

    def get_architecture(self) -> str:
        return _run_cmd(["uname", "-m"])

    def get_hostnamectl(self) -> str:
        return _run_cmd(["hostnamectl"])

    def get_uptime(self) -> str:
        return _read_uptime()

    def get_distribution(self) -> Distribution:
        d = Distribution()
        try:
            out = subprocess.run(
                ["lsb_release", "-a"], capture_output=True, text=True, timeout=_RUN_TIMEOUT
            ).stdout
            for line in out.strip().split("\n"):
                if "Distributor ID" in line:
                    d.id = line.split(":", 1)[-1].strip()
                elif "Release" in line:
                    d.version = line.split(":", 1)[-1].strip()
                elif "Codename" in line:
                    d.codename = line.split(":", 1)[-1].strip()
                elif "Description" in line:
                    d.pretty_name = line.split(":", 1)[-1].strip()
        except Exception:
            pass
        return d

class SystemInfoService:
    def __init__(self, data_source: SystemDataSource):
        self._ds = data_source
        self._cache: SystemInfo | None = None

    def get_system_info(self) -> SystemInfo:
        if self._cache:
            return self._cache
        return self._build()

    def refresh(self) -> None:
        self._cache = None

    def _build(self) -> SystemInfo:
        self._cache = SystemInfo(
            hostname=self._ds.get_hostname(),
            os=self._ds.get_os_release(),
            kernel=self._ds.get_kernel(),
            architecture=self._ds.get_architecture(),
            hostnamectl_output=self._ds.get_hostnamectl(),
            uptime=self._ds.get_uptime(),
            distribution=self._ds.get_distribution(),
        )
        return self._cache

