"""Dataset contract cho bảng doc_chunks, viết dưới dạng code thi hành được.

Contract không phải docstring. Mỗi quy tắc ở đây trả lời được ba câu: vi phạm thì
*phát hiện bằng cách nào*, *hậu quả là gì*, và *xử lý ra sao*.

Hai mức severity, phân theo **hậu quả** chứ không theo cảm giác nghiêm trọng:

* ``FATAL``   — dòng không vào bảng chính, đi vào quarantine kèm lý do.
* ``WARNING`` — dòng vẫn vào bảng chính, nhưng được đếm và báo trong manifest.

Module này dùng chung cho ingestion và cho đường serving. Hai bản sao của cùng một
contract là cách sinh ra sai lệch train/serve mà không ai thấy exception.
"""

from dataclasses import dataclass, field
from enum import StrEnum

import pandas as pd

from src.scope import (
    ALLOWED_ACCESS_LEVELS,
    ALLOWED_DEPARTMENTS,
    ROLE_VISIBLE_LEVELS,
    visible_access_levels,
)

__all__ = [
    "ALLOWED_ACCESS_LEVELS",
    "ALLOWED_DEPARTMENTS",
    "ROLE_VISIBLE_LEVELS",
    "visible_access_levels",
    "CONTRACT_VERSION",
    "ContractError",
    "Severity",
    "ValidationResult",
    "Violation",
    "check_dtypes",
    "check_schema",
    "validate",
]

CONTRACT_VERSION = "1.0.0"

# Grain: một dòng là một chunk của một document.
NATURAL_KEY: tuple[str, ...] = ("doc_id", "chunk_index")

# Quy tắc phạm vi quyền sống ở src/scope.py (không phụ thuộc pandas) và được
# re-export ở đây để chỗ gọi cũ không phải đổi. Xem docstring của scope.py.

REQUIRED_COLUMNS: tuple[str, ...] = (
    "doc_id",
    "chunk_index",
    "department",
    "access_level",
    "title",
    "chunk_text",
    "published_at",
    "available_at",
    "effective_from",
    "effective_to",
)

# dtype mong đợi sau khi đọc. Đơn vị datetime là [us] vì pandas 3.x đọc ở microsecond
# — con số này lấy từ một lần chạy thật, không phải đoán.
EXPECTED_DTYPES: dict[str, str] = {
    "doc_id": "string",
    "chunk_index": "int64",
    "department": "string",
    "access_level": "string",
    "title": "string",
    "chunk_text": "string",
    "published_at": "datetime64[us, UTC]",
    "available_at": "datetime64[us, UTC]",
    "effective_from": "datetime64[us]",
    "effective_to": "datetime64[us]",
}


class Severity(StrEnum):
    FATAL = "fatal"
    WARNING = "warning"


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: Severity
    row_index: int
    detail: str


@dataclass
class ValidationResult:
    """Kết quả kiểm một batch: dòng nhận, dòng loại, và lý do từng dòng."""

    accepted: pd.DataFrame
    quarantined: pd.DataFrame
    violations: list[Violation] = field(default_factory=list)

    def count_by_rule(self) -> dict[str, int]:
        """Đếm theo từng quy tắc. Một số tổng không cho biết phải sửa gì."""
        out: dict[str, int] = {}
        for v in self.violations:
            out[v.rule] = out.get(v.rule, 0) + 1
        return dict(sorted(out.items()))


class ContractError(Exception):
    """Vi phạm mức batch, không phải mức dòng: loại vài dòng không sửa được."""


def check_schema(frame: pd.DataFrame) -> None:
    """Kiểm schema ở mức batch. Thiếu cột là lỗi của cả batch, không của một dòng."""
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ContractError(
            f"Thiếu cột bắt buộc: {missing}. Nguồn đã đổi schema — phải dừng ingest và "
            f"xem lại nguồn, không được tự điền giá trị mặc định."
        )


def check_dtypes(frame: pd.DataFrame) -> list[str]:
    """So dtype thực tế với contract, trả về danh sách lệch (không raise).

    Báo cáo chứ không FATAL: một lệch đơn vị datetime không làm sai dữ liệu, nhưng
    nếu không ai báo thì cũng không biết nguồn đã đổi gì. Khi có lệch, phải xác định
    *ai* sai — contract đoán sai, nguồn đổi kiểu, hay bước đọc sai — rồi mới sửa.
    """
    return [
        f"{col}: contract={want} actual={frame[col].dtype}"
        for col, want in EXPECTED_DTYPES.items()
        if col in frame.columns and str(frame[col].dtype) != want
    ]


