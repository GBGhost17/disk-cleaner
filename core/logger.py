"""
Ghi log mọi hành động của tool vào logs/YYYY-MM-DD.log.
Không xóa gì cả — chỉ ghi.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .actions import ActionResult, ActionStatus
from .scanner import ScanResult


LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str = "disk-cleaner") -> logging.Logger:
    """
    Trả về logger ghi vào logs/YYYY-MM-DD.log.
    Tự tạo thư mục logs/ nếu chưa có.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now():%Y-%m-%d}.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # Tránh thêm handler trùng lặp nếu gọi nhiều lần
    if not any(isinstance(h, logging.FileHandler) and h.baseFilename == str(log_file)
               for h in logger.handlers):
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        logger.addHandler(handler)

    # Thêm StreamHandler để thấy log trên console (chỉ thêm một lần)
    if not any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
               for h in logger.handlers):
        stream = logging.StreamHandler()
        stream.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        stream.setLevel(logging.WARNING)  # console chỉ hiện warning trở lên
        logger.addHandler(stream)

    return logger


def log_scan_results(results: list[ScanResult], logger: logging.Logger | None = None) -> None:
    """Ghi log kết quả quét."""
    logger = logger or get_logger()
    logger.info("=" * 60)
    logger.info("SCAN RESULTS")
    total = 0
    for r in results:
        total += r.total_bytes
        logger.info(
            f"  {r.target.id}: total={r.total_gb}GB, reclaimable={r.estimated_reclaimable_gb}GB, "
            f"files={r.file_count}, dirs={r.dir_count}, exists={r.exists}, err={r.error}"
        )
    logger.info(f"  TOTAL: {round(total / 1024 / 1024 / 1024, 2)}GB")
    logger.info("=" * 60)


def log_action_results(results: list[ActionResult], dry_run: bool, logger: logging.Logger | None = None) -> None:
    """Ghi log kết quả thực thi hành động."""
    logger = logger or get_logger()
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    logger.info("=" * 60)
    logger.info(f"ACTION RESULTS ({mode})")
    total_reclaimed = 0
    total_planned = 0
    for r in results:
        total_reclaimed += r.reclaimed_bytes
        total_planned += r.planned_bytes
        logger.info(
            f"  {r.target.id}: [{r.status.value}] {r.message}"
        )
        if r.skipped_locked:
            logger.info(f"    - skipped_locked={r.skipped_locked}")
        for locked in r.locked_details:
            logger.info(f"    - LOCKED: {locked}")
        for err in r.errors:
            logger.warning(f"    - {err}")
    logger.info(f"  TOTAL planned: {round(total_planned / 1024 / 1024 / 1024, 2)}GB")
    logger.info(f"  TOTAL reclaimed: {round(total_reclaimed / 1024 / 1024 / 1024, 2)}GB")
    logger.info("=" * 60)


def log_refusal(target_id: str, reason: str, logger: logging.Logger | None = None) -> None:
    """Ghi log khi từ chối xóa một target."""
    logger = logger or get_logger()
    logger.warning(f"REFUSED {target_id}: {reason}")