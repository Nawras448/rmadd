"""Application bootstrap: builds services and dispatches TUI/CLI."""

import sys

from rmadd.cache import CachingSystemAdapter, CachingHardwareAdapter
from rmadd.config import Config
from rmadd.hardware import ProcFsAdapter, HardwareMonitorService
from rmadd.logging import setup_logging, get_logger
from rmadd.package_managers.base import discover_managers
from rmadd.package_managers.service import PackageManagerService
from rmadd.system_info import HostnamectlAdapter, SystemInfoService


def build_app():
    system_source = CachingSystemAdapter(HostnamectlAdapter(), ttl_seconds=60)
    system_service = SystemInfoService(system_source)

    hardware_source = CachingHardwareAdapter(ProcFsAdapter(), ttl_seconds=3)
    hardware_service = HardwareMonitorService(hardware_source)

    package_service = PackageManagerService(dict(discover_managers()))

    return system_service, package_service, hardware_service


def main():
    setup_logging()
    logger = get_logger("main")
    logger.info("Starting rmadd")

    config = Config()
    system_service, package_service, hardware_service = build_app()

    ui_mode = config.ui_mode

    if ui_mode == "tui":
        from rmadd.tui import RmaddTuiApp
        app = RmaddTuiApp(system_service, package_service, hardware_service)
        app.run()

    elif ui_mode == "cli":
        from rmadd.cli import CliApp
        app = CliApp(system_service, package_service, hardware_service)
        app.run(sys.argv[1:])

    else:
        logger.warning(f"GUI mode is not implemented; falling back to TUI (got ui_mode={ui_mode!r})")
        from rmadd.tui import RmaddTuiApp
        app = RmaddTuiApp(system_service, package_service, hardware_service)
        app.run()


if __name__ == "__main__":
    main()
