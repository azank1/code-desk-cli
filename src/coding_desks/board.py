"""The board: per-thread gate state and the two-sided handshake."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import yaml

from .manifest import HATS, Office

CLOSED = "closed"


class BoardError(Exception):
    pass


@dataclass
class Delivery:
    note: str | None = None
    evidence: str | None = None
    at: str | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class ThreadState:
    gate: str  # current gate name, or CLOSED
    delivered: dict[str, dict[str, dict[str, Delivery]]] = field(default_factory=dict)
    # delivered[gate][hat][item] = Delivery

    def filed(self, gate: str, hat: str) -> dict[str, Delivery]:
        return self.delivered.get(gate, {}).get(hat, {})


@dataclass
class SyncRow:
    thread: str
    desk: str
    gate: str
    owner_filed: list[str]
    owner_owes: list[str]
    engineer_filed: list[str]
    engineer_owes: list[str]
    blocked_hat: str | None  # hat that may not file yet because of `order`

    @property
    def closed(self) -> bool:
        return self.gate == CLOSED

    @property
    def owes(self) -> list[str]:
        """Hats that owe something at this gate, in the order they can act."""
        hats = []
        if self.engineer_owes and self.blocked_hat != "engineer":
            hats.append("engineer")
        if self.owner_owes and self.blocked_hat != "owner":
            hats.append("owner")
        return hats

    @property
    def status(self) -> str:
        if self.closed:
            return "closed"
        if not self.owes:
            return "in sync"
        return " & ".join(f"{h} owes" for h in self.owes)


class Board:
    def __init__(self, office: Office, threads: dict[str, ThreadState] | None = None):
        self.office = office
        self.threads: dict[str, ThreadState] = threads or {}

    # -- persistence -----------------------------------------------------

    @classmethod
    def load(cls, office: Office) -> Board:
        path = office.board_path
        data = {}
        if path.is_file():
            data = yaml.safe_load(path.read_text()) or {}
        threads = {}
        for name, t in (data.get("threads") or {}).items():
            delivered = {}
            for gate, hats in (t.get("delivered") or {}).items():
                delivered[gate] = {}
                for hat, items in (hats or {}).items():
                    delivered[gate][hat] = {item: Delivery(**(d or {})) for item, d in (items or {}).items()}
            threads[name] = ThreadState(gate=t.get("gate", CLOSED), delivered=delivered)
        b = cls(office, threads)
        b.reconcile()
        return b

    def to_dict(self) -> dict:
        out = {}
        for name, t in self.threads.items():
            entry = {"gate": t.gate}
            if t.delivered:
                entry["delivered"] = {
                    g: {h: {i: d.to_dict() for i, d in items.items()} for h, items in hats.items()}
                    for g, hats in t.delivered.items()
                }
            out[name] = entry
        return {"threads": out}

    def save(self) -> None:
        self.office.state_dir.mkdir(parents=True, exist_ok=True)
        self.office.board_path.write_text(
            "# .office/board.yaml — state, written by `desk deliver`. Commit it.\n"
            + yaml.safe_dump(self.to_dict(), sort_keys=False)
        )

    def reconcile(self) -> list[str]:
        """Add threads the manifest has but the board lacks. Returns names added."""
        added = []
        for name in self.office.threads:
            if name not in self.threads:
                gates = self.office.thread_gates(name)
                self.threads[name] = ThreadState(gate=gates[0] if gates else CLOSED)
                added.append(name)
        return added

    # -- handshake -------------------------------------------------------

    def _state(self, thread: str) -> ThreadState:
        if thread not in self.office.threads:
            raise BoardError(f"unknown thread {thread!r} (not in office.yaml)")
        return self.threads[thread]

    def row(self, thread: str) -> SyncRow:
        st = self._state(thread)
        desk = self.office.threads[thread].desk
        if st.gate == CLOSED:
            return SyncRow(thread, desk, CLOSED, [], [], [], [], None)
        gate = self.office.gates[st.gate]
        o_filed = [i for i in gate.owner if i in st.filed(st.gate, "owner")]
        e_filed = [i for i in gate.engineer if i in st.filed(st.gate, "engineer")]
        o_owes = [i for i in gate.owner if i not in o_filed]
        e_owes = [i for i in gate.engineer if i not in e_filed]
        blocked = None
        if gate.order == "engineer-first" and e_owes:
            blocked = "owner"
        elif gate.order == "owner-first" and o_owes:
            blocked = "engineer"
        return SyncRow(thread, desk, st.gate, o_filed, o_owes, e_filed, e_owes, blocked)

    def rows(self) -> list[SyncRow]:
        return [self.row(t) for t in self.office.threads]

    def deliver(
        self, thread: str, hat: str, item: str, note: str | None = None, evidence: str | None = None
    ) -> tuple[SyncRow, bool]:
        """File one deliverable. Returns (row after, advanced?)."""
        if hat not in HATS:
            raise BoardError(f"hat must be one of {HATS}")
        st = self._state(thread)
        if st.gate == CLOSED:
            raise BoardError(f"{thread} is closed")
        row = self.row(thread)
        gate = self.office.gates[st.gate]
        if item not in gate.items(hat):
            raise BoardError(f"{hat} does not deliver {item!r} at gate {st.gate}; expected one of {gate.items(hat)}")
        if row.blocked_hat == hat:
            other = "engineer" if hat == "owner" else "owner"
            owes = row.engineer_owes if other == "engineer" else row.owner_owes
            raise BoardError(f"gate {st.gate} is {gate.order}: {hat} may not file until {other} files {owes}")
        if item in st.filed(st.gate, hat):
            raise BoardError(f"{hat}:{item} already filed at {st.gate} for {thread}")
        st.delivered.setdefault(st.gate, {}).setdefault(hat, {})[item] = Delivery(
            note=note, evidence=evidence, at=dt.datetime.now().astimezone().isoformat(timespec="seconds")
        )
        row = self.row(thread)
        advanced = False
        if not row.owner_owes and not row.engineer_owes:
            gates = self.office.thread_gates(thread)
            i = gates.index(st.gate)
            st.gate = gates[i + 1] if i + 1 < len(gates) else CLOSED
            advanced = True
            row = self.row(thread)
        return row, advanced

    def inbox(self, hat: str) -> list[SyncRow]:
        if hat not in HATS:
            raise BoardError(f"hat must be one of {HATS}")
        return [r for r in self.rows() if hat in r.owes]

    def waiting_on_other(self, hat: str) -> list[SyncRow]:
        """Rows where this hat is done or blocked and the other hat owes."""
        other = "engineer" if hat == "owner" else "owner"
        return [r for r in self.rows() if not r.closed and hat not in r.owes and other in r.owes]
