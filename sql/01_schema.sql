-- Schema của platform. Chạy sau 00_extensions.sql.
--
-- Nguyên tắc xuyên suốt: constraint ở đây là LỚP CHẶN THỨ HAI. src/contracts.py kiểm
-- để báo lỗi có ngữ cảnh và đưa dòng xấu vào quarantine; database kiểm để chặn cả
-- những đường ghi không đi qua code Python (script migration, sửa tay lúc sự cố).
-- Hai lớp cùng một quy tắc là cố ý, không phải dư thừa.

DROP TABLE IF EXISTS audit_log;
DROP TABLE IF EXISTS ingest_run;
DROP TABLE IF EXISTS doc_chunks_quarantine;
DROP TABLE IF EXISTS doc_chunks;
DROP TABLE IF EXISTS monthly_revenue;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS departments;

-- ╔════════════════════════════════════════════════════════════════════╗
-- ║ 1. Dữ liệu nghiệp vụ — nguồn cho tool SQL                          ║
-- ╚════════════════════════════════════════════════════════════════════╝

CREATE TABLE departments (
    department  TEXT PRIMARY KEY,
    full_name   TEXT NOT NULL,
    CONSTRAINT ck_department_known
        CHECK (department IN ('sales', 'hr', 'finance', 'engineering'))
);

CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY,
    full_name   TEXT NOT NULL,
    department  TEXT NOT NULL REFERENCES departments (department),
    role        TEXT NOT NULL,
    CONSTRAINT ck_employee_role
        CHECK (role IN ('employee', 'manager', 'executive'))
);

-- Grain: một dòng cho mỗi (phòng ban, tháng). Khóa chính ép đúng grain đó, nên một
-- JOIN sang bảng này không thể nhân bản dòng.
CREATE TABLE monthly_revenue (
    department      TEXT    NOT NULL REFERENCES departments (department),
    month           DATE    NOT NULL,
    revenue_vnd     BIGINT  NOT NULL,
    -- Tháng mới nhất có thể chưa chốt sổ. Cột này để truy vấn phân biệt "số cuối" và
    -- "số tạm", thay vì coi mọi dòng như nhau.
    is_final        BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT pk_monthly_revenue PRIMARY KEY (department, month),
    CONSTRAINT ck_revenue_nonneg CHECK (revenue_vnd >= 0),
    -- Chuẩn hóa month về ngày đầu tháng ngay ở tầng database: nếu để lẫn 01/03 và
    -- 15/03 thì GROUP BY theo tháng sẽ ra hai nhóm cho cùng một tháng.
    CONSTRAINT ck_month_is_first_day CHECK (month = date_trunc('month', month)::date)
);

-- ╔════════════════════════════════════════════════════════════════════╗
-- ║ 2. Tài liệu — nguồn cho tool retrieval                             ║
-- ╚════════════════════════════════════════════════════════════════════╝

-- Grain: một dòng là một chunk của một document.
--
-- Ba loại thời gian, tách theo đúng cách ngày 6 đã tách:
--   published_at   — tài liệu được công bố lúc nào
--   available_at   — hệ thống CÓ THỂ DÙNG nó từ lúc nào (dùng để lọc point-in-time)
--   effective_from / effective_to — tài liệu có hiệu lực nghiệp vụ trong khoảng nào
-- Một câu hỏi tại thời điểm t chỉ được đọc chunk có available_at <= t.
CREATE TABLE doc_chunks (
    doc_id            TEXT        NOT NULL,
    chunk_index       INTEGER     NOT NULL,
    department        TEXT        NOT NULL REFERENCES departments (department),
    -- Không chỉ là một trường dữ liệu: đây là ranh giới bảo mật. Mọi truy vấn
    -- retrieval đều lọc theo nó, nên một giá trị lạ là lỗi FATAL ở contract.
    access_level      TEXT        NOT NULL,
    title             TEXT        NOT NULL,
    chunk_text        TEXT        NOT NULL,
    published_at      TIMESTAMPTZ NOT NULL,
    available_at      TIMESTAMPTZ NOT NULL,
    effective_from    DATE        NOT NULL,
    -- NULL nghĩa là "còn hiệu lực". Không dùng 9999-12-31 thay thế: một ngày giả sẽ
    -- lặng lẽ đi vào mọi phép so sánh.
    effective_to      DATE,

    -- Lấp ở giai đoạn retrieval nền tảng. Cho phép NULL để ingest được ngay từ tầng
    -- dữ liệu, trước khi chọn embedding model.
    embedding         vector(384),

    -- Lineage tối thiểu: đủ trả lời "dòng này từ đâu, theo contract nào, lúc nào".
    source_file       TEXT        NOT NULL,
    source_hash       TEXT        NOT NULL,
    contract_version  TEXT        NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL,

    CONSTRAINT pk_doc_chunks PRIMARY KEY (doc_id, chunk_index),
    CONSTRAINT ck_access_level
        CHECK (access_level IN ('employee', 'manager', 'executive')),
    CONSTRAINT ck_interval_direction
        CHECK (effective_to IS NULL OR effective_from <= effective_to),
    CONSTRAINT ck_timestamp_order
        CHECK (available_at >= published_at),
    CONSTRAINT ck_text_not_blank
        CHECK (length(btrim(chunk_text)) > 0)
);

