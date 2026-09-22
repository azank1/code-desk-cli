<h1 align="center">code desks</h1>

<p align="center">
  Run an office of AI coding sessions from your terminal.<br>
  Two hats, gated handoffs, and a meter that reads what each desk really used.
</p>

<p align="center">
  <a href="https://github.com/azank1/code-desk-cli/actions/workflows/ci.yml"><img alt="ci" src="https://github.com/azank1/code-desk-cli/actions/workflows/ci.yml/badge.svg"></a>
  &nbsp;
  <img alt="python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white">
  &nbsp;
  <img alt="license MIT" src="https://img.shields.io/badge/license-MIT-green">
  &nbsp;
  <img alt="status v0" src="https://img.shields.io/badge/status-v0%20pre--release-orange">
</p>

<p align="center">
  <a href="#quick-start">Quick start</a> ·
  <a href="#how-it-works">How it works</a> ·
  <a href="#the-manifest">Manifest</a> ·
  <a href="#the-meter">Meter</a> ·
  <a href="#commands">Commands</a> ·
  <a href="#design">Design</a> ·
  <a href="#contributing">Contributing</a>
</p>

---

A **desk** is one real Claude Code, Codex or Cursor session with a role
prompt: product manager, developer, reviewer, whatever your office needs.
An **office** is a set of desks working one repo under one sprint cadence,
described in a single `office.yaml` you edit like code.

One person wears two hats. The **owner** decides. The **engineer** delivers
evidence. Every handoff between them is a **gate** with two columns, and a
thread passes only when both are filled. A gate marked `engineer-first`
refuses the owner's verdict until the engineer's evidence is on file.

That is the whole trick. The timeline cannot drift, because nobody can sign
off on nothing.

<br>

<table align="center">
<tr>
<td width="33%" valign="top">

**No daemon, no keys, no cloud**

Everything is files in your repo plus the transcript logs your harnesses
already write. Nothing runs when you are not running it.

</td>
<td width="33%" valign="top">

**Not a framework**

Your existing sessions are the agents. This tool launches them, names
them, hands work between them and meters them. It never calls a model.

</td>
<td width="33%" valign="top">

**Tokens, never money**

The meter reports what each desk actually consumed, per sprint, against a
budget you set. It never guesses a price.

</td>
</tr>
</table>

<br>

## Quick start

Requires Python 3.11+, [`uv`](https://docs.astral.sh/uv/), `tmux`, and at
least one of `claude`, `codex` or `cursor-agent` on your `PATH`.

```bash
git clone https://github.com/azank1/code-desk-cli
cd code-desk-cli
uv sync
uv run desk --help
```

Then, inside the repo you want to run an office on:

```bash
desk init            # writes office.yaml + .office/roles/*.md
$EDITOR office.yaml  # name the desks, gates, threads, sprint start
desk check           # validates the manifest, warns on gaps
desk up              # one tmux window per desk, plus one for you
```

Prefer to describe the office in a paragraph? Let the harness you are
already sitting in write the manifest:

```bash
desk intake "PM, one dev on Claude, a Codex reviewer, weekly sprints from Monday, ship v1 by Oct 15"
# paste the printed prompt into any harness; it writes office.yaml; then: desk check
```

## How it works

```
  office.yaml ─────────► desks ──── desk up ────► tmux: one window per desk
       │                                                │
       │ gates, threads                                 │ transcript logs
       ▼                                                ▼
  .office/board.yaml ◄── desk deliver          ~/.claude  ~/.codex  ~/.cursor
       │                                                │
       ▼                                                ▼
  desk status / inbox / board                      desk meter
  who owes what, right now                 tokens per desk per sprint
```

A **thread** is one piece of work on one desk. It walks the gates in order
toward a milestone. At each gate the owner's column holds decisions
(scope, priority, verdict, acceptance) and the engineer's column holds
evidence (estimate, risks, tests green, read-back). `desk inbox --as owner`
and `desk inbox --as engineer` are two views of the same board.

```
THREAD          GATE      OWNER              ENGINEER               SYNC
auth-flow       scope     — scope, priority  estimate, risks        owner owes
board-export    scope     scope, priority    — estimate, risks      engineer owes
meter-cursor    ready     — verdict          tests-green, evidence  owner owes
kb-cadence      shipped   acceptance         read-back v0.1.3       closed
```

## The manifest

`office.yaml` is the contract. Edit it like code, review it in PRs.

```yaml
name: my-office
hats: [owner, engineer]
cadence: { sprint_days: 7, start: 2026-09-22, review: friday }
gates:
  scope:   { owner: [scope, priority], engineer: [estimate, risks] }
  ready:   { owner: [verdict],         engineer: [tests-green, evidence], order: engineer-first }
  shipped: { owner: [acceptance],      engineer: [read-back, receipt],    order: engineer-first }
desks:
  pm:     { role: .office/roles/pm.md,     harness: claude, model: opus, budget: 10_000_000 }
  dev:    { role: .office/roles/dev.md,    harness: claude, model: opus, budget: 36_000_000 }
  review: { role: .office/roles/review.md, harness: codex,  budget: 5_000_000 }
milestones:
  - { name: first-release, due: 2026-10-15 }
threads:
  - { name: auth-flow, desk: dev, milestone: first-release }
```

| Key | Meaning |
|---|---|
| `hats` | Exactly `owner` and `engineer`. They may be the same person. |
| `cadence` | Sprint length in days and the first sprint's start date. Budgets are per sprint. |
| `gates` | Ordered. Each has an `owner` column and an `engineer` column. `order: engineer-first` blocks the owner until the engineer's column is complete. |
| `desks` | One per role. `harness` is `claude`, `codex`, `cursor` or `custom` (with a `command`). `budget` is tokens per sprint. `cwd` defaults to the repo root. |
| `threads` | Work items. One desk each, optional milestone, optional `gates:` subset. |

State lives in `.office/board.yaml` (which gate each thread is at, what was
filed, when, with what evidence) and `.office/launches.yaml` (when each
desk was started, for meter attribution). Commit both or ignore both.

## The meter

No instrumentation. Claude Code writes `~/.claude/projects/<slug>/*.jsonl`
and Codex writes `~/.codex/sessions/**/rollout-*.jsonl`; both carry per
response token usage and the working directory. The meter reads them,
dedupes (Claude repeats usage across the content blocks of one response;
Codex keeps a cumulative per-turn record that must be ignored), and
attributes each session to a desk by, in order:

1. the session's name equals a desk name (`claude --name`, or a Codex
   thread name from its session index);
