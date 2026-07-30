from dataclasses import dataclass


@dataclass
class SystemInfo:
    hostname: str = ""
    os: str = ""
    kernel: str = ""
    architecture: str = ""
    hostnamectl_output: str = ""
    uptime: str = ""


@dataclass
class Distribution:
    id: str = ""
    version: str = ""
    codename: str = ""
    pretty_name: str = ""
