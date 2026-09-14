"""Dense retrieval trên doc_chunks: lọc quyền và thời điểm trước, xếp hạng bằng
embedding sau. Xem ADR-009 cho quyết định phạm vi quyền của docs retrieval.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from pgvector.psycopg import register_vector

from src.db import get_connection
from src.embeddings import embed
from src.scope import visible_access_levels


@dataclass(frozen=True)
class RetrievedChunk:
    doc_id: str
    chunk_index: int
    chunk_text: str
    department: str
    access_level: str
    distance: float

    @property
    def chunk_id(self) -> str:
        return f"{self.doc_id}#{self.chunk_index}"


def retrieve(
    question: str, *, role: str, as_of: datetime | None = None, k: int = 5
) -> list[RetrievedChunk]:
    """Trả về top-k chunk trong phạm vi quyền của role, xếp theo cosine distance.

    Thứ tự bắt buộc: lọc quyền và thời điểm nằm trong WHERE, chạy TRƯỚC khi
    PostgreSQL tính khoảng cách và sắp xếp — không lọc kết quả đã xếp hạng sau khi
    trả về. Một chunk vượt quyền không bao giờ vào ứng viên, không phải bị cắt sau.

    Args:
        role: Xác định tập access_level được thấy. Role lạ trả về danh sách rỗng ở
            ``visible_access_levels``, nên WHERE ``access_level = ANY('{}')`` không
            khớp gì — hệ thống không thấy chunk nào, không đoán quyền.
        as_of: Thời điểm point-in-time. Mặc định là hiện tại — dùng để tái lập một
            kết quả tại một mốc cụ thể trong test và trong lab.
        k: Số chunk tối đa trả về. Không phải ngân sách token (đó là việc của bước
           lập prompt); đây chỉ là số ứng viên đưa vào bước đó.
    """
    as_of = as_of or datetime.now(UTC)
    levels = visible_access_levels(role)
    if not levels:
        return []

    query_vector = embed(question, task_type="RETRIEVAL_QUERY")

    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        register_vector(conn)
        cur.execute(
            """
            SELECT doc_id, chunk_index, chunk_text, department, access_level,
                   embedding <=> %(qvec)s::vector AS distance
            FROM doc_chunks
            WHERE access_level = ANY(%(levels)s)
              AND available_at <= %(as_of)s
              AND effective_from <= %(as_of)s::date
              AND (effective_to IS NULL OR effective_to >= %(as_of)s::date)
              AND embedding IS NOT NULL
            ORDER BY distance ASC
            LIMIT %(k)s
            """,
            {"qvec": query_vector, "levels": levels, "as_of": as_of, "k": k},
        )
        rows = cur.fetchall()

    return [
        RetrievedChunk(
            doc_id=r["doc_id"],
            chunk_index=r["chunk_index"],
            chunk_text=r["chunk_text"],
            department=r["department"],
            access_level=r["access_level"],
            distance=float(r["distance"]),
        )
        for r in rows
    ]
