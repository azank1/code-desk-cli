import io
import json

import pytest

from coding_desks import cli, hooks, mail


@pytest.fixture
def in_office(office, monkeypatch):
    monkeypatch.chdir(office.root)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("DESK", raising=False)
    return office


def test_send_unread_render_mark_read(office):
    p = mail.send(office, "dev", "  take auth-flow, scope is filed  ", sender="pm", thread="a")
    assert p.parent == office.state_dir / "mail" / "dev" and p.suffix == ".md"
    (m,) = mail.unread(office, "dev")
    assert (m.sender, m.to, m.thread, m.body) == ("pm", "dev", "a", "take auth-flow, scope is filed")
    text = mail.render("dev", [m])
    assert "1 message(s) for desk dev" in text and "from pm at" in text and "thread a" in text
    mail.mark_read([m])
    assert mail.unread(office, "dev") == [] and (p.parent / "read" / p.name).is_file()
    assert (office.state_dir / ".gitignore").read_text().splitlines()[1:] == ["mail/", "launches.yaml"]


def test_send_validates(office):
    with pytest.raises(mail.MailError, match="no desk named"):
        mail.send(office, "ceo", "x", sender="pm")
    with pytest.raises(mail.MailError, match="no thread named"):
        mail.send(office, "dev", "x", sender="pm", thread="nope")
    with pytest.raises(mail.MailError, match="empty"):
        mail.send(office, "dev", "   ", sender="pm")


def test_hook_output_shapes():
    c = json.loads(mail.hook_output("claude", "ctx"))
    assert c["hookSpecificOutput"] == {"hookEventName": "UserPromptSubmit", "additionalContext": "ctx"}
    assert mail.hook_output("claude", None) == "{}"
    u = json.loads(mail.hook_output("cursor", "ctx"))
    assert u == {"continue": True, "additional_context": "ctx"}
    assert json.loads(mail.hook_output("cursor", None)) == {"continue": True}
    with pytest.raises(mail.MailError):
        mail.hook_output("codex", "x")


def test_hook_command_delivers_once_for_the_desk_in_env(in_office, monkeypatch, capsys):
    mail.send(in_office, "dev", "hello dev", sender="pm")
    mail.send(in_office, "pm", "not for dev", sender="dev")
    monkeypatch.setenv("DESK", "dev")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"hook_event_name":"UserPromptSubmit","prompt":"hi"}'))
    cli.main(["hook", "claude"])
    out = json.loads(capsys.readouterr().out)
    assert "hello dev" in out["hookSpecificOutput"]["additionalContext"]
    assert "not for dev" not in out["hookSpecificOutput"]["additionalContext"]
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    cli.main(["hook", "claude"])
    assert capsys.readouterr().out.strip() == "{}"  # delivered once


def test_hook_renders_only_what_it_moved_when_another_session_took_a_message(in_office, monkeypatch, capsys):
    mail.send(in_office, "dev", "taken by the other session", sender="pm")
    mail.send(in_office, "dev", "still here", sender="pm")
    msgs = mail.unread(in_office, "dev")
    taken = next(m for m in msgs if m.body.startswith("taken"))  # same second, so the order is by file name
    taken.path.unlink()  # the other hook moved it between our listing and our move
    monkeypatch.setattr(mail, "unread", lambda office, desk: msgs)
    monkeypatch.setenv("DESK", "dev")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    cli.main(["hook", "claude"])
    ctx = json.loads(capsys.readouterr().out)["hookSpecificOutput"]["additionalContext"]
    assert "still here" in ctx and "taken by" not in ctx and "1 message(s)" in ctx


