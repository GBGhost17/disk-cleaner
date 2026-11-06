"""
Giao diện dòng lệnh cho disk-cleaner.

Lệnh:
    python -m cli.main scan              # Quét, hiển thị bảng
    python -m cli.main scan --verbose    # Hiển thị cả mục bị skip và lý do
    python -m cli.main clean --dry-run   # Xem trước sẽ xóa gì
    python -m cli.main clean             # Xóa thật, có xác nhận y/N
    python -m cli.main clean --yes       # Xóa thật, bỏ qua xác nhận
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Thêm thư mục gốc vào sys.path để import core khi chạy trực tiếp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.actions import ActionResult, ActionStatus, execute_targets
from core.config import load_targets
from core.logger import get_logger, log_action_results, log_scan_results
from core.scanner import ScanResult, scan_targets, summarize


def _fmt_gb(n_bytes: int) -> str:
    return f"{n_bytes / (1024 ** 3):.2f} GB"


def _print_scan_table(results: list[ScanResult], verbose: bool = False) -> None:
    """In bảng kết quả quét."""
    print()
    print(f"{'ID':<32} {'TOTAL':>10} {'RECLAIM':>10} {'FILES':>8} {'STATUS':<12}")
    print("-" * 76)

    for r in results:
        status = "OK" if r.exists and not r.error else ("MISSING" if not r.exists else "ERROR")
        reclaim = _fmt_gb(r.estimated_reclaimable) if r.is_reclaimable else "-"
        print(
            f"{r.target.id:<32} {_fmt_gb(r.total_bytes):>10} {reclaim:>10} "
            f"{r.file_count:>8} {status:<12}"
        )
        if verbose and r.error:
            print(f"    └─ {r.error}")

    print("-" * 76)


def _print_summary(results: list[ScanResult]) -> None:
    """In tổng hợp theo safety."""
    s = summarize(results)
    print()
    print("TỔNG HỢP:")
    print(f"  Tổng dung lượng quét:        {_fmt_gb(s['total_bytes'])}")
    print(f"  Có thể giải phóng ước tính/tiềm năng: {_fmt_gb(s['estimated_reclaimable'])}")
    print()
    for safety, data in s["by_safety"].items():
        if data["count"] > 0:
            print(
                f"  {safety.value:<10} {data['count']:>2} mục  "
                f"reclaimable={_fmt_gb(data['reclaimable']):>10}  "
                f"total={_fmt_gb(data['bytes']):>10}"
            )
    if s["errors"]:
        print(f"  Lỗi: {s['errors']} mục")
    print()


def _print_action_results(results: list[ActionResult], dry_run: bool) -> None:
    """In kết quả thực thi hành động."""
    mode = "DRY-RUN" if dry_run else "THỰC THI"
    print()
    print(f"KẾT QUẢ ({mode}):")
    print("-" * 76)

    total_reclaimed = 0
    total_planned = 0
    for r in results:
        total_reclaimed += r.reclaimed_bytes
        total_planned += r.planned_bytes
        status_icon = {
            ActionStatus.PLANNED: "○",
            ActionStatus.EXECUTED: "✓",
            ActionStatus.SKIPPED: "→",
            ActionStatus.REFUSED: "✗",
            ActionStatus.PARTIAL: "~",
            ActionStatus.FAILED: "✗",
        }.get(r.status, "?")
        print(f"  {status_icon} {r.target.id:<32} {r.message}")
        for err in r.errors[:3]:
            print(f"      └─ {err}")
        if len(r.errors) > 3:
            print(f"      └─ ... và {len(r.errors) - 3} lỗi khác")

    print("-" * 76)
    print(f"  Tổng dự kiến:  {_fmt_gb(total_planned)}")
    print(f"  Tổng giải phóng: {_fmt_gb(total_reclaimed)}")
    print()


def cmd_scan(args: argparse.Namespace) -> int:
    """Lệnh scan: quét và hiển thị."""
    logger = get_logger()
    targets, skipped = load_targets(only_valid=not args.verbose)

    if not targets:
        print("Không có target hợp lệ nào. Kiểm tra config/targets.*.json")
        return 1

    results = scan_targets(targets)
    _print_scan_table(results, verbose=args.verbose)
    _print_summary(results)
    log_scan_results(results, logger)

    if args.verbose and skipped:
        print("MỤC BỊ SKIP:")
        for t, reason in skipped:
            print(f"  - {t.id}: {reason}")
        print()

    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    """Lệnh clean: xóa (có dry-run mặc định nếu không có --yes)."""
    logger = get_logger()
    targets, _ = load_targets(only_valid=True)

    if not targets:
        print("Không có target hợp lệ nào.")
        return 1

    # Bước 1: luôn chạy dry-run trước để hiển thị kế hoạch
    print("\n[1/2] Đang lên kế hoạch (dry-run)...")
    dry_results = execute_targets(targets, dry_run=True)
    _print_action_results(dry_results, dry_run=True)
    log_action_results(dry_results, dry_run=True, logger=logger)

    # Nếu người dùng chỉ muốn dry-run
    if args.dry_run:
        print("Đã chạy dry-run. Không có tệp nào bị xóa.")
        print("Để xóa thật, chạy lại không có --dry-run (sẽ hỏi xác nhận).")
        return 0

    # Bước 2: xác nhận
    actionable = [
        r for r in dry_results
        if r.planned_bytes > 0 and r.status == ActionStatus.PLANNED
    ]
    if not actionable:
        print("Không có gì để xóa (tất cả đều 0 byte hoặc bị skip).")
        return 0

    total = sum(r.planned_bytes for r in actionable)
    if not args.yes:
        print(f"\nSẽ xóa {len(actionable)} mục, tổng cộng {_fmt_gb(total)}.")
        answer = input("Tiếp tục? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Đã hủy. Không có tệp nào bị xóa.")
            return 0

    # Bước 3: xóa thật
    print("\n[2/2] Đang xóa...")
    real_results = execute_targets(targets, dry_run=False)
    _print_action_results(real_results, dry_run=False)
    log_action_results(real_results, dry_run=False, logger=logger)

    print("Hoàn tất. Kiểm tra log trong logs/ để xem chi tiết.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="disk-cleaner",
        description="Công cụ dọn dẹp ổ đĩa Windows (CLI).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Quét dung lượng các mục tiêu")
    p_scan.add_argument(
        "--verbose", "-v", action="store_true",
        help="Hiển thị cả mục bị skip và lý do",
    )
    p_scan.set_defaults(func=cmd_scan)

    p_clean = sub.add_parser(
        "clean",
        help="Dọn dẹp: luôn chạy dry-run trước, hiển thị kế hoạch, hỏi xác nhận, rồi xóa thật",
    )
    p_clean.add_argument(
        "--dry-run", action="store_true",
        help="Chỉ xem trước, không xóa",
    )
    p_clean.add_argument(
        "--yes", "-y", action="store_true",
        help="Bỏ qua xác nhận (dùng cẩn thận)",
    )
    p_clean.set_defaults(func=cmd_clean)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())