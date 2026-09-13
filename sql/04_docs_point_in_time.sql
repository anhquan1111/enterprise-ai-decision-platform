-- Tài liệu mà một người gọi ĐƯỢC PHÉP đọc tại một thời điểm.
--
-- Ba điều kiện độc lập, hay bị gộp thành một:
--   1. Phạm vi quyền      — department + access_level của người gọi
--   2. Đã có trong hệ thống — available_at <= as_of  (point-in-time của ngày 6)
--   3. Còn hiệu lực nghiệp vụ — as_of nằm trong [effective_from, effective_to]
--
-- Một tài liệu đã published nhưng available_at sau as_of thì KHÔNG được dùng: ở
-- thời điểm as_of hệ thống chưa có nó. Lọc thiếu điều kiện 2 là cách leakage đi vào
-- một hệ thống retrieval.

SELECT doc_id,
       chunk_index,
       department,
       access_level,
       title,
       effective_from,
       effective_to
FROM doc_chunks
WHERE department = %(department)s
  -- Thứ bậc quyền: employee thấy 1 mức, manager thấy 2, executive thấy cả 3.
  AND access_level = ANY(%(allowed_levels)s)
  AND available_at <= %(as_of)s
  AND effective_from <= %(as_of)s::date
  AND (effective_to IS NULL OR effective_to >= %(as_of)s::date)
ORDER BY doc_id, chunk_index;
