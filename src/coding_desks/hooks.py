"""Project-scoped turn-start hooks that deliver mail. Never touches ~/."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .manifest import Office

CLAUDE_SETTINGS = ".claude/settings.json"
CURSOR_HOOKS = ".cursor/hooks.json"
CHECK_TIMEOUT_S = 30


def desk_bin() -> str:
    """The `desk` this process runs as, by absolute path.

    The harness runs the hook with its own PATH, which need not contain the
    venv or uv shim that owns `desk`; a bare `desk` there exits 127 on every
    turn and no mail is ever delivered. So the installed command names the
    binary outright. Falls back to the bare name when nothing better is known.
    """
    argv0 = Path(sys.argv[0])
    if argv0.name == "desk" and argv0.is_file():
        return str(argv0.resolve())
    return shutil.which("desk") or "desk"


def hook_command(harness: str) -> str:
    return shlex.join([desk_bin(), "hook", harness])


def is_ours(command: object, harness: str) -> bool:
    """Any `<…/>desk hook <harness>` entry counts as installed, bare or absolute."""
    if not isinstance(command, str):
        return False
    try:
        argv = shlex.split(command)
    except ValueError:
        return False
    return len(argv) == 3 and Path(argv[0]).name == "desk" and argv[1:] == ["hook", harness]


def merge_claude(settings: dict) -> tuple[dict, bool]:
    """Add the UserPromptSubmit hook if absent. (new settings, changed?)"""
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [])
    for g in groups:
        for h in g.get("hooks", []):
            if is_ours(h.get("command"), "claude"):
                return settings, False
    groups.append({"hooks": [{"type": "command", "command": hook_command("claude")}]})
    return settings, True


def merge_cursor(cfg: dict) -> tuple[dict, bool]:
    cfg.setdefault("version", 1)
    hooks = cfg.setdefault("hooks", {})
    entries = hooks.setdefault("beforeSubmitPrompt", [])
    if any(is_ours(e.get("command"), "cursor") for e in entries):
        return cfg, False
    entries.append({"command": hook_command("cursor")})
    return cfg, True


def installed(office: Office) -> list[tuple[Path, str, str]]:
    """(file, harness, command) for every hook of ours already in the office's files."""
    out = []
    p = office.root / CLAUDE_SETTINGS
    for g in _load(p).get("hooks", {}).get("UserPromptSubmit", []) if p.is_file() else []:
        for h in g.get("hooks", []):
            if is_ours(h.get("command"), "claude"):
                out.append((p, "claude", h["command"]))
    p = office.root / CURSOR_HOOKS
    for e in _load(p).get("hooks", {}).get("beforeSubmitPrompt", []) if p.is_file() else []:
        if is_ours(e.get("command"), "cursor"):
            out.append((p, "cursor", e["command"]))
    return out


@dataclass
class Check:
    path: Path
    harness: str
    command: str
    ok: bool
    detail: str


def check(office: Office) -> list[Check]:
    """Run each installed hook the way a harness would: bare PATH, empty payload.

    Passing means exit 0 and JSON on stdout. This is the only way to learn
    that the harness will find `desk`; `desk hooks` alone proves nothing.
    """
    desk = next(iter(office.desks), "")
    env = {"PATH": "/usr/bin:/bin", "HOME": os.environ.get("HOME", ""), "DESK": desk}
    out = []
    for path, harness, command in installed(office):
        try:
            r = subprocess.run(
                shlex.split(command),
                input="{}",
                capture_output=True,
                text=True,
                cwd=office.root,
                env=env,
                timeout=CHECK_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            out.append(Check(path, harness, command, False, str(e)))
            continue
        try:
            json.loads(r.stdout)
            ok = r.returncode == 0
        except json.JSONDecodeError:
            ok = False
        detail = f"exit {r.returncode}: " + (r.stdout.strip() or r.stderr.strip() or "(no output)")
        out.append(Check(path, harness, command, ok, detail))
    return out


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text() or "{}")
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: not valid JSON ({e}); fix it by hand first") from e
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return data


def plan(office: Office) -> list[tuple[Path, str, dict, bool]]:
    """(path, harness, merged content, changed) for each harness the office uses."""
    harnesses = {d.harness for d in office.desks.values()}
    out = []
    if "claude" in harnesses:
        p = office.root / CLAUDE_SETTINGS
        out.append((p, "claude", *merge_claude(_load(p))))
    if "cursor" in harnesses:
        p = office.root / CURSOR_HOOKS
        out.append((p, "cursor", *merge_cursor(_load(p))))
    return out


def install(office: Office) -> list[tuple[Path, bool]]:
    done = []
    for path, _, content, changed in plan(office):
        if changed:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content, indent=2) + "\n")
        done.append((path, changed))
    return done
