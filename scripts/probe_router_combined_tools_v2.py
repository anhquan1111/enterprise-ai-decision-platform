"""Theo dõi ADR-024 (H21 tái phát lỗi H07 dù ADR-020 đã đo 6/6): 6 câu ở
`probe_router_combined_tools.py` không đủ để coi khoảng trống "router bỏ sót tool
trong câu hỏi kết hợp" đã đóng. Probe này lớn hơn hẳn (18 câu, không phải 6) và
dùng để đo baseline TRƯỚC khi sửa, rồi đo lại SAU khi sửa — cùng một bộ câu hỏi cho
cả hai lần đo, để so sánh công bằng.

18 câu hỏi MỚI, không trùng/gần giống eval/dev.jsonl, eval/final.jsonl (cả hai
vòng), hay 6 câu của probe_router_combined_tools.py — bao phủ cả 4 phòng ban, đổi
thứ tự sql-trước/docs-trước trong câu, và một số câu hỏi doanh thu phòng A kèm
chính sách của phòng B (docs không lọc theo phòng ban — ADR-009 — nên đây là tổ
hợp hợp lệ). Chỉ gọi `route()` trực tiếp — không qua RBAC/thực thi, vì đây là bài
đo phân loại tool, không phải bài đo đúng/sai nội dung.

    uv run python -m scripts.probe_router_combined_tools_v2 --pre    # trước khi sửa
    uv run python -m scripts.probe_router_combined_tools_v2 --post   # sau khi sửa
"""

import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.agent.router import route

EVIDENCE_DIR = Path(__file__).parent.parent / "evidence"

SLEEP_BETWEEN_QUESTIONS_S = 1.0

QUESTIONS = [
    "Trưởng phòng sales muốn biết doanh thu tháng 1 năm 2026, đồng thời mức giảm giá "
    "tối đa nhân viên được tự quyết hiện nay là bao nhiêu phần trăm?",
    "So doanh thu sales tháng 2 và tháng 3 năm 2026 ra sao, và chính sách giảm giá "
    "dành cho nhân viên kinh doanh hiện tại quy định mức tối đa bao nhiêu?",
    "Phòng finance tháng 4 năm 2026 đạt doanh thu bao nhiêu, và trưởng phòng được "
    "duyệt chi tối đa bao nhiêu mà không cần ai phê duyệt thêm?",
    "Cho tôi số liệu doanh thu finance tháng 5 năm 2026, kèm theo thông tin số doanh "
    "thu tháng được chốt chính thức vào ngày nào?",
    "Nhân viên phòng finance được đề xuất chi tối đa bao nhiêu mà không cần duyệt "
    "thêm, và doanh thu phòng này trong tháng 2 năm 2026 là bao nhiêu?",
    "Doanh thu kỹ thuật tháng 3 năm 2026 ra sao, và mọi bản release cần qua bước gì "
    "trước khi lên production?",
    "Trước khi triển khai lên production, một bản release engineering cần đạt điều "
    "kiện gì, và doanh thu phòng này tháng 5 năm 2026 là bao nhiêu?",
    "Doanh thu engineering từ tháng 1 đến tháng 6 năm 2026 là bao nhiêu, và quyền "
    "truy cập dữ liệu khách hàng được cấp và thu hồi theo quy tắc nào?",
    "Phòng hr tháng 4 năm 2026 có doanh thu bao nhiêu, và một nhân viên chính thức "
    "được nghỉ phép bao nhiêu ngày mỗi năm?",
    "Trưởng phòng được phép mở tuyển dụng khi nào, và doanh thu hr tháng 1 năm 2026 là bao nhiêu?",
    "Ứng viên cần trải qua bao nhiêu vòng phỏng vấn kỹ thuật trước khi nhận offer, "
    "đồng thời cho tôi biết doanh thu phòng hr tháng 3 năm 2026?",
    "Tôi cần biết doanh thu sales tháng 4 năm 2026, và ngày phép hàng năm của một "
    "nhân viên chính thức là bao nhiêu ngày?",
    "Số liệu doanh thu finance tháng 3 năm 2026 thế nào, và quy trình release lên "
    "production yêu cầu những bước nào?",
    "Doanh thu engineering tháng 2 năm 2026 là bao nhiêu, và công ty quy định mức "
    "giảm giá tự do hiện tại cho nhân viên kinh doanh là bao nhiêu phần trăm?",
    "Khoản chi trên 50 triệu đồng cuối cùng do ai phê duyệt, và doanh thu phòng hr "
    "tháng 5 năm 2026 ra sao?",
    "Ngày phép không dùng hết trong năm có được cộng dồn sang năm sau không, và "
    "doanh thu sales tháng 6 năm 2026 hiện tại là bao nhiêu?",
    "Doanh thu phòng finance 6 tháng đầu năm 2026 ra sao, và nếu một bản release gặp "
    "sự cố thì phải xử lý trong tối đa bao lâu?",
    "Quy trình tuyển dụng của trưởng phòng cần điều kiện gì về ngân sách headcount, "
    "và doanh thu phòng hr tháng 2 năm 2026 là bao nhiêu?",
]


def main(argv: list[str]) -> int:
    if "--pre" in argv:
        tag = "pre"
    elif "--post" in argv:
        tag = "post"
    else:
        print("Cần chỉ định --pre (trước khi sửa) hoặc --post (sau khi sửa).")
        return 1

    # Lỗi hạ tầng thoáng qua (503 vẫn dày đặc sau ADR-026) không được làm chết cả
    # lượt đo — ghi lại là lỗi hạ tầng cho câu đó, tiếp tục câu tiếp theo, giống
    # đúng nguyên tắc run_eval.py/run_held_out_eval.py đã dùng.
    rows: list[dict[str, Any]] = []
    for i, question in enumerate(QUESTIONS, 1):
        try:
            result = route(question)
        except Exception as exc:  # noqa: BLE001 - lỗi hạ tầng, không phải nội dung
            print(f"[{i}/{len(QUESTIONS)}] LỖI HẠ TẦNG: {type(exc).__name__}")
            rows.append(
                {
                    "question": question,
                    "tools": None,
                    "got_both": False,
                    "total_tokens": None,
                    "infra_error": type(exc).__name__,
                }
            )
            continue
        got_both = set(result.plan.tools) == {"sql", "docs"}
        mark = "OK" if got_both else "SAI"
        print(f"[{i}/{len(QUESTIONS)}] tools={result.plan.tools} -> {mark}")
        rows.append(
            {
                "question": question,
                "tools": result.plan.tools,
                "got_both": got_both,
                "total_tokens": result.total_tokens,
                "infra_error": None,
            }
        )
        if i < len(QUESTIONS):
            time.sleep(SLEEP_BETWEEN_QUESTIONS_S)

    n_both = sum(1 for r in rows if r["got_both"])
    n_infra_errors = sum(1 for r in rows if r["infra_error"] is not None)
    summary = {
        "tag": tag,
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "n_questions": len(rows),
        "n_got_both_tools": n_both,
        "n_infra_errors": n_infra_errors,
        "rate": f"{n_both}/{len(rows)}",
        "rows": rows,
    }
    print(
        f"\n{n_both}/{len(rows)} câu chọn đúng cả hai tool ({tag}), {n_infra_errors} lỗi hạ tầng."
    )
    evidence_path = EVIDENCE_DIR / f"router_combined_tools_v2_{tag}.json"
    evidence_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"Đã ghi: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
