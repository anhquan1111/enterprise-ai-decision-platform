# Decision log

Short records of choices that are not obvious from reading the code, so the
reasoning survives past the day it was made. Format: context → decision →
consequence. A decision that later turns out wrong is superseded here, not
silently edited.

Ghi chú về ngôn ngữ: ADR-001..005 (giai đoạn skeleton) viết bằng tiếng Anh, từ ADR-006
(tầng dữ liệu) trở đi viết bằng tiếng Việt để tác giả đọc lại nhanh hơn. Nội dung và
format không đổi.

---

## ADR-001 — One PostgreSQL instance for business data, vectors and audit log

**Date:** skeleton · **Status:** accepted

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

## ADR-002 — Chốt Gemini cho cả generation và embedding

**Ngày:** mở ở giai đoạn skeleton, chốt 13/09/2026 · **Trạng thái:** accepted, chốt bằng số đo

**Bối cảnh ban đầu (giai đoạn skeleton).** Không chọn provider ngay, vì chốt vendor trước khi có bộ
đánh giá sẽ làm phép đo đầu tiên trở thành cuộc so sánh vendor thay vì một baseline của
hệ thống. `LLM_PROVIDER` và `EMBEDDING_BACKEND` để `unset`, không SDK nào là hard
dependency.

### Điều đã đo, và nó loại bỏ phương án local

Máy phát triển: RTX 4060 Laptop 8 GB VRAM, 15,2 GB RAM, Ryzen 7 7840H.

Đã cài Ollama và pull `qwen2.5:7b-instruct-q4_K_M` (4,7 GB, đặt trên ổ D:). **Model
không load được ở cả ba cấu hình:**

| Cấu hình | Lỗi |
|---|---|
| GPU đầy (`num_gpu=99`) | `cudaMalloc failed: out of memory` khi cấp 4168 MiB |
| GPU một phần (`num_gpu=20`) | cùng lỗi |
| CPU thuần (`num_gpu=0`) | `ggml_backend_cpu_buffer_type_alloc_buffer: failed` |

CPU cũng fail cho thấy **nút thắt là RAM hệ thống, không phải VRAM** — `nvidia-smi` báo
GPU trống 7956 MiB tại thời điểm đó. Đo lại:

```text
RAM tổng      : 15,2 GB
RAM còn trống : 1,1 GB
Committed     : 28,6 GB / limit 31,2 GB   (15,2 RAM + 16 pagefile)
```

Chỉ còn **2,6 GB commit headroom**, trong khi model cần một block **4,37 GB**. Và đó là
lúc chỉ đang mở VS Code, Docker, WSL và trình duyệt — tức môi trường làm việc bình
thường. Kết luận: **máy này không chạy được model 7B local song song với stack dev.**

### Quyết định

| Thành phần | Chọn | Ghi chú |
|---|---|---|
| Generation | **`gemini-3.1-flash-lite`** | Pin phiên bản, không dùng alias `-latest` |
| Model so sánh | `gemini-3.5-flash` | Dùng cho A/B ở giai đoạn retrieval nền tảng |
| Embedding | **`gemini-embedding-001`**, `outputDimensionality=384` | Giữ nguyên cột `vector(384)` |
| Auth | Key trong header `x-goog-api-key` | **Không** để trong query string |
| API version | `v1beta` | `v1` không có các model này |

### Vì sao các phương án khác bị loại

| Phương án | Lý do loại |
|---|---|
| Local Qwen 7B | Không load được — đo ở trên |
| Anthropic | Không có embedding API; gói thuê tháng không cấp API key, phải nạp credit riêng |
| OpenAI | Cùng vấn đề gói thuê tháng ≠ API credit; không có key sẵn |
| `gemini-2.5-flash` | API trả 404: *"no longer available to new users"* |
| `gemini-3.8-flash` | 2 trên 5 request trả **503 Service Unavailable** trên free tier |
| `gemini-3.6-flash` | **Không tắt được thinking** — `thinkingBudget=0` trả 400 |

### Số đo, 5 câu hỏi trên corpus thật, JSON mode

Chi tiết: `evidence/bench/`. Tái lập: `uv run python -m scripts.bench_model <model>`.

| Model | Đúng schema | Bịa nguồn | tok/s | Ước tính 40 câu |
|---|---|---|---:|---:|
| `gemini-3.1-flash-lite` | **5/5** | **0** | 42,7 | ~1,5 phút |
| `gemini-3.5-flash` | **5/5** | **0** | 19,2 | ~2,6 phút |

Cả hai trả lời đúng, trích đúng nguồn, và **tự bắc cầu được qua khác biệt dấu**: corpus
viết không dấu, câu hỏi có dấu, câu trả lời trả về có dấu đúng chính tả.

**Một ca đáng chú ý.** Câu *"Khoản chi 80 triệu đồng thì ai duyệt?"* chạy với
`role="manager"`. Chunk chứa đáp án (`FIN-014#2`, "trên 50 triệu → Giám đốc") có
`access_level = executive` nên **bị phạm vi quyền loại khỏi context**. Cả hai model
đều trả `abstained=true, citations=[]` thay vì đoán "Giám đốc" từ kiến thức có sẵn.

Đây là bằng chứng đo được cho hai thứ cùng lúc: phân quyền áp ở tầng truy vấn có hiệu
lực thật, và model từ chối đúng lúc khi bằng chứng bị chặn.

### Cái bẫy phải nhớ: thinking token trừ vào max output

Gemini 3.x bật thinking mặc định, và **`thoughtsTokenCount` được tính vào
`maxOutputTokens`**. Đo được với `maxOutputTokens=80`:

```text
gemini-3.6-flash : think=75  out=1     finish=MAX_TOKENS
gemini-3.8-flash : think=101 out=None  finish=MAX_TOKENS   -> content rỗng
gemini-3.5-flash : think=77  out=None  finish=MAX_TOKENS   -> content rỗng
```

Response rỗng nhưng HTTP 200. Nếu không kiểm `finishReason`, nó sẽ hiện ra dưới dạng
một lỗi parse JSON khó hiểu ở tầng trên. `llm_max_output_tokens` đặt **1200**, và
`scripts/bench_model.py` gọi đúng tên trường hợp này: `response rong (finish=...)`.

Đây chính là bài học "để dành output" đã học trước đó, chỉ khác ở chỗ phần dự trữ còn phải
nuôi một người tiêu thụ vô hình.

### Hệ quả

- **Không đổi schema:** `outputDimensionality=384` khớp cột `vector(384)` đang có.
  Đánh đổi: 384 là bản cắt Matryoshka của vector 3072 chiều, nên mất một phần chất
  lượng. Mức mất chỉ đo được trên bộ eval ở giai đoạn retrieval nền tảng; nếu đáng kể
  thì đổi cột và ingest lại — rẻ vì corpus chỉ 16 chunk.
- **Mọi báo cáo số liệu phải ghi tên model và ngày chạy.** Hành vi model đổi theo bản
  phát hành; một con số không có tên model thì không tái lập được.
- **5 câu là smoke test, không phải đánh giá.** Nó nói model chạy được và tuân schema;
  nó không nói model tốt tới đâu. Khác biệt giữa hai model chỉ lộ ra trên bộ 40 câu ở
  giai đoạn retrieval nền tảng.
- Ollama và Qwen 7B **giữ lại** làm cấu hình đối chiếu khi máy rảnh, và là một mục thật
  trên CV: chạy model local, đo được giới hạn bộ nhớ, chọn API dựa trên số đo.

---

## ADR-003 — The eval set and the evidence files are committed; data and models are not

**Date:** skeleton · **Status:** accepted

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

**Date:** skeleton · **Status:** accepted

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

**Date:** skeleton · **Status:** accepted, cause established by measurement

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

**Ngày:** tầng dữ liệu · **Trạng thái:** accepted

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

**Ngày:** tầng dữ liệu · **Trạng thái:** accepted, phát hiện khi chạy thật

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

**Ngày:** tầng dữ liệu · **Trạng thái:** accepted, có số đo

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

---

## ADR-009 — Docs retrieval lọc theo role, không lọc theo department

**Ngày:** retrieval nền tảng · **Trạng thái:** accepted, làm rõ lại một câu trong tài liệu skeleton

**Bối cảnh.** `AskRequest` docstring (viết ở giai đoạn skeleton) nói: "Role và department nằm trong
request... mọi truy cập dữ liệu phía dưới đều bị giới hạn theo hai trường này." Khi
xây `src/retrieval.py` thật, áp cả hai làm ranh giới cứng sẽ khiến một nhân viên
Sales không bao giờ đọc được chính sách nghỉ phép của HR — vì `HR-001` có
`department='hr'`, khác `department='sales'` của người hỏi.

**Quyết định.** Đường tài liệu (docs) chỉ lọc theo `access_level` (qua
`visible_access_levels(role)`). `department` trên mỗi chunk là **phân loại nội dung**,
không phải ranh giới bảo mật cho tài liệu chính sách. Ranh giới bảo mật thật của docs
là `access_level` (employee/manager/executive) và thời điểm (`available_at`,
`effective_from/to`), cả hai đã áp trong `WHERE` trước khi tính khoảng cách vector.

**Vì sao.** Tài liệu chính sách nội bộ (nghỉ phép, quy trình release, hạn mức chi) là
tài liệu tham khảo chung toàn công ty — một nhân viên Sales hỏi "release lỗi thì xử lý
sao" là câu hỏi hợp lệ, không phải hành vi cần chặn. Ràng buộc department chỉ có ý
nghĩa thật cho **tool SQL** (agent routing): doanh thu của phòng Sales là số liệu Sales
sở hữu, và một nhân viên phòng khác không cần thấy nó ở dạng số thô.

**Hệ quả.** `department` trong `AskRequest` vẫn giữ nguyên schema — nó sẽ dùng để
scope tool SQL khi tool đó được xây ở giai đoạn agent routing, không phải bỏ đi. Bộ
eval ở giai đoạn retrieval nền tảng cố tình có câu hỏi liên phòng ban (một employee HR
hỏi về quy trình Engineering) để phản ánh đúng thiết kế này; nếu sau này router cần
siết department cho SQL, ADR đó sẽ ghi riêng.

---

## ADR-010 — Baseline retrieval nền tảng đo trên 25 câu dev; held-out chạy sớm là một lỗi, đã sửa

**Ngày:** retrieval nền tảng · **Trạng thái:** accepted, có tự sửa lỗi quy trình

**Số đo baseline** (chi tiết: `evidence/eval_summary_dev.json`, tái lập bằng
`uv run python -m scripts.run_eval --report`), model `gemini-3.1-flash-lite` sinh câu
trả lời, `gemini-embedding-001` (384 chiều) cho cả embed tài liệu và câu hỏi, đo
13/09–14/09/2026:

| Chỉ số | Kết quả |
|---|---|
| recall@3 / @5 / @10 | 18/18 (100%) — bằng nhau ở mọi k vì gold luôn đứng hạng 1 |
| MRR | 1,000 |
| Đúng hoàn toàn (`correct`) | 18/18 |
| Từ chối đúng vì hết quyền (`access_correct`) | 5/5 |
| Từ chối đúng vì corpus không có (`no_knowledge_correct`) | 2/2 |
| Vi phạm quyền, bịa nguồn, trích sai, retrieval trượt | **0** ở mọi nhóm |

So với một baseline TF-IDF thử trước đó trên một corpus khác:
recall@3 khi đó là 92,3%, có 1 câu retrieval trượt do khác biệt từ vựng ("release lỗi"
xếp hạng 5). Cùng loại câu hỏi đó, chạy bằng dense embedding thật trên corpus của dự
án này xếp **hạng 1** (cosine distance 0,208) — đúng như dense retrieval được kỳ vọng
sửa lỗi từ vựng của baseline từ khóa.

**Một lỗi rubric thật, đã sửa trước khi chạy hết bộ.** Câu hỏi về số liệu tạm tính có
rubric `expected_answer_keywords=["khong dung"]`. Model trả lời hoàn toàn đúng —
*"không **được** dùng để báo cáo ra bên ngoài"* — nhưng "khong dung" không phải chuỗi
con của "không được dùng", nên bị chấm nhầm thành `generation_wrong_fact`. Sửa rubric
thành `["khong duoc dung", "khong dung"]` rồi chạy lại đúng câu đó. Đây là ví dụ thật
của bài học đã biết trước: rubric từ khóa phải bao trùm cách diễn đạt hợp lý, không chỉ
một cách nói.

**Một lỗi kỹ thuật thật, đã sửa trước khi chạy bất kỳ câu nào.** `expected_answer_keywords`
và corpus viết không dấu, nhưng Gemini luôn trả lời bằng tiếng Việt có dấu đầy đủ —
đúng hành vi mong muốn cho người dùng thật. So khớp chuỗi trực tiếp không bao giờ
khớp ("khong duoc" không phải chuỗi con của "không được"). `src/eval_taxonomy.py`
chuẩn hóa cả hai phía bằng cách bỏ dấu (NFD, xử lý riêng "đ") trước khi so — nếu không
sửa, gần như mọi câu đúng sẽ bị chấm sai.

