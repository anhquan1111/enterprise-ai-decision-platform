"""Embed mọi chunk chưa có vector, ghi thẳng vào cột doc_chunks.embedding.

    uv run python -m scripts.backfill_embeddings

Idempotent: chỉ xử lý dòng có embedding IS NULL, nên chạy lại không tốn thêm lệnh gọi
API cho những chunk đã có vector. Việc này quan trọng vì mỗi lần gọi Gemini đều tính
vào hạn mức miễn phí theo ngày.
"""

import sys
import time

from pgvector.psycopg import register_vector

from src.db import get_connection
from src.embeddings import embed


def main() -> int:
    with get_connection(read_only=False) as conn, conn.cursor() as cur:
        register_vector(conn)

        cur.execute(
            "SELECT doc_id, chunk_index, chunk_text FROM doc_chunks "
            "WHERE embedding IS NULL ORDER BY doc_id, chunk_index"
        )
        rows = cur.fetchall()

        if not rows:
            print("Không có chunk nào cần embed — mọi thứ đã sẵn sàng.")
            return 0

        print(f"Cần embed {len(rows)} chunk.")
        for i, row in enumerate(rows, 1):
            vector = embed(row["chunk_text"], task_type="RETRIEVAL_DOCUMENT")
            cur.execute(
                "UPDATE doc_chunks SET embedding = %(v)s "
                "WHERE doc_id = %(doc_id)s AND chunk_index = %(chunk_index)s",
                {"v": vector, "doc_id": row["doc_id"], "chunk_index": row["chunk_index"]},
            )
            print(f"  [{i}/{len(rows)}] {row['doc_id']}#{row['chunk_index']} đã embed")
            # Rải nhẹ lệnh gọi để không dồn dập vào giới hạn requests-per-minute của
            # free tier — 16 chunk là ít, nhưng thói quen này cần giữ khi corpus lớn
            # hơn nhiều lần.
            time.sleep(0.5)

        conn.commit()

    with get_connection(read_only=True) as conn, conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM doc_chunks WHERE embedding IS NULL")
        remaining = cur.fetchone()
        assert remaining is not None
        print(f"Còn lại chưa embed: {remaining['n']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
