from features.system_info.ports import GetSystemInfoUseCase, SystemDataSource
from features.system_info.domain import SystemInfo, Distribution


class GetSystemInfoService(GetSystemInfoUseCase):
    def __init__(self, data_source: SystemDataSource):
        self._ds = data_source
        self._cache: SystemInfo | None = None

    def get_system_info(self) -> SystemInfo:
        if self._cache:
            return self._cache
        return self._build()

    def get_distribution(self) -> Distribution:
        return self._ds.get_distribution()

    def refresh(self) -> None:
        self._cache = None

    def _build(self) -> SystemInfo:
        self._cache = SystemInfo(
            hostname=self._ds.get_hostname(),
            os=self._ds.get_os_release(),
            kernel=self._ds.get_kernel(),
            architecture=self._ds.get_architecture(),
            hostnamectl_output=self._ds.get_hostnamectl(),
        )
        return self._cache
