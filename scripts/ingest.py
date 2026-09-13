"""Ingest một batch document chunk: đọc → kiểm contract → ghi → manifest.

Chạy:
    docker compose up -d db
    uv run python -m scripts.ingest                            # corpus chính
    uv run python -m scripts.ingest data/documents_dirty.csv   # xem quarantine hoạt động

Dùng ``-m`` chứ không phải ``python scripts/ingest.py``: cách đó đặt project root vào
sys.path nên ``import src...`` hoạt động, không cần chèn sys.path trong code.

Chạy lại cùng một file **không** được làm tăng số dòng trong doc_chunks. Batch bị chạy
lại thường xuyên hơn người ta tưởng: job retry, backfill, hoặc có người gõ lại lệnh vì
không chắc lần trước đã xong.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from src.contracts import (
    CONTRACT_VERSION,
    ContractError,
    ValidationResult,
    check_dtypes,
    validate,
)
from src.db import get_connection

DEFAULT_SOURCE = Path("data/documents.csv")


def read_batch(path: Path) -> pd.DataFrame:
    """Đọc CSV với dtype chỉ định rõ, không để pandas tự đoán.

    Tự đoán dtype là nơi sinh lỗi im lặng: mã dạng "001" thành số 1, cột số nguyên có
    một ô rỗng thành float. Chỉ định trước thì sai kiểu thành lỗi đọc, thấy được ngay.
    """
    frame = pd.read_csv(
        path,
        dtype={
            "doc_id": "string",
            "department": "string",
            "access_level": "string",
            "title": "string",
            "chunk_text": "string",
        },
        parse_dates=["published_at", "available_at", "effective_from", "effective_to"],
    )
    frame["chunk_index"] = frame["chunk_index"].astype("int64")
    return frame


def file_fingerprint(path: Path) -> str:
    """SHA-256 của file nguồn, phần lineage tối thiểu để truy lại đúng batch nào."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _as_db_value(value: Any) -> Any:
    """NaT/NA của pandas sang None, vì psycopg không nhận hai kiểu đó."""
    return None if pd.isna(value) else value


