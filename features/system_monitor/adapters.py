import os
import re
import time
import shutil
import subprocess
from typing import Optional

from features.system_monitor.ports import HardwareDataSource
from features.system_monitor.domain import CpuInfo, MemoryInfo, DiskInfo, GpuInfo, NetworkInfo


class _CpuReader:
    def __init__(self):
        self._prev_stat: Optional[tuple] = None

    def read(self) -> CpuInfo:
        info = CpuInfo()
        try:
            with open("/proc/cpuinfo") as f:
                data = f.read()
            for line in data.split("\n"):
                if line.startswith("processor"):
                    info.cores += 1
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
            info.threads = os.cpu_count() or info.cores
            info.temperature_celsius = self._read_temp()
            info.usage_percent = self._calc_usage()
        except (FileNotFoundError, PermissionError):
            pass
        return info

    def _read_temp(self) -> Optional[float]:
        for path in ["/sys/class/thermal/thermal_zone0/temp", "/sys/class/hwmon/hwmon0/temp1_input",
                     "/sys/class/thermal/thermal_zone1/temp"]:
            try:
                return int(open(path).read().strip()) / 1000.0
            except (FileNotFoundError, PermissionError, ValueError):
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
            raw_disks = self._list_devices()
            for dev in raw_disks:
                disk = self._enrich(dev)
                if disk:
                    disks.append(disk)
        except Exception:
            pass
        return disks

    def _list_devices(self) -> list:
        if shutil.which("lsblk"):
            out = subprocess.run(["lsblk", "-ndo", "NAME,SIZE,MOUNTPOINT,FSTYPE", "-e", "7,1"],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            return [line.split() for line in out.split("\n") if line]
        with open("/proc/partitions") as f:
            return [[parts[3]] for line in f.readlines()[2:] if (parts := line.split()) and len(parts) >= 4 and not parts[3].isdigit()]

    def _enrich(self, parts: list) -> Optional[DiskInfo]:
        dev = parts[0]
        disk = DiskInfo(device=dev)
        try:
            usage = shutil.disk_usage(dev if dev.startswith("/") else f"/dev/{dev}")
            disk.mount_point = parts[2] if len(parts) > 2 and parts[2] else ""
        except (PermissionError, FileNotFoundError, OSError):
            for mount in ["/", "/home", "/var"]:
                try:
                    usage = shutil.disk_usage(mount)
                    disk.mount_point = mount
                    break
                except (PermissionError, FileNotFoundError, OSError):
                    continue
            else:
                return None
        disk.total_gb = round(usage.total / (1024**3), 1)
        disk.used_gb = round(usage.used / (1024**3), 1)
        disk.available_gb = round(usage.free / (1024**3), 1)
        disk.usage_percent = round(100.0 * usage.used / usage.total, 1) if usage.total > 0 else 0.0
        disk.filesystem = parts[3] if len(parts) > 3 else ""
        return disk


class _GpuReader:
    def read(self) -> Optional[GpuInfo]:
        try:
            out = subprocess.run(["lspci"], capture_output=True, text=True, timeout=10).stdout.strip()
            for line in out.split("\n"):
                if any(x in line.lower() for x in ["vga", "3d", "display"]):
                    parts = line.strip().split(":", 2)
                    return GpuInfo(model=parts[-1].strip() if len(parts) >= 3 else line.strip(),
                                   vendor=parts[0].strip())
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
                    net.mac_address = open(mac_file).read().strip()
                except Exception:
                    pass
                try:
                    net.rx_bytes = int(open(rx_file).read().strip())
                    net.tx_bytes = int(open(tx_file).read().strip())
                except Exception:
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
    def get_gpu_info(self) -> Optional[GpuInfo]: return self._gpu.read()
    def get_network_info(self) -> list: return self._net.read()
