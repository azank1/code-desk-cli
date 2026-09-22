"""Read the transcript logs each harness already writes and attribute them to desks."""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .manifest import Office

UNASSIGNED = "(unassigned)"
LAUNCH_MATCH_WINDOW = dt.timedelta(minutes=10)


@dataclass
class Turn:
    ts: dt.datetime
    model: str | None
    input: int  # fresh + cache-write + cache-read input tokens
    cached: int  # the cache-read part of `input`
    output: int

    @property
    def total(self) -> int:
        return self.input + self.output


@dataclass
class Session:
    harness: str
    id: str
    cwd: str
    first_ts: dt.datetime
    name: str | None = None
    turns: list[Turn] = field(default_factory=list)
    metered: bool = True  # False when the harness writes no token counts to disk


@dataclass
class Launch:
    desk: str
    harness: str
    cwd: str
    at: dt.datetime


def _ts(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.UTC)
    return d


# -- readers ------------------------------------------------------------------


def read_claude(root: Path | None = None) -> list[Session]:
    """~/.claude/projects/<slug>/<session>.jsonl: assistant lines carry usage.

    One response is written as several lines that share a requestId and repeat
    the same usage block; count each requestId once.
    """
    root = root or Path.home() / ".claude" / "projects"
    out: list[Session] = []
    for path in sorted(root.glob("*/*.jsonl")):
        sess: Session | None = None
        seen: set[str] = set()
        name: str | None = None  # last custom-title record wins
        with path.open(errors="replace") as fh:
            for line in fh:
                if "assistant" not in line and "customTitle" not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") != "assistant":
                    if d.get("customTitle"):
                        name = d["customTitle"]
                        if sess is not None:
                            sess.name = name
                    continue
                usage = (d.get("message") or {}).get("usage")
                ts = d.get("timestamp")
                if not usage or not ts:
                    continue
                key = d.get("requestId") or d.get("uuid")
                if key in seen:
                    continue
                seen.add(key)
                if sess is None:
                    sess = Session(
                        harness="claude",
                        id=d.get("sessionId") or path.stem,
                        cwd=d.get("cwd") or "",
                        first_ts=_ts(ts),
                        name=name,
                    )
                cached = int(usage.get("cache_read_input_tokens") or 0)
                inp = int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0) + cached
                sess.turns.append(
                    Turn(
                        _ts(ts),
                        (d.get("message") or {}).get("model"),
                        inp,
                        cached,
                        int(usage.get("output_tokens") or 0),
                    )
                )
        if sess and sess.turns:
            out.append(sess)
    return out


def codex_names(index: Path) -> dict[str, str]:
    """~/.codex/session_index.jsonl: one {id, thread_name, updated_at} per rename; last wins."""
    names: dict[str, str] = {}
    if not index.is_file():
        return names
    with index.open(errors="replace") as fh:
        for line in fh:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("id") and d.get("thread_name"):
                names[d["id"]] = d["thread_name"]
    return names


def read_codex(root: Path | None = None) -> list[Session]:
    """~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl: token_usage_record per response.

    `payload.usage` is per response; `turn_token_usage` is cumulative per turn,
    so it is ignored. Dedupe on (file, ordinal).
    """
    root = root or Path.home() / ".codex" / "sessions"
    names = codex_names(root.parent / "session_index.jsonl")
    out: list[Session] = []
    for path in sorted(root.rglob("rollout-*.jsonl")):
        sess: Session | None = None
        cwd = ""
        seen: set = set()
        with path.open(errors="replace") as fh:
            for line in fh:
                if '"session_meta"' not in line and '"token_usage_record"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                p = d.get("payload") or {}
                if d.get("type") == "session_meta":
                    cwd = p.get("cwd") or cwd
                    continue
                if d.get("type") != "token_usage_record":
                    continue
                usage = p.get("usage")
                ts = d.get("timestamp")
                if not usage or not ts:
                    continue
                key = (path.name, d.get("ordinal"))
                if key in seen:
                    continue
                seen.add(key)
                if sess is None:
                    sid = p.get("thread_id") or path.stem
                    sess = Session("codex", sid, cwd, _ts(ts), name=names.get(sid))
                cached = int(usage.get("cached_input_tokens") or 0)
                inp = int(usage.get("input_tokens") or 0) + int(usage.get("cache_write_input_tokens") or 0)
                # codex counts cached tokens inside input_tokens already
                sess.turns.append(Turn(_ts(ts), None, inp, cached, int(usage.get("output_tokens") or 0)))
        if sess and sess.turns:
            sess.cwd = sess.cwd or cwd
            out.append(sess)
    return out


