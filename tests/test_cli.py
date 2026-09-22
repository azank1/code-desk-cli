import pytest

from coding_desks import cli, launcher
from coding_desks.board import Board


@pytest.fixture
def in_office(office, monkeypatch):
    monkeypatch.chdir(office.root)
    monkeypatch.setenv("NO_COLOR", "1")
    Board.load(office).save()
    return office


def _run(argv):
    cli.main(argv)


def test_deliver_waiting_line_separates_hats(in_office, capsys):
    _run(["deliver", "a", "engineer", "estimate", "--note", "2d"])
    out = capsys.readouterr().out
    assert "waiting on owner scope, priority · engineer risks" in out


def test_deliver_waiting_line_one_hat(in_office, capsys):
    _run(["deliver", "a", "engineer", "estimate"])
    _run(["deliver", "a", "engineer", "risks"])
    out = capsys.readouterr().out.splitlines()[-1]
    assert out == "waiting on owner scope, priority"


def test_codex_command_is_a_short_pointer(office):
    argv = launcher.desk_command(office, office.desks["review"])
    assert argv[0] == "codex" and len(argv) == 2
    assert "review desk" in argv[1] and str(office.root / ".office/roles/review.md") in argv[1]
    assert len(argv[1]) < 300


def test_up_dry_run_prints_plan(in_office, capsys):
    _run(["up", "--dry-run"])
    out = capsys.readouterr().out
    assert "tmux new-session -d -s t -n " in out and "-n pm -c" in out and "-n review -c" in out
    assert "select-window -t t:you" in out
