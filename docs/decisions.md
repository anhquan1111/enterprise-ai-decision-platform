# Decision log

Short records of choices that are not obvious from reading the code, so the
reasoning survives past the day it was made. Format: context → decision →
consequence. A decision that later turns out wrong is superseded here, not
silently edited.

Ghi chú về ngôn ngữ: ADR-001..005 (D0) viết bằng tiếng Anh, từ ADR-006 (D1) trở đi viết
bằng tiếng Việt để tác giả đọc lại nhanh hơn. Nội dung và format không đổi.

---

## ADR-001 — One PostgreSQL instance for business data, vectors and audit log

**Date:** D0 · **Status:** accepted

**Context.** The system needs relational business tables (for the SQL tool),
document chunks with embeddings (for the retrieval tool), and an audit trail. The
obvious alternative is a dedicated vector database (Qdrant, Weaviate) next to
PostgreSQL.

**Decision.** Use a single PostgreSQL 17 instance with the `pgvector` extension
for all three.

**Why.** Two reasons, in order of weight:

1. **Access control stays in one place.** Row-level scoping for SQL results and
   document chunks is enforced by the same `WHERE` clauses against the same
   session. With a separate vector store, the document side would need its own
   filter implementation, and two implementations of one security rule is how
   isolation bugs happen.
2. Fewer moving parts for a demo that must start with one command.

**Consequence.** Approximate-nearest-neighbour tuning options are narrower than a
dedicated vector DB. At a few hundred chunks this is irrelevant — exact search is
fast enough, and an honest "exact search, corpus is small" beats an untuned HNSW
index. Revisit only if measured latency says so.

---

## ADR-002 — LLM and embedding provider deliberately unset on D0

**Date:** D0 · **Status:** open, decide on D2

**Context.** Generation and embeddings both need a provider. Anthropic has no
embedding API; OpenAI and Google have both generation and embeddings; local
`sentence-transformers` embeddings are free but pull in torch (a large download).

**Decision.** `LLM_PROVIDER`, `LLM_MODEL` and `EMBEDDING_BACKEND` default to
`unset`/`local` and are read from the environment. No provider SDK is a hard
dependency yet; the `embed` and `eval` extras stay optional.

**Why.** Committing the skeleton to one vendor before the eval harness exists
would make the first measurement a vendor comparison instead of a baseline.

**Consequence.** D2 must pick one and record the exact model name and date in
`docs/report.md`, because model behaviour changes over time and a number without
a model name cannot be reproduced.

---

## ADR-003 — The eval set and the evidence files are committed; data and models are not

**Date:** D0 · **Status:** accepted

**Context.** `.gitignore` normally excludes data. But the evaluation questions are
ground truth written by hand, and every number in the README comes from a
specific run.

**Decision.** Commit `eval/` (questions and expected answers) and `evidence/`
(raw run outputs). Keep `data/raw/`, `models/`, `mlruns/` out.

**Why.** A claimed metric that cannot be traced to a file is not evidence. The
eval set is also the artefact that makes a retrieval change comparable across
days; versioning it in git (and with DVC once it grows) is what makes
"recall went from A to B" a statement about the system rather than about the
dataset.

**Consequence.** The eval set is visible to anyone reading the repo. That is
intended — it invites the reader to judge whether the questions are fair.

---

## ADR-004 — Liveness and readiness are separate endpoints

**Date:** D0 · **Status:** accepted

**Context.** A container healthcheck that calls the database will fail the
container when the database is briefly unavailable, and the orchestrator will
restart a process that was working fine.

**Decision.** `/health` reports only that the process is up and makes no
dependency calls. `/ready` checks PostgreSQL and returns 503 when it is
unreachable. The Docker `HEALTHCHECK` uses `/health`.

**Consequence.** A database outage makes the service not-ready (so traffic can be
withheld) without triggering a restart loop.

---

## ADR-005 — Database host defaults to `127.0.0.1`, never `localhost`

**Date:** D0 · **Status:** accepted, cause established by measurement

> **Correction.** The first version of this record blamed "the IPv6 attempt
> stalls", citing a `Test-NetConnection ::1` probe. That probe was unreliable (it
> returned `NotConnected` in 0.02s, which is not a connect result), and the
> explanation was wrong. The measurements below replace it.

