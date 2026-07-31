from abc import ABC, abstractmethod

from features.system_info.domain import SystemInfo, Distribution


class GetSystemInfoUseCase(ABC):
    @abstractmethod
    def get_system_info(self) -> SystemInfo:
        pass

    @abstractmethod
    def get_distribution(self) -> Distribution:
        pass

    @abstractmethod
    def refresh(self) -> None:
        pass


class SystemDataSource(ABC):
    @abstractmethod
    def get_hostname(self) -> str:
        pass

    @abstractmethod
    def get_os_release(self) -> str:
        pass

    @abstractmethod
    def get_kernel(self) -> str:
        pass

    @abstractmethod
    def get_architecture(self) -> str:
        pass

    @abstractmethod
    def get_hostnamectl(self) -> str:
        pass

    @abstractmethod
    def get_uptime(self) -> str:
        pass

    @abstractmethod
    def get_distribution(self) -> Distribution:
        pass
