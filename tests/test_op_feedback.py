"""M2 Step 2 tests: OpResult surfacing (classify matrix, service synthesis,
BaseAdapter dispatch, sudo-prompt detection, pilot-driven toast/auth UX)."""

import threading
import time

import pytest

from rmadd.models import PackageManager
from rmadd.package_managers.base import (
    BaseAdapter,
    FailureReason,
    OpResult,
)
from rmadd.package_managers.service import PackageManagerService
from rmadd.screens.op_feedback import classify, failure_line, is_auth_prompt

BASE = "rmadd.package_managers.base"
APT = PackageManager.APT
DPKG = PackageManager.DPKG
FLATPAK = PackageManager.FLATPAK


def _res(ok=False, reason=FailureReason.FAILED, tail="", cancelled=False):
    return OpResult(ok, cancelled, reason, tail)


# ------------------------------------------------------------- pure units --

def test_is_auth_prompt_matrix():
    assert is_auth_prompt("[sudo] password for tester:")
    assert is_auth_prompt("Password for root: ")
    assert is_auth_prompt("SUDO PASSWORD REQUIRED")
    assert not is_auth_prompt("Unpacking htop (3.0)")
    assert not is_auth_prompt("")


def test_classify_success_is_silent():
    assert classify("remove", "git", APT, _res(True, FailureReason.NONE), False) == ("", "")


def test_classify_legacy_none_result():
    assert classify("install", "jq", APT, None, True)[0] == "warning"
    assert "cancelled" in classify("install", "jq", APT, None, True)[1]
    assert classify("install", "jq", APT, None, False)[0] == "error"


def test_classify_cancel_paths_are_warnings():
    sev, msg = classify("remove", "git", APT, _res(False, FailureReason.CANCELLED), False)
    assert sev == "warning" and "cancelled" in msg
    # explicit cancel flag overrides an otherwise-FAILED classification
    sev, _ = classify("remove", "git", APT, _res(False), True)
    assert sev == "warning"


def test_classify_auth_reasons_warn():
    for reason in (FailureReason.AUTH_DENIED, FailureReason.AUTH_UNAVAILABLE):
        sev, msg = classify("install", "jq", APT, _res(False, reason), False)
        assert sev == "warning"
        assert "failed:" in msg


def test_classify_timeouts_error():
    for reason in (FailureReason.TIMEOUT, FailureReason.AUTH_TIMEOUT):
        sev, msg = classify("update", "htop", APT, _res(False, reason), False)
        assert sev == "error"
        assert "timed out" in msg


def test_classify_manager_missing_names_binary():
    sev, msg = classify("install", "jq", DPKG, _res(False, FailureReason.MANAGER_MISSING), False)
    assert sev == "error"
    assert "dpkg binary not found" in msg


def test_classify_unsupported_error():
    sev, msg = classify("install", "jq", APT, _res(False, FailureReason.UNSUPPORTED), False)
    assert sev == "error" and "not supported" in msg


def test_classify_failed_includes_remove_hint_and_tail_context():
    long_tail = "line-one\n" * 60  # > TAIL_EXCERPT_CHARS
    sev, msg = classify("remove", "git", APT, _res(False, FailureReason.FAILED, long_tail), False)
    assert sev == "error"
    assert "may still be present" in msg
    excerpt = msg[msg.index("[") + 1 : msg.rindex("]")]
    assert "\n" not in excerpt and len(excerpt) <= 165


def test_failure_line_markup():
    line = failure_line("remove", "git", _res(False, FailureReason.AUTH_DENIED))
    assert line.startswith("[bold red]\u2717 Remove failed (git)")
    assert "authentication denied" in line
    assert failure_line("remove", "git", None).endswith("\u2014 failed[/bold red]")


# ---------------------------------------------------- adapter dispatch --

class _MiniAdapter(BaseAdapter):
    def __init__(self, manager):
        super().__init__(manager)
        self._available = True

    def list_installed(self):
        return []

    def get_info(self, name):
        return None

    def count(self):
        return 0

    def _install_cmd(self, name):
        return ["echo", f"install {name}"]


def test_run_op_unsupported_capability(monkeypatch):
    monkeypatch.setattr(f"{BASE}.os.geteuid", lambda: 0)
    adapter = _MiniAdapter(DPKG)  # dpkg caps: list_installed, remove only
    result = adapter._run_op("install", "jq")
    assert result.ok is False
    assert result.reason is FailureReason.UNSUPPORTED


def test_run_op_supported_routes_to_stream(monkeypatch):
    monkeypatch.setattr(f"{BASE}.os.geteuid", lambda: 0)
    adapter = _MiniAdapter(APT)
    result = adapter._run_op("install", "vim")
    assert result.ok is True and result.reason is FailureReason.NONE
    assert "install vim" in result.tail


# ------------------------------------------------------ service synthesis --