**Context.** The integration test did not finish instead of failing fast.
Reproduced deliberately afterwards: with `POSTGRES_HOST=localhost` the same test
still does not finish within 240s; with `127.0.0.1` it passes in 0.44s.

**What was measured.**

| Probe | Result |
|---|---|
| `socket.getaddrinfo("localhost", 5433)` | returns `AF_INET6 ::1` **first**, then `AF_INET 127.0.0.1` |
| `Get-NetTCPConnection -LocalPort 5433 -State Listen` | one listener, `127.0.0.1` only — nothing on `[::1]` |
| raw Python `connect(("::1", 5433))` | `ConnectionRefusedError` after **2.04s** — refused, but not promptly |
| raw Python `connect(("127.0.0.1", 5433))` | connected in **0.000s** |
| `psycopg.connect(...@localhost...?connect_timeout=5)` | **succeeds in 5.08s** — exactly the timeout |
| `psycopg.connect(...@127.0.0.1...)` | succeeds in **0.04s** |

**Cause.** Three things compose into one slow path:

1. `localhost` is a name, and on this host it resolves IPv6-first.
2. Compose publishes the port as `127.0.0.1:5433:5432`, so `[::1]:5433` has no
   listener.
3. libpq tries resolved addresses **in order**, and `connect_timeout` is applied
   **per address**. The `::1` attempt is not rejected promptly here (~2s raw), so
   every new connection pays that cost before falling back to IPv4 — and with
   `connect_timeout=5` it burns the full 5s rather than the 2s, proving the wait
   is bounded by the timeout, not by the refusal.

**Confirmed by the fix.** Adding `connect_timeout=5` to the DSN turned the same
`localhost` run from "does not finish in 240s" into **10.91s, 1 passed** — the test
opens two connections, and 2 × 5s is the whole cost. The penalty is therefore
per-connection and linear, and the original runaway was that same penalty with **no
ceiling**, because libpq with no `connect_timeout` waits on the operating system
rather than on a bound of its own.

This also means the raw-socket measurement above (refused after 2.04s) was
measuring something narrower than libpq's connect path: a single socket's
refusal, not what libpq does while walking the address list. Why libpq's attempt
on `::1` is not ended by that refusal is the one piece still not isolated — and it
no longer matters operationally, because the timeout bounds it.

**Decision.** Default `POSTGRES_HOST` to `127.0.0.1` in both `src/config.py` and
`.env.example`. Keep the explicit IPv4 binding in compose: binding to all
interfaces would hide this and would also expose the database beyond the host.

**Follow-on decisions, both applied.**

1. `database_url` always appends `connect_timeout` (default 5s,
   `POSTGRES_CONNECT_TIMEOUT`). Verified against an unroutable address
   (`192.0.2.1`, TEST-NET-1): fails in **5.08s** with `ConnectionTimeout` instead
   of blocking.
2. `pytest-timeout` with a 30s per-test limit. Verified with a deliberate 10s
   sleep under `@pytest.mark.timeout(2)`: the run is cut and reported as a
   failure.

**The general lesson.** A missing timeout converts a fast error into an unbounded
wait, and a test with no time limit reports a hang as "still running" rather than
as a failure. Neither is a tuning detail: together they decide whether a fault
shows up as a clear error in seconds or as a frozen terminal. Every outbound call
added to this system later — LLM API, embedding service, reranker — gets a timeout
at the point it is written, not after it hangs once.

---

## ADR-006 — Contract dữ liệu là một module dùng chung, severity phân theo hậu quả

**Ngày:** D1 · **Trạng thái:** accepted

**Bối cảnh.** Dữ liệu tài liệu vào hệ thống qua ingestion, và sẽ được đọc lại ở đường
serving. Cách dễ nhất là kiểm ở mỗi nơi tiêu thụ.

**Quyết định.** Toàn bộ quy tắc nằm trong `src/contracts.py`, áp **một lần ở biên
ingestion**. Hai mức severity, phân theo **hậu quả nếu dòng đó vào bảng chính**:
`FATAL` đưa dòng vào quarantine, `WARNING` cho dòng vào nhưng đếm và báo.

