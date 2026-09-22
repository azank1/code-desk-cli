# coding-desks

Run an **office** of coding-harness sessions from your terminal: a product
manager desk, a developer desk, a reviewer desk, each a real Claude Code or
Codex session with its own role prompt, all working one repo under one
sprint cadence, with a usage meter that tells you what each desk actually
costs in tokens.

One person wears two hats, **owner** (decides) and **engineer** (delivers
evidence). Every handoff between them is a **gate** with two columns. A
thread passes a gate only when both columns are filled, and a gate marked
`engineer-first` refuses the owner's verdict until the engineer's evidence
is on file. That is the whole trick: the timeline cannot drift, because
nobody can sign off on nothing.

Status: **v0, pre-release.** Works on this author's machine. Not on PyPI.

## What it is not

- Not a multi-agent framework. Your existing harness sessions are the
  agents; this tool only launches, names and meters them.
- Not a service. No daemon, no API keys, no cloud. Everything is files in
  your repo plus the transcript logs the harnesses already write.
- Not a cost calculator. It reports tokens, never money.

## Install (development)

```bash
git clone https://github.com/azank1/code-desk-cli
cd code-desk-cli
uv sync            # or: pip install -e .
uv run desk --help
```

Requires Python 3.11+, `tmux`, and at least one of `claude` or `codex` on
your PATH. `pyyaml` is the only dependency.

## Five minutes

```bash
cd your-repo
desk init                   # writes office.yaml + .office/roles/*.md
$EDITOR office.yaml         # name the desks, gates, threads, sprint start
desk check                  # validates the manifest, warns on gaps
desk up                     # one tmux window per desk, plus one for you
```

Or describe the office in a paragraph and let the harness you are already
sitting in write the manifest:

```bash
desk intake "PM, one dev on Claude, a Codex reviewer, weekly sprints from Monday, ship v1 by Oct 15" | pbcopy
# paste into any harness; it writes office.yaml; then: desk check
```

Working the board:

```bash
desk status                          # sprint header + every thread's gate + who owes what
desk inbox --as engineer             # what the engineer owes right now
desk deliver auth-flow engineer estimate --note "2 days"
desk deliver auth-flow engineer risks --evidence docs/risks.md
desk deliver auth-flow owner scope   # owner's column; refused if engineer-first and evidence missing
desk board                           # full table
desk meter                           # tokens per desk this sprint, vs budget, with a 30-day projection
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

State lives in `.office/board.yaml` (which gate each thread is at, what was
filed, when, with what evidence) and `.office/launches.yaml` (when each desk
was started, for meter attribution). Commit both or ignore both; your call.

## How the meter works

No instrumentation. Claude Code writes `~/.claude/projects/<slug>/*.jsonl`
and Codex writes `~/.codex/sessions/**/rollout-*.jsonl`; both carry per
response token usage and the working directory. The meter reads them,
dedupes (Claude repeats usage across content blocks of one response; Codex
has a cumulative per-turn record that must be ignored) and attributes each
session to a desk by, in order:

1. the session's name equals a desk name (`claude --name`, or a Codex thread
   name from its session index);
2. a `desk up` launch record within ten minutes of the session start, same
   harness and directory;
3. exactly one desk claims that harness and directory.

Anything else under the office root shows as `(unassigned)`; anything
outside is ignored. Budgets are per sprint and in tokens.

## Design

The product requirements, architecture, stack and roadmap are in
`docs/architecture.pdf` (source `docs/architecture.html`), with the diagrams as
SVG under `docs/diagrams/`. That document is the source of truth for the
idea; this README is the source of truth for how to run what exists.

## Contributing

See `CONTRIBUTING.md`. Short version: `uv sync`, `uv run pytest -q`, open a PR from a branch. Branches and PRs are unlimited; `main` takes four squash-merges a day.

## License

MIT.
