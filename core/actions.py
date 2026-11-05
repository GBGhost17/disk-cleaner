"""
Thực thi hành động xóa cho từng Target.
Đây là module duy nhất được phép xóa tệp — mọi module khác chỉ đọc.

Nguyên tắc cứng:
- validate_target() phải pass trước khi làm bất cứ điều gì.
- safety == DANGEROUS hoặc action == NEVER_TOUCH: từ chối ngay.
- dry_run=True mặc định.
- Xóa từng tệp, không dùng shutil.rmtree mù quáng.
- delete_contents giữ thư mục gốc; delete_folder xóa thư mục mục tiêu.
- Không xóa parent/ancestor của target.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from .models import (
    Action,
    Safety,
    Target,
    is_protected_root,
    is_symlink_or_junction,
    validate_target,
    is_path_within_target,
)


class ActionStatus(str, Enum):
    """Trạng thái của một lần thực thi hành động."""
    PLANNED = "planned"      # dry-run: đã lên kế hoạch, chưa xóa
    EXECUTED = "executed"    # đã xóa thành công
    SKIPPED = "skipped"      # bỏ qua do không hợp lệ / không tồn tại
    REFUSED = "refused"      # từ chối do safety/action nguy hiểm
    PARTIAL = "partial"      # xóa được một phần, có lỗi
    FAILED = "failed"        # lỗi hoàn toàn, không xóa được gì


@dataclass
class ActionResult:
    """Kết quả của một lần thực thi hành động."""
    target: Target
    status: ActionStatus
    dry_run: bool
    planned_bytes: int = 0
    reclaimed_bytes: int = 0
    deleted_files: int = 0
    failed_files: int = 0
    errors: list[str] = field(default_factory=list)
    message: str = ""

    @property
    def reclaimed_gb(self) -> float:
        return round(self.reclaimed_bytes / (1024 * 1024 * 1024), 2)

    @property
    def planned_gb(self) -> float:
        return round(self.planned_bytes / (1024 * 1024 * 1024), 2)


def _refuse(target: Target, reason: str, dry_run: bool) -> ActionResult:
    """Tạo ActionResult từ chối, dùng cho các trường hợp nguy hiểm."""
    return ActionResult(
        target=target,
        status=ActionStatus.REFUSED,
        dry_run=dry_run,
        message=reason,
    )


def _skip(target: Target, reason: str, dry_run: bool) -> ActionResult:
    """Tạo ActionResult bỏ qua, dùng cho trường hợp không hợp lệ."""
    return ActionResult(
        target=target,
        status=ActionStatus.SKIPPED,
        dry_run=dry_run,
        message=reason,
    )


def _measure_path(path: Path) -> int:
    """Đo tổng dung lượng các tệp trong path (không đệ quy symlink)."""
    total = 0
    if path.is_file():
        try:
            return path.lstat().st_size
        except OSError:
            return 0
    for dirpath, _, filenames in os.walk(path, topdown=True, onerror=None):
        for name in filenames:
            fp = Path(dirpath) / name
            try:
                total += fp.lstat().st_size
            except (OSError, PermissionError):
                continue
    return total


def _delete_file(fp: Path, dry_run: bool) -> tuple[bool, int, str | None]:
    """
    Xóa một tệp. Trả về (ok, bytes, error).
    Nếu dry_run=True, không xóa, chỉ đo.
    """
    try:
        st = fp.lstat()
        size = st.st_size
    except OSError as e:
        return False, 0, f"lstat failed: {e}"

    if dry_run:
        return True, size, None

    try:
        fp.unlink()
        return True, size, None
    except (OSError, PermissionError) as e:
        return False, 0, f"unlink failed: {e}"


def _execute_delete_contents(target: Target, resolved: Path, dry_run: bool) -> ActionResult:
    """
    Xóa toàn bộ nội dung bên trong resolved, giữ lại thư mục gốc.
    Không đệ quy vào symlink/junction con.
    """
    planned = _measure_path(resolved)
    result = ActionResult(
        target=target,
        status=ActionStatus.PLANNED if dry_run else ActionStatus.EXECUTED,
        dry_run=dry_run,
        planned_bytes=planned,
    )

    for entry in resolved.iterdir():
        # Bỏ qua symlink/junction con — không xóa theo
        if is_symlink_or_junction(entry):
            result.errors.append(f"Bỏ qua symlink/junction: {entry}")
            continue

        if entry.is_file():
            if not is_path_within_target(entry.resolve(strict=False), resolved):
                result.errors.append(f"Bỏ qua tệp ngoài target root: {entry}")
                continue
            ok, size, err = _delete_file(entry, dry_run)
            if ok:
                result.reclaimed_bytes += size
                result.deleted_files += 1
            else:
                result.failed_files += 1
                if err:
                    result.errors.append(f"{entry}: {err}")
        elif entry.is_dir():
            # Duyệt đệ quy thư mục con, xóa từng tệp
            for dirpath, dirnames, filenames in os.walk(entry, topdown=True, onerror=None):
                # Loại junction/symlink khỏi dirnames để không duyệt vào
                dirnames[:] = [
                    d for d in dirnames
                    if not is_symlink_or_junction(Path(dirpath) / d)
                ]
                for name in filenames:
                    fp = Path(dirpath) / name
                    if is_symlink_or_junction(fp):
                        result.errors.append(f"Bỏ qua symlink/junction: {fp}")
                        continue
                    if not is_path_within_target(fp.resolve(strict=False), resolved):
                        result.errors.append(f"Bỏ qua tệp ngoài target root: {fp}")
                        continue
                    ok, size, err = _delete_file(fp, dry_run)
                    if ok:
                        result.reclaimed_bytes += size
                        result.deleted_files += 1
                    else:
                        result.failed_files += 1
                        if err:
                            result.errors.append(f"{fp}: {err}")

            if not dry_run:
                # Xóa thư mục con nếu rỗng (không xóa resolved)
                try:
                    entry.rmdir()
                except OSError:
                    pass  # không rỗng, bỏ qua

    if result.failed_files > 0 and result.deleted_files > 0:
        result.status = ActionStatus.PARTIAL
    elif result.failed_files > 0 and result.deleted_files == 0:
        result.status = ActionStatus.FAILED

    result.message = (
        f"{'[DRY-RUN] ' if dry_run else ''}"
        f"Xóa {result.deleted_files} tệp, {result.reclaimed_gb} GB"
        + (f", {result.failed_files} lỗi" if result.failed_files else "")
    )
    return result


def _execute_delete_folder(target: Target, resolved: Path, dry_run: bool) -> ActionResult:
    """
    Xóa toàn bộ thư mục mục tiêu (không xóa parent/ancestor).
    Yêu cầu: resolved không phải protected root, không phải symlink.
    """
    # Lớp bảo vệ cuối: kiểm tra lại lần nữa
    if is_protected_root(resolved):
        return _refuse(target, f"Từ chối xóa thư mục gốc được bảo vệ: {resolved}", dry_run)
    if is_symlink_or_junction(resolved):
        return _refuse(target, f"Từ chối xóa symlink/junction: {resolved}", dry_run)

    planned = _measure_path(resolved)
    result = ActionResult(
        target=target,
        status=ActionStatus.PLANNED if dry_run else ActionStatus.EXECUTED,
        dry_run=dry_run,
        planned_bytes=planned,
    )

    # Duyệt và xóa từng tệp trước
    for dirpath, dirnames, filenames in os.walk(resolved, topdown=True, onerror=None):
        # Loại junction/symlink khỏi dirnames để không duyệt vào
        dirnames[:] = [
            d for d in dirnames
            if not is_symlink_or_junction(Path(dirpath) / d)
        ]
        for name in filenames:
            fp = Path(dirpath) / name
            if is_symlink_or_junction(fp):
                result.errors.append(f"Bỏ qua symlink/junction: {fp}")
                continue
            if not is_path_within_target(fp.resolve(strict=False), resolved):
                result.errors.append(f"Bỏ qua tệp ngoài target root: {fp}")
                continue
            ok, size, err = _delete_file(fp, dry_run)
            if ok:
                result.reclaimed_bytes += size
                result.deleted_files += 1
            else:
                result.failed_files += 1
                if err:
                    result.errors.append(f"{fp}: {err}")

    if not dry_run:
        rmdir_errors = 0
        # Xóa các thư mục con từ dưới lên, cuối cùng xóa resolved
        for dirpath, dirnames, filenames in os.walk(resolved, topdown=False, onerror=None):
            try:
                Path(dirpath).rmdir()
            except OSError:
                rmdir_errors += 1
        if resolved.exists():
            try:
                resolved.rmdir()
            except OSError as e:
                result.errors.append(f"Không xóa được thư mục gốc: {e}")
                rmdir_errors += 1
                if result.deleted_files == 0:
                    result.status = ActionStatus.FAILED
                    result.message = f"Không xóa được thư mục: {resolved}"
                    return result

        # Nếu có lỗi rmdir, đánh dấu PARTIAL/FAILED dù đã xóa được tệp
        if rmdir_errors > 0 and result.deleted_files > 0:
            result.status = ActionStatus.PARTIAL
        elif rmdir_errors > 0 and result.deleted_files == 0:
            result.status = ActionStatus.FAILED

    if result.failed_files > 0 and result.deleted_files > 0:
        result.status = ActionStatus.PARTIAL
    elif result.failed_files > 0 and result.deleted_files == 0:
        result.status = ActionStatus.FAILED

    result.message = (
        f"{'[DRY-RUN] ' if dry_run else ''}"
        f"Xóa thư mục {resolved.name}: {result.deleted_files} tệp, {result.reclaimed_gb} GB"
        + (f", {result.failed_files} lỗi" if result.failed_files else "")
    )
    return result


def execute_target(target: Target, dry_run: bool = True) -> ActionResult:
    """
    Thực thi hành động cho một target.

    Mặc định dry_run=True: chỉ đo và lên kế hoạch, không xóa.
    Trả về ActionResult mô tả những gì đã làm (hoặc sẽ làm).
    """
    # Lớp 1: từ chối cứng dangerous / never_touch
    if target.safety == Safety.DANGEROUS:
        return _refuse(target, f"Mục tiêu dangerous, từ chối: {target.id}", dry_run)
    if target.action == Action.NEVER_TOUCH:
        return _refuse(target, f"Action never_touch, từ chối: {target.id}", dry_run)

    # Lớp 2: validate_target() — kiểm tra tồn tại, symlink, protected root
    ok, message = validate_target(target)
    if not ok:
        return _skip(target, message, dry_run)

    resolved = target.resolved_path()

    # Lớp 3: phân nhánh theo action
    if target.action == Action.DELETE_CONTENTS:
        return _execute_delete_contents(target, resolved, dry_run)
    if target.action == Action.DELETE_FOLDER:
        return _execute_delete_folder(target, resolved, dry_run)
    if target.action == Action.DISM_CLEANUP:
        return ActionResult(
            target=target,
            status=ActionStatus.SKIPPED,
            dry_run=dry_run,
            message="DISM cleanup: chạy thủ công 'Dism.exe /Online /Cleanup-Image /StartComponentCleanup' trong PowerShell quyền admin",
        )
    if target.action == Action.MANUAL_REVIEW:
        return ActionResult(
            target=target,
            status=ActionStatus.SKIPPED,
            dry_run=dry_run,
            message=f"Cần xử lý thủ công: {target.note}",
        )

    # Không nên tới đây, nhưng phòng trường hợp
    return _refuse(target, f"Action không được hỗ trợ: {target.action}", dry_run)


def execute_targets(targets: list[Target], dry_run: bool = True) -> list[ActionResult]:
    """Thực thi nhiều target, trả về danh sách kết quả theo thứ tự đầu vào."""
    return [execute_target(t, dry_run=dry_run) for t in targets]