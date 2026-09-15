# Query plan của đường truy vấn retrieval

Đo thật trên máy phát triển ngày 13/09/2026, PostgreSQL 17.11 trong Docker. Tái lập:

```bash
docker compose exec -T db psql -U app -d enterprise_ai -f /sql/05_explain.sql
```

Toàn bộ phần phình dữ liệu nằm trong một transaction kết thúc bằng `ROLLBACK`, nên
corpus thật không đổi — kiểm chứng ở cuối file.

## Câu truy vấn được đo

Đây là đường đi thật của tool retrieval: lọc theo phạm vi quyền, rồi lọc theo thời
điểm dữ liệu đã có trong hệ thống.

```sql
SELECT doc_id, chunk_index, title
FROM doc_chunks
WHERE department = 'finance'
  AND access_level = ANY(ARRAY['employee', 'manager'])
  AND available_at <= '2026-09-01 00:00+00';
```

Index đang có:

```sql
CREATE INDEX ix_chunks_scope ON doc_chunks (department, access_level, available_at);
```

## Ba phép đo

### A. 16 dòng thật, có index

```text
Index Scan using ix_chunks_scope on doc_chunks  (cost=0.14..8.17 rows=1 width=68)
                                                (actual time=0.031..0.033 rows=4 loops=1)
  Index Cond: ((department = 'finance') AND (access_level = ANY ('{employee,manager}'))
               AND (available_at <= '2026-09-01 00:00:00+00'))
  Buffers: shared hit=2
Planning Time: 0.572 ms
Execution Time: 0.085 ms
```

**Kết quả này ngược với dự đoán của tôi.** Tôi nghĩ ở 16 dòng Postgres sẽ chọn
`Seq Scan` vì đọc cả bảng còn rẻ hơn đi qua index. Số đo nói khác: planner vẫn chọn
`Index Scan`.

Hai chi tiết đáng đọc ở đây, và cả hai đều quan trọng hơn việc nó chọn scan nào:

- **`rows=1` (ước lượng) so với `rows=4` (thực tế).** Ở bảng nhỏ, thống kê quá mỏng để
  ước lượng đúng. Lệch 4 lần mà vẫn chọn đúng kế hoạch chỉ vì ở quy mô này mọi kế
  hoạch đều nhanh.
- **Planning Time 0.572 ms so với Execution Time 0.085 ms.** Lập kế hoạch tốn gấp 6
  lần thực thi. Nói cách khác, ở quy mô này index không giải quyết vấn đề gì cả —
  không có vấn đề nào để giải quyết.

### B. ~20.000 dòng, có index

```text
Bitmap Heap Scan on doc_chunks  (cost=67.13..565.53 rows=3337 width=41)
                                (actual time=0.193..1.057 rows=3337 loops=1)
  Recheck Cond: (...)
  Heap Blocks: exact=440
  Buffers: shared hit=448
  ->  Bitmap Index Scan on ix_chunks_scope  (cost=0.00..66.30 rows=3337 width=0)
                                            (actual time=0.148..0.148 rows=3337 loops=1)
        Buffers: shared hit=8
Planning Time: 0.167 ms
Execution Time: 1.237 ms
```

Kế hoạch đổi từ `Index Scan` sang **`Bitmap Heap Scan`**: khi số dòng khớp lớn, đọc
index để dựng bitmap rồi đọc heap theo thứ tự block rẻ hơn là nhảy ngẫu nhiên từng
dòng. Ước lượng `rows=3337` khớp đúng thực tế vì đã chạy `ANALYZE`.

### C. ~20.000 dòng, không index

```text
Seq Scan on doc_chunks  (cost=0.00..790.28 rows=3337 width=41)
                        (actual time=0.010..2.953 rows=3337 loops=1)
  Filter: (...)
  Rows Removed by Filter: 16679
  Buffers: shared hit=440
Planning Time: 0.064 ms
Execution Time: 3.051 ms
```

`Rows Removed by Filter: 16679` là con số đáng nhìn nhất trong cả ba plan: quét
20.016 dòng để lấy 3.337 dòng, bỏ đi 16.679 dòng. Đó chính là phần việc mà index
tránh được.

## Tổng hợp

| Phép đo | Quy mô | Kế hoạch | Execution Time | Ước lượng vs thực tế |
|---|---:|---|---:|---|
| A | 16 dòng | Index Scan | 0,085 ms | rows=1 vs 4 — lệch |
| B | ~20k dòng | Bitmap Heap Scan | 1,237 ms | rows=3337 vs 3337 — khớp |
| C | ~20k dòng | Seq Scan | 3,051 ms | rows=3337 vs 3337 — khớp |

Index nhanh hơn **khoảng 2,5 lần** ở 20k dòng (1,237 ms so với 3,051 ms).

## Bốn điều rút ra

**1. Index chỉ đáng kể khi dữ liệu đủ lớn.** Ở 16 dòng, thời gian lập kế hoạch lớn
hơn thời gian thực thi, nên không có gì để tối ưu. Tạo index ở đây là chuẩn bị cho
tương lai, không phải một cải thiện đo được hôm nay.

**2. 2,5 lần là mức khiêm tốn, và có lý do.** Query này trả về ~17% số dòng của bảng
(3.337 trên 20.016). Index phát huy nhất khi **chọn lọc cao** — lấy vài dòng trong
nhiều. Lọc theo một phòng ban trong bốn phòng ban thì vốn đã không chọn lọc. Muốn
nhanh hơn nhiều thì phải đổi câu hỏi hoặc đổi cách phân vùng dữ liệu, không phải thêm
index khác.

**3. `ANALYZE` không phải chi tiết nhỏ.** Nếu chèn 20k dòng mà không chạy `ANALYZE`,
planner vẫn dùng thống kê của bảng 16 dòng và chọn kế hoạch theo một thực tế đã cũ.
Lệch ước lượng so với thực tế trong plan là chỗ đầu tiên cần nhìn khi một query
chậm bất thường.

**4. Thứ tự cột trong index khớp với thứ tự lọc của câu truy vấn.**
`(department, access_level, available_at)` dùng được cho cả ba điều kiện vì hai cột
đầu là so sánh bằng và cột cuối là so sánh khoảng. Nếu đặt `available_at` lên đầu thì
hai điều kiện bằng phía sau không dùng được index hiệu quả nữa.

## Chưa làm

- **Chưa có ANN index** (HNSW/IVFFlat) cho cột `embedding`. Ở vài trăm chunk, exact
  search nhanh hơn và không có sai số. Mở khi số đo nói cần, không mở vì nghe hợp lý.
- **Chưa đo với concurrency.** Cả ba plan ở trên là một truy vấn đơn lẻ trên máy rảnh.
  Con số latency dưới tải đồng thời là việc của giai đoạn xác thực & độ tin cậy.
- Các con số này đo trên **Docker trên Windows**, không phải trên phần cứng
  production. Chúng dùng để so sánh ba kế hoạch với nhau, không phải để báo latency
  của hệ thống.

## Kiểm chứng ROLLBACK

```text
 doc_chunks | index_con
------------+-----------
         16 |         1
```

Sau thí nghiệm, corpus vẫn 16 dòng và index vẫn còn. Thử một thay đổi có hậu quả
trong transaction rồi `ROLLBACK` là cách giữ dữ liệu gốc mà vẫn có số đo thật.
