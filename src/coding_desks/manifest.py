"""office.yaml: load and validate the office contract."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HATS = ("owner", "engineer")
HARNESSES = ("claude", "codex", "cursor", "custom", "any")
LAUNCHABLE = ("claude", "codex", "cursor", "custom")
OFFICE_FILE = "office.yaml"
STATE_DIR = ".office"
BOARD_FILE = "board.yaml"


class ManifestError(Exception):
    pass


@dataclass
class Gate:
    name: str
    owner: list[str]
    engineer: list[str]
    order: str | None = None  # None | "engineer-first" | "owner-first"

    def items(self, hat: str) -> list[str]:
        return self.owner if hat == "owner" else self.engineer


@dataclass
class Desk:
    name: str
    role: str | None
    harness: str = "claude"
    model: str | None = None
    tier: str | None = None
    cwd: str = "."
    command: str | None = None
    budget: int | None = None  # tokens per sprint
    sessions: list[str] = field(default_factory=list)  # name globs, or id:<session id>


@dataclass
class Thread:
    name: str
    desk: str
    milestone: str | None = None
    gates: list[str] | None = None  # override of gate order


@dataclass
class Milestone:
    name: str
    due: dt.date | None = None


@dataclass
class Cadence:
    sprint_days: int = 7
    start: dt.date | None = None
    review: str | None = None


@dataclass
class Office:
    name: str
    root: Path
    estate: str = "."  # the directory whose sessions this office meters, relative to root
    hats: list[str] = field(default_factory=lambda: list(HATS))
    cadence: Cadence = field(default_factory=Cadence)
    gates: dict[str, Gate] = field(default_factory=dict)
    desks: dict[str, Desk] = field(default_factory=dict)
    milestones: dict[str, Milestone] = field(default_factory=dict)
    threads: dict[str, Thread] = field(default_factory=dict)

    @property
    def gate_order(self) -> list[str]:
        return list(self.gates)

    def thread_gates(self, thread: str) -> list[str]:
        t = self.threads[thread]
        return list(t.gates) if t.gates else self.gate_order

    @property
    def estate_root(self) -> Path:
        return (self.root / self.estate).resolve()

    @property
    def state_dir(self) -> Path:
        return self.root / STATE_DIR

    @property
    def board_path(self) -> Path:
        return self.state_dir / BOARD_FILE

    def sprint_window(self, today: dt.date | None = None) -> tuple[int, dt.date, dt.date] | None:
        """(sprint number, start, end-exclusive) for today, or None if no start."""
        c = self.cadence
        if c.start is None or c.sprint_days <= 0:
            return None
        today = today or dt.date.today()
        if today < c.start:
            return (0, c.start, c.start + dt.timedelta(days=c.sprint_days))
        n = (today - c.start).days // c.sprint_days
        start = c.start + dt.timedelta(days=n * c.sprint_days)
        return (n + 1, start, start + dt.timedelta(days=c.sprint_days))


def _date(v, where: str) -> dt.date | None:
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    try:
        return dt.date.fromisoformat(str(v))
    except ValueError as e:
        raise ManifestError(f"{where}: not an ISO date: {v!r}") from e


def _int(v, where: str) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        raise ManifestError(f"{where}: expected an integer")
    if isinstance(v, int):
        return v
    try:
        return int(str(v).replace("_", ""))
    except ValueError as e:
        raise ManifestError(f"{where}: expected an integer, got {v!r}") from e


def _strlist(v, where: str) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ManifestError(f"{where}: expected a list of strings")
    return list(v)


def find_root(start: Path | None = None) -> Path | None:
    """Walk up from start looking for office.yaml."""
    p = (start or Path.cwd()).resolve()
    for cand in (p, *p.parents):
        if (cand / OFFICE_FILE).is_file():
            return cand
    return None


def parse(data: dict, root: Path) -> Office:
    if not isinstance(data, dict):
        raise ManifestError("office.yaml must be a mapping")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ManifestError("name: required")
    estate = data.get("estate", ".")
    if not isinstance(estate, str) or not estate.strip():
        raise ManifestError("estate: expected a directory path")
    office = Office(name=name.strip(), root=root, estate=estate)

    hats = _strlist(data.get("hats", list(HATS)), "hats")
    if sorted(hats) != sorted(HATS):
        raise ManifestError(f"hats: must be exactly {list(HATS)} (got {hats})")
    office.hats = hats

    cad = data.get("cadence") or {}
    if not isinstance(cad, dict):
        raise ManifestError("cadence: expected a mapping")
    office.cadence = Cadence(
        sprint_days=_int(cad.get("sprint_days", 7), "cadence.sprint_days") or 7,
        start=_date(cad.get("start"), "cadence.start"),
        review=cad.get("review"),
    )

    gates = data.get("gates") or {}
    if not isinstance(gates, dict) or not gates:
        raise ManifestError("gates: at least one gate is required")
    for gname, g in gates.items():
        if not isinstance(g, dict):
            raise ManifestError(f"gates.{gname}: expected a mapping")
        owner = _strlist(g.get("owner"), f"gates.{gname}.owner")
        eng = _strlist(g.get("engineer"), f"gates.{gname}.engineer")
        if not owner and not eng:
            raise ManifestError(f"gates.{gname}: both columns are empty")
        order = g.get("order")
        if order not in (None, "engineer-first", "owner-first"):
            raise ManifestError(f"gates.{gname}.order: must be engineer-first or owner-first")
        office.gates[gname] = Gate(gname, owner, eng, order)

    desks = data.get("desks") or {}
    if not isinstance(desks, dict) or not desks:
        raise ManifestError("desks: at least one desk is required")
    for dname, d in desks.items():
        if not isinstance(d, dict):
            raise ManifestError(f"desks.{dname}: expected a mapping")
        harness = d.get("harness", "claude")
        if harness not in HARNESSES:
            raise ManifestError(f"desks.{dname}.harness: must be one of {HARNESSES}")
        role = d.get("role")
        if role is not None and (not isinstance(role, str) or not role):
            raise ManifestError(f"desks.{dname}.role: expected a path to a markdown role prompt")
        if role is None and harness != "any":
            raise ManifestError(f"desks.{dname}.role: required (path to a markdown role prompt)")
        if harness == "custom" and not d.get("command"):
            raise ManifestError(f"desks.{dname}.command: required for a custom harness")
        sessions = _strlist(d.get("sessions"), f"desks.{dname}.sessions")
        for pat in sessions:
            if not pat.strip() or pat.strip() == "id:":
                raise ManifestError(f"desks.{dname}.sessions: empty pattern")
        office.desks[dname] = Desk(
            name=dname,
            role=role,
            harness=harness,
            model=d.get("model"),
            tier=d.get("tier"),
            cwd=str(d.get("cwd", ".")),
            command=d.get("command"),
            budget=_int(d.get("budget"), f"desks.{dname}.budget"),
            sessions=sessions,
        )

    for m in data.get("milestones") or []:
        if not isinstance(m, dict) or not m.get("name"):
            raise ManifestError("milestones: each entry needs a name")
        office.milestones[m["name"]] = Milestone(m["name"], _date(m.get("due"), f"milestones.{m['name']}.due"))

    for t in data.get("threads") or []:
        if not isinstance(t, dict) or not t.get("name"):
            raise ManifestError("threads: each entry needs a name")
        tname = t["name"]
        if tname in office.threads:
            raise ManifestError(f"threads.{tname}: duplicate name")
        desk = t.get("desk")
        if desk not in office.desks:
            raise ManifestError(f"threads.{tname}.desk: unknown desk {desk!r}")
        ms = t.get("milestone")
        if ms is not None and ms not in office.milestones:
            raise ManifestError(f"threads.{tname}.milestone: unknown milestone {ms!r}")
        tg = _strlist(t.get("gates"), f"threads.{tname}.gates") or None
        if tg:
            unknown = [g for g in tg if g not in office.gates]
            if unknown:
                raise ManifestError(f"threads.{tname}.gates: unknown gates {unknown}")
        office.threads[tname] = Thread(tname, desk, ms, tg)

    return office


def load(root: Path | None = None) -> Office:
    root = root or find_root()
    if root is None:
        raise ManifestError("no office.yaml found here or above; run `desk init`")
    path = root / OFFICE_FILE
    try:
        data = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as e:
        raise ManifestError(f"{path}: {e}") from e
    return parse(data, root)


def warnings(office: Office) -> list[str]:
    """Non-fatal problems worth printing from `desk check`."""
    out = []
    if not office.estate_root.is_dir():
        out.append(f"estate is not a directory: {office.estate}")
    for d in office.desks.values():
        if d.role and not (office.root / d.role).is_file():
            out.append(f"desk {d.name}: role file missing: {d.role}")
        if not (office.estate_root / d.cwd).is_dir():
            out.append(f"desk {d.name}: cwd is not a directory: {d.cwd}")
    if office.cadence.start is None:
        out.append("cadence.start unset: no sprint window, meter reports the last 7 days")
    used = {t.desk for t in office.threads.values()}
    for d in office.desks:
        if d not in used:
            out.append(f"desk {d}: no threads assigned")
    return out
