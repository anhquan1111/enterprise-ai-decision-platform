# Kịch bản quay GIF — /ui + Grafana (~60 giây, không lời thoại)

GIF này chỉ để nhúng vào `README.md` (autoplay, không có âm thanh), khác với
`docs/demo_script.md` (bản `curl`/terminal đầy đủ, có tường thuật). Vì GIF không
có tiếng, kịch bản dưới đây chỉ ghi **thao tác** và **nên dừng ở đâu vài giây để
người xem đọc kịp chữ trên màn hình** — không cần đọc gì thành lời khi quay.

Nguyên tắc cũ vẫn giữ: không dàn dựng, không cắt bỏ nếu có gì chạy chậm/lỗi thật —
xem "Không nên làm gì" ở cuối.

Công cụ quay: **ScreenToGif** (miễn phí, Windows, [screentogif.com](https://www.screentogif.com/))
— quay trực tiếp một vùng màn hình rồi xuất thẳng ra `.gif`, không cần bước
convert bằng ffmpeg, và có thể bật hiệu ứng highlight khi click chuột để người
xem dễ theo dõi thao tác.

**60 giây là ngân sách chặt** vì mỗi lần gọi `/ask` thật sự tốn 2–6 giây chờ (đã đo
thật, câu so sánh phòng ban từng mất ~6.5s) — không phải hoạt ảnh giả. Vì vậy
kịch bản dưới đây CHỈ chọn 4 lát cắt "đắt" nhất, bỏ bớt phần chính sách nội bộ để
đủ thời lượng. Nếu quay xong dư ra vài giây chết (lúc chờ loading-dots), có thể
cắt bớt trong ScreenToGif editor (xoá frame) để giữ đúng nhịp.

## Chuẩn bị (trước khi quay — không tính vào 60 giây)

Container `db`/`prometheus`/`grafana` cứ để nguyên như đang chạy (`docker compose
ps` để kiểm tra).

**Muốn panel Grafana thật sự nhảy trên hình** (nên làm — đó là lý do có bản
Grafana thay vì chỉ quay terminal), rebuild lại riêng image `api`; `db`/
`prometheus`/`grafana` không bị đụng tới:

```bash
docker compose build api && docker compose up -d api
```

Đây là rebuild thật (vài chục giây, 1 image Python nhỏ) — làm việc này **trước**
khi bấm record, không phải trong lúc quay. Không phải rebuild lại cả stack; volume
`db-data`/`prometheus-data`/`grafana-data` không bị mất gì đã scrape trước đó.

Có cách nhẹ hơn nhưng **sẽ làm hỏng phần Grafana**: chạy
`uv run uvicorn src.api:app --port 8010` trực tiếp trên máy vẫn dùng được cho UI,
nhưng Prometheus scrape theo mạng container ở `api:8010`
(`docker/prometheus/prometheus.yml`), không phải máy host — nếu chỉ cần quay phần
UI (docs/SQL/RBAC) mà không cần Grafana thì cách này nhanh hơn.

**Không cần chuẩn bị API key nào cả.** Ba nút đăng nhập nhanh trong `/ui` gọi
`POST /auth/demo-token` (ADR-031), tự cấp JWT thẳng cho 3 danh tính demo cố định —
không có API key nào lưu trong frontend để phải copy hay giữ kín khi quay. Đây
cũng chính xác là những gì một nhà tuyển dụng sẽ làm khi bấm vào link đã deploy.

Mở sẵn 2 tab trước khi bấm record:
- Tab 1: `http://127.0.0.1:8010/ui/`
- Tab 2: `http://127.0.0.1:3000` (Grafana; đăng nhập `admin`/`admin` nếu chưa đổi)
  → mở sẵn dashboard **"Enterprise AI Decision Platform - /ask overview"**

## Kịch bản theo giây (~60s)

Tên nút bên dưới là chữ thật đang có trong `web/index.html`. Mỗi thẻ câu hỏi mẫu ở
sidebar xoay vòng 3 câu thật mỗi lần bấm — **chỉ bấm mỗi thẻ đúng 1 lần** trong lúc
quay, theo đúng thứ tự dưới đây, để câu hỏi hiện ra khớp với những gì mô tả.

| Giây | Thao tác |
|---|---|
| 0:00–0:05 | Màn login: bấm thẻ đăng nhập nhanh **Employee · Phòng Sales** (không cần key) |
| 0:05–0:15 | Bấm **"Doanh thu phòng khác"** → **Gửi**. Chờ badge **"Từ chối"** (màu hổ phách) hiện ra — đây là RBAC chặn thật, dừng lại ~2s cho người xem đọc |
| 0:15–0:25 | Bấm **"Doanh thu phòng mình"** → **Gửi**. Chờ số liệu thật hiện ra kèm `(+x,x% so tháng trước)` — dừng ~2s |
| 0:25–0:30 | Bấm **"Đăng xuất"**, rồi bấm thẻ đăng nhập nhanh **Executive · Phòng Finance** |
| 0:30–0:40 | Bấm **"So sánh mọi phòng ban"** → **Gửi**. Chờ cả 4 phòng ban hiện ra trong 1 câu trả lời — dừng ~3s |
| 0:40–0:55 | Chuyển qua tab Grafana, để chuột dừng lần lượt ở panel **"Request rate by tool"** rồi **"Non-2xx rate"** — 2 panel này vừa nhảy đúng theo các click ở trên |
| 0:55–1:00 | Quay lại tab UI, dừng ở khung hội thoại đang có 3 câu hỏi/trả lời — kết thúc |

Nếu dư giây (ví dụ request trả lời nhanh hơn dự kiến), có thể bấm thêm
**"Chính sách nội bộ"** → **Gửi** ngay sau bước 0:25 để khoe thêm phần trích dẫn
tài liệu (citation) — không bắt buộc, chỉ thêm nếu còn ngân sách thời gian.

## Không nên làm gì

- Đừng dán API key thật của một nhân viên vào ô đăng nhập cho video này — các thẻ
  đăng nhập nhanh sinh ra chính là để không cần gõ/lộ key nào cả. Nếu muốn quay
  luồng `/auth/token` thủ công, phải cấp key **mới** cho nhân viên demo **mới**,
  không dùng lại key của nhân viên đã tồn tại (AGENTS.md cấm ghi đè key cũ).
- Đừng bấm một thẻ sidebar quá 1 lần trước khi Gửi — chữ trên thẻ không đổi nhưng
  câu hỏi bên dưới sẽ nhảy sang 1 trong 3 biến thể tiếp theo, bấm nhầm 2 lần sẽ
  làm câu hỏi hiện ra không khớp với thứ tự mô tả ở trên.
- Đừng refresh Grafana trước khi request thật sự chạy xong — Prometheus scrape
  theo chu kỳ (`docker/prometheus/prometheus.yml`), nên chờ vài giây sau click
  cuối rồi mới chuyển tab, không thì panel sẽ trống trên hình.
- Nếu một request chạy chậm hoặc panel chưa kịp cập nhật, cứ giữ nguyên trong
  video và không cắt sửa — đúng tinh thần "không dàn dựng" mà dự án đã theo từ
  đầu.

## Sau khi quay xong

File GIF đã lưu tại `docs/Demo.gif` và đã được chèn vào cả `README.md` (bản
tiếng Anh) và `README.vi.md` (bản tiếng Việt), ngay sau đoạn giới thiệu/status
callout, trước mục "Why this project" / "Vì sao làm project này":

```markdown
![UI + Grafana demo](docs/Demo.gif)
```

Giữ file dưới ~10 MB để load được trên GitHub — file hiện tại ~2.1 MB nên thoải
mái. Nếu quay lại sau này và file xuất ra to hơn 10 MB, giảm frame rate xuống
~10–12 fps thay vì giảm độ phân giải (chữ cần giữ rõ để đọc được).