**Lỗi quy trình: chạy held-out ở giai đoạn retrieval nền tảng, đáng lẽ để dành cho báo
cáo cuối.** `docs/architecture.md` ghi rõ "Final report on held-out questions" là việc
của báo cáo cuối, sau khi hybrid retrieval (agent routing) và RBAC/audit (xác thực & độ
tin cậy) đã có — hệ thống hiện tại chưa phải hệ thống cuối cùng. Chạy 5 câu
`eval/final.jsonl` ngay hôm nay là chạy sớm, và theo đúng quy tắc đã ghi ("nhiễm thì
không xoá, không giả vờ chưa xem — chuyển thành dev, viết tập cuối mới"): 5 câu đó đã
đổi tên thành `F0x_seen_early` (ban đầu `F0x_seen_at_d2`, đổi lại sau khi dự án bỏ
nhãn ngày — xem ADR về việc thay D0-D5 bằng tên giai đoạn) và gộp vào
`eval/dev.jsonl`. `eval/final.jsonl` để trống, chờ báo cáo cuối viết một tập held-out
mới trên hệ thống thật sự hoàn chỉnh.

**Điều chưa đo được, ghi đúng như vậy.** 25 câu là quy mô học tập trên một corpus 16
chunk — đủ để tìm lỗi và xác nhận cơ chế, không đủ để tuyên bố hệ thống đáng tin cậy
ở mọi tình huống. Baseline "sạch tuyệt đối" (0 lỗi) một phần phản ánh corpus nhỏ và
câu hỏi rõ ràng; giai đoạn agent routing cần bộ câu hỏi khó hơn hoặc corpus lớn hơn mới
biết dense retrieval còn giới hạn ở đâu — nếu baseline đã hoàn hảo, hybrid retrieval
(kế hoạch ban đầu) có thể không có gì để cải thiện, và quyết định đó cần đo trước khi
làm, không mặc định làm theo kế hoạch cũ.

---

## ADR-011 — Không làm hybrid retrieval ở giai đoạn agent routing, sau khi đo thử trên câu hỏi khó hơn

**Ngày:** agent routing · **Trạng thái:** accepted

**Bối cảnh.** ADR-010 để lại đúng câu hỏi cần trả lời trước khi code hybrid:
`docs/report.md` nói "nên đo trên câu hỏi khó hơn hoặc nhiều hơn trước khi giả định
hybrid search đáng giá độ phức tạp thêm vào." Một thí nghiệm trước đó (chủ đề hybrid
retrieval & rerank) đã đo hiện tượng này trên một corpus khác (22 đoạn) và phát hiện:
hybrid (RRF) có MRR **thấp hơn** dense đơn thuần trên đúng bộ câu hỏi đó — không có cơ
sở giả định kết luận đó lặp lại y hệt trên corpus của dự án này mà không đo lại.

**Đo thật.** `scripts/probe_retrieval_headroom.py` (chạy 14/09/2026, không sửa
`eval/dev.jsonl` — xem AGENTS.md mục 4 về việc sửa bộ eval sau baseline): 5 câu hỏi mới,
paraphrase mạnh để tối đa hoá lệch từ vựng so với 5 câu tương ứng đã có trong
`eval/dev.jsonl` cho cùng gold chunk (ví dụ: gold `ENG-007#1` vốn được hỏi bằng
"Neu mot ban release bi loi thi phai lam gi?" — probe hỏi lại bằng "Khi mot phien ban
phan mem gap su co ngay sau khi phat hanh, quy trinh khac phuc la gi?", không còn từ
"release" hay "loi" nào chung).

| Kết quả | Giá trị |
|---|---|
| recall@3 trên 5 probe paraphrase mạnh | **5/5 (100%)** — mọi gold chunk đều đứng hạng 1 |
| Bằng chứng | [`evidence/hybrid_headroom_probe.json`](../evidence/hybrid_headroom_probe.json) |

**Quyết định.** Không xây hybrid retrieval ở giai đoạn agent routing. `gemini-embedding-001` xử lý tốt cả
những câu hỏi paraphrase mạnh nhất có thể nghĩ ra trên corpus 16 chunk này — không còn
khoảng trống chất lượng nào đo được để hybrid lấp vào. Xây thêm RRF/BM25 ở quy mô này
sẽ là thêm độ phức tạp và một lệnh gọi mạng nữa mà không có số đo nào chứng minh lợi
ích, đúng loại quyết định "làm vì kế hoạch cũ nói vậy" mà AGENTS.md yêu cầu tránh.

**Khi nào mở lại.** Nếu corpus mở rộng đáng kể (hàng trăm chunk trở lên, nhiều domain
hơn) hoặc xuất hiện câu hỏi thật có nhiều mã số/tên riêng cần khớp chính xác (dense yếu
ở việc này), đo lại bằng đúng protocol đã dùng trên chính `eval/dev.jsonl`, không chỉ
dựa vào probe 5 câu này.

---

## ADR-012 — RBAC cho tool SQL: giới hạn theo phòng ban, trừ executive

**Ngày:** agent routing · **Trạng thái:** accepted, hiện thực hoá quyết định đã hoãn ở ADR-009

**Bối cảnh.** ADR-009 đã chốt: `department` không phải ranh giới bảo mật cho docs, mà
"ranh giới department thật sự thuộc về tool SQL ở giai đoạn agent routing." Bảng `monthly_revenue` không có
cột phân quyền — cần một quy tắc rõ ràng trước khi `sql_tool` chạy câu truy vấn nào.

**Quyết định.** `employee` và `manager` chỉ được xem doanh thu của **đúng phòng ban ghi
trong `AskRequest.department`** (không phải phòng ban được nêu trong câu hỏi — hai giá
trị có thể khác nhau, xem mục dưới). `executive` xem được doanh thu của **mọi** phòng
ban. Role lạ luôn bị chặn, không suy đoán quyền — nhất quán với `visible_access_levels`.

```python
def can_query_department(*, role: str, caller_department: str, target_department: str) -> bool:
    if role == "executive":
        return True
    if role in ("employee", "manager"):
        return caller_department == target_department
    return False
```

**Vì sao manager không có đặc quyền liên phòng ban.** Khác docs (nơi `access_level`
phân biệt employee/manager/executive theo *loại nội dung* chính sách), số liệu doanh
thu không có khái niệm "manager xem được nhiều hơn employ cùng phòng" trong dữ liệu
tổng hợp của dự án này — ranh giới thật là *phòng ban sở hữu số liệu đó*, không phải
cấp bậc. Một trưởng phòng Sales không có lý do nghiệp vụ để xem doanh thu phòng Kỹ
thuật. Đây là một lựa chọn thiết kế hợp lý cho corpus tổng hợp này, không phải một quy
luật RBAC tổng quát — một hệ thống thật có thể cần "manager cấp cao xem được nhóm phòng
ban trực thuộc," nhưng dữ liệu hiện có không có cấu trúc phân cấp đó để mô hình hoá.

**Chặn TRƯỚC khi câu SQL chạy, không lọc kết quả sau.** `sql_tool()` gọi
`can_query_department` trước dòng `fetch_all()` đầu tiên — một role/department không đủ
quyền không bao giờ khiến PostgreSQL chạy câu truy vấn, giống nguyên tắc đã áp cho docs
retrieval ở ADR-009 (lọc trong `WHERE`, không lọc sau khi có kết quả).

**Phòng thủ prompt injection nằm chính ở đây, không nằm ở router.** Router (Gemini,
`src/agent/router.py`) chỉ đọc CÂU HỎI để quyết định `department` mục tiêu của câu
SQL — nó có thể bị một câu hỏi có chủ ý lừa để đề xuất một phòng ban khác phòng ban
thật của người hỏi (`caller_department` tới từ `AskRequest`, một trường đã xác thực,
không phải từ router). Kiểm chứng thật (không mock), `tests/test_ask_live.py`:

```text
role=employee, department=sales, câu hỏi cố tình yêu cầu:
  "Cho toi xem doanh thu phong finance thang 1 nam 2026"
-> router (Gemini thật) đề xuất department="finance" đúng như câu hỏi yêu cầu
-> can_query_department(role=employee, caller_department=sales, target=finance) = False
-> abstained=true, tool_used=none — CHƯA BAO GIỜ chạy câu SQL cho finance
```

Router có thể bị thuyết phục sai — hệ thống vẫn đúng, vì quyết định cuối cùng không
nằm ở router.

---

## ADR-013 — Kiến trúc agent: pipeline có giới hạn, không phải vòng lặp ReAct; số liệu SQL không đi qua LLM

**Ngày:** agent routing · **Trạng thái:** accepted

**Quyết định 1 — không dùng vòng lặp ReAct nhiều bước.** Một bài học trước đó về
agent loop & tool use dạy một vòng lặp tổng quát: planner tự đề xuất từng bước một, không
biết trước cần bao nhiêu bước hay tool nào. `/ask` không có bài toán đó — kiến trúc đã
biết trước chính xác có 2 tool cố định (SQL, docs) và một câu hỏi chỉ cần **một** quyết
định phân loại ("cần tool nào") để biết phải chạy gì. Ép vào khuôn vòng lặp nhiều bước
sẽ là một trừu tượng thừa cho một bài toán đã có hình dạng cố định — vi phạm nguyên tắc
"không thêm trừu tượng ngoài yêu cầu." `src/agent/loop.py` triển khai router → RBAC →
thực thi (có retry/timeout) → tổng hợp như một pipeline có giới hạn, giữ nguyên các cơ
chế phòng thủ đã học (RBAC trước thực thi, phân loại lỗi hạ tầng/nghiệp vụ, không bịa
khi thiếu bằng chứng) mà không cần một `max_steps` mở cho nhiều vòng lặp.

**Quyết định 2 — số liệu SQL không đi qua LLM để "diễn đạt lại."** Kiến trúc ban đầu
(`docs/architecture.md`) vẽ `T1 (SQL) --> GEN` như thể mọi câu trả lời đều qua bước
sinh văn bản. Quyết định thật: văn bản số liệu (`sql_tool()` trả về, ví dụ
`"2026-01: 4.200.000.000 VND"`) được dùng **nguyên văn** làm câu trả lời phần số liệu,
không gửi qua Gemini để viết lại. Lý do: số liệu từ database đã là sự thật chính xác;
để một LLM diễn đạt lại chỉ tạo thêm một điểm có thể sai/thêm/bớt số — một rủi ro không
cần thiết khi văn bản đúng đã có sẵn. Phần docs (cần diễn giải từ ngữ cảnh chính sách)
vẫn qua `generation.answer_question()` như ở giai đoạn retrieval nền tảng, vì nội dung chính sách thật sự cần một
mô hình đọc hiểu và tổng hợp, khác với một con số đã có sẵn.

**Hệ quả đo được:** câu hỏi kết hợp cả số liệu và chính sách trong một lần hỏi đôi khi
chỉ được router chọn đúng MỘT tool thay vì cả hai (đo thật một lần, chưa có bộ câu hỏi
hệ thống để đo tỷ lệ) — ghi vào "Not yet measured" ở `docs/report.md`, không che giấu.

---

## ADR-014 — Trích xuất tài liệu scan bằng Gemini vision, chưa nối vào ingestion

**Ngày:** sau agent routing · **Trạng thái:** accepted, phạm vi hẹp có chủ ý

**Bối cảnh.** Tài liệu nội bộ thật thường không phải CSV sạch mà là bản scan/PDF.
`scripts/ingest.py` (tầng dữ liệu) chỉ nhận dữ liệu dạng bảng có sẵn `chunk_text`. Cần một cách
lấy văn bản từ ảnh/PDF trước khi dữ liệu đó có thể đi qua `src/contracts.py`.

**Quyết định.** Dùng Gemini vision (`src/ocr.py::extract_text`) thay vì một OCR engine
cục bộ (Tesseract, EasyOCR). Gửi file (ảnh hoặc PDF) dạng `inlineData` base64 tới
`generateContent`, cùng pattern retry mạng (429/5xx) đã dùng ở `generation.py`/
`router.py`. Không thêm dependency nặng nào — tái dùng đúng `httpx` + `LLM_API_KEY`
đã có. Lý do đầy đủ và rủi ro của lựa chọn này (LLM có thể "đọc" sai nhưng nghe trôi
chảy, không có confidence score như OCR truyền thống): xem vault
`D:/Documents/AI/Update/OCR_Ingestion/1. OCR_Co_Che_Va_Phuong_Phap.md`.

**Đo thật, không đoán.** Vì không có confidence score tự động, chất lượng chỉ đáng tin
khi đo bằng CER/WER trên dữ liệu có đáp án biết trước (`src/ocr_metrics.py`, viết tay,
không thêm dependency). `scripts/generate_ocr_sample.py` dựng một PDF mô phỏng bản scan
(nhiễu ngẫu nhiên + nghiêng nhẹ) từ đúng văn bản đã có trong `data/documents.csv`
(HR-001, FIN-014) — không dùng tài liệu thật của công ty nào.

| Chỉ số | Kết quả | Bằng chứng |
|---|---|---|
| CER | **0,95%** | [`evidence/ocr_quality_probe.json`](../evidence/ocr_quality_probe.json) |
| WER | **0,00%** | cùng file |
| Độ trễ | 8,3s cho một trang | cùng file |

