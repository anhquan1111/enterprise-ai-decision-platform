# Nhật ký Quyết định Kiến trúc (Decision Log - ADR)

Các bản ghi ngắn gọn ghi lại các lựa chọn kỹ thuật **không hiển nhiên** khi đọc code, để lý do đưa ra quyết định vẫn còn lưu lại sau này. Định dạng chuẩn: **Bối cảnh (Context) → Quyết định (Decision) → Hệ quả (Consequence)**. Một quyết định sau này nếu nhận thấy sai thì sẽ được ghi đè/thay thế bằng một ADR mới tại đây, chứ không âm thầm sửa lén.

---

## ADR-001 — Dùng một instance PostgreSQL duy nhất cho dữ liệu nghiệp vụ, vector và audit log

**Ngày:** D0 • **Trạng thái:** Chấp thuận (Accepted)

**Bối cảnh (Context).** Hệ thống cần các bảng nghiệp vụ quan hệ (cho công cụ SQL Tool), các đoạn văn bản tài liệu kèm vector embedding (cho công cụ Retrieval Tool / RAG), và một bảng nhật ký kiểm toán (Audit Trail). Phương án thay thế phổ biến ngoài thị trường là dựng thêm một Vector Database chuyên dụng (như Qdrant, Weaviate, Pinecone) chạy song song cạnh PostgreSQL.

**Quyết định (Decision).** Sử dụng duy nhất một phiên bản **PostgreSQL 17 kèm extension `pgvector`** cho cả 3 nhiệm vụ trên.

**Vì sao (Why).** Hai lý do lớn, xếp theo thứ tự trọng số:
1. **Kiểm soát phân quyền (Access Control) gom về một nơi duy nhất**: Cơ chế phân quyền cấp dòng (Row-level scoping) cho kết quả SQL và các đoạn tài liệu chunks được thực thi bởi **cùng các mệnh đề `WHERE` trong cùng một phiên kết nối Database**. Nếu dùng một Vector DB riêng biệt, phía tài liệu sẽ phải tự viết một bộ lọc phân quyền riêng, và việc có 2 cách cài đặt khác nhau cho cùng 1 quy tắc an ninh là con đường dẫn tới các lỗ hổng rò rỉ dữ liệu mật (Isolation Bugs).
2. Ít thành phần chuyển động (Fewer moving parts) hơn cho một bản demo có thể khởi động mượt mà chỉ bằng một câu lệnh duy nhất.

**Hệ quả (Consequence).** Các tùy chọn tinh chỉnh tìm kiếm láng giềng gần đúng (ANN - Approximate Nearest Neighbor) sẽ hẹp hơn so với Vector DB chuyên dụng. Tuy nhiên ở quy mô vài trăm đến vài nghìn chunks, điều này hoàn toàn không quan trọng: Tìm kiếm vét cạn chính xác (Exact Search) đủ nhanh và một tuyên bố trung thực "tìm kiếm chính xác vì tập dữ liệu nhỏ" luôn đánh bại một chỉ mục HNSW tạo bừa không đo đạc. Chỉ xem xét lại nếu số đo độ trễ thực tế yêu cầu.

---

## ADR-002 — Chốt Gemini cho cả Generation và Embedding

**Ngày:** Mở ở D0, chốt ngày 13/09/2026 • **Trạng thái:** Chấp thuận (Accepted), chốt bằng số đo thực tế

**Bối cảnh ban đầu (D0).** Không chọn nhà cung cấp vội, vì chốt vendor trước khi có bộ đánh giá sẽ biến phép đo đầu tiên thành cuộc so sánh vendor thay vì đo lường năng lực của hệ thống.

### Điều đã đo thực tế, và nó loại bỏ phương án Local Model:
Máy phát triển: Laptop GPU RTX 4060 8 GB VRAM, 15.2 GB RAM, CPU Ryzen 7 7840H.
Đã cài Ollama và tải model `qwen2.5:7b-instruct-q4_K_M` (4.7 GB). **Model không load được ở cả 3 cấu hình:**
- Đẩy toàn bộ vào GPU (`num_gpu=99`): Lỗi `cudaMalloc failed: out of memory` khi cấp phát 4168 MiB.
- Đẩy một phần vào GPU (`num_gpu=20`): Cùng lỗi trên.
- Chạy thuần CPU (`num_gpu=0`): `ggml_backend_cpu_buffer_type_alloc_buffer: failed`.

