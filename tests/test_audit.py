"""Test cho src/audit.py — mock get_connection, khong cham database that."""

from contextlib import contextmanager
from uuid import uuid4

import pytest

from src import audit as audit_module
from src.audit import AuditEntry, record


class FakeCursor:
    def __init__(self, calls: list) -> None:  # type: ignore[type-arg]
        self._calls = calls

    def execute(self, sql: str, params: dict) -> None:  # type: ignore[type-arg]
        self._calls.append(params)

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *a: object) -> None:
        return None


class FakeConn:
    def __init__(self, calls: list) -> None:  # type: ignore[type-arg]
        self._calls = calls
        self.committed = False

    def cursor(self) -> FakeCursor:
        return FakeCursor(self._calls)

    def commit(self) -> None:
        self.committed = True


def make_entry(**overrides: object) -> AuditEntry:
    base = dict(
        request_id=uuid4(),
        user_id="emp_001",
        role="employee",
        department="sales",
        question="cau hoi mau",
        tool_used="docs",
        retrieved_doc_ids=["HR-001#0"],
        abstained=False,
        latency_ms=1234,
    )
    base.update(overrides)
    return AuditEntry(**base)  # type: ignore[arg-type]


def test_record_inserts_one_row(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []  # type: ignore[type-arg]
    fake_conn = FakeConn(calls)

    @contextmanager
    def fake_get_connection(*, read_only: bool = True):  # type: ignore[no-untyped-def]
        yield fake_conn

    monkeypatch.setattr(audit_module, "get_connection", fake_get_connection)

    record(make_entry())

    assert len(calls) == 1
    assert calls[0]["user_id"] == "emp_001"
    assert calls[0]["tool_used"] == "docs"
    assert fake_conn.committed is True


def test_record_does_not_raise_when_db_write_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Audit ghi lỗi KHÔNG được làm sập request đang trả lời người dùng — chỉ log."""

    @contextmanager
    def raising_get_connection(*, read_only: bool = True):  # type: ignore[no-untyped-def]
        raise ConnectionError("gia lap DB khong toi duoc")
        yield  # pragma: no cover - khong bao gio chay toi day

    monkeypatch.setattr(audit_module, "get_connection", raising_get_connection)

    record(make_entry())  # không raise, đúng hành vi mong đợi
