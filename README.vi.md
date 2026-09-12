# Enterprise AI Decision Platform (Tiếng Việt)

API hỏi đáp nội bộ cho doanh nghiệp: nhân viên hỏi bằng ngôn ngữ tự nhiên, hệ
thống tự quyết định câu trả lời nằm ở **số liệu kinh doanh (SQL)** hay **tài liệu
quy trình nội bộ (retrieval)**, rồi trả lời **kèm trích dẫn nguồn**, **chỉ trong
phạm vi quyền của người hỏi**, và **ghi nhật ký kiểm toán** mọi lượt truy vấn.

> **Trạng thái: D0 — mới dựng khung.** Dịch vụ khởi động được, báo liveness và
> readiness, và đã áp contract cho `/ask`. Đường trả lời chưa implement: `/ask`
> trả `501` một cách có chủ ý, thay vì trả một câu trả lời giả trông như thật.
> Lộ trình và tiến độ ở [`AGENTS.md`](AGENTS.md#7-session-plan-d0--d5).

## Vì sao làm project này

Ba tính chất quyết định một trợ lý LLM có dùng được trong doanh nghiệp hay
không, và cả ba thường thiếu trong các bản demo:

| Tính chất | Nghĩa cụ thể trong repo này |
|---|---|
| **Câu trả lời kiểm chứng được** | Mọi claim đều có citation — một chunk tài liệu, hoặc chính câu SQL đã tạo ra con số. Câu trả lời không truy nguồn được bị coi là thất bại, không phải thành công. |
| **Phân quyền thật sự có hiệu lực** | Scope được áp bằng filter trong `WHERE` của SQL và trong truy vấn retrieval, **trước khi** bất kỳ text nào tới model. Model không bao giờ nhìn thấy chunk mà người hỏi không được đọc. Dặn model "đừng tiết lộ tài liệu mật" chỉ là một lời dặn, không phải một ranh giới. |
| **Đo chứ không tuyên bố** | Mọi thay đổi retrieval được đánh giá trên một bộ câu hỏi cố định, với baseline đo trước. "Hybrid search tốt hơn" chỉ là một khẳng định nếu có số đứng sau. |

## Chạy thử

Cần: Docker, [uv](https://docs.astral.sh/uv/), Python 3.12.

```bash
git clone https://github.com/anhquan1111/enterprise-ai-decision-platform.git
cd enterprise-ai-decision-platform
cp .env.example .env

uv sync --extra dev
docker compose up -d db
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/00_extensions.sql

uv run uvicorn src.api:app --reload --port 8010
# http://127.0.0.1:8010/docs
```

Kiểm tra:

```bash
curl http://127.0.0.1:8010/health    # liveness, không gọi DB
curl http://127.0.0.1:8010/ready     # readiness, có kiểm PostgreSQL
uv run pytest tests/ -v -m "not integration"
uv run pytest tests/ -v -m integration    # cần container db đang chạy
```

Nếu dùng Git Bash, thêm `MSYS_NO_PATHCONV=1` trước lệnh `docker compose exec`,
nếu không đường dẫn `/sql/...` sẽ bị đổi thành đường dẫn Windows.

## Kiến trúc

Sơ đồ và giải thích đầy đủ: [`docs/architecture.md`](docs/architecture.md).
Các quyết định thiết kế và lý do: [`docs/decisions.md`](docs/decisions.md).

Điểm quan trọng nhất: **phân quyền nằm ở tầng truy vấn dữ liệu, không nằm trong
prompt.** Đây là lý do prompt injection trong một tài liệu được truy xuất không
mở rộng được phạm vi dữ liệu mà người hỏi nhìn thấy.

## Đánh giá

Số chỉ xuất hiện trong README khi nó đã tồn tại, và mỗi số trỏ về một file trong
`evidence/`. Kế hoạch đã chốt trước:

- Khoảng **40 câu hỏi tự viết** có ground truth (doc id đúng), chia **28 câu
  dev** và **12 câu held-out** giữ nguyên tới lần chạy cuối.
- Retrieval đo bằng recall@5 và MRR. Answer đo bằng tính đúng của citation và
  khả năng **abstain** đúng lúc khi corpus (hoặc phạm vi quyền) không có đáp án.
- **Luôn báo số ca tuyệt đối kèm phần trăm.** Trên 28 câu, một câu là ~3,6% —
  nằm trong nhiễu, và sẽ được ghi rõ là nhiễu.

## Giới hạn

- Corpus là **dữ liệu tổng hợp** tự viết cho project. Không dùng tài liệu thật
  của bất kỳ công ty nào.
- Vector search dạng exact, chưa có ANN index. Đúng ở quy mô vài trăm chunk,
  không phải một tuyên bố về khả năng mở rộng.
- Bộ 40 câu là quy mô học tập. Đủ để định vị lỗi và so sánh hai cấu hình, **không
  đủ** để kết luận hệ thống đáng tin cậy ở mọi tình huống.
- Chưa deploy lên cloud. Chạy local bằng Docker Compose.

## Giấy phép

MIT
