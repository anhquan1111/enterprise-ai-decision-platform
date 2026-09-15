"""Giai đoạn báo cáo cuối, bổ sung (ADR-016's khoảng trống chưa đo, ADR-026): đo lại
tỷ lệ lỗi hạ tầng ở đúng kịch bản đã phát hiện vấn đề ban đầu — N request đồng thời —
CÓ và KHÔNG có jitter, để biết bản vá (`random.uniform(0, 0.5)` cộng vào backoff ở
`router.py`/`generation.py`/`embeddings.py`) thật sự giảm tỷ lệ va chạm retry hay
không, thay vì chỉ tin "đã sửa theo đúng nguyên nhân đã xác định".

Gọi thẳng `run_agent()` trong tiến trình (không qua HTTP/`/ask`) — phạm vi đo là cơ
chế retry/backoff/jitter của các hàm gọi Gemini, không phải toàn bộ đường HTTP/xác
thực. Không cần API key: role/department truyền thẳng vào `run_agent()`.

Cả hai điều kiện (có/không jitter) chạy NỐI TIẾP NHAU trong cùng một lần gọi script,
để mức độ nghẽn thật của Gemini tại thời điểm đo (biến đổi theo thời gian trong
ngày, thấy rõ suốt phiên đo held-out v2) ảnh hưởng tới cả hai điều kiện gần như
nhau — so sánh "có jitter hôm nay" với "không jitter hôm qua" sẽ không công bằng.

    uv run python -m scripts.probe_retry_jitter_load
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src import embeddings as embeddings_module
from src import generation as generation_module
from src.agent import loop as loop_module
from src.agent import router as router_module

EVIDENCE_PATH = Path(__file__).parent.parent / "evidence" / "retry_jitter_load_probe.json"

CONCURRENT_REQUESTS = 3  # đúng kịch bản đã phát hiện vấn đề ở ADR-016
TRIALS_PER_CONDITION = 8

# Câu hỏi kết hợp sql+docs — chạm cả ba hàm có retry (router, embeddings, generation),
# không nằm trong eval/dev.jsonl hay eval/final.jsonl (đây không phải bài đo đúng/sai
# nội dung nên không có rủi ro leakage, nhưng vẫn dùng câu mới cho rõ ràng).
QUESTION = (
    "Doanh thu phòng sales tháng 3 năm 2026 là bao nhiêu, và nhân viên chính thức "
    "được nghỉ phép bao nhiêu ngày một năm?"
)
ROLE = "employee"
DEPARTMENT = "sales"


def _one_call() -> tuple[bool, str | None]:
    """Trả về (thành_công, tên_lỗi_nếu_có). Lỗi nghiệp vụ/RBAC không tính là thất bại
    hạ tầng — chỉ exception thật (hết retry) mới tính."""
    try:
        loop_module.run_agent(QUESTION, role=ROLE, department=DEPARTMENT)
        return True, None
    except Exception as exc:  # noqa: BLE001 - probe đo MỌI lỗi hạ tầng, không lọc loại
        return False, type(exc).__name__


def run_trials(*, jitter_enabled: bool) -> dict[str, Any]:
    label = "voi_jitter" if jitter_enabled else "khong_jitter"
    jitter_value = 0.5 if jitter_enabled else 0.0
    router_module._NETWORK_RETRY_JITTER_S = jitter_value
    generation_module._NETWORK_RETRY_JITTER_S = jitter_value
    embeddings_module._NETWORK_RETRY_JITTER_S = jitter_value

    trials: list[dict[str, Any]] = []
    for t in range(1, TRIALS_PER_CONDITION + 1):
        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=CONCURRENT_REQUESTS) as pool:
            futures = [pool.submit(_one_call) for _ in range(CONCURRENT_REQUESTS)]
            results = [f.result() for f in as_completed(futures)]
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        n_failed = sum(1 for ok, _ in results if not ok)
        errors = [name for ok, name in results if not ok]
        print(
            f"  [{label} {t}/{TRIALS_PER_CONDITION}] {CONCURRENT_REQUESTS - n_failed}/"
            f"{CONCURRENT_REQUESTS} thanh cong, {elapsed_ms}ms, loi={errors}"
        )
        trials.append(
            {
                "trial": t,
                "n_concurrent": CONCURRENT_REQUESTS,
                "n_failed": n_failed,
                "errors": errors,
                "elapsed_ms": elapsed_ms,
            }
        )

    total_calls = TRIALS_PER_CONDITION * CONCURRENT_REQUESTS
    total_failed = sum(t["n_failed"] for t in trials)
    return {
        "jitter_enabled": jitter_enabled,
        "jitter_s": jitter_value,
        "total_calls": total_calls,
        "total_failed": total_failed,
        "failure_rate": f"{total_failed}/{total_calls}",
        "trials": trials,
    }


def main() -> int:
    print(f"Đo {TRIALS_PER_CONDITION} lượt x {CONCURRENT_REQUESTS} request đồng thời, có jitter:")
    with_jitter = run_trials(jitter_enabled=True)

    print(
        f"\nĐo {TRIALS_PER_CONDITION} lượt x {CONCURRENT_REQUESTS} request đồng thời, KHÔNG jitter:"
    )
    without_jitter = run_trials(jitter_enabled=False)

    # Khôi phục jitter mặc định trước khi thoát — script này chạy trong cùng tiến
    # trình có thể được import lại (test, REPL), không để lại trạng thái module đã
    # sửa.
    router_module._NETWORK_RETRY_JITTER_S = 0.5
    generation_module._NETWORK_RETRY_JITTER_S = 0.5
    embeddings_module._NETWORK_RETRY_JITTER_S = 0.5

    summary = {
        "measured_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "concurrent_requests": CONCURRENT_REQUESTS,
        "trials_per_condition": TRIALS_PER_CONDITION,
        "question": QUESTION,
        "with_jitter": with_jitter,
        "without_jitter": without_jitter,
    }
    print(f"\nCó jitter:    {with_jitter['failure_rate']} thất bại hạ tầng")
    print(f"Không jitter: {without_jitter['failure_rate']} thất bại hạ tầng")

    EVIDENCE_PATH.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"\nĐã ghi: {EVIDENCE_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