Chạy CPU thuần cũng fail chứng minh rằng **nút thắt cổ chai nằm ở RAM hệ thống, không phải VRAM** (lúc đó `nvidia-smi` báo GPU còn trống 7956 MiB). Đo lại:
- RAM tổng: 15.2 GB
- RAM còn trống: 1.1 GB
- Bộ nhớ cam kết (Committed): 28.6 GB / giới hạn 31.2 GB (15.2 GB RAM + 16 GB pagefile).
Chỉ còn **2.6 GB commit headroom**, trong khi model cần một khối liên tục **4.37 GB**. Và đó là lúc máy chỉ đang mở VS Code, Docker, WSL và trình duyệt (môi trường làm việc bình thường).
👉 **Kết luận:** Máy này không thể chạy model 7B local song song với stack lập trình.

### Quyết định (Decision):
| Thành phần | Lựa chọn | Ghi chú |
|---|---|---|
| **Generation (Sinh văn bản)** | **`gemini-3.1-flash-lite`** | Ghim cứng phiên bản cụ thể, **không** dùng alias `-latest` |
| **Model so sánh A/B** | `gemini-3.5-flash` | Dùng để đối chiếu ở D2 |
| **Embedding** | **`gemini-embedding-001`** | `outputDimensionality=384` (giữ nguyên cột `vector(384)`) |
| **Xác thực (Auth)** | API Key đặt trong Header `x-goog-api-key` | **Không** để key lộ trên URL Query String |
| **API Version** | `v1beta` | Bản `v1` không hỗ trợ các model mới này |

### Vì sao các phương án khác bị loại:
- **Local Qwen 7B**: Không load được do thiếu RAM cam kết (đã đo ở trên).
- **Anthropic (Claude)**: Không có API tạo Embedding; gói thuê bao tháng không cấp API key riêng mà phải nạp credit thẻ tín dụng riêng.
- **OpenAI**: Tương tự vấn đề gói thuê bao tháng khác API credit; không có sẵn key.
- **`gemini-2.5-flash`**: API báo lỗi 404 (*"no longer available to new users"*).
- **`gemini-3.8-flash`**: 2 trên 5 request trả về lỗi **503 Service Unavailable** ở gói miễn phí.
- **`gemini-3.6-flash`**: **Không tắt được tính năng Thinking** (`thinkingBudget=0` bị báo lỗi 400).

### Bẫy kỹ thuật bắt buộc phải nhớ: Thinking Token bị trừ vào Max Output!
Gemini 3.x bật chế độ suy nghĩ (Thinking) mặc định, và **`thoughtsTokenCount` được tính thẳng vào `maxOutputTokens`**. Đã đo được với `maxOutputTokens = 80`:
- Model dùng hết 75 token để suy nghĩ, chỉ còn 1 token để xuất $ightarrow$ Bị ngắt với `finishReason = MAX_TOKENS` $ightarrow$ Nội dung trả về bị **RỖNG** dù mã HTTP vẫn là 200!
- Ở tầng trên nó sẽ hiện ra thành lỗi Parse JSON rất khó hiểu.
👉 **Giải pháp:** Đặt `llm_max_output_tokens = 1200` và luôn kiểm tra `finishReason` trước khi parse.

---

## ADR-003 — Bộ Eval và các file Evidence được commit lên Git; Dữ liệu thô và mô hình thì không

**Ngày:** D0 • **Trạng thái:** Chấp thuận (Accepted)

**Bối cảnh.** File `.gitignore` thông thường sẽ loại trừ toàn bộ thư mục dữ liệu. Nhưng các câu hỏi đánh giá ở đây là Ground Truth được viết cẩn thận bằng tay, và mọi con số tuyên bố trong README đều phải truy nguyên được từ một lần chạy cụ thể.