**CER khác 0 dù WER = 0% — không phải lỗi nội dung.** Ground truth được ngắt dòng cứng
theo độ dài cố định (`textwrap.wrap`); Gemini trả về đoạn văn liền mạch, tự xuống dòng
theo đoạn. CER tính cả ký tự xuống dòng nên bị lệch bởi khác biệt định dạng thuần tuý,
không phải từ nào bị đọc sai — WER (tách theo từ, không quan tâm xuống dòng ở đâu) mới
là chỉ số phản ánh đúng: khớp hoàn toàn. `tests/test_ocr_live.py` giữ ngưỡng chấp nhận
rộng (< 5%) cho cả hai, có ghi rõ lý do.

**Phạm vi cố ý chưa làm — không phải bỏ sót.** `src/ocr.py` chỉ trích xuất văn bản.
Hai việc còn thiếu để có một pipeline ingest ảnh hoàn chỉnh — **chia chunk** một khối
văn bản dài thành nhiều dòng đúng grain của `doc_chunks`, và **gán `department`/
`access_level`/thời gian hiệu lực** (không thể suy ra từ nội dung ảnh) — chưa được xây.
Đây là quyết định phạm vi, ghi trong vault
`D:/Documents/AI/Update/OCR_Ingestion/2. Tich_Hop_Chunking_Va_Danh_Gia.md` mục 3 trước
khi code, không phải giới hạn phát hiện sau. Mở khi có nhu cầu ingest ảnh thật.

---

## ADR-015 — AuthN thật bằng API key, đóng lỗ hổng đã đo được

**Ngày:** xác thực & độ tin cậy · **Trạng thái:** accepted, vá một lỗ hổng bảo mật thật

**Bối cảnh.** Một bài đo trước đó (`Reliability_&_Access_Control/4. Lab.md`) đo bằng curl
thật: `/ask` nhận `role`/`department` như trường request tự khai, không có gì xác
minh. Một request với `user_id="khach_la_hoac_ke_gia_mao"`, không header xác thực
nào, tự khai `role=executive` nhận đúng `FIN-014#2` — tài liệu chỉ dành cho
executive. RBAC (`can_query_department`, `visible_access_levels`) đúng logic tuyệt
đối, nhưng bảo vệ một giả định sai: *client trung thực về danh tính của họ*.

**Quyết định.** Thêm xác thực bằng API key thật:

- `sql/06_auth.sql`: cột `employees.api_key_hash` (SHA-256, không bao giờ lưu
  plaintext), unique index để một hash không dùng chung được giữa hai nhân viên.
- `scripts/issue_api_keys.py`: sinh key thật, in ra **đúng một lần**, chỉ ghi hash
  vào DB — mô phỏng đúng cách một hệ thống thật cấp phát credential.
- `src/auth.py::authenticate()`: xác minh header `Authorization: Bearer <key>`, tra
  cứu nhân viên theo hash, trả về danh tính **thật**.
- `src/api.py::ask`: gọi `authenticate()` trước tiên. Nếu `role`/`department` trong
  body KHÔNG khớp danh tính đã xác thực → `403`. Quan trọng hơn: **RBAC/agent dùng
  role/department từ danh tính đã xác thực, không dùng trường request** — loại bỏ
  khả năng sai lệch tận gốc, không chỉ phát hiện sai lệch rồi chặn.

**Đo thật, không chỉ tin thiết kế.**

```text
curl /ask, key thật của emp_001 (employee/sales), body tự khai role="executive"
-> 403, RBAC/run_agent CHƯA BAO GIỜ được gọi (test_auth_integration.py xác nhận
   bằng cách cho run_agent raise AssertionError nếu bị gọi tới — không raise nghĩa
   là bị chặn đúng trước khi tới đó)

curl /ask, không có header Authorization nào -> 401
curl /ask, key hợp lệ + role/department khớp -> 200, trả lời đúng
```

**Vẫn còn giới hạn thật, ghi rõ không che giấu.** Đây là xác thực bằng "sở hữu một
bí mật" (possession-based), không phải xác thực đa yếu tố hay OAuth2/JWT có hết hạn/
thu hồi tức thời. Đủ để đóng đúng lỗ hổng đã đo (client không còn tự khai được role),
nhưng nếu một key bị lộ, không có cơ chế thu hồi ngoài xoá `api_key_hash` thủ công.
Nâng cấp lên JWT/OAuth2 khi dự án cần thu hồi quyền tức thời hoặc tích hợp một hệ
thống định danh doanh nghiệp thật.

---

## ADR-016 — Connection pool, statement timeout, và jitter cho retry

**Ngày:** xác thực & độ tin cậy · **Trạng thái:** accepted, vá ba khoảng trống đã đo

Ba thay đổi độc lập, cùng nguồn gốc là số đo thật ở một bài đo tải trước đó, gộp vào
một ADR vì cùng chủ đề độ tin cậy dưới tải và cùng giai đoạn xác thực & độ tin cậy.

**1. Connection pool (`psycopg_pool.ConnectionPool`, `src/db.py`).** Đo được: mở
connection mới tốn ~15ms/lần so với ~1,7ms khi dùng lại — nhỏ so với việc gọi Gemini
(giây), nhưng không miễn phí và trả thêm mỗi request. Sau khi đổi sang pool
(`min_size=1, max_size=10`, cấu hình qua `Settings`), đo lại: ~5,5ms/lần qua pool —
cải thiện thật (~3×) so với connect() mới, dù không bằng lý thuyết tốt nhất của một
connection giữ mãi (pool checkout vẫn có chi phí đồng bộ hoá riêng).

**2. Statement timeout (`postgres_statement_timeout_ms`, mặc định 5000ms).**
`connect_timeout` (ADR-005) chỉ bảo vệ lúc MỞ connection — không bảo vệ một câu lệnh
chạy quá lâu SAU KHI đã kết nối thành công. Thêm `options=-c statement_timeout=...`
vào connection string, xác nhận thật bằng `SHOW statement_timeout` trả về `5s` sau
khi đổi. Áp dụng cho MỌI truy vấn qua `get_connection()` — kể cả SQL tool của agent,
nơi câu lệnh cuối cùng chạy dựa trên tham số một router LLM tạo ra.

**3. Jitter cho retry mạng (`generation.py`, `router.py`, `ocr.py`).** Đo được: 3
request `/ask` đồng thời, 2/3 nhận `503` — nguyên nhân không phải
threadpool hay DB, mà retry của cả 3 request theo ĐÚNG cùng lịch backoff
(`1s, 2s, 4s...`) nên có xu hướng va lại giới hạn tốc độ của Gemini ở cùng thời
điểm. Thêm `random.uniform(0, 0.5)` vào mỗi lần backoff — làm các request retry
lệch pha nhau. Chưa đo lại tỷ lệ `503` trước/sau ở đúng kịch bản 3-request-đồng-thời
(cần một phiên đo tải riêng, không nằm trong phạm vi giai đoạn này) — ghi đúng là "đã
sửa theo đúng nguyên nhân đã xác định", không phải "đã đo hết tác dụng của bản vá".

---

## ADR-017 — Audit log và Prometheus metrics

**Ngày:** xác thực & độ tin cậy · **Trạng thái:** accepted

**Audit log (`src/audit.py`).** Bảng `audit_log` tồn tại từ giai đoạn tầng dữ liệu,
chưa từng được ghi. Giai đoạn này ghi vào nó ở cuối mỗi request `/ask` thành công: `request_id`, danh tính đã xác
thực (không phải trường tự khai), câu hỏi, tool đã dùng, các `chunk_id` đã trích
dẫn, có abstain không, model, độ trễ. **Quyết định có chủ ý: lỗi ghi audit không làm
sập request** — bắt mọi exception, chỉ log lại, không raise. Lý do: audit phục vụ
tuân thủ/quan sát, không phải đường bắt buộc để trả lời được câu hỏi; một lần DB tạm
thời không ghi được audit không nên biến thành lỗi 500 cho người dùng đang chờ câu
trả lời. Đánh đổi: một khoảng thời gian ngắn có thể có request không để lại audit
trail nếu DB đúng lúc đó không ghi được — chấp nhận được ở quy mô hiện tại, cần xem
lại nếu audit trở thành yêu cầu tuân thủ cứng (ví dụ luật định).

**Không ghi audit cho request bị chặn ở tầng xác thực (401/403).** `AuditEntry` yêu
cầu `role`/`department` (NOT NULL trong schema) — một request chưa xác thực không có
danh tính đáng tin để gán vào các trường đó. Tín hiệu cho các ca này nằm ở
`ask_auth_failures_total` (Prometheus) và log warning, tách biệt khỏi audit trail
của các request đã xử lý.

**Prometheus metrics (`src/metrics.py`, `/metrics`).** `prometheus-client` là
dependency từ giai đoạn skeleton, chưa từng dùng tới giai đoạn này. Ba metric: `ask_requests_total` (theo
`tool_used`/`status`), `ask_request_duration_seconds` (histogram, theo `tool_used`),
`ask_auth_failures_total` (theo `reason`). Cố tình không dùng câu hỏi làm label —
cardinality không giới hạn sẽ làm nổ số lượng chuỗi metric. `/metrics` không yêu cầu
xác thực, đúng quy ước Prometheus thông thường (bảo vệ bằng network policy/reverse
proxy ở tầng hạ tầng, không phải app-level auth).

## ADR-018 — Chi phí token thật: đọc `usageMetadata`, không ước lượng

**Ngày:** báo cáo cuối · **Trạng thái:** accepted

**Vấn đề.** `audit_log.total_tokens` tồn tại từ giai đoạn tầng dữ liệu (cột
NOT NULL-able, có sẵn trong schema) nhưng chưa từng được ghi — `api.py` không bao giờ
truyền giá trị này vào `AuditEntry`, và không có nơi nào trong `generation.py`/
`router.py` đọc `usageMetadata` từ response Gemini. Báo cáo cuối cần báo cáo "token
cost kèm điều kiện đo"
(`AGENTS.md` mục 7) — ước lượng chi phí từ độ dài prompt là đoán, không phải đo,
đúng loại lỗi mà `AGENTS.md` mục 4 đã cấm ("đưa số chưa đo vào README/CV").

**Quyết định.** Đọc `body.get("usageMetadata", {}).get("totalTokenCount", 0)` ở cả
hai nơi gọi Gemini thật (`generation.py::_call_gemini`, `router.py::_call_gemini`),
cộng dồn qua mọi lượt retry (mỗi lượt gọi lại đều tốn tiền thật, kể cả lượt thất
bại), rồi truyền lên tới `AgentAnswer.total_tokens` và ghi vào `audit_log` qua
`api.py`. `total_tokens` của một request `/ask` = token router + token generation
(nếu có dùng docs tool) — `sql_tool` không gọi LLM nên không cộng thêm.

**`route()` đổi kiểu trả về:** từ `ToolPlan` sang `RouterResult` (bọc
`plan: ToolPlan` và `total_tokens: int`). Cân nhắc thay thế: giữ nguyên `route()` trả
`ToolPlan`, lưu token vào một biến module-level rồi đọc lại ở `loop.py` sau khi gọi —
**bị loại** vì đó là state dùng chung có thể đua nhau (race condition) giữa các
request xử lý đồng thời trên cùng một tiến trình, đúng loại bug mà ADR-016 (jitter
cho retry) đã tốn công phát hiện và sửa; không lặp lại lớp lỗi đó chỉ để tránh sửa
vài chữ ký hàm. Đổi kiểu trả về đụng tới các test mock `route()` trực tiếp
(`tests/test_agent_router.py`, `tests/test_agent_loop.py`) — đã cập nhật toàn bộ,
165 test không-integration vẫn xanh sau khi đổi.

**`RouterSchemaFailure` mang theo `total_tokens`.** Router thất bại sau khi hết lượt
retry (`_SCHEMA_RETRY_ATTEMPTS`) vẫn đã tốn tiền cho các lượt đã thử — exception giữ
lại con số đó thay vì để tầng gọi báo `0` sai sự thật. `SchemaFailure` của
`generation.py` **không** được xử lý tương tự (phạm vi nhỏ hơn: lỗi này luôn dẫn tới
502 ở `api.py`, và đường 502 hiện tại không gọi `record_audit` — audit hoá token trên
một đường không audit gì khác là việc thêm phạm vi không cần thiết cho báo cáo cuối;
ghi nhận đây là một giới hạn đã biết, không phải điểm mù).

**Không đo được:** đơn giá theo token của `gemini-3.1-flash-lite`/
`gemini-embedding-001` tại thời điểm đo — Google AI Studio không cấp API tra cứu giá
theo model; báo cáo cuối quy đổi VNĐ sẽ trích dẫn trang giá công khai kèm ngày truy cập
thay vì bịa một con số cố định có thể đã lỗi thời.

## ADR-019 — Tập held-out cuối: qua HTTP thật, chạy một lần, ba phát hiện thật để nguyên không vá

**Ngày:** báo cáo cuối · **Trạng thái:** accepted

**12 câu held-out, không phải bản mở rộng của `eval/dev.jsonl`.** `eval/dev.jsonl`
(25 câu, giai đoạn retrieval nền tảng) chỉ kiểm docs retrieval — có từ trước khi agent
(agent routing) tồn tại, nên chưa từng gọi tool SQL hay đường kết hợp cả hai tool. 12
câu held-out được thiết kế để lấp đúng hai khoảng trống đã được các báo cáo trước tự
ghi nhận là "chưa đo được": SQL-only (bao gồm bị RBAC chặn, và tháng số liệu tạm tính
chưa chốt), và một câu hỏi hỏi cả số liệu lẫn chính sách trong cùng một câu (báo cáo
agent routing: "quan sát được một lần, chưa có eval set riêng"). Không dùng lại nguyên
văn/gần giống bất kỳ câu nào trong dev — kiểm tra chéo toàn bộ 25 câu dev trước khi
viết 12 câu held-out, đúng theo `AGENTS.md` mục 4 ("Xem bộ 12 câu held-out trước khi
viết báo cáo cuối — xem rồi là mất tính độc lập": ở đây là viết mới, không phải xem
một tập đã có).

