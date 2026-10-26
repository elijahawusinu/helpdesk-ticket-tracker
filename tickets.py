"""
helpdesk-ticket-tracker
-----------------------
A lightweight command-line help desk ticketing system backed by SQLite.

Modelled on the Tier 1/2 support workflow used in healthcare and
accounting environments: open a ticket, assign it, add work notes,
resolve it, and report on the queue.

Usage examples:
    python tickets.py create "Printer offline in Suite 204" --user jsmith --priority high
    python tickets.py list --status open
    python tickets.py assign 3 --tech elijah
    python tickets.py note 3 "Reseated network cable, printer back online"
    python tickets.py close 3 --resolution "Loose Ethernet cable"
    python tickets.py report
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

DEFAULT_DB = Path("tickets.db")

PRIORITIES = ("low", "medium", "high", "critical")
STATUSES = ("open", "in_progress", "resolved", "closed")

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    requester   TEXT    NOT NULL,
    category    TEXT    NOT NULL DEFAULT 'general',
    priority    TEXT    NOT NULL DEFAULT 'medium',
    status      TEXT    NOT NULL DEFAULT 'open',
    assignee    TEXT,
    resolution  TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL,
    closed_at   TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id   INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    author      TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL
);
"""


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


@dataclass
class Ticket:
    id: int
    title: str
    requester: str
    category: str
    priority: str
    status: str
    assignee: str | None
    resolution: str | None
    created_at: str
    updated_at: str
    closed_at: str | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Ticket":
        return cls(**{k: row[k] for k in row.keys()})


class TicketStore:
    """All database operations live here so the CLI stays thin and testable."""

    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)

    # -- create / read -------------------------------------------------

    def create(
        self,
        title: str,
        requester: str,
        category: str = "general",
        priority: str = "medium",
    ) -> Ticket:
        if priority not in PRIORITIES:
            raise ValueError(f"priority must be one of {PRIORITIES}")
        if not title.strip():
            raise ValueError("title cannot be empty")
        ts = _now()
        cur = self.conn.execute(
            "INSERT INTO tickets (title, requester, category, priority, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (title.strip(), requester, category, priority, ts, ts),
        )
        self.conn.commit()
        return self.get(cur.lastrowid)

    def get(self, ticket_id: int) -> Ticket:
        row = self.conn.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)).fetchone()
        if row is None:
            raise LookupError(f"ticket #{ticket_id} not found")
        return Ticket.from_row(row)

    def list(
        self,
        status: str | None = None,
        assignee: str | None = None,
        priority: str | None = None,
    ) -> list[Ticket]:
        clauses, params = [], []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if assignee:
            clauses.append("assignee = ?")
            params.append(assignee)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        # critical first, then oldest first
        order = (
            "ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, created_at"
        )
        rows = self.conn.execute(f"SELECT * FROM tickets {where} {order}", params).fetchall()
        return [Ticket.from_row(r) for r in rows]

    # -- update ---------------------------------------------------------

    def assign(self, ticket_id: int, tech: str) -> Ticket:
        t = self.get(ticket_id)
        if t.status in ("resolved", "closed"):
            raise ValueError(f"ticket #{ticket_id} is {t.status}; reopen it first")
        self.conn.execute(
            "UPDATE tickets SET assignee = ?, status = 'in_progress', updated_at = ? WHERE id = ?",
            (tech, _now(), ticket_id),
        )
        self.conn.commit()
        return self.get(ticket_id)

    def add_note(self, ticket_id: int, body: str, author: str = "tech") -> None:
        self.get(ticket_id)  # raises if missing
        ts = _now()
        self.conn.execute(
            "INSERT INTO notes (ticket_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (ticket_id, author, body, ts),
        )
        self.conn.execute("UPDATE tickets SET updated_at = ? WHERE id = ?", (ts, ticket_id))
        self.conn.commit()

    def notes(self, ticket_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM notes WHERE ticket_id = ? ORDER BY created_at", (ticket_id,)
        ).fetchall()

    def close(self, ticket_id: int, resolution: str) -> Ticket:
        if not resolution.strip():
            raise ValueError("a resolution is required to close a ticket")
        self.get(ticket_id)
        ts = _now()
        self.conn.execute(
            "UPDATE tickets SET status = 'closed', resolution = ?, updated_at = ?, closed_at = ?"
            " WHERE id = ?",
            (resolution.strip(), ts, ts, ticket_id),
        )
        self.conn.commit()
        return self.get(ticket_id)

    def reopen(self, ticket_id: int) -> Ticket:
        self.get(ticket_id)
        self.conn.execute(
            "UPDATE tickets SET status = 'open', closed_at = NULL, updated_at = ? WHERE id = ?",
            (_now(), ticket_id),
        )
        self.conn.commit()
        return self.get(ticket_id)

    # -- reporting ------------------------------------------------------

    def report(self) -> dict:
        counts = {
            s: self.conn.execute("SELECT COUNT(*) FROM tickets WHERE status = ?", (s,)).fetchone()[0]
            for s in STATUSES
        }
        by_priority = {
            p: self.conn.execute(
                "SELECT COUNT(*) FROM tickets WHERE priority = ? AND status NOT IN ('resolved','closed')",
                (p,),
            ).fetchone()[0]
            for p in PRIORITIES
        }
        by_tech = self.conn.execute(
            "SELECT COALESCE(assignee, '(unassigned)') AS tech, COUNT(*) AS n "
            "FROM tickets WHERE status NOT IN ('resolved','closed') GROUP BY tech ORDER BY n DESC"
        ).fetchall()
        return {
            "by_status": counts,
            "open_by_priority": by_priority,
            "open_by_tech": {r["tech"]: r["n"] for r in by_tech},
            "total": sum(counts.values()),
        }


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def _print_table(tickets: Iterable[Ticket]) -> None:
    tickets = list(tickets)
    if not tickets:
        print("No tickets match.")
        return
    print(f"{'ID':>4}  {'PRI':<8} {'STATUS':<12} {'ASSIGNEE':<12} {'REQUESTER':<12} TITLE")
    print("-" * 78)
    for t in tickets:
        print(
            f"{t.id:>4}  {t.priority:<8} {t.status:<12} {(t.assignee or '-'):<12} "
            f"{t.requester:<12} {t.title}"
        )


