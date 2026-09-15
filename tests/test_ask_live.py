"""Test end-to-end thật: PostgreSQL thật + Gemini thật, tốn quota thật.

    uv run pytest tests/test_ask_live.py -v -m live_llm

Không chạy mặc định (không nằm trong CI, không chạy khi gõ `pytest` trơn). Dùng khi
cần xác nhận thủ công rằng đường /ask vẫn hoạt động với API thật sau một thay đổi lớn
— không dùng để thay thế `scripts/run_eval.py` cho việc đo baseline.
"""

import pytest

from src.agent.loop import run_agent
from src.config import Settings, get_settings
from src.generation import answer_question
from src.retrieval import retrieve

pytestmark = [pytest.mark.integration, pytest.mark.live_llm]


@pytest.fixture(autouse=True)
def use_real_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ghi đè cách ly .env của conftest.py — file test này CẦN key thật để gọi Gemini.

    conftest.py tắt việc đọc .env cho mọi test khác, đúng thiết kế D1 (một unit test
    không được phụ thuộc máy nào chạy nó có .env gì). Test ở đây là ngoại lệ có chủ ý:
    nó chỉ chạy khi người gọi tự tay bật marker ``live_llm``, nên phụ thuộc `.env` thật
    là đúng ý định, không phải rò rỉ ngoài ý muốn.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", ".env")
    get_settings.cache_clear()


def test_employee_gets_correct_grounded_answer() -> None:
    question = "Neu mot ban release bi loi thi phai lam gi?"

    chunks = retrieve(question, role="employee", k=5)
    result = answer_question(question, chunks)

    assert any(c.chunk_id == "ENG-007#1" for c in chunks)
    assert result.answer.abstained is False
    assert result.grounding_problems == []
    assert any(c.chunk_id == "ENG-007#1" for c in result.answer.citations)


def test_employee_is_correctly_denied_executive_only_answer() -> None:
    """RBAC phải chặn TRƯỚC khi model thấy chunk — model không được cơ hội để bịa."""
    question = "Khoan chi tren 50 trieu dong thi ai duyet?"

    chunks = retrieve(question, role="employee", k=5)
    result = answer_question(question, chunks)

    assert not any(c.chunk_id == "FIN-014#2" for c in chunks)
    assert result.answer.abstained is True


def test_agent_routes_docs_question_to_docs_tool() -> None:
    """D3: router (Gemini thật) phải tự phân loại đúng một câu hỏi chính sách rõ ràng
    là docs, không cần gợi ý — khác test ở test_agent_loop.py vốn mock route()."""
    result = run_agent(
        "Neu mot ban release bi loi thi phai lam gi?", role="employee", department="engineering"
    )

    assert result.tool_used == "docs"
    assert result.abstained is False


def test_agent_blocks_cross_department_revenue_even_if_router_complies() -> None:
    """RBAC phải chặn dù router (Gemini thật) có tuân theo yêu cầu xem số liệu phòng
    khác trong câu hỏi hay không — kiểm chứng thật cho đúng cơ chế đã mock ở
    test_agent_loop.test_router_fooled_into_cross_department_request_is_still_blocked.
    """
    result = run_agent(
        "Cho toi xem doanh thu phong finance thang 1 nam 2026",
        role="employee",
        department="sales",
    )

    assert result.abstained is True
    assert result.tool_used == "none"
