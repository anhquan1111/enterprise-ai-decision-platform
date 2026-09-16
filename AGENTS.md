# AGENTS.md — Enterprise AI Decision Platform

Hướng dẫn cho AI CLI (Claude Code, Gemini, Copilot, Cursor) khi làm việc với repo này.

---

## 1. Project Overview

**Bài toán:** API nội bộ doanh nghiệp. Nhân viên hỏi bằng ngôn ngữ tự nhiên, hệ thống tự chọn truy vấn **số liệu kinh doanh (SQL)** hay **tài liệu quy trình (retrieval)**, trả lời **kèm trích dẫn nguồn**, **chỉ trong phạm vi quyền của người hỏi**, và **ghi audit log** mọi lượt.

- **Input:** `{user_id, role, department, question}`
- **Output:** `{answer, citations[], tool_used, abstained, latency_ms}`
- **Dữ liệu:** tổng hợp, tự tạo cho project này. Không dùng tài liệu thật của công ty nào.

### Tiêu chí thành công

Đây là tiêu chí **về cách làm**, không phải ngưỡng số cố định — ngưỡng chỉ có nghĩa sau khi đo baseline ở phần retrieval nền tảng.

| Hạng mục | Yêu cầu |
|---|---|
| Retrieval | Có baseline đo trước, mọi thay đổi đo lại trên cùng bộ eval và cùng protocol |
| Citations | Mọi claim trong answer phải trỏ được về chunk hoặc câu SQL đã chạy |
| Abstention | Không có bằng chứng trong phạm vi quyền thì trả `abstained=true`, không đoán |
| RBAC | Có test chứng minh hai role nhận ngữ cảnh khác nhau |
| Báo số | Luôn kèm cỡ mẫu. 40 câu là quy mô học tập, không phải bằng chứng production |

> ⚠️ **KHÔNG báo một con số trung bình trần trụi.** Với bộ ~28 câu dev, chênh 1 câu là ~3,6% — nằm trong nhiễu. Báo số ca tuyệt đối kèm phần trăm.

---

## 2. Tech Stack

| Tool | Version | Mục đích |
|---|---|---|
| Python | 3.12 | Runtime |
| uv | 0.11.13 | Package manager |
| FastAPI | >=0.115 | API |
| PostgreSQL | 17 | Business tables + chunks + audit log |
| pgvector | 0.8.6 | Vector type + cosine distance operator |
| psycopg | >=3.2 | DB driver, raw SQL (không ORM) |
| Pydantic | >=2.9 | Request/response contract |
| pytest, ruff, mypy | — | Test, lint, type check |
| MLflow | >=2.17 | Tracking mỗi eval run (extra `eval`) — **chưa dùng**, hiện chỉ ghi JSONL/JSON thô. Thêm nếu số lần chạy eval nhiều tới mức JSON thô khó so sánh |
| prometheus-client | >=0.26 | Metrics |
| Gemini API | v1beta | `gemini-3.1-flash-lite` sinh, `gemini-embedding-001` embed |

**LLM provider đã chốt (ADR-002):** Gemini, key trong `.env` (`LLM_API_KEY`), auth bằng
header `x-goog-api-key` chứ không qua query string. Local 7B đã thử và **không chạy được**
trên máy này vì hết commit headroom — số đo trong ADR-002.

---

## 3. Common Commands

