"""Hardware monitoring: procfs readers and report service."""

import os
import re
import shutil
import subprocess
import time
from abc import ABC, abstractmethod

from rmadd.models import (
    CpuInfo,
    DiskInfo,
    GpuInfo,
    HardwareReport,
    MemoryInfo,
    NetworkInfo,
)


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
    def get_gpu_info(self) -> GpuInfo | None:
        pass

    @abstractmethod
    def get_network_info(self) -> list:
        pass


class _CpuReader:
    def __init__(self):
        self._prev_stat: tuple | None = None

    def read(self) -> CpuInfo:
        info = CpuInfo()
        try:
            with open("/proc/cpuinfo") as f:
                data = f.read()
            phys_id = ""
            physical_cores: set[tuple[str, str]] = set()
            for line in data.split("\n"):
                if line.startswith("processor"):
                    info.threads += 1
                elif line.startswith("physical id"):
                    phys_id = line.split(":", 1)[-1].strip()
                elif line.startswith("core id"):
                    physical_cores.add((phys_id, line.split(":", 1)[-1].strip()))
                if "model name" in line and not info.model:
                    info.model = line.split(":", 1)[-1].strip()
                if "vendor_id" in line and not info.vendor:
                    info.vendor = line.split(":", 1)[-1].strip()
                if "cpu MHz" in line:
                    try:
                        info.frequency_mhz = float(line.split(":", 1)[-1].strip())
                    except ValueError:
                        pass
                if "cache size" in line and not info.cache_kb:
                    m = re.search(r"(\d+)", line)
                    if m:
                        info.cache_kb = int(m.group(1))
            info.cores = len(physical_cores) if physical_cores else (info.threads or os.cpu_count() or 0)
            if info.threads == 0:
                info.threads = os.cpu_count() or info.cores
            info.temperature_celsius = self._read_temp()
            info.usage_percent = self._calc_usage()
        except (FileNotFoundError, PermissionError):
            pass
        return info

    def _read_temp(self) -> float | None:
        for path in ["/sys/class/thermal/thermal_zone0/temp", "/sys/class/hwmon/hwmon0/temp1_input",
                     "/sys/class/thermal/thermal_zone1/temp"]:
            try:
                with open(path) as f:
                    return int(f.read().strip()) / 1000.0
            except (FileNotFoundError, PermissionError, ValueError, OSError):
                continue
        return None

    def _calc_usage(self) -> float:
        try:
            with open("/proc/stat") as f:
                parts = [int(x) for x in f.readline().strip().split()[1:]]
            if len(parts) < 4:
                return 0.0
            total = sum(parts[:4])
            idle = parts[3]
            now = time.time()
            if self._prev_stat is not None:
                prev_total, prev_idle, prev_time = self._prev_stat
                dt, di = total - prev_total, idle - prev_idle
                self._prev_stat = (total, idle, now)
                return round(100.0 * (1.0 - di / dt), 1) if dt > 0 else 0.0
            self._prev_stat = (total, idle, now)
            return 0.0
        except Exception:
            return 0.0


class _MemoryReader:
    def read(self) -> MemoryInfo:
        mem = MemoryInfo()
        try:
            with open("/proc/meminfo") as f:
                data = f.read()
            for line in data.split("\n"):
                if line.startswith("MemTotal"):
                    mem.total_gb = int(line.split()[1]) / 1024 / 1024
                elif line.startswith("MemAvailable"):
                    mem.available_gb = int(line.split()[1]) / 1024 / 1024
                elif line.startswith("SwapTotal"):
                    mem.swap_total_gb = int(line.split()[1]) / 1024 / 1024
                elif line.startswith("SwapFree"):
                    free = int(line.split()[1]) / 1024 / 1024
                    mem.swap_used_gb = mem.swap_total_gb - free
            mem.used_gb = mem.total_gb - mem.available_gb
            if mem.total_gb > 0:
                mem.usage_percent = round(100.0 * mem.used_gb / mem.total_gb, 1)
        except (FileNotFoundError, PermissionError):
            pass
        return mem


