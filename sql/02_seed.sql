-- Dữ liệu nghiệp vụ tổng hợp, tự viết cho project này. Không phải dữ liệu thật của
-- công ty nào.
--
-- Quy mô nhỏ có chủ ý: 4 phòng ban x 6 tháng = 24 dòng doanh thu, đủ để tính tay và
-- kiểm query bằng mắt. Mốc thời gian cố định ở 2026 nên chạy lại không phụ thuộc
-- ngày hôm nay.

-- Seed idempotent bằng ON CONFLICT, không TRUNCATE. Lý do cụ thể: doc_chunks tham
-- chiếu departments, nên TRUNCATE ... CASCADE ở đây sẽ xóa luôn toàn bộ corpus tài
-- liệu đã ingest. Chạy lại file này bao nhiêu lần cũng an toàn.

INSERT INTO departments (department, full_name) VALUES
    ('sales',       'Khoi Kinh doanh'),
    ('hr',          'Khoi Nhan su'),
    ('finance',     'Khoi Tai chinh'),
    ('engineering', 'Khoi Ky thuat')
ON CONFLICT (department) DO UPDATE SET full_name = EXCLUDED.full_name;

INSERT INTO employees (employee_id, full_name, department, role) VALUES
    ('emp_001', 'Nguyen Van A', 'sales',       'employee'),
    ('emp_002', 'Tran Thi B',   'sales',       'manager'),
    ('emp_003', 'Le Van C',     'finance',     'employee'),
    ('emp_004', 'Pham Thi D',   'finance',     'manager'),
    ('emp_005', 'Hoang Van E',  'hr',          'employee'),
    ('emp_006', 'Vu Thi F',     'engineering', 'employee'),
    ('emp_007', 'Dang Van G',   'engineering', 'manager'),
    ('emp_008', 'Bui Thi H',    'finance',     'executive')
ON CONFLICT (employee_id) DO UPDATE SET
    full_name  = EXCLUDED.full_name,
    department = EXCLUDED.department,
    role       = EXCLUDED.role;

-- Doanh thu 6 tháng đầu 2026. Hai điểm được gài có chủ ý:
--   * sales tháng 3 GIẢM so với tháng 2 -> kiểm được window function tính tăng trưởng
--     ra số âm đúng chỗ.
--   * tháng 6 của mọi phòng ban is_final = FALSE -> số chưa chốt sổ.
INSERT INTO monthly_revenue (department, month, revenue_vnd, is_final) VALUES
    ('sales',       '2026-01-01', 4200000000, TRUE),
    ('sales',       '2026-02-01', 4800000000, TRUE),
    ('sales',       '2026-03-01', 4100000000, TRUE),
    ('sales',       '2026-04-01', 5300000000, TRUE),
    ('sales',       '2026-05-01', 5900000000, TRUE),
    ('sales',       '2026-06-01', 3100000000, FALSE),

    ('finance',     '2026-01-01',  820000000, TRUE),
    ('finance',     '2026-02-01',  860000000, TRUE),
    ('finance',     '2026-03-01',  910000000, TRUE),
    ('finance',     '2026-04-01',  880000000, TRUE),
    ('finance',     '2026-05-01',  940000000, TRUE),
    ('finance',     '2026-06-01',  500000000, FALSE),

    ('engineering', '2026-01-01', 1500000000, TRUE),
    ('engineering', '2026-02-01', 1620000000, TRUE),
    ('engineering', '2026-03-01', 1710000000, TRUE),
    ('engineering', '2026-04-01', 1680000000, TRUE),
    ('engineering', '2026-05-01', 1800000000, TRUE),
    ('engineering', '2026-06-01',  950000000, FALSE),

    ('hr',          '2026-01-01',   40000000, TRUE),
    ('hr',          '2026-02-01',   42000000, TRUE),
    ('hr',          '2026-03-01',   39000000, TRUE),
    ('hr',          '2026-04-01',   45000000, TRUE),
    ('hr',          '2026-05-01',   47000000, TRUE),
    ('hr',          '2026-06-01',   20000000, FALSE)
ON CONFLICT (department, month) DO UPDATE SET
    revenue_vnd = EXCLUDED.revenue_vnd,
    is_final    = EXCLUDED.is_final;
