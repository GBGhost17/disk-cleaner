"""Nội dung hướng dẫn cho tab Help của GUI."""

HELP_CONTENT = """Disk Cleaner - Hướng dẫn sử dụng

1) Quy tắc an toàn
- Tool luôn ưu tiên an toàn: chỉ dọn các target hợp lệ.
- Target dangerous / never_touch sẽ bị từ chối.
- Symlink / junction và các vùng protected root sẽ bị chặn.

2) Quy trình chuẩn
- Bấm Scan để quét dung lượng.
- Chọn các mục SAFE có reclaimable > 0.
- Chạy Clean (Dry-run) để xem kế hoạch.
- Chỉ dùng Clean (Execute) khi đã kiểm tra kỹ.

3) Ý nghĩa trạng thái
- planned: đã lên kế hoạch (dry-run).
- executed: đã xóa thành công.
- skipped: bỏ qua (không hợp lệ / không áp dụng).
- refused: từ chối vì chính sách an toàn.
- partial: xóa được một phần.
- failed: thất bại.

4) Lưu ý quan trọng
- Dung lượng reclaimable hiển thị là ước tính/tiềm năng.
- Có thể khác thực tế do file đang bị khóa hoặc thiếu quyền.
- Nên đóng ứng dụng đang chạy trước khi clean để hiệu quả tốt hơn.

5) Nhật ký
- Mọi kết quả scan/clean được ghi trong thư mục logs/.
"""