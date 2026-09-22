import copy
import datetime as dt

import pytest

from coding_desks.manifest import ManifestError, parse, warnings
from tests.conftest import MANIFEST


def bad(mutate):
    m = copy.deepcopy(MANIFEST)
    mutate(m)
    return m


def test_parse_roundtrip(office):
    assert office.gate_order == ["scope", "ready", "shipped"]
    assert office.thread_gates("c") == ["ready"]
    assert office.desks["dev"].budget == 5000
    assert office.milestones["m1"].due == dt.date(2026, 10, 1)


def test_sprint_window(office):
    n, s, e = office.sprint_window(dt.date(2026, 9, 21))
    assert (n, s, e) == (1, dt.date(2026, 9, 15), dt.date(2026, 9, 22))
    n, s, e = office.sprint_window(dt.date(2026, 9, 22))
    assert (n, s) == (2, dt.date(2026, 9, 22))


def test_underscore_budget(tmp_path):
    m = bad(lambda m: m["desks"]["pm"].__setitem__("budget", "10_000_000"))
    assert parse(m, tmp_path).desks["pm"].budget == 10_000_000


@pytest.mark.parametrize(
    "mutate, needle",
    [
        (lambda m: m.__setitem__("hats", ["owner"]), "hats"),
        (lambda m: m.__setitem__("gates", {}), "gates"),
        (lambda m: m["gates"]["ready"].__setitem__("order", "sideways"), "order"),
        (lambda m: m["threads"][0].__setitem__("desk", "nobody"), "unknown desk"),
        (lambda m: m["threads"][0].__setitem__("milestone", "m9"), "unknown milestone"),
        (lambda m: m["threads"].append({"name": "a", "desk": "pm"}), "duplicate"),
        (lambda m: m["desks"].__setitem__("x", {"role": "r.md", "harness": "custom"}), "command"),
        (lambda m: m["desks"].__setitem__("x", {"role": "r.md", "harness": "vim"}), "harness"),
        (lambda m: m["threads"][0].__setitem__("gates", ["nope"]), "unknown gates"),
    ],
)
def test_rejects(tmp_path, mutate, needle):
    with pytest.raises(ManifestError, match=needle):
        parse(bad(mutate), tmp_path)


def test_warnings_role_missing(office):
    (office.root / ".office" / "roles" / "pm.md").unlink()
    ws = warnings(office)
    assert any("pm" in w and "role file missing" in w for w in ws)