```bash
# Môi trường (PowerShell hoặc bash trên Windows)
uv sync --extra dev                 # Dependencies + dev tools
uv sync --extra dev --extra eval    # MLflow + BM25 — đã đo và KHÔNG dùng hybrid
                                     # (ADR-011); extra này để sẵn cho phân tích, chưa
                                     # gỡ vì có thể cần lại nếu corpus mở rộng

# Database
docker compose up -d db             # Chỉ bật PostgreSQL (dev thường ngày)
docker compose up -d                # Bật cả 4 service (api, db, prometheus, grafana)
docker compose up -d db api prometheus grafana   # Tương đương, liệt kê rõ
docker compose build api            # Bắt buộc sau khi sửa src/ — compose up không tự rebuild
docker compose down                 # Dừng, giữ dữ liệu trong named volume
docker compose down -v              # Dừng và XÓA dữ liệu

# Áp schema và seed (thêm MSYS_NO_PATHCONV=1 nếu dùng Git Bash — xem mục 6)
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/00_extensions.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/01_schema.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/02_seed.sql
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/06_auth.sql   # cột api_key_hash

# Alembic (ADR-025): cách này vẫn là cách nhanh nhất để dựng một DB dev SẠCH từ đầu.
# Alembic quản lý các thay đổi schema TIẾP THEO trên một DB đã tồn tại — không thay
# thế bốn dòng trên, không autogenerate (không có ORM metadata để diff theo).
uv run alembic upgrade head       # áp mọi migration chưa chạy trên DB hiện tại
uv run alembic current            # xem DB đang ở revision nào
uv run alembic downgrade -1       # lùi lại một migration (test rollback trước khi apply thật)
uv run alembic revision -m "mo ta thay doi"   # tạo migration mới, viết tay upgrade()/downgrade()

# Ingest tài liệu. Dùng -m để project root vào sys.path, không phải python scripts/...
uv run python -m scripts.ingest                            # corpus chính, 16 chunk
uv run python -m scripts.ingest data/documents_dirty.csv   # xem quarantine hoạt động

# Cấp API key cho từng nhân viên đã seed — in ra ĐÚNG MỘT LẦN, tự lưu lại ngay.
# Idempotent theo từng nhân viên: không ghi đè key đã cấp, chỉ cấp cho ai chưa có.
uv run python -m scripts.issue_api_keys

# Query plan: thí nghiệm 16 dòng vs 20k dòng, có/không index, kết thúc bằng ROLLBACK
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/05_explain.sql

# API dev server
uv run uvicorn src.api:app --reload --port 8010
# http://127.0.0.1:8010/docs — /ask cần header: Authorization: Bearer <key từ issue_api_keys>
# http://127.0.0.1:8010/ui/  — giao diện demo tĩnh (ADR-029), 3 nut dang nhap nhanh
# qua /auth/demo-token (ADR-031, khong can API key) — tu phuc vu cho nguoi xem repo
# LUÔN kiểm port trống trước khi start — xem mục 6 "Kiểm process cũ đang chiếm port"

# /ui chạy được qua container api CHỈ SAU KHI rebuild image (Dockerfile giờ copy
# thêm web/) — image cũ trên máy dev không có thư mục này:
docker compose build api && docker compose up -d api

# Test, lint, types
uv run pytest tests/ -v -m "not integration"    # Mặc định, không cần DB
uv run pytest tests/ -v -m integration          # Cần docker compose up -d db
uv run ruff check src/ tests/ scripts/
uv run ruff format src/ tests/ scripts/
uv run mypy src/ scripts/
```

**Port đã dùng:** API `8010`, PostgreSQL `5433`, Prometheus `9090`, Grafana `3000`. Tránh `8000` (fraud-detection-api) và `5546` (một project SQL khác) vì hai cái đó có thể đang chạy song song.

---

## 4. Permission Levels

### Luôn được tự làm

- Viết/sửa code trong `src/`, thêm test, refactor, type hints, docstrings
- Chạy lint, format, mypy, pytest
- Thêm logging, error handling, timeout
- Cập nhật `docs/`, README, AGENTS.md
- Chạy `docker compose up/down` (không kèm `-v`)

### Phải hỏi trước

- **Đổi LLM provider hoặc model** — ảnh hưởng mọi số đo đã báo
- **Sửa bộ eval** (`eval/`) sau khi đã đo baseline — làm số cũ và số mới không so sánh được
- **Xem bộ 12 câu held-out** trước khi viết báo cáo cuối — xem rồi là mất tính độc lập
- **Đổi quy tắc RBAC** — là quyết định bảo mật, không phải refactor
- **Thêm dependency lớn** (torch, transformers) — ảnh hưởng thời gian cài và kích thước image
- **`docker compose down -v`** — xóa dữ liệu

