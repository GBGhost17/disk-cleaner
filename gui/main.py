"""
Giao diện đồ họa cho disk-cleaner, dùng Tkinter.
Chia sẻ cùng lõi core với CLI.

Quy tắc checkbox:
- Chỉ tick được khi: safety == safe VÀ action là delete_contents/delete_folder.
- Tick sẵn nếu thêm điều kiện reclaimable > 0.
- caution / dangerous: checkbox disabled (hiển thị —).
"""
from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.actions import ActionResult, ActionStatus, execute_targets
from core.config import load_targets
from core.logger import get_logger, log_action_results, log_scan_results
from core.models import Action, Safety, Target
from core.scanner import ScanResult, scan_targets, summarize


CHECKED = "☑"
UNCHECKED = "☐"
DISABLED = "—"


class DiskCleanerGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Disk Cleaner")
        self.root.geometry("1100x750")

        self.logger = get_logger()
        self.targets: list[Target] = []
        self.scan_results: dict[str, ScanResult] = {}
        self.checked: set[str] = set()

        self._build_ui()

    def _build_ui(self) -> None:
        toolbar = ttk.Frame(self.root, padding=6)
        toolbar.pack(fill=tk.X)

        ttk.Button(toolbar, text="Scan", command=self.on_scan).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Chọn tất cả", command=self.on_select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Bỏ chọn tất cả", command=self.on_clear_all).pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=8)
        ttk.Button(toolbar, text="Clean (Dry-run)", command=self.on_clean_dry).pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="Clean (Execute)", command=self.on_clean_execute).pack(side=tk.LEFT, padx=2)

        columns = ("check", "id", "total", "reclaim", "files", "safety", "action", "note")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings", height=20)
        headings = {
            "check": ("Chọn", 60),
            "id": ("ID", 200),
            "total": ("Total", 90),
            "reclaim": ("Reclaimable", 100),
            "files": ("Files", 70),
            "safety": ("Safety", 80),
            "action": ("Action", 120),
            "note": ("Ghi chú", 260),
        }
        for col, (text, width) in headings.items():
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=tk.W)

        self.tree.tag_configure("caution", foreground="#888888")
        self.tree.tag_configure("dangerous", foreground="#cc0000")
        self.tree.tag_configure("reclaimable", background="#f0fff0")

        self.tree.bind("<Button-1>", self.on_tree_click)

        vsb = ttk.Scrollbar(self.root, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=6)
        vsb.place(in_=self.tree, relx=1.0, rely=0.0, relheight=1.0, anchor="ne")

        self.status_var = tk.StringVar(value="Nhấn Scan để bắt đầu.")
        ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W).pack(
            fill=tk.X, side=tk.BOTTOM
        )

        log_frame = ttk.LabelFrame(self.root, text="Log", padding=4)
        log_frame.pack(fill=tk.BOTH, side=tk.BOTTOM, padx=6, pady=4)
        self.log_text = tk.Text(log_frame, height=10, wrap=tk.WORD, state=tk.DISABLED)
        log_scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    # ---------- Helpers ----------

    def _fmt_gb(self, n_bytes: int) -> str:
        return f"{n_bytes / (1024 ** 3):.2f} GB"

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _can_check(self, target: Target) -> bool:
        """Chỉ safe + action xóa được mới cho tick."""
        if target.safety != Safety.SAFE:
            return False
        if target.action not in (Action.DELETE_CONTENTS, Action.DELETE_FOLDER):
            return False
        return True

    def _is_actionable(self, target: Target, result: ScanResult | None) -> bool:
        """Có thể tick sẵn: đủ điều kiện tick + có dữ liệu để xóa."""
        if not self._can_check(target):
            return False
        if result is None:
            return False
        return result.estimated_reclaimable > 0

    # ---------- Scan ----------

    def on_scan(self) -> None:
        self.status_var.set("Đang quét...")
        self.root.update_idletasks()

        self.tree.delete(*self.tree.get_children())
        self.scan_results.clear()
        self.checked.clear()

        targets, skipped = load_targets(only_valid=True)

        # Chặn duplicate id ở tầng dữ liệu
        seen_ids: set[str] = set()
        unique_targets: list[Target] = []
        for t in targets:
            if t.id in seen_ids:
                self._append_log(f"CẢNH BÁO: trùng id '{t.id}', bỏ qua mục thứ hai.")
                continue
            seen_ids.add(t.id)
            unique_targets.append(t)

        self.targets = unique_targets

        if not self.targets:
            self.status_var.set("Không có target hợp lệ nào.")
            self._append_log("Không có target hợp lệ nào. Kiểm tra config/targets.*.json")
            return

        results = scan_targets(self.targets)
        log_scan_results(results, self.logger)

        for r in results:
            self.scan_results[r.target.id] = r

        inserted = 0
        for r in results:
            t = r.target
            if self._is_actionable(t, r):
                self.checked.add(t.id)

            check_mark = self._check_mark_for(t)
            reclaim = self._fmt_gb(r.estimated_reclaimable) if r.is_reclaimable else "-"
            tags = ()
            if t.safety == Safety.CAUTION:
                tags = ("caution",)
            elif t.safety == Safety.DANGEROUS:
                tags = ("dangerous",)
            elif r.is_reclaimable:
                tags = ("reclaimable",)

            self.tree.insert(
                "", tk.END,
                iid=t.id,
                values=(
                    check_mark,
                    t.id,
                    self._fmt_gb(r.total_bytes),
                    reclaim,
                    r.file_count,
                    t.safety.value,
                    t.action.value,
                    t.note,
                ),
                tags=tags,
            )
            inserted += 1

        s = summarize(results)
        self.status_var.set(
            f"Quét xong: {inserted} mục, tổng {self._fmt_gb(s['total_bytes'])}, "
            f"có thể giải phóng {self._fmt_gb(s['estimated_reclaimable'])}."
        )
        self._append_log(self.status_var.get())
        if skipped:
            self._append_log(f"Có {len(skipped)} mục bị skip (không tồn tại hoặc không hợp lệ).")

    def _check_mark_for(self, target: Target) -> str:
        if not self._can_check(target):
            return DISABLED
        return CHECKED if target.id in self.checked else UNCHECKED

    # ---------- Checkbox ----------

    def on_tree_click(self, event: tk.Event) -> None:
        region = self.tree.identify("region", event.x, event.y)
        if region != "cell":
            return
        column = self.tree.identify_column(event.x)
        if column != "#1":
            return
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        target = next((t for t in self.targets if t.id == row_id), None)
        if target is None or not self._can_check(target):
            return

        if target.id in self.checked:
            self.checked.discard(target.id)
        else:
            self.checked.add(target.id)
        self._refresh_check_cell(target.id)

    def _refresh_check_cell(self, target_id: str) -> None:
        target = next((t for t in self.targets if t.id == target_id), None)
        if target is None:
            return
        values = list(self.tree.item(target_id, "values"))
        values[0] = self._check_mark_for(target)
        self.tree.item(target_id, values=values)

    def on_select_all(self) -> None:
        for t in self.targets:
            r = self.scan_results.get(t.id)
            if self._is_actionable(t, r):
                self.checked.add(t.id)
                self._refresh_check_cell(t.id)

    def on_clear_all(self) -> None:
        self.checked.clear()
        for t in self.targets:
            self._refresh_check_cell(t.id)

    # ---------- Clean ----------

    def _selected_targets(self) -> list[Target]:
        return [t for t in self.targets if t.id in self.checked]

    def on_clean_dry(self) -> None:
        selected = self._selected_targets()
        if not selected:
            messagebox.showinfo("Dry-run", "Chưa chọn mục nào.")
            return
        self.status_var.set("Đang chạy dry-run...")
        self.root.update_idletasks()
        results = execute_targets(selected, dry_run=True)
        log_action_results(results, dry_run=True, logger=self.logger)
        self._show_action_results(results, dry_run=True)

    def on_clean_execute(self) -> None:
        selected = self._selected_targets()
        if not selected:
            messagebox.showinfo("Clean", "Chưa chọn mục nào.")
            return

        self.status_var.set("Đang lên kế hoạch...")
        self.root.update_idletasks()

        dry = execute_targets(selected, dry_run=True)
        actionable = [r for r in dry if r.status == ActionStatus.PLANNED and r.planned_bytes > 0]
        if not actionable:
            messagebox.showinfo("Clean", "Không có gì để xóa trong các mục đã chọn.")
            self.status_var.set("Không có gì để xóa.")
            return

        total = sum(r.planned_bytes for r in actionable)
        detail = "\n".join(f"  - {r.target.id}: {self._fmt_gb(r.planned_bytes)}" for r in actionable)
        confirm = messagebox.askyesno(
            "Xác nhận xóa",
            f"Sẽ xóa {len(actionable)} mục, tổng {self._fmt_gb(total)}:\n\n{detail}\n\nTiếp tục?",
            icon="warning",
        )
        if not confirm:
            self._append_log("Đã hủy xóa.")
            self.status_var.set("Đã hủy.")
            return

        self.status_var.set("Đang xóa...")
        self.root.update_idletasks()

        real = execute_targets(selected, dry_run=False)
        log_action_results(real, dry_run=False, logger=self.logger)
        self._show_action_results(real, dry_run=False)

        self.on_scan()

    def _show_action_results(self, results: list[ActionResult], dry_run: bool) -> None:
        mode = "DRY-RUN" if dry_run else "THỰC THI"
        self._append_log(f"--- KẾT QUẢ ({mode}) ---")
        total_reclaimed = 0
        total_planned = 0
        for r in results:
            total_reclaimed += r.reclaimed_bytes
            total_planned += r.planned_bytes
            self._append_log(f"  [{r.status.value}] {r.target.id}: {r.message}")
            for err in r.errors[:3]:
                self._append_log(f"      └─ {err}")
            if len(r.errors) > 3:
                self._append_log(f"      └─ ... và {len(r.errors) - 3} lỗi khác")
        self._append_log(
            f"  Tổng dự kiến: {self._fmt_gb(total_planned)} | "
            f"Tổng giải phóng: {self._fmt_gb(total_reclaimed)}"
        )
        self.status_var.set(
            f"{mode}: dự kiến {self._fmt_gb(total_planned)}, "
            f"giải phóng {self._fmt_gb(total_reclaimed)}."
        )


def main() -> None:
    root = tk.Tk()
    DiskCleanerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()