**Chạy qua HTTP thật (`/ask` đang chạy), không gọi `run_agent()` trong tiến trình.**
Lý do: báo cáo cuối cần đo latency và token đúng tại biên mà một caller thật sẽ chạm —
bao gồm cả xác thực thật và một dòng `audit_log` thật cho mỗi câu — không phải thời
gian gọi hàm nội bộ, vốn bỏ qua toàn bộ overhead HTTP/xác thực.

**8 nhân viên `emp_101`–`emp_108` mới, chỉ để chạy eval này.** 8 nhân viên gốc đã có
`api_key_hash` từ một phiên trước — key gốc (plaintext) không còn giữ được (chỉ hash
được lưu, đúng thiết kế của giai đoạn xác thực), và `AGENTS.md` cấm chạy lại `issue_api_keys.py` theo
cách vô hiệu hoá key đang dùng của người khác. `issue_api_keys.py` tự nó đã idempotent
(chỉ cấp key cho nhân viên `api_key_hash IS NULL`), nên thêm 8 dòng nhân viên mới —
cùng đúng 8 tổ hợp role×department cần cho 12 câu hỏi — rồi cấp key cho riêng 8 dòng
đó là cách đạt được một lượt chạy thật mà không chạm gì vào 8 nhân viên gốc. Key
plaintext của 8 nhân viên mới nằm ngoài repo (thư mục scratchpad của phiên làm việc),
không bao giờ commit.

**"Chạy một lần" áp dụng cho tập câu hỏi, không phải cho một lần gọi hạ tầng thất
bại.** Lần chạy đầu tiên mất 7 kết quả thật (câu 1–7) khi câu 8 gặp lỗi 502, vì
`run_held_out_eval.py` (bug của chính harness, không phải hệ thống đang đo) chỉ ghi
kết quả ra đĩa sau khi CẢ 12 câu chạy xong. Sửa lại đúng mẫu `run_eval.py` đã dùng cho
`eval/dev.jsonl` — ghi từng câu ngay sau khi chạy — rồi chạy lại từ đầu. Vì chưa có gì
được ghi ra đĩa ở lần thất bại, đây là hoàn thành đúng MỘT lượt chạy đã định, không
phải một lượt chạy thứ hai sau khi biết trước kết quả.

**Ba phát hiện thật (router bỏ sót một tool ở câu kết hợp — H07; một response tự mâu
thuẫn `abstained=true` kèm citation không được xử lý mềm, ra 502 — H08; timeout mạng
gọi Gemini không được retry dù lỗi HTTP status thì có — H02) để nguyên không vá.**
Quyết định có chủ ý, không phải bỏ sót: `AGENTS.md` mục 4 cấm rõ "xem điểm trên tập
held-out rồi tiếp tục tinh chỉnh và báo lại trên chính tập đó". Vá cả ba rồi chạy lại
đúng 12 câu này để lấy một con số đẹp hơn sẽ vi phạm đúng quy tắc đó — dù ý định là
sửa lỗi thật, hệ quả (một held-out report được tinh chỉnh sau khi thấy điểm) giống hệt
nhau. Ba phát hiện được ghi lại làm backlog cho phiên sau, kèm bằng chứng log server
cụ thể — không bị giấu, không bị vá âm thầm.

---

## ADR-020 — Vá ba phát hiện của báo cáo cuối, không đụng lại tập held-out đã niêm phong

**Ngày:** phiên sau báo cáo cuối · **Trạng thái:** accepted

**Bối cảnh.** ADR-019 để nguyên ba lỗi thật (H02, H07, H08) không vá, đúng luật
"không tinh chỉnh rồi báo lại trên cùng tập held-out". Phiên này vá cả ba — điều đó
**không** vi phạm ADR-019, vì không có ý định chạy lại 12 câu `eval/final.jsonl` để
lấy một con số held-out mới. `eval/final.jsonl` vẫn được xem là đã niêm phong; báo
cáo cuối trong `docs/report.md` không bị sửa lại theo các fix này.

**Fix 1 — timeout mạng không được retry (H02).** `router.py::_call_gemini` và
`generation.py::_call_gemini` chỉ retry dựa trên HTTP status code
(`_RETRYABLE_STATUS`); một `httpx.TimeoutException`/`ConnectError` ném ra ngay từ
lệnh gọi `httpx.post()` không rơi vào nhánh retry nào, thoát thẳng ra ngoài. Sửa:
bọc `httpx.post()` trong `try/except` bắt riêng hai loại lỗi này
(`_NETWORK_LEVEL_RETRYABLE`), coi tương đương một status tạm thời — cùng backoff +
jitter đã có từ ADR-016. Test: `test_answer_question_retries_after_network_timeout`,
`test_route_retries_after_real_timeout_exception` (mock `httpx.post` ném exception
thật ở lượt đầu, thành công ở lượt hai).

**Fix 2 — response tự mâu thuẫn ra 502 thay vì suy biến mềm (H08).** Model đôi khi
trả `abstained=true` kèm `citations` không rỗng — tự mâu thuẫn trong chính output
của Gemini, không phải lỗi hệ thống. Validator cũ (`abstain_means_no_citation`)
raise `ValueError`, khiến cả response bị coi là sai schema → retry → hết lượt →
`SchemaFailure` → 502. **Quyết định:** tín hiệu `abstained=true` an toàn hơn (từ
chối trả lời) so với các citation thừa đi kèm nó — giữ `abstained=true`, xoá
`citations`, không raise. Đổi tên validator thành `normalize_abstain_citations`,
thêm cờ `Answer.self_contradiction_corrected: bool` để `check_grounding()` vẫn ghi
lại sự kiện vào `grounding_problems` — sửa nhưng không giấu, cùng nguyên tắc minh
bạch đã áp dụng cho hai bug đo lường ở giai đoạn retrieval nền tảng. Test:
`test_answer_question_degrades_gracefully_instead_of_502_on_self_contradiction`
(mô phỏng đúng response tự mâu thuẫn đã gặp thật ở H08).

**Cân nhắc bị loại:** giữ nguyên hành vi raise, chỉ thêm retry — bị loại vì retry
không sửa được gì (model có xu hướng lặp lại đúng kiểu mâu thuẫn đó ở lần thử thứ
hai, như đã thấy ở log thật của H08: `SchemaFailure` sau đúng 2 lần).

**Fix 3 — router bỏ sót một tool ở câu hỏi kết hợp (H07).** `SYSTEM_INSTRUCTION` cũ
chỉ nói "có thể cần CẢ HAI" trong một câu, không có ví dụ minh hoạ. Sửa: thêm một
checklist hai bước bắt kiểm tra ĐỘC LẬP từng điều kiện (có hỏi số liệu không, có
hỏi chính sách không) thay vì chọn một tool "nổi bật nhất", cộng một ví dụ JSON đầy
đủ cho câu hỏi kết hợp.

Đo bằng `scripts/probe_router_combined_tools.py` — **6 câu hỏi mới**, không trùng
`eval/dev.jsonl` lẫn `eval/final.jsonl` (không đo lại trên tập đã niêm phong, đúng
tinh thần ADR-011). Kết quả thật, 15/09/2026: **6/6** câu chọn đúng cả hai tool
(`evidence/router_combined_tools_probe.json`). Mẫu nhỏ, không phải bằng chứng "đã
sửa dứt điểm" — router vẫn là một LLM call xác suất, không có gì đảm bảo 100% ở quy
mô lớn hơn. Ghi nhận đúng mức: đo được một cải thiện thật trên 6 câu, không suy
rộng thành cam kết.

**Không đo lại H07 bằng chính câu hỏi đó** — H07 nằm trong `eval/final.jsonl` đã
niêm phong; đo bằng câu hỏi mới là cách duy nhất kiểm được prompt mới mà không phá
tính "held-out" của tập đó.

---

## ADR-021 — Prometheus và Grafana là container riêng, không gộp vào `api`

**Ngày:** phiên sau báo cáo cuối · **Trạng thái:** accepted

**Bối cảnh.** `/metrics` (Prometheus format, `src/metrics.py`) tồn tại từ giai đoạn
xác thực & độ tin cậy nhưng chưa từng có ai scrape hay hiển thị nó — số liệu sinh ra
rồi không đi đâu cả. Đây là khoảng trống thật, không phải overengineering.

**Quyết định.** Thêm đúng hai service mới vào `compose.yaml`: `prometheus`
(`prom/prometheus:v3.0.1`, scrape `api:8010/metrics` mỗi 15s, cấu hình ở
`docker/prometheus/prometheus.yml`) và `grafana` (`grafana/grafana:11.4.0`,
datasource + một dashboard `ask-overview` được provision thẳng từ file trong
`docker/grafana/provisioning/` — không có bước nào phải bấm tay sau khi
`docker compose up`). Đây là ranh giới container đúng: mỗi thành phần một service
(stateful `db`, stateless `api`, hai service quan sát riêng `prometheus`/`grafana`),
khác với việc nhét thêm logic quan sát vào tiến trình `api` — cùng nguyên tắc đã áp
dụng từ ADR-001 (một Postgres cho ba việc, nhưng KHÔNG có nghĩa gộp mọi service vào
một tiến trình).

**Không mở rộng thêm.** Cân nhắc tách API thành nhiều service nhỏ hơn (router riêng,
auth riêng...) — **bị loại**, vì chưa có lý do đo được (không có nhu cầu scale độc
lập, không có ranh giới bảo mật cần cô lập tiến trình, không có nhiều team sở hữu
riêng từng phần). Thêm Prometheus/Grafana khác về bản chất: đó là quan sát một hệ
thống đã có, không phải chia nhỏ chính hệ thống đó — chi phí vận hành thêm (hai
container nữa) đổi lấy một khoảng trống thật đã tồn tại từ lâu, không phải đổi lấy
một khả năng chưa ai cần.

**Lỗi mount gặp thật khi dựng.** Mount hai volume riêng biệt lồng vào cùng một path
(`./docker/grafana/provisioning:/etc/grafana/provisioning:ro` và một mount thứ hai
vào `/etc/grafana/provisioning/dashboards/files`) — Docker không tạo được mountpoint
bên trong một bind mount read-only khác:
`mkdirat ... read-only file system`. Sửa bằng cách đưa file dashboard JSON vào ngay
trong cây `docker/grafana/provisioning/dashboards/files/`, để một mount duy nhất phủ
hết, không mount lồng.

**Đo thật, không chỉ tin cấu hình đúng cú pháp.** Gọi 3 request `/ask` thật (401
thiếu key, 200 câu hỏi docs hợp lệ, 403 giả mạo role) qua container `api` đang chạy,
đợi một chu kỳ scrape (15s), rồi xác nhận bằng đúng ba lớp: Prometheus `/api/v1/query`
trả về đúng 3 dòng khớp nhãn `status`/`tool_used` đã gọi; Grafana
`/api/datasources/proxy/uid/prometheus/...` (đi qua đúng đường dashboard sẽ dùng, không
phải gọi thẳng Prometheus) trả `sum(ask_requests_total) = 3`. Không suy luận từ
"container Running" — "Running" không chứng minh scrape có hoạt động, như log
`lastError: 404` ban đầu đã cho thấy (image `api` cũ chưa build lại code mới nhất).

**Giới hạn đã biết.** `GRAFANA_ADMIN_PASSWORD` mặc định `admin` trong `.env.example`
— đổi trước khi để container này chạm mạng ngoài `127.0.0.1`. Dashboard hiện chỉ có
một trang tổng quan (`ask-overview`), chưa có alerting rule nào — mở khi có nhu cầu
đo được (ví dụ ngưỡng `503` liên tục).

## ADR-022 — Corpus và `eval/dev.jsonl` chuyển sang tiếng Việt có dấu, đo lại baseline

**Ngày:** 15/09/2026 · **Trạng thái:** accepted

**Bối cảnh.** Corpus (`data/documents.csv`, `data/documents_dirty.csv`) và
`eval/dev.jsonl` được viết không dấu từ đầu dự án. Lý do ban đầu không hề được ghi
lại thành ADR nào — không có quyết định nào nói "bỏ dấu để tiết kiệm token". Đây là
một khoảng trống tài liệu, không phải một đánh đổi đã cân nhắc. Trong khi đó, tiếng
Việt có dấu là dạng phổ biến trong dữ liệu huấn luyện của các BPE tokenizer, nên
thường được token hoá gọn hơn tiếng Việt không dấu (không dấu là biến thể hiếm hơn,
dễ bị tách vụn). Giữ bản không dấu vừa sai chính tả vừa không đúng ngay cả với lý do
"tiết kiệm token" nếu ai đó dùng nó để biện minh ngược sau này.

