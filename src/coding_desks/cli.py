"""`desk` — the command line."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import sys
from importlib import resources
from pathlib import Path

from . import __version__, hooks, mail, meter
from .board import Board, BoardError, SyncRow
from .intake import build_prompt
from .launcher import LaunchError, up
from .manifest import HATS, OFFICE_FILE, STATE_DIR, ManifestError, Office, load, warnings

# -- output helpers --------------------------------------------------------------

_COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _COLOR else s


def owner(s: str) -> str:
    return _c("33", s)


def eng(s: str) -> str:
    return _c("36", s)


def bad(s: str) -> str:
    return _c("31", s)


def ok(s: str) -> str:
    return _c("32", s)


def dim(s: str) -> str:
    return _c("2", s)


def table(headers: list[str], rows: list[list[str]]) -> str:
    import re

    def strip(s: str) -> str:
        return re.sub(r"\033\[[0-9;]*m", "", s)

    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(strip(cell)))

    def line(cells):
        return "  ".join(c + " " * (widths[i] - len(strip(c))) for i, c in enumerate(cells)).rstrip()

    out = [dim(line(headers))]
    out += [line(r) for r in rows]
    return "\n".join(out)


def die(msg: str, code: int = 1) -> NoReturn:  # noqa: F821
    print(bad("error: ") + msg, file=sys.stderr)
    sys.exit(code)


def _office() -> Office:
    try:
        return load()
    except ManifestError as e:
        die(str(e))


# -- rendering -----------------------------------------------------------------


def _col(filed: list[str], owes: list[str], paint) -> str:
    parts = [paint(x) for x in filed]
    if owes:
        parts.append(bad("— " + ", ".join(owes)))
    return " ".join(parts) or dim("·")


def board_table(rows: list[SyncRow]) -> str:
    body = []
    for r in rows:
        if r.closed:
            body.append([r.thread, r.desk, dim("closed"), dim("·"), dim("·"), ok("closed")])
            continue
        status = r.status
        paint = ok if status == "in sync" else bad
        body.append(
            [
                r.thread,
                r.desk,
                r.gate,
                _col(r.owner_filed, r.owner_owes, owner),
                _col(r.engineer_filed, r.engineer_owes, eng),
                paint(status),
            ]
        )
    return table(["THREAD", "DESK", "GATE", "OWNER", "ENGINEER", "SYNC"], body)


def sprint_header(office: Office) -> str:
    label, _, _ = meter.window(office)
    ms = ", ".join(office.milestones) or "none"
    return f"{dim('office')} {office.name}    {dim(label)}    {dim('milestones')} {ms}"


def meter_table(office: Office, days: int | None = None) -> str:
    label, start, end = meter.window(office, days=days)
    sessions = meter.read_all()
    rows = meter.summarize(office, sessions, meter.read_launches(office), start, end)
    now = dt.datetime.now(dt.UTC)
    body = []
    for u in rows:
        if u.turns == 0 and u.desk == meter.UNASSIGNED:
            continue
        pct = ""
        if u.budget:
            p = u.pct or 0.0
            pct = (bad if p >= 100 else ok)(f"{p:.0f}%") + dim(f" of {meter.fmt_tokens(u.budget)}")
        proj = meter.projection(u.total, start, min(now, end)) if u.total else 0
        if u.unmetered and u.unmetered == u.turns:
            # every turn came from a harness that writes no token counts
            tokens_in, tokens_out, tokens_total, pct, proj_s = dim("n/a"), dim("n/a"), dim("n/a"), dim("no data"), ""
        else:
            tokens_in = f"{meter.fmt_tokens(u.input)} ({meter.fmt_tokens(u.cached)})"
            tokens_out = meter.fmt_tokens(u.output)
            tokens_total = meter.fmt_tokens(u.total) + (dim("+") if u.unmetered else "")
            proj_s = dim(f"{meter.fmt_tokens(proj)}/30d") if proj else ""
        body.append(
            [u.desk, u.harness, str(u.sessions), str(u.turns), tokens_in, tokens_out, tokens_total, pct, proj_s]
        )
    if not body:
        return dim(f"no harness usage attributed to this office in {label}")
    note = ""
    if any(u.unmetered for u in rows):
        note = "\n" + dim("n/a, +: cursor writes no token counts to disk; those turns are counted, not metered")
    return (
        f"{dim('usage')} {label}\n"
        + table(["DESK", "HARNESS", "SESS", "TURNS", "IN (cached)", "OUT", "TOTAL", "BUDGET", "PROJECTION"], body)
        + note
    )


# -- commands --------------------------------------------------------------------


def cmd_init(a) -> None:
    root = Path.cwd()
    target = root / OFFICE_FILE
    if target.exists() and not a.force:
        die(f"{OFFICE_FILE} already exists here (use --force to overwrite)")
    tpl = resources.files("coding_desks").joinpath("templates")
    target.write_text(tpl.joinpath("office.yaml").read_text())
    roles = root / STATE_DIR / "roles"
    roles.mkdir(parents=True, exist_ok=True)
    for name in ("pm", "dev", "review"):
        p = roles / f"{name}.md"
        if not p.exists() or a.force:
            p.write_text(tpl.joinpath(f"roles/{name}.md").read_text())
    print(f"wrote {OFFICE_FILE} and {STATE_DIR}/roles/{{pm,dev,review}}.md")
    print("next: describe your office in your own words with `desk intake`, or edit office.yaml, then `desk check`")


def cmd_intake(a) -> None:
    if a.file:
        text = Path(a.file).read_text()
    elif a.text:
        text = " ".join(a.text)
    else:
        if sys.stdin.isatty():
            print(dim("paste your description, then Ctrl-D:"), file=sys.stderr)
        text = sys.stdin.read()
    if not text.strip():
        die("nothing to intake")
    print(build_prompt(text, Path.cwd() / OFFICE_FILE))


def cmd_check(a) -> None:
    office = _office()
    for w in warnings(office):
        print(bad("warn: ") + w)
    board = Board.load(office)
    added = board.reconcile()
    board.save()
    if added:
        print(f"board: added {len(added)} thread(s): {', '.join(added)}")
    n_open = sum(1 for r in board.rows() if not r.closed)
    print(
        ok("ok: ")
        + f"{office.name}: {len(office.desks)} desks, {len(office.gates)} gates, {len(office.threads)} threads ({n_open} open)"
    )


def cmd_board(a) -> None:
    office = _office()
    board = Board.load(office)
    print(sprint_header(office))
    print()
    print(board_table(board.rows()))


def cmd_inbox(a) -> None:
    office = _office()
    board = Board.load(office)
    hat = a.hat
    paint = owner if hat == "owner" else eng
    label, _, _ = meter.window(office)
    print(paint(f"{hat.upper()} INBOX") + f"  {dim(label)}")
    print()
    mine = board.inbox(hat)
    owes_key = "owner_owes" if hat == "owner" else "engineer_owes"
    other = "engineer" if hat == "owner" else "owner"
    other_filed = "engineer_filed" if hat == "owner" else "owner_filed"
    if not mine:
        print(dim("nothing owed by this hat"))
    for r in mine:
        print(f"{paint('▶')} {r.thread:<16}{r.gate:<10}owes: {paint(', '.join(getattr(r, owes_key)))}")
        filed = getattr(r, other_filed)
        if filed:
            print(f"  {'':<16}{'':<10}{other} filed: {', '.join(filed)}")
    waiting = board.waiting_on_other(hat)
    print()
    print(dim(f"{len(mine)} owed by {hat} · {len(waiting)} waiting on {other}"))


def cmd_deliver(a) -> None:
    office = _office()
    board = Board.load(office)
    try:
        row, advanced = board.deliver(a.thread, a.hat, a.item, note=a.note, evidence=a.evidence)
    except BoardError as e:
        die(str(e))
    board.save()
    paint = owner if a.hat == "owner" else eng
    print(
        f"filed {paint(a.hat + ':' + a.item)} on {a.thread} at gate {row.gate if not advanced else dim('(previous)')}"
    )
    if advanced:
        print(ok("gate passed") + f" → {a.thread} is now at " + (ok("closed") if row.closed else row.gate))
    elif row.owes:
        print(
            "waiting on "
            + " · ".join(
                f"{paint_(hat)} {', '.join(items)}"
                for hat, items, paint_ in (("owner", row.owner_owes, owner), ("engineer", row.engineer_owes, eng))
                if items
            )
        )


def cmd_status(a) -> None:
    office = _office()
    board = Board.load(office)
    print(sprint_header(office))
    print()
    rows = board.rows()
    print(board_table(rows))
    out = [r for r in rows if not r.closed and r.owes]
    print()
    print(
        dim(f"{len(out)} gate(s) out of sync · ") + " · ".join(f"{r.thread}: {'/'.join(r.owes)}" for r in out)
        if out
        else ok("all open gates in sync")
    )
    print()
    print(meter_table(office))


def cmd_meter(a) -> None:
    office = _office()
    print(meter_table(office, days=a.days))


def _desk_arg(a, required: bool = True) -> str | None:
    desk = getattr(a, "desk", None) or mail.current_desk()
    if desk is None and required:
        die("which desk? pass --desk NAME or run inside a desk started by `desk up` (DESK is set)")
    return desk


def cmd_send(a) -> None:
    office = _office()
    sender = a.sender or mail.current_desk() or "you"
    try:
        path = mail.send(office, a.desk, a.message, sender, thread=a.thread)
    except mail.MailError as e:
        die(str(e))
    print(f"sent to {eng(a.desk)} as {sender}: {dim(str(path.relative_to(office.root)))}")
    if office.desks[a.desk].harness == "codex":
        pushed, why = mail.codex_push(a.desk, f"[desk mail] new mail from {sender}; run `desk mail read`.")
        print(
            ok("codex: queued a pointer on the session named " + a.desk)
            if pushed
            else dim(f"codex: not pushed ({why}); the file waits for `desk mail read`")
        )


def cmd_mail(a) -> None:
    office = _office()
    if a.desk is None and mail.current_desk() is None and not a.read:
        rows = [(d, len(mail.unread(office, d))) for d in office.desks]
        print(table(["DESK", "UNREAD"], [[d, str(n) if n == 0 else bad(str(n))] for d, n in rows]))
        return
    desk = _desk_arg(a)
    if desk not in office.desks:
        die(f"no desk named {desk!r}")
    msgs = mail.unread(office, desk)
    if not msgs:
        print(dim(f"no unread mail for {desk}"))
        return
    print(mail.render(desk, msgs))
    if a.read:
        mail.mark_read(msgs)
        print(dim(f"{len(msgs)} marked read"))


def cmd_hook(a) -> None:
    """Turn-start hook body. Prints the harness's JSON; never fails the turn."""
    try:
        sys.stdin.read()  # the harness's payload; nothing in it we need, DESK carries identity
    except OSError:
        pass
    context = None
    try:
        office = load()
        desk = mail.current_desk()
        if desk and desk in office.desks:
            msgs = mail.unread(office, desk)
            if msgs:
                context = mail.render(desk, msgs)
                mail.mark_read(msgs)
    except (ManifestError, OSError):
        context = None
    try:
        print(mail.hook_output(a.harness, context))
    except mail.MailError as e:
        die(str(e))


