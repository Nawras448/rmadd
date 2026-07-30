import subprocess

from features.system_info.ports import SystemDataSource
from features.system_info.domain import Distribution


class HostnamectlAdapter(SystemDataSource):
    def get_hostname(self) -> str:
        try:
            return subprocess.run(["hostname"], capture_output=True, text=True).stdout.strip()
        except Exception:
            return "Unknown"

    def get_os_release(self) -> str:
        try:
            out = subprocess.run(["lsb_release", "-d"], capture_output=True, text=True).stdout.strip()
            return out.split(":", 1)[-1].strip() if ":" in out else out
        except Exception:
            return "Unknown"

    def get_kernel(self) -> str:
        try:
            return subprocess.run(["uname", "-r"], capture_output=True, text=True).stdout.strip()
        except Exception:
            return "Unknown"

    def get_architecture(self) -> str:
        try:
            return subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip()
        except Exception:
            return "Unknown"

    def get_hostnamectl(self) -> str:
        try:
            return subprocess.run(["hostnamectl"], capture_output=True, text=True).stdout.strip()
        except Exception:
            return ""

    def get_distribution(self) -> Distribution:
        d = Distribution()
        try:
            out = subprocess.run(["lsb_release", "-a"], capture_output=True, text=True).stdout
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
        try:
            return subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
        except Exception:
            return "Unknown"

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
