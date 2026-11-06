"""
Giao diện đồ họa cho disk-cleaner, dùng Tkinter.
Đã sửa lỗi đơ GUI bằng cách dùng Thread cho các tác vụ nặng.
"""
from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.actions import ActionResult, ActionStatus, execute_targets
from core.config import load_targets
from core.logger import get_logger, log_action_results, log_scan_results
from core.models import Action, Safety, Target
from core.scanner import ScanResult, scan_targets, summarize

# Import các giá trị tĩnh
from .constants import (
    CHECKED, UNCHECKED, DISABLED, 
    WINDOW_TITLE, WINDOW_GEOMETRY, WINDOW_MIN_SIZE,
    TREE_COLUMNS, COLOR_CAUTION, COLOR_DANGEROUS, COLOR_RECLAIMABLE_BG
)
from .help_text import HELP_CONTENT


class DiskCleanerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(WINDOW_TITLE)
        self.root.geometry(WINDOW_GEOMETRY)
        self.root.minsize(*WINDOW_MIN_SIZE)

        self.logger = get_logger()
        self.targets: list[Target] = []
        self.scan_results: dict[str, ScanResult] = {}
        self.checked: set[str] = set()
        self.last_action_results: list[ActionResult] = []
        self.last_action_dry_run: bool = True

        self._thread_running = False
        self._thread_result = None
        self._thread_error = None

        self._build_ui()

    def _build_ui(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.main_tab = ttk.Frame(self.notebook)
        self.help_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.main_tab, text="Cleaner")
        self.notebook.add(self.help_tab, text="Help")

        self._build_main_tab()
        self._build_help_tab()

    def _build_main_tab(self) -> None:
        self.main_tab.rowconfigure(1, weight=1)
        self.main_tab.columnconfigure(0, weight=1)

        # Toolbar
        toolbar = ttk.Frame(self.main_tab, padding=6)
        toolbar.grid(row=0, column=0, sticky="ew")

        ttk.Button(toolbar, text="Scan", command=self.on_scan).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Chọn tất cả", command=self.on_select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Bỏ chọn tất cả", command=self.on_clear_all).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Clean (Dry-run)", command=self.on_clean_dry).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clean (Execute)", command=self.on_clean_execute).pack(side=tk.LEFT, padx=2)

        # Treeview
        tree_frame = ttk.Frame(self.main_tab)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)
        
        cols = [c[0] for c in TREE_COLUMNS]
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=10)
        
        for col_id, title, width in TREE_COLUMNS:
            self.tree.heading(col_id, text=title)
            self.tree.column(col_id, width=width, anchor=tk.W)

        self.tree.tag_configure("caution", foreground=COLOR_CAUTION)
        self.tree.tag_configure("dangerous", foreground=COLOR_DANGEROUS)
        self.tree.tag_configure("reclaimable", background=COLOR_RECLAIMABLE_BG)
        self.tree.bind("<Button-1>", self.on_tree_click)

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # Bottom Bar
        bottom_frame = ttk.Frame(self.main_tab)
        bottom_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 6))

        self.log_line_var = tk.StringVar(value="Sẵn sàng.")
        ttk.Label(bottom_frame, textvariable=self.log_line_var, anchor=tk.W).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self.detail_btn = ttk.Button(
            bottom_frame, text="Xem chi tiết", command=self.on_show_details, state=tk.DISABLED
        )
        self.detail_btn.pack(side=tk.RIGHT)

        # Status Bar
        self.status_var = tk.StringVar(value="Nhấn Scan để bắt đầu.")
        ttk.Label(self.main_tab, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).grid(
            row=3, column=0, sticky="ew"
        )

    def _build_help_tab(self) -> None:
        text = tk.Text(self.help_tab, wrap=tk.WORD, padx=12, pady=12)
        scroll = ttk.Scrollbar(self.help_tab, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Lấy text từ module help_text
        text.insert("1.0", HELP_CONTENT)
        text.configure(state=tk.DISABLED)

    # ---------- Helpers ----------
    def _fmt_gb(self, n_bytes: int) -> str:
        return f"{n_bytes / (1024 ** 3):.2f} GB"

    def _set_log_line(self, message: str) -> None:
        self.log_line_var.set(message)

    def _can_check(self, target: Target) -> bool:
        return target.safety == Safety.SAFE and target.action in (Action.DELETE_CONTENTS, Action.DELETE_FOLDER)

    def _is_actionable(self, target: Target, result: ScanResult | None) -> bool:
        return self._can_check(target) and result is not None and result.estimated_reclaimable > 0

    def _set_busy(self, busy: bool, status: str | None = None) -> None:
        self._thread_running = busy
        self.root.configure(cursor="watch" if busy else "")
        if status:
            self.status_var.set(status)

    def _run_background(self, worker, on_done, busy_text: str) -> None:
        if self._thread_running:
            messagebox.showinfo("Đang xử lý", "Tác vụ trước đó chưa hoàn tất.")
            return

        self._thread_result = None
        self._thread_error = None
        self._set_busy(True, busy_text)

        def _job() -> None:
            try:
                self._thread_result = worker()
            except Exception as e:  # noqa: BLE001
                self._thread_error = str(e)

        thread = threading.Thread(target=_job, daemon=True)
        thread.start()

        def _poll() -> None:
            if thread.is_alive():
                self.root.after(80, _poll)
                return
            self._set_busy(False)
            if self._thread_error:
                messagebox.showerror("Lỗi", self._thread_error)
                self.status_var.set("Có lỗi trong quá trình xử lý.")
                return
            on_done(self._thread_result)

        self.root.after(80, _poll)

    def _refresh_tree(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)

        for t in self.targets:
            r = self.scan_results.get(t.id)
            total = self._fmt_gb(r.total_bytes) if r else "-"
            reclaim = self._fmt_gb(r.estimated_reclaimable) if r else "-"
            files = str(r.file_count) if r else "-"

            check_mark = DISABLED
            if self._is_actionable(t, r):
                check_mark = CHECKED if t.id in self.checked else UNCHECKED

            tags: list[str] = []
            if t.safety == Safety.CAUTION:
                tags.append("caution")
            if t.safety == Safety.DANGEROUS:
                tags.append("dangerous")
            if r and r.estimated_reclaimable > 0:
                tags.append("reclaimable")

            self.tree.insert(
                "",
                tk.END,
                iid=t.id,
                values=(
                    check_mark,
                    t.id,
                    total,
                    reclaim,
                    files,
                    t.safety.value,
                    t.action.value,
                    t.note,
                ),
                tags=tuple(tags),
            )

    def _get_selected_targets(self) -> list[Target]:
        selected_ids = self.checked.copy()
        return [t for t in self.targets if t.id in selected_ids]

    # ---------- Scan ----------
    def on_scan(self) -> None:
        def _worker():
            targets, skipped = load_targets(only_valid=False)
            results = scan_targets(targets)
            return targets, skipped, results

        def _done(payload) -> None:
            targets, skipped, results = payload
            self.targets = targets
            self.scan_results = {r.target.id: r for r in results}
            target_by_id = {t.id: t for t in self.targets}

            # Giữ lại các mục checked còn hợp lệ sau khi scan lại
            self.checked = {
                tid for tid in self.checked
                if tid in self.scan_results
                and tid in target_by_id
                and self._is_actionable(target_by_id[tid], self.scan_results.get(tid))
            }

            self._refresh_tree()

            summary = summarize(results)
            self.status_var.set(
                f"Đã quét {len(results)} mục | "
                f"Tổng: {self._fmt_gb(summary['total_bytes'])} | "
                f"Ước tính/tiềm năng: {self._fmt_gb(summary['estimated_reclaimable'])}"
            )
            self._set_log_line(
                f"Scan xong: {len(results)} mục, lỗi: {summary['errors']}"
            )
            self.detail_btn.configure(state=tk.NORMAL)

            if skipped:
                self.logger.warning("Có %s target không hợp lệ trong config", len(skipped))
            log_scan_results(results, self.logger)

        self._run_background(_worker, _done, "Đang quét...")

    # ---------- Checkbox ----------
    def on_tree_click(self, event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        column = self.tree.identify_column(event.x)
        item = self.tree.identify_row(event.y)

        if region != "cell" or column != "#1" or not item:
            return

        target = next((t for t in self.targets if t.id == item), None)
        result = self.scan_results.get(item)
        if target is None or not self._is_actionable(target, result):
            return

        if item in self.checked:
            self.checked.remove(item)
        else:
            self.checked.add(item)

        self._refresh_tree()
        self._set_log_line(f"Đã chọn {len(self.checked)} mục.")

    def on_select_all(self) -> None:
        for t in self.targets:
            r = self.scan_results.get(t.id)
            if self._is_actionable(t, r):
                self.checked.add(t.id)
        self._refresh_tree()
        self._set_log_line(f"Đã chọn tất cả ({len(self.checked)} mục).")

    def on_clear_all(self) -> None:
        self.checked.clear()
        self._refresh_tree()
        self._set_log_line("Đã bỏ chọn tất cả.")

    # ---------- Clean ----------
    def _run_clean(self, dry_run: bool) -> None:
        selected = self._get_selected_targets()
        if not selected:
            messagebox.showinfo("Chưa chọn", "Vui lòng chọn ít nhất 1 mục SAFE để dọn.")
            return

        if not dry_run:
            answer = messagebox.askyesno(
                "Xác nhận",
                f"Bạn sắp xóa dữ liệu ở {len(selected)} mục đã chọn. Tiếp tục?",
                icon="warning",
            )
            if not answer:
                return

        def _worker():
            return execute_targets(selected, dry_run=dry_run)

        def _done(results: list[ActionResult]) -> None:
            self.last_action_results = results
            self.last_action_dry_run = dry_run
            log_action_results(results, dry_run=dry_run, logger=self.logger)

            total = sum(r.reclaimed_bytes for r in results)
            planned = sum(r.planned_bytes for r in results)

            if dry_run:
                self.status_var.set(
                    f"Dry-run xong | Dự kiến: {self._fmt_gb(planned)}"
                )
                self._set_log_line("Dry-run hoàn tất.")
            else:
                self.status_var.set(
                    f"Clean xong | Đã giải phóng: {self._fmt_gb(total)}"
                )
                self._set_log_line("Clean execute hoàn tất.")
                # Sau khi xóa thật, scan lại để cập nhật giao diện
                self.on_scan()

            self.detail_btn.configure(state=tk.NORMAL)

        title = "Đang lập kế hoạch dọn (dry-run)..." if dry_run else "Đang xóa..."
        self._run_background(_worker, _done, title)

    def on_clean_dry(self) -> None:
        self._run_clean(dry_run=True)

    def on_clean_execute(self) -> None:
        self._run_clean(dry_run=False)

    # ---------- Details ----------
    def on_show_details(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Chi tiết kết quả")
        win.geometry("760x420")

        text = tk.Text(win, wrap=tk.WORD, padx=10, pady=10)
        scroll = ttk.Scrollbar(win, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        if self.last_action_results:
            mode = "DRY-RUN" if self.last_action_dry_run else "EXECUTE"
            text.insert(tk.END, f"KẾT QUẢ CLEAN ({mode})\n")
            text.insert(tk.END, "-" * 60 + "\n")
            for r in self.last_action_results:
                text.insert(
                    tk.END,
                    f"[{r.status.value}] {r.target.id}: {r.message}\n"
                )
                for err in r.errors:
                    text.insert(tk.END, f"  - {err}\n")
            total_plan = sum(r.planned_bytes for r in self.last_action_results)
            total_real = sum(r.reclaimed_bytes for r in self.last_action_results)
            text.insert(tk.END, "\n")
            text.insert(tk.END, f"Tổng dự kiến: {self._fmt_gb(total_plan)}\n")
            text.insert(tk.END, f"Tổng giải phóng: {self._fmt_gb(total_real)}\n")
        elif self.scan_results:
            results = list(self.scan_results.values())
            s = summarize(results)
            text.insert(tk.END, "KẾT QUẢ SCAN\n")
            text.insert(tk.END, "-" * 60 + "\n")
            text.insert(tk.END, f"Tổng dung lượng: {self._fmt_gb(s['total_bytes'])}\n")
            text.insert(
                tk.END,
                f"Ước tính/tiềm năng: {self._fmt_gb(s['estimated_reclaimable'])}\n"
            )
            text.insert(tk.END, f"Số mục lỗi: {s['errors']}\n")
        else:
            text.insert(tk.END, "Chưa có dữ liệu. Hãy chạy Scan trước.\n")

        text.configure(state=tk.DISABLED)


def main() -> None:
    root = tk.Tk()
    DiskCleanerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()