# Sổ Tay Kinh Nghiệm Thực Chiến 2 (Enterprise AI Decision Platform)

Tài liệu đúc kết các bài học kỹ thuật thực tế, mẹo thiết kế hệ thống và câu hỏi phỏng vấn đắt giá trong quá trình xây dựng dự án.

---

## 1. So sánh `Enum` vs `Literal` (Khi nào dùng cái nào?)

| Tiêu chí | `Literal` (từ thư viện `typing`) | `StrEnum` / `Enum` (từ thư viện `enum`) |
|---|---|---|
| **Cách viết** | `role: Literal["employee", "manager"]` *(ngắn gọn đúng 1 dòng)* | Phải khai báo riêng `class Role(StrEnum): ...` |
| **Phạm vi sử dụng** | **Nội bộ, cục bộ**: Dùng nhanh cho 1 class / 1 hàm duy nhất. | **Toàn hệ thống**: Dùng chung cho nhiều file (Schemas, DB, Scope, Tests...). |
| **Bảo trì khi mở rộng** | Khó: Thêm role mới phải copy-paste sửa ở từng file. | Dễ: Sửa đúng 1 chỗ trong class `Role`, cả dự án tự cập nhật theo. |
| **Swagger UI (`/docs`)** | Hiện dạng text box kiểm tra lỗi. | Tự động sinh ra **Menu thả xuống (Dropdown)** cho tester bấm chọn cực đẹp. |

> 💡 **Quy tắc vàng thực chiến**:
> - Dùng **`Literal`** khi chỉ kiểm tra tạm thời ở đúng 1 chỗ nội bộ, không ai dùng lại.
> - Dùng **`StrEnum`** khi giá trị đó là nghiệp vụ cốt lõi của công ty (Chức vụ `Role`, Phòng ban `Department`, Trạng thái `Status`...).

---
