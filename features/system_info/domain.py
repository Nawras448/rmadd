from dataclasses import dataclass, field


@dataclass
class Distribution:
    id: str = ""
    version: str = ""
    codename: str = ""
    pretty_name: str = ""


@dataclass
class SystemInfo:
    hostname: str = ""
    os: str = ""
    kernel: str = ""
    architecture: str = ""
    hostnamectl_output: str = ""
    uptime: str = ""
    distribution: Distribution = field(default_factory=Distribution)
