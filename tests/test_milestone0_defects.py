"""Milestone 0 regression tests for defects D1-D5.

D1 update dispatch kwargs     D3 detect_tools purity      D5 binding collisions
D2 Config default isolation   D4 row-key codec
"""

import inspect

import pytest

from rmadd.models import PackageManager

# --------------------------------------------------------------------- D1 --

def test_update_service_accepts_stream_kwargs():
    from rmadd.package_managers.service import PackageManagerService

    kwargs = dict(on_output=lambda s: None, cancel_event=None)
    for action in ("install", "remove", "update"):
        sig = inspect.signature(getattr(PackageManagerService, action))
        sig.bind(None, "pkg", PackageManager.APT, **kwargs)


# --------------------------------------------------------------------- D2 --

def test_config_load_does_not_contaminate_defaults(tmp_path):
    from rmadd.config import DEFAULT_CONFIG, Config

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text('{"ui": {"mode": "cli", "theme": "light"}}')

    first = Config(str(cfg_file))
    second = Config(str(cfg_file))

    assert first.ui_mode == "cli"
    assert DEFAULT_CONFIG["ui"]["mode"] == "tui"
    assert DEFAULT_CONFIG["ui"]["theme"] == "dark"
    first.ui_mode = "tui"
    assert second.ui_mode == "cli"


# --------------------------------------------------------------------- D3 --

def _catalog_snapshot():
    from dataclasses import replace

    from rmadd.tools import INSTALLER_TOOLS

    return [(t.name, t.manager) for t in map(replace, INSTALLER_TOOLS)]


def test_detect_tools_does_not_mutate_catalog(monkeypatch):
    from rmadd.tools import detect_tools

    monkeypatch.setattr("rmadd.tools.resolve_system_manager", lambda: PackageManager.PACMAN)
    before = _catalog_snapshot()
    detect_tools()
    assert _catalog_snapshot() == before


def test_detect_tools_recomputes_fallback_each_call(monkeypatch):
    from rmadd.tools import detect_tools

    monkeypatch.setattr("rmadd.tools.resolve_system_manager", lambda: PackageManager.APT)
    first = {t.name: t.manager for t, _ in detect_tools()}
    monkeypatch.setattr("rmadd.tools.resolve_system_manager", lambda: PackageManager.DNF)
    second = {t.name: t.manager for t, _ in detect_tools()}
    assert first["npm"] == PackageManager.APT
    assert second["npm"] == PackageManager.DNF


# --------------------------------------------------------------------- D4 --

def test_key_roundtrip_simple():
    from rmadd.ui_keys import decode_key, encode_key

    assert decode_key(encode_key("htop", PackageManager.APT)) == ("htop", "apt")


def test_key_roundtrip_adversarial_name_with_pipe():
    from rmadd.ui_keys import decode_key, encode_key

    key = encode_key("my|tool", PackageManager.LOCAL)
    assert decode_key(key) == ("my|tool", "local")


def test_decode_manager_like_name_suffix():
    from rmadd.ui_keys import decode_key, encode_key

    assert decode_key(encode_key("apt|apt", PackageManager.APT)) == ("apt|apt", "apt")


def test_decode_without_separator():
    from rmadd.ui_keys import decode_key

    assert decode_key("system") == ("system", "")
    assert decode_key("") == ("", "")


def test_package_table_uses_codec():
    from rmadd.models import Package
    from rmadd.screens.widgets.package_table import PackageTable
    from rmadd.ui_keys import encode_key

    table = PackageTable()
    wanted = table._wanted_rows([Package(name="my|tool", manager=PackageManager.LOCAL)])
    assert wanted[0][0] == encode_key("my|tool", PackageManager.LOCAL)


# --------------------------------------------------------------------- D5 --

def _binding_keys(bindings) -> set:
    keys = set()
    for b in bindings:
        if isinstance(b, str):
            keys.add(b)
        elif isinstance(b, (tuple, list)):
            keys.add(b[0])
        else:
            keys.add(b.key)
    return keys


def test_app_bindings_not_shadowed_by_screens():
    pytest.importorskip("textual")
    from rmadd.screens.appimage_install_screen import AppImageInstallScreen
    from rmadd.screens.install_progress_screen import InstallProgressScreen
    from rmadd.screens.package_detail_screen import PackageDetailScreen
    from rmadd.screens.store_screen import StoreScreen
    from rmadd.tui import RmaddTuiApp

    app_keys = _binding_keys(RmaddTuiApp.BINDINGS)
    for screen in (StoreScreen, InstallProgressScreen, PackageDetailScreen,
                   AppImageInstallScreen):
        overlap = app_keys & _binding_keys(screen.BINDINGS)
        assert not overlap, f"{screen.__name__} shadows app keys: {overlap}"


def test_refresh_rebound_to_uppercase_r():
    pytest.importorskip("textual")
    from rmadd.tui import RmaddTuiApp

    assert "R" in _binding_keys(RmaddTuiApp.BINDINGS)
    assert "r" not in _binding_keys(RmaddTuiApp.BINDINGS)