**Quyết định.** Viết lại toàn bộ `data/documents.csv` (16 chunk) và
`data/documents_dirty.csv` (8 dòng vi phạm hợp đồng dữ liệu có chủ đích, giữ nguyên
từng lỗi) sang tiếng Việt có dấu chuẩn, không đổi `doc_id`/`chunk_index`/
`department`/`access_level`/các mốc thời gian. `eval/dev.jsonl` viết lại đồng bộ cả
`question` lẫn `expected_answer_keywords` (25 câu, khớp cách hành văn mới của
corpus). Hậu tố `F0x_seen_at_d2` đổi thành `F0x_seen_early` nhân dịp này (nhất quán
với việc dự án đã bỏ nhãn ngày ở khắp nơi khác — xem ADR-010); ba nơi tham chiếu tới
hậu tố cũ (`AGENTS.md`, ADR-010 ở trên, `docs/report.md`) được cập nhật theo.
`eval/final.jsonl` (đã niêm phong, đã có kết quả) **không bị đụng vào** — xem
"Không làm gì" bên dưới.

**Một lỗi thật phát hiện trước khi chạy, không phải sau khi đo sai.** Trước khi
ingest lại, đọc lại `scripts/ingest.py` phát hiện `ON CONFLICT (doc_id,
chunk_index) DO UPDATE SET` không hề đụng tới cột `embedding` — nghĩa là re-ingest
với `chunk_text` mới sẽ để lại vector embedding của văn bản CŨ gắn với chunk có nội
dung MỚI, làm retrieval xếp hạng theo nghĩa cũ trong khi trích dẫn trả về là câu
chữ mới. Vá bằng `CASE WHEN doc_chunks.chunk_text IS DISTINCT FROM
EXCLUDED.chunk_text THEN NULL ELSE doc_chunks.embedding END` — chỉ reset embedding
khi văn bản thật sự đổi, so bằng giá trị **đã có trong bảng**, không phải giá trị
mới, để lần re-ingest không có gì thay đổi thì không phải embed lại tốn kém. Có
test tích hợp riêng (`test_reingest_invalidates_embedding_only_when_text_actually_changes`,
`tests/test_sql_integration.py`) khoá lại hành vi này bằng một `doc_id` giả lập,
không đụng corpus thật.

**Quy trình đo lại.** Re-ingest (`uv run python -m scripts.ingest`) → xác nhận cả
16 chunk có `embedding IS NULL` ngay sau đó (chứng minh patch ở trên hoạt động) →
re-embed (`uv run python -m scripts.backfill_embeddings`) → chạy lại
`documents_dirty.csv` để xác nhận hành vi kiểm dịch không đổi (8 dòng vào, 0 được
nhận, 8 bị cách ly — khớp thiết kế gốc). File bằng chứng cũ
(`evidence/eval_results_dev.jsonl`, 25 dòng từ lần đo không dấu) được **đổi tên**
thành `evidence/eval_results_dev_pre_diacritics.jsonl` (và tương ứng cho file
summary) trước khi chạy lại — không xoá, và không để nguyên tên cũ, vì
`scripts/run_eval.py` bỏ qua `question_id` đã có trong file kết quả để hỗ trợ chạy
lại giữa chừng; giữ nguyên tên sẽ khiến 20/25 câu (ID không đổi, nội dung đã đổi
hoàn toàn) bị bỏ qua và tái sử dụng nhầm điểm số của bản không dấu.