def read_cursor(root: Path | None = None) -> list[Session]:
    """~/.cursor/chats/<workspace-hash>/<session>/{meta.json,store.db}: sessions, no tokens.

    meta.json carries cwd, createdAtMs, updatedAtMs. store.db has a `meta`
    row (hex JSON with the session name) and one `blobs` row per message,
    role in the JSON. Neither the CLI stores nor the IDE's state.vscdb carry
    per-response token counts (verified 2026-09-22: 39k IDE bubbles all
    zero, 99k CLI blobs without a usage field), so every turn is 0 tokens
    and the session is marked unmetered. Messages carry no timestamps; all
    turns sit at the session's creation time.
    """
    import sqlite3

    root = root or Path.home() / ".cursor" / "chats"
    out: list[Session] = []
    for meta_path in sorted(root.glob("*/*/meta.json")):
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not meta.get("hasConversation"):
            continue
        db = meta_path.with_name("store.db")
        if not db.is_file():
            continue
        created = meta.get("createdAtMs")
        if not created:
            continue
        ts = dt.datetime.fromtimestamp(created / 1000, dt.UTC)
        name: str | None = None
        n_assistant = 0
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            try:
                for (value,) in con.execute("select value from meta"):
                    try:
                        name = json.loads(bytes.fromhex(value)).get("name") or name
                    except (ValueError, AttributeError):
                        continue
                # message blobs are JSON whose first key is `role`; encrypted
                # blobs are binary and never match. Same count as parsing
                # every blob, checked over 67 stores, at half the time.
                (n_assistant,) = con.execute(
                    """select count(*) from blobs where cast(substr(data, 1, 19) as text) = '{"role":"assistant"'"""
                ).fetchone()
            finally:
                con.close()
        except sqlite3.Error:
            continue
        if n_assistant == 0:
            continue
        if name == "New Agent":  # Cursor's default, carries no information
            name = None
        out.append(
            Session(
                "cursor",
                meta_path.parent.name,
                meta.get("cwd") or "",
                ts,
                name=name,
                turns=[Turn(ts, None, 0, 0, 0) for _ in range(n_assistant)],
                metered=False,
            )
        )
    return out


def read_all(
    claude_root: Path | None = None, codex_root: Path | None = None, cursor_root: Path | None = None
) -> list[Session]:
    sessions = []
    for reader, root in ((read_claude, claude_root), (read_codex, codex_root), (read_cursor, cursor_root)):
        try:
            sessions.extend(reader(root))
        except FileNotFoundError:
            pass
    return sessions


# -- launches (written by `desk up`) ------------------------------------------


def launches_path(office: Office) -> Path:
    return office.state_dir / "launches.yaml"


def read_launches(office: Office) -> list[Launch]:
    p = launches_path(office)
    if not p.is_file():
        return []
    data = yaml.safe_load(p.read_text()) or []
    return [Launch(x["desk"], x["harness"], x["cwd"], _ts(x["at"])) for x in data]


def record_launch(office: Office, launch: Launch) -> None:
    p = launches_path(office)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load(p.read_text()) if p.is_file() else []
    data = data or []
    data.append(
        {
            "desk": launch.desk,
            "harness": launch.harness,
            "cwd": launch.cwd,
            "at": launch.at.isoformat(timespec="seconds"),
        }
    )
    p.write_text(
        "# .office/launches.yaml — written by `desk up`, read by the meter.\n" + yaml.safe_dump(data, sort_keys=False)
    )


