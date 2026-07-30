from typing import Optional

from features.package_store.domain import PackageManager
from features.package_store.ports import GetPackagesUseCase, InstallPackageUseCase, PackageDataSource
from features.package_store.service import PackageManagerService
from features.system_info.ports import GetSystemInfoUseCase, SystemDataSource
from features.system_info.service import GetSystemInfoService
from features.system_monitor.ports import MonitorHardwareUseCase, HardwareDataSource
from features.system_monitor.service import HardwareMonitorService


class DIContainer:
    def __init__(self):
        self._system_source: Optional[SystemDataSource] = None
        self._hardware_source: Optional[HardwareDataSource] = None
        self._package_sources: dict[PackageManager, PackageDataSource] = {}
        self._system_service: Optional[GetSystemInfoUseCase] = None
        self._package_service: Optional[PackageManagerService] = None
        self._hardware_service: Optional[MonitorHardwareUseCase] = None

    def set_system_source(self, source: SystemDataSource) -> "DIContainer":
        self._system_source = source
        self._system_service = None
        return self

    def set_hardware_source(self, source: HardwareDataSource) -> "DIContainer":
        self._hardware_source = source
        self._hardware_service = None
        return self

    def add_package_source(self, manager: PackageManager, source: PackageDataSource) -> "DIContainer":
        self._package_sources[manager] = source
        self._package_service = None
        return self

    def get_system_service(self) -> GetSystemInfoUseCase:
        if self._system_service is None:
            assert self._system_source is not None
            self._system_service = GetSystemInfoService(self._system_source)
        return self._system_service

    def get_package_service(self) -> PackageManagerService:
        if self._package_service is None:
            assert self._package_sources
            self._package_service = PackageManagerService(self._package_sources)
        return self._package_service

    def get_hardware_service(self) -> MonitorHardwareUseCase:
        if self._hardware_service is None:
            assert self._hardware_source is not None
            self._hardware_service = HardwareMonitorService(self._hardware_source)
        return self._hardware_service
