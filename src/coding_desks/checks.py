"""Gate checks: a command that must exit 0 before a deliverable is accepted.

A gate item can name a check in office.yaml:

    gates:
      shipped:
        engineer: [read-back, receipt]
        checks:
          receipt: "my-verifier {evidence}"

`desk deliver <thread> engineer receipt --evidence <path>` then runs the
command from the office root. Exit 0 files the item; anything else refuses
it and nothing is written. The tool names no verifier and signs nothing:
the command is yours, like a Makefile target. When the evidence is a file,
its sha256 is kept on the board so `desk verify` can tell later whether the
file changed after it was accepted.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path

TIMEOUT_S = 300
TAIL_LINES = 12


class CheckError(Exception):
    pass


@dataclass
class CheckResult:
    command: str  # the template from office.yaml, before substitution
    returncode: int
    output: str  # combined stdout+stderr, last TAIL_LINES lines

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def digest(root: Path, evidence: str) -> str | None:
    """sha256 of the evidence if it names a file, else None (a SHA, URL, version...)."""
    p = Path(evidence)
    if not p.is_absolute():
        p = root / p
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def render(template: str, *, evidence: str, thread: str, gate: str, item: str) -> str:
    """Substitute {evidence} {thread} {gate} {item}, each shell-quoted."""
    values = {"evidence": evidence, "thread": thread, "gate": gate, "item": item}
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", shlex.quote(v))
    return out


def run(
    root: Path, template: str, *, evidence: str, thread: str, gate: str, item: str, timeout: int = TIMEOUT_S
) -> CheckResult:
    cmd = render(template, evidence=evidence, thread=thread, gate=gate, item=item)
    env = dict(os.environ)
    env.update(DESK_EVIDENCE=evidence, DESK_THREAD=thread, DESK_GATE=gate, DESK_ITEM=item)
    try:
        p = subprocess.run(
            ["sh", "-c", cmd],
            cwd=root,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(template, 124, f"check timed out after {timeout}s")
    tail = "\n".join((p.stdout + p.stderr).strip().splitlines()[-TAIL_LINES:])
    return CheckResult(template, p.returncode, tail)
