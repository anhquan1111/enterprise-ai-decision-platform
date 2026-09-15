-- D4: cot luu API key da bam hash cho tung nhan vien.
--
-- Khong luu key dang plaintext o bat ky dau - chi luu SHA-256 hex digest. Khi xac
-- thuc, server bam key nguoi goi gui len roi so voi cot nay, khong bao gio giai ma
-- nguoc. scripts/issue_api_keys.py sinh key that, in ra dung MOT LAN, roi ghi hash
-- vao day - dung mo hinh "hien thi dung mot lan luc cap phat" cua cac he thong that.
ALTER TABLE employees ADD COLUMN IF NOT EXISTS api_key_hash TEXT;

-- Mot hash khong duoc trung giua hai nhan vien khac nhau - trung nghia la dung
-- chung mot key, pha vo hoan toan y nghia xac thuc danh tinh.
CREATE UNIQUE INDEX IF NOT EXISTS ux_employees_api_key_hash
    ON employees (api_key_hash)
    WHERE api_key_hash IS NOT NULL;