# -- attribution ---------------------------------------------------------------


def _under(path: str, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def attribute(office: Office, sessions: list[Session], launches: list[Launch]) -> dict[str, str | None]:
    """session.id -> desk name, UNASSIGNED (in this office, no desk), or None (not this office)."""
    result: dict[str, str | None] = {}
    desk_by_cwd: dict[tuple[str, str], list[str]] = {}
    for d in office.desks.values():
        key = (d.harness, str((office.root / d.cwd).resolve()))
        desk_by_cwd.setdefault(key, []).append(d.name)
    for s in sessions:
        if not s.cwd or not _under(s.cwd, office.root):
            result[s.id] = None
            continue
        # 1. the harness recorded a name equal to a desk name
        if s.name and s.name in office.desks:
            result[s.id] = s.name
            continue
        # 2. a launch record just before the session began, same harness + cwd
        best: Launch | None = None
        for ln in launches:
            if ln.harness != s.harness or str(Path(ln.cwd).resolve()) != str(Path(s.cwd).resolve()):
                continue
            if ln.at <= s.first_ts <= ln.at + LAUNCH_MATCH_WINDOW and (best is None or ln.at > best.at):
                best = ln
        if best:
            result[s.id] = best.desk
            continue
        # 3. exactly one desk claims this harness + cwd
        cands = desk_by_cwd.get((s.harness, str(Path(s.cwd).resolve())), [])
        result[s.id] = cands[0] if len(cands) == 1 else UNASSIGNED
    return result


# -- summaries -----------------------------------------------------------------


@dataclass
class DeskUsage:
    desk: str
    harness: str
    sessions: int = 0
    turns: int = 0
    input: int = 0
    cached: int = 0
    output: int = 0
    budget: int | None = None
    unmetered: int = 0  # turns from sessions whose harness writes no token counts

    @property
    def total(self) -> int:
        return self.input + self.output

    @property
    def pct(self) -> float | None:
        return None if not self.budget else 100.0 * self.total / self.budget


def summarize(
    office: Office,
    sessions: list[Session],
    launches: list[Launch],
    start: dt.datetime,
    end: dt.datetime,
) -> list[DeskUsage]:
    who = attribute(office, sessions, launches)
    rows: dict[str, DeskUsage] = {d.name: DeskUsage(d.name, d.harness, budget=d.budget) for d in office.desks.values()}
    for s in sessions:
        desk = who.get(s.id)
        if desk is None:
            continue
        turns = [t for t in s.turns if start <= t.ts < end]
        if not turns:
            continue
        row = rows.setdefault(desk, DeskUsage(desk, s.harness))
        if desk == UNASSIGNED and row.harness != s.harness:
            row.harness = "mixed"
        row.sessions += 1
        row.turns += len(turns)
        if not s.metered:
            row.unmetered += len(turns)
        row.input += sum(t.input for t in turns)
        row.cached += sum(t.cached for t in turns)
        row.output += sum(t.output for t in turns)
    return list(rows.values())


def window(
    office: Office, now: dt.datetime | None = None, days: int | None = None
) -> tuple[str, dt.datetime, dt.datetime]:
    """(label, start, end) — the current sprint, or the last N days."""
    now = now or dt.datetime.now(dt.UTC)
    sw = office.sprint_window(now.astimezone().date()) if days is None else None
    if sw:
        n, s, e = sw
        tz = dt.datetime.now().astimezone().tzinfo
        start = dt.datetime.combine(s, dt.time.min, tz)
        end = dt.datetime.combine(e, dt.time.min, tz)
        return (f"sprint {n} · {s.isoformat()} → {e.isoformat()}", start, end)
    days = days or 7
    return (f"last {days} days", now - dt.timedelta(days=days), now)


def projection(total: int, start: dt.datetime, now: dt.datetime | None = None, horizon_days: int = 30) -> int:
    now = now or dt.datetime.now(dt.UTC)
    elapsed = max((now - start).total_seconds() / 86400.0, 1.0)
    return int(total / elapsed * horizon_days)


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}k"
    return str(n)
