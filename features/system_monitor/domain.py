from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class CpuInfo:
    model: str = ""
    vendor: str = ""
    cores: int = 0
    threads: int = 0
    frequency_mhz: float = 0.0
    max_frequency_mhz: float = 0.0
    cache_kb: int = 0
    temperature_celsius: Optional[float] = None
    usage_percent: float = 0.0


@dataclass
class MemoryInfo:
    total_gb: float = 0.0
    used_gb: float = 0.0
    available_gb: float = 0.0
    swap_total_gb: float = 0.0
    swap_used_gb: float = 0.0
    usage_percent: float = 0.0


@dataclass
class DiskInfo:
    device: str = ""
    mount_point: str = ""
    total_gb: float = 0.0
    used_gb: float = 0.0
    available_gb: float = 0.0
    usage_percent: float = 0.0
    filesystem: str = ""


@dataclass
class GpuInfo:
    model: str = ""
    vendor: str = ""
    driver: str = ""
    memory_mb: Optional[int] = None
    temperature_celsius: Optional[float] = None


@dataclass
class NetworkInfo:
    interface: str = ""
    ip_address: str = ""
    mac_address: str = ""
    rx_bytes: int = 0
    tx_bytes: int = 0


@dataclass
class HardwareReport:
    cpu: CpuInfo = field(default_factory=CpuInfo)
    memory: MemoryInfo = field(default_factory=MemoryInfo)
    disks: List[DiskInfo] = field(default_factory=list)
    gpu: Optional[GpuInfo] = None
    networks: List[NetworkInfo] = field(default_factory=list)
