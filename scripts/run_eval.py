"""Chạy bộ đánh giá thật: retrieval + generation qua Gemini, phân loại lỗi, recall@k, MRR.

    uv run python -m scripts.run_eval                    # eval/dev.jsonl
    uv run python -m scripts.run_eval --final             # eval/final.jsonl, CHỈ CHẠY MỘT LẦN
    uv run python -m scripts.run_eval --report             # đọc report đã có, không gọi gì

Có thể chạy lại giữa chừng: kết quả ghi theo từng câu vào
``evidence/eval_results_<mode>.jsonl``, và những câu đã có trong file đó được bỏ qua ở
lần chạy sau — giống đúng cách multi_agent_LLM_system xử lý giới hạn quota free-tier
theo ngày. Không xoá file kết quả để "chạy sạch" — xoá là mất bằng chứng của lần chạy
trước, và với tập final thì mất luôn tính "chỉ chạy một lần".
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.eval_taxonomy import classify
from src.generation import SchemaFailure, answer_question
from src.retrieval import retrieve

EVAL_DIR = Path(__file__).parent.parent / "eval"
EVIDENCE_DIR = Path(__file__).parent.parent / "evidence"

# Rải nhẹ giữa các câu để không dồn dập vào giới hạn requests-per-minute — hai lệnh
# gọi mỗi câu (embed câu hỏi + generate) đã tính cả trong ADR-002.
SLEEP_BETWEEN_QUESTIONS_S = 1.0
MAX_K = 10  # đủ lớn để đo recall@10 song song với recall@3 dùng cho generation thật
GENERATION_K = 5


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def load_done_ids(results_path: Path) -> dict[str, dict[str, Any]]:
    if not results_path.exists():
        return {}
    return {row["question_id"]: row for row in load_jsonl(results_path)}


def append_result(results_path: Path, row: dict[str, Any]) -> None:
    with results_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_one(question: dict[str, Any]) -> dict[str, Any]:
    as_of = datetime.fromisoformat(question["as_of"]) if question.get("as_of") else None

    # k=MAX_K cho phép đo recall@k ở nhiều mức mà không cần gọi retrieval hai lần —
    # cùng một lần gọi embedding phục vụ cả recall@10 lẫn top-GENERATION_K đưa cho model.
    ranked = retrieve(question["question"], role=question["role"], as_of=as_of, k=MAX_K)
    top_ids_full = [c.chunk_id for c in ranked]
    generation_context = ranked[:GENERATION_K]

    rank_of_gold = None
    if not question["should_abstain"]:
        rank_of_gold = next(
            (i + 1 for i, cid in enumerate(top_ids_full) if cid in question["expected_chunk_ids"]),
            None,
        )

    try:
        result = answer_question(question["question"], generation_context)
    except SchemaFailure as exc:
        # Ghi lại như một câu KHÔNG trả lời được, không phải làm sập cả lượt chạy —
        # một câu lỗi không được cản những câu còn lại. category="error" là nhãn thứ
        # chín, ngoài tám nhãn của eval_taxonomy: nó nghĩa là "chưa đo được", không
        # phải một trong bốn nhóm nguyên nhân đã biết.
        return {
            "question_id": question["question_id"],
            "question": question["question"],
            "role": question["role"],
            "retrieved_top_k": top_ids_full[:GENERATION_K],
            "rank_of_gold": rank_of_gold,
            "system_abstained": True,
            "system_answer": "",
            "system_citations": [],
            "grounding_problems": [],
            "category": "error",
            "error": str(exc),
            "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }

    diag = classify(
        expected_chunk_ids=question["expected_chunk_ids"],
        should_abstain=question["should_abstain"],
        abstain_reason=question["abstain_reason"],
        expected_answer_keywords=question["expected_answer_keywords"],
        retrieved_chunk_ids=[c.chunk_id for c in generation_context],
        answer=result.answer,
    )

    return {
        "question_id": question["question_id"],
        "question": question["question"],
        "role": question["role"],
        "retrieved_top_k": [c.chunk_id for c in generation_context],
        "rank_of_gold": rank_of_gold,
        "system_abstained": result.answer.abstained,
        "system_answer": result.answer.answer,
        "system_citations": [
            {"chunk_id": c.chunk_id, "quote": c.quote} for c in result.answer.citations
        ],
        "grounding_problems": result.grounding_problems,
        "category": diag.category.value,
        "error": None,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def summarize(rows: list[dict[str, Any]], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    answerable = [q for q in gold_by_id.values() if not q["should_abstain"]]
    recall_hits = {k: 0 for k in (3, 5, 10)}
    mrr_sum = 0.0

    for row in rows:
        gold = gold_by_id[row["question_id"]]
        if gold["should_abstain"]:
            continue
        rank = row.get("rank_of_gold")
        for k in recall_hits:
            if rank is not None and rank <= k:
                recall_hits[k] += 1
        mrr_sum += (1.0 / rank) if rank else 0.0

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1

    n = len(answerable)
    return {
        "n_questions": len(gold_by_id),
        "n_answerable": n,
        "n_completed": len(rows),
        "recall_at_k": {
            f"recall@{k}": f"{v}/{n} ({100 * v / n:.1f}%)" for k, v in recall_hits.items()
        }
        if n
        else {},
        "mrr": round(mrr_sum / n, 3) if n else None,
        "categories": counts,
    }


def main(argv: list[str]) -> int:
    is_final = "--final" in argv
    report_only = "--report" in argv
    gold_path = EVAL_DIR / ("final.jsonl" if is_final else "dev.jsonl")
    results_path = EVIDENCE_DIR / f"eval_results_{'final' if is_final else 'dev'}.jsonl"

    gold_rows = load_jsonl(gold_path)
    gold_by_id = {g["question_id"]: g for g in gold_rows}
    done = load_done_ids(results_path)

    if report_only:
        rows = list(done.values())
        print(json.dumps(summarize(rows, gold_by_id), indent=2, ensure_ascii=False))
        return 0

    if is_final and done:
        print(
            f"CẢNH BÁO: tập held-out đã có {len(done)} câu kết quả. "
            f"Tập này chỉ chạy MỘT LẦN — không xoá {results_path} để chạy lại trừ khi "
            f"bạn thật sự có ý định niêm phong một tập held-out mới."
        )

    remaining = [g for g in gold_rows if g["question_id"] not in done]
    print(f"Cần chạy {len(remaining)}/{len(gold_rows)} câu (đã có {len(done)} từ trước).")

    for i, question in enumerate(remaining, 1):
        row = run_one(question)
        append_result(results_path, row)
        mark = "LỖI" if row.get("error") else row["category"]
        print(f"  [{i}/{len(remaining)}] {question['question_id']:16s} -> {mark}")
        if i < len(remaining):
            time.sleep(SLEEP_BETWEEN_QUESTIONS_S)

    all_rows = load_jsonl(results_path)
    summary = summarize(all_rows, gold_by_id)
    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))

    summary_path = EVIDENCE_DIR / f"eval_summary_{'final' if is_final else 'dev'}.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nĐã ghi: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
