"""Tests for /ask — mocked retrieval và generation, không chạm mạng hay database.

/ask gọi PostgreSQL (retrieve) và Gemini (answer_question) thật khi chạy production,
nhưng một unit test không được phụ thuộc dịch vụ ngoài: chậm, tốn quota, và kết quả có
thể đổi giữa hai lần chạy vì model không xác định. Test ở đây thay hai hàm đó bằng giá
trị giả, giống cách ScriptedLLM của ngày 19 tách được luồng xử lý khỏi việc gọi model
thật.

Test end-to-end với API và database thật nằm trong ``test_ask_live.py``, đánh dấu
``live_llm``, không chạy mặc định.
"""

from fastapi.testclient import TestClient

from src import api
from src.generation import Answer, Citation, GroundedAnswer, SchemaFailure
from src.retrieval import RetrievedChunk

client = TestClient(api.app)

VALID_REQUEST = {
    "user_id": "emp_042",
    "role": "employee",
    "department": "engineering",
    "question": "Neu mot ban release bi loi thi phai lam gi?",
}


def make_chunk(chunk_id: str = "ENG-007#1") -> RetrievedChunk:
    doc_id, index = chunk_id.split("#")
    return RetrievedChunk(
        doc_id=doc_id,
        chunk_index=int(index),
        chunk_text="Release that bai phai rollback ve image truoc do.",
        department="engineering",
        access_level="employee",
        distance=0.12,
    )


def test_health_is_liveness_only() -> None:
    """/health phải trả lời mà không chạm database."""
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "enterprise-ai-decision-platform"


def test_ask_rejects_unknown_role() -> None:
    """Role lạ là vi phạm hợp đồng request, không phải câu hỏi cần trả lời.

    Phạm vi quyền suy ra từ role, nên một role hệ thống không biết không bao giờ
    được chạm tới tầng dữ liệu.
    """
    response = client.post("/ask", json={**VALID_REQUEST, "role": "ceo_of_everything"})

    assert response.status_code == 422


def test_ask_rejects_empty_question() -> None:
    response = client.post("/ask", json={**VALID_REQUEST, "question": ""})

    assert response.status_code == 422


def test_ask_returns_grounded_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Đường thành công: có chunk, model trả lời đúng schema và có bằng chứng."""
    chunk = make_chunk()
    grounded = GroundedAnswer(
        answer=Answer(
            answer="Phai rollback trong 15 phut.",
            citations=[Citation(chunk_id="ENG-007#1", quote="rollback ve image")],
            abstained=False,
        ),
        grounding_problems=[],
        attempts=1,
    )
    monkeypatch.setattr(api, "retrieve", lambda *a, **kw: [chunk])
    monkeypatch.setattr(api, "answer_question", lambda *a, **kw: grounded)

    response = client.post("/ask", json=VALID_REQUEST)

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


def test_ask_reports_no_evidence_as_none_tool_and_abstained(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """0 chunk (do quyền hoặc do corpus không có) phải trả tool_used=none, không phải lỗi."""
    grounded = GroundedAnswer(
        answer=Answer(answer="Khong tim thay tai lieu.", citations=[], abstained=True),
        grounding_problems=[],
        attempts=0,
    )
    monkeypatch.setattr(api, "retrieve", lambda *a, **kw: [])
    monkeypatch.setattr(api, "answer_question", lambda *a, **kw: grounded)

    response = client.post("/ask", json=VALID_REQUEST)

    assert response.status_code == 200
    body = response.json()
    assert body["abstained"] is True
    assert body["tool_used"] == "none"
    assert body["citations"] == []


def test_ask_returns_502_when_generation_gives_up(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Model sai schema hết số lần thử — báo lỗi rõ ràng, không trả một câu bịa."""

    def raise_schema_failure(*a: object, **kw: object) -> GroundedAnswer:
        raise SchemaFailure("vẫn sai schema sau 2 lần: giả lập cho test")

    monkeypatch.setattr(api, "retrieve", lambda *a, **kw: [make_chunk()])
    monkeypatch.setattr(api, "answer_question", raise_schema_failure)

    response = client.post("/ask", json=VALID_REQUEST)

    assert response.status_code == 502
    assert "request_id" in response.json()


def test_ask_returns_503_when_upstream_network_fails(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Lỗi mạng gọi Gemini/Postgres phải là 503, không phải 500 không rõ nguyên nhân."""
    import httpx

    def raise_network_error(*a: object, **kw: object) -> GroundedAnswer:
        raise httpx.ConnectError("giả lập mất kết nối")

    monkeypatch.setattr(api, "retrieve", lambda *a, **kw: [make_chunk()])
    monkeypatch.setattr(api, "answer_question", raise_network_error)

    response = client.post("/ask", json=VALID_REQUEST)

    assert response.status_code == 503