def _print_ticket(store: TicketStore, t: Ticket) -> None:
    print(f"Ticket #{t.id}: {t.title}")
    print(f"  Requester : {t.requester}")
    print(f"  Category  : {t.category}")
    print(f"  Priority  : {t.priority}")
    print(f"  Status    : {t.status}")
    print(f"  Assignee  : {t.assignee or '-'}")
    print(f"  Created   : {t.created_at}")
    print(f"  Updated   : {t.updated_at}")
    if t.closed_at:
        print(f"  Closed    : {t.closed_at}")
        print(f"  Resolution: {t.resolution}")
    notes = store.notes(t.id)
    if notes:
        print("  Work notes:")
        for n in notes:
            print(f"    [{n['created_at']}] {n['author']}: {n['body']}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Help desk ticket tracker")
    p.add_argument("--db", default=str(DEFAULT_DB), help="path to SQLite database file")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="open a new ticket")
    c.add_argument("title")
    c.add_argument("--user", required=True, help="person reporting the issue")
    c.add_argument("--category", default="general",
                   help="e.g. hardware, printer, network, account, software")
    c.add_argument("--priority", default="medium", choices=PRIORITIES)

    l = sub.add_parser("list", help="list tickets")
    l.add_argument("--status", choices=STATUSES)
    l.add_argument("--tech", dest="assignee")
    l.add_argument("--priority", choices=PRIORITIES)

    s = sub.add_parser("show", help="show one ticket with its notes")
    s.add_argument("id", type=int)

    a = sub.add_parser("assign", help="assign a ticket to a technician")
    a.add_argument("id", type=int)
    a.add_argument("--tech", required=True)

    n = sub.add_parser("note", help="add a work note")
    n.add_argument("id", type=int)
    n.add_argument("body")
    n.add_argument("--author", default="tech")

    cl = sub.add_parser("close", help="close a ticket with a resolution")
    cl.add_argument("id", type=int)
    cl.add_argument("--resolution", required=True)

    r = sub.add_parser("reopen", help="reopen a closed ticket")
    r.add_argument("id", type=int)

    sub.add_parser("report", help="queue summary")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = TicketStore(args.db)
    try:
        if args.cmd == "create":
            t = store.create(args.title, args.user, args.category, args.priority)
            print(f"Created ticket #{t.id} ({t.priority}): {t.title}")
        elif args.cmd == "list":
            _print_table(store.list(args.status, args.assignee, args.priority))
        elif args.cmd == "show":
            _print_ticket(store, store.get(args.id))
        elif args.cmd == "assign":
            t = store.assign(args.id, args.tech)
            print(f"Ticket #{t.id} assigned to {t.assignee} (status: {t.status})")
        elif args.cmd == "note":
            store.add_note(args.id, args.body, args.author)
            print(f"Note added to ticket #{args.id}")
        elif args.cmd == "close":
            t = store.close(args.id, args.resolution)
            print(f"Ticket #{t.id} closed: {t.resolution}")
        elif args.cmd == "reopen":
            t = store.reopen(args.id)
            print(f"Ticket #{t.id} reopened")
        elif args.cmd == "report":
            rep = store.report()
            print(f"Total tickets: {rep['total']}")
            print("By status     :", ", ".join(f"{k}={v}" for k, v in rep["by_status"].items()))
            print("Open by prio  :", ", ".join(f"{k}={v}" for k, v in rep["open_by_priority"].items()))
            print("Open by tech  :", ", ".join(f"{k}={v}" for k, v in rep["open_by_tech"].items()) or "none")
    except (ValueError, LookupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
