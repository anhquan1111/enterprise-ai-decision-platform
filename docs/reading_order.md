# Thứ tự đọc để hiểu hết D0 + D1

Đọc theo thứ tự này thì mỗi file chỉ dùng kiến thức từ các file trước nó. Tổng khoảng
**90 phút**. Cột bên phải ghi chỗ tương ứng trong tài liệu học, để thấy code này đến từ
cơ chế nào.

Vault tài liệu: `D:\Documents\AI\Update\`.

## Trước khi đọc: bật hệ thống lên

Đọc code mà không thấy nó chạy thì khó nhớ. Chạy bốn lệnh này trước, mỗi lệnh ~10 giây:

```powershell
docker compose up -d db
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/01_schema.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/02_seed.sql
uv run python -m scripts.ingest
```

Giữ terminal đó mở. Mỗi khi đọc tới một file SQL, chạy thử câu trong đó.

---

## Chặng 1 — Hệ thống này làm gì (10 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 1 | [README.md](../README.md) | Bài toán là gì, đang xong tới đâu, chạy thế nào |
| 2 | [docs/architecture.md](architecture.md) | Một request đi qua những bước nào, và vì sao phạm vi quyền được xác định **trước** router |

Điểm cần nắm sau chặng này: phân quyền là **filter ở tầng truy vấn dữ liệu**, không
phải một câu dặn trong prompt. Đó là lý do của gần như mọi quyết định sau đó.

## Chặng 2 — Cấu hình và kết nối (10 phút)

| # | File | Câu hỏi được trả lời | Tương ứng tài liệu |
|---:|---|---|---|
| 3 | [src/config.py](../src/config.py) | Setting đến từ đâu, `database_url` được ghép thế nào | — |
| 4 | [src/db.py](../src/db.py) | Mở connection kiểu gì, vì sao đường đọc là read-only | Ngày 6 |

Hai chỗ đáng dừng lại:

- `postgres_host = "127.0.0.1"` chứ không phải `"localhost"` — đọc comment, rồi xem
  ADR-005 ở chặng 6 nếu muốn biết số đo.
- `get_connection(read_only=True)` là mặc định: đường trả lời câu hỏi không bao giờ cần
  ghi dữ liệu nghiệp vụ.

## Chặng 3 — Biên của hệ thống (10 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 5 | [src/schemas.py](../src/schemas.py) | Request/response của `/ask` có hình dạng gì |
| 6 | [src/api.py](../src/api.py) | Ba endpoint làm gì, vì sao `/ask` trả 501 |

Điểm cần nắm: **schema hợp lệ** và **nội dung đúng** là hai việc khác nhau. Pydantic
kiểm cái thứ nhất; cái thứ hai là việc của bộ đánh giá ở D2.

Thử ngay:

```powershell
uv run uvicorn src.api:app --port 8010
# rồi mở http://127.0.0.1:8010/docs và gửi thử một request với role = "ceo_of_everything"
```

## Chặng 4 — Tầng dữ liệu, phần chính của D1 (30 phút)

Đọc đúng thứ tự này: schema trước, dữ liệu sau, rồi mới tới code kiểm.

| # | File | Câu hỏi được trả lời | Tương ứng tài liệu |
|---:|---|---|---|
| 7 | [sql/01_schema.sql](../sql/01_schema.sql) | 7 bảng, và mỗi constraint chặn lỗi gì | Ngày 6 + Ngày 7 |
| 8 | [sql/02_seed.sql](../sql/02_seed.sql) | Dữ liệu nghiệp vụ, hai điểm được gài có chủ ý | Ngày 7 |
| 9 | [data/documents.csv](../data/documents.csv) và [documents_dirty.csv](../data/documents_dirty.csv) | Dữ liệu thật trông như thế nào; 8 dòng bẩn sai những gì | Ngày 7 lab |
| 10 | [src/contracts.py](../src/contracts.py) | Sáu quy tắc R1–R6, và vì sao mỗi cái là FATAL hay WARNING | Ngày 7 file 1 + 2 |
| 11 | [scripts/ingest.py](../scripts/ingest.py) | Luồng đọc → kiểm → quarantine → upsert → manifest | Ngày 7 file 3 |

File 7 đọc theo từng khối có tiêu đề khung, không đọc tuần tự từng dòng. Ba chỗ quan
trọng nhất:

- `PRIMARY KEY (doc_id, chunk_index)` — grain được database bảo đảm.
- Ba loại thời gian `published_at` / `available_at` / `effective_from..to` tách riêng.
- Các `CHECK` lặp lại đúng quy tắc đã có trong `contracts.py` — **lặp có chủ ý**, là
  lớp chặn thứ hai cho những đường ghi không đi qua Python.

File 9: trước khi đọc tiếp, thử tự tìm 8 dòng bẩn sai gì. Rồi chạy:

```powershell
uv run python -m scripts.ingest data/documents_dirty.csv
docker compose exec -T db psql -U app -d enterprise_ai -c "SELECT doc_id, chunk_index, left(reject_reason,60) FROM doc_chunks_quarantine ORDER BY quarantine_id;"
```

File 11, hai chỗ khó nhất trong toàn bộ D1:

- `ON CONFLICT ... DO UPDATE ... RETURNING (xmax = 0)` — `xmax = 0` nghĩa là dòng vừa
  được chèn mới, nhờ đó manifest phân biệt được insert với update. Chạy `ingest` hai
  lần rồi so `inserted` và `updated` để thấy.
- Cả ba thao tác ghi nằm trong **một** transaction, nên không bao giờ có batch đã ghi mà
  không có manifest nói nó đã chạy.

## Chặng 5 — Truy vấn và query plan (20 phút)

| # | File | Câu hỏi được trả lời | Tương ứng tài liệu |
|---:|---|---|---|
| 12 | [sql/03_business_metrics.sql](../sql/03_business_metrics.sql) | JOIN many-to-one và window function tính tăng trưởng | Ngày 6 file 1 + 2 |
| 13 | [sql/04_docs_point_in_time.sql](../sql/04_docs_point_in_time.sql) | Ba điều kiện độc lập: quyền, đã có trong hệ thống, còn hiệu lực | Ngày 6 file 3 |
| 14 | [sql/05_explain.sql](../sql/05_explain.sql) rồi [docs/query_plan.md](query_plan.md) | Index giúp được bao nhiêu, ở quy mô nào | Ngày 6 file 4 |

File 13 là chỗ ngày 6 gặp lại trực tiếp nhất. Câu hỏi tự kiểm: vì sao lọc thiếu
`available_at <= as_of` là một dạng leakage, dù query vẫn chạy đúng cú pháp?

File 14 chạy được và tự dọn sau khi chạy (`ROLLBACK`):

```powershell
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/05_explain.sql
```

Trong `query_plan.md`, đọc kỹ mục "Bốn điều rút ra" — có một kết quả đo **ngược dự
đoán** và nó được ghi lại đúng như vậy.

## Chặng 6 — Test: nơi các quy tắc được phát biểu rõ nhất (15 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 15 | [tests/test_contracts.py](../tests/test_contracts.py) | Mỗi quy tắc bị vi phạm thì hệ thống làm gì |
| 16 | [tests/test_sql_integration.py](../tests/test_sql_integration.py) | Grain có giữ được không, phân quyền có hiệu lực không |

Nếu chỉ có 15 phút cho cả D1, đọc hai file này. Tên test là một câu phát biểu về hành
vi, nên đọc danh sách tên test là đọc được bản tóm tắt của cả tầng dữ liệu:

```powershell
uv run pytest tests/ --collect-only -q
```

## Chặng 7 — Vì sao lại làm như vậy (15 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 17 | [docs/decisions.md](decisions.md) | 8 quyết định không hiển nhiên, kèm số đo |
| 18 | [AGENTS.md](../AGENTS.md) mục 4, 6, 7 | Quyền của AI, các bẫy đã gặp, kế hoạch D2–D5 |

ADR nên đọc trước nếu ít thời gian: **005** (một bug thật và một lần tôi giải thích
sai rồi sửa), **006** (contract là module dùng chung), **007** (TRUNCATE CASCADE xóa
nhiều hơn bảng được nêu tên).

Cuối cùng, xem lịch sử để thấy thứ tự các lớp được thêm vào:

```powershell
git log --oneline
```

---

## Ba câu tự kiểm sau khi đọc xong

Trả lời được cả ba là đã hiểu D0 + D1. Trả lời không trôi câu nào thì quay lại đúng
chặng đó, không đọc lại từ đầu.

1. Một dòng tài liệu có `access_level = "top_secret"` đi vào hệ thống. Kể đường đi của
   nó: bị chặn ở đâu, vì sao không hạ xuống `employee` cho tiện, và nếu ai đó ghi trực
   tiếp bằng `psql` thì chuyện gì xảy ra?
2. Chạy `ingest` hai lần trên cùng một file thì `doc_chunks` có bao nhiêu dòng, và
   `doc_chunks_quarantine` có bao nhiêu dòng? Vì sao hai bảng ứng xử khác nhau?
3. Một câu hỏi ở thời điểm `2026-06-01` không được thấy tài liệu `SAL-009`. Ba điều
   kiện trong `04_docs_point_in_time.sql`, điều kiện nào loại nó, và nếu bỏ điều kiện
   đó thì hệ thống sai theo kiểu gì?