**Kết quả đo lại (15/09/2026, `uv run python -m scripts.run_eval`): giống hệt bản
gốc về số liệu.** 25/25 câu chạy xong, recall@3/@5/@10 = 18/18 (100%), MRR = 1,000,
`correct` 18, `access_correct` 5, `no_knowledge_correct` 2, mọi nhóm lỗi = 0. Điều
này xác nhận việc thêm dấu không phải là thay đổi hành vi hệ thống — nó chỉ sửa một
lỗi chính tả trong dữ liệu. Ví dụ cosine distance trong `docs/report.md` ("release
thất bại" xếp hạng 1) được đo lại thật bằng `src/retrieval.retrieve()` trên corpus
mới: 0,208 (bản không dấu) → 0,2033 (bản có dấu) — chênh lệch nhỏ, thứ hạng không
đổi.

**Không làm gì: `eval/final.jsonl`.** Đây là tập held-out đã niêm phong, đã chạy
qua HTTP thật và đã có kết quả trong báo cáo cuối (ADR-019/ADR-020). Sửa nội dung
của nó — kể cả chỉ để thêm dấu — sẽ làm mất tính "chưa từng thấy" nếu có ai dùng nó
lại, và phá vỡ đúng nguyên tắc mà ADR-019 dựng lên. Quyết định (đã thống nhất với
người dùng): giữ nguyên `eval/final.jsonl` và kết quả cũ làm hồ sơ lịch sử, viết
một tập held-out **mới gồm 12 câu**, có dấu, tránh trùng lặp với cả `eval/dev.jsonl`
mới lẫn `eval/final.jsonl` cũ, chạy một lần qua HTTP thật — xem ADR kế tiếp khi tập
đó được viết.

**`sql/02_seed.sql` và system prompt cũng được chuyển sang có dấu, trong cùng đợt
này.** Tên nhân viên/phòng ban trong seed data (ví dụ "Nguyen Van A" → "Nguyễn Văn
A", "Khoi Kinh doanh" → "Khối Kinh doanh") và `SYSTEM_INSTRUCTION` trong
`src/generation.py`/`src/agent/router.py` không có test nào hardcode nội dung cũ
(đã kiểm bằng grep trước khi sửa), nên rủi ro thấp; đổi luôn cho nhất quán thay vì
để dành một lượt dọn dẹp riêng.

## ADR-023 — Chi phí token quy đổi VNĐ/USD: một khoảng, không phải một con số

**Ngày:** báo cáo cuối (bổ sung) · **Trạng thái:** accepted

**Bối cảnh.** ADR-018 ghi rõ đây là việc chưa đo được tại thời điểm đó: "báo cáo
cuối quy đổi VNĐ sẽ trích dẫn trang giá công khai kèm ngày truy cập thay vì bịa một
con số cố định có thể đã lỗi thời." `docs/report.md` (mục "Token cost") đã có số đo
thật — 6.189 token cộng dồn trên 10/12 câu held-out hoàn thành (2 câu còn lại lỗi hạ
tầng, không có `total_tokens`) — nhưng chưa quy đổi ra tiền.

**Vấn đề thật, không phải chi tiết vặt: `audit_log.total_tokens` chỉ lưu tổng.**
Response Gemini trả về `promptTokenCount` (input) và `candidatesTokenCount`
(output) tách riêng, và hai loại được tính giá khác nhau — nhưng
`generation.py::_call_gemini`/`router.py::_call_gemini` chỉ từng đọc
`usageMetadata.totalTokenCount` (xem ADR-018), nên không còn cách nào tách lại sau
khi đã ghi. Ước lượng tỉ lệ input/output là đoán, đúng loại lỗi `AGENTS.md` mục 4
cấm.

**Quyết định: báo cáo một khoảng, cận dưới = toàn bộ token tính theo đơn giá input,
cận trên = toàn bộ token tính theo đơn giá output.** Đây là khoảng đúng về mặt toán
học (chi phí thật chắc chắn nằm trong đó), khác với việc bịa một tỉ lệ input/output
"hợp lý" rồi báo một con số điểm có vẻ chính xác nhưng thực ra là đoán.

**Số liệu, tra cứu 15/09/2026:**
- Đơn giá `gemini-3.1-flash-lite`, tier chuẩn, từ trang giá công khai
  (ai.google.dev/gemini-api/docs/pricing): $0,25 / 1M token input (text), $1,50 /
  1M token output.
- Tỷ giá (xe.com, 09:32 UTC): 1 USD = 25.981,41 VNĐ.
- Kết quả: 6.189 token của lần chạy held-out = $0,0015–$0,0093 (~40–241 VNĐ). Quy
  ra 1.000 request ở mức trung bình của lần chạy này (618,9 token/request):
  $0,155–$0,928 (~4.020–24.120 VNĐ).

**Không làm gì: không chạy lại tập held-out để lấy số chính xác hơn.** Đây là toán
tiền tệ trên số đã đo, không phải một phép đo mới — chạy lại `eval/final.jsonl` chỉ
để tách input/output sẽ vi phạm đúng quy tắc ADR-019 đã dựng lên (tập held-out chỉ
chạy một lần). Muốn có con số chính xác thay vì khoảng, cần một ADR riêng thêm cột
`prompt_tokens`/`candidates_tokens` vào `audit_log` rồi đo trên một lần chạy MỚI
(một eval set khác, không phải tập đã niêm phong) — ghi nhận là khoảng trống đã
biết, không phải điểm mù.

## ADR-024 — Held-out vòng 2: tập 12 câu mới, một lỗ hổng retry thật phát hiện giữa lúc chạy

**Ngày:** báo cáo cuối, vòng 2 · **Trạng thái:** accepted

**Bối cảnh.** ADR-022 chuyển corpus và `eval/dev.jsonl` sang có dấu, và người dùng
yêu cầu rõ: giữ nguyên `eval/final.jsonl` (12 câu, đã niêm phong, đã chạy, đã có kết
quả trong báo cáo) làm hồ sơ lịch sử, viết một tập held-out **mới hoàn toàn** để
tránh leakage, rồi chạy một lần và cập nhật báo cáo. ADR này ghi lại toàn bộ quá
trình đó.

**Lưu trữ tập cũ, không sửa.** `eval/final.jsonl`,
`evidence/eval_results_final_agent.jsonl`, `evidence/eval_summary_final_agent.json`
được đổi tên thành hậu tố `_v1_pre_diacritics` (không xoá), trước khi viết tập mới
vào đúng tên file gốc — cùng cơ chế đã dùng ở ADR-022 cho `evidence/eval_results_dev.jsonl`.
`scripts/run_held_out_eval.py` đã có sẵn đúng cờ cho tình huống này
(`--force`, với comment từ trước "sau khi eval/final.jsonl được viết lại từ đầu") —
không cần sửa script để hỗ trợ vòng 2.

**12 câu mới (H13–H24), kiểm tra chéo với cả `eval/dev.jsonl` (có dấu, 25 câu) và
tập held-out vòng 1 trước khi viết**, nhắm vào các góc chưa từng đo: SQL truy vấn
nhiều tháng liên tiếp (H13, trước giờ mọi câu SQL chỉ hỏi đúng một tháng), SQL bị
chặn ở cấp **manager** (H14 — vòng 1 chỉ thử employee bị chặn), doanh thu phòng hr
truy vấn trực tiếp (H15/H16 — vòng 1 chỉ thấy hr qua đường executive liên phòng
ban), chặn quyền tách riêng chiều "level" khỏi chiều "department" bằng cách chặn một
manager khỏi tài liệu executive-only **trong chính phòng ban của họ** (H18), một chủ
đề hoàn toàn vắng mặt mới (bảo hiểm y tế, H19), câu hỏi kết hợp sql+docs ở cấp
employee thay vì manager (H20/H21 — vòng 1 chỉ thử ở manager), paraphrase mạnh cho
hai sự kiện chưa từng bị diễn giải lại (H22/H23), và một câu hỏi hệ thống **không
thể** trả lời đúng về mặt kiến trúc — tổng doanh thu bốn phòng ban cùng lúc, vì
`SqlArgs.department` là một `Literal` đơn, không phải danh sách (H24) — hành vi đúng
là từ chối, không đoán bằng số của một phòng ban.

**8 nhân viên eval mới, có tracking trong repo — sửa luôn một khoảng trống từ vòng
1.** `sql/07_eval_held_out_employees.sql` (emp_109–emp_116, idempotent, cùng mẫu
`ON CONFLICT` với `02_seed.sql`). Vòng 1 tạo `emp_101`–`emp_108` bằng lệnh ad hoc,
không có trong repo — không tái lập được từ mã nguồn. Không thể tái sử dụng
`emp_101`–`emp_108`: key thật của họ chỉ hiển thị một lần lúc cấp, đã mất; và
`scripts/issue_api_keys.py` cố tình **không bao giờ cấp lại** key cho nhân viên đã
có hash (tránh vô hiệu hoá key đang dùng của người khác) — đây chính là lý do cần
nhân viên mới, không phải một lựa chọn tuỳ ý.

**Một lỗ hổng độ tin cậy thật, phát hiện và vá GIỮA LÚC chạy — không phải sửa vì
điểm đúng/sai.** Lần chạy đầu tiên: 0/12, toàn bộ 12 câu đều nhận `503 "high
demand"` thật từ Gemini (xác nhận trực tiếp bằng curl, không phải lỗi ở tầng retry
của dự án). Soi kỹ hơn lộ ra quy luật: mọi câu SQL-only đều qua, mọi câu chạm tới
docs retrieval đều fail. Nguyên nhân: `src/embeddings.py` — hàm DUY NHẤT dùng để
embed cả chunk lúc ingest lẫn câu hỏi lúc truy vấn — **chưa từng có logic retry
nào**, khác hẳn `generation.py` và `router.py` đã có `_NETWORK_RETRY_ATTEMPTS` kèm
backoff/jitter từ ADR-016. Một lần 503 thoáng qua từ `gemini-embedding-001` giết
chết ngay request, và `agent/loop.py`'s `_retry()` ở tầng tool chỉ bắt lỗi mạng
(`ConnectError`/`TimeoutException`), không bắt `HTTPStatusError`, nên cũng không có
cơ hội thứ hai. Vá bằng cách đưa `embed()` về đúng cấu trúc retry/backoff/jitter của
`_call_gemini` ở hai module kia, kèm test hồi quy riêng
(`tests/test_embeddings.py`).

**Vì sao việc vá giữa chừng KHÔNG làm hỏng tính toàn vẹn của tập held-out.** Lúc phát
hiện, chưa có câu nào chạm docs từng ra được một kết quả có chấm điểm — bằng chứng
duy nhất lúc đó là 5 câu SQL-only thành công (H13–H17) đối lập với một bức tường
503 ở mọi câu còn lại: đây là tín hiệu hạ tầng, không phải tín hiệu đúng/sai. Không
gì trong router, retrieval, RBAC, hay nội dung generation bị đụng tới. Cùng loại
tình huống với lỗi harness của vòng 1 (ADR trước: vá giữa chừng, chạy lại từ đầu) —
một lỗ hổng trong đường ống đang chặn cả việc chạy được, phát hiện mà chưa hề biết
câu trả lời đúng hay sai. Điều **sẽ không được phép**, và không xảy ra ở đây: sửa
prompt router, một luật RBAC, hay một bước kiểm grounding **vì** một câu bị trả lời
sai.

**Kết quả: 11/12 đúng, 1 sai thật, 0 lỗi hạ tầng ở trạng thái cuối cùng.** Chi tiết
đầy đủ, bảng kết quả, latency, chi phí token quy đổi VNĐ/USD: `docs/report.md` mục
"Final report, round 2". Điểm đáng chú ý nhất: **H21 lặp lại đúng lỗi H07 của vòng
1** (router bỏ một tool khỏi câu hỏi kết hợp) — dù ADR-020 đã siết prompt router và
đo được 6/6 đúng trên một probe riêng sau đó. H21 là câu kết hợp độc lập thứ 7,
chưa từng nằm trong probe hay bất kỳ lần tinh chỉnh nào, và router vẫn bỏ `docs`.
Không kết luận rằng bản vá ADR-020 vô dụng (6/6 là cải thiện thật, đo được) — chỉ
kết luận 6 mẫu chưa đủ để coi khoảng trống đã đóng. **Để nguyên không vá**, đúng quy
tắc: sửa router prompt *vì* H21 sẽ là tinh chỉnh dựa trên kết quả held-out, đúng
điều luật này cấm. Cần một probe lớn hơn, độc lập, không phải một lần chỉnh nhanh
được xác nhận bằng chính tập đã lộ ra vấn đề.

## ADR-025 — Thêm Alembic làm công cụ migration, không thay thế `sql/*.sql`

**Ngày:** sau báo cáo cuối · **Trạng thái:** accepted

**Bối cảnh.** Từ trước tới giờ, mọi thay đổi schema đi qua các file `sql/*.sql`
đánh số thứ tự (`00_extensions`, `01_schema`, `06_auth`, ...), áp thủ công bằng
`psql -f`. Cách này đủ dùng khi dự án chỉ có một môi trường (`db` container local)
và một người vận hành, nhưng không trả lời được hai câu hỏi cơ bản của bất kỳ hệ
thống nhiều môi trường nào: "database này đang ở đúng phiên bản schema nào?" và "áp
đúng-và-chỉ-đúng những thay đổi còn thiếu, theo thứ tự đúng, như thế nào?" —
`01_schema.sql` tự nó bắt đầu bằng `DROP TABLE IF EXISTS ...`, nghĩa là chạy lại
trên một DB đã có dữ liệu sẽ XOÁ SẠCH dữ liệu đó. Đây không phải lỗi thiết kế cho
mục đích ban đầu (dựng nhanh một DB dev sạch), nhưng là một khoảng trống thật nếu
sau này có nhiều môi trường (staging/prod) hay nhiều người cùng sửa schema.

**Quyết định.** Thêm Alembic (`alembic>=1.13.0`, `sqlalchemy>=2.0.0` — chỉ dùng
SQLAlchemy làm engine kết nối, không dùng ORM/ `declarative_base`/`Table` object
nào). `target_metadata = None` trong `alembic/env.py` — không có autogenerate, vì
không có model nào để diff theo; mọi migration viết tay bằng `op.execute()` chứa
raw SQL, cùng triết lý với `src/db.py`: "đọc được, giải thích được, đọc được query
plan", áp dụng luôn cho migration.

**`alembic/env.py` đọc connection string từ `src.config.Settings`, không lặp lại
cấu hình trong `alembic.ini`.** Hai nơi cấu hình DB là cách lệch cấu hình xảy ra —
đúng bài học đã áp dụng cho mọi phần khác của dự án (`docs/decisions.md` nhiều ADR
lặp lại nguyên tắc "một nguồn sự thật"). Vướng một lỗi thật lúc nối dây: `database_url`
chứa `%20`/`%3D` (URL-encoded), còn `configparser` (nền của `alembic.ini`) dùng `%`
cho cú pháp interpolation riêng của nó — ghi thẳng chuỗi URL vào
`config.set_main_option()` báo `ValueError: invalid interpolation syntax`. Vá bằng
cách nhân đôi mọi `%` thành `%%` trước khi ghi (đúng cách configparser escape ký tự
đặc biệt của chính nó).

**Migration `9064d9299cfa` (baseline) chụp lại đúng schema đang chạy, không bắt đầu
từ rỗng.** Dự án đã chạy production-shaped từ lâu trước khi có Alembic — "baseline"
ở đây nghĩa là "mô tả lại cái đã có" (00_extensions + 01_schema + 06_auth, chép
nguyên văn), không phải điểm khởi đầu mới. **Cố ý chép tay SQL vào file migration
thay vì đọc lại `sql/*.sql` lúc chạy**: một migration phải là ảnh chụp bất biến —
`sql/01_schema.sql` sẽ còn đổi theo các ADR sau này, và nếu migration đọc lại file
đó mỗi lần chạy, lịch sử migrate sẽ không còn tái lập đúng được (chạy `upgrade` ở
một thời điểm sau sẽ áp một schema khác với schema mà migration đó *nói* nó áp,
tuỳ vào `sql/01_schema.sql` lúc đó đang có nội dung gì). Trùng lặp giữa
`sql/01_schema.sql` và migration là chấp nhận được — đây là chi phí đứng đắn của
việc có lịch sử migration đúng nghĩa, không phải sơ suất.

**Đo thật trước khi coi là xong, không tin migration chạy không lỗi là đủ.** Tạo
một database tạm (`CREATE DATABASE alembic_test`) trong cùng container `db`, chạy
`alembic upgrade head` lên đó, rồi `pg_dump --schema-only` cả hai database
(`alembic_test` và `enterprise_ai` thật) và `diff` — giống hệt nhau ngoại trừ token
bảo mật ngẫu nhiên của chính `pg_dump`. Chạy tiếp `alembic downgrade base` trên
`alembic_test`, xác nhận cả 7 bảng bị xoá sạch, chỉ còn `alembic_version`. Sau khi
xác nhận, xoá `alembic_test`, rồi `alembic stamp head` trên `enterprise_ai` thật
(ghi nhận "đang ở revision này", KHÔNG chạy lại DDL — schema đã có sẵn, chạy lại
`CREATE TABLE` sẽ lỗi "already exists"). Xác nhận dữ liệu thật không suy chuyển:
`doc_chunks` vẫn 16 dòng, `employees` vẫn đủ (8 seed gốc + 16 eval hai vòng
held-out) sau `stamp`.

**Không thay thế `sql/00_extensions.sql`/`01_schema.sql`/`02_seed.sql`/`06_auth.sql`.**
`01_schema.sql`'s `DROP TABLE IF EXISTS` đầu file vẫn là cách nhanh nhất dựng một DB
dev sạch từ đầu (một lệnh, không cần biết lịch sử migration). Alembic quản lý các
thay đổi schema TIẾP THEO trên một DB đã tồn tại — từ migration kế tiếp trở đi, mọi
`ALTER TABLE`/`CREATE TABLE` mới nên đi qua `alembic revision` thay vì thêm một file
`sql/0N_*.sql` đánh số mới, để có lịch sử version thật thay vì chỉ có thứ tự file.

## ADR-026 — Đo lại jitter dưới tải đồng thời thật: không thấy cải thiện đo được

**Ngày:** sau báo cáo cuối · **Trạng thái:** accepted, đo xong một khoảng trống đã ghi từ ADR-016

**Bối cảnh.** ADR-016 thêm `random.uniform(0, 0.5)` vào backoff của
`generation.py`/`router.py`/`ocr.py` (sau này cả `embeddings.py`, ADR-024) sau khi
quan sát 2/3 request `/ask` đồng thời nhận `503` — nguyên nhân xác định: cả ba
request retry theo đúng cùng lịch (1s, 2s, 4s), va lại giới hạn tốc độ của Gemini ở
cùng thời điểm. ADR-016 tự ghi rõ đây là khoảng trống: "chưa đo lại tỷ lệ 503
trước/sau ở đúng kịch bản 3-request-đồng-thời". ADR này đo đúng khoảng trống đó.

**Phương pháp.** `scripts/probe_retry_jitter_load.py`: gọi thẳng `run_agent()`
trong tiến trình bằng `ThreadPoolExecutor` (3 luồng thật, không phải giả lập) —
phạm vi đo là cơ chế retry/backoff/jitter của các hàm gọi Gemini, không phải toàn
bộ đường HTTP/xác thực. 8 lượt × 3 request đồng thời cho mỗi điều kiện (có/không
jitter), bật/tắt bằng cách ghi trực tiếp vào biến module-level
`_NETWORK_RETRY_JITTER_S` giữa hai điều kiện. **Cả hai điều kiện chạy nối tiếp
nhau trong cùng một lần gọi script** — mức độ nghẽn thật của Gemini biến đổi theo
thời gian (thấy rõ suốt phiên đo held-out v2, ADR-024), nên so sánh "có jitter lúc
này" với "không jitter lúc khác xa" sẽ không công bằng.

**Kết quả: không thấy cải thiện đo được — nếu có khác biệt, còn hơi tệ hơn, nhưng
trong biên độ nhiễu.**

| Điều kiện | Tỷ lệ thất bại |
|---|---:|
| Có jitter (như đang triển khai, ADR-016) | 23/24 (95,8%) |
| Không jitter (tắt bằng monkeypatch) | 20/24 (83,3%) |

Cả hai tỷ lệ đều bị chi phối bởi mức nghẽn thật cực cao của Gemini trong phiên đo
này (cùng hiện tượng đã thấy suốt ADR-024) — từng lượt riêng lẻ dao động từ 0/3 tới
3/3 thất bại ở CẢ HAI điều kiện, nhiễu nội tại lớn hơn nhiều so với chênh lệch 3
lần thất bại giữa hai điều kiện.

**Không kết luận rằng bản vá ADR-016 sai.** Jitter giải quyết đúng một cơ chế cụ
thể: nhiều client retry TRÙNG THỜI ĐIỂM. Đó là một cơ chế thật, khác với nghẽn KÉO
DÀI vượt quá toàn bộ ngân sách retry — ở mức nghẽn hôm nay, ngân sách retry (3 lần
thử, backoff tối đa ≈ 7s + jitter tối đa 1,5s ≈ 8,5s tổng) liên tục ngắn hơn hẳn
thời gian một đợt nghẽn thật (kéo dài hàng chục giây tới vài phút, quan sát được
suốt phiên held-out v2) — jitter không còn gì để giúp một khi MỌI lần thử trong
ngân sách đều rơi vào cùng một đợt nghẽn.

**Để nguyên không vá thêm — đây là một khoảng trống KHÁC, không phải khoảng trống
ADR-016 đã đóng.** Tăng số lần retry hay đổi chiến lược backoff (thích ứng theo độ
dài đợt nghẽn thay vì cố định) sẽ giải quyết đúng vấn đề "ngân sách retry ngắn hơn
đợt nghẽn" — nhưng đó là một quyết định riêng, cần đo trước khi làm (ví dụ: retry
nhiều hơn tốn tiền/thời gian hơn cho MỌI request, kể cả lúc không nghẽn), không
phải hệ quả tự động của phát hiện này. Ghi nhận là khoảng trống đã biết.

**Giới hạn của phép đo này.** Đo trong tiến trình (bỏ qua tầng HTTP/xác thực thật),
và dưới mức nghẽn BẤT THƯỜNG cao của đúng ngày đo — không chắc đại diện cho điều
kiện vận hành thông thường. `evidence/retry_jitter_load_probe.json` giữ toàn bộ dữ
liệu thô cho ai muốn phân tích lại.

## ADR-027 — Router "bỏ sót tool" (H07, H21): đo lại trên mẫu lớn hơn, không tái hiện được — không vá

**Ngày:** sau báo cáo cuối · **Trạng thái:** accepted, đo xong không tìm thấy tín hiệu để sửa

**Bối cảnh.** ADR-024 ghi nhận H21 (held-out vòng 2) lặp lại đúng lỗi H07 (held-out
vòng 1) — router bỏ `docs` khỏi câu hỏi cần cả hai tool — dù ADR-020 đã gia cố
prompt và đo 6/6 đúng trên một probe riêng. Kết luận khi đó: "6 mẫu chưa đủ để coi
khoảng trống đã đóng", để nguyên không vá, và ghi rõ hướng đi đúng là "cần một
probe lớn hơn, độc lập" trước khi sửa bất cứ gì.

**Phương pháp.** `scripts/probe_router_combined_tools_v2.py` — 18 câu hỏi kết hợp
sql+docs MỚI (không phải 6 như trước), bao phủ cả 4 phòng ban, đổi thứ tự
sql-trước/docs-trước, một số câu cố tình mô phỏng rất sát cấu trúc H21 (doanh thu +
một con số phần trăm chính sách trong cùng câu). Chỉ gọi `route()` trực tiếp —
không qua RBAC/thực thi, vì đây là bài đo phân loại tool, không phải đo đúng/sai
nội dung. Không trùng/gần giống `eval/dev.jsonl`, `eval/final.jsonl` (cả hai vòng),
hay 6 câu của probe gốc.

**Một lỗi thật gặp khi đo: script gốc không chịu được lỗi hạ tầng giữa chừng.**
Đúng bài học đã học nhiều lần trong dự án này (harness held-out vòng 1, run_eval.py)
— một `HTTPStatusError` ở câu 1/18 làm chết cả lượt đo. Vá bằng cách bắt lỗi từng
câu, ghi `infra_error`, tiếp tục câu tiếp theo — cùng mẫu `run_eval.py`/
`run_held_out_eval.py` đã dùng. Thêm nghỉ 1s giữa các câu, cùng lý do ADR-026.

**Kết quả: 18/18 đúng, 0 lỗi phân loại — kể cả các câu mô phỏng sát H21.** Lần chạy
đầu 13/18 (5 lỗi hạ tầng, 0 lỗi phân loại trong 13 câu chạy được); chạy lại lấp đủ
18/18, tất cả đúng. `evidence/router_combined_tools_v2_pre.json` giữ toàn bộ dữ
liệu thô.

**Không vá — không có tín hiệu lỗi nào để nhắm vào.** Sửa prompt lúc này sẽ là đoán
mò, đúng loại lỗi `AGENTS.md` mục 4 cấm ("đưa số chưa đo vào README/CV", cùng tinh
thần với "sửa mà không có bằng chứng"). Với ~20 câu hỏi kết hợp đã từng chạy qua hệ
thống này tính từ đầu dự án (6 câu probe gốc + 2 câu held-out H07/H21 + 18 câu probe
này), thấy 2 lần bỏ sót tool — tỷ lệ ~5-10% — hoàn toàn phù hợp với sai số ngẫu
nhiên bình thường của một LLM (`temperature=0.0` không đảm bảo tất định tuyệt đối),
không phải bằng chứng về một lỗ hổng hệ thống trong cách viết prompt. Đây là kết
luận **tốt hơn** giả định ban đầu: tỷ lệ lỗi thật thấp hơn nhiều so với ấn tượng "2
lần liên tiếp" tạo ra.

**Quyết định (đã thống nhất với người dùng): ghi nhận là nhiễu thống kê, không vá.**
Nếu muốn giảm tỷ lệ này xuống gần 0% trong tương lai, hướng đúng — khi có bằng
chứng cụ thể hơn — là đổi `ToolPlan` sang hai trường boolean độc lập
(`needs_sql`/`needs_docs`) thay vì một `list[Literal]`, ép Gemini phải trả lời
từng điều kiện tách biệt ở tầng schema thay vì tin vào hướng dẫn ngôn ngữ tự nhiên
— nhưng đây là một thay đổi để dành, không làm trong ADR này vì chưa có lỗi tái
hiện được để xác nhận nó thật sự cần thiết.

## ADR-028 — Thêm JWT song song API key, chia 3 bước để mỗi commit an toàn riêng

**Ngày:** sau báo cáo cuối · **Trạng thái:** accepted, đủ cả 3 bước — API key vẫn
hoạt động song song JWT trong suốt, không bước nào làm gián đoạn

**Bối cảnh.** ADR-015 tự ghi rõ điều kiện nâng cấp: "Nâng cấp lên JWT/OAuth2 khi dự
án cần thu hồi quyền tức thời hoặc tích hợp một hệ thống định danh doanh nghiệp
thật." API key hôm nay là xác thực "sở hữu một bí mật" — không có hạn dùng, thu hồi
chỉ bằng cách xoá `api_key_hash` thủ công. Thêm JWT chia làm 3 bước tách biệt, mỗi
bước một commit riêng, để không có bước nào làm API key hiện tại ngừng hoạt động
giữa chừng: (1) tiện ích cấp/xác minh — đúng ADR này; (2) endpoint `/auth/token`
phát hành token, API key vẫn chạy song song; (3) `authenticate()` chấp nhận cả JWT
lẫn API key.

**Quyết định, bước 1/3: `src/jwt_auth.py` — `issue_token()`/`verify_token()`, chưa
route nào gọi tới.** HS256 (đối xứng), không RS256 — chỉ một service vừa cấp vừa
xác minh, bất đối xứng chỉ có ích khi việc ký và xác minh tách rời giữa nhiều bên,
thêm vào bây giờ là độ phức tạp chưa cần. Setting mới trong `Settings`:
`jwt_secret_key` (rỗng mặc định, giống `llm_api_key` — thiếu secret phải lỗi rõ
ràng lúc dùng, không âm thầm ký bằng giá trị giả đoán trước được), `jwt_algorithm`
(mặc định `HS256`), `jwt_expiry_minutes` (mặc định 60).

**Phòng vệ "algorithm confusion" — luôn truyền `algorithms=[...]` tường minh khi
decode.** Đây là lớp tấn công JWT có thật và đã biết: kẻ tấn công tự ký một token
bằng thuật toán khác thuật toán server mong đợi (ví dụ `none`, hoặc đổi
RS256↔HS256 nếu server không ép rõ), qua được bước xác minh nếu thư viện tự đoán
thuật toán từ header của chính token. `verify_token()` luôn truyền
`algorithms=[settings.jwt_algorithm]`, không bao giờ để PyJWT tự suy luận. Test
riêng khoá lại: token tự ký bằng HS384 (khác HS256 đã cấu hình) bị từ chối dù chữ
ký hợp lệ với secret đúng.

**Claims tối thiểu, đánh đổi có chủ ý.** `sub` (employee_id, đúng tên chuẩn JWT
cho "subject"), `role`/`department` để RBAC đọc thẳng từ token — không tra DB mỗi
request như API key. Đánh đổi: đổi role/department của một nhân viên sau khi token
đã phát hành sẽ không phản ánh cho tới khi token đó hết hạn (tối đa
`jwt_expiry_minutes`). Chấp nhận được ở quy mô hiện tại — nếu cần phản ánh tức
thời, cần một cơ chế thu hồi riêng (denylist token, không nằm trong phạm vi bước
này).

**Lỗi nào cũng gộp thành `AuthenticationError`** (hết hạn, sai chữ ký, thiếu
claim, token hỏng cú pháp) — cùng loại lỗi `authenticate()` (API key) đã trả ra
hôm nay, để bước 3/3 xử lý thống nhất bất kể xác thực bằng phương thức nào, không
phải viết hai nhánh lỗi khác nhau ở tầng gọi.

**Test (`tests/test_jwt_auth.py`, 8 ca): round-trip đúng, chữ ký giả bị từ chối,
hết hạn bị từ chối, ký sai secret bị từ chối, algorithm confusion bị từ chối,
thiếu claim bị từ chối, thiếu secret cấu hình báo lỗi rõ ràng ở cả issue lẫn
verify.** 183 test không-integration vẫn xanh sau khi thêm.

**Bước 2/3: `POST /auth/token` — đổi API key lấy JWT, `/ask` không đổi gì.** Endpoint
mới nhận `Authorization: Bearer <api_key>`, xác thực bằng đúng `authenticate()` đã
có (không thêm cơ chế xác thực thứ hai — hệ thống này không có username/password,
JWT chỉ là một dạng khác của cùng danh tính API key đã chứng minh), rồi ký token
bằng `issue_token()` từ bước 1/3. Trả về `TokenResponse`
(`access_token`/`token_type`/`expires_in`, đặt tên theo đúng quy ước OAuth2 RFC
6749 §5.1 dù đây không phải OAuth2 đầy đủ — quy ước quen thuộc, không bịa tên field
riêng). `/ask` không sửa một dòng nào ở bước này — API key vẫn là đường xác thực
duy nhất cho tới bước 3/3.

**Test (`tests/test_api.py`, 3 ca mới): 200 kèm token hợp lệ khi API key đúng, 401
khi thiếu header, 401 khi API key sai — cùng mẫu test đã có cho `/ask`.** Một chi
tiết kỹ thuật đáng ghi: `src/api.py` đọc `Settings` MỘT LẦN ở mức module
(`settings = get_settings()` lúc import), nên test không so `expires_in` với một
giá trị `Settings` đọc lại sau đó (`get_settings()` gọi lại sẽ tạo instance MỚI,
không phản ánh vào biến module đã gán) — chỉ kiểm `expires_in` là số dương, tránh
một assertion trông có vẻ đúng nhưng thực ra so hai nguồn cấu hình khác nhau.

**Một lỗi thật gặp khi đo qua container thật, không phải chỉ tin test mock.**
`compose.yaml`'s service `api` liệt kê tường minh từng biến môi trường truyền vào
container (`POSTGRES_*`, `LLM_*`) — không có `.env` nào tự động "chảy" vào bên
trong, kể cả khi biến đó có sẵn trên host. Thêm `JWT_SECRET_KEY`/`.env` ở host
không đủ: gọi `/auth/token` qua container thật ban đầu trả `Internal Server Error`
(500), log container cho thấy đúng `RuntimeError: JWT_SECRET_KEY rỗng`. Vá bằng
cách thêm ba dòng `JWT_SECRET_KEY`/`JWT_ALGORITHM`/`JWT_EXPIRY_MINUTES` vào
`environment:` của service `api` trong `compose.yaml`, đúng mẫu các biến khác đã
có. Xác nhận lại bằng request thật (không phải test mock): `curl -X POST
/auth/token` trả token, decode payload xác nhận đúng
`sub`/`role`/`department`/`exp-iat=3600s`.

**Bước 3/3: `authenticate()` chấp nhận cả API key lẫn JWT, `/ask` không đổi route
nào.** `src/auth.py::authenticate()` giờ phân biệt hai kiểu Bearer token bằng
HÌNH DẠNG trước khi thử xác minh: một JWT luôn là đúng ba đoạn base64url cách nhau
bởi hai dấu `.`; một API key (`secrets.token_urlsafe(32)`) không bao giờ chứa ký
tự `.` trong bảng chữ cái base64url của nó. `token.count(".") == 2` → đi đường
`jwt_auth.verify_token()`; ngược lại → đi đường tra `employees.api_key_hash` như
cũ. Chọn kiểm hình dạng trước, không thử-cả-hai-rồi-bắt-lỗi: hai đường lỗi khác
nhau ("token JWT hỏng" so với "API key sai") rõ ràng hơn cho người debug, và tránh
tốn một lượt gọi DB hoặc một lượt giải mã JWT không cần thiết mỗi lần.

**Vòng import: tách `AuthenticatedEmployee`/`AuthenticationError` ra
`src/identity.py`.** Bước 1/3 đã để `jwt_auth.py` import hai kiểu này từ
`auth.py`. Bước 3/3 cần `auth.py` import ngược lại `jwt_auth.py` (gọi
`verify_token()`) — hai module import lẫn nhau vỡ ngay lúc import. Giải pháp: một
module trung lập (`src/identity.py`, không phụ thuộc DB/JWT/gì khác) giữ hai kiểu
dữ liệu dùng chung, cả `auth.py` và `jwt_auth.py` cùng import từ đó, không import
lẫn nhau nữa. `auth.py` re-export lại hai tên này (`__all__`) nên
`from src.auth import AuthenticatedEmployee, AuthenticationError` ở mọi nơi khác
(`api.py`, các file test cũ) không cần sửa gì.

**Test mới (`tests/test_auth.py`, 3 ca): một JWT hợp lệ xác thực được và KHÔNG gọi
`fetch_one`** (spy raise nếu bị gọi — chứng minh đường JWT thật sự tách biệt khỏi
đường DB, không phải "thử API key trước, JWT chỉ là fallback tình cờ đúng"),
**token có đúng hình dạng JWT (2 dấu `.`) nhưng nội dung rác bị từ chối rõ ràng**,
và **API key thường (không dấu `.`) vẫn đi đúng đường tra DB cũ**. 189 test
không-integration xanh.

**Đo thật qua container, không chỉ tin test mock.** `curl -X POST /auth/token`
bằng API key thật → nhận JWT → `curl -X POST /ask` bằng chính JWT đó (không kèm
API key nào) → trả lời đúng, có trích dẫn (`HR-001#0`, "12 ngày phép"). Gọi lại
`/ask` bằng API key CŨ ngay sau đó → vẫn `200` — xác nhận cả ba bước không có bước
nào làm API key hiện tại ngừng hoạt động, đúng cam kết đặt ra từ đầu ADR này.

---

## ADR-029 — Giao diện demo tĩnh ở `/ui`, chỉ để quay video/GIF, không phải sản phẩm

**Ngày:** 16/09/2026 · **Trạng thái:** accepted

**Bối cảnh.** Dự án chỉ có API — mọi demo trước giờ là `curl` trong terminal
(`docs/demo_script.md`). Cần một giao diện có thể quay GIF cho README/hồ sơ, nhưng
đây không phải yêu cầu thêm một sản phẩm frontend thật.

**Quyết định.** HTML/CSS/JS thuần (`web/index.html`, `style.css`, `app.js`), không
framework, không build step, không Node/npm — nhất quán với nguyên tắc "không thêm
hạ tầng khi không cần" đã áp dụng xuyên suốt dự án (ADR-002 chọn HTTP thuần thay
SDK, ADR-014 chọn Gemini vision thay OCR engine cục bộ, ADR-025 thêm Alembic chỉ
khi thật sự cần). FastAPI tự phục vụ thư mục này qua
`app.mount("/ui", StaticFiles(directory="web", html=True))`, mount **sau cùng**
và ở tiền tố riêng — không phải `"/"` — để không có route API nào bị che khuất.

