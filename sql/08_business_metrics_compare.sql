-- Truy vấn cho tool SQL, biến thể SO SÁNH: doanh thu MỌI phòng ban trong cùng
-- khoảng thời gian, kèm tăng trưởng theo tháng của từng phòng ban.
--
-- Khác 03_business_metrics.sql: KHÔNG có tham số department trong WHERE — trả về
-- mọi phòng ban. LƯU Ý CHO NGƯỜI SỬA FILE NÀY SAU: không gõ ký tự phần trăm trong
-- bất kỳ comment nào của file .sql này, kể cả để MÔ TẢ cú pháp tham số — psycopg
-- quét toàn bộ văn bản câu lệnh (kể cả bên trong comment) để tìm token cần bind,
-- và một ký tự phần trăm "mồ côi" từng làm nó ném ProgrammingError lúc chạy thật,
-- hai lần liên tiếp, vì hai cách viết khác nhau đều vẫn còn ký tự đó. Xem
-- docs/decisions.md ADR-030.
-- Vì vậy tool gọi câu này (src/agent/tools.py, query_type="compare_departments")
-- chỉ cho phép role="executive" (scope.can_compare_departments) — một employee/manager
-- dù đúng phòng ban mình cũng không có lý do nghiệp vụ thấy số liệu phòng ban khác
-- chỉ vì nó đi kèm trong bảng so sánh này.
--
-- Giữ đúng grain một dòng cho mỗi (phòng ban, tháng), giống file 03 — JOIN sang
-- departments là many-to-one, không nhân bản dòng.

WITH monthly AS (
    SELECT r.department,
           d.full_name,
           r.month,
           r.revenue_vnd,
           r.is_final
    FROM monthly_revenue r
    JOIN departments d ON d.department = r.department
    WHERE r.month >= %(month_from)s
      AND r.month <= %(month_to)s
)
SELECT department,
       full_name,
       month,
       revenue_vnd,
       is_final,
       -- Ở đây PARTITION BY department thực sự có tác dụng (khác file 03, nơi CTE
       -- đã lọc còn đúng một phòng ban): mỗi phòng ban tính tăng trưởng riêng, không
       -- lẫn tháng cuối của phòng này với tháng đầu của phòng khác.
       LAG(revenue_vnd) OVER (PARTITION BY department ORDER BY month) AS prev_revenue_vnd,
       ROUND(
           100.0 * (revenue_vnd - LAG(revenue_vnd) OVER (PARTITION BY department ORDER BY month))
           / NULLIF(LAG(revenue_vnd) OVER (PARTITION BY department ORDER BY month), 0),
           1
       ) AS mom_growth_pct
FROM monthly
ORDER BY month, department;
