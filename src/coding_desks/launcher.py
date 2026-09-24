"""`desk up`: one tmux window per desk, each harness carrying its role prompt."""

from __future__ import annotations

import datetime as dt
import shlex
import shutil
import subprocess

from .manifest import LAUNCHABLE, Desk, Office
from .meter import Launch, record_launch


class LaunchError(Exception):
    pass


def desk_command(office: Office, desk: Desk) -> list[str]:
    if desk.harness not in LAUNCHABLE or not desk.role:
        raise LaunchError(f"desk {desk.name}: harness {desk.harness} is metered, never launched")
    role = office.root / desk.role
    if desk.harness == "claude":
        return ["claude", "--name", desk.name, "--append-system-prompt-file", str(role)]
    if desk.harness == "codex":
        # Codex has no system-prompt flag and no session-name flag (verified
        # 2026-09-21). The role file stays on disk; the first prompt is a short
        # pointer, so `desk up --dry-run` stays readable and the role can be
        # edited without relaunching.
        return ["codex", codex_pointer(desk, role)]
    if desk.harness == "cursor":
        # cursor-agent: no system-prompt flag, no session-name flag; same pointer
        # prompt as Codex. Name the session inside it (/rename) so the meter
        # attributes by rule 1; otherwise rule 2 (launch record) applies.
        return ["cursor-agent", codex_pointer(desk, role)]
    if desk.harness == "custom" and desk.command:
        return shlex.split(desk.command.format(name=desk.name, role=str(role), cwd=str(office.estate_root / desk.cwd)))
    raise LaunchError(f"desk {desk.name}: no command for harness {desk.harness}")


def codex_pointer(desk: Desk, role) -> str:
    return (
        f"You are the {desk.name} desk of this office. "
        f"Read {role} now and follow it for the rest of this session; "
        "it is your role prompt. Then read office.yaml and .office/board.yaml."
    )


def launchable(office: Office) -> list[Desk]:
    """Desks `desk up` opens. A `harness: any` desk only collects sessions for the meter."""
    return [d for d in office.desks.values() if d.harness in LAUNCHABLE]


def tmux_plan(office: Office) -> list[list[str]]:
    """The tmux argv list that opens the office. Pure; nothing runs."""
    if not launchable(office):
        raise LaunchError("no desk here can be launched: every desk is `harness: any`")
    session = office.name
    plan: list[list[str]] = []
    first = True
    for d in launchable(office):
        cwd = str((office.estate_root / d.cwd).resolve())
        cmd = shlex.join(desk_command(office, d))
        if first:
            plan.append(["tmux", "new-session", "-d", "-s", session, "-n", d.name, "-c", cwd, cmd])
            first = False
        else:
            plan.append(["tmux", "new-window", "-t", session, "-n", d.name, "-c", cwd, cmd])
    plan.append(["tmux", "new-window", "-t", session, "-n", "you", "-c", str(office.root)])
    plan.append(["tmux", "select-window", "-t", f"{session}:you"])
    return plan


def up(office: Office, dry_run: bool = False, attach: bool = True) -> list[list[str]]:
    plan = tmux_plan(office)
    if dry_run:
        return plan
    if shutil.which("tmux") is None:
        raise LaunchError("tmux is not installed")
    if subprocess.run(["tmux", "has-session", "-t", office.name], capture_output=True).returncode == 0:
        raise LaunchError(f"tmux session {office.name!r} is already running; `tmux attach -t {office.name}`")
    now = dt.datetime.now().astimezone()
    for argv in plan:
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode != 0:
            raise LaunchError(f"{shlex.join(argv)}\n{r.stderr.strip()}")
    for d in launchable(office):
        record_launch(office, Launch(d.name, d.harness, str((office.estate_root / d.cwd).resolve()), now))
    if attach:
        subprocess.run(["tmux", "attach", "-t", office.name])
    return plan
