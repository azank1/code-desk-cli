# Contributing

## Setup

```bash
git clone https://github.com/azank1/code-desk-cli
cd code-desk-cli
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Python 3.11+, `uv`, `tmux`. Tests must not touch `~/.claude` or `~/.codex`;
the meter tests build their own log files under `tmp_path`.

## Branches, PRs and the commit budget

- `main` is append-only and moves only by **squash-merge of a PR**. Never
  push to it directly.
- **Four commits a day on `main`.** Branches and PRs are unlimited and do
  not count; only the squash that lands counts. Check before merging:

  ```bash
  tools/commit-budget.sh
  ```

- Branch names: `feat/<thing>`, `fix/<thing>`, `chore/<thing>`, `docs/<thing>`.
- A PR is one change with one reason. Its title becomes the commit message
  on `main`, so write the title for the changelog.
- CI (`ruff` + `pytest` on 3.11/3.12/3.13) must be green before merge.
- Every commit is authored by the person who made it. No generated
  co-author trailers.

## Where things live

| Path | What |
|---|---|
| `src/coding_desks/` | the package; `cli.py` is the only place that prints |
| `src/coding_desks/templates/` | `office.yaml` template and the three role prompts written by `desk init` |
| `tests/` | pytest; `conftest.py` holds the shared manifest fixture |
| `docs/architecture.pdf` | the PRD, architecture, stack and roadmap; `architecture.html` is its source, `diagrams/` the SVGs |
| `tools/` | maintainer scripts |

Regenerate the PDF after editing `docs/architecture.html`:

```bash
cd docs && soffice --headless --convert-to pdf architecture.html
```

## Releases

Versions live in `pyproject.toml` and `CHANGELOG.md`. Nothing is on PyPI yet.
