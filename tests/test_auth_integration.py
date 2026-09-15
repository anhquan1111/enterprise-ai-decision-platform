"""Test tich hop that: authenticate() doi voi PostgreSQL that (khong mock fetch_one).

Khac test_auth.py (mock hoan toan) - o day xac nhan ca vong doi that: sinh key, bam
hash, ghi vao DB that, roi authenticate() bang key goc phai tim dung lai nhan vien.
Dung mot nhan vien TAM THOI (khong dung emp_001..008 that su) de khong lam hong key
that da cap boi scripts/issue_api_keys.py.
"""

import hashlib
import secrets
from collections.abc import Iterator

import pytest

from src.auth import AuthenticationError, authenticate
from src.db import get_connection

pytestmark = pytest.mark.integration

_TEST_EMPLOYEE_ID = "test_auth_tmp_001"


@pytest.fixture
def temp_employee_with_key() -> Iterator[tuple[str, str]]:
    """Tạo một nhân viên tạm với API key thật, xoá lại sau khi test xong — không
    đụng tới 8 nhân viên seed thật (giai đoạn tầng dữ liệu) hay key đã cấp cho họ."""
    api_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()

    with get_connection(read_only=False) as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO employees (employee_id, full_name, department, role, api_key_hash)
            VALUES (%(id)s, 'Test Tam Thoi', 'sales', 'manager', %(hash)s)
            ON CONFLICT (employee_id) DO UPDATE SET api_key_hash = EXCLUDED.api_key_hash
            """,
            {"id": _TEST_EMPLOYEE_ID, "hash": key_hash},
        )
        conn.commit()

    yield _TEST_EMPLOYEE_ID, api_key

    with get_connection(read_only=False) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM employees WHERE employee_id = %(id)s", {"id": _TEST_EMPLOYEE_ID})
        conn.commit()


def test_authenticate_finds_employee_by_real_key_round_trip(
    temp_employee_with_key: tuple[str, str],
) -> None:
    employee_id, api_key = temp_employee_with_key

    employee = authenticate(f"Bearer {api_key}")

    assert employee.employee_id == employee_id
    assert employee.role == "manager"
    assert employee.department == "sales"


def test_authenticate_rejects_a_key_that_was_never_issued(
    temp_employee_with_key: tuple[str, str],
) -> None:
    with pytest.raises(AuthenticationError):
        authenticate("Bearer mot-key-hoan-toan-khac-chua-tung-duoc-cap")


def test_ask_end_to_end_blocks_forged_role_with_real_key_and_real_db(
    temp_employee_with_key: tuple[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tái hiện đúng lỗ hổng đã đo bằng curl thật ở vault ngày 26 — lần này thành một
    test tự động, qua /ask thật (TestClient, không cần start uvicorn riêng), dùng
    DB thật, chỉ mock run_agent để không tốn quota Gemini (không phải điều cần xác
    nhận ở đây — điều cần xác nhận là tầng xác thực/RBAC chặn đúng)."""
    from fastapi.testclient import TestClient

    from src import api

    _employee_id, api_key = temp_employee_with_key
    monkeypatch.setattr(
        api,
        "run_agent",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("run_agent KHONG duoc goi - phai bi chan o tang xac thuc/RBAC truoc do")
        ),
    )

    client = TestClient(api.app)
    response = client.post(
        "/ask",
        json={
            "user_id": "khach_la_hoac_ke_gia_mao",
            "role": "executive",  # tự khai — thật sự chỉ là 'manager'/'sales'
            "department": "finance",
            "question": "Khoan chi tren 50 trieu dong thi ai duyet?",
        },
        headers={"Authorization": f"Bearer {api_key}"},
    )

    assert response.status_code == 403
