-- Nhân viên dành riêng cho việc chạy tập held-out thật qua HTTP (xem ADR-019,
-- ADR-024). Tách khỏi 8 nhân viên nghiệp vụ ở sql/02_seed.sql để không bao giờ phải
-- đụng tới key đã cấp cho họ khi cần một vòng held-out mới — mỗi vòng held-out có
-- bộ nhân viên/API key riêng, phát sinh mới thay vì tái dùng, đúng nguyên tắc idempotent
-- của scripts/issue_api_keys.py (không bao giờ cấp lại key cho nhân viên đã có).
--
-- 8 nhân viên = đúng 8 tổ hợp role×department mà eval/final.jsonl (v2) cần: cả 4
-- phòng ban ở mức employee, và manager/executive ở những phòng ban câu hỏi cần
-- kiểm quyền chặn/cho qua.

INSERT INTO employees (employee_id, full_name, department, role) VALUES
    ('emp_109', 'Held-out Eval — Sales / Employee',       'sales',       'employee'),
    ('emp_110', 'Held-out Eval — Sales / Manager',        'sales',       'manager'),
    ('emp_111', 'Held-out Eval — Finance / Employee',     'finance',     'employee'),
    ('emp_112', 'Held-out Eval — Finance / Manager',      'finance',     'manager'),
    ('emp_113', 'Held-out Eval — Finance / Executive',    'finance',     'executive'),
    ('emp_114', 'Held-out Eval — Engineering / Employee', 'engineering', 'employee'),
    ('emp_115', 'Held-out Eval — Engineering / Manager',  'engineering', 'manager'),
    ('emp_116', 'Held-out Eval — HR / Employee',          'hr',          'employee')
ON CONFLICT (employee_id) DO UPDATE SET
    full_name  = EXCLUDED.full_name,
    department = EXCLUDED.department,
    role       = EXCLUDED.role;