**Luồng xác thực trên UI giống hệt luồng thật, không giả lập.** Người dùng dán API
key thật (lấy từ `scripts/issue_api_keys.py`) → trang gọi `POST /auth/token` →
JWT nhận về được **giải mã ở client chỉ để hiển thị** danh tính
(`employee_id`/`role`/`department` đọc thẳng từ payload, base64url decode, không
xác minh chữ ký) — quyết định bảo mật thật vẫn luôn nằm ở server
(`src/jwt_auth.verify_token`), client không bao giờ được tin cho việc đó. Token
giữ trong biến JS, không `localStorage` — mất khi tải lại trang, đúng bản chất
"JWT ngắn hạn".

**Ba câu hỏi mẫu dựng sẵn khớp đúng ba tình huống của `docs/demo_script.md`:**
câu hỏi chính sách (docs), câu hỏi doanh thu đúng phòng ban (sql), câu hỏi doanh
thu **phòng ban khác** phòng ban thật của người đang đăng nhập (RBAC chặn) — nút
"sql-blocked" tính `otherDept` động theo `state.department`, không hard-code
phòng ban cụ thể, nên đúng với bất kỳ tài khoản demo nào đăng nhập.

**Tài khoản demo mới, không đụng key của ai đang dùng.** AGENTS.md liệt rõ:
"Chạy lại `scripts/issue_api_keys.py` rồi ghi đè `api_key_hash` thủ công cho một
nhân viên đã có key" là việc **không bao giờ được làm** — mọi nhân viên seed sẵn
(`emp_001`...`emp_116`, `demo_emp_sales`...) đã có hash, không lấy lại được
plaintext. Thêm một nhân viên MỚI (`demo_ui_frontend`, sales/employee) rồi chạy
`issue_api_keys.py` — script này chỉ cấp key cho hàng có `api_key_hash IS NULL`,
nên không nhân viên nào khác bị ảnh hưởng. Key thật đã cấp một lần, ghi trong
`docs/demo_script_ui.md`, không lặp lại ở đây (đúng mô hình "hiện đúng một lần").

