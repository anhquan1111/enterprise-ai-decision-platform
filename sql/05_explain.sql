-- Thí nghiệm: index ix_chunks_scope có giúp gì không, và ở quy mô nào.
--
-- Chạy:
--   docker compose exec -T db psql -U app -d enterprise_ai -f /sql/05_explain.sql
--
-- Toàn bộ phần phình dữ liệu nằm trong một transaction kết thúc bằng ROLLBACK, nên
-- corpus thật không bị thay đổi. Đây là cách thử một thay đổi có hậu quả mà không
-- phải dựng lại database.
--
-- ANALYZE nghĩa là câu lệnh được chạy thật: số dòng và thời gian là số đo. So nó với
-- số ước lượng của planner cho biết thống kê của bảng có sát thực tế hay không.

\echo '=============== A. 16 dòng thật, CÓ index ==============='
EXPLAIN (ANALYZE, BUFFERS)
SELECT doc_id, chunk_index, title
FROM doc_chunks
WHERE department = 'finance'
  AND access_level = ANY(ARRAY['employee', 'manager'])
  AND available_at <= '2026-09-01 00:00+00';

BEGIN;

-- Nhân corpus lên ~20k dòng bằng generate_series. doc_id được gắn hậu tố nên không
-- đụng khóa chính của dữ liệu thật.
INSERT INTO doc_chunks (
    doc_id, chunk_index, department, access_level, title, chunk_text,
    published_at, available_at, effective_from,
    source_file, source_hash, contract_version, ingested_at
)
SELECT 'BULK-' || g,
       0,
       (ARRAY['sales', 'hr', 'finance', 'engineering'])[1 + (g % 4)],
       (ARRAY['employee', 'manager', 'executive'])[1 + (g % 3)],
       'Tai lieu sinh tu dong ' || g,
       'Noi dung sinh tu dong so ' || g,
       '2026-01-01 00:00+00'::timestamptz + (g % 200) * INTERVAL '1 day',
       '2026-01-01 01:00+00'::timestamptz + (g % 200) * INTERVAL '1 day',
       '2026-01-01'::date,
       'bulk', 'bulk', '1.0.0', now()
FROM generate_series(1, 20000) AS g;

-- Không ANALYZE thì planner vẫn dùng thống kê của bảng 16 dòng và chọn sai.
ANALYZE doc_chunks;

\echo '=============== B. ~20k dòng, CÓ index ==============='
EXPLAIN (ANALYZE, BUFFERS)
SELECT doc_id, chunk_index, title
FROM doc_chunks
WHERE department = 'finance'
  AND access_level = ANY(ARRAY['employee', 'manager'])
  AND available_at <= '2026-09-01 00:00+00';

DROP INDEX ix_chunks_scope;

\echo '=============== C. ~20k dòng, KHÔNG index ==============='
EXPLAIN (ANALYZE, BUFFERS)
SELECT doc_id, chunk_index, title
FROM doc_chunks
WHERE department = 'finance'
  AND access_level = ANY(ARRAY['employee', 'manager'])
  AND available_at <= '2026-09-01 00:00+00';

ROLLBACK;

\echo '=============== Sau ROLLBACK: dữ liệu và index còn nguyên ==============='
SELECT (SELECT COUNT(*) FROM doc_chunks) AS doc_chunks,
       (SELECT COUNT(*) FROM pg_indexes WHERE indexname = 'ix_chunks_scope') AS index_con;
