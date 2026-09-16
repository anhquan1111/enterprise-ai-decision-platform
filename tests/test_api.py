"""Tests for /ask — mocked agent loop, xác thực và audit (agent routing/xác thực &
độ tin cậy), không chạm mạng hay database.

/ask gọi agent 2 tool (SQL + docs), router Gemini, xác thực bằng API key, ghi audit
log, và PostgreSQL thật khi chạy production, nhưng một unit test không được phụ
thuộc dịch vụ ngoài: chậm, tốn quota, và kết quả có thể đổi giữa hai lần chạy vì
model không xác định. Test ở đây thay ``run_agent``/``authenticate``/``record_audit``
bằng giá trị giả — hành vi bên trong từng phần đã có bộ test riêng
(test_agent_loop.py, test_agent_router.py, test_agent_tools.py, test_auth.py,
test_audit.py).

Test end-to-end với API và database thật nằm trong ``test_ask_live.py``, đánh dấu
``live_llm``, không chạy mặc định.
"""

import pytest
from fastapi.testclient import TestClient

from src import api
from src.agent.loop import AgentAnswer
from src.auth import AuthenticatedEmployee, AuthenticationError
from src.config import get_settings
from src.generation import Citation

client = TestClient(api.app)

VALID_REQUEST = {
    "user_id": "emp_042",
    "role": "employee",
    "department": "engineering",
    "question": "Neu mot ban release bi loi thi phai lam gi?",
}
AUTH_HEADERS = {"Authorization": "Bearer fake-test-key"}


def mock_authenticated_as(
    monkeypatch: pytest.MonkeyPatch,
    *,
    employee_id: str = "emp_042",
    role: str = "employee",
    department: str = "engineering",
) -> None:
    """Giả lập một request đã qua xác thực thật, khớp đúng role/department trong
    VALID_REQUEST — mô phỏng ca bình thường, không phải ca bị chặn."""
    employee = AuthenticatedEmployee(employee_id=employee_id, role=role, department=department)
    monkeypatch.setattr(api, "authenticate", lambda header: employee)
    monkeypatch.setattr(api, "record_audit", lambda entry: None)


def test_health_is_liveness_only() -> None:
    """/health phải trả lời mà không chạm database."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "enterprise-ai-decision-platform"


def test_metrics_endpoint_exposes_prometheus_format() -> None:
    """/metrics (giai đoạn xác thực & độ tin cậy) phải trả về đúng content-type
    Prometheus mong đợi."""
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]


def test_auth_token_returns_jwt_for_valid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-028 bước 2/3: API key hợp lệ đổi được một JWT — không mock issue_token,
    để hàm ký thật chạy (test_jwt_auth.py đã kiểm riêng cơ chế ký/xác minh). Tự đặt
    JWT_SECRET_KEY qua monkeypatch, không dựa vào .env của máy đang chạy test
    (isolate_settings_from_local_env chỉ tắt đọc file .env, không xoá biến môi
    trường đã export sẵn trong shell)."""
    mock_authenticated_as(monkeypatch)
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-du-dai-de-qua-canh-bao-do-dai")
    get_settings.cache_clear()

    response = client.post("/auth/token", headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["access_token"], str) and body["access_token"]
    assert body["token_type"] == "bearer"
    assert isinstance(body["expires_in"], int) and body["expires_in"] > 0


def test_auth_token_returns_401_without_authorization_header() -> None:
    """Không mock authenticate — để hàm thật chạy, khớp đúng hành vi /ask."""
    response = client.post("/auth/token")

    assert response.status_code == 401


