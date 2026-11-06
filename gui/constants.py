"""Các hằng số và cấu hình tĩnh cho GUI."""

CHECKED = "☑"
UNCHECKED = "☐"
DISABLED = "—"

WINDOW_TITLE = "Disk Cleaner"
WINDOW_GEOMETRY = "850x550"
WINDOW_MIN_SIZE = (700, 450)

# Định nghĩa cột cho Treeview: (ID, Tiêu đề, Độ rộng)
TREE_COLUMNS = [
    ("check", "Chọn", 50),
    ("id", "ID", 160),
    ("total", "Total", 80),
    ("reclaim", "Reclaimable", 90),
    ("files", "Files", 60),
    ("safety", "Safety", 70),
    ("action", "Action", 110),
    ("note", "Ghi chú", 200),
]

# Màu sắc cho các tag trong Treeview
COLOR_CAUTION = "#888888"
COLOR_DANGEROUS = "#cc0000"
COLOR_RECLAIMABLE_BG = "#f0fff0"