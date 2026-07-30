from abc import ABC, abstractmethod
from typing import Callable, Optional

from features.system_monitor.domain import (
    CpuInfo, MemoryInfo, DiskInfo, GpuInfo, NetworkInfo, HardwareReport
)


class MonitorHardwareUseCase(ABC):
    @abstractmethod
    def get_cpu_info(self) -> CpuInfo:
        pass

    @abstractmethod
    def get_memory_info(self) -> MemoryInfo:
        pass

    @abstractmethod
    def get_disk_info(self) -> list:
        pass

    @abstractmethod
    def get_gpu_info(self) -> Optional[GpuInfo]:
        pass

    @abstractmethod
    def get_network_info(self) -> list:
        pass

    @abstractmethod
    def get_full_report(self) -> HardwareReport:
        pass

    @abstractmethod
    def subscribe_cpu(self, callback: Callable[[CpuInfo], None]) -> None:
        pass

    @abstractmethod
    def subscribe_memory(self, callback: Callable[[MemoryInfo], None]) -> None:
        pass


class HardwareDataSource(ABC):
    @abstractmethod
    def get_cpu_info(self) -> CpuInfo:
        pass

    @abstractmethod
    def get_memory_info(self) -> MemoryInfo:
        pass

    @abstractmethod
    def get_disk_info(self) -> list:
        pass

    @abstractmethod
    def get_gpu_info(self) -> Optional[GpuInfo]:
        pass

    @abstractmethod
    def get_network_info(self) -> list:
        pass
