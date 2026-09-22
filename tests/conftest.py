import datetime as dt
from pathlib import Path

import pytest
import yaml

from coding_desks.manifest import parse

MANIFEST = {
    "name": "t",
    "hats": ["owner", "engineer"],
    "cadence": {"sprint_days": 7, "start": "2026-09-15"},
    "gates": {
        "scope": {"owner": ["scope", "priority"], "engineer": ["estimate", "risks"]},
        "ready": {"owner": ["verdict"], "engineer": ["tests-green", "evidence"], "order": "engineer-first"},
        "shipped": {"owner": ["acceptance"], "engineer": ["read-back"], "order": "engineer-first"},
    },
    "desks": {
        "pm": {"role": ".office/roles/pm.md", "harness": "claude", "budget": 1000},
        "dev": {"role": ".office/roles/dev.md", "harness": "claude", "cwd": "src", "budget": 5000},
        "review": {"role": ".office/roles/review.md", "harness": "codex"},
    },
    "milestones": [{"name": "m1", "due": "2026-10-01"}],
    "threads": [
        {"name": "a", "desk": "dev", "milestone": "m1"},
        {"name": "b", "desk": "pm"},
        {"name": "c", "desk": "review", "gates": ["ready"]},
    ],
}


@pytest.fixture
def office(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / ".office" / "roles").mkdir(parents=True)
    for n in ("pm", "dev", "review"):
        (tmp_path / ".office" / "roles" / f"{n}.md").write_text(f"# {n}\n")
    (tmp_path / "office.yaml").write_text(yaml.safe_dump(MANIFEST))
    return parse(MANIFEST, tmp_path)


@pytest.fixture
def now():
    return dt.datetime(2026, 9, 21, 12, 0, tzinfo=dt.timezone.utc)
