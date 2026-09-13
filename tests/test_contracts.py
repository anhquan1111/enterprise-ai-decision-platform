"""Test contract dữ liệu — kiểm quy tắc, không kiểm implementation.

Mỗi quy tắc có **một ca xấu đã biết** và ca đó phải bị bắt, cộng một ca tốt phải đi
qua: một contract chặn tất cả thì vô dụng ngang contract không chặn gì.

Các test này phát biểu về *dữ liệu*, nên chúng vẫn đúng nếu sau này validate() được
viết lại bằng pandera hoặc bằng SQL thuần.
"""

import pandas as pd
import pytest

from src.contracts import ContractError, Severity, validate, visible_access_levels


def make_row(**overrides: object) -> dict[str, object]:
    """Một dòng hợp lệ; test ghi đè đúng một trường để tách biệt quy tắc cần kiểm."""
    row: dict[str, object] = {
        "doc_id": "HR-001",
        "chunk_index": 0,
        "department": "hr",
        "access_level": "employee",
        "title": "Quy dinh nghi phep",
        "chunk_text": "Nhan vien duoc 12 ngay phep mot nam.",
        "published_at": pd.Timestamp("2026-01-10 09:00", tz="UTC"),
        "available_at": pd.Timestamp("2026-01-10 10:00", tz="UTC"),
        "effective_from": pd.Timestamp("2026-01-01"),
        "effective_to": pd.Timestamp("2026-12-31"),
    }
    row.update(overrides)
    return row


def frame_of(*rows: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(list(rows))


def test_valid_row_is_accepted() -> None:
    result = validate(frame_of(make_row()))

    assert len(result.accepted) == 1
    assert result.quarantined.empty


def test_duplicate_key_quarantines_every_copy() -> None:
    """Cả hai bản sao bị loại, không giữ bản đầu.

    Khi khóa đã trùng thì không có căn cứ nào để tin bản nào đúng; giữ bản đầu là chọn
    theo thứ tự dòng trong file, một thứ tự không mang ý nghĩa nghiệp vụ.
    """
    result = validate(frame_of(make_row(), make_row(chunk_text="ban sao")))

    assert result.accepted.empty
    assert len(result.quarantined) == 2
    assert result.count_by_rule()["R1_duplicate_key"] == 2


def test_missing_required_field_is_fatal() -> None:
    result = validate(frame_of(make_row(department="")))

    assert result.accepted.empty
    assert "R2_missing_required" in result.count_by_rule()


def test_unknown_access_level_is_fatal_not_downgraded() -> None:
    """Mức quyền lạ bị loại, không hạ xuống mức thấp nhất cho tiện.

    Một mức lạ rất có thể là mức CAO hơn executive; hạ nó xuống employee là công khai
    một tài liệu mật. Fail-closed là hướng an toàn duy nhất ở đây.
    """
    result = validate(frame_of(make_row(access_level="top_secret")))

    assert result.accepted.empty
    assert "R3_access_level_not_allowed" in result.count_by_rule()


def test_unknown_department_is_fatal() -> None:
    result = validate(frame_of(make_row(department="legal")))

    assert result.accepted.empty
    assert "R3_department_not_allowed" in result.count_by_rule()


def test_reversed_validity_interval_is_fatal() -> None:
    result = validate(
        frame_of(
            make_row(
                effective_from=pd.Timestamp("2026-08-01"),
                effective_to=pd.Timestamp("2026-03-01"),
            )
        )
    )

    assert result.accepted.empty
    assert "R4_interval_reversed" in result.count_by_rule()


def test_available_before_published_is_fatal() -> None:
    """Dữ liệu không thể dùng được trước khi nó tồn tại.

    Tin một available_at như vậy sẽ cho phép truy vấn point-in-time đọc thứ chưa có
    tại thời điểm đó.
    """
    result = validate(
        frame_of(
            make_row(
                published_at=pd.Timestamp("2026-05-02 10:00", tz="UTC"),
                available_at=pd.Timestamp("2026-05-02 08:00", tz="UTC"),
            )
        )
    )

    assert result.accepted.empty
    assert "R5_available_before_published" in result.count_by_rule()


def test_open_ended_validity_is_warning_and_still_ingested() -> None:
    """effective_to rỗng nghĩa là "còn hiệu lực" — hợp lệ, nhưng phải đếm được."""
    result = validate(frame_of(make_row(effective_to=pd.NaT)))

    assert len(result.accepted) == 1
    assert [v.severity for v in result.violations] == [Severity.WARNING]


def test_missing_column_raises_instead_of_dropping_rows() -> None:
    """Thiếu cột là lỗi mức batch: dừng, không ingest một phần."""
    frame = frame_of(make_row()).drop(columns=["access_level"])

    with pytest.raises(ContractError, match="access_level"):
        validate(frame)


def test_quarantined_row_carries_a_readable_reason() -> None:
    result = validate(frame_of(make_row(access_level="top_secret")))

    reason = result.quarantined.iloc[0]["reject_reason"]
    assert "R3_access_level_not_allowed" in reason
    assert "employee" in reason


def test_one_row_can_break_several_rules() -> None:
    """Báo mọi vi phạm của một dòng, không dừng ở vi phạm đầu tiên."""
    result = validate(frame_of(make_row(department="", access_level="top_secret")))

    rules = set(result.count_by_rule())
    assert {"R2_missing_required", "R3_access_level_not_allowed"} <= rules


def test_role_sees_its_own_level_and_below() -> None:
    assert visible_access_levels("employee") == ["employee"]
    assert visible_access_levels("manager") == ["employee", "manager"]
    assert visible_access_levels("executive") == ["employee", "manager", "executive"]


def test_unknown_role_sees_nothing() -> None:
    """Role lạ trả về danh sách rỗng, không phải mức thấp nhất.

    Không biết người gọi là ai thì không cho thấy gì. Trả về ["employee"] sẽ biến một
    request sai thành một request được phục vụ.
    """
    assert visible_access_levels("ceo_of_everything") == []
