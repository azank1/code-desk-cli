"""Desk-to-desk mail: `.office/mail/<desk>/*.md`, read at turn start.

The board is owner-to-engineer inside one thread. Mail is a different axis:
one desk handing something to another desk, possibly in another harness.
So it is a separate store, never merged into board.yaml.

Delivery has two shapes. Claude Code and Cursor pull: a turn-start hook
(`desk hook claude` / `desk hook cursor`) returns unread mail as extra
context and marks it read. Codex has no working project hook, so `desk
send` pushes a pointer with `codex queue --thread <desk>` when a session
with that exact name exists; the file still waits on disk for `desk mail
read`, which every role prompt asks the desk to run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import secrets
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .manifest import Office

MAIL_DIR = "mail"
READ_DIR = "read"
DESK_ENV = "DESK"  # set by `desk up` on every desk's process


class MailError(Exception):
    pass


@dataclass
class Message:
    path: Path
    sender: str
    to: str
    thread: str | None
    at: dt.datetime
    body: str

    def header(self) -> str:
        t = f" · thread {self.thread}" if self.thread else ""
        return f"from {self.sender} at {self.at.isoformat(timespec='minutes')}{t}"


def mail_dir(office: Office, desk: str) -> Path:
    return office.state_dir / MAIL_DIR / desk


def current_desk() -> str | None:
    return os.environ.get(DESK_ENV) or None


def send(office: Office, to: str, body: str, sender: str, thread: str | None = None) -> Path:
    if to not in office.desks:
        raise MailError(f"no desk named {to!r} (desks: {', '.join(office.desks)})")
    if thread is not None and thread not in office.threads:
        raise MailError(f"no thread named {thread!r}")
    body = body.strip()
    if not body:
        raise MailError("empty message")
    now = dt.datetime.now().astimezone()
    d = mail_dir(office, to)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{now.strftime('%Y%m%dT%H%M%S')}-{sender}-{secrets.token_hex(2)}.md"
    head = [f"from: {sender}", f"to: {to}", f"at: {now.isoformat(timespec='seconds')}"]
    if thread:
        head.append(f"thread: {thread}")
    path.write_text("\n".join(head) + "\n\n" + body + "\n")
    return path


def _parse(path: Path) -> Message | None:
    try:
        text = path.read_text()
    except OSError:
        return None
    head, _, body = text.partition("\n\n")
    fields: dict[str, str] = {}
    for line in head.splitlines():
        k, _, v = line.partition(":")
        fields[k.strip()] = v.strip()
    try:
        at = dt.datetime.fromisoformat(fields["at"])
    except (KeyError, ValueError):
        return None
    return Message(
        path,
        fields.get("from", "?"),
        fields.get("to", path.parent.name),
        fields.get("thread") or None,
        at,
        body.strip(),
    )


def unread(office: Office, desk: str) -> list[Message]:
    d = mail_dir(office, desk)
    if not d.is_dir():
        return []
    out = [m for p in sorted(d.glob("*.md")) if (m := _parse(p))]
    return sorted(out, key=lambda m: m.at)


def mark_read(msgs: list[Message]) -> None:
    for m in msgs:
        dest = m.path.parent / READ_DIR
        dest.mkdir(exist_ok=True)
        shutil.move(str(m.path), str(dest / m.path.name))


def render(desk: str, msgs: list[Message]) -> str:
    """Plain text a model can act on: one block per message, oldest first."""
    lines = [f"[desk mail] {len(msgs)} message(s) for desk {desk}:"]
    for i, m in enumerate(msgs, 1):
        lines.append(f"\n--- {i}. {m.header()} ---\n{m.body}")
    lines.append('\n[desk mail] end. Reply with `desk send <desk> "..."` if the sender needs an answer.')
    return "\n".join(lines)


def hook_output(harness: str, context: str | None) -> str:
    """The JSON a turn-start hook prints so the harness adds `context` to the turn."""
    if harness == "claude":
        if context is None:
            return "{}"
        return json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": context}})
    if harness == "cursor":
        out: dict = {"continue": True}
        if context is not None:
            out["additional_context"] = context
        return json.dumps(out)
    raise MailError(f"no turn-start hook shape for harness {harness!r}")


def codex_push(desk: str, text: str) -> tuple[bool, str]:
    """`codex queue --thread <desk>`: works only when a Codex session is named exactly `desk`."""
    if shutil.which("codex") is None:
        return False, "codex is not installed"
    r = subprocess.run(["codex", "queue", "--thread", desk, "--message", text], capture_output=True, text=True)
    if r.returncode == 0:
        return True, "queued"
    return False, (r.stderr or r.stdout).strip().splitlines()[-1] if (
        r.stderr or r.stdout
    ).strip() else f"exit {r.returncode}"
