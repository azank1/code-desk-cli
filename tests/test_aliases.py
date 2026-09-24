import datetime as dt

import pytest
import yaml

from coding_desks import cli, meter
from coding_desks.launcher import LaunchError, tmux_plan
from coding_desks.manifest import ManifestError, load, parse, warnings
from coding_desks.meter import UNASSIGNED, Launch, Session, Turn


def _sess(harness, sid, cwd, name=None, ts="2026-09-21T10:00:00+00:00", tokens=100):
    t = dt.datetime.fromisoformat(ts)
    return Session(harness, sid, cwd, t, name, [Turn(t, None, tokens, 0, 10)], metered=harness != "cursor")


def _office(tmp_path, desks, **extra):
    data = {"name": "t", "gates": {"done": {"owner": ["ok"], "engineer": ["tests"]}}, "desks": desks, **extra}
    return parse(data, tmp_path)


def test_alias_globs_ignore_case_and_span_harnesses(tmp_path):
    o = _office(
        tmp_path,
        {
            "payments": {"harness": "any", "sessions": ["pay-*", "billing"]},
            "search": {"harness": "any", "sessions": ["search*"]},
        },
    )
    root = str(tmp_path)
    who = meter.explain(
        o,
        [
            _sess("claude", "a", root, "Pay-Refunds"),
            _sess("codex", "b", root, "pay-webhooks"),
            _sess("cursor", "c", root, "BILLING"),
            _sess("claude", "d", root, "search-ranking"),
            _sess("codex", "e", root, "unrelated"),
            _sess("cursor", "f", root),
        ],
        [],
    )
    assert {k: (v.desk, v.rule) for k, v in who.items()} == {
        "a": ("payments", "alias"),
        "b": ("payments", "alias"),
        "c": ("payments", "alias"),
        "d": ("search", "alias"),
        "e": (UNASSIGNED, "none"),  # any desks never take a session by directory
        "f": (UNASSIGNED, "none"),
    }


def test_overlapping_aliases_are_a_tie_never_first_match(tmp_path):
    o = _office(
        tmp_path,
        {
            "api": {"harness": "any", "sessions": ["api-*"], "cwd": "."},
            "infra": {"harness": "any", "sessions": ["*-deploy"], "cwd": "."},
        },
    )
    (at,) = meter.explain(o, [_sess("claude", "x", str(tmp_path), "api-deploy")], []).values()
    assert at.desk == UNASSIGNED and at.rule == "ambiguous" and sorted(at.candidates) == ["api", "infra"]


def test_rule_order_id_then_name_then_alias_then_launch_then_cwd(tmp_path):
    (tmp_path / "src").mkdir()
    o = _office(
        tmp_path,
        {
            "pinned": {"harness": "any", "sessions": ["id:s-pinned"], "cwd": "src"},
            "web": {"harness": "any", "sessions": ["web-*"], "cwd": "src"},
            "dev": {"harness": "claude", "role": "dev.md", "cwd": "src"},
        },
    )
    src = str(tmp_path / "src")
    launches = [Launch("dev", "claude", src, dt.datetime.fromisoformat("2026-09-21T09:58:00+00:00"))]
    who = meter.explain(
        o,
        [
            _sess("claude", "s-pinned", src, "web-login"),  # id beats alias and launch
            _sess("claude", "s-named", src, "pinned"),  # a name equal to a desk beats the alias
            _sess("claude", "s-alias", src, "web-login"),  # alias beats the launch record
            _sess("claude", "s-launch", src, "notes"),  # launch record
            _sess("codex", "s-cwd", src, "notes"),  # codex at src: dev is claude, any desks never take by cwd
        ],
        launches,
    )
    assert who["s-pinned"].desk == "pinned" and who["s-pinned"].rule == "id"
    assert who["s-named"].desk == "pinned" and who["s-named"].rule == "name"
    assert who["s-alias"].desk == "web" and who["s-alias"].rule == "alias"
    assert who["s-launch"].desk == "dev" and who["s-launch"].rule == "launch"
    assert who["s-cwd"].desk == UNASSIGNED and who["s-cwd"].rule == "none"


def test_an_any_desk_never_takes_a_session_by_directory(tmp_path):
    o = _office(tmp_path, {"dev": {"harness": "claude", "role": "dev.md"}, "ops": {"harness": "any"}})
    root = str(tmp_path)
    who = meter.explain(o, [_sess("claude", "c", root), _sess("codex", "x", root)], [])
    assert who["c"].desk == "dev" and who["c"].rule == "cwd"
    assert who["x"].desk == UNASSIGNED and who["x"].rule == "none"


