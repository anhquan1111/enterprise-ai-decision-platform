# Deploy lên Render — Blueprint 1-click + các bước thủ công sau lần đầu

`render.yaml` ở gốc repo định nghĩa 1 database Postgres (free) + 1 web service
chạy bằng Docker (`Dockerfile` có sẵn, không cần viết thêm gì). Phần này ghi lại
đúng những gì cần làm — không nhiều hơn, không giấu bước thủ công nào.

## 1. Tạo Blueprint

1. Đăng nhập [dashboard.render.com](https://dashboard.render.com), chọn
   **New > Blueprint**, trỏ vào repo GitHub này.
2. Render đọc `render.yaml`, hiện ra 2 resource: database `enterprise-ai-db` và
   web service `enterprise-ai-decision-platform`. Bấm **Apply**.
3. Vì `LLM_API_KEY` và `JWT_SECRET_KEY` khai báo `sync: false` trong
   `render.yaml`, Render sẽ hỏi nhập giá trị thật ngay lúc này — **không giá trị
   thật nào nằm trong file đã commit**:
   - `LLM_API_KEY`: key thật lấy ở Google AI Studio (giống hệt key dùng ở local
     `.env`).
   - `JWT_SECRET_KEY`: sinh mới, không dùng lại key ở local
     (`python -c "import secrets; print(secrets.token_urlsafe(32))"`).
4. Đợi build xong. `preDeployCommand: uv run --no-sync alembic upgrade head`
   trong `render.yaml` tự tạo schema (bảng + extension `vector`/`pg_trgm`) —
   không cần chạy tay bước này.

Sau bước 4, service đã **chạy được** (`/health` trả `200`), nhưng `/ui` sẽ trả
lời rỗng/abstain cho mọi câu hỏi vì `monthly_revenue` chưa có dữ liệu và
`doc_chunks` chưa có tài liệu nào — đó là lý do có bước 2 dưới đây.

## 2. Nạp dữ liệu demo (chỉ làm 1 lần)

`Dockerfile` cố tình **không COPY thư mục `data/`** vào image (giữ image nhẹ,
đúng tinh thần "chỉ copy những gì runtime cần" đã áp dụng cho `sql/`/`web/`) —
nên bước ingest tài liệu phải chạy từ máy của bạn, trỏ thẳng vào Postgres trên
Render, không chạy được từ bên trong container đã deploy.

1. Lấy **External Database URL** ở tab "Connect" của database `enterprise-ai-db`
   trên dashboard Render.
2. Từ máy bạn, tạm trỏ `.env` sang DB đó (đừng ghi đè `.env` đang dùng cho local
   — sao ra một file khác hoặc export biến môi trường trong shell tạm thời), rồi
   chạy 2 lệnh sau bằng chính `uv` đang có trên máy:

   ```bash
   # Seed số liệu doanh thu (bảng monthly_revenue) — dùng psql trực tiếp với
   # External Database URL lấy ở bước 1.
   psql "<external-database-url>" -f sql/02_seed.sql

   # Ingest tài liệu chính sách nội bộ (data/documents.csv) + sinh embedding qua
   # Gemini API — cần LLM_API_KEY thật trong .env đang trỏ vào DB đó.
   uv run python -m scripts.ingest
   ```

3. Sau khi cả 2 lệnh chạy xong, `/ui` trên Render đã trả lời được cả câu SQL lẫn
   câu chính sách nội bộ — thử lại `docs/demo_script_ui.md` với domain Render
   thay vì `127.0.0.1:8010`.

Không cần seed bảng `employees` cho bản demo công khai: ba tài khoản đăng nhập
nhanh trên `/ui` đi qua `POST /auth/demo-token` (ADR-031), cấp JWT trực tiếp,
không tra bảng `employees` nào cả.

## Giới hạn đã biết (nói thẳng, không tô hồng)

- **Free plan của Render "ngủ" sau ~15 phút không có request** — lần bấm đầu
  tiên của một nhà tuyển dụng sau thời gian dài có thể mất 30–50 giây để container
  khởi động lại trước khi trả lời. Đây là giới hạn của gói free, không phải lỗi
  của hệ thống.
- **Postgres free của Render hết hạn sau 30 ngày** — nếu link demo im lặng đột
  ngột sau khoảng thời gian đó, khả năng cao là database đã bị Render xoá theo
  chính sách free tier, cần tạo lại database rồi lặp lại bước 2.
- **Grafana/Prometheus không nằm trong blueprint này** — `render.yaml` chỉ
  deploy API + Postgres. Dashboard Grafana trong `docs/demo_script_ui.md` vẫn
  chỉ chạy được ở local qua `docker compose up -d prometheus grafana`, không có
  bản public tương ứng.
