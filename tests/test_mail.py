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
    assert s2["hooks"]["UserPromptSubmit"] == [{"hooks": [{"type": "command", "command": "desk hook claude"}]}]
    _, changed = hooks.merge_claude(s2)
    assert not changed
    c = {"version": 1, "hooks": {"stop": [{"command": "./hooks/ping.sh"}]}}
    c2, changed = hooks.merge_cursor(c)
    assert changed and c2["hooks"]["stop"] == [{"command": "./hooks/ping.sh"}]
    assert c2["hooks"]["beforeSubmitPrompt"] == [{"command": "desk hook cursor"}]
    assert hooks.merge_cursor(c2)[1] is False


def test_hooks_install_writes_only_project_files(in_office, capsys):
    cli.main(["hooks"])
    out = capsys.readouterr().out
    assert ".claude/settings.json" in out and "would change" in out
    assert ".cursor/hooks.json" not in out  # no cursor desk in the fixture
    cli.main(["hooks", "--install"])
    assert "wrote .claude/settings.json" in capsys.readouterr().out
    data = json.loads((in_office.root / ".claude" / "settings.json").read_text())
    assert data["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"] == "desk hook claude"
    cli.main(["hooks", "--install"])
    assert "already there" in capsys.readouterr().out


def test_up_dry_run_sets_desk_env(in_office, capsys):
    cli.main(["up", "--dry-run"])
    out = capsys.readouterr().out
    assert "env DESK=pm claude --name pm" in out
    assert "env DESK=review codex " in out and "desk mail read" in out