**Quyết định.** Commit thư mục `eval/` (câu hỏi và đáp án kỳ vọng) và thư mục `evidence/` (kết quả log thô sau các lần chạy). Vẫn giữ `data/raw/`, `models/`, `mlruns/` ở ngoài git.

**Vì sao.** Một con số metric tuyên bố mà không thể truy vết về một file log cụ thể thì không phải là bằng chứng. Bộ câu hỏi eval cũng là tạo tác giúp việc đo lường so sánh giữa các ngày có giá trị chuẩn xác.

---

## ADR-004 — Tách riêng hai Endpoint Liveness (`/health`) và Readiness (`/ready`)

**Ngày:** D0 • **Trạng thái:** Chấp thuận (Accepted)

**Bối cảnh.** Nếu một Container Healthcheck gọi tới Database, khi Database bị khởi động lại hoặc nghẽn mạng ngắn hạn, container ứng dụng sẽ bị đánh giá là lỗi và Docker/Kubernetes sẽ restart một tiến trình vốn đang hoạt động hoàn toàn bình thường.

**Quyết định.**
- `/health`: Chỉ báo cáo tiến trình Python còn sống, **không gọi bất kỳ dependency nào**.
- `/ready`: Kiểm tra kết nối tới PostgreSQL và trả về HTTP `503` khi không kết nối được. Docker `HEALTHCHECK` cấu hình trỏ vào `/health`.

**Hệ quả.** Khi Database gặp sự cố, service sẽ tạm thời ở trạng thái "Not-ready" (để Load Balancer ngừng đẩy khách hàng vào) mà không bị kích hoạt vòng lặp khởi động lại vô tận (Restart Loop).

---

## ADR-005 — Database Host mặc định là `127.0.0.1`, tuyệt đối không dùng `localhost`

**Ngày:** D0 • **Trạng thái:** Chấp thuận (Accepted), nguyên nhân xác định bằng số đo thực tế

**Bối cảnh.** Bài kiểm tra tích hợp chạy mãi không xong thay vì báo lỗi nhanh. Tái hiện lại có chủ đích: Với `POSTGRES_HOST=localhost`, bài test không hoàn thành trong 240 giây; với `127.0.0.1`, test pass trong **0.44 giây**.

### Đo đạc thực tế:
| Phép đo | Kết quả |
|---|---|
| `socket.getaddrinfo("localhost", 5433)` | Trả về IPv6 `::1` **trước**, sau đó mới tới IPv4 `127.0.0.1` |
| `Get-NetTCPConnection -LocalPort 5433` | Chỉ có 1 cổng lắng nghe trên `127.0.0.1`, không có gì trên `[::1]` |
| Kết nối Python thuần tới `("::1", 5433)` | Bị từ chối (`ConnectionRefusedError`) sau **2.04 giây** |
| Kết nối Python thuần tới `("127.0.0.1", 5433)` | Kết nối thành công trong **0.000 giây** |
| `psycopg.connect(...@localhost...?connect_timeout=5)` | Thành công sau **5.08 giây** (chính bằng thời gian timeout) |
| `psycopg.connect(...@127.0.0.1...)` | Thành công sau **0.04 giây** |

**Nguyên nhân.** Ba yếu tố kết hợp tạo thành con đường chậm:
1. `localhost` là tên miền, và trên Windows nó ưu tiên phân giải IPv6 trước.
2. Docker Compose chỉ mở cổng trên IPv4 `127.0.0.1:5433`, nên cổng IPv6 không có ai lắng nghe.
3. Thư viện `libpq` thử các địa chỉ theo thứ tự và áp dụng `connect_timeout` cho **từng địa chỉ một**. Lần thử IPv6 mất đứt 5 giây chờ đợi trước khi fallback sang IPv4!

**Quyết định.** Mặc định `POSTGRES_HOST` là `127.0.0.1` trong cả `src/config.py` và `.env.example`. Luôn kèm `connect_timeout=5` vào chuỗi kết nối DSN.

