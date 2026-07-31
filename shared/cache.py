import time
from typing import Any, Callable

from features.system_info.ports import SystemDataSource
from features.system_monitor.ports import HardwareDataSource
from features.system_info.domain import Distribution
from features.system_monitor.domain import CpuInfo, MemoryInfo, DiskInfo, GpuInfo, NetworkInfo


class _CacheMixin:
    def __init__(self, ttl_seconds: int):
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[float, Any]] = {}

    def _cached(self, key: str, fetch: Callable) -> Any:
        now = time.time()
        if key in self._cache:
            ts, val = self._cache[key]
            if now - ts < self._ttl:
                return val
        result = fetch()
        self._cache[key] = (now, result)
        return result


class CachingSystemAdapter(_CacheMixin, SystemDataSource):
    def __init__(self, inner: SystemDataSource, ttl_seconds: int = 60):
        _CacheMixin.__init__(self, ttl_seconds)
        self._inner = inner

    def get_hostname(self) -> str: return self._cached("hostname", self._inner.get_hostname)
    def get_os_release(self) -> str: return self._cached("os", self._inner.get_os_release)
    def get_kernel(self) -> str: return self._cached("kernel", self._inner.get_kernel)
    def get_architecture(self) -> str: return self._cached("arch", self._inner.get_architecture)
    def get_hostnamectl(self) -> str: return self._cached("hostnamectl", self._inner.get_hostnamectl)
    def get_uptime(self) -> str: return self._cached("uptime", self._inner.get_uptime)
    def get_distribution(self) -> Distribution: return self._cached("distribution", self._inner.get_distribution)


class CachingHardwareAdapter(_CacheMixin, HardwareDataSource):
    def __init__(self, inner: HardwareDataSource, ttl_seconds: int = 5):
        _CacheMixin.__init__(self, ttl_seconds)
        self._inner = inner

    def get_cpu_info(self) -> CpuInfo: return self._cached("cpu", self._inner.get_cpu_info)
    def get_memory_info(self) -> MemoryInfo: return self._cached("memory", self._inner.get_memory_info)
    def get_disk_info(self) -> list: return self._cached("disk", self._inner.get_disk_info)
    def get_gpu_info(self) -> GpuInfo | None: return self._cached("gpu", self._inner.get_gpu_info)
    def get_network_info(self) -> list: return self._cached("network", self._inner.get_network_info)