def validate(frame: pd.DataFrame) -> ValidationResult:
    """Áp toàn bộ quy tắc mức dòng, trả về phần nhận được và phần bị loại."""
    check_schema(frame)

    violations: list[Violation] = []
    fatal_rows: set[int] = set()

    def fail(rule: str, mask: pd.Series, detail: str) -> None:
        for idx in frame.index[mask.fillna(False)]:
            violations.append(Violation(rule, Severity.FATAL, int(idx), detail))
            fatal_rows.add(int(idx))

    def warn(rule: str, mask: pd.Series, detail: str) -> None:
        for idx in frame.index[mask.fillna(False)]:
            violations.append(Violation(rule, Severity.WARNING, int(idx), detail))

    # R1. Khóa trùng: FATAL vì nó nhân bản dòng ở mọi JOIN phía sau mà không báo lỗi.
    # keep=False đánh dấu TẤT CẢ bản sao — khi đã trùng thì không có căn cứ nào để tin
    # bản nào là bản đúng, nên giữ bản đầu chỉ là chọn theo thứ tự dòng trong file.
    fail(
        "R1_duplicate_key",
        frame.duplicated(subset=list(NATURAL_KEY), keep=False),
        f"Trùng khóa tự nhiên {NATURAL_KEY}",
    )

    # R2. Trường bắt buộc rỗng. isna() một mình không bắt được "" và "   ".
    for col in ("doc_id", "department", "access_level", "title", "chunk_text"):
        empty = frame[col].isna() | (frame[col].astype("string").str.strip() == "")
        fail("R2_missing_required", empty, f"Trường bắt buộc rỗng: {col}")

    # R3. Giá trị ngoài tập cho phép. Với access_level đây là ranh giới bảo mật: một
    # giá trị lạ nghĩa là hệ thống không biết ai được đọc, và hạ nó xuống mức thấp
    # nhất cho tiện có thể đang công khai một tài liệu mật. Fail-closed, không đoán.
    fail(
        "R3_access_level_not_allowed",
        frame["access_level"].notna() & ~frame["access_level"].isin(ALLOWED_ACCESS_LEVELS),
        f"Ngoài tập {sorted(ALLOWED_ACCESS_LEVELS)}",
    )
    fail(
        "R3_department_not_allowed",
        frame["department"].notna() & ~frame["department"].isin(ALLOWED_DEPARTMENTS),
        f"Ngoài tập {sorted(ALLOWED_DEPARTMENTS)}",
    )

    # R4. Khoảng hiệu lực ngược chiều: từng cột đều hợp lệ nhưng đi cùng nhau thì mọi
    # truy vấn "còn hiệu lực ngày X" trả sai.
    fail(
        "R4_interval_reversed",
        frame["effective_to"].notna() & (frame["effective_from"] > frame["effective_to"]),
        "effective_from > effective_to",
    )

    # R5. Dữ liệu không thể dùng được trước khi nó tồn tại. Tin một available_at như
    # vậy sẽ cho phép truy vấn point-in-time đọc thứ chưa có tại thời điểm đó.
    fail(
        "R5_available_before_published",
        frame["available_at"] < frame["published_at"],
        "available_at < published_at",
    )

    # R6. effective_to rỗng là trạng thái HỢP LỆ, nghĩa là còn hiệu lực. Chỉ WARNING,
    # nhưng vẫn đếm: tỷ lệ nhảy vọt có thể nghĩa là nguồn thôi gửi trường này.
    warn("R6_open_ended_validity", frame["effective_to"].isna(), "effective_to rỗng")

    keep = ~frame.index.isin(fatal_rows)
    accepted = frame.loc[keep].copy()
    quarantined = frame.loc[~keep].copy()

    # Gom mọi lý do FATAL của cùng một dòng vào một chuỗi đọc được, để người xử lý sự
    # cố không phải mở code mới biết dòng đó sai gì.
    reasons: dict[int, list[str]] = {}
    for v in violations:
        if v.severity is Severity.FATAL:
            reasons.setdefault(v.row_index, []).append(f"{v.rule}: {v.detail}")
    if not quarantined.empty:
        quarantined["reject_reason"] = [
            " | ".join(reasons.get(int(i), [])) for i in quarantined.index
        ]

    return ValidationResult(accepted=accepted, quarantined=quarantined, violations=violations)
