import argparse


class CliApp:
    def __init__(self, container):
        self._container = container
        self.system_service = container.get_system_service()
        self.package_service = container.get_package_service()
        self.hardware_service = container.get_hardware_service()

    def run(self, args: list[str] | None = None):
        parser = argparse.ArgumentParser(prog="rmadd")
        sub = parser.add_subparsers(dest="command")

        sub.add_parser("info", help="Show system info")
        sub.add_parser("packages", help="List package counts")
        sub.add_parser("hardware", help="Show hardware info")

        parsed = parser.parse_args(args)

        if parsed.command == "info":
            info = self.system_service.get_system_info()
            print(f"Hostname: {info.hostname}")
            print(f"OS: {info.os}")
            print(f"Kernel: {info.kernel}")
            print(f"Arch: {info.architecture}")

        elif parsed.command == "packages":
            counts = self.package_service.get_all_counts()
            for mgr, count in counts.items():
                print(f"{mgr}: {count}")

        elif parsed.command == "hardware":
            cpu = self.hardware_service.get_cpu_info()
            mem = self.hardware_service.get_memory_info()
            print(f"CPU: {cpu.model} ({cpu.cores}c/{cpu.threads}t)")
            print(f"RAM: {mem.used_gb:.1f}/{mem.total_gb:.1f} GB ({mem.usage_percent}%)")
