# Thứ tự đọc để hiểu toàn bộ dự án

Đọc theo thứ tự này thì mỗi file chỉ dùng kiến thức từ các file trước nó. Chặng 1–7
(skeleton + tầng dữ liệu) mất khoảng **90 phút**; toàn bộ dự án mất khoảng **170
phút** — không cần đọc một mạch, dừng ở cuối bất kỳ chặng nào cũng để lại một hiểu
biết trọn vẹn về đúng phần đó.

## Trước khi đọc: bật hệ thống lên

Đọc code mà không thấy nó chạy thì khó nhớ. Chạy các lệnh này trước (lần đầu, đủ cho
tới hết phần agent routing; hai lệnh cuối chỉ cần cho phần xác thực trở đi):

```powershell
docker compose up -d db
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/01_schema.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/02_seed.sql
uv run python -m scripts.ingest
uv run python -m scripts.backfill_embeddings
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/06_auth.sql
uv run python -m scripts.issue_api_keys       # in ra key MỘT LẦN — tự lưu lại nếu muốn thử /ask
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

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 3 | [src/config.py](../src/config.py) | Setting đến từ đâu, `database_url` được ghép thế nào |
| 4 | [src/scope.py](../src/scope.py) | Role nào đọc được mức quyền nào |
| 5 | [src/db.py](../src/db.py) | Mở connection kiểu gì, vì sao đường đọc là read-only |

Hai chỗ đáng dừng lại:

- `postgres_host = "127.0.0.1"` chứ không phải `"localhost"` — đọc comment, rồi xem
  ADR-005 ở chặng 6 nếu muốn biết số đo.
- `get_connection(read_only=True)` là mặc định: đường trả lời câu hỏi không bao giờ cần
  ghi dữ liệu nghiệp vụ.
- `src/scope.py` nhỏ nhưng là **nguồn sự thật duy nhất** về phân quyền, và nó cố ý
  **không phụ thuộc pandas**: đường serving không nên kéo theo numpy chỉ để tra một
  dict. Nó tách ra khỏi `contracts.py` sau khi tầng dữ liệu ổn định — xem phần cuối file.

## Chặng 3 — Biên của hệ thống (10 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 6 | [src/schemas.py](../src/schemas.py) | Request/response của `/ask` có hình dạng gì |
| 7 | [src/api.py](../src/api.py) | Các endpoint làm gì |

Điểm cần nắm: **schema hợp lệ** và **nội dung đúng** là hai việc khác nhau. Pydantic
kiểm cái thứ nhất; cái thứ hai là việc của bộ đánh giá ở phần retrieval nền tảng.

Thử ngay:

```powershell
uv run uvicorn src.api:app --port 8010
# rồi mở http://127.0.0.1:8010/docs và gửi thử một request với role = "ceo_of_everything"
```

## Chặng 4 — Tầng dữ liệu (30 phút)

Đọc đúng thứ tự này: schema trước, dữ liệu sau, rồi mới tới code kiểm.

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 8 | [sql/01_schema.sql](../sql/01_schema.sql) | 7 bảng, và mỗi constraint chặn lỗi gì |
| 9 | [sql/02_seed.sql](../sql/02_seed.sql) | Dữ liệu nghiệp vụ, hai điểm được gài có chủ ý |
| 10 | [data/documents.csv](../data/documents.csv) và [documents_dirty.csv](../data/documents_dirty.csv) | Dữ liệu thật trông như thế nào; 8 dòng bẩn sai những gì |
| 11 | [src/contracts.py](../src/contracts.py) | Sáu quy tắc R1–R6, và vì sao mỗi cái là FATAL hay WARNING |
| 12 | [scripts/ingest.py](../scripts/ingest.py) | Luồng đọc → kiểm → quarantine → upsert → manifest |

`01_schema.sql` đọc theo từng khối có tiêu đề khung, không đọc tuần tự từng dòng. Ba chỗ quan
trọng nhất:

- `PRIMARY KEY (doc_id, chunk_index)` — grain được database bảo đảm.
- Ba loại thời gian `published_at` / `available_at` / `effective_from..to` tách riêng.
- Các `CHECK` lặp lại đúng quy tắc đã có trong `contracts.py` — **lặp có chủ ý**, là
  lớp chặn thứ hai cho những đường ghi không đi qua Python.

`documents_dirty.csv`: trước khi đọc tiếp, thử tự tìm 8 dòng bẩn sai gì. Rồi chạy:

```powershell
uv run python -m scripts.ingest data/documents_dirty.csv
docker compose exec -T db psql -U app -d enterprise_ai -c "SELECT doc_id, chunk_index, left(reject_reason,60) FROM doc_chunks_quarantine ORDER BY quarantine_id;"
```

`scripts/ingest.py`, hai chỗ khó nhất trong toàn bộ tầng dữ liệu:

- `ON CONFLICT ... DO UPDATE ... RETURNING (xmax = 0)` — `xmax = 0` nghĩa là dòng vừa
  được chèn mới, nhờ đó manifest phân biệt được insert với update. Chạy `ingest` hai
  lần rồi so `inserted` và `updated` để thấy.
- Cả ba thao tác ghi nằm trong **một** transaction, nên không bao giờ có batch đã ghi mà
  không có manifest nói nó đã chạy.

## Chặng 5 — Truy vấn và query plan (20 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 13 | [sql/03_business_metrics.sql](../sql/03_business_metrics.sql) | JOIN many-to-one và window function tính tăng trưởng |
| 14 | [sql/04_docs_point_in_time.sql](../sql/04_docs_point_in_time.sql) | Ba điều kiện độc lập: quyền, đã có trong hệ thống, còn hiệu lực |
| 15 | [sql/05_explain.sql](../sql/05_explain.sql) rồi [docs/query_plan.md](query_plan.md) | Index giúp được bao nhiêu, ở quy mô nào |

Câu hỏi tự kiểm cho `03_business_metrics.sql`: vì sao lọc thiếu
`available_at <= as_of` là một dạng leakage, dù query vẫn chạy đúng cú pháp?

`05_explain.sql` chạy được và tự dọn sau khi chạy (`ROLLBACK`):

```powershell
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/05_explain.sql
```

Trong `query_plan.md`, đọc kỹ mục "Bốn điều rút ra" — có một kết quả đo **ngược dự
đoán** và nó được ghi lại đúng như vậy.

## Chặng 6 — Test: nơi các quy tắc được phát biểu rõ nhất (15 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 16 | [tests/test_contracts.py](../tests/test_contracts.py) | Mỗi quy tắc bị vi phạm thì hệ thống làm gì |
| 17 | [tests/test_sql_integration.py](../tests/test_sql_integration.py) | Grain có giữ được không, phân quyền có hiệu lực không |
| 18 | [tests/conftest.py](../tests/conftest.py) | Vì sao test phải cách ly khỏi `.env` của máy |

Nếu chỉ có 15 phút cho cả tầng dữ liệu, đọc hai file này. Tên test là một câu phát biểu về hành
vi, nên đọc danh sách tên test là đọc được bản tóm tắt của cả tầng dữ liệu:

```powershell
uv run pytest tests/ --collect-only -q
```

## Chặng 7 — Vì sao lại làm như vậy (15 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 19 | [docs/decisions.md](decisions.md) | Các quyết định không hiển nhiên, kèm số đo |
| 20 | [AGENTS.md](../AGENTS.md) mục 4, 6, 7 | Quyền của AI, các bẫy đã gặp, kế hoạch xây dựng |

ADR nên đọc trước nếu ít thời gian: **005** (một bug thật và một lần tôi giải thích
sai rồi sửa), **006** (contract là module dùng chung), **007** (TRUNCATE CASCADE xóa
nhiều hơn bảng được nêu tên).

Cuối cùng, xem lịch sử để thấy thứ tự các lớp được thêm vào:

```powershell
git log --oneline
```

---

## Ba câu tự kiểm sau khi đọc xong skeleton + tầng dữ liệu

Trả lời được cả ba là đã hiểu hai phần này. Trả lời không trôi câu nào thì quay lại đúng
chặng đó, không đọc lại từ đầu.

1. Một dòng tài liệu có `access_level = "top_secret"` đi vào hệ thống. Kể đường đi của
   nó: bị chặn ở đâu, vì sao không hạ xuống `employee` cho tiện, và nếu ai đó ghi trực
   tiếp bằng `psql` thì chuyện gì xảy ra?
2. Chạy `ingest` hai lần trên cùng một file thì `doc_chunks` có bao nhiêu dòng, và
   `doc_chunks_quarantine` có bao nhiêu dòng? Vì sao hai bảng ứng xử khác nhau?
3. Một câu hỏi ở thời điểm `2026-06-01` không được thấy tài liệu `SAL-009`. Ba điều
   kiện trong `04_docs_point_in_time.sql`, điều kiện nào loại nó, và nếu bỏ điều kiện
   đó thì hệ thống sai theo kiểu gì?

**Tiếp theo:** phần dưới đây đi tiếp qua retrieval, agent, xác thực và báo cáo cuối —
mỗi chặng vẫn chỉ cần kiến thức từ các chặng trước nó (kể cả hai phần ở trên).

---

## Chặng 8 — Retrieval nền tảng: retrieval thật và cổng chất lượng câu trả lời (25 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 21 | [src/embeddings.py](../src/embeddings.py) | Một hàm `embed()` dùng chung cho cả ingest lẫn query, khác nhau ở `task_type` |
| 22 | [src/retrieval.py](../src/retrieval.py) | Phạm vi quyền + point-in-time lọc TRƯỚC khi tính cosine, không phải sau |
| 23 | [src/generation.py](../src/generation.py) | Hai cổng tách biệt: schema (Pydantic) rồi mới tới bằng chứng (`check_grounding`) — không trộn làm một |
| 24 | [src/eval_taxonomy.py](../src/eval_taxonomy.py) | 8 nhãn lỗi, và vì sao thứ tự kiểm (quyền → retrieval → generation) không được đảo |
| 25 | [eval/dev.jsonl](../eval/dev.jsonl) rồi [docs/report.md](report.md) mục retrieval baseline | 25 câu hỏi thật trông như thế nào, và hai lỗi đo lường đã xảy ra thật (rubric bug, bug dấu tiếng Việt) |

Điểm cần nắm: recall@3 = 100% trên tập dev **không có nghĩa** retrieval luôn đúng —
đọc kỹ đoạn so sánh với một baseline TF-IDF trên corpus khác (cùng dạng câu hỏi, TF-IDF
xếp hạng 5 nhưng dense embedding xếp hạng 1) trong `docs/report.md` để thấy baseline
này chỉ đúng trong đúng điều kiện đã ghi, không phải một tuyên bố chung.

Chạy thử (không tốn quota — đọc kết quả đã có sẵn):

```powershell
uv run python -m scripts.run_eval --report
```

## Chặng 9 — Agent routing: điều phối tool, RBAC cho SQL, quyết định không xây hybrid (25 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 26 | [src/scope.py](../src/scope.py) mục `can_query_department` | Ranh giới quyền cho SQL khác ranh giới cho docs (ADR-009) như thế nào |
| 27 | [src/agent/schema.py](../src/agent/schema.py) | Router chỉ trả về đúng hình dạng gì (`ToolPlan`, `SqlArgs`) |
| 28 | [src/agent/router.py](../src/agent/router.py) | Một quyết định phân loại DUY NHẤT — vì sao đây không phải vòng lặp ReAct |
| 29 | [src/agent/tools.py](../src/agent/tools.py) | RBAC kiểm TRƯỚC khi câu SQL chạy, không phải lọc kết quả sau |
| 30 | [src/agent/loop.py](../src/agent/loop.py) | `route → RBAC → thực thi (retry) → tổng hợp`; vì sao số liệu SQL không bao giờ qua LLM |
| 31 | [docs/report.md](report.md) mục agent routing | Đo trước khi xây: 5 câu paraphrase khó, recall@3 vẫn 5/5 → quyết định không làm hybrid (ADR-011) |

Dừng lại ở `loop.py::run_agent` — đọc kỹ khối `try/except RouterSchemaFailure` và so
với `_summarize()`: đây là nơi một router bị "thuyết phục" sai vẫn không vượt qua được
RBAC, vì RBAC dùng `role`/`department` của người gọi, không dùng văn bản câu hỏi.
`tests/test_agent_loop.py::test_router_fooled_into_cross_department_request_is_still_blocked`
là bài kiểm chứng trực tiếp cho đúng khẳng định này.

## Chặng 10 — Xác thực & độ tin cậy: xác thực thật, audit, độ tin cậy đo được (25 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 32 | [sql/06_auth.sql](../sql/06_auth.sql) | `api_key_hash` được thêm vào `employees` như thế nào, vì sao chỉ lưu hash |
| 33 | [src/auth.py](../src/auth.py) | `Authorization: Bearer <key>` → nhân viên thật, hay 401 |
| 34 | [src/api.py](../src/api.py) mục `/ask` | Thứ tự bắt buộc: xác thực → đối chiếu role/department → agent → audit |
| 35 | [src/audit.py](../src/audit.py) | Vì sao lỗi ghi audit không được làm sập request đang trả lời |
| 36 | [src/metrics.py](../src/metrics.py) | Ba metric Prometheus, vì sao câu hỏi không được dùng làm label |
| 37 | [tests/test_rbac_isolation.py](../tests/test_rbac_isolation.py) | Ma trận 61 ca — đọc tên test là đọc bản tóm tắt toàn bộ ranh giới quyền |
| 38 | [docs/report.md](report.md) mục xác thực & độ tin cậy | Lỗ hổng thật đã đo bằng `curl` (trước/sau khi vá), và 3 khoảng trống độ tin cậy đã sửa (pool, statement timeout, jitter) |

Thử ngay — request giả mạo role bị chặn thật:

```powershell
uv run uvicorn src.api:app --port 8010
# rồi (không có Authorization header):
curl -X POST http://127.0.0.1:8010/ask -H "Content-Type: application/json" -d '{"user_id":"x","role":"executive","department":"finance","question":"test"}'
# -> 401, agent chưa từng được gọi
```

## Chặng 11 — Báo cáo cuối: tập held-out, và ba lỗi để nguyên không vá (20 phút)

| # | File | Câu hỏi được trả lời |
|---:|---|---|
| 39 | [eval/final.jsonl](../eval/final.jsonl) | 12 câu held-out thật trông như thế nào, và vì sao chúng khác hẳn 25 câu dev (SQL, kết hợp tool) |
| 40 | [scripts/run_held_out_eval.py](../scripts/run_held_out_eval.py) | Vì sao chạy qua HTTP thật thay vì gọi `run_agent()` trong tiến trình; vì sao ghi kết quả từng câu một |
| 41 | [docs/report.md](report.md) mục báo cáo cuối | Kết quả thật (9/12), và ba phát hiện thật (router bỏ sót tool, response tự mâu thuẫn, timeout không được retry) |
| 42 | [docs/decisions.md](decisions.md) ADR-018, ADR-019 | Vì sao đo token cost cần đổi kiểu trả về của `route()`, và vì sao ba lỗi phát hiện được KHÔNG bị vá rồi chạy lại |
| 43 | [docs/demo_script.md](demo_script.md), [docs/cv_bullets.md](cv_bullets.md) | Kịch bản demo 2-3 phút, và bullet CV — cả hai chỉ dùng số đã có trong `evidence/`/`docs/report.md` |

Điểm quan trọng nhất của cả chặng này, dễ bị đọc lướt qua: tập held-out tìm ra ba lỗi
thật rồi **cố tình không sửa ngay**. Đọc kỹ đoạn giải thích trong ADR-019 — đây không
phải làm dở, mà là hệ quả trực tiếp của đúng nguyên tắc "held-out chỉ chạy một lần" mà
`AGENTS.md` mục 4 đã đặt ra từ trước.

---

## Ba câu tự kiểm sau khi đọc xong toàn bộ

1. Một câu hỏi vừa hỏi số liệu doanh thu vừa hỏi chính sách liên quan trong cùng một
   câu. Router THƯỜNG chọn tool nào, và tại sao đây là một phát hiện được đo hai lần
   độc lập (khi xây agent, rồi lại lúc chạy held-out) chứ không phải một lần đoán?
2. Một request có `Authorization` header hợp lệ nhưng `role` trong body không khớp
   role thật của key đó. Request đi qua bao nhiêu bước kiểm trước khi tới `run_agent()`,
   và dừng ở bước nào?
3. Tập held-out tìm ra một response tự mâu thuẫn (`abstained=true` kèm citation)
   khiến request 502. Vì sao không sửa lỗi này rồi chạy lại đúng 12 câu đó để lấy
   một con số tốt hơn — điều đó vi phạm đúng nguyên tắc nào?
