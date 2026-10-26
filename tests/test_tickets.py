import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tickets import TicketStore, main  # noqa: E402


@pytest.fixture
def store(tmp_path):
    return TicketStore(tmp_path / "test.db")


def test_create_and_get(store):
    t = store.create("Printer offline", "jsmith", "printer", "high")
    assert t.id == 1
    assert t.status == "open"
    assert t.priority == "high"
    assert store.get(1).title == "Printer offline"


def test_create_rejects_bad_priority(store):
    with pytest.raises(ValueError):
        store.create("x", "u", priority="urgent")


def test_create_rejects_empty_title(store):
    with pytest.raises(ValueError):
        store.create("   ", "u")


def test_assign_moves_to_in_progress(store):
    t = store.create("VPN not connecting", "mlee")
    t = store.assign(t.id, "elijah")
    assert t.assignee == "elijah"
    assert t.status == "in_progress"


def test_close_requires_resolution(store):
    t = store.create("Account locked", "kbrown", "account")
    with pytest.raises(ValueError):
        store.close(t.id, "  ")
    t = store.close(t.id, "Unlocked in Active Directory")
    assert t.status == "closed"
    assert t.closed_at is not None
    assert t.resolution == "Unlocked in Active Directory"


def test_cannot_assign_closed_ticket(store):
    t = store.create("Old issue", "u")
    store.close(t.id, "done")
    with pytest.raises(ValueError):
        store.assign(t.id, "elijah")


def test_reopen(store):
    t = store.create("Flaky Wi-Fi", "u")
    store.close(t.id, "Rebooted AP")
    t = store.reopen(t.id)
    assert t.status == "open"
    assert t.closed_at is None


def test_notes_attach_to_ticket(store):
    t = store.create("Slow laptop", "u")
    store.add_note(t.id, "Ran disk cleanup", author="elijah")
    store.add_note(t.id, "Replaced HDD with SSD", author="elijah")
    notes = store.notes(t.id)
    assert [n["body"] for n in notes] == ["Ran disk cleanup", "Replaced HDD with SSD"]


def test_missing_ticket_raises(store):
    with pytest.raises(LookupError):
        store.get(999)


def test_list_orders_by_priority(store):
    store.create("low one", "u", priority="low")
    store.create("critical one", "u", priority="critical")
    store.create("medium one", "u", priority="medium")
    titles = [t.title for t in store.list()]
    assert titles == ["critical one", "medium one", "low one"]


def test_list_filters(store):
    store.create("a", "u", priority="high")
    b = store.create("b", "u", priority="low")
    store.assign(b.id, "elijah")
    assert len(store.list(status="open")) == 1
    assert len(store.list(assignee="elijah")) == 1
    assert len(store.list(priority="high")) == 1


def test_report_counts(store):
    a = store.create("a", "u", priority="high")
    store.create("b", "u")
    store.close(a.id, "fixed")
    rep = store.report()
    assert rep["total"] == 2
    assert rep["by_status"]["closed"] == 1
    assert rep["by_status"]["open"] == 1
    assert rep["open_by_priority"]["medium"] == 1
    assert rep["open_by_tech"]["(unassigned)"] == 1


def test_cli_end_to_end(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "create", "Printer jam", "--user", "jsmith", "--priority", "high"]) == 0
    assert main(["--db", db, "assign", "1", "--tech", "elijah"]) == 0
    assert main(["--db", db, "note", "1", "Cleared jam"]) == 0
    assert main(["--db", db, "close", "1", "--resolution", "Cleared paper path"]) == 0
    assert main(["--db", db, "show", "1"]) == 0
    out = capsys.readouterr().out
    assert "Cleared paper path" in out
    assert "Cleared jam" in out


def test_cli_error_returns_nonzero(tmp_path, capsys):
    db = str(tmp_path / "cli.db")
    assert main(["--db", db, "show", "42"]) == 1
    assert "not found" in capsys.readouterr().err
