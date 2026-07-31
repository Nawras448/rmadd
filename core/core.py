import shutil
import subprocess


class SystemInfo:

    # قاموس يعرّف مديري الحزم والأوامر الخاصة بهم
    PACKAGE_MANAGERS = {
        "apt": "dpkg-query -f '${binary:Package}\n' -W | wc -l",
        "snap": "snap list | tail -n +2 | wc -l",
        "flatpak": "flatpak list --app | wc -l",
        "pacman": "pacman -Qq | wc -l",
        "dnf": "rpm -qa | wc -l",
    }

    def get_package_count(self, manager_name: str) -> str:
        """تحقق من وجود مدير الحزم وتنفيذ أمره"""
        if not shutil.which(manager_name):
            return "N/A"

        try:
            cmd = self.PACKAGE_MANAGERS.get(manager_name)
            if not cmd:
                return "N/A"

            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, check=True
            )
            return result.stdout.strip()
        except Exception:
            return "0"

    def get_all_counts(self) -> dict:
        """جلب أعداد كل الحزم المتاحة في النظام"""
        counts = {}
        for pm in self.PACKAGE_MANAGERS:
            count = self.get_package_count(pm)
            if count != "N/A":
                counts[pm] = count
        return counts

    def get_system_info(self) -> dict:
        """جلب معلومات النظام الأساسية"""
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