"""Command-line interface for disk-cleaner."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to sys.path so core can be imported when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.actions import ActionResult, ActionStatus, execute_targets
from core.config import load_targets
from core.logger import get_logger, log_action_results, log_scan_results
from core.scanner import ScanResult, scan_targets, summarize
from .help_text import CLI_HELP_TEXT


def _fmt_gb(n_bytes: int) -> str:
    return f"{n_bytes / (1024 ** 3):.2f} GB"


def _print_scan_table(results: list[ScanResult], verbose: bool = False) -> None:
    """Print scan results table."""
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
    """Print summary grouped by safety level."""
    s = summarize(results)
    print()
    print("SUMMARY:")
    print(f"  Total scanned size:               {_fmt_gb(s['total_bytes'])}")
    print(f"  Estimated/potential reclaimable:  {_fmt_gb(s['estimated_reclaimable'])}")
    print()
    for safety, data in s["by_safety"].items():
        if data["count"] > 0:
            print(
                f"  {safety.value:<10} {data['count']:>2} mục  "
                f"reclaimable={_fmt_gb(data['reclaimable']):>10}  "
                f"total={_fmt_gb(data['bytes']):>10}"
            )
    if s["errors"]:
        print(f"  Errors: {s['errors']} targets")
    print()


def _print_action_results(results: list[ActionResult], dry_run: bool) -> None:
    """Print action execution results."""
    mode = "DRY-RUN" if dry_run else "EXECUTE"
    print()
    print(f"RESULTS ({mode}):")
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
        if r.skipped_locked:
            print(f"      └─ Skipped {r.skipped_locked} file(s) currently in use")
        for err in r.errors[:3]:
            print(f"      └─ {err}")
        if len(r.errors) > 3:
            print(f"      └─ ... and {len(r.errors) - 3} more errors")

    print("-" * 76)
    print(f"  Total planned:    {_fmt_gb(total_planned)}")
    print(f"  Total reclaimed:  {_fmt_gb(total_reclaimed)}")
    print()


def cmd_scan(args: argparse.Namespace) -> int:
    """Scan command: scan and display targets."""
    logger = get_logger()
    targets, skipped = load_targets(only_valid=not args.verbose)

    if not targets:
        print("No valid targets found. Check config/targets.*.json")
        return 1

    results = scan_targets(targets)
    _print_scan_table(results, verbose=args.verbose)
    _print_summary(results)
    log_scan_results(results, logger)

    if args.verbose and skipped:
        print("SKIPPED TARGETS:")
        for t, reason in skipped:
            print(f"  - {t.id}: {reason}")
        print()

    return 0


def cmd_clean(args: argparse.Namespace) -> int:
    """Clean command: dry-run first, then confirm before execution."""
    logger = get_logger()
    targets, _ = load_targets(only_valid=True)

    if not targets:
        print("No valid targets found.")
        return 1

    # Step 1: always run dry-run first to show the plan
    print("\n[1/2] Building plan (dry-run)...")
    dry_results = execute_targets(targets, dry_run=True)
    _print_action_results(dry_results, dry_run=True)
    log_action_results(dry_results, dry_run=True, logger=logger)

    # User requested dry-run only
    if args.dry_run:
        print("Dry-run completed. No files were deleted.")
        print("To execute deletion, rerun without --dry-run (confirmation required).")
        return 0

    # Step 2: confirmation
    actionable = [
        r for r in dry_results
        if r.planned_bytes > 0 and r.status == ActionStatus.PLANNED
    ]
    if not actionable:
        print("Nothing to clean (all targets are 0 bytes or skipped).")
        return 0

    total = sum(r.planned_bytes for r in actionable)
    if not args.yes:
        print(f"\nAbout to clean {len(actionable)} target(s), total {_fmt_gb(total)}.")
        answer = input("Continue? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Canceled. No files were deleted.")
            return 0

    # Step 3: execute
    print("\n[2/2] Cleaning...")
    real_results = execute_targets(targets, dry_run=False)
    _print_action_results(real_results, dry_run=False)
    log_action_results(real_results, dry_run=False, logger=logger)

    print("Done. Check logs/ for details.")
    return 0

def cmd_help(args: argparse.Namespace) -> int:
    """Help command: print detailed usage guide."""
    print(CLI_HELP_TEXT)
    return 0

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="disk-cleaner",
        description="Windows disk cleanup tool (CLI). Safe defaults with dry-run and logging.",
        epilog="Run 'python -m cli.main help' for detailed guide and examples.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Scan command
    p_scan = sub.add_parser("scan", help="Scan target sizes")
    p_scan.add_argument(
        "--verbose", "-v", action="store_true",
        help="Show skipped targets and reasons",
    )
    p_scan.set_defaults(func=cmd_scan)

    # Clean command
    p_clean = sub.add_parser(
        "clean",
        help="Clean targets: always dry-run first, then confirm before execution",
    )
    p_clean.add_argument(
        "--dry-run", action="store_true",
        help="Preview only, do not delete",
    )
    p_clean.add_argument(
        "--yes", "-y", action="store_true",
        help="Skip confirmation (use with caution)",
    )
    p_clean.set_defaults(func=cmd_clean)

    # Help command
    p_help = sub.add_parser("help", help="Show detailed usage guide")
    p_help.set_defaults(func=cmd_help)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())