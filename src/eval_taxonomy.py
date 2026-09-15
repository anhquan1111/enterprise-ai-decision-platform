"""Phân loại một câu đã chấm vào đúng một trong tám nhãn.

Đây là bản production của bộ phân loại đã học và đo ở RAG_Evaluation (ngày 20). Thứ
tự kiểm cố định — quyền trước, retrieval trước generation — không được đảo, vì khâu
trước sai thì phân tích khâu sau vô nghĩa.
"""

import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from src.generation import Answer


def _fold(text: str) -> str:
    """Chuẩn hóa để so từ khóa không phân biệt dấu tiếng Việt.

    Corpus và rubric ban đầu viết không dấu, còn Gemini luôn trả lời bằng tiếng Việt
    có dấu đầy đủ và đúng chính tả — hành vi đúng cho người dùng thật nhưng khiến so
    khớp trực tiếp không bao giờ khớp ("khong duoc" không phải chuỗi con của "không
    được" theo byte). Corpus và rubric đã chuyển sang có dấu (ADR-022), nên nguyên
    nhân gốc không còn, nhưng vẫn giữ hàm này: chi phí bằng không, và giúp so khớp
    không phụ thuộc vào việc dữ liệu đầu vào có dấu hay không.

    NFD tách dấu phụ khỏi nguyên âm gốc (ví dụ "ư" thành "u" + dấu), nhưng "đ" là một
    chữ cái Latin riêng (U+0111), không phải tổ hợp — phải thay tay trước khi NFD.
    """
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower()


class Category(StrEnum):
    CORRECT = "correct"
    ACCESS_CORRECT = "access_correct"
    ACCESS_VIOLATION = "access_violation"
    NO_KNOWLEDGE_CORRECT = "no_knowledge_correct"
    NO_KNOWLEDGE_HALLUCINATION = "no_knowledge_hallucination"
    RETRIEVAL_ERROR = "retrieval_error"
    GENERATION_UNNECESSARY_ABSTENTION = "generation_unnecessary_abstention"
    GENERATION_FABRICATED_CITATION = "generation_fabricated_citation"
    GENERATION_WRONG_FACT = "generation_wrong_fact"


@dataclass(frozen=True)
class Diagnosis:
    category: Category
    system_answered: bool


def classify(
    *,
    expected_chunk_ids: list[str],
    should_abstain: bool,
    abstain_reason: str | None,
    expected_answer_keywords: list[str],
    retrieved_chunk_ids: list[str],
    answer: Answer,
) -> Diagnosis:
    """Xếp một câu đã chấm vào đúng một trong tám nhãn.

    Thứ tự kiểm cố định: (1) đáng lẽ phải từ chối chưa, (2) chunk đúng có trong danh
    sách đã retrieval chưa, (3) mới tới nội dung câu trả lời.
    """
    answered = not answer.abstained

    if should_abstain:
        if abstain_reason == "access_denied":
            cat = Category.ACCESS_VIOLATION if answered else Category.ACCESS_CORRECT
        else:
            cat = Category.NO_KNOWLEDGE_HALLUCINATION if answered else Category.NO_KNOWLEDGE_CORRECT
        return Diagnosis(cat, answered)

    gold_was_retrieved = any(cid in retrieved_chunk_ids for cid in expected_chunk_ids)

    if not gold_was_retrieved:
        return Diagnosis(Category.RETRIEVAL_ERROR, answered)

    if not answered:
        return Diagnosis(Category.GENERATION_UNNECESSARY_ABSTENTION, answered)

    cited_ids = {c.chunk_id for c in answer.citations}
    if any(cid not in retrieved_chunk_ids for cid in cited_ids):
        return Diagnosis(Category.GENERATION_FABRICATED_CITATION, answered)

    if expected_answer_keywords:
        text = _fold(answer.answer)
        if not any(_fold(kw) in text for kw in expected_answer_keywords):
            return Diagnosis(Category.GENERATION_WRONG_FACT, answered)

    return Diagnosis(Category.CORRECT, answered)
