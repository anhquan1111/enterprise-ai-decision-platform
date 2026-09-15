"""D5: chạy bộ 12 câu held-out (``eval/final.jsonl``) MỘT LẦN, qua HTTP thật tới
``/ask`` đang chạy — không gọi thẳng ``run_agent()`` trong tiến trình, vì D5 cần đo
đúng những gì D4 đã xây: xác thực thật, audit log thật, latency thật đo tại biên
HTTP (không phải thời gian gọi hàm nội bộ).

    uv run python -m scripts.run_held_out_eval --keys-file <path to JSON: employee_id -> api key>
    uv run python -m scripts.run_held_out_eval --report      # đọc report đã có, không gọi gì

``--keys-file`` trỏ tới một file JSON NẰM NGOÀI repo (không bao giờ commit key thật —
xem AGENTS.md mục 4). File có dạng ``{"emp_101": "<key>", ...}``.

Giống nguyên tắc của ``run_eval.py --final``: kết quả ghi theo từng câu, ngay sau khi
gọi xong (không đợi hết cả 12 câu mới ghi một lần) — một lỗi hạ tầng (502, timeout)
giữa chừng không được xoá mất những câu đã chạy thật trước đó. Không xoá
``evidence/eval_results_final_agent.jsonl`` để "chạy sạch". Script từ chối chạy khi
file kết quả đã có đủ 12 câu, trừ khi ``--force`` (chỉ dùng khi thật sự có ý định niêm
phong lại một tập held-out MỚI, ví dụ sau khi eval/final.jsonl được viết lại từ đầu).
"""

import json
import statistics
import sys
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import httpx

from src.db import fetch_all

EVAL_DIR = Path(__file__).parent.parent / "eval"
EVIDENCE_DIR = Path(__file__).parent.parent / "evidence"
GOLD_PATH = EVAL_DIR / "final.jsonl"
RESULTS_PATH = EVIDENCE_DIR / "eval_results_final_agent.jsonl"
SUMMARY_PATH = EVIDENCE_DIR / "eval_summary_final_agent.json"

API_BASE = "http://127.0.0.1:8010"
REQUEST_TIMEOUT = 60.0


def _fold(text: str) -> str:
    """Bỏ dấu tiếng Việt để so khớp từ khoá — bản sao nhỏ của
    ``src.eval_taxonomy._fold`` (không import trực tiếp một hàm private của module
    khác; logic chỉ 3 dòng, trùng lặp rẻ hơn là kéo phụ thuộc chéo)."""
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(c for c in normalized if unicodedata.category(c) != "Mn").lower()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def load_done_ids(results_path: Path) -> dict[str, dict[str, Any]]:
    return {row["question_id"]: row for row in load_jsonl(results_path)}


def append_result(results_path: Path, row: dict[str, Any]) -> None:
    with results_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def call_ask(question: dict[str, Any], api_key: str) -> dict[str, Any]:
    response = httpx.post(
        f"{API_BASE}/ask",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
        json={
            "user_id": question["caller_employee_id"],
            "role": question["role"],
            "department": question["department"],
            "question": question["question"],
        },
    )
    response.raise_for_status()
    return cast(dict[str, Any], response.json())


