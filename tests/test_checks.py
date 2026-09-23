import copy

import pytest
import yaml

from coding_desks import cli
from coding_desks.board import Board, BoardError
from coding_desks.manifest import ManifestError, parse

from .conftest import MANIFEST

# A stand-in verifier: accepts a file whose first line is "sealed", refuses anything else.
VERIFY = 'head -n1 {evidence} | grep -qx sealed || { echo "not sealed: $DESK_EVIDENCE"; exit 3; }'


@pytest.fixture
def checked(tmp_path):
    m = copy.deepcopy(MANIFEST)
    m["gates"]["shipped"]["engineer"] = ["read-back", "receipt"]
    m["gates"]["shipped"]["checks"] = {"receipt": VERIFY}
    (tmp_path / "src").mkdir()
    (tmp_path / ".office" / "roles").mkdir(parents=True)
    (tmp_path / "office.yaml").write_text(yaml.safe_dump(m))
    office = parse(m, tmp_path)
    b = Board.load(office)
    # walk thread `a` to `shipped`
    for hat, item in [
        ("engineer", "estimate"),
        ("engineer", "risks"),
        ("owner", "scope"),
        ("owner", "priority"),
        ("engineer", "tests-green"),
        ("engineer", "evidence"),
        ("owner", "verdict"),
    ]:
        b.deliver("a", hat, item)
    assert b.row("a").gate == "shipped"
    b.save()
    return office


def _receipt(office, name="r.json", first="sealed"):
    p = office.root / name
    p.write_text(first + "\n{}\n")
    return name


def test_manifest_rejects_check_on_unknown_item():
    m = copy.deepcopy(MANIFEST)
    m["gates"]["shipped"]["checks"] = {"nope": "true"}
    with pytest.raises(ManifestError, match="not an item of this gate"):
        parse(m, None)


def test_manifest_rejects_empty_command():
    m = copy.deepcopy(MANIFEST)
    m["gates"]["shipped"]["checks"] = {"read-back": "  "}
    with pytest.raises(ManifestError, match="command string"):
        parse(m, None)


def test_checked_item_needs_evidence(checked):
    b = Board.load(checked)
    with pytest.raises(BoardError, match="pass --evidence"):
        b.deliver("a", "engineer", "receipt")


def test_failing_check_refuses_and_writes_nothing(checked):
    b = Board.load(checked)
    bad = _receipt(checked, "bad.json", first="tampered")
    with pytest.raises(BoardError, match=r"check refused .*exit 3") as e:
        b.deliver("a", "engineer", "receipt", evidence=bad)
    assert "not sealed: bad.json" in str(e.value)
    assert "receipt" not in b.threads["a"].filed("shipped", "engineer")


def test_missing_evidence_file_is_refused_by_the_check(checked):
    b = Board.load(checked)
    with pytest.raises(BoardError, match="check refused"):
        b.deliver("a", "engineer", "receipt", evidence="nowhere.json")


def test_passing_check_records_command_and_digest(checked):
    b = Board.load(checked)
    ev = _receipt(checked)
    b.deliver("a", "engineer", "receipt", evidence=ev)
    d = b.threads["a"].filed("shipped", "engineer")["receipt"]
    assert d.check == VERIFY and d.digest.startswith("sha256:") and len(d.digest) == 71
    b.save()
    again = Board.load(checked).threads["a"].filed("shipped", "engineer")["receipt"]
    assert again.digest == d.digest and again.check == VERIFY


def test_evidence_is_shell_quoted(checked):
    b = Board.load(checked)
    ev = _receipt(checked, "a b; touch pwned.json")
    b.deliver("a", "engineer", "receipt", evidence=ev)
    assert not (checked.root / "pwned.json").exists()


def test_unchecked_items_behave_as_before(checked):
    b = Board.load(checked)
    b.deliver("a", "engineer", "read-back")
    d = b.threads["a"].filed("shipped", "engineer")["read-back"]
    assert d.check is None and d.digest is None