def cmd_hooks(a) -> None:
    office = _office()
    try:
        plan = hooks.plan(office)
    except ValueError as e:
        die(str(e))
    if not plan:
        print(dim("no desk uses claude or cursor; nothing to install (codex is pushed to with `codex queue`)"))
        return
    if a.install:
        for path, changed in hooks.install(office):
            print((ok("wrote ") if changed else dim("already there ")) + str(path.relative_to(office.root)))
        return
    for path, harness, content, changed in plan:
        print(f"{path.relative_to(office.root)}  ({harness}, {'would change' if changed else 'already installed'})")
        print(dim(json.dumps(content, indent=2)))
    print(dim("run `desk hooks --install` to write these; only the office's own .claude/ and .cursor/ are touched"))


def cmd_up(a) -> None:
    office = _office()
    try:
        plan = up(office, dry_run=a.dry_run, attach=not a.no_attach)
    except LaunchError as e:
        die(str(e))
    if a.dry_run:
        for argv in plan:
            print(shlex.join(argv))
    elif a.no_attach:
        print(f"office {office.name} is up: tmux attach -t {shlex.quote(office.name)}")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="desk", description="Run an office of coding-harness sessions from the CLI.")
    p.add_argument("--version", action="version", version=f"coding-desks {__version__}")
    sp = p.add_subparsers(dest="cmd", required=True)

    s = sp.add_parser("init", help="write a template office.yaml and role prompts here")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sp.add_parser("intake", help="print a prompt that turns your description into office.yaml")
    s.add_argument("text", nargs="*")
    s.add_argument("-f", "--file")
    s.set_defaults(fn=cmd_intake)

    s = sp.add_parser("check", help="validate office.yaml and reconcile the board")
    s.set_defaults(fn=cmd_check)

    s = sp.add_parser("board", help="threads, gates and who owes what")
    s.set_defaults(fn=cmd_board)

    s = sp.add_parser("inbox", help="what one hat owes right now")
    s.add_argument("--as", dest="hat", choices=HATS, required=True)
    s.set_defaults(fn=cmd_inbox)

    s = sp.add_parser("deliver", help="file one deliverable at a thread's current gate")
    s.add_argument("thread")
    s.add_argument("hat", choices=HATS)
    s.add_argument("item")
    s.add_argument("--note")
    s.add_argument("--evidence", help="a path, SHA, URL or version string")
    s.set_defaults(fn=cmd_deliver)

    s = sp.add_parser("status", help="sprint, board, sync and usage in one screen")
    s.set_defaults(fn=cmd_status)

    s = sp.add_parser("meter", help="harness usage per desk from the transcript logs")
    s.add_argument("--days", type=int, help="ignore the sprint window and use the last N days")
    s.set_defaults(fn=cmd_meter)

    s = sp.add_parser("send", help="mail another desk (any harness)")
    s.add_argument("desk")
    s.add_argument("message")
    s.add_argument("--thread", help="the thread this is about")
    s.add_argument("--from", dest="sender", help="who is sending (default: $DESK, else 'you')")
    s.set_defaults(fn=cmd_send)

    s = sp.add_parser("mail", help="unread mail per desk, or one desk's mail")
    s.add_argument("--desk", help="which desk (default: $DESK)")
    s.add_argument("read", nargs="?", choices=["read"], help="print and mark read")
    s.set_defaults(fn=cmd_mail)

    s = sp.add_parser("hook", help="turn-start hook body for a harness (installed by `desk hooks`)")
    s.add_argument("harness", choices=["claude", "cursor"])
    s.set_defaults(fn=cmd_hook)

    s = sp.add_parser("hooks", help="show or install the project-scoped turn-start hooks that deliver mail")
    s.add_argument("--install", action="store_true")
    s.set_defaults(fn=cmd_hooks)

    s = sp.add_parser("up", help="open the office: one tmux window per desk")
    s.add_argument("--dry-run", action="store_true", help="print the tmux commands only")
    s.add_argument("--no-attach", action="store_true")
    s.set_defaults(fn=cmd_up)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
