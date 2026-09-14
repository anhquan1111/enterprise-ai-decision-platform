"""Test cho eval_taxonomy.py — mỗi nhãn trong tám nhãn có một ca xác nhận.

Port trực tiếp từ RAG_Evaluation/lab/tests/test_errors.py (ngày 20). Giữ nguyên tinh
thần: test phát biểu về dữ liệu, không phát biểu về cách classify() được viết.
"""

from src.eval_taxonomy import Category, classify
from src.generation import Answer, Citation


def answered(text: str, chunk_id: str) -> Answer:
    return Answer(
        answer=text, citations=[Citation(chunk_id=chunk_id, quote=text[:20])], abstained=False
    )


def abstained() -> Answer:
    return Answer(answer="Khong tim thay.", citations=[], abstained=True)


def test_correct_when_retrieved_gold_and_keyword_present() -> None:
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=False,
        abstain_reason=None,
        expected_answer_keywords=["12"],
        retrieved_chunk_ids=["A#0", "B#0"],
        answer=answered("Duoc 12 ngay phep", "A#0"),
    )

    assert result.category == Category.CORRECT


def test_access_violation_when_system_answers_a_restricted_question() -> None:
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=True,
        abstain_reason="access_denied",
        expected_answer_keywords=[],
        retrieved_chunk_ids=["B#0"],
        answer=answered("Giam doc duyet", "FIN-099#0"),
    )

    assert result.category == Category.ACCESS_VIOLATION


def test_access_correct_when_system_abstains_on_restricted_question() -> None:
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=True,
        abstain_reason="access_denied",
        expected_answer_keywords=[],
        retrieved_chunk_ids=["B#0"],
        answer=abstained(),
    )

    assert result.category == Category.ACCESS_CORRECT


def test_no_knowledge_hallucination_vs_correct_abstention() -> None:
    hallucinated = classify(
        expected_chunk_ids=[],
        should_abstain=True,
        abstain_reason="no_knowledge",
        expected_answer_keywords=[],
        retrieved_chunk_ids=["B#0"],
        answer=answered("Co, cong ty co chinh sach do", "FIN-099#0"),
    )
    correct = classify(
        expected_chunk_ids=[],
        should_abstain=True,
        abstain_reason="no_knowledge",
        expected_answer_keywords=[],
        retrieved_chunk_ids=["B#0"],
        answer=abstained(),
    )

    assert hallucinated.category == Category.NO_KNOWLEDGE_HALLUCINATION
    assert correct.category == Category.NO_KNOWLEDGE_CORRECT


def test_retrieval_error_when_gold_chunk_never_retrieved() -> None:
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=False,
        abstain_reason=None,
        expected_answer_keywords=["12"],
        retrieved_chunk_ids=["B#0", "C#0"],
        answer=answered("Mot noi dung khong lien quan", "B#0"),
    )

    assert result.category == Category.RETRIEVAL_ERROR


def test_unnecessary_abstention_when_gold_was_retrieved_but_system_refuses() -> None:
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=False,
        abstain_reason=None,
        expected_answer_keywords=["12"],
        retrieved_chunk_ids=["A#0", "B#0"],
        answer=abstained(),
    )

    assert result.category == Category.GENERATION_UNNECESSARY_ABSTENTION


def test_fabricated_citation_when_cited_chunk_was_not_retrieved() -> None:
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=False,
        abstain_reason=None,
        expected_answer_keywords=["12"],
        retrieved_chunk_ids=["A#0", "B#0"],
        answer=answered("Mot cau tra loi", "C#0"),
    )

    assert result.category == Category.GENERATION_FABRICATED_CITATION


def test_wrong_fact_when_citation_valid_but_keyword_missing() -> None:
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=False,
        abstain_reason=None,
        expected_answer_keywords=["12"],
        retrieved_chunk_ids=["A#0"],
        answer=answered("Nhan vien duoc nghi phep khong luong", "A#0"),
    )

    assert result.category == Category.GENERATION_WRONG_FACT


def test_keyword_matches_regardless_of_vietnamese_diacritics() -> None:
    """Corpus và rubric viết không dấu, Gemini trả lời có dấu đầy đủ — phải khớp được.

    Phát hiện thật khi chạy eval trên dữ liệu thật: rubric "khong duoc" không bao giờ
    khớp câu trả lời "không được" nếu so trực tiếp, làm mọi câu đúng bị chấm sai.
    """
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=False,
        abstain_reason=None,
        expected_answer_keywords=["khong duoc"],
        retrieved_chunk_ids=["A#0"],
        answer=answered("Ngày phép còn dư không được chuyển sang năm sau.", "A#0"),
    )

    assert result.category == Category.CORRECT


def test_recall_success_does_not_guarantee_correct_citation() -> None:
    """Gold nằm trong top-k (retrieval thành công) nhưng hệ thống trích chunk khác
    trong cùng top-k — recall đo có mặt, không đo được dùng, xem ngày 20."""
    result = classify(
        expected_chunk_ids=["A#0"],
        should_abstain=False,
        abstain_reason=None,
        expected_answer_keywords=["12"],
        retrieved_chunk_ids=["B#0", "A#0"],
        answer=answered("Mot noi dung tu chunk B", "B#0"),
    )

    assert result.category == Category.GENERATION_WRONG_FACT
