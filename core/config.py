"""
Đọc và gộp cấu hình từ targets.default.json và targets.local.json.
Không thực hiện xóa — chỉ đọc, gộp, kiểm tra hợp lệ.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Action, Safety, Target, validate_target
import sys

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG = BASE_DIR / "config" / "targets.default.json"
LOCAL_CONFIG = BASE_DIR / "config" / "targets.local.json"


def _load_json(path: Path) -> list[dict]:
    """Đọc file JSON, trả về danh sách target thô. Trả về rỗng nếu file không tồn tại."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "targets" not in data:
        raise ValueError(f"File cấu hình không hợp lệ (thiếu 'targets'): {path}")
    targets = data["targets"]
    if not isinstance(targets, list):
        raise ValueError(f"'targets' phải là list: {path}")
    return targets


def _parse_target(raw: dict) -> Target:
    """Chuyển dict thô thành Target. Raise ValueError nếu thiếu trường bắt buộc."""
    required = ("id", "path", "category", "safety", "action")
    for key in required:
        if key not in raw:
            raise ValueError(f"Target thiếu trường '{key}': {raw}")

    try:
        safety = Safety(raw["safety"])
    except ValueError as e:
        raise ValueError(f"Safety không hợp lệ '{raw['safety']}' trong target '{raw['id']}'") from e

    try:
        action = Action(raw["action"])
    except ValueError as e:
        raise ValueError(f"Action không hợp lệ '{raw['action']}' trong target '{raw['id']}'") from e

    return Target(
        id=raw["id"],
        path=raw["path"],
        category=raw["category"],
        safety=safety,
        action=action,
        note=raw.get("note", ""),
    )


def load_targets(
    include_local: bool = True,
    only_valid: bool = True,
) -> tuple[list[Target], list[tuple[Target, str]]]:
    """
    Đọc và gộp cấu hình.

    - include_local: nếu True, gộp thêm targets.local.json (local ghi đè default theo id).
    - only_valid: nếu True, bỏ qua các target không vượt qua validate_target().

    Trả về (valid_targets, skipped) — skipped là danh sách (target, lý do) bị bỏ.
    """
    merged: dict[str, Target] = {}

    for raw in _load_json(DEFAULT_CONFIG):
        target = _parse_target(raw)
        merged[target.id] = target

    if include_local:
        for raw in _load_json(LOCAL_CONFIG):
            target = _parse_target(raw)
            merged[target.id] = target  # local ghi đè default nếu trùng id

    valid: list[Target] = []
    skipped: list[tuple[Target, str]] = []

    for target in merged.values():
        ok, message = validate_target(target)
        if ok:
            valid.append(target)
        elif not only_valid:
            skipped.append((target, message))
        # Nếu only_valid=True và target không hợp lệ: bỏ qua hoàn toàn, không append vào đâu cả.

    return valid, skipped


def get_target_by_id(target_id: str, include_local: bool = True) -> Target | None:
    """Tìm target theo id. Trả về None nếu không có."""
    valid, _ = load_targets(include_local=include_local, only_valid=False)
    for target in valid:
        if target.id == target_id:
            return target
    return None