def test_adding_an_alias_desk_moves_only_the_sessions_it_names(office):
    root = str(office.root)
    sessions = [
        _sess("claude", "by-name", root, name="pm"),
        _sess("claude", "unique-cwd", root + "/src"),
        _sess("codex", "codex-root", root),
        _sess("claude", "root-unnamed", root),
        _sess("cursor", "cursor-root", root),
        _sess("claude", "ops-named", root, name="ops-nightly"),
    ]
    before = meter.attribute(office, sessions, [])
    data = yaml.safe_load((office.root / "office.yaml").read_text())
    data["desks"]["ops"] = {"harness": "any", "sessions": ["ops-*"]}
    after = meter.attribute(parse(data, office.root), sessions, [])
    assert after.pop("ops-named") == "ops"
    before.pop("ops-named")
    assert after == before


def test_estate_lets_the_office_live_outside_the_repo_it_meters(tmp_path):
    repo, overlay = tmp_path / "repo", tmp_path / "overlay"
    (repo / "sub").mkdir(parents=True)
    overlay.mkdir()
    o = _office(overlay, {"ops": {"harness": "any", "sessions": ["ops-*"]}}, estate="../repo")
    assert o.estate_root == repo.resolve()
    who = meter.explain(
        o,
        [
            _sess("claude", "in", str(repo / "sub"), "ops-nightly"),
            _sess("claude", "overlay", str(overlay), "ops-nightly"),  # the overlay dir itself is not the estate
        ],
        [],
    )
    assert who["in"].desk == "ops" and who["overlay"].desk is None
    assert not [w for w in warnings(o) if "cwd" in w or "estate" in w]


def test_manifest_rules_for_any_desks(tmp_path):
    o = _office(tmp_path, {"ops": {"harness": "any"}})
    assert o.desks["ops"].role is None and o.desks["ops"].sessions == []
    with pytest.raises(ManifestError, match="role: required"):
        _office(tmp_path, {"dev": {"harness": "claude"}})
    with pytest.raises(ManifestError, match="empty pattern"):
        _office(tmp_path, {"ops": {"harness": "any", "sessions": ["id:"]}})
    with pytest.raises(ManifestError, match="estate"):
        _office(tmp_path, {"ops": {"harness": "any"}}, estate="")


def test_an_any_desk_with_no_threads_is_not_a_warning(tmp_path):
    (tmp_path / "dev.md").write_text("# dev\n")
    o = _office(tmp_path, {"ops": {"harness": "any"}, "dev": {"harness": "claude", "role": "dev.md"}})
    assert [w for w in warnings(o) if "no threads" in w] == ["desk dev: no threads assigned"]


def test_desk_up_never_launches_an_any_desk(tmp_path):
    o = _office(tmp_path, {"ops": {"harness": "any"}})
    with pytest.raises(LaunchError, match="every desk is `harness: any`"):
        tmux_plan(o)
    (tmp_path / "dev.md").write_text("# dev\n")
    o = _office(tmp_path, {"ops": {"harness": "any"}, "dev": {"harness": "claude", "role": "dev.md"}})
    windows = [argv[argv.index("-n") + 1] for argv in tmux_plan(o) if "-n" in argv]
    assert windows == ["dev", "you"]


def test_summary_names_the_harnesses_an_any_desk_drew_on(tmp_path):
    o = _office(tmp_path, {"ops": {"harness": "any", "sessions": ["ops*"]}})
    root = str(tmp_path)
    start = dt.datetime.fromisoformat("2026-09-21T00:00:00+00:00")
    rows = meter.summarize(
        o,
        [_sess("cursor", "a", root, "ops"), _sess("claude", "b", root, "ops-2")],
        [],
        start,
        start + dt.timedelta(days=1),
    )
    (ops,) = [r for r in rows if r.desk == "ops"]
    assert ops.harness == "claude+cursor" and ops.sessions == 2 and ops.unmetered == 1


def test_cli_sessions_shows_desk_and_rule(tmp_path, monkeypatch, capsys):
    (tmp_path / "office.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "t",
                "gates": {"done": {"owner": ["ok"], "engineer": ["tests"]}},
                "desks": {"api": {"harness": "any", "sessions": ["api-*"]}, "web": {"harness": "any"}},
            }
        )
    )
    monkeypatch.chdir(tmp_path)
    now = dt.datetime.now(dt.UTC).isoformat()
    root = str(tmp_path)
    monkeypatch.setattr(
        meter,
        "read_all",
        lambda: [
            _sess("codex", "11111111-a", root, "api-auth", ts=now),
            _sess("cursor", "22222222-b", root, None, ts=now),
            _sess("claude", "33333333-c", "/elsewhere", "api-auth", ts=now),
        ],
    )
    assert load().estate_root == tmp_path.resolve()
    cli.main(["sessions", "--days", "1"])
    out = capsys.readouterr().out
    assert "api-auth" in out and "alias" in out and "11111111" in out
    assert "none" in out and "ambiguous" not in out
    assert "33333333" not in out  # outside the estate: not listed
    assert "2 sessions · 1 attributed · 1 unassigned (1 of them unnamed)" in out
