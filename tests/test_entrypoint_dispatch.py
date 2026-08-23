"""Dispatch tests: bare invocation launches the TUI; args route to the CLI."""

import pytest

from rmadd.cli import CliApp
from rmadd.main import main


class FakeTui:
    instances = []

    def __init__(self, *services):
        self.services = services
        self.ran = False
        FakeTui.instances.append(self)

    def run(self):
        self.ran = True


class RecordingCli(CliApp):
    """Real argparse behavior, recording construction/invocation."""

    instances = []
    run_args = None

    def __init__(self, *services):
        super().__init__(*services)
        RecordingCli.instances.append(self)

    def run(self, args):
        RecordingCli.run_args = list(args)
        super().run(args)


@pytest.fixture()
def fakes(monkeypatch):
    FakeTui.instances = []
    RecordingCli.instances = []
    RecordingCli.run_args = None
    monkeypatch.setattr("rmadd.tui.RmaddTuiApp", FakeTui)
    monkeypatch.setattr("rmadd.cli.CliApp", RecordingCli)
    return FakeTui, RecordingCli


def test_no_args_launches_tui(fakes):
    tui, cli = fakes
    main([])
    assert len(tui.instances) == 1
    assert tui.instances[0].ran is True
    assert cli.instances == []


def test_subcommand_routes_to_cli(fakes, capsys):
    tui, cli = fakes
    main(["info"])
    assert tui.instances == []
    assert len(cli.instances) == 1
    assert cli.run_args == ["info"]
    assert "Hostname" in capsys.readouterr().out


def test_help_flag_prints_usage_and_exits_zero(fakes, capsys):
    tui, _cli = fakes
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "usage:" in out
    for sub in ("info", "packages", "hardware"):
        assert sub in out
    assert tui.instances == []


def test_unknown_command_exits_two(fakes):
    with pytest.raises(SystemExit) as exc:
        main(["definitely-not-a-command"])
    assert exc.value.code == 2
