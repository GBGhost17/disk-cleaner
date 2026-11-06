"""Text content for the CLI help command."""

CLI_HELP_TEXT = """
DISK CLEANER CLI GUIDE

Usage:
    python -m cli.main <command> [options]

Commands:
    scan        Scan target sizes
    clean       Clean targets (dry-run first, then confirmation)
    help        Show this guide

Options for 'scan':
    --verbose, -v   Show skipped targets and reasons
                    (useful for config debugging)

Options for 'clean':
    --dry-run       Preview only, do not delete
    --yes, -y       Skip confirmation (use with caution)

Examples:
    # Scan and view size table
    python -m cli.main scan

    # Scan with verbose output, including skipped targets
    python -m cli.main scan --verbose

    # Preview cleanup plan (safe, no deletion)
    python -m cli.main clean --dry-run

    # Execute cleanup with y/N confirmation
    python -m cli.main clean

    # Execute cleanup and skip confirmation (automation/script)
    python -m cli.main clean --yes

Safety principles:
    - Always run dry-run before real deletion.
    - Only delete targets marked safety=safe with action=delete_contents/delete_folder.
    - Never delete protected system locations (Windows, Program Files, ProgramData).
    - Skip locked files (logged, no crash).
    - All actions are logged to logs/YYYY-MM-DD.log.

Configuration:
    Targets are defined in config/targets.default.json (shared)
    and config/targets.local.json (local/private).
"""