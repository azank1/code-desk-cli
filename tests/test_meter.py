import datetime as dt
import json

from coding_desks import meter
from coding_desks.meter import UNASSIGNED, Launch, Session, Turn


def _claude_file(root, slug, session, cwd, lines):
    d = root / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{session}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


def test_read_claude_dedupes_by_request_id(tmp_path):
    usage = {"input_tokens": 2, "cache_creation_input_tokens": 40, "cache_read_input_tokens": 8, "output_tokens": 5}
    line = lambda rid, ts: {"type": "assistant", "requestId": rid, "sessionId": "s1", "cwd": "/repo", "timestamp": ts,
                            "message": {"model": "m", "usage": usage}}
    _claude_file(tmp_path, "-repo", "s1", "/repo", [
        {"type": "custom-title", "customTitle": "dev", "sessionId": "s1"},
        line("r1", "2026-09-21T10:00:00.000Z"),
        line("r1", "2026-09-21T10:00:00.000Z"),   # same response, second content block
        {"type": "user", "timestamp": "2026-09-21T10:00:01.000Z"},
        line("r2", "2026-09-21T10:00:02.000Z"),
    ])
    (sess,) = meter.read_claude(tmp_path)
    assert sess.name == "dev" and sess.cwd == "/repo" and sess.harness == "claude"
    assert len(sess.turns) == 2
    assert sess.turns[0].input == 50 and sess.turns[0].cached == 8 and sess.turns[0].output == 5


def test_read_codex_uses_per_response_usage(tmp_path):
    d = tmp_path / "2026" / "09" / "21"
    d.mkdir(parents=True)
    rec = lambda i, inp, out: {"timestamp": f"2026-09-21T10:00:0{i}Z", "ordinal": i, "type": "token_usage_record",
                               "payload": {"thread_id": "t1", "usage": {"input_tokens": inp, "cached_input_tokens": 1, "cache_write_input_tokens": 0, "output_tokens": out},
                                           "turn_token_usage": {"input_tokens": 999, "output_tokens": 999}}}
    (d / "rollout-x.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"timestamp": "2026-09-21T09:59:59Z", "ordinal": 0, "type": "session_meta", "payload": {"cwd": "/repo/src"}},
        rec(1, 100, 10), rec(2, 120, 3), rec(2, 120, 3),
    ]) + "\n")
    (tmp_path.parent / "session_index.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"id": "t1", "thread_name": "first name", "updated_at": "2026-09-21T10:00:00Z"},
        {"id": "t1", "thread_name": "review", "updated_at": "2026-09-21T10:01:00Z"},
        {"id": "other", "thread_name": "x", "updated_at": "2026-09-21T10:01:00Z"},
    ]) + "\n")
    (sess,) = meter.read_codex(tmp_path)
    assert sess.harness == "codex" and sess.cwd == "/repo/src"
    assert [t.total for t in sess.turns] == [110, 123]
    assert sess.name == "review"  # last rename in session_index.jsonl wins


def _sess(harness, sid, cwd, name=None, ts="2026-09-21T10:00:00+00:00", tokens=100):
    t = dt.datetime.fromisoformat(ts)
    return Session(harness, sid, cwd, t, name, [Turn(t, None, tokens, 0, 10)])


def test_attribution_rules(office):
    root = str(office.root)
    sessions = [
        _sess("claude", "by-name", root, name="pm"),                       # rule 1
        _sess("claude", "by-launch", root),                                # rule 2
        _sess("claude", "unique-cwd", root + "/src"),                      # rule 3: only dev is claude@src
        _sess("codex", "codex-root", root),                                # rule 3: only review is codex@root
        _sess("claude", "ambiguous", root, ts="2026-09-21T15:00:00+00:00"),  # pm and dev? pm@root only -> pm
        _sess("claude", "elsewhere", "/somewhere/else"),
    ]
    launches = [Launch("dev", "claude", root, dt.datetime.fromisoformat("2026-09-21T09:55:00+00:00"))]
    who = meter.attribute(office, sessions, launches)
    assert who["by-name"] == "pm"
    assert who["by-launch"] == "dev"
    assert who["unique-cwd"] == "dev"
    assert who["codex-root"] == "review"
    assert who["ambiguous"] == "pm"
    assert who["elsewhere"] is None


def test_attribution_unassigned_when_two_desks_share_cwd(office):
    office.desks["dev"].cwd = "."  # now pm and dev both claim claude@root
    s = _sess("claude", "x", str(office.root))
    assert meter.attribute(office, [s], [])["x"] == UNASSIGNED


def test_summarize_window_and_budget(office, now):
    root = str(office.root)
    inside = _sess("claude", "in", root, name="pm", ts="2026-09-20T10:00:00+00:00", tokens=600)
    outside = _sess("claude", "out", root, name="pm", ts="2026-09-01T10:00:00+00:00", tokens=600)
    label, start, end = meter.window(office, now=now)
    assert label.startswith("sprint 1")
    rows = {r.desk: r for r in meter.summarize(office, [inside, outside], [], start, end)}
    assert rows["pm"].turns == 1 and rows["pm"].total == 610
    assert round(rows["pm"].pct) == 61
    assert rows["dev"].total == 0 and rows["review"].pct is None
    assert meter.projection(600, start, now) > 600


def test_window_last_days_when_no_start(office, now):
    office.cadence.start = None
    label, start, end = meter.window(office, now=now)
    assert label == "last 7 days" and (end - start).days == 7
