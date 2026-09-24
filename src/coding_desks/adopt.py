"""`desk adopt`: propose desks for a repo that already has sessions, from their names.

Adoption reads session metadata only (harness, id, name, directory, turn
counts) and writes an overlay office somewhere else. It never writes into
the directory it scans. The proposal is a starting point: a person confirms
or corrects it in `sessions.yaml`, and `desk sessions --against` measures the
office against that list.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .manifest import Office
from .meter import Launch, Session, _under, explain

COPY_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")  # "ops (2)": a harness's copy of a session name
TOKEN = re.compile(r"[a-z0-9]+")


class AdoptError(Exception):
    pass


def tokens(name: str, drop: set[str] = frozenset()) -> list[str]:
    """Lowercase alphanumeric runs of a session name, minus `drop` (the scanned dir's own words)."""
    toks = TOKEN.findall(COPY_SUFFIX.sub("", name).lower())
    kept = [t for t in toks if t not in drop]
    return kept or toks


def cluster(names: list[str], drop: set[str] = frozenset()) -> dict[str, list[str]]:
    """Group session names into proposed desks: same first token, or the same set of tokens.

    Deliberately dumb and explainable. It knows no vocabulary, stems nothing,
    and never guesses that two different words mean one topic; a person does
    that when they correct the proposal.
    """
    distinct = sorted(set(names), key=str.lower)
    parent = {n: n for n in distinct}

    def find(n: str) -> str:
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    by_key: dict[tuple, str] = {}
    for n in distinct:
        toks = tokens(n, drop)
        if not toks:
            continue
        for key in (("first", toks[0]), ("set", frozenset(toks))):
            if key in by_key:
                parent[find(n)] = find(by_key[key])
            else:
                by_key[key] = n
    groups: dict[str, list[str]] = {}
    for n in distinct:
        groups.setdefault(find(n), []).append(n)
    out: dict[str, list[str]] = {}
    for members in groups.values():
        firsts = {tuple(tokens(m, drop))[:1] for m in members}
        if len(firsts) == 1 and len(members) > 1:
            desk = next(iter(firsts))[0]
        else:
            desk = "-".join(tokens(members[0], drop)) or "desk"
        base, i = desk, 2
        while desk in out:
            desk, i = f"{base}-{i}", i + 1
        out[desk] = members
    return dict(sorted(out.items()))


@dataclass
class Proposal:
    estate: Path
    sessions: list[Session]  # every session under the estate
    desks: dict[str, list[str]]  # desk -> the session names it takes
    outside: int = 0  # sessions elsewhere, or with no directory recorded: not examined
    by_desk: dict[str, list[Session]] = field(default_factory=dict)

    @property
    def unnamed(self) -> list[Session]:
        return [s for s in self.sessions if not s.name]


def propose(estate: Path, sessions: list[Session]) -> Proposal:
    estate = estate.resolve()
    inside = [s for s in sessions if s.cwd and _under(s.cwd, estate)]
    drop = set(TOKEN.findall(estate.name.lower()))
    desks = cluster([s.name for s in inside if s.name], drop)
    p = Proposal(estate, inside, desks, outside=len(sessions) - len(inside))
    home = {n: d for d, names in desks.items() for n in names}
    for s in inside:
        if s.name:
            p.by_desk.setdefault(home[s.name], []).append(s)
    return p


def check_out_dir(estate: Path, out: Path) -> None:
    """Adoption never writes into the estate it scans."""
    e, o = estate.resolve(), out.resolve()
    if o == e or e in o.parents:
        raise AdoptError(f"--out {out} is inside {estate}; adoption never writes into the directory it scans")


def office_yaml(p: Proposal, out: Path, name: str) -> str:
    rel = os.path.relpath(p.estate, out.resolve())
    # exact names, escaped so a `[` or `*` in a name is not read as a glob
    desks = {desk: {"harness": "any", "sessions": [glob.escape(n) for n in names]} for desk, names in p.desks.items()}
    body = yaml.safe_dump(
        {
            "name": name,
            "estate": rel,
            "gates": {"adopted": {"owner": ["confirmed"], "engineer": ["evidence"]}},
            "desks": desks,
        },
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    return (
        "# Written by `desk adopt`: a proposal, not a fact. Rename desks, merge them,\n"
        "# widen `sessions:` into globs, pin ids with `id:<session id>`. Then check it\n"
        "# against sessions.yaml with `desk sessions --against sessions.yaml`.\n"
        "# `harness: any` desks are metered, never launched. The gate is a placeholder.\n" + body
    )


def sessions_yaml(p: Proposal) -> str:
    home = {n: d for d, names in p.desks.items() for n in names}
    rows = []
    for s in sorted(p.sessions, key=lambda s: s.first_ts):
        rows.append(
            {
                "id": s.id,
                "harness": s.harness,
                "name": s.name or "",
                "started": s.first_ts.isoformat(timespec="minutes"),
                "turns": len(s.turns),
                "desk": home.get(s.name, "") if s.name else "",
            }
        )
    return (
        "# Written by `desk adopt`. One row per session, keyed by its stable id.\n"
        "# `desk` holds the proposal. Correct it, and fill in the blank ones you can:\n"
        "# this file is the ground truth `desk sessions --against` measures the office by.\n"
        + yaml.safe_dump({"sessions": rows}, sort_keys=False, allow_unicode=True, width=120)
    )


@dataclass
class Agreement:
    turns_agree: int = 0
    turns_labelled: int = 0
    disagree: list[tuple[Session, str, str]] = field(default_factory=list)  # session, list says, office says
    unlabelled: list[Session] = field(default_factory=list)  # in the list with no desk
    unlisted: list[Session] = field(default_factory=list)  # under the estate, not in the list

    @property
    def pct(self) -> float | None:
        return None if not self.turns_labelled else 100.0 * self.turns_agree / self.turns_labelled


def read_truth(path: Path) -> dict[str, str]:
    data = yaml.safe_load(path.read_text()) or {}
    rows = data.get("sessions") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise AdoptError(f"{path}: expected a `sessions:` list")
    truth = {}
    for r in rows:
        if not isinstance(r, dict) or not r.get("id"):
            raise AdoptError(f"{path}: every row needs an id")
        truth[str(r["id"])] = str(r.get("desk") or "")
    return truth


def agreement(office: Office, sessions: list[Session], launches: list[Launch], truth: dict[str, str]) -> Agreement:
    """How many turns the office attributes to the desk the list says, weighted by turns."""
    who = explain(office, sessions, launches)
    a = Agreement()
    for s in sessions:
        at = who[s.id]
        if at.desk is None:
            continue
        if s.id not in truth:
            a.unlisted.append(s)
            continue
        want = truth[s.id]
        if not want:
            a.unlabelled.append(s)
            continue
        got = at.desk
        a.turns_labelled += len(s.turns)
        if got == want:
            a.turns_agree += len(s.turns)
        else:
            a.disagree.append((s, want, got))
    return a
