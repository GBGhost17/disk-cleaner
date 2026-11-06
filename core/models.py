"""
Định nghĩa kiểu dữ liệu cốt lõi cho tool.
Không chứa logic xóa — chỉ mô tả cấu trúc và kiểm tra an toàn.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class Safety(str, Enum):
    """Mức độ an toàn của một mục tiêu."""
    SAFE = "safe"            # Có thể xóa, luôn dry-run trước
    CAUTION = "caution"      # Chỉ gợi ý, không tự động xóa
    DANGEROUS = "dangerous"  # Không bao giờ động vào


class Action(str, Enum):
    """Hành động tool sẽ thực hiện với một mục tiêu."""
    DELETE_CONTENTS = "delete_contents"  # Xóa nội dung bên trong, giữ thư mục
    DELETE_FOLDER = "delete_folder"      # Xóa cả thư mục
    DISM_CLEANUP = "dism_cleanup"        # Chỉ hiển thị lệnh DISM, không tự chạy
    MANUAL_REVIEW = "manual_review"      # Chỉ hiển thị ghi chú
    NEVER_TOUCH = "never_touch"          # Bỏ qua hoàn toàn


@dataclass(frozen=True)
class Target:
    """Một mục tiêu dọn dẹp, đọc từ file cấu hình."""
    id: str
    path: str            # Đường dẫn gốc, có thể chứa biến môi trường
    category: str
    safety: Safety
    action: Action
    note: str = ""

    def resolved_path(self) -> Path:
        """Mở rộng biến môi trường và trả về Path tuyệt đối."""
        expanded = os.path.expandvars(self.path)
        return Path(expanded).resolve(strict=False)


# Ngưỡng bảo vệ: các thư mục gốc không bao giờ được phép xóa
PROTECTED_ROOTS = [
    Path("C:/Windows"),
    Path("C:/Program Files"),
    Path("C:/Program Files (x86)"),
    Path("C:/ProgramData"),
    # Path("C:/Users"),
]


def is_path_within_target(candidate: Path, target_root: Path) -> bool:
    """
    Kiểm tra candidate có nằm trong target_root hay không.
    Dùng để chặn trường hợp người dùng truyền đường dẫn tùy ý.
    """
    try:
        candidate.resolve(strict=False).relative_to(target_root.resolve(strict=False))
        return True
    except ValueError:
        return False


def is_protected_root(candidate: Path) -> bool:
    r"""
    Kiểm tra candidate có phải là thư mục gốc được bảo vệ,
    HOẶC nằm bên trong bất kỳ thư mục gốc được bảo vệ nào.
    Ví dụ: C:\Program Files\SomeApp -> True (vì nằm trong C:\Program Files).
    """
    resolved = candidate.resolve(strict=False)
    for root in PROTECTED_ROOTS:
        root_resolved = root.resolve(strict=False)
        if resolved == root_resolved or root_resolved in resolved.parents:
            return True
    return False

def is_volume_root(candidate: Path) -> bool:
    r"""Kiểm tra candidate có phải là ổ đĩa gốc không (C:\, D:\...)."""
    resolved = candidate.resolve(strict=False)
    return resolved.parent == resolved


def is_symlink_or_junction(candidate: Path) -> bool:
    """
    Kiểm tra candidate có phải symlink hoặc junction không.
    Trên Windows, os.path.islink() phát hiện symlink; junction cần kiểm tra thêm
    qua thuộc tính reparse point (dùng os.lstat và st_file_attributes).
    """
    if candidate.is_symlink():
        return True
    try:
        stat = os.lstat(candidate)
        # FILE_ATTRIBUTE_REPARSE_POINT = 0x400
        return bool(getattr(stat, "st_file_attributes", 0) & 0x400)
    except OSError:
        return False


def validate_target(target: Target) -> tuple[bool, str]:
    resolved = target.resolved_path()

    if not resolved.exists():
        return False, f"Đường dẫn không tồn tại: {resolved}"

    if is_symlink_or_junction(resolved):
        return False, f"Đường dẫn là symlink/junction, từ chối xử lý: {resolved}"

    if is_volume_root(resolved):
        return False, f"Từ chối xóa ổ đĩa gốc: {resolved}"

    if is_protected_root(resolved):
        return False, f"Đường dẫn nằm trong khu vực được bảo vệ: {resolved}"

    if target.safety == Safety.DANGEROUS:
        return False, f"Mục tiêu được đánh dấu dangerous, không xử lý: {target.id}"

    if target.action in (Action.DELETE_CONTENTS, Action.DELETE_FOLDER):
        if not resolved.is_dir():
            return False, f"Action {target.action.value} yêu cầu thư mục, nhưng target là tệp: {resolved}"

    return True, "OK"