# AGENTS.md — Enterprise AI Decision Platform

Hướng dẫn cho AI CLI (Claude Code, Gemini, Copilot, Cursor) khi làm việc với repo này.

---

## 1. Project Overview

**Bài toán:** API nội bộ doanh nghiệp. Nhân viên hỏi bằng ngôn ngữ tự nhiên, hệ thống tự chọn truy vấn **số liệu kinh doanh (SQL)** hay **tài liệu quy trình (retrieval)**, trả lời **kèm trích dẫn nguồn**, **chỉ trong phạm vi quyền của người hỏi**, và **ghi audit log** mọi lượt.

- **Input:** `{user_id, role, department, question}`
- **Output:** `{answer, citations[], tool_used, abstained, latency_ms}`
- **Dữ liệu:** tổng hợp, tự tạo cho project này. Không dùng tài liệu thật của công ty nào.

### Tiêu chí thành công

Đây là tiêu chí **về cách làm**, không phải ngưỡng số cố định — ngưỡng chỉ có nghĩa sau khi đo baseline ở D2.

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
| MLflow | >=2.17 | Tracking mỗi eval run (extra `eval`, từ D2) |
| prometheus-client | >=0.26 | Metrics (từ D4) |

**Quyết định còn mở:** LLM provider và embedding backend — xem `docs/decisions.md` ADR-002.

---

## 3. Common Commands

```bash
# Môi trường (PowerShell hoặc bash trên Windows)
uv sync --extra dev                 # Dependencies + dev tools
uv sync --extra dev --extra eval    # Thêm MLflow + BM25 (từ D2)

# Database
docker compose up -d db             # Chỉ bật PostgreSQL (dev thường ngày)
docker compose up -d                # Bật cả API trong container (demo)
docker compose down                 # Dừng, giữ dữ liệu trong named volume
docker compose down -v              # Dừng và XÓA dữ liệu

# Áp schema (thêm MSYS_NO_PATHCONV=1 nếu dùng Git Bash — xem mục 6)
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/00_extensions.sql

# API dev server
uv run uvicorn src.api:app --reload --port 8010
# http://127.0.0.1:8010/docs

# Test, lint, types
uv run pytest tests/ -v -m "not integration"    # Mặc định, không cần DB
uv run pytest tests/ -v -m integration          # Cần docker compose up -d db
uv run ruff check src/ tests/ scripts/
uv run ruff format src/ tests/ scripts/
uv run mypy src/
```

**Port đã dùng:** API `8010`, PostgreSQL `5433`. Tránh `8000` (fraud-detection-api) và `5546` (lab SQL ngày 6) vì hai cái đó có thể đang chạy song song.

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
- **Xem bộ 12 câu held-out** trước D5 — xem rồi là mất tính độc lập
- **Đổi quy tắc RBAC** — là quyết định bảo mật, không phải refactor
- **Thêm dependency lớn** (torch, transformers) — ảnh hưởng thời gian cài và kích thước image
- **`docker compose down -v`** — xóa dữ liệu

### Không bao giờ được làm

- **Commit `.env`** hoặc bất kỳ API key nào
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

### Vì sao `/ask` trả 501 ở D0

Một stub trả lời trông như thật sẽ làm endpoint trông như đã xong, và đó đúng là hành vi project này được xây để phản đối. Test `test_ask_is_honestly_unimplemented` sẽ phải được viết lại khi D2 implement thật — để việc đổi hành vi là hành động có ý thức.

### Eval trước tối ưu

D2 phải có bộ eval và số baseline **trước** khi D3 đổi retrieval. Đây là nguyên tắc cứng, không phải thứ tự cho tiện.

---

## 7. Session Plan (D0 → D5)

Mỗi ngày là một session độc lập. Bắt đầu chat mới được, không mất context nhờ `AGENTS.md` + `docs/architecture.md` + `docs/decisions.md` + git history.

Lịch học tương ứng nằm ở `CHIEN_LUOC_HOC_VA_LAM_PROJECT_RIKKEI.md` trong vault tài liệu (`D:\Documents\AI\Update`), không nằm trong repo này.