def test_recheck_holds_then_catches_a_flipped_byte(checked):
    b = Board.load(checked)
    ev = _receipt(checked)
    b.deliver("a", "engineer", "receipt", evidence=ev)
    [r] = b.recheck()
    assert r.ok and r.item == "receipt"
    (checked.root / ev).write_text("sealed\n{ }\n")  # same verdict from the command, different bytes
    [r] = b.recheck("a")
    assert not r.ok and r.problem == "evidence changed since it was accepted"
    (checked.root / ev).unlink()
    [r] = b.recheck("a")
    assert r.problem == "evidence file is gone"


def test_recheck_catches_a_check_that_now_fails(checked):
    checked.gates["shipped"].checks["receipt"] = "test -f marker"
    (checked.root / "marker").write_text("")
    b = Board.load(checked)
    b.deliver("a", "engineer", "receipt", evidence="v1.2.3")  # not a file: no digest to compare
    assert b.threads["a"].filed("shipped", "engineer")["receipt"].digest is None
    (checked.root / "marker").unlink()
    [r] = b.recheck()
    assert r.problem == "check now fails (exit 1)"


def test_recheck_never_runs_a_command_only_the_board_names(checked):
    b = Board.load(checked)
    ev = _receipt(checked)
    b.deliver("a", "engineer", "receipt", evidence=ev)
    b.threads["a"].filed("shipped", "engineer")["receipt"].check = "touch pwned"  # someone edits board.yaml
    [r] = b.recheck()
    assert r.problem == "check changed since it was accepted" and "touch pwned" in r.output
    assert not (checked.root / "pwned").exists()


def test_recheck_flags_a_check_removed_from_office_yaml(checked):
    b = Board.load(checked)
    b.deliver("a", "engineer", "receipt", evidence=_receipt(checked))
    del checked.gates["shipped"].checks["receipt"]
    [r] = b.recheck()
    assert r.problem == "office.yaml no longer checks this item"


@pytest.fixture
def in_checked(checked, monkeypatch):
    monkeypatch.chdir(checked.root)
    monkeypatch.setenv("NO_COLOR", "1")
    return checked


def test_cli_deliver_and_verify(in_checked, capsys):
    ev = _receipt(in_checked)
    cli.main(["deliver", "a", "engineer", "receipt", "--evidence", ev])
    out = capsys.readouterr().out
    assert "check passed" in out and "sha256:" in out
    cli.main(["verify"])
    out = capsys.readouterr().out
    assert "1/1 links hold" in out and "holds" in out
    (in_checked.root / ev).write_text("sealed\nchanged\n")
    with pytest.raises(SystemExit) as e:
        cli.main(["verify", "a"])
    assert e.value.code == 1
    assert "evidence changed since it was accepted" in capsys.readouterr().out


def test_cli_deliver_refusal_exits_1(in_checked, capsys):
    ev = _receipt(in_checked, "bad.json", first="nope")
    with pytest.raises(SystemExit) as e:
        cli.main(["deliver", "a", "engineer", "receipt", "--evidence", ev])
    assert e.value.code == 1
    assert "check refused" in capsys.readouterr().err


def test_one_file_backs_one_link(checked):
    b = Board.load(checked)
    ev = _receipt(checked)
    b.deliver("a", "engineer", "receipt", evidence=ev)
    for hat, item in [("engineer", "estimate"), ("engineer", "risks"), ("owner", "scope"), ("owner", "priority")]:
        b.deliver("b", hat, item)
    for hat, item in [("engineer", "tests-green"), ("engineer", "evidence"), ("owner", "verdict")]:
        b.deliver("b", hat, item)
    _receipt(checked, "copy.json")  # byte-identical to r.json
    with pytest.raises(BoardError, match=r"already accepted at a shipped:engineer:receipt"):
        b.deliver("b", "engineer", "receipt", evidence="copy.json")