### Không bao giờ được làm

- **Commit `.env`** hoặc bất kỳ API key nào — kể cả API key nhân viên do
  `scripts/issue_api_keys.py` cấp; chỉ hash mới được lưu, không bao giờ log
  plaintext key ra console/file ngoài lần in DUY NHẤT lúc cấp
- **Chạy lại `scripts/issue_api_keys.py` rồi ghi đè `api_key_hash` thủ công** cho một
  nhân viên đã có key — vô hiệu hoá key đang dùng của người khác mà không báo trước
- **Trả về câu trả lời bịa** từ một endpoint chưa implement — thà trả 501
- **Đưa số chưa đo vào README/CV** — mọi số phải trỏ về file trong `evidence/`
- **Áp phân quyền bằng prompt** thay vì bằng filter ở tầng dữ liệu
- **Tối ưu retrieval trước khi có baseline** — không có baseline thì không chứng minh được gì
- **Xem điểm trên tập held-out rồi tiếp tục tinh chỉnh** và báo lại trên chính tập đó
- **Dùng tài liệu nội bộ thật** của bất kỳ công ty nào làm corpus

---

## 5. Coding Conventions

- **Commit:** [Conventional Commits](https://www.conventionalcommits.org/) — `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`, `ci:`
- **Format:** `ruff format`, line length 100
- **Lint:** ruff rules `E`, `F`, `I`, `W`, `UP`, `B`, `SIM`
- **Types:** bắt buộc cho mọi function signature; `mypy --disallow-untyped-defs` phải xanh
- **Docstrings:** Google style
- **SQL:** luôn dùng named placeholder kiểu `%(name)s`, **không** nối câu SQL bằng f-string
- **Comment:** chỉ viết ở chỗ có quyết định khó hiểu, giải thích *vì sao*, không dịch lại code

---

## 6. Non-obvious Patterns & Gotchas

### Dùng `127.0.0.1`, không dùng `localhost`

`getaddrinfo("localhost")` trên máy này trả `::1` **trước** `127.0.0.1`, còn compose publish port ở `127.0.0.1:5433:5432` (chỉ IPv4) nên `[::1]:5433` không có ai listen. libpq thử các địa chỉ **theo thứ tự** và áp `connect_timeout` cho **từng địa chỉ**, nên mỗi connection phải trả giá cho lần thử IPv6 thất bại trước khi fallback.

Đo được: `psycopg.connect` tới `localhost` mất **5,08s** với `connect_timeout=5` (đúng bằng timeout), tới `127.0.0.1` mất **0,04s**. Integration test với `localhost` không xong trong 240s; với `127.0.0.1` pass 0,44s.

Chi tiết và phần chưa giải thích được: `docs/decisions.md` ADR-005.

**Đã sửa, và đây là bài học quan trọng hơn bản thân con bug.** Nguyên nhân khiến lỗi biến thành *treo* thay vì *báo lỗi* là DSN không có `connect_timeout` — libpq mặc định chờ vô hạn. Hai thứ đã thêm:

- `database_url` luôn gắn `connect_timeout` (mặc định 5s, đổi qua `POSTGRES_CONNECT_TIMEOUT`). Kiểm chứng với địa chỉ không routable `192.0.2.1`: fail sau **5,08s** kèm `ConnectionTimeout`, không đứng.
- `pytest-timeout`, giới hạn **30s mỗi test**. Kiểm chứng bằng một test `sleep(10)` dưới `@pytest.mark.timeout(2)`: bị cắt và báo fail.

Sau khi thêm timeout, chạy lại với `POSTGRES_HOST=localhost` mất **10,91s** (2 connection × 5s) thay vì không xong trong 240s — tức chi phí là per-connection và tuyến tính.

**Quy tắc rút ra, áp cho mọi lời gọi ra ngoài thêm vào sau này** (LLM API, embedding, reranker): đặt timeout **ngay lúc viết**, không đợi nó treo một lần rồi mới thêm. Thiếu timeout làm một lỗi nhanh thành treo vô hạn; test không có giới hạn thời gian thì báo treo thành "đang chạy" chứ không phải "fail".

### Git Bash mangle đường dẫn Unix trong `docker compose exec`

Đường dẫn `/sql/00_extensions.sql` bị Git Bash đổi thành `D:/Downloads/Git/sql/...`. Thêm `MSYS_NO_PATHCONV=1` trước lệnh, hoặc chạy từ PowerShell.

### `/health` và `/ready` khác nhau, đừng gộp

`/health` = process còn sống, **không** gọi DB. `/ready` = gọi DB, trả 503 khi DB chết. Docker `HEALTHCHECK` dùng `/health`. Nếu healthcheck gọi DB thì DB chớp tắt sẽ làm container restart dù process hoàn toàn bình thường. Xem ADR-004.

### Vì sao đọc DB bằng session read-only

`get_connection(read_only=True)` là mặc định. Đường trả lời câu hỏi không bao giờ cần ghi dữ liệu nghiệp vụ, nên một bug hoặc một câu SQL do LLM sinh ra cũng không sửa được dữ liệu. Ingestion và audit log truyền `read_only=False` một cách tường minh.

### `/ask` trả 501 lúc mới dựng skeleton, trả lời thật từ khi có retrieval

Stub 501 tồn tại đúng một mục đích: một câu trả lời trông như thật ở giai đoạn skeleton sẽ làm endpoint trông như đã xong. Test `test_ask_is_honestly_unimplemented` được viết lại thành `test_api.py` hiện tại khi retrieval được implement thật, đúng như dòng ghi chú của nó đã yêu cầu — đây là ví dụ hiếm hoi một test tự ra lệnh cho việc sửa nó trong tương lai.

### pgvector: phải cast tường minh `::vector` trong SQL

`register_vector(conn)` không đủ để psycopg tự nhận ra một `list[float]` truyền qua tham số là kiểu `vector` — nó vẫn gửi đi như mảng `double precision[]`, và PostgreSQL báo `operator does not exist: vector <=> double precision[]`. Luôn viết `%(qvec)s::vector` trong câu SQL, không chỉ dựa vào `register_vector`.

### Không được gõ ký tự `%` trong comment của một file `.sql` chạy qua psycopg

psycopg quét **toàn bộ văn bản** câu lệnh để tìm token cần bind (`%(name)s`) — kể cả bên trong comment `--`. Một dòng comment giải thích "câu này không lọc theo department" bằng chính cú pháp `%(department)s` để minh hoạ đã làm psycopg đòi bind một tham số không tồn tại (`ProgrammingError: query parameter missing: department`); né bằng cách viết nửa vời (`%-ngoặc-s`) vẫn còn một ký tự `%` trơ trọi, ra lỗi khác (`only '%s', '%b', '%t' are allowed as placeholders, got '%-'`). Cả hai lần đều **không unit test mock nào bắt được** — mock `fetch_all` không đi qua psycopg thật, chỉ lộ ra khi gọi qua container thật. Quy tắc: không gõ ký tự `%` trong comment của bất kỳ file `.sql` nào được nạp qua `fetch_all()`/`cur.execute(sql, params)`, kể cả để mô tả cú pháp — mô tả bằng lời. Chi tiết: ADR-030; kiểm tĩnh chống tái diễn: `tests/test_agent_tools.py::test_no_sql_file_has_a_stray_percent_outside_real_placeholders`.

### So khớp từ khóa tiếng Việt phải bỏ dấu cả hai phía

Corpus và rubric trong `eval/*.jsonl` viết không dấu, nhưng Gemini luôn trả lời có dấu đầy đủ — đúng hành vi mong muốn, sai giả định nếu so chuỗi trực tiếp: `"khong duoc"` không phải chuỗi con của `"không được"`. `src/eval_taxonomy.py` có `_fold()` chuẩn hoá cả hai phía bằng NFD trước khi so, xử lý riêng `đ`/`Đ` vì đó là chữ cái Latin, không phải tổ hợp dấu. Thiếu bước này thì gần như mọi câu đúng bị chấm sai — đã xảy ra thật khi đo baseline retrieval.

### `department` không phải ranh giới bảo mật cho docs retrieval

Chỉ `access_level` (qua `visible_access_levels`) và thời điểm lọc docs — `department` là phân loại nội dung, không phải quyền. Một nhân viên Sales được phép đọc chính sách nghỉ phép của HR. Ranh giới department thật sự (nếu cần) thuộc về tool SQL, xem ADR-009.

### TRUNCATE ... CASCADE xóa nhiều hơn bảng được nêu tên

`doc_chunks` có khóa ngoại tới `departments`, nên `TRUNCATE departments CASCADE` xóa luôn
toàn bộ corpus tài liệu. Bản đầu của `sql/02_seed.sql` mắc đúng lỗi này. Seed giờ dùng
`ON CONFLICT DO UPDATE`, chạy lại bao nhiêu lần cũng an toàn. Xem ADR-007.

### Chạy script bằng `-m`, không phải đường dẫn file

`python scripts/ingest.py` không import được `src` vì project root không nằm trong
sys.path. `python -m scripts.ingest` thì có. Đừng chèn sys.path trong code để lách.

### Thinking token trừ vào max output

Gemini 3.x bật thinking mặc định và `thoughtsTokenCount` tính vào `maxOutputTokens`. Đặt
thấp (ví dụ 400) thì thinking ăn hết, API trả **HTTP 200 với content rỗng** và
`finishReason=MAX_TOKENS`. Ở tầng trên nó hiện ra thành lỗi parse JSON khó hiểu.
`llm_max_output_tokens` đặt 1200; luôn kiểm `finishReason` trước khi parse.

`gemini-3.6-flash` không tắt được thinking (`thinkingBudget=0` trả 400). Nếu đổi model,
phải thử lại điều này.

### Eval trước tối ưu

Phải có bộ eval và số baseline **trước** khi đổi retrieval. Đây là nguyên tắc cứng, không phải thứ tự cho tiện.

### Kiểm process cũ đang chiếm port trước khi tin một kết quả debug lạ

Khi debug agent routing, `/ask` trả lời sai (route ra "docs" cho một câu hỏi doanh thu rõ ràng)
dù gọi thẳng `run_agent()` bằng script lại đúng. Nguyên nhân: một tiến trình
`uvicorn --port 8010` cũ từ phiên làm việc trước đó **vẫn đang chạy**, phục vụ code cũ
(trước khi có `src/agent/`), và request cứ thế trúng vào nó. Log của lần start MỚI
(`uv run uvicorn ...` lần sau) có báo lỗi bind port thất bại — chính log đó mới lộ ra
vấn đề, không phải log của server thật sự trả lời.

Bài học: khi một kết quả qua HTTP khác kết quả gọi hàm trực tiếp, nghi ngờ **server có
đúng là code hiện tại không** trước khi nghi ngờ logic. Kiểm bằng
`Get-NetTCPConnection -LocalPort <port> -State Listen` (PowerShell) rồi đối chiếu
`StartTime` của process với thời điểm sửa code gần nhất; giết process cũ trước khi
start lại, không chạy song song nhiều bản.

### `docker compose up` không tự rebuild image `api` khi sửa code

Gặp thật khi dựng Prometheus/Grafana (ADR-021): sửa `src/api.py`, chạy
`docker compose up -d api`, container start bình thường nhưng `/metrics` trả `404` —
image `enterprise-ai-api:local` vẫn là bản build cũ, compose không so sánh mã nguồn
với image đã có sẵn. Phải `docker compose build api` (hoặc `up --build`) sau MỌI lần
sửa `src/`/`sql/` trước khi `up` lại, không chỉ lần đầu.

### Cổng đã map ra host có thể bị kẹt bởi tiến trình không còn tồn tại

Gặp thật khi dựng Prometheus/Grafana: `Get-NetTCPConnection -LocalPort 8010` báo
`Listen` bởi một PID mà `Get-Process`/`taskkill`/`Get-CimInstance Win32_Process` đều
xác nhận **không tồn tại** — sống sót qua cả việc kill tiến trình host, restart Docker
Desktop, và `wsl --shutdown`. Đây là kẹt cổng ở tầng hệ điều hành/sandbox, không phải
lỗi cấu hình `compose.yaml`. Xử lý tạm: đổi map cổng host sang một cổng khác
(`"127.0.0.1:8011:8010"`) chỉ để xác minh pipeline hoạt động — cổng nội bộ trong mạng
compose (`api:8010`, cái Prometheus thực sự scrape) không đổi theo host port, nên kết
quả xác minh vẫn hợp lệ cho cấu hình gốc. Đừng đoán "container Running" nghĩa là
service bên trong đã đúng — kiểm bằng một request thật.

---

## 7. Kế hoạch xây dựng

Mỗi giai đoạn là một session độc lập. Bắt đầu chat mới được, không mất context nhờ `AGENTS.md` + `docs/architecture.md` + `docs/decisions.md` + git history.

| Giai đoạn | Trạng thái | Deliverables |
|---|---|---|
| **Skeleton** | DONE | `compose.yaml`, `Dockerfile`, `src/{api,config,db,schemas}.py`, 7 tests, CI, `docs/{architecture,decisions}.md` |
| **Tầng dữ liệu** | DONE | `sql/01_schema.sql` (7 bảng), `sql/02_seed.sql`, `sql/03_business_metrics.sql`, `sql/04_docs_point_in_time.sql`, `sql/05_explain.sql`, `src/contracts.py`, `scripts/ingest.py`, `data/documents.csv` (16 chunk) + `documents_dirty.csv`, 32 tests, `docs/query_plan.md` |
| **Retrieval nền tảng** | DONE | `src/embeddings.py`, `src/retrieval.py` (dense, pgvector), `src/generation.py` (structured output, 2 cổng kiểm), `src/eval_taxonomy.py` (8 nhãn), `scripts/{backfill_embeddings,run_eval}.py`, `eval/dev.jsonl` (25 câu), `docs/report.md`, 50 unit + 11 integration tests |
| **Agent routing** | DONE | Đo trước: 5 câu paraphrase mạnh, recall@3=5/5 — không có gì để hybrid cải thiện, ADR-011 ghi lý do không xây. `src/agent/{router,tools,schema,loop}.py` (2 tool: SQL + docs, RBAC trước thực thi, retry/timeout, KHÔNG phải ReAct nhiều bước — ADR-013), RBAC SQL theo phòng ban (ADR-012), test prompt injection thật (Gemini thật bị "thuyết phuc" đề xuất sai phòng ban, RBAC vẫn chặn) |
| **Xác thực & độ tin cậy** | DONE | Đóng lỗ hổng AuthN thật đã đo bằng curl (ADR-015): `src/auth.py` + `sql/06_auth.sql` + `scripts/issue_api_keys.py` — RBAC/agent giờ dùng role/department từ danh tính đã xác thực, không dùng trường request. `tests/test_rbac_isolation.py` (ma trận 61 ca), `src/audit.py` (ghi `audit_log`, ADR-017), `src/metrics.py` + `/metrics` (Prometheus, ADR-017), `docs/runbook.md`. Vá thêm 3 khoảng trống đo được: connection pool (`psycopg_pool`), `statement_timeout`, jitter cho retry (ADR-016) |
| **Báo cáo cuối** | DONE | `docs/report.md` (chạy 12 câu held-out **một lần**), README hoàn chỉnh, `docs/demo_script.md`, `docs/cv_bullets.md`, `docs/reading_order.md`, ADR-018/019. Bổ sung sau khi corpus chuyển sang có dấu (ADR-022): quy đổi chi phí token ra VNĐ/USD (ADR-023), held-out **vòng 2** — 12 câu mới, `sql/07_eval_held_out_employees.sql`, vá lỗ hổng retry thật ở `src/embeddings.py` phát hiện giữa lúc chạy (ADR-024), migration tooling Alembic (ADR-025), và đo lại jitter dưới tải đồng thời thật — không thấy cải thiện đo được ở mức nghẽn Gemini hôm đo (ADR-026) |

### Bootstrap Prompt cho session mới

**Tầng dữ liệu:**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md,
docs/architecture.md và docs/decisions.md để nắm context.
Tầng dữ liệu: thiết kế schema PostgreSQL cho business data + document
chunks + audit log, viết ingestion có contract validation, chạy EXPLAIN ANALYZE
trước/sau index.
Kiểm codebase hiện tại rồi bắt đầu.
```

**Retrieval nền tảng (hoàn thành 14/09/2026):**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md và
docs/decisions.md.
Retrieval nền tảng: dense retrieval + structured output cho /ask, rồi viết
bộ eval 40 câu có ground truth (28 dev / 12 held-out) và ĐO BASELINE trước khi
tối ưu bất cứ gì. Provider đã chốt ở ADR-002: Gemini, key có sẵn trong .env.
Kiểm codebase hiện tại rồi bắt đầu.
```

Kết quả thật khác kế hoạch ở một chỗ đáng ghi: chỉ 25 câu (không phải 40), và
`eval/final.jsonl` **để trống** — 5 câu held-out ban đầu bị chạy sớm (lỗi quy
trình, xem ADR-010), đã gộp vào dev với hậu tố `_seen_early` (ban đầu đặt tên
`_seen_at_d2`, đổi lại khi bỏ nhãn ngày khỏi toàn bộ dự án). Báo cáo cuối cần viết
một tập held-out mới, sau khi agent routing và xác thực đều xong.

**Agent routing (hoàn thành 14/09/2026):**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md,
docs/decisions.md (ADR-010) và docs/report.md.
Agent routing: baseline retrieval đã recall@3=100% trên 25 câu dev (corpus 16
chunk) — TRƯỚC KHI code hybrid, viết thêm câu hỏi khó hơn hoặc corpus lớn hơn để
biết dense retrieval còn giới hạn ở đâu; nếu không có gì để cải thiện thì ghi rõ
lý do không làm hybrid, đừng làm vì kế hoạch cũ nói vậy. Xây agent 2 tool (SQL +
docs) có timeout/retry/max_steps và test prompt injection.
Kiểm codebase hiện tại rồi bắt đầu.
```

Kết quả thật, đáng ghi: đo 5 câu paraphrase mạnh trước, recall@3=5/5 — quyết định
**không xây hybrid** (ADR-011), không phải vì hết thời gian mà vì không đo được lợi
ích nào. Agent là một pipeline có giới hạn (router → RBAC → thực thi → tổng hợp,
ADR-013), không phải vòng lặp ReAct nhiều bước — vì kiến trúc chỉ
cần đúng một quyết định phân loại, không cần agent tự đề xuất từng bước. RBAC cho SQL
giới hạn theo phòng ban, trừ executive (ADR-012); test prompt injection dùng Gemini
thật (không mock) để xác nhận RBAC chặn được ngay cả khi router bị "thuyết phục" đề
xuất sai phòng ban.

**Xác thực & độ tin cậy (hoàn thành 15/09/2026):**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md và
docs/architecture.md.
Xác thực & độ tin cậy: RBAC áp ở tầng truy vấn dữ liệu (không qua prompt), test
cách ly theo role, audit log, Prometheus metrics, async timeout, runbook.
Lưu ý: cache key phải chứa access scope, nếu không sẽ rò dữ liệu giữa các user.
Kiểm codebase hiện tại rồi bắt đầu.
```

Kết quả thật, đáng ghi: RBAC ở tầng truy vấn dữ liệu đã đúng từ trước — phát hiện
thật của giai đoạn này là **phía TRƯỚC RBAC** hoàn toàn trống: `role`/`department` chỉ là
trường request tự khai, không có gì xác thực (đo bằng `curl` thật, ADR-015). Vá
bằng API key thật (`src/auth.py`), không dừng ở việc thêm test — RBAC/agent đổi
sang dùng danh tính đã xác thực làm nguồn sự thật. Audit log và Prometheus đều là
dependency/bảng đã tồn tại từ trước, chưa từng dùng tới giờ mới thật sự ghi/expose.
Ghi chú "cache key phải chứa access scope" trong bootstrap prompt trên vẫn đúng
nhưng chưa áp dụng — dự án chưa có cache nào, nguyên tắc để
sẵn cho lần đầu tiên thêm cache.

**Báo cáo cuối (hoàn thành 15/09/2026):**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md và toàn bộ
evidence/.
Báo cáo cuối: chạy bộ 12 câu held-out MỘT LẦN, viết docs/report.md
(ablation, latency p50/p95, token cost kèm điều kiện đo), hoàn chỉnh README + sơ
đồ, script video demo 2-3 phút, bullet CV có số thật.
Kiểm codebase hiện tại rồi bắt đầu.
```

Kết quả thật, đáng ghi: `audit_log.total_tokens` tồn tại từ lâu nhưng chưa từng được
ghi — trước khi đo được "token cost kèm điều kiện đo" như bootstrap yêu cầu, phải vá
lỗ hổng đó trước (ADR-018), đổi kiểu trả về của `route()` để tránh một bug tương tranh
tương tự lớp lỗi ADR-016 đã gặp. Viết mới 12 câu held-out (`eval/final.jsonl`, chưa
từng chấm điểm) nhắm đúng vào hai khoảng trống các báo cáo trước đã tự ghi nhận
"chưa đo được": SQL-only và câu hỏi kết hợp cả hai tool. Chạy MỘT LẦN qua `/ask` thật
(không gọi `run_agent()` trong tiến trình) — 9/12 đúng, phát hiện 3 lỗi thật (router bỏ
sót tool ở câu kết hợp, một response tự mâu thuẫn khiến 502, một timeout mạng không được
retry dù lỗi HTTP status thì có). Cả ba **để nguyên không vá** — đúng luật ở mục 4
("xem điểm trên held-out rồi tiếp tục tinh chỉnh và báo lại trên chính tập đó" là bị
cấm), ghi lại làm backlog cho phiên sau thay vì âm thầm sửa rồi báo một con số đẹp
hơn (ADR-019). Bootstrap prompt trên nói "ablation" — thực tế đo được là so sánh
tool đã chọn (router) với tool đáng lẽ cần cho từng câu hỏi, không phải một ablation
kiểu bật/tắt thành phần hệ thống; ghi rõ ở đây để phiên sau không hiểu nhầm đã có một
thí nghiệm ablation đầy đủ hơn những gì thật sự đã chạy.

### Quy tắc kết thúc session (bắt buộc cho AI)

Khi hoàn thành tất cả deliverables của session:

1. **Chạy** `uv run ruff format`, `ruff check`, `mypy src/`, `pytest` — phải xanh trước khi commit
2. **Commit** theo Conventional Commits
3. **Cập nhật** bảng session ở trên: `TODO` thành `DONE`
4. **Ghi** mọi quyết định không hiển nhiên vào `docs/decisions.md` dưới dạng ADR mới
5. **Thông báo** cho user theo format: deliverables đã xong, bằng chứng đã chạy thật (lệnh + kết quả + file trong `evidence/`), còn mở gì cần user quyết, và bootstrap prompt của session kế tiếp

> ⚠️ AI không được tự nhảy sang session tiếp theo. User quyết định khi nào bắt đầu.
