"""Module truy vấn tài liệu ngữ nghĩa (Dense Retrieval) bằng pgvector kết hợp lọc RBAC."""

from dataclasses import dataclass
from datetime import UTC, datetime

from pgvector.psycopg import register_vector

from src.db import get_connection
from src.embeddings import embed
from src.scope import visible_access_levels


# 1. Retrieved Chunk Data Model
@dataclass(frozen=True)
class RetrievedChunk:
    """Mô hình dữ liệu một đoạn văn bản được trích xuất từ cơ sở dữ liệu sau khi xếp hạng."""

    doc_id: str
    chunk_index: int
    chunk_text: str
    department: str
    access_level: str
    distance: float

    @property
    def chunk_id(self) -> str:
        """Mã định danh duy nhất của chunk theo cấu trúc: doc_id#chunk_index."""
        return f"{self.doc_id}#{self.chunk_index}"


# 2. Dense Vector Retrieval with Pre-filtering & Point-in-Time
def retrieve(
    question: str, *, role: str, as_of: datetime | None = None, k: int = 5
) -> list[RetrievedChunk]:
    """Truy vấn top-k đoạn văn bản phù hợp nhất bằng khoảng cách cosine trong phạm vi quyền hạn.

    Nguyên tắc bảo mật & vận hành (ADR-009):
    - Lọc quyền (Pre-filtering): Lọc access_level ngay trong mệnh đề WHERE của SQL TRƯỚC KHI tính
      toán khoảng cách. Tuyệt đối không tính vector rồi mới lọc ở RAM (tránh rò rỉ tài liệu mật).
    - Point-in-Time: Kiểm tra mốc khả dụng (available_at) và hiệu lực chính sách (effective dates).
    - Ép kiểu tường minh %(qvec)s::vector để psycopg không bị nhầm sang mảng double precision[].

    Args:
        question: Câu hỏi ngôn ngữ tự nhiên của người dùng.
        role: Chức vụ của người gọi để xác định tập access_level được phép xem.
        as_of: Mốc thời gian hiệu lực (mặc định là hiện tại, dùng để tái lập kết quả trong test).
        k: Số lượng chunk tối đa cần lấy.

    Returns:
        Danh sách RetrievedChunk được sắp xếp theo khoảng cách cosine tăng dần (gần nhất trước).
    """
    as_of = as_of or datetime.now(UTC)
    levels = visible_access_levels(role)
    # Fail-closed: Role lạ không có quyền xem bất kỳ cấp độ nào -> Trả về rỗng ngay lập tức
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