**Vì sao.** Kiểm rải rác thì mỗi nơi kiểm một tập quy tắc hơi khác, và chỗ nào quên
thì chỗ đó sai. Với `access_level` điều này nghiêm trọng hơn: nó là ranh giới bảo mật,
nên một giá trị lạ phải bị từ chối chứ không được hạ xuống mức thấp nhất cho tiện —
một mức lạ rất có thể là mức cao hơn `executive`, và hạ nó xuống là công khai tài liệu
mật. Fail-closed.

Hai bản sao của cùng một contract cũng là cách sinh ra sai lệch train/serve: offline
chuẩn hóa một kiểu, online một kiểu, không bên nào báo lỗi.

**Hệ quả.** `doc_chunks_quarantine` giữ dòng thô kèm `reject_reason`, và `ingest_run`
lưu manifest mỗi lần chạy. Manifest nằm trong bảng chứ không phải file JSON để so được
giữa các lần chạy bằng SQL: tỷ lệ loại nhảy từ 5% lên 40% là tín hiệu, dù từng lý do
đều hợp lệ. `ck_rows_balance` ép `nhận + loại = số dòng trong file` ngay ở database.

---

## ADR-007 — Seed idempotent, không dùng TRUNCATE CASCADE

**Ngày:** D1 · **Trạng thái:** accepted, phát hiện khi chạy thật

**Bối cảnh.** Bản đầu của `sql/02_seed.sql` mở bằng
`TRUNCATE monthly_revenue, employees, departments CASCADE;` cho "sạch".

**Điều đã xảy ra.** `doc_chunks` có khóa ngoại tới `departments`, nên CASCADE lan sang
và **xóa toàn bộ corpus tài liệu đã ingest**. psql báo đúng điều đó:
`NOTICE: truncate cascades to table "doc_chunks"`.

**Quyết định.** Bỏ TRUNCATE. Cả ba bảng dùng `INSERT ... ON CONFLICT DO UPDATE`.

**Hệ quả.** Chạy lại seed bao nhiêu lần cũng an toàn và không ảnh hưởng dữ liệu tài
liệu. Cùng một tính chất idempotent mà ingestion đã có qua `ON CONFLICT DO UPDATE` trên
khóa tự nhiên — xem ADR-006.

**Bài học tổng quát.** Một lệnh dọn dẹp có CASCADE phải được đọc cùng với sơ đồ khóa
ngoại, không đọc một mình. "Cho sạch" là lý do yếu để xóa dữ liệu.

---

## ADR-008 — Giữ index ix_chunks_scope dù ở quy mô hiện tại chưa đo được lợi ích

**Ngày:** D1 · **Trạng thái:** accepted, có số đo

**Bối cảnh.** Corpus hiện có 16 chunk. Một index ở quy mô đó là chuẩn bị, không phải
tối ưu.

**Số đo** (chi tiết và cách tái lập: `docs/query_plan.md`):

| Quy mô | Kế hoạch | Execution Time |
|---:|---|---:|
| 16 dòng, có index | Index Scan | 0,085 ms |
| ~20k dòng, có index | Bitmap Heap Scan | 1,237 ms |
| ~20k dòng, không index | Seq Scan | 3,051 ms |

**Quyết định.** Giữ `ix_chunks_scope (department, access_level, available_at)`. Chưa tạo
ANN index (HNSW/IVFFlat) cho cột `embedding`.

**Vì sao.** Ở 20k dòng index nhanh hơn ~2,5 lần, và thứ tự cột khớp thứ tự lọc của
truy vấn retrieval: hai cột so sánh bằng trước, cột so sánh khoảng sau. Mức 2,5 lần là
khiêm tốn vì query trả về ~17% số dòng — index phát huy nhất khi chọn lọc cao, và lọc
theo một trong bốn phòng ban thì vốn không chọn lọc.

**Điều đo được trái dự đoán.** Ở 16 dòng, planner **vẫn chọn Index Scan**, không phải
Seq Scan như dự đoán ban đầu. Chi tiết đáng chú ý hơn là `Planning Time 0,572 ms` so
với `Execution Time 0,085 ms`: ở quy mô này lập kế hoạch tốn gấp 6 lần thực thi, nên
không có vấn đề hiệu năng nào để giải quyết.

**Hệ quả.** ANN index mở khi số đo nói cần, không mở vì nghe hợp lý. Mọi con số trên
đo bằng Docker trên Windows, dùng để so ba kế hoạch với nhau, không phải để báo latency
của hệ thống.
