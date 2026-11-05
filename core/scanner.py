"""
Quét dung lượng thư mục cho từng Target.
Chỉ đọc — không có bất kỳ lệnh xóa nào trong module này.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .models import Action, Safety, Target


# Quy tắc ước tính dung lượng có thể giải phóng thực tế.
# Chỉ những action thực sự xóa mới có estimated_reclaimable > 0.
_RECLAIMABLE_ACTIONS = {Action.DELETE_CONTENTS, Action.DELETE_FOLDER}


@dataclass(frozen=True)
class ScanResult:
    """Kết quả quét một target."""
    target: Target
    resolved_path: Path
    exists: bool
    total_bytes: int
    file_count: int
    dir_count: int
    error: str | None = None

    @property
    def total_mb(self) -> float:
        return round(self.total_bytes / (1024 * 1024), 2)

    @property
    def total_gb(self) -> float:
        return round(self.total_bytes / (1024 * 1024 * 1024), 2)

    @property
    def estimated_reclaimable(self) -> int:
        """
        Dung lượng ước tính có thể giải phóng thực tế.
        Chỉ > 0 khi action thực sự xóa (delete_contents / delete_folder).
        Với dism_cleanup, manual_review, never_touch: trả về 0.
        """
        if self.target.action in _RECLAIMABLE_ACTIONS:
            return self.total_bytes
        return 0

    @property
    def estimated_reclaimable_gb(self) -> float:
        return round(self.estimated_reclaimable / (1024 * 1024 * 1024), 2)

    @property
    def is_reclaimable(self) -> bool:
        """True nếu có thể giải phóng dung lượng (dù chỉ một phần)."""
        return self.estimated_reclaimable > 0


def _scan_path(root: Path) -> tuple[int, int, int, str | None]:
    """
    Duyệt đệ quy root, trả về (total_bytes, file_count, dir_count, error).
    Bỏ qua tệp/thư mục không đọc được thay vì crash.
    dir_count là tổng số thư mục đã duyệt (không phải số thư mục con trực tiếp).
    """
    total_bytes = 0
    file_count = 0
    dir_count = 0

    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=None):
            dir_count += 1  # đếm chính thư mục hiện tại
            for name in filenames:
                fp = Path(dirpath) / name
                try:
                    st = fp.lstat()
                    total_bytes += st.st_size
                    file_count += 1
                except (OSError, PermissionError):
                    continue
    except (OSError, PermissionError) as e:
        return total_bytes, file_count, dir_count, str(e)

    return total_bytes, file_count, dir_count, None


def scan_target(target: Target) -> ScanResult:
    """
    Quét một target. Không xóa gì cả.
    Nếu đường dẫn không tồn tại, trả về exists=False, total_bytes=0.
    """
    resolved = target.resolved_path()

    if not resolved.exists():
        return ScanResult(
            target=target,
            resolved_path=resolved,
            exists=False,
            total_bytes=0,
            file_count=0,
            dir_count=0,
            error="Đường dẫn không tồn tại",
        )

    if resolved.is_file():
        try:
            size = resolved.lstat().st_size
            return ScanResult(
                target=target,
                resolved_path=resolved,
                exists=True,
                total_bytes=size,
                file_count=1,
                dir_count=0,
            )
        except OSError as e:
            return ScanResult(
                target=target,
                resolved_path=resolved,
                exists=True,
                total_bytes=0,
                file_count=0,
                dir_count=0,
                error=str(e),
            )

    total_bytes, file_count, dir_count, error = _scan_path(resolved)
    return ScanResult(
        target=target,
        resolved_path=resolved,
        exists=True,
        total_bytes=total_bytes,
        file_count=file_count,
        dir_count=dir_count,
        error=error,
    )


def scan_targets(targets: list[Target]) -> list[ScanResult]:
    """Quét nhiều target, trả về danh sách kết quả theo thứ tự đầu vào."""
    return [scan_target(t) for t in targets]


def summarize(results: list[ScanResult]) -> dict:
    """
    Tổng hợp kết quả quét.

    Trả về dict:
    {
        'total_bytes': int,              # tổng kích thước tất cả target
        'estimated_reclaimable': int,    # tổng dung lượng thực sự có thể giải phóng
        'by_safety': {
            Safety.SAFE: {'bytes': int, 'reclaimable': int, 'count': int},
            Safety.CAUTION: {...},
            Safety.DANGEROUS: {...},
        },
        'by_action': {Action: {'bytes': int, 'reclaimable': int, 'count': int}},
        'errors': int,
    }
    """
    total_bytes = 0
    total_reclaimable = 0

    by_safety: dict[Safety, dict] = {
        Safety.SAFE: {"bytes": 0, "reclaimable": 0, "count": 0},
        Safety.CAUTION: {"bytes": 0, "reclaimable": 0, "count": 0},
        Safety.DANGEROUS: {"bytes": 0, "reclaimable": 0, "count": 0},
    }
    by_action: dict[Action, dict] = {}

    errors = 0

    for r in results:
        total_bytes += r.total_bytes
        total_reclaimable += r.estimated_reclaimable

        by_safety[r.target.safety]["bytes"] += r.total_bytes
        by_safety[r.target.safety]["reclaimable"] += r.estimated_reclaimable
        by_safety[r.target.safety]["count"] += 1

        if r.target.action not in by_action:
            by_action[r.target.action] = {"bytes": 0, "reclaimable": 0, "count": 0}
        by_action[r.target.action]["bytes"] += r.total_bytes
        by_action[r.target.action]["reclaimable"] += r.estimated_reclaimable
        by_action[r.target.action]["count"] += 1

        if r.error:
            errors += 1

    return {
        "total_bytes": total_bytes,
        "estimated_reclaimable": total_reclaimable,
        "by_safety": by_safety,
        "by_action": by_action,
        "errors": errors,
    }