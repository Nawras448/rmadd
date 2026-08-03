import subprocess

from features.system_info.ports import SystemDataSource
from features.system_info.domain import Distribution

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


class LsbReleaseAdapter(SystemDataSource):
    def _run(self, cmd: list) -> str:
        return _run_cmd(cmd)

    def get_hostname(self) -> str:
        return self._run(["hostname"])

    def get_os_release(self) -> str:
        out = self._run(["lsb_release", "-d"])
        return out.split(":", 1)[-1].strip() if ":" in out else out

    def get_kernel(self) -> str:
        return self._run(["uname", "-r"])

    def get_architecture(self) -> str:
        return self._run(["uname", "-m"])

    def get_hostnamectl(self) -> str:
        return self._run(["hostnamectl"])

    def get_uptime(self) -> str:
        return _read_uptime()

    def get_distribution(self) -> Distribution:
        d = Distribution()
        for line in self._run(["lsb_release", "-a"]).split("\n"):
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if k == "Distributor ID":
                d.id = v
            elif k == "Release":
                d.version = v
            elif k == "Codename":
                d.codename = v
            elif k == "Description":
                d.pretty_name = v
        return d
