"""D5 follow-up (ADR-020): đo router.route() có chọn đúng CẢ HAI tool cho câu hỏi
kết hợp sql+docs hay không, sau khi sửa SYSTEM_INSTRUCTION (checklist độc lập +
một ví dụ minh hoạ). Gọi Gemini thật.

6 câu hỏi MỚI, không trùng/gần giống eval/dev.jsonl hay eval/final.jsonl (H07, H08)
— không được đo lại trên chính hai tập đó sau khi đã niêm phong (xem ADR-019).
Đây là một probe riêng, giống đúng tinh thần scripts/probe_retrieval_headroom.py
(ADR-011): đo trước khi tin, không đoán prompt đã sửa là đủ.

    uv run python -m scripts.probe_router_combined_tools
"""

import json
from datetime import UTC, datetime
from pathlib import Path

from src.agent.router import route

EVIDENCE_PATH = Path(__file__).parent.parent / "evidence" / "router_combined_tools_probe.json"

QUESTIONS = [
    "Doanh thu sales thang 2 nam 2026 la bao nhieu, va nhan vien kinh doanh hien tai "
    "duoc tu quyet giam gia toi da bao nhieu phan tram?",
    "Doanh thu phong hr thang 3 nam 2026 la bao nhieu, va nhan vien duoc nghi phep "
    "bao nhieu ngay mot nam?",
    "Doanh thu ky thuat thang 4 nam 2026 la bao nhieu, va truoc khi len production "
    "mot ban release phai qua buoc nao?",
    "Doanh thu finance thang 5 nam 2026 la bao nhieu, va nhan vien duoc de xuat chi "
    "toi da bao nhieu ma khong can duyet them?",
    "So sanh doanh thu sales thang 3 va thang 4 nam 2026, va cho biet chinh sach "
    "giam gia hien tai danh cho nhan vien la gi?",
    "Doanh thu ky thuat 6 thang dau nam 2026 la bao nhieu, va quyen truy cap du lieu "
    "khach hang duoc cap va thu hoi nhu the nao?",
]


def main() -> int:
    rows = []
    for i, question in enumerate(QUESTIONS, 1):
        result = route(question)
        got_both = set(result.plan.tools) == {"sql", "docs"}
        mark = "OK" if got_both else "SAI"
        print(f"[{i}/{len(QUESTIONS)}] tools={result.plan.tools} -> {mark}")
        rows.append(
            {
                "question": question,
                "tools": result.plan.tools,
                "got_both": got_both,
                "total_tokens": result.total_tokens,
            }
        )

    n_both = sum(1 for r in rows if r["got_both"])
    summary = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_questions": len(rows),
        "n_got_both_tools": n_both,
        "rate": f"{n_both}/{len(rows)}",
        "rows": rows,
    }
    print(f"\n{n_both}/{len(rows)} câu chọn đúng cả hai tool.")
    EVIDENCE_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Đã ghi: {EVIDENCE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