class BoolOnlySource:
    """Pre-_run_op style source: bool returns, no rich context."""

    def __init__(self, ok=True):
        self.ok = ok

    def supports(self, op):
        return True

    def install(self, name, on_output=None, cancel_event=None):
        if on_output is not None:
            on_output("bool source output\n")
        return self.ok

    remove = install
    update = install


def _svc_with(source):
    return PackageManagerService({APT: source})


def test_service_synthesizes_success_from_bool_source():
    svc = _svc_with(BoolOnlySource(True))
    r = svc.install_result("pkg", APT)
    assert isinstance(r, OpResult)
    assert (r.ok, r.cancelled, r.reason) == (True, False, FailureReason.NONE)


def test_service_synthesizes_failed_and_cancelled():
    ev = threading.Event()
    svc = _svc_with(BoolOnlySource(False))
    r = svc.remove_result("pkg", APT, cancel_event=ev)
    assert (r.ok, r.reason) == (False, FailureReason.FAILED)
    ev.set()
    r2 = svc.remove_result("pkg", APT, cancel_event=ev)
    assert (r2.ok, r2.cancelled, r2.reason) == (False, True, FailureReason.CANCELLED)


def test_service_legacy_bool_wrappers_delegate():
    assert _svc_with(BoolOnlySource(True)).remove("p", APT) is True
    assert _svc_with(BoolOnlySource(False)).update("p", APT) is False


# ------------------------------------------------------------ pilot UX ----

pytest.importorskip("textual")

from textual.widgets import Static  # noqa: E402

from rmadd.hardware import HardwareMonitorService  # noqa: E402
from rmadd.models import Package  # noqa: E402
from rmadd.screens.install_progress_screen import InstallProgressScreen  # noqa: E402
from rmadd.system_info import SystemInfoService  # noqa: E402
from rmadd.tui import RmaddTuiApp  # noqa: E402
from tests.test_store_screen_smoke import (  # noqa: E402
    FakeHardwareDS,
    FakeSystemDS,
    _label,
    _wait_until,
)


class SlowAuthFakeSource:
    """Emits a sudo prompt then fails slowly so the modal stays observable."""

    def __init__(self, mgr, names):
        self._mgr = mgr
        self._names = list(names)

    def _pkg(self, n):
        return Package(name=n, manager=self._mgr, version="1.0", summary=f"{n}")

    def list_installed(self):
        return [self._pkg(n) for n in self._names]

    def count(self):
        return len(self._names)

    def search(self, q):
        return []

    def get_info(self, name):
        return self._pkg(name) if name in self._names else None

    def get_status(self, name):
        return None

    def install(self, name, on_output=None, cancel_event=None, **kw):
        return True

    def remove(self, name, on_output=None, cancel_event=None, **kw):
        if on_output is not None:
            on_output("[sudo] password for tester:\n")
        time.sleep(0.8)
        return False

    def update(self, name, on_output=None, cancel_event=None, **kw):
        return True

    def update_all(self, on_output=None, cancel_event=None, **kw):
        return True

    def list_repos(self):
        return []


def _build_app(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    svc = PackageManagerService({
        APT: SlowAuthFakeSource(APT, ["git", "htop"]),
        FLATPAK: SlowAuthFakeSource(FLATPAK, ["spotify"]),
    })
    return RmaddTuiApp(
        SystemInfoService(FakeSystemDS()),
        svc,
        HardwareMonitorService(FakeHardwareDS()),
    )


def test_pilot_surfaces_sudo_prompt_and_failed_reason(tmp_path, monkeypatch):
    import asyncio

    async def scenario():
        app = _build_app(tmp_path, monkeypatch)
        async with app.run_test(size=(120, 40)) as pilot:
            store = app.screen
            assert await _wait_until(lambda: store.installed.loaded)
            toasts: list[tuple[str, str]] = []
            store.notify = lambda *a, **k: toasts.append(
                (k.get("severity", "information"), a[0] if a else k.get("message", ""))
            )

            await pilot.press("f3")
            await pilot.pause(0.2)
            await pilot.press("r")  # remove 'git' -> prompt + failure

            # While the modal lives: auth hint repainted into the title.
            seen_modal = await _wait_until(
                lambda: isinstance(app.screen, InstallProgressScreen)
            )
            assert seen_modal
            modal = app.screen
            assert await _wait_until(lambda: modal._auth_seen)
            assert "awaiting authentication" in _label(
                modal.query_one("#progress-title", Static)
            ).lower()

            # Settle: failure classified, git restored by revert.
            assert await _wait_until(
                lambda: store.ops.state.pending_action("git", APT) is None
                and "git" in {p.name for p in store.ops.state.installed_packages()}
            )
            assert "command failed" in _label(store.result("installed"))
            errors = [m for s, m in toasts if s == "error"]
            assert any("command failed" in m and "git" in m for m in errors)
            assert all("cancelled" not in m.lower() or s != "warning"
                       for s, m in toasts)

    asyncio.run(scenario())