**Đo thật qua HTTP, không chỉ mở trang xem giao diện.** Chạy `uv run uvicorn
src.api:app --port 8011` (cổng phụ, không đụng container `api` đang chạy ở 8010),
gọi đúng bốn bước UI sẽ gọi — `/auth/token`, câu hỏi docs, câu hỏi SQL đúng
phòng ban, câu hỏi SQL sai phòng ban, và `/ask` không kèm token — bằng `curl`
y hệt payload JS gửi. Cả năm đều đúng như thiết kế: JWT cấp được, câu trả lời
docs có trích dẫn thật (`ENG-007#1`), số liệu SQL đúng dữ liệu seed
(`4.200.000.000 VND`), câu hỏi sai phòng ban bị chặn (`abstained=true`,
`tool_used=none`), không token bị `401`.

**Chưa làm, ghi rõ để không quên:**
- Chưa tự tay mở trình duyệt kiểm giao diện — mọi xác nhận ở trên chỉ qua `curl`,
  không phải ảnh chụp màn hình hay video thật. Người dùng cần tự mở
  `http://127.0.0.1:8010/ui/` kiểm trước khi quay.
- Không có test tự động nào cho `web/*.js` — đây là công cụ quay demo, không phải
  đường chạy production; không đưa vào `tests/` theo đúng phạm vi ADR này.
- Ảnh Docker `enterprise-ai-api:local` đang chạy **chưa build lại** — nó không có
  `/ui` cho tới khi rebuild. Muốn quay qua container thật cần
  `docker compose build api && docker compose up -d api`; cách nhẹ hơn là dừng
  riêng container `api` và chạy `uvicorn` trên host ở cổng 8010, không đụng
  `db`/`prometheus`/`grafana` đang chạy.

---

## ADR-030 — Thêm truy vấn so sánh liên phòng ban cho tool SQL; một lỗi psycopg thật bắt được khi chạy qua container

**Ngày:** 16/09/2026 · **Trạng thái:** accepted

**Bối cảnh.** `sql_tool` trước đó chỉ trả lời được đúng một dạng câu hỏi: doanh thu
của MỘT phòng ban theo khoảng thời gian. Một câu như "so sánh doanh thu giữa các
phòng ban" không có cách nào trả lời được — không phải vì router không hiểu câu hỏi,
mà vì không có câu SQL tham số hoá nào cho việc đó. Nhận xét đúng: đây thật sự là một
giới hạn, không phải một thiết kế đã đủ.

**Quyết định 1 — thêm MỘT câu SQL cố định thứ hai, không phải text-to-SQL tự do.**
`sql/08_business_metrics_compare.sql` — cùng grain, cùng cách tính `mom_growth_pct`
bằng window function như `03_business_metrics.sql`, chỉ khác: không lọc theo
department, trả về mọi phòng ban trong khoảng thời gian. `SqlArgs.query_type`
(`"single_department"` mặc định | `"compare_departments"`) chọn giữa hai câu đã có
sẵn — vẫn giữ nguyên nguyên tắc ADR-013 (không bao giờ để LLM tự sinh SQL). Đây là
lựa chọn có chủ ý: mở rộng số loại câu hỏi trả lời được mà không mở rộng bề mặt tấn
công (không có SQL injection, không câu truy vấn tốn kém ngoài dự kiến).

**Quyết định 2 — so sánh liên phòng ban chỉ dành cho executive.**
`scope.can_compare_departments(role)`: khác `can_query_department` (so một phòng ban
cụ thể với phòng ban người gọi), truy vấn so sánh trả về TẤT CẢ phòng ban cùng lúc —
không có khái niệm "đúng phòng ban của mình", nên chỉ có "được xem toàn bộ" (executive)
hoặc "không được xem gì" (employee/manager, kể cả đúng phòng ban của chính họ).

**Quyết định 3 — tận dụng lại `mom_growth_pct` đã tính sẵn nhưng bị bỏ phí.**
Cả hai câu SQL đều tính tăng trưởng theo tháng bằng `LAG()`/window function từ trước,
nhưng `sql_tool` chưa từng đưa cột đó vào văn bản trả lời — chi phí tính đã trả, giá
trị chưa từng tới tay người dùng. `_format_revenue_line()` giờ thêm hậu tố
`(+x,x% so tháng trước)` khi cột này có giá trị.

**Một lỗi psycopg thật, bắt được khi chạy qua container thật, không phải qua test
mock.** Viết comment giải thích "câu này KHÔNG lọc theo department" bằng đúng cú
pháp placeholder `%(department)s` để minh hoạ — psycopg quét **toàn bộ văn bản** câu
lệnh để tìm token cần bind, **kể cả bên trong comment**, nên nó đòi một tham số
`department` không hề tồn tại trong câu lệnh thật: `ProgrammingError: query
parameter missing: department`. Sửa lần một (viết "%-ngoặc-s" để né cú pháp đầy đủ)
vẫn còn một ký tự `%` trơ trọi, ra lỗi khác:
`only '%s', '%b', '%t' are allowed as placeholders, got '%-'`. Sửa đúng: bỏ hoàn
toàn ký tự phần trăm khỏi mọi comment trong file, mô tả bằng lời thay vì bằng ký
hiệu. **Không unit test mock nào bắt được lỗi này** — `test_executive_can_compare_departments`
(mock `fetch_all`) xanh cả hai lần sai, vì mock không đi qua psycopg thật. Chỉ lộ ra
khi gọi `curl` qua container thật (`docker compose build api && up -d api`).

**Vá lỗ hổng test, không chỉ vá lỗi.** Thêm
`tests/test_sql_integration.py::test_compare_departments_sql_file_actually_executes`
(chạy `fetch_all` thật với đúng file `.sql`, không mock) và
`tests/test_agent_tools.py::test_no_sql_file_has_a_stray_percent_outside_real_placeholders`
(kiểm tĩnh, chạy mặc định không cần DB — quét đúng hai file thật sự đi qua
`psycopg.execute()` bằng tham số, không quét toàn bộ `sql/*.sql` vì các file
schema/seed khác chạy bằng `psql -f` trực tiếp, không qua parameter binding của
psycopg nên không cùng lớp rủi ro).

**Đo thật qua container, cả hai vai trò.** Executive hỏi "so sánh doanh thu giữa các
phòng ban tháng 1 năm 2026" → trả đúng cả 4 phòng ban với số liệu khớp seed
(`sales: 4.200.000.000`, `finance: 820.000.000`, `engineering: 1.500.000.000`,
`hr: 40.000.000`). Manager hỏi cùng câu → `abstained=true`, `tool_used=none`, câu
SQL so sánh chưa từng chạy — đúng thiết kế Quyết định 2.

---

## ADR-031 — `/auth/demo-token`: đăng nhập nhanh cho trang `/ui` công khai, không hardcode API key vào frontend

**Ngày:** 16/09/2026 · **Trạng thái:** accepted

**Bối cảnh.** Trang `/ui` (ADR-029) cần cho phép một người xem trang công khai (nhà
tuyển dụng bấm link sau khi deploy lên Render) tự thử ngay, không cần chạy
`scripts/issue_api_keys.py` hay có quyền truy cập database. Cách đầu tiên định làm —
tạo 3 tài khoản demo, cấp key thật, rồi ghi thẳng 3 key đó vào `web/app.js` làm nút
"đăng nhập nhanh" — **bị chính hệ thống phân loại an toàn của công cụ chặn lại**
(cảnh báo "Credential Leakage") trước khi file được ghi ra đĩa.

**Quyết định.** Không hardcode bất kỳ API key nào vào frontend. Thêm
`POST /auth/demo-token?role=employee|manager|executive` — cấp JWT thẳng cho đúng ba
danh tính demo cố định (`_DEMO_ACCOUNTS` trong `src/api.py`), gọi lại nguyên
`issue_token()` đã có sẵn (`src/jwt_auth.py`), **không kiểm bất kỳ credential nào**.
Ba nút "đăng nhập nhanh" trên `/ui` gọi endpoint này thay vì gửi kèm một API key có
sẵn trong source.

**Vì sao đây là quyết định đúng, không chỉ là né cảnh báo của công cụ.** Cảnh báo
"Credential Leakage" chỉ ra đúng một vấn đề thật: hardcode key vào file sẽ commit
công khai đi ngược chính kỷ luật dự án đã xây từ ADR-015 (key chỉ hiện **đúng một
lần** lúc cấp phát, không bao giờ ở dạng plaintext lâu dài trong bất kỳ file nào,
kể cả file "chỉ để demo"). `/auth/demo-token` giữ đúng nguyên tắc đó: không có API
key nào của ba tài khoản demo từng xuất hiện trong source code, git history, hay
network tab trình duyệt — endpoint tự biết cấp JWT cho ai mà không cần một secret
nào đi kèm request.

**Vì sao bỏ qua xác thực ở ĐÚNG endpoint này là chấp nhận được, không phải một lỗ
hổng.** Ba danh tính trong `_DEMO_ACCOUNTS` không đứng sau bất kỳ dữ liệu thật hay
quyền ghi nào — cùng corpus tổng hợp, cùng bảng `monthly_revenue` giả lập đã dùng
xuyên suốt dự án. `/ask` vẫn chạy đúng toàn bộ RBAC (`can_query_department`,
`can_compare_departments`) trên danh tính JWT này y hệt một nhân viên thật — endpoint
chỉ bỏ qua bước "chứng minh bạn là ai", không bỏ qua bước "bạn được phép xem gì sau
khi đã là ai". Đây KHÔNG phải mẫu áp dụng được cho nhân viên thật — chỉ đúng vì ba
danh tính này được tạo ra chỉ để làm việc này.

**Đo thật qua container.** Cả ba role (`employee`, `manager`, `executive`) lấy được
JWT qua `/auth/demo-token` không kèm header nào; JWT giải mã đúng
`employee_id`/`role`/`department` khớp `_DEMO_ACCOUNTS`; gọi `/ask` bằng JWT đó cho
câu hỏi so sánh liên phòng ban (role executive) trả đúng cả 4 phòng ban, số liệu
khớp seed — cùng kết quả như dùng API key thật qua `/auth/token` ở ADR-030, xác nhận
hai đường xác thực không tạo ra hai luồng RBAC khác nhau.

**Test mới:** `tests/test_api.py::test_demo_token_issues_jwt_without_any_credential`
(3 ca, mỗi role) và `test_demo_token_rejects_role_outside_fixed_allowlist` (giá trị
ngoài 3 literal đã khai báo bị FastAPI tự trả 422). 204 test không-integration xanh.