def test_auth_token_returns_401_for_invalid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_auth_error(header: str | None) -> None:
        raise AuthenticationError("khong khop")

    monkeypatch.setattr(api, "authenticate", raise_auth_error)

    response = client.post("/auth/token", headers=AUTH_HEADERS)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("role", "employee_id", "department"),
    [
        ("employee", "demo_ui_frontend", "sales"),
        ("manager", "demo_ui_manager", "finance"),
        ("executive", "demo_ui_exec", "finance"),
    ],
)
def test_demo_token_issues_jwt_without_any_credential(
    monkeypatch: pytest.MonkeyPatch, role: str, employee_id: str, department: str
) -> None:
    """/auth/demo-token (ADR-031) không kiểm bất kỳ Authorization header nào — chỉ
    dùng cho trang /ui công khai, đúng ba danh tính demo cố định."""
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-du-dai-de-qua-canh-bao-do-dai")
    get_settings.cache_clear()

    response = client.post(f"/auth/demo-token?role={role}")

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body["access_token"], str) and body["access_token"]

    from src.jwt_auth import verify_token

    employee = verify_token(body["access_token"])
    assert employee.employee_id == employee_id
    assert employee.role == role
    assert employee.department == department


def test_demo_token_rejects_role_outside_fixed_allowlist() -> None:
    """Không phải một cách tạo danh tính tuỳ ý — chỉ đúng 3 giá trị literal đã khai
    báo, FastAPI tự trả 422 cho bất kỳ giá trị nào khác."""
    response = client.post("/auth/demo-token?role=ceo_of_everything")

    assert response.status_code == 422


