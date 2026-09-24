# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

### Added
- Session aliases: a desk's `sessions:` takes name globs (any case) and
  pinned `id:<session id>` entries, so one desk collects a topic's sessions
  across harnesses and names. Ties between desks are reported, never
  resolved by order.
- `harness: any`: a desk that is metered but never launched by `desk up`.
- `estate:` in `office.yaml`: the directory whose sessions the office
  meters, so an office can live beside a repo instead of inside it.
- `desk sessions`: every session, the desk it went to and the rule that
  decided it.
- `desk adopt <dir> --out <dir>`: propose desks for a repo from the names
  of the sessions already run in it, and write an overlay office plus a
  `sessions.yaml` to correct. Reads session metadata only; refuses to write
  inside the directory it scans.
- `desk sessions --against <file>`: the share of turns the office attributes
  the way a confirmed list says, and every session it does not.
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
