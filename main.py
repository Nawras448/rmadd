import sys
import os

from features.package_store.registry import discover_managers
from features.system_info.adapters import HostnamectlAdapter
from features.system_monitor.adapters import ProcFsAdapter
from shared.cache import CachingSystemAdapter, CachingHardwareAdapter
from shared.di_container import DIContainer
from shared.config import Config
from shared.logging import setup_logging, get_logger


def build_container() -> DIContainer:
    container = DIContainer()

    system_source = CachingSystemAdapter(HostnamectlAdapter(), ttl_seconds=60)
    container.set_system_source(system_source)

    hardware_source = CachingHardwareAdapter(ProcFsAdapter(), ttl_seconds=3)
    container.set_hardware_source(hardware_source)

    for manager, adapter in discover_managers():
        container.add_package_source(manager, adapter)

    return container


def main():
    setup_logging()
    logger = get_logger("main")
    logger.info("Starting rmadd")

    config = Config()
    container = build_container()

    ui_mode = config.ui_mode

    if ui_mode == "tui":
        from features.ui_switch.presentation.tui.app import RmaddTuiApp
        app = RmaddTuiApp(container)
        app.run()

    elif ui_mode == "gui":
        from features.ui_switch.presentation.gui.app import RmaddGuiApp
        app = RmaddGuiApp(container)
        app.run()

    elif ui_mode == "cli":
        from features.ui_switch.presentation.cli.commands import CliApp
        app = CliApp(container)
        app.run(sys.argv[1:])

    else:
        logger.error(f"Unknown UI mode: {ui_mode}")
        sys.exit(1)


if __name__ == "__main__":
    main()