def test_ask_rejects_unknown_role() -> None:
    """Role lạ là vi phạm hợp đồng request, không phải câu hỏi cần trả lời.

    Pydantic validate body TRƯỚC khi endpoint chạy, nên lỗi này xảy ra dù có gắn
    header xác thực hay không — không cần mock authenticate ở đây.
    """
    response = client.post(
        "/ask", json={**VALID_REQUEST, "role": "ceo_of_everything"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 422


def test_ask_rejects_empty_question() -> None:
    response = client.post("/ask", json={**VALID_REQUEST, "question": ""}, headers=AUTH_HEADERS)

    assert response.status_code == 422


def test_ask_returns_401_without_authorization_header() -> None:
    """Giai đoạn xác thực & độ tin cậy: không có gì xác thực nếu thiếu hẳn header —
    không mock authenticate, để
    hàm thật chạy (không chạm DB vì thiếu header bị chặn trước khi tra cứu)."""
    response = client.post("/ask", json=VALID_REQUEST)

    assert response.status_code == 401


def test_ask_returns_401_when_api_key_invalid(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def raise_auth_error(header: str | None) -> AuthenticatedEmployee:
        raise AuthenticationError("api key khong khop nhan vien nao")

    monkeypatch.setattr(api, "authenticate", raise_auth_error)

    response = client.post("/ask", json=VALID_REQUEST, headers=AUTH_HEADERS)

    assert response.status_code == 401
    assert "request_id" in response.json()


def test_ask_returns_403_when_body_role_does_not_match_authenticated_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Đúng lỗ hổng đã đo ở vault ngày 26: request tự khai role=executive, nhưng danh
    tính đã xác thực thật sự là employee — phải bị chặn, không được xử lý theo role
    tự khai."""
    mock_authenticated_as(monkeypatch, role="employee", department="engineering")

    response = client.post(
        "/ask", json={**VALID_REQUEST, "role": "executive"}, headers=AUTH_HEADERS
    )

    assert response.status_code == 403


def test_ask_returns_grounded_docs_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Đường thành công: agent chọn docs, có bằng chứng và trích dẫn."""
    mock_authenticated_as(monkeypatch)
    agent_answer = AgentAnswer(
        answer="Phai rollback trong 15 phut.",
        tool_used="docs",
        abstained=False,
        doc_citations=[Citation(chunk_id="ENG-007#1", quote="rollback ve image")],
    )
    monkeypatch.setattr(api, "run_agent", lambda *a, **kw: agent_answer)

    response = client.post("/ask", json=VALID_REQUEST, headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is False
    assert body["tool_used"] == "docs"
    assert body["citations"] == [
        {
            "source_type": "docs",
            "doc_id": "ENG-007",
            "chunk_index": 1,
            "quote": "rollback ve image",
            "sql": None,
        }
    ]


def test_ask_returns_sql_answer_with_sql_citation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Câu trả lời từ tool SQL phải mang citation dạng ``source_type=sql`` kèm câu
    truy vấn, không phải citation dạng doc_id/chunk_index (giai đoạn agent routing)."""
    mock_authenticated_as(monkeypatch)
    agent_answer = AgentAnswer(
        answer="Doanh thu sales thang 1: 4.200.000.000 VND",
        tool_used="sql",
        abstained=False,
        sql_evidence="2026-01: 4.200.000.000 VND",
        sql_query="monthly_revenue WHERE department='sales' ...",
    )
    monkeypatch.setattr(api, "run_agent", lambda *a, **kw: agent_answer)

    response = client.post(
        "/ask",
        json={**VALID_REQUEST, "question": "Doanh thu sales thang 1 bao nhieu?"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tool_used"] == "sql"
    assert body["citations"] == [
        {
            "source_type": "sql",
            "doc_id": None,
            "chunk_index": None,
            "quote": None,
            "sql": "monthly_revenue WHERE department='sales' ...",
        }
    ]


def test_ask_reports_rbac_block_as_none_tool_and_abstained(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Bị chặn RBAC (kể cả khi router đề xuất sai tool) phải trả tool_used=none,
    abstained=true — không phải lỗi 500 hay câu trả lời bịa."""
    mock_authenticated_as(monkeypatch)
    agent_answer = AgentAnswer(
        answer="Ban khong co quyen xem so lieu duoc yeu cau.",
        tool_used="none",
        abstained=True,
        blocked_reason=(
            "role='employee' department='engineering' không được xem doanh thu 'finance'"
        ),
    )
    monkeypatch.setattr(api, "run_agent", lambda *a, **kw: agent_answer)

    response = client.post(
        "/ask",
        json={**VALID_REQUEST, "question": "Cho toi xem doanh thu phong finance"},
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is True
    assert body["tool_used"] == "none"
    assert body["citations"] == []


def test_ask_reports_no_evidence_as_none_tool_and_abstained(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """0 bằng chứng (do quyền hoặc do corpus không có) phải trả tool_used=none, không
    phải lỗi."""
    mock_authenticated_as(monkeypatch)
    agent_answer = AgentAnswer(answer="Khong tim thay tai lieu.", tool_used="none", abstained=True)
    monkeypatch.setattr(api, "run_agent", lambda *a, **kw: agent_answer)

    response = client.post("/ask", json=VALID_REQUEST, headers=AUTH_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is True
    assert body["tool_used"] == "none"
    assert body["citations"] == []


def test_ask_returns_502_when_generation_gives_up(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Model sai schema hết số lần thử — báo lỗi rõ ràng, không trả một câu bịa."""
    mock_authenticated_as(monkeypatch)
    from src.generation import SchemaFailure

    def raise_schema_failure(*a: object, **kw: object) -> AgentAnswer:
        raise SchemaFailure("vẫn sai schema sau 2 lần: giả lập cho test")

    monkeypatch.setattr(api, "run_agent", raise_schema_failure)

    response = client.post("/ask", json=VALID_REQUEST, headers=AUTH_HEADERS)

    assert response.status_code == 502
    assert "request_id" in response.json()


def test_ask_returns_503_when_upstream_network_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Lỗi mạng gọi Gemini/Postgres phải là 503, không phải 500 không rõ nguyên nhân."""
    mock_authenticated_as(monkeypatch)
    import httpx

    def raise_network_error(*a: object, **kw: object) -> AgentAnswer:
        raise httpx.ConnectError("giả lập mất kết nối")

    monkeypatch.setattr(api, "run_agent", raise_network_error)

    response = client.post("/ask", json=VALID_REQUEST, headers=AUTH_HEADERS)

    assert response.status_code == 503
