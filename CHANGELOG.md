# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- Desk-to-desk mail in `.office/mail/<desk>/`: `desk send`, `desk mail`,
  `desk mail read`. Separate from the board on purpose: the board is
  owner-to-engineer inside a thread, mail crosses desks and harnesses.
- Turn-start delivery: `desk hook claude` (UserPromptSubmit,
  `additionalContext`) and `desk hook cursor` (beforeSubmitPrompt,
  `additional_context`), installed project-scoped by `desk hooks --install`
  with a read-then-merge that keeps existing hooks. Codex is pushed to with
  `codex queue --thread <desk>` when a session carries the desk's name.
  Both pull hooks verified live with a nonce; `cursor-agent -p` does not run
  project hooks, only its interactive TUI does.
- `desk up` sets `DESK=<name>` on every desk's process; role prompts ask
  for `desk mail read` at the start of each turn.
- `cursor` harness: `desk up` launches `cursor-agent` with the same pointer
  prompt as Codex; the meter reads `~/.cursor/chats` and attributes sessions
  by name, launch record or directory.

### Changed
- The meter distinguishes counted turns from metered turns. A desk whose
  harness writes no token counts (Cursor) shows `n/a` instead of `0`, and a
  mixed desk marks its total with `+`.

## [0.0.1] — 2026-09-22

First tracked version. Not on PyPI.

### Added
- `office.yaml` manifest: two hats, gates with two columns and an optional
  `engineer-first` order, desks bound to a harness, threads, milestones,
  sprint cadence.
- Board in `.office/board.yaml`: `desk status`, `board`, `inbox --as`,
  `deliver`; a gate passes only when both columns are filed, and
  `engineer-first` refuses the owner's column until the engineer's is done.
- Meter: reads Claude Code and Codex transcript logs on disk, dedupes,
  attributes sessions to desks by name, launch record, or unique
  harness+directory, and reports tokens per desk per sprint with a 30-day
  projection.
- `desk up`: one tmux window per desk plus one for you; Claude desks get
  `--name` and their role file as a system prompt, Codex desks a short
  pointer prompt.
- `desk intake`: prints a prompt that turns a paragraph into `office.yaml`
  inside whatever harness you are already sitting in.
- Design document (PRD, architecture, stack, roadmap) under `docs/`.
