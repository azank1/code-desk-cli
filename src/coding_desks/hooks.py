"""Project-scoped turn-start hooks that deliver mail. Never touches ~/."""

from __future__ import annotations

import json
from pathlib import Path

from .manifest import Office

CLAUDE_SETTINGS = ".claude/settings.json"
CURSOR_HOOKS = ".cursor/hooks.json"
CLAUDE_CMD = "desk hook claude"
CURSOR_CMD = "desk hook cursor"


def merge_claude(settings: dict) -> tuple[dict, bool]:
    """Add the UserPromptSubmit hook if absent. (new settings, changed?)"""
    hooks = settings.setdefault("hooks", {})
    groups = hooks.setdefault("UserPromptSubmit", [])
    for g in groups:
        for h in g.get("hooks", []):
            if h.get("command") == CLAUDE_CMD:
                return settings, False
    groups.append({"hooks": [{"type": "command", "command": CLAUDE_CMD}]})
    return settings, True


def merge_cursor(cfg: dict) -> tuple[dict, bool]:
    cfg.setdefault("version", 1)
    hooks = cfg.setdefault("hooks", {})
    entries = hooks.setdefault("beforeSubmitPrompt", [])
    if any(e.get("command") == CURSOR_CMD for e in entries):
        return cfg, False
    entries.append({"command": CURSOR_CMD})
    return cfg, True


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
