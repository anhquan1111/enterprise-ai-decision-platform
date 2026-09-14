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

## ADR-002 — Chốt Gemini cho cả generation và embedding

**Ngày:** mở ở D0, chốt 13/09/2026 · **Trạng thái:** accepted, chốt bằng số đo

**Bối cảnh ban đầu (D0).** Không chọn provider ngay, vì chốt vendor trước khi có bộ
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
| Model so sánh | `gemini-3.5-flash` | Dùng cho A/B ở D2 |
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

Đây chính là bài học `reserve_output` của ngày 19, chỉ khác ở chỗ phần dự trữ còn phải
nuôi một người tiêu thụ vô hình.

### Hệ quả

- **Không đổi schema:** `outputDimensionality=384` khớp cột `vector(384)` đang có.
  Đánh đổi: 384 là bản cắt Matryoshka của vector 3072 chiều, nên mất một phần chất
  lượng. Mức mất chỉ đo được trên bộ eval ở D2; nếu đáng kể thì đổi cột và ingest lại —
  rẻ vì corpus chỉ 16 chunk.
- **Mọi báo cáo số liệu phải ghi tên model và ngày chạy.** Hành vi model đổi theo bản
  phát hành; một con số không có tên model thì không tái lập được.
- **5 câu là smoke test, không phải đánh giá.** Nó nói model chạy được và tuân schema;
  nó không nói model tốt tới đâu. Khác biệt giữa hai model chỉ lộ ra trên bộ 40 câu ở
  D2.
- Ollama và Qwen 7B **giữ lại** làm cấu hình đối chiếu khi máy rảnh, và là một mục thật
  trên CV: chạy model local, đo được giới hạn bộ nhớ, chọn API dựa trên số đo.

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

---

## ADR-009 — Docs retrieval lọc theo role, không lọc theo department

**Ngày:** D2 · **Trạng thái:** accepted, làm rõ lại một câu trong tài liệu D0

**Bối cảnh.** `AskRequest` docstring (viết ở D0) nói: "Role và department nằm trong
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
nghĩa thật cho **tool SQL** (D3): doanh thu của phòng Sales là số liệu Sales sở hữu,
và một nhân viên phòng khác không cần thấy nó ở dạng số thô.

**Hệ quả.** `department` trong `AskRequest` vẫn giữ nguyên schema — nó sẽ dùng để
scope tool SQL khi tool đó được xây ở D3, không phải bỏ đi. Bộ eval của D2 cố tình có
câu hỏi liên phòng ban (một employee HR hỏi về quy trình Engineering) để phản ánh đúng
thiết kế này; nếu sau này router (D3) cần siết department cho SQL, ADR đó sẽ ghi riêng.

---

## ADR-010 — Baseline D2 đo trên 25 câu dev; held-out chạy sớm là một lỗi, đã sửa

**Ngày:** D2 · **Trạng thái:** accepted, có tự sửa lỗi quy trình

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

So với baseline TF-IDF của bài học RAG_Evaluation (ngày 20) trên một corpus khác:
recall@3 khi đó là 92,3%, có 1 câu retrieval trượt do khác biệt từ vựng ("release lỗi"
xếp hạng 5). Cùng loại câu hỏi đó, chạy bằng dense embedding thật trên corpus của dự
án này xếp **hạng 1** (cosine distance 0,208) — đúng như dense retrieval được kỳ vọng
sửa lỗi từ vựng của baseline từ khóa.

**Một lỗi rubric thật, đã sửa trước khi chạy hết bộ.** Câu hỏi về số liệu tạm tính có
rubric `expected_answer_keywords=["khong dung"]`. Model trả lời hoàn toàn đúng —
*"không **được** dùng để báo cáo ra bên ngoài"* — nhưng "khong dung" không phải chuỗi
con của "không được dùng", nên bị chấm nhầm thành `generation_wrong_fact`. Sửa rubric
thành `["khong duoc dung", "khong dung"]` rồi chạy lại đúng câu đó. Đây là ví dụ thật
của bài học ngày 20: rubric từ khóa phải bao trùm cách diễn đạt hợp lý, không chỉ một
cách nói.

**Một lỗi kỹ thuật thật, đã sửa trước khi chạy bất kỳ câu nào.** `expected_answer_keywords`
và corpus viết không dấu, nhưng Gemini luôn trả lời bằng tiếng Việt có dấu đầy đủ —
đúng hành vi mong muốn cho người dùng thật. So khớp chuỗi trực tiếp không bao giờ
khớp ("khong duoc" không phải chuỗi con của "không được"). `src/eval_taxonomy.py`
chuẩn hóa cả hai phía bằng cách bỏ dấu (NFD, xử lý riêng "đ") trước khi so — nếu không
sửa, gần như mọi câu đúng sẽ bị chấm sai.

**Lỗi quy trình: chạy held-out ở D2, đáng lẽ để dành cho D5.**
`docs/architecture.md` ghi rõ "Final report on held-out questions" là việc của D5, sau
khi hybrid retrieval (D3) và RBAC/audit (D4) đã có — hệ thống ở D2 chưa phải hệ thống
cuối cùng. Chạy 5 câu `eval/final.jsonl` ngay hôm nay là chạy sớm, và theo đúng quy
tắc đã ghi ở ngày 19 ("nhiễm thì không xoá, không giả vờ chưa xem — chuyển thành dev,
viết tập cuối mới"): 5 câu đó đã đổi tên thành `F0x_seen_at_d2` và gộp vào
`eval/dev.jsonl`. `eval/final.jsonl` để trống, chờ D5 viết một tập held-out mới trên
hệ thống thật sự hoàn chỉnh.

**Điều chưa đo được, ghi đúng như vậy.** 25 câu là quy mô học tập trên một corpus 16
chunk — đủ để tìm lỗi và xác nhận cơ chế, không đủ để tuyên bố hệ thống đáng tin cậy
ở mọi tình huống. Baseline "sạch tuyệt đối" (0 lỗi) một phần phản ánh corpus nhỏ và
câu hỏi rõ ràng; D3 cần bộ câu hỏi khó hơn hoặc corpus lớn hơn mới biết dense retrieval
còn giới hạn ở đâu — nếu baseline đã hoàn hảo, hybrid retrieval (kế hoạch ban đầu của
D3) có thể không có gì để cải thiện, và quyết định đó cần đo trước khi làm, không mặc
định làm theo kế hoạch cũ.
