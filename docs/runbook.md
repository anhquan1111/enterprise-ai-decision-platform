# Runbook

Hướng dẫn xử lý sự cố, viết TRƯỚC khi cần dùng — mỗi mục theo đúng cấu trúc: triệu
chứng, chẩn đoán nhanh, hành động, xác nhận đã xong, khi nào leo thang. Xem
`D:/Documents/AI/Update/Reliability_&_Access_Control/3. Rollback_Recovery_Runbook_Postmortem.md`
(vault) cho lý thuyết đầy đủ đứng sau format này.

---

## 1. Kết quả `/ask` qua HTTP khác kết quả gọi hàm Python trực tiếp

Sự cố **thật** đã xảy ra khi debug D3 — xem `AGENTS.md` mục "Non-obvious Patterns &
Gotchas" và postmortem đầy đủ trong vault (`Reliability_&_Access_Control/4. Lab.md`).

### Triệu chứng
- Gọi `run_agent()`/`retrieve()` trực tiếp bằng script cho kết quả ĐÚNG.
- Gọi qua HTTP (`curl`, client thật) tới cùng endpoint cho kết quả SAI hoặc CŨ.

### Chẩn đoán nhanh
```powershell
Get-NetTCPConnection -LocalPort 8010 -State Listen -ErrorAction SilentlyContinue
Get-Process -Id (Get-NetTCPConnection -LocalPort 8010 -State Listen).OwningProcess |
    Select-Object Id, StartTime
```
So `StartTime` với thời điểm sửa code gần nhất. Cũ hơn → đúng sự cố này.

### Hành động
1. `Stop-Process -Id <pid> -Force`.
2. Xác nhận port trống (chạy lại lệnh chẩn đoán, không còn PID nào).
3. Start lại: `uv run uvicorn src.api:app --port 8010`.
4. Đọc log khởi động — phải thấy "Application startup complete", không phải lỗi bind.

### Xác nhận đã xong
Gọi lại đúng request đã sai ở bước 1 — kết quả phải khớp kết quả gọi hàm trực tiếp.

### Khi nào leo thang
Sau khi kill và start lại vẫn sai → không phải sự cố process cũ, quay lại nghi ngờ
logic code.

---

## 2. `/ready` báo `503` — PostgreSQL không tới được

### Triệu chứng
`GET /ready` trả `503`, `checks.postgres` bắt đầu bằng `"unreachable:"`.

### Chẩn đoán nhanh
```bash
docker compose ps db
docker compose logs db --tail 50
```

### Hành động
1. Nếu container không chạy: `docker compose up -d db`.
2. Nếu container chạy nhưng không nhận kết nối: đợi tối đa `postgres_connect_timeout`
   giây (mặc định 5s, `src/config.py`) — connect có timeout rõ ràng (ADR-005), không
   treo vô hạn.
3. Nếu vẫn lỗi sau khi container khoẻ mạnh: kiểm `DATABASE_URL` build đúng chưa
   (`get_settings().database_url`), đặc biệt `postgres_host` phải là `127.0.0.1`
   (ADR-005 — `localhost` gây treo 5s/connection do thử IPv6 trước).

### Xác nhận đã xong
`curl http://127.0.0.1:8010/ready` trả `200`, `checks.postgres` bắt đầu bằng `"ok"`.

### Khi nào leo thang
Container khoẻ, network tới được, nhưng vẫn lỗi → kiểm `pg_hba.conf`/credentials
trong `.env` có khớp `sql/02_seed.sql` không.

---

## 3. `/ask` trả `401`/`403` hàng loạt (nghi ngờ sự cố xác thực, D4)

### Triệu chứng
Nhiều client báo `/ask` trả `401 khong xac thuc duoc` hoặc `403` dù trước đó vẫn
dùng bình thường.

