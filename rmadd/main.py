"""Application bootstrap: builds services and dispatches TUI/CLI by argv."""

import sys

from rmadd.cache import CachingHardwareAdapter, CachingSystemAdapter
from rmadd.hardware import HardwareMonitorService, ProcFsAdapter
from rmadd.logging import get_logger, setup_logging
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


def main(argv: list[str] | None = None) -> None:
    """Dispatch on argument presence: bare invocation launches the TUI.

    ``argv`` defaults to ``sys.argv[1:]`` and is injectable for tests.
    Any arguments (subcommands or flags such as ``--help``) are handed to
    the CLI parser.
    """
    args = list(sys.argv[1:] if argv is None else argv)

    setup_logging()
    get_logger("main").info("Starting rmadd")

    system_service, package_service, hardware_service = build_app()

    if args:
        from rmadd.cli import CliApp

        cli = CliApp(system_service, package_service, hardware_service)
        cli.run(args)
        return

    from rmadd.tui import RmaddTuiApp

    app = RmaddTuiApp(system_service, package_service, hardware_service)
    app.run()


if __name__ == "__main__":
    main()