def write_batch(
    result: ValidationResult, *, source: Path, source_hash: str, started_at: datetime
) -> dict[str, Any]:
    """Ghi dòng hợp lệ, dòng bị loại và manifest trong MỘT transaction.

    Một transaction cho cả ba: nếu manifest ghi thất bại thì dữ liệu cũng không vào,
    nên không bao giờ có batch đã ghi mà không có bản ghi nào nói nó đã chạy.
    """
    now = datetime.now(UTC)
    inserted = updated = 0

    with get_connection(read_only=False) as conn, conn.cursor() as cur:
        before = cur.execute("SELECT COUNT(*) AS n FROM doc_chunks").fetchone()
        assert before is not None

        for row in result.accepted.to_dict(orient="records"):
            # ON CONFLICT DO UPDATE trên khóa tự nhiên: chạy lại thì cập nhật tại chỗ
            # thay vì thêm bản sao. RETURNING (xmax = 0) cho biết dòng vừa rồi là
            # insert mới hay update — dòng mới chèn có xmax bằng 0.
            cur.execute(
                """
                INSERT INTO doc_chunks (
                    doc_id, chunk_index, department, access_level, title, chunk_text,
                    published_at, available_at, effective_from, effective_to,
                    source_file, source_hash, contract_version, ingested_at
                ) VALUES (
                    %(doc_id)s, %(chunk_index)s, %(department)s, %(access_level)s,
                    %(title)s, %(chunk_text)s, %(published_at)s, %(available_at)s,
                    %(effective_from)s, %(effective_to)s,
                    %(source_file)s, %(source_hash)s, %(contract_version)s, %(ingested_at)s
                )
                ON CONFLICT (doc_id, chunk_index) DO UPDATE SET
                    department = EXCLUDED.department,
                    access_level = EXCLUDED.access_level,
                    title = EXCLUDED.title,
                    chunk_text = EXCLUDED.chunk_text,
                    published_at = EXCLUDED.published_at,
                    available_at = EXCLUDED.available_at,
                    effective_from = EXCLUDED.effective_from,
                    effective_to = EXCLUDED.effective_to,
                    source_hash = EXCLUDED.source_hash,
                    contract_version = EXCLUDED.contract_version,
                    ingested_at = EXCLUDED.ingested_at
                RETURNING (xmax = 0) AS was_insert
                """,
                {
                    "doc_id": row["doc_id"],
                    "chunk_index": int(row["chunk_index"]),
                    "department": row["department"],
                    "access_level": row["access_level"],
                    "title": row["title"],
                    "chunk_text": row["chunk_text"],
                    "published_at": row["published_at"],
                    "available_at": row["available_at"],
                    "effective_from": row["effective_from"],
                    "effective_to": _as_db_value(row["effective_to"]),
                    "source_file": source.name,
                    "source_hash": source_hash,
                    "contract_version": CONTRACT_VERSION,
                    "ingested_at": now,
                },
            )
            outcome = cur.fetchone()
            assert outcome is not None
            if outcome["was_insert"]:
                inserted += 1
            else:
                updated += 1

        for row in result.quarantined.to_dict(orient="records"):
            cur.execute(
                """
                INSERT INTO doc_chunks_quarantine (
                    doc_id, chunk_index, raw_row, reject_reason,
                    source_file, source_hash, contract_version, ingested_at
                ) VALUES (
                    %(doc_id)s, %(chunk_index)s, %(raw_row)s, %(reject_reason)s,
                    %(source_file)s, %(source_hash)s, %(contract_version)s, %(ingested_at)s
                )
                """,
                {
                    "doc_id": _as_db_value(row["doc_id"]),
                    "chunk_index": int(row["chunk_index"]),
                    "raw_row": json.dumps(
                        {str(k): str(v) for k, v in row.items()}, ensure_ascii=False
                    ),
                    "reject_reason": row["reject_reason"],
                    "source_file": source.name,
                    "source_hash": source_hash,
                    "contract_version": CONTRACT_VERSION,
                    "ingested_at": now,
                },
            )

        after = cur.execute("SELECT COUNT(*) AS n FROM doc_chunks").fetchone()
        assert after is not None

        manifest = {
            "source_file": source.name,
            "source_hash": source_hash,
            "contract_version": CONTRACT_VERSION,
            "rows_in_file": int(len(result.accepted) + len(result.quarantined)),
            "rows_accepted": int(len(result.accepted)),
            "rows_quarantined": int(len(result.quarantined)),
            "rows_inserted": inserted,
            "rows_updated": updated,
            "violations": json.dumps(result.count_by_rule(), ensure_ascii=False),
            "started_at": started_at,
            "finished_at": datetime.now(UTC),
        }
        cur.execute(
            """
            INSERT INTO ingest_run (
                source_file, source_hash, contract_version,
                rows_in_file, rows_accepted, rows_quarantined,
                rows_inserted, rows_updated, violations, started_at, finished_at
            ) VALUES (
                %(source_file)s, %(source_hash)s, %(contract_version)s,
                %(rows_in_file)s, %(rows_accepted)s, %(rows_quarantined)s,
                %(rows_inserted)s, %(rows_updated)s, %(violations)s,
                %(started_at)s, %(finished_at)s
            )
            RETURNING run_id
            """,
            manifest,
        )
        run = cur.fetchone()
        assert run is not None
        conn.commit()

    return {
        "run_id": run["run_id"],
        "source_file": source.name,
        "rows_in_file": manifest["rows_in_file"],
        "rows_accepted": manifest["rows_accepted"],
        "rows_quarantined": manifest["rows_quarantined"],
        "inserted": inserted,
        "updated": updated,
        "doc_chunks_before": before["n"],
        "doc_chunks_after": after["n"],
        "violations_by_rule": result.count_by_rule(),
    }


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else DEFAULT_SOURCE
    if not source.exists():
        print(f"Không tìm thấy file nguồn: {source}")
        return 2

    started_at = datetime.now(UTC)
    frame = read_batch(source)
    dtype_mismatches = check_dtypes(frame)

    try:
        result = validate(frame)
    except ContractError as exc:
        # Lỗi mức batch: dừng hẳn, không dòng nào được ghi. Vấn đề nằm ở cấu trúc
        # nguồn, không ở vài dòng xấu, nên ingest một phần chỉ tạo dữ liệu thiếu.
        print(f"CONTRACT ERROR (batch bị từ chối): {exc}")
        return 1

    summary = write_batch(
        result, source=source, source_hash=file_fingerprint(source), started_at=started_at
    )
    summary["dtype_mismatches"] = dtype_mismatches
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
