import shutil
import subprocess

from features.package_store.registry import discover_managers


class SystemInfo:

    def get_package_count(self, manager_name: str) -> str:
        """Count packages via the shared adapter for the given manager."""
        for mgr, adapter in discover_managers():
            if mgr.value == manager_name:
                try:
                    return str(adapter.count())
                except Exception:
                    return "0"
        return "N/A"

    def get_all_counts(self) -> dict:
        """Fetch the package counts of all available managers (tier ordered)"""
        counts = {}
        for mgr, adapter in discover_managers():
            try:
                count = adapter.count()
            except Exception:
                continue
            if count and count > 0:
                counts[mgr.value] = str(count)
        return counts

    def get_system_info(self) -> dict:
        """Fetch basic system information"""
        try:
            hostname = subprocess.run(
                "hostname", shell=True, capture_output=True, text=True, check=True
            ).stdout.strip()
        except Exception:
            hostname = "Unknown"

        try:
            os_info = subprocess.run(
                "lsb_release -d", shell=True, capture_output=True, text=True, check=True
            ).stdout.strip().split(":")[1].strip()
        except Exception:
            os_info = "Unknown"

        try:
            hostnamectl = subprocess.run(
                "hostnamectl", shell=True, capture_output=True, text=True, check=True
                ).stdout.strip()
        except Exception:
            hostnamectl = "Unknown"

        return {"hostname": hostname, "os": os_info, "hostnamectl": hostnamectl}