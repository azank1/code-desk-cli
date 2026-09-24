import datetime as dt

import pytest
import yaml

from coding_desks import adopt, cli, meter
from coding_desks.manifest import load
from coding_desks.meter import UNASSIGNED, Session, Turn


def _sess(harness, sid, cwd, name=None, turns=1, ts="2026-09-21T10:00:00+00:00"):
    t = dt.datetime.fromisoformat(ts)
    return Session(harness, sid, str(cwd), t, name, [Turn(t, None, 10, 0, 1) for _ in range(turns)])


def test_tokens_drop_the_dirs_own_words_and_copy_suffixes():
    assert adopt.tokens("shop-API-auth (2)", {"shop"}) == ["api", "auth"]
    assert adopt.tokens("shop", {"shop"}) == ["shop"]  # never reduced to nothing


def test_cluster_by_first_token_or_same_token_set():
    got = adopt.cluster(
        [
            "api-auth",
            "API-webhooks",
            "shop-ops-nightly",
            "nightly-ops",  # same token set as shop-ops-nightly once "shop" is dropped
            "search",
            "searching",  # a different word: never merged by guessing
            "api-auth",
        ],
        {"shop"},
    )
    assert got == {
        "api": ["api-auth", "API-webhooks"],
        "nightly-ops": ["nightly-ops", "shop-ops-nightly"],
        "search": ["search"],
        "searching": ["searching"],
    }


def test_propose_counts_named_unnamed_and_outside(tmp_path):
    shop = tmp_path / "shop"
    (shop / "sub").mkdir(parents=True)
    p = adopt.propose(
        shop,
        [
            _sess("claude", "a", shop, "api-auth", turns=5),
            _sess("codex", "b", shop / "sub", "api-webhooks", turns=3),
            _sess("cursor", "c", shop, None),
            _sess("claude", "d", tmp_path / "elsewhere", "api-auth"),
            _sess("cursor", "e", "", "no-cwd"),
        ],
    )
    assert p.desks == {"api": ["api-auth", "api-webhooks"]}
    assert [s.id for s in p.by_desk["api"]] == ["a", "b"]
    assert [s.id for s in p.unnamed] == ["c"] and p.outside == 2


def test_out_dir_may_not_be_inside_the_estate(tmp_path):
    with pytest.raises(adopt.AdoptError, match="never writes into"):
        adopt.check_out_dir(tmp_path, tmp_path / ".office")
    with pytest.raises(adopt.AdoptError):
        adopt.check_out_dir(tmp_path, tmp_path)
    adopt.check_out_dir(tmp_path / "repo", tmp_path / "overlay")  # a sibling is fine


def _world(tmp_path, monkeypatch):
    shop, out = tmp_path / "shop", tmp_path / "overlay"
    shop.mkdir()
    sessions = [
        _sess("claude", "s1", shop, "api-auth", turns=40),
        _sess("codex", "s2", shop, "api-webhooks", turns=10),
        _sess("cursor", "s3", shop, "web-checkout", turns=6),
        _sess("cursor", "s4", shop, "fix [flaky] test", turns=2),
        _sess("cursor", "s5", shop, None, turns=1),
    ]
    monkeypatch.setattr(meter, "read_all", lambda: sessions)
    return shop, out, sessions


def test_cli_adopt_writes_an_overlay_that_meters_the_estate(tmp_path, monkeypatch, capsys):
    shop, out, sessions = _world(tmp_path, monkeypatch)
    before = sorted(p.name for p in shop.iterdir())
    cli.main(["adopt", str(shop), "--out", str(out)])
    text = capsys.readouterr().out
    assert "5 sessions · 3 desks proposed from 4 named sessions" in text
    assert "1 unnamed (cursor 1)" in text
    assert sorted(p.name for p in shop.iterdir()) == before  # nothing written into the estate

    monkeypatch.chdir(out)
    office = load()
    assert office.estate_root == shop.resolve()
    assert set(office.desks) == {"api", "web-checkout", "fix-flaky-test"}
    assert office.desks["fix-flaky-test"].sessions == ["fix [[]flaky] test"]
    who = meter.explain(office, sessions, [])
    assert {k: v.desk for k, v in who.items()} == {
        "s1": "api",
        "s2": "api",
        "s3": "web-checkout",
        "s4": "fix-flaky-test",
        "s5": UNASSIGNED,
    }

    rows = yaml.safe_load((out / "sessions.yaml").read_text())["sessions"]
    assert [(r["id"], r["desk"]) for r in rows] == [
        ("s1", "api"),
        ("s2", "api"),
        ("s3", "web-checkout"),
        ("s4", "fix-flaky-test"),
        ("s5", ""),
    ]


def test_cli_adopt_refuses_to_overwrite_or_write_inside(tmp_path, monkeypatch):
    shop, out, _ = _world(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        cli.main(["adopt", str(shop), "--out", str(shop / "overlay")])
    assert not (shop / "overlay").exists()
    cli.main(["adopt", str(shop), "--out", str(out)])
    with pytest.raises(SystemExit):
        cli.main(["adopt", str(shop), "--out", str(out)])
    cli.main(["adopt", str(shop), "--out", str(out), "--force"])


def test_sessions_against_weights_by_turns_and_lists_every_disagreement(tmp_path, monkeypatch, capsys):
    shop, out, _ = _world(tmp_path, monkeypatch)
    cli.main(["adopt", str(shop), "--out", str(out)])
    truth = out / "sessions.yaml"
    data = yaml.safe_load(truth.read_text())
    for r in data["sessions"]:
        if r["id"] == "s2":
            r["desk"] = "integrations"  # the person says the webhooks session was not api work
        if r["id"] == "s4":
            r["desk"] = ""  # and does not know this one
    data["sessions"] = [r for r in data["sessions"] if r["id"] != "s3"]  # nor list this one
    truth.write_text(yaml.safe_dump(data))
    monkeypatch.chdir(out)
    capsys.readouterr()
    cli.main(["sessions", "--against", "sessions.yaml"])
    text = capsys.readouterr().out
    # labelled: s1 (40, agrees), s2 (10, disagrees), s5 (unassigned, 1 turn: labelled "" -> unlabelled)
    assert "40/50 turns agree with sessions.yaml (80.0%)" in text
    assert "integrations" in text and "api-webhooks" in text
    assert "1 sessions disagree · 2 in the list with no desk · 1 under the estate but not in the list" in text


def test_agreement_counts_an_unassigned_session_as_a_disagreement(tmp_path):
    shop = tmp_path / "shop"
    shop.mkdir()
    p = adopt.propose(shop, [_sess("claude", "x", shop, "notes"), _sess("codex", "z", shop, "billing")])
    (tmp_path / "o").mkdir()
    (tmp_path / "o" / "office.yaml").write_text(adopt.office_yaml(p, tmp_path / "o", "o"))
    o = load(tmp_path / "o")
    ag = adopt.agreement(o, [_sess("claude", "y", shop, "other", turns=3)], [], {"y": "notes"})
    assert ag.pct == 0.0 and ag.disagree[0][2] == UNASSIGNED  # two desks tie on the cwd rule
