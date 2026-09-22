import pytest

from coding_desks.board import CLOSED, Board, BoardError


def test_reconcile_and_persist(office):
    b = Board.load(office)
    assert {r.thread for r in b.rows()} == {"a", "b", "c"}
    assert b.row("c").gate == "ready"
    b.save()
    assert office.board_path.is_file()
    b2 = Board.load(office)
    assert b2.row("a").gate == "scope"


def test_handshake_advances_when_both_columns_filled(office):
    b = Board.load(office)
    r, adv = b.deliver("a", "engineer", "estimate", note="2d")
    assert not adv and r.owes == ["engineer", "owner"]
    r, adv = b.deliver("a", "engineer", "risks")
    assert not adv and r.owes == ["owner"] and r.status == "owner owes"
    b.deliver("a", "owner", "scope")
    r, adv = b.deliver("a", "owner", "priority")
    assert adv and r.gate == "ready"
    assert b.row("a").engineer_owes == ["tests-green", "evidence"]


def test_engineer_first_refuses_verdict_on_no_evidence(office):
    b = Board.load(office)
    for hat, item in [("engineer", "estimate"), ("engineer", "risks"), ("owner", "scope"), ("owner", "priority")]:
        b.deliver("a", hat, item)
    assert b.row("a").gate == "ready"
    with pytest.raises(BoardError, match="engineer-first"):
        b.deliver("a", "owner", "verdict")
    b.deliver("a", "engineer", "tests-green", evidence="pytest: 12 passed")
    with pytest.raises(BoardError, match="engineer-first"):
        b.deliver("a", "owner", "verdict")
    b.deliver("a", "engineer", "evidence", evidence="abc123")
    r, adv = b.deliver("a", "owner", "verdict", note="ship")
    assert adv and r.gate == "shipped"


def test_thread_gate_override_closes(office):
    b = Board.load(office)
    b.deliver("c", "engineer", "tests-green")
    b.deliver("c", "engineer", "evidence")
    r, adv = b.deliver("c", "owner", "verdict")
    assert adv and r.gate == CLOSED and r.closed
    with pytest.raises(BoardError, match="closed"):
        b.deliver("c", "owner", "verdict")


def test_rejects_wrong_item_and_double_file(office):
    b = Board.load(office)
    with pytest.raises(BoardError, match="does not deliver"):
        b.deliver("a", "owner", "evidence")
    b.deliver("a", "owner", "scope")
    with pytest.raises(BoardError, match="already filed"):
        b.deliver("a", "owner", "scope")
    with pytest.raises(BoardError, match="unknown thread"):
        b.deliver("zzz", "owner", "scope")


def test_inboxes_split_by_hat(office):
    b = Board.load(office)
    b.deliver("a", "engineer", "estimate")
    b.deliver("a", "engineer", "risks")  # a: owner owes
    b.deliver("b", "owner", "scope")
    b.deliver("b", "owner", "priority")  # b: engineer owes
    # c: ready, engineer-first -> owner blocked, engineer owes
    assert [r.thread for r in b.inbox("owner")] == ["a"]
    assert [r.thread for r in b.inbox("engineer")] == ["b", "c"]
    assert [r.thread for r in b.waiting_on_other("owner")] == ["b", "c"]
    assert [r.thread for r in b.waiting_on_other("engineer")] == ["a"]
