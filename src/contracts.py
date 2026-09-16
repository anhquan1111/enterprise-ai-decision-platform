"""Data Contract cho doc_chunks: Kiểm tra schema, 6 quy tắc toàn vẹn và quarantine."""

# 1. Imports & Scope Re-exports
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

# 2. Contract Constants & Schema Definition
CONTRACT_VERSION = "1.0.0"

# Grain: Mỗi dòng đại diện cho một chunk duy nhất của một tài liệu
NATURAL_KEY: tuple[str, ...] = ("doc_id", "chunk_index")

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

# Kiểu dữ liệu mong đợi sau khi đọc CSV. Pandas 3.x parse datetime ở đơn vị microsecond [us]
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


# 3. Severity Levels & Data Models
class Severity(StrEnum):
    FATAL = "fatal"  # Dòng bị loại, đưa vào bảng quarantine kèm lý do reject_reason
    WARNING = "warning"  # Dòng vẫn được nạp vào bảng chính, chỉ ghi nhận để cảnh báo


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: Severity
    row_index: int
    detail: str


@dataclass
class ValidationResult:
    """Kết quả kiểm tra batch: dòng hợp lệ (accepted), bị cách ly (quarantined) và vi phạm."""

    accepted: pd.DataFrame
    quarantined: pd.DataFrame
    violations: list[Violation] = field(default_factory=list)

    def count_by_rule(self) -> dict[str, int]:
        """Thống kê số lượng vi phạm theo từng quy tắc để báo cáo telemetry/manifest."""
        out: dict[str, int] = {}
        for v in self.violations:
            out[v.rule] = out.get(v.rule, 0) + 1
        return dict(sorted(out.items()))


class ContractError(Exception):
    """Lỗi ở mức batch (như thiếu cột bắt buộc) — dừng pipeline, không thể sửa từng dòng."""


# 4. Batch-level Checks
def check_schema(frame: pd.DataFrame) -> None:
    """Kiểm tra sự hiện diện của các cột bắt buộc; thiếu cột sẽ ném exception dừng toàn bộ batch."""
    missing = [c for c in REQUIRED_COLUMNS if c not in frame.columns]
    if missing:
        raise ContractError(
            f"Thiếu cột bắt buộc: {missing}. Schema nguồn đã thay đổi — dừng nạp để kiểm tra."
        )


def check_dtypes(frame: pd.DataFrame) -> list[str]:
    """Đối chiếu kiểu dữ liệu thực tế với contract để cảnh báo lệch kiểu (không raise exception)."""
    return [
        f"{col}: contract={want} actual={frame[col].dtype}"
        for col, want in EXPECTED_DTYPES.items()
        if col in frame.columns and str(frame[col].dtype) != want
    ]


# 5. Row-level Validation Pipeline
def validate(frame: pd.DataFrame) -> ValidationResult:
    """Áp dụng 6 quy tắc kiểm tra từng dòng, tách riêng tập accepted và quarantined."""
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

    # R1. Trùng khóa chính (doc_id, chunk_index): FATAL. keep=False đánh dấu TẤT CẢ bản sao
    fail(
        "R1_duplicate_key",
        frame.duplicated(subset=list(NATURAL_KEY), keep=False),
        f"Trùng khóa tự nhiên {NATURAL_KEY}",
    )

    # R2. Trường bắt buộc bị rỗng: Kiểm tra cả isna() lẫn chuỗi toàn khoảng trắng
    for col in ("doc_id", "department", "access_level", "title", "chunk_text"):
        empty = frame[col].isna() | (frame[col].astype("string").str.strip() == "")
        fail("R2_missing_required", empty, f"Trường bắt buộc rỗng: {col}")

    # R3. Giá trị ngoài danh mục cho phép (Bảo mật: fail-closed, không tự ý hạ cấp quyền)
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

    # R4. Khoảng thời gian hiệu lực bị ngược: effective_from > effective_to
    fail(
        "R4_interval_reversed",
        frame["effective_to"].notna() & (frame["effective_from"] > frame["effective_to"]),
        "effective_from > effective_to",
    )

    # R5. Khả dụng trước khi công bố: available_at < published_at (ngăn rò rỉ dữ liệu)
    fail(
        "R5_available_before_published",
        frame["available_at"] < frame["published_at"],
        "available_at < published_at",
    )

    # R6. effective_to rỗng: Hợp lệ (văn bản vô thời hạn) — chỉ WARNING để theo dõi tỉ lệ
    warn("R6_open_ended_validity", frame["effective_to"].isna(), "effective_to rỗng")

    keep = ~frame.index.isin(fatal_rows)
    accepted = frame.loc[keep].copy()
    quarantined = frame.loc[~keep].copy()

    # Gom tất cả lý do FATAL của từng dòng thành chuỗi reject_reason chi tiết
    reasons: dict[int, list[str]] = {}
    for v in violations:
        if v.severity is Severity.FATAL:
            reasons.setdefault(v.row_index, []).append(f"{v.rule}: {v.detail}")
    if not quarantined.empty:
        quarantined["reject_reason"] = [
            " | ".join(reasons.get(int(i), [])) for i in quarantined.index
        ]

    return ValidationResult(accepted=accepted, quarantined=quarantined, violations=violations)