def error_row(question: dict[str, Any], exc: httpx.HTTPStatusError) -> dict[str, Any]:
    """Một câu lỗi hạ tầng/không trả lời được (vd 502) vẫn phải để lại một dòng kết
    quả — một câu lỗi không được cản những câu còn lại, và bản thân việc lỗi là một
    phát hiện thật của lần chạy held-out, không phải thứ nên biến mất im lặng."""
    return {
        "question_id": question["question_id"],
        "question": question["question"],
        "expected_tool": question["expected_tool"],
        "actual_tool_used": None,
        "router_match": None,
        "should_abstain": question["should_abstain"],
        "actual_abstained": None,
        "correct": False,
        "reason": f"http_error_{exc.response.status_code}",
        "answer": None,
        "citations": [],
        "request_id": None,
        "latency_ms": None,
        "total_tokens": None,
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def score_one(question: dict[str, Any], ask_response: dict[str, Any]) -> dict[str, Any]:
    abstained = ask_response["abstained"]
    tool_used = ask_response["tool_used"]
    answer_text = ask_response["answer"]
    citations = ask_response["citations"]

    router_match: bool | None = None
    if question["expected_tool"] is not None:
        router_match = tool_used == question["expected_tool"]

    if question["should_abstain"]:
        correct = abstained is True
        # Toàn vẹn thêm: một câu abstain không bao giờ được kèm citation nào —
        # nếu có, đó là một lỗi grounding nghiêm trọng hơn cả "sai nhãn abstain".
        if abstained and citations:
            correct = False
        reason = "abstained_correctly" if correct else "did_not_abstain_when_expected"
    else:
        correct = not abstained
        if correct and question["expected_chunk_ids"]:
            cited_doc_chunk_ids = {
                f"{c['doc_id']}#{c['chunk_index']}"
                for c in citations
                if c.get("source_type") == "docs"
            }
            correct = any(eid in cited_doc_chunk_ids for eid in question["expected_chunk_ids"])
        if correct and question["expected_answer_keywords"]:
            folded_answer = _fold(answer_text)
            correct = all(_fold(kw) in folded_answer for kw in question["expected_answer_keywords"])
        reason = "correct" if correct else "wrong_or_unexpected_abstain"

    return {
        "question_id": question["question_id"],
        "question": question["question"],
        "expected_tool": question["expected_tool"],
        "actual_tool_used": tool_used,
        "router_match": router_match,
        "should_abstain": question["should_abstain"],
        "actual_abstained": abstained,
        "correct": correct,
        "reason": reason,
        "answer": answer_text,
        "citations": citations,
        "request_id": ask_response["request_id"],
        "latency_ms": ask_response["latency_ms"],
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def fetch_total_tokens(request_ids: list[str]) -> dict[str, int | None]:
    """Đọc total_tokens thật từ audit_log (D5, xem ADR-018) — không ước lượng."""
    if not request_ids:
        return {}
    rows = fetch_all(
        "SELECT request_id, total_tokens FROM audit_log WHERE request_id = ANY(%(ids)s::uuid[])",
        {"ids": request_ids},
    )
    return {str(r["request_id"]): r["total_tokens"] for r in rows}


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, int(round(pct / 100 * (len(ordered) - 1))))
    return float(ordered[idx])


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    # latency_ms/total_tokens là None cho một câu lỗi hạ tầng (error_row) — loại khỏi
    # thống kê thay vì để None làm hỏng sort/min/max.
    latencies = [r["latency_ms"] for r in rows if r.get("latency_ms") is not None]
    tokens = [r["total_tokens"] for r in rows if r.get("total_tokens")]
    router_checked = [r for r in rows if r["router_match"] is not None]
    n_errors = sum(1 for r in rows if r["reason"].startswith("http_error"))

    return {
        "n_questions": len(rows),
        "n_correct": sum(1 for r in rows if r["correct"]),
        "n_infra_errors": n_errors,
        "accuracy": f"{sum(1 for r in rows if r['correct'])}/{len(rows)}",
        "router_tool_selection": {
            "n_checked": len(router_checked),
            "n_match": sum(1 for r in router_checked if r["router_match"]),
        },
        "latency_ms": {
            "p50": percentile(latencies, 50),
            "p95": percentile(latencies, 95),
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "total_tokens": {
            "sum": sum(tokens) if tokens else None,
            "mean": round(statistics.mean(tokens), 1) if tokens else None,
            "n_with_token_data": len(tokens),
        },
        "per_question": [
            {
                "question_id": r["question_id"],
                "correct": r["correct"],
                "reason": r["reason"],
                "expected_tool": r["expected_tool"],
                "actual_tool_used": r["actual_tool_used"],
                "latency_ms": r["latency_ms"],
                "total_tokens": r.get("total_tokens"),
            }
            for r in rows
        ],
    }


def main(argv: list[str]) -> int:
    report_only = "--report" in argv
    force = "--force" in argv

    if report_only:
        if not RESULTS_PATH.exists():
            print(f"Chưa có kết quả nào ở {RESULTS_PATH}.")
            return 1
        existing_rows = load_jsonl(RESULTS_PATH)
        print(json.dumps(summarize(existing_rows), indent=2, ensure_ascii=False))
        return 0

    questions = load_jsonl(GOLD_PATH)
    done = load_done_ids(RESULTS_PATH)
    # Đủ 12/12 rồi thì đây thật sự là niêm phong lại, không phải "chạy nốt phần lỗi
    # hạ tầng còn thiếu" — chỉ cho qua với --force.
    if len(done) >= len(questions) and not force:
        print(
            f"CẢNH BÁO: đã có {len(done)}/{len(questions)} kết quả ở {RESULTS_PATH}. Tập "
            f"held-out chỉ chạy MỘT LẦN — dừng lại, không ghi đè. Dùng --report để xem kết "
            f"quả đã có, hoặc --force nếu thật sự có ý định niêm phong lại một tập held-out MỚI."
        )
        return 1
    if force and RESULTS_PATH.exists():
        RESULTS_PATH.unlink()
        done = {}

    keys_file_arg = next((a for a in argv if a.startswith("--keys-file=")), None)
    if keys_file_arg is None:
        print("Thiếu --keys-file=<path to JSON employee_id -> api key>.")
        return 1
    keys = json.loads(Path(keys_file_arg.split("=", 1)[1]).read_text(encoding="utf-8"))

    remaining = [q for q in questions if q["question_id"] not in done]
    print(
        f"Cần chạy {len(remaining)}/{len(questions)} câu held-out qua {API_BASE}/ask "
        f"(đã có {len(done)} từ trước)."
    )

    for i, question in enumerate(remaining, 1):
        api_key = keys[question["caller_employee_id"]]
        try:
            ask_response = call_ask(question, api_key)
            row = score_one(question, ask_response)
        except httpx.HTTPStatusError as exc:
            row = error_row(question, exc)
        append_result(RESULTS_PATH, row)
        mark = "OK" if row["correct"] else "SAI"
        print(
            f"  [{i}/{len(remaining)}] {question['question_id']:4s} "
            f"tool={row['actual_tool_used']!s:5s} abstain={row['actual_abstained']!s:5s} "
            f"-> {mark} ({row['reason']}) {row['latency_ms']}ms"
        )

    rows = load_jsonl(RESULTS_PATH)
    request_ids = [r["request_id"] for r in rows if r.get("request_id")]
    token_by_request = fetch_total_tokens(request_ids)
    for row in rows:
        if row.get("request_id"):
            row["total_tokens"] = token_by_request.get(row["request_id"])
    with RESULTS_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarize(rows)
    SUMMARY_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nĐã ghi: {RESULTS_PATH}")
    print(f"Đã ghi: {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