### Chẩn đoán nhanh
```bash
# 401: key sai/hết hạn/chưa cấp — kiểm nhân viên có api_key_hash chưa
uv run python -c "
from src.db import fetch_all
print(fetch_all('SELECT employee_id, api_key_hash IS NOT NULL AS has_key FROM employees'))
"
```
- Nếu `has_key=False` cho nhân viên đang báo lỗi → chưa từng được cấp key.
- Nếu `has_key=True` nhưng vẫn `401` → key phía client không khớp hash lưu (key bị
  gõ sai, hoặc key đã bị cấp lại — `issue_api_keys.py` không ghi đè key đang có,
  nên chỉ xảy ra nếu ai đó UPDATE thủ công cột `api_key_hash`).
- `403` (khác 401): key ĐÚNG nhưng `role`/`department` trong request KHÔNG khớp bản
  ghi nhân viên — kiểm client có đang gửi đúng role/department của chính họ không
  (đây là hành vi ĐÚNG THIẾT KẾ nếu client cố tình/nhầm gửi sai, không phải bug).

### Hành động
- Thiếu key: `uv run python -m scripts.issue_api_keys`, gửi key mới cho đúng nhân
  viên qua kênh riêng (không log, không commit).
- `403` hàng loạt bất thường: kiểm gần đây có ai sửa `role`/`department` của nhân
  viên trong bảng `employees` mà chưa báo cho client cập nhật request không.

### Xác nhận đã xong
`curl` thử với key + role/department đúng, nhận `200`.

### Khi nào leo thang
Key đúng, role/department khớp, vẫn `401`/`403` → nghi ngờ bug trong `src/auth.py`,
không phải vấn đề vận hành — xem lại test `tests/test_auth.py`/`test_auth_integration.py`
có còn xanh không trước khi sửa gì.

---

## 4. `/ask` chậm bất thường hoặc trả `503 upstream error` khi có tải đồng thời

### Triệu chứng
Nhiều request cùng lúc, một phần trả `503`, log có `429 Too Many Requests` hoặc
`503 Service Unavailable` từ `generativelanguage.googleapis.com`.

### Chẩn đoán nhanh
Đây là sự cố **đã đo thật** ở vault ngày 25 — không phải giả định. Đọc log tìm dòng
`INFO:httpx:HTTP Request: POST .../generateContent "HTTP/1.1 429...` hoặc `503...`.

### Hành động
- Đây là giới hạn của Gemini free-tier, không phải bug trong code — retry đã có
  (`_NETWORK_RETRY_ATTEMPTS=3`, có jitter từ D4) sẽ tự phục hồi phần lớn trường hợp.
- Nếu tần suất `503` cao và kéo dài: cân nhắc nâng hạn mức API (trả phí) hoặc giảm
  tải đồng thời phía client (xem vault ngày 25, mục "Phương án mở rộng").

### Xác nhận đã xong
Tỷ lệ `503` giảm về gần 0 sau khi tải giảm hoặc hạn mức được nâng.

### Khi nào leo thang
`503` xảy ra ngay cả khi chỉ có 1 request tại một thời điểm → không phải rate limit,
kiểm `LLM_API_KEY` còn hợp lệ và còn quota chưa.

---

## 5. Rollback sau một lần đổi cấu hình gây lỗi (ví dụ đổi `llm_model`)

### Triệu chứng
Sau khi đổi biến môi trường (`.env`) và restart, `/ask` bắt đầu lỗi hoặc trả kết quả
tệ hơn rõ rệt.

### Hành động
1. Sửa lại đúng giá trị cũ trong `.env` (mọi setting đều tách khỏi code —
   `src/config.py` — không cần build lại image).
2. Restart process/container.
3. Xác nhận bằng `uv run pytest tests/ -v -m "not integration and not live_llm"` xanh
   trước khi coi là xong.

### Xác nhận đã xong
`/ask` trả lời đúng như trước khi đổi cấu hình, trên cùng một câu hỏi đã biết đáp án
(ví dụ câu hỏi mẫu trong README).

### Khi nào leo thang
Rollback cấu hình không sửa được — nghi ngờ vấn đề nằm ở code, không phải cấu hình;
dùng `git log`/`git revert` cho commit gây lỗi.
