"""Row-key codec shared by package/tool tables and screens.

Row identity is encoded as ``"<name>|<manager>"``. Manager values come from
the PackageManager enum and never contain ``"|"``, while package/binary
names may (e.g. executables scanned by the LOCAL binary scanner). Decoding
therefore splits on the LAST separator.
"""

from rmadd.models import PackageManager


def encode_key(name: str, manager: PackageManager) -> str:
    return f"{name}|{manager.value}"


def decode_key(key: str) -> tuple[str, str]:
    """Inverse of :func:`encode_key`; returns ``(name, manager_value)``."""
    if "|" not in key:
        return (key, "")
    name, _, manager = key.rpartition("|")
    return (name, manager)