| Session | Trạng thái | Roadmap | Deliverables |
|---|---|---|---|
| **D0** | DONE | Ngày 5 (pandas) | Skeleton: `compose.yaml`, `Dockerfile`, `src/{api,config,db,schemas}.py`, 7 tests, CI, `docs/{architecture,decisions}.md` |
| **D1** | TODO | Ngày 6 + 7 | `sql/01_schema.sql`, `sql/02_seed.sql`, `scripts/ingest.py` có contract validation, `docs/query_plan.md` (EXPLAIN trước/sau index) |
| **D2** | TODO | Ngày 19 + 20 | `src/retrieval/dense.py`, `src/generation.py` (structured output), `eval/questions.jsonl` (40 câu: 28 dev / 12 held-out), `scripts/run_eval.py`, `evidence/eval_baseline.json` |
| **D3** | TODO | Ngày 21 + 22 | `src/retrieval/{lexical,fusion}.py`, `evidence/eval_hybrid.json` + bảng so sánh, `src/agent/` (2 tool, timeout, retry, max_steps), test prompt injection |
| **D4** | TODO | Ngày 25 + 26 | `src/security/scope.py`, `tests/test_rbac_isolation.py`, `src/audit.py`, Prometheus metrics, `docs/runbook.md` |
| **D5** | TODO | Ngày 29 | `docs/report.md` (chạy 12 câu held-out **một lần**), README hoàn chỉnh, video demo, bullet CV |

### Bootstrap Prompt cho session mới

**D1:**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md,
docs/architecture.md và docs/decisions.md để nắm context.
D1 (roadmap Ngày 6+7): thiết kế schema PostgreSQL cho business data + document
chunks + audit log, viết ingestion có contract validation, chạy EXPLAIN ANALYZE
trước/sau index.
Kiểm codebase hiện tại rồi bắt đầu.
```

**D2:**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md và
docs/decisions.md.
D2 (roadmap Ngày 19+20): dense retrieval + structured output cho /ask, rồi viết
bộ eval 40 câu có ground truth (28 dev / 12 held-out) và ĐO BASELINE trước khi
tối ưu bất cứ gì. Chốt LLM provider + embedding backend (ADR-002) trước khi code.
Kiểm codebase hiện tại rồi bắt đầu.
```

**D3:**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md và
evidence/eval_baseline.json.
D3 (roadmap Ngày 21+22): thêm lexical search + RRF fusion, đo lại trên ĐÚNG bộ
dev của D2, rồi xây agent 2 tool (SQL + docs) có timeout/retry/max_steps và test
prompt injection. Rerank chỉ làm nếu còn giờ, và phải đo cả latency trước khi
quyết định giữ.
Kiểm codebase hiện tại rồi bắt đầu.
```

**D4:**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md và
docs/architecture.md.
D4 (roadmap Ngày 25+26): RBAC áp ở tầng truy vấn dữ liệu (không qua prompt), test
cách ly theo role, audit log, Prometheus metrics, async timeout, runbook.
Lưu ý: cache key phải chứa access scope, nếu không sẽ rò dữ liệu giữa các user.
Kiểm codebase hiện tại rồi bắt đầu.
```

**D5:**

```text
Tôi tiếp tục project Enterprise AI Decision Platform. Đọc AGENTS.md và toàn bộ
evidence/.
D5 (roadmap Ngày 29): chạy bộ 12 câu held-out MỘT LẦN, viết docs/report.md
(ablation, latency p50/p95, token cost kèm điều kiện đo), hoàn chỉnh README + sơ
đồ, script video demo 2-3 phút, bullet CV có số thật.
Kiểm codebase hiện tại rồi bắt đầu.
```

### Quy tắc kết thúc session (bắt buộc cho AI)

Khi hoàn thành tất cả deliverables của session:

1. **Chạy** `uv run ruff format`, `ruff check`, `mypy src/`, `pytest` — phải xanh trước khi commit
2. **Commit** theo Conventional Commits
3. **Cập nhật** bảng session ở trên: `TODO` thành `DONE`
4. **Ghi** mọi quyết định không hiển nhiên vào `docs/decisions.md` dưới dạng ADR mới
5. **Thông báo** cho user theo format: deliverables đã xong, bằng chứng đã chạy thật (lệnh + kết quả + file trong `evidence/`), còn mở gì cần user quyết, và bootstrap prompt của session kế tiếp

> ⚠️ AI không được tự nhảy sang session tiếp theo. User quyết định khi nào bắt đầu.