**Bài học tổng quát.** Thiếu timeout sẽ biến một lỗi nhanh thành một trạng thái treo vô hạn. Mọi lời gọi ra bên ngoài thêm vào sau này (LLM API, embedding, reranker) đều phải đặt timeout ngay lúc viết code.

---

## ADR-006 — Contract dữ liệu là một module dùng chung, Severity phân theo hậu quả

**Ngày:** D1 • **Trạng thái:** Chấp thuận (Accepted)

**Bối cảnh.** Dữ liệu tài liệu vào hệ thống qua Ingestion và sẽ được đọc lại ở luồng Serving. Cách dễ nhất là kiểm tra rải rác ở mỗi nơi tiêu thụ.

**Quyết định.** Toàn bộ quy tắc nằm tập trung trong `src/contracts.py`, áp dụng **một lần duy nhất ở biên Ingestion**. Hai mức độ nghiêm trọng phân theo **hậu quả nếu dòng đó lọt vào bảng chính**:
- `FATAL`: Đưa dòng vào Quarantine (Khu cách ly).
- `WARNING`: Cho dòng vào bảng chính nhưng đếm số lượng và cảnh báo.

**Vì sao.** Kiểm tra rải rác thì mỗi nơi kiểm tra một kiểu, chỗ nào quên thì chỗ đó sai. Với `access_level` điều này cực kỳ nguy hiểm: Nó là ranh giới bảo mật, nên một giá trị lạ phải bị từ chối chứ không được tự ý hạ xuống mức thấp nhất (Fail-closed). Tránh hoàn toàn lỗi sai lệch Train/Serving Skew.

---

## ADR-007 — Seed Idempotent, không dùng `TRUNCATE CASCADE`

**Ngày:** D1 • **Trạng thái:** Chấp thuận (Accepted), phát hiện khi chạy thật

**Bối cảnh.** Bản đầu tiên của `sql/02_seed.sql` mở đầu bằng:
`TRUNCATE monthly_revenue, employees, departments CASCADE;` cho "sạch".

**Điều đã xảy ra.** Bảng `doc_chunks` có khóa ngoại trỏ tới `departments`, nên lệnh `CASCADE` lan sang và **xóa sạch toàn bộ tài liệu đã nạp trước đó**!

**Quyết định.** Bỏ hoàn toàn `TRUNCATE`. Cả 3 bảng chuyển sang dùng:
`INSERT ... ON CONFLICT DO UPDATE`.

**Hệ quả.** Chạy lại file seed bao nhiêu lần cũng an toàn tuyệt đối và không ảnh hưởng tới dữ liệu tài liệu.
**Bài học tổng quát.** Một lệnh dọn dẹp có `CASCADE` phải được đọc cùng với sơ đồ khóa ngoại, không được nhìn một mình. "Cho sạch" là lý do rất yếu để xóa dữ liệu.

---

## ADR-008 — Giữ Index `ix_chunks_scope` dù ở quy mô hiện tại chưa đo được lợi ích

**Ngày:** D1 • **Trạng thái:** Chấp thuận (Accepted), có số đo thực tế

**Bối cảnh.** Kho tài liệu hiện có 16 chunks. Một index ở quy mô đó là chuẩn bị cho tương lai, không phải tối ưu tức thì.

**Số đo thực tế (Chi tiết trong `docs/query_plan.md`):**
| Quy mô | Kế hoạch thực thi | Thời gian chạy (Execution Time) |
|---:|---|---:|
| 16 dòng thật, CÓ index | Index Scan | 0.085 ms |
| ~20.000 dòng, CÓ index | Bitmap Heap Scan | 1.237 ms |
| ~20.000 dòng, KHÔNG index | Seq Scan (Quét tuần tự) | 3.051 ms |

**Quyết định.** Giữ index `ix_chunks_scope (department, access_level, available_at)`. **Chưa** tạo chỉ mục ANN (HNSW/IVFFlat) cho cột `embedding`.

**Vì sao.** Ở quy mô 20.000 dòng, index nhanh hơn ~2.5 lần. Chưa tạo ANN index vì ở quy mô nhỏ, Exact Search nhanh hơn và không có sai số. Chỉ mở khi số đo thực tế yêu cầu.