class _DiskReader:
    def read(self) -> list:
        disks = []
        try:
            rows = self._list_mounts()
            seen: set[str] = set()
            for mount, source, fstype in rows:
                if not source.startswith("/dev/"):
                    continue
                dev = source[len("/dev/"):]
                if dev in seen or dev.startswith(("loop", "ram", "zram")):
                    continue
                seen.add(dev)
                try:
                    usage = shutil.disk_usage(mount)
                except (PermissionError, FileNotFoundError, OSError):
                    continue
                disk = DiskInfo(device=dev, mount_point=mount, filesystem=fstype)
                disk.total_gb = round(usage.total / (1024**3), 1)
                disk.used_gb = round(usage.used / (1024**3), 1)
                disk.available_gb = round(usage.free / (1024**3), 1)
                disk.usage_percent = round(100.0 * usage.used / usage.total, 1) if usage.total > 0 else 0.0
                disks.append(disk)
        except Exception:
            pass
        return disks

    def _list_mounts(self) -> list:
        if shutil.which("findmnt"):
            out = subprocess.run(["findmnt", "-rno", "TARGET,SOURCE,FSTYPE"],
                                 capture_output=True, text=True, timeout=10).stdout
            return [line.split(None, 2) for line in out.split("\n") if line.strip()]
        rows = []
        with open("/proc/self/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 3:
                    rows.append((parts[1], parts[0], parts[2]))
        return rows


class _GpuReader:
    def read(self) -> GpuInfo | None:
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10).stdout.strip()
            for line in out.split("\n"):
                if any(x in line.lower() for x in ["vga", "3d", "display"]):
                    rest = line.strip()
                    _, _, rest = rest.partition(":")
                    _, _, desc = rest.partition(":")
                    model = desc.strip() or rest.strip()
                    vendor = ""
                    for name in ("NVIDIA Corporation", "Intel Corporation", "Advanced Micro Devices, Inc.",
                                 "AMD/ATI", "ASPEED Technology"):
                        if model.startswith(name):
                            vendor = name
                            break
                    return GpuInfo(model=model, vendor=vendor)
        except Exception:
            pass
        return None


class _NetworkReader:
    def read(self) -> list:
        nets = []
        try:
            for iface in os.listdir("/sys/class/net"):
                if iface == "lo":
                    continue
                net = NetworkInfo(interface=iface)
                mac_file = f"/sys/class/net/{iface}/address"
                rx_file = f"/sys/class/net/{iface}/statistics/rx_bytes"
                tx_file = f"/sys/class/net/{iface}/statistics/tx_bytes"
                try:
                    with open(mac_file) as f:
                        net.mac_address = f.read().strip()
                except (FileNotFoundError, PermissionError):
                    pass
                try:
                    with open(rx_file) as f:
                        net.rx_bytes = int(f.read().strip())
                    with open(tx_file) as f:
                        net.tx_bytes = int(f.read().strip())
                except (FileNotFoundError, PermissionError, ValueError):
                    pass
                nets.append(net)
        except FileNotFoundError:
            pass
        return nets


class ProcFsAdapter(HardwareDataSource):
    def __init__(self):
        self._cpu = _CpuReader()
        self._mem = _MemoryReader()
        self._disk = _DiskReader()
        self._gpu = _GpuReader()
        self._net = _NetworkReader()

    def get_cpu_info(self) -> CpuInfo: return self._cpu.read()
    def get_memory_info(self) -> MemoryInfo: return self._mem.read()
    def get_disk_info(self) -> list: return self._disk.read()
    def get_gpu_info(self) -> GpuInfo | None: return self._gpu.read()
    def get_network_info(self) -> list: return self._net.read()


class HardwareMonitorService:
    def __init__(self, data_source: HardwareDataSource):
        self._ds = data_source

    def get_cpu_info(self) -> CpuInfo:
        return self._ds.get_cpu_info()

    def get_memory_info(self) -> MemoryInfo:
        return self._ds.get_memory_info()

    def get_disk_info(self) -> list:
        return self._ds.get_disk_info()

    def get_gpu_info(self) -> GpuInfo | None:
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