def test_hook_command_never_fails_outside_an_office(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DESK", "dev")
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    cli.main(["hook", "cursor"])
    assert json.loads(capsys.readouterr().out) == {"continue": True}


def test_mail_cli_table_and_read(in_office, capsys):
    cli.main(["send", "dev", "one", "--from", "pm"])
    cli.main(["send", "dev", "two", "--from", "pm", "--thread", "a"])
    out = capsys.readouterr().out
    assert "sent to dev as pm" in out
    cli.main(["mail"])
    out = capsys.readouterr().out
    assert "dev" in out and "2" in out
    cli.main(["mail", "--desk", "dev", "read"])
    out = capsys.readouterr().out
    assert "one" in out and "two" in out and "2 marked read" in out
    cli.main(["mail", "--desk", "dev"])
    assert "no unread mail" in capsys.readouterr().out


def test_hooks_merge_is_idempotent_and_keeps_existing():
    s = {
        "permissions": {"allow": ["Bash(ls)"]},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "beep"}]}]},
    }
    s2, changed = hooks.merge_claude(s)
    assert changed and s2["permissions"] == {"allow": ["Bash(ls)"]} and "Stop" in s2["hooks"]
    ((entry,),) = [g["hooks"] for g in s2["hooks"]["UserPromptSubmit"]]
    assert entry["type"] == "command" and hooks.is_ours(entry["command"], "claude")
    assert entry["command"].split()[0].endswith("desk") and entry["command"].endswith(" hook claude")
    assert entry["command"].startswith("/"), "the harness's PATH is not ours: install by absolute path"
    _, changed = hooks.merge_claude(s2)
    assert not changed
    c = {"version": 1, "hooks": {"stop": [{"command": "./hooks/ping.sh"}]}}
    c2, changed = hooks.merge_cursor(c)
    assert changed and c2["hooks"]["stop"] == [{"command": "./hooks/ping.sh"}]
    (e,) = c2["hooks"]["beforeSubmitPrompt"]
    assert hooks.is_ours(e["command"], "cursor")
    assert hooks.merge_cursor(c2)[1] is False
    # an entry installed by an older release (bare name) still counts as ours
    legacy = {"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "desk hook claude"}]}]}}
    assert hooks.merge_claude(legacy)[1] is False
    assert not hooks.is_ours("desk hook cursor", "claude") and not hooks.is_ours("/bin/echo hook claude", "claude")


def test_hooks_install_writes_only_project_files(in_office, capsys):
    cli.main(["hooks"])
    out = capsys.readouterr().out
    assert ".claude/settings.json" in out and "would change" in out
    assert ".cursor/hooks.json" not in out  # no cursor desk in the fixture
    cli.main(["hooks", "--install"])
    assert "wrote .claude/settings.json" in capsys.readouterr().out
    data = json.loads((in_office.root / ".claude" / "settings.json").read_text())
    assert hooks.is_ours(data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"], "claude")
    cli.main(["hooks", "--install"])
    assert "already there" in capsys.readouterr().out


def test_hooks_check_runs_the_installed_hook_with_a_bare_path(in_office, capsys):
    with pytest.raises(SystemExit):
        cli.main(["hooks", "--check"])  # nothing installed yet
    cli.main(["hooks", "--install"])
    capsys.readouterr()
    cli.main(["hooks", "--check"])
    out = capsys.readouterr().out
    assert "ok" in out and ".claude/settings.json" in out and "exit 0: {}" in out
    # a hook the harness cannot find fails the check instead of failing silently at every turn
    p = in_office.root / ".claude" / "settings.json"
    data = json.loads(p.read_text())
    data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] = "/nowhere/desk hook claude"
    p.write_text(json.dumps(data))
    with pytest.raises(SystemExit) as e:
        cli.main(["hooks", "--check"])
    assert e.value.code == 1 and "FAILS" in capsys.readouterr().out


def test_up_dry_run_sets_desk_env(in_office, capsys):
    cli.main(["up", "--dry-run"])
    out = capsys.readouterr().out
    assert f"env DESK=pm DESK_OFFICE={in_office.root} claude --name pm" in out
    assert f"env DESK=review DESK_OFFICE={in_office.root} codex " in out and "desk mail read" in out
