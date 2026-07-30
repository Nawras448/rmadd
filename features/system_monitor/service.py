from typing import Callable, Optional

from features.system_monitor.ports import MonitorHardwareUseCase, HardwareDataSource
from features.system_monitor.domain import (
    CpuInfo, MemoryInfo, DiskInfo, GpuInfo, NetworkInfo, HardwareReport
)


class HardwareMonitorService(MonitorHardwareUseCase):
    def __init__(self, data_source: HardwareDataSource):
        self._ds = data_source
        self._cpu_callbacks: list[Callable[[CpuInfo], None]] = []
        self._mem_callbacks: list[Callable[[MemoryInfo], None]] = []

    def get_cpu_info(self) -> CpuInfo:
        return self._ds.get_cpu_info()

    def get_memory_info(self) -> MemoryInfo:
        return self._ds.get_memory_info()

    def get_disk_info(self) -> list:
        return self._ds.get_disk_info()

    def get_gpu_info(self) -> Optional[GpuInfo]:
        return self._ds.get_gpu_info()

    def get_network_info(self) -> list:
        return self._ds.get_network_info()

    def get_full_report(self) -> HardwareReport:
        return HardwareReport(
            cpu=self.get_cpu_info(),
            memory=self.get_memory_info(),
            disks=self.get_disk_info(),
            gpu=self.get_gpu_info(),
            networks=self.get_network_info(),
        )

    def subscribe_cpu(self, callback: Callable[[CpuInfo], None]) -> None:
        self._cpu_callbacks.append(callback)

    def subscribe_memory(self, callback: Callable[[MemoryInfo], None]) -> None:
        self._mem_callbacks.append(callback)