-- Dòng bị loại không bị xóa. Không có bảng này thì "ingest 14/17 dòng" là thông tin
-- không điều tra được: không ai biết 3 dòng kia là gì.
CREATE TABLE doc_chunks_quarantine (
    quarantine_id     BIGSERIAL   PRIMARY KEY,
    doc_id            TEXT,
    chunk_index       INTEGER,
    -- Giữ dòng THÔ: người xử lý sự cố cần thấy đúng dữ liệu đã đến, không phải bản
    -- đã bị code làm sạch một nửa. JSONB để không phải sửa schema mỗi lần nguồn đổi.
    raw_row           JSONB       NOT NULL,
    reject_reason     TEXT        NOT NULL,
    source_file       TEXT        NOT NULL,
    source_hash       TEXT        NOT NULL,
    contract_version  TEXT        NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL
);

-- ╔════════════════════════════════════════════════════════════════════╗
-- ║ 3. Vận hành — manifest mỗi lần ingest, và audit log                 ║
-- ╚════════════════════════════════════════════════════════════════════╝

-- Manifest của ngày 7, lưu trong bảng thay vì file JSON: so được giữa các lần chạy
-- bằng SQL. Tỷ lệ loại nhảy từ 5% lên 40% là tín hiệu, dù từng lý do đều hợp lệ.
CREATE TABLE ingest_run (
    run_id            BIGSERIAL   PRIMARY KEY,
    source_file       TEXT        NOT NULL,
    source_hash       TEXT        NOT NULL,
    contract_version  TEXT        NOT NULL,
    rows_in_file      INTEGER     NOT NULL,
    rows_accepted     INTEGER     NOT NULL,
    rows_quarantined  INTEGER     NOT NULL,
    rows_inserted     INTEGER     NOT NULL,
    rows_updated      INTEGER     NOT NULL,
    violations        JSONB       NOT NULL,
    started_at        TIMESTAMPTZ NOT NULL,
    finished_at       TIMESTAMPTZ NOT NULL,
    -- Kiểm cân đối ngay ở database: nhận + loại phải bằng số dòng trong file. Không
    -- cân nghĩa là có dòng biến mất ở đâu đó, và đó là lỗi phải tìm trước mọi thứ.
    CONSTRAINT ck_rows_balance
        CHECK (rows_accepted + rows_quarantined = rows_in_file)
);

-- Tạo ở D1 để schema hoàn chỉnh; ghi vào nó là việc của D4.
CREATE TABLE audit_log (
    audit_id          BIGSERIAL   PRIMARY KEY,
    request_id        UUID        NOT NULL,
    user_id           TEXT        NOT NULL,
    role              TEXT        NOT NULL,
    department        TEXT        NOT NULL,
    question          TEXT        NOT NULL,
    tool_used         TEXT        NOT NULL,
    retrieved_doc_ids TEXT[]      NOT NULL DEFAULT '{}',
    abstained         BOOLEAN     NOT NULL,
    llm_model         TEXT,
    total_tokens      INTEGER,
    latency_ms        INTEGER     NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ╔════════════════════════════════════════════════════════════════════╗
-- ║ 4. Index                                                           ║
-- ╚════════════════════════════════════════════════════════════════════╝

-- Index cho đường truy vấn retrieval thật: lọc theo phạm vi quyền trước, rồi mới
-- xét thời gian. Hiệu quả của nó được đo trong docs/query_plan.md, không phải
-- giả định — ở corpus nhỏ, Postgres vẫn có thể chọn seq scan và đó là lựa chọn đúng.
CREATE INDEX ix_chunks_scope ON doc_chunks (department, access_level, available_at);

-- Chưa tạo ANN index (HNSW/IVFFlat) cho cột embedding: ở quy mô vài trăm chunk,
-- exact search nhanh hơn và không có sai số. Mở khi số đo nói cần.