2. a `desk up` launch record within ten minutes of the session start, same
   harness and directory;
3. exactly one desk claims that harness and directory.

Anything else under the office root shows as `(unassigned)`. Anything
outside is ignored.

```
usage sprint 2 · 2026-09-22 → 2026-09-29
DESK    HARNESS  SESS  TURNS  IN (cached)      OUT     TOTAL    BUDGET         PROJECTION
pm      claude   3     412    41.2M (38.9M)    0.6M    41.8M    418% of 10.0M  125.4M/30d
dev     claude   5     1105   130.1M (124.0M)  2.1M    132.2M   367% of 36.0M  396.6M/30d
review  cursor   2     96     n/a              n/a     n/a      no data
```

**Cursor** is different. `cursor-agent` writes the directory, start time,
session name and every message to `~/.cursor/chats`, but no token counts,
and the IDE's own database has none either. A `cursor` desk is attributed
and its turns are counted; its token columns say `n/a`. Nothing is
estimated in their place.

## Commands

| Command | What it does |
|---|---|
| `desk init` | Write `office.yaml` and the three starter role prompts. |
| `desk intake "<paragraph>"` | Print a prompt that turns your description into `office.yaml`, for the harness you are already in. |
| `desk check` | Validate the manifest. Warn on desks with no threads, threads with no milestone, gates nobody uses. |
| `desk up [--dry-run] [--no-attach]` | Open a tmux session, one window per desk, each harness carrying its role. |
| `desk status` | Sprint header, every thread's gate, who owes what. |
| `desk board` | The full table. |
| `desk inbox --as owner\|engineer` | What one hat owes right now, and what it is waiting on. |
| `desk deliver <thread> <hat> <item> [--note] [--evidence]` | File one deliverable at the thread's current gate. Refused if the item is wrong, already filed, or blocked by `engineer-first`. |
| `desk meter [--days N]` | Tokens per desk for the current sprint, or the last N days, against budget, with a 30-day projection. |

## Design

The product requirements, architecture, stack and roadmap live in
[`docs/architecture.pdf`](docs/architecture.pdf), with the diagrams as
SVG under [`docs/diagrams/`](docs/diagrams/). That document is the source
of truth for the idea. This README is the source of truth for running what
exists.

**Roadmap, short form:** `desk estimate` (which plan tier each desk needs
at the measured cadence, only after seven days of history) · per-desk
mailbox so a PM desk can hand a thread to a dev desk in another harness ·
signed receipts at the `shipped` gate.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Short version: `uv sync`,
`uv run pytest -q`, open a PR from a branch. Branches and PRs are
unlimited; `main` takes four squash-merges a day.

## License

MIT. See [`LICENSE`](LICENSE).
