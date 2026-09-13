-- Truy vấn cho tool SQL: doanh thu theo phòng ban và tháng, kèm tăng trưởng.
--
-- Giữ đúng grain một dòng cho mỗi (phòng ban, tháng). JOIN sang departments là
-- many-to-one nhờ khóa chính bên đó, nên không nhân bản dòng — đây là điều phải
-- kiểm chứ không phải giả định, xem tests/test_sql_integration.py.

WITH monthly AS (
    SELECT r.department,
           d.full_name,
           r.month,
           r.revenue_vnd,
           r.is_final
    FROM monthly_revenue r
    JOIN departments d ON d.department = r.department
    WHERE r.department = %(department)s
      AND r.month >= %(month_from)s
      AND r.month <= %(month_to)s
)
SELECT department,
       full_name,
       month,
       revenue_vnd,
       is_final,
       -- Window function: so với tháng liền trước TRONG CÙNG phòng ban. Thiếu
       -- PARTITION BY thì dòng đầu của phòng ban này sẽ lấy số của phòng ban trước.
       LAG(revenue_vnd) OVER (PARTITION BY department ORDER BY month) AS prev_revenue_vnd,
       ROUND(
           100.0 * (revenue_vnd - LAG(revenue_vnd) OVER (PARTITION BY department ORDER BY month))
           / NULLIF(LAG(revenue_vnd) OVER (PARTITION BY department ORDER BY month), 0),
           1
       ) AS mom_growth_pct
FROM monthly
ORDER BY month;
