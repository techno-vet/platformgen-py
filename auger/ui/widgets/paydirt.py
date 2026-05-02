"""Paydirt workflow widget for Task 174."""

from __future__ import annotations

import csv
import importlib
import json
import threading
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from auger.tools import paydirt as _paydirt
from auger.ui import icons as _icons
from auger.ui.utils import add_treeview_menu

_paydirt = importlib.reload(_paydirt)

BG = "#1e1e1e"
BG2 = "#252526"
BG3 = "#2d2d2d"
BG4 = "#333333"
FG = "#e0e0e0"
FG2 = "#888888"
ACCENT = "#007acc"
ACCENT2 = "#dcdcaa"
SUCCESS = "#4ec9b0"
ERROR = "#f44747"
WARN = "#f0c040"
DISPLAY_LIMIT = 5000
ENV_VALUES = ("prod", "staging", "dev")


def make_icon(size=18, color="#dcdcaa"):
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 10)
    draw.ellipse([pad, size // 3, size - pad, size - pad], fill="#473a12", outline=color, width=max(1, size // 12))
    draw.ellipse([size // 4, size // 2 - 1, size * 3 // 4, size // 2 + 1], fill=color)
    draw.line([(size // 2, pad), (size // 2, size // 3)], fill=color, width=max(1, size // 12))
    draw.line([(size // 3, size // 6), (size * 2 // 3, size // 6)], fill=color, width=max(1, size // 12))
    return img


class PaydirtWidget(tk.Frame):
    """Manual-first CVE workflow widget backed by daily Prisma ZIPs in S3."""

    WIDGET_NAME = "paydirt"
    WIDGET_TITLE = "Paydirt"
    WIDGET_ICON_FUNC = staticmethod(make_icon)
    WIDGET_ICON_NAME = "prospector"
    WIDGET_DEMO_DATA = {
        "bucket": "assist-data-development-s3",
        "prefix": "prisma/raw/",
        "workflow_mode": "manual",
        "monitor_targets": [
            "assist-prod",
            "assist-staging06",
            "data-tools staging/prod namespaces",
        ],
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._icons: dict[str, object] = {}
        self.settings = _paydirt.load_settings()
        self._reports: list[_paydirt.ReportArchive] = []
        self._latest_env_summaries: list[dict[str, object]] = []
        self._workflow_result: dict[str, object] | None = None
        self._current_snapshot: _paydirt.Snapshot | None = None
        self._previous_snapshot: _paydirt.Snapshot | None = None
        self._comparison: dict[str, object] | None = None
        self._filtered_current_rows: list[dict[str, str]] = []
        self._filtered_change_rows: list[dict[str, str]] = []
        self._filtered_tracked_rows: list[dict[str, str]] = []
        self._filtered_story_drafts: list[dict[str, object]] = []
        self._story_tree_map: dict[str, dict[str, object]] = {}
        self._build_ui()
        self.after(100, self._load_defaults)

    def _build_ui(self):
        self._setup_tree_styles()
        for name in ("prospector", "refresh", "download", "copy", "search", "settings", "warning"):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        self.status_var = tk.StringVar(value="Ready")
        self.source_var = tk.StringVar()
        self.mode_var = tk.StringVar()
        self.targets_var = tk.StringVar()
        self.tab_count_var = tk.StringVar(value="Counts: waiting for data")
        self.footer_var = tk.StringVar()

        self.env_var = tk.StringVar(value="prod")
        self.date_var = tk.StringVar()
        self.filter_var = tk.StringVar()
        self.severity_var = tk.StringVar(value="All")
        self.change_state_var = tk.StringVar(value="All")
        self.scope_var = tk.StringVar(value="Tracked Only")

        header = tk.Frame(self, bg=BG2)
        header.pack(fill=tk.X, padx=5, pady=(5, 0))

        title_wrap = tk.Frame(header, bg=BG2)
        title_wrap.pack(side=tk.LEFT, fill=tk.X, expand=True)
        if self._icons.get("prospector"):
            tk.Label(title_wrap, image=self._icons["prospector"], bg=BG2).pack(side=tk.LEFT, padx=(10, 4), pady=8)
        tk.Label(
            title_wrap,
            text="Paydirt",
            font=("Segoe UI", 13, "bold"),
            fg=ACCENT2,
            bg=BG2,
        ).pack(side=tk.LEFT, padx=(0, 6), pady=8)
        tk.Label(
            title_wrap,
            text="Manual-first CVE workflow from daily Prisma ZIPs",
            font=("Segoe UI", 9),
            fg=FG2,
            bg=BG2,
        ).pack(side=tk.LEFT, padx=4)

        action_wrap = tk.Frame(header, bg=BG2)
        action_wrap.pack(side=tk.RIGHT, padx=8, pady=6)
        self._make_btn(action_wrap, "Settings", self._open_settings_dialog, "settings").pack(side=tk.LEFT, padx=4)
        self._make_btn(action_wrap, "Process Today", self._process_today_async, "download").pack(side=tk.LEFT, padx=4)
        self._make_btn(action_wrap, "Refresh S3", self._refresh_s3_async, "refresh").pack(side=tk.LEFT, padx=4)
        self.status_label = tk.Label(action_wrap, textvariable=self.status_var, font=("Segoe UI", 9), fg=FG2, bg=BG2)
        self.status_label.pack(side=tk.LEFT, padx=(10, 2))

        summary = tk.Frame(self, bg=BG2)
        summary.pack(fill=tk.X, padx=5, pady=(0, 4))
        tk.Label(summary, textvariable=self.source_var, bg=BG2, fg=FG, font=("Segoe UI", 9), anchor="w").pack(fill=tk.X, padx=10, pady=(4, 1))
        tk.Label(summary, textvariable=self.mode_var, bg=BG2, fg=FG2, font=("Segoe UI", 9), anchor="w").pack(fill=tk.X, padx=10, pady=1)
        tk.Label(summary, textvariable=self.targets_var, bg=BG2, fg=FG2, font=("Segoe UI", 9), anchor="w").pack(fill=tk.X, padx=10, pady=(1, 6))

        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        controls = tk.Frame(body, bg=BG2)
        controls.pack(fill=tk.X)

        row1 = tk.Frame(controls, bg=BG2)
        row1.pack(fill=tk.X, padx=4, pady=(4, 2))
        tk.Label(row1, text="Env:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(4, 5))
        self.env_combo = ttk.Combobox(row1, textvariable=self.env_var, values=list(ENV_VALUES), width=12, state="readonly")
        self.env_combo.pack(side=tk.LEFT, padx=4)
        self.env_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_env_change())
        tk.Label(row1, text="Report Date:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(10, 5))
        self.date_combo = ttk.Combobox(row1, textvariable=self.date_var, values=[], width=16, state="readonly")
        self.date_combo.pack(side=tk.LEFT, padx=4)
        self.date_combo.bind("<<ComboboxSelected>>", lambda _e: self._load_selected_async())
        self._make_btn(row1, "Load Replay", self._load_selected_async, "download").pack(side=tk.LEFT, padx=6)
        self._make_btn(row1, "Latest", self._jump_to_latest, "search").pack(side=tk.LEFT, padx=4)
        self._make_btn(row1, "Export View", self._export_active_view, "copy").pack(side=tk.LEFT, padx=4)

        row2 = tk.Frame(controls, bg=BG2)
        row2.pack(fill=tk.X, padx=4, pady=(0, 6))
        tk.Label(row2, text="Search:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(4, 5))
        filter_entry = tk.Entry(row2, textvariable=self.filter_var, bg=BG3, fg=FG, relief=tk.FLAT, width=30)
        filter_entry.pack(side=tk.LEFT, padx=4)
        filter_entry.bind("<Return>", lambda _e: self._apply_filters())
        tk.Label(row2, text="Severity:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(10, 5))
        self.severity_combo = ttk.Combobox(
            row2,
            textvariable=self.severity_var,
            values=["All", "Critical", "High", "Medium", "Low", "Unknown"],
            width=12,
            state="readonly",
        )
        self.severity_combo.pack(side=tk.LEFT, padx=4)
        self.severity_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        tk.Label(row2, text="Scope:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(10, 5))
        self.scope_combo = ttk.Combobox(row2, textvariable=self.scope_var, values=["Tracked Only", "All Findings"], width=14, state="readonly")
        self.scope_combo.pack(side=tk.LEFT, padx=4)
        self.scope_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        tk.Label(row2, text="Change View:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(10, 5))
        self.change_combo = ttk.Combobox(row2, textvariable=self.change_state_var, values=["All", "New", "Resolved", "Persistent"], width=14, state="readonly")
        self.change_combo.pack(side=tk.LEFT, padx=4)
        self.change_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_filters())
        tk.Button(
            row2,
            text="Apply Filters",
            command=self._apply_filters,
            bg=BG3,
            fg=FG,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=8,
            pady=4,
            cursor="hand2",
        ).pack(side=tk.LEFT, padx=6)

        count_row = tk.Frame(controls, bg=BG2)
        count_row.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Label(
            count_row,
            textvariable=self.tab_count_var,
            bg=BG2,
            fg=FG2,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill=tk.X)

        self.nb = ttk.Notebook(body)
        self.nb.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.nb.bind("<<NotebookTabChanged>>", lambda _e: self._update_tab_counts())

        workflow = tk.Frame(self.nb, bg=BG)
        self.nb.add(workflow, text="Workflow")
        self.workflow_text = scrolledtext.ScrolledText(
            workflow,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 10),
        )
        self.workflow_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.workflow_text.insert("1.0", "Refresh S3 or Process Today to start the Paydirt workflow.\n")
        self.workflow_text.config(state=tk.DISABLED)

        tracked_frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(tracked_frame, text="Tracked CVEs")
        self.tracked_tree = self._make_tree(
            tracked_frame,
            ("env", "namespace", "cluster", "cve", "severity", "package", "version", "image"),
            (80, 150, 190, 130, 80, 190, 120, 420),
        )

        story_frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(story_frame, text="Jira Drafts")
        story_top = tk.Frame(story_frame, bg=BG)
        story_top.pack(fill=tk.BOTH, expand=True)
        self.story_tree = self._make_story_tree(story_top)
        self.story_tree.bind("<<TreeviewSelect>>", lambda _e: self._render_story_detail())

        story_actions = tk.Frame(story_frame, bg=BG2)
        story_actions.pack(fill=tk.X, padx=8, pady=(0, 4))
        self._make_btn(story_actions, "Create Selected", self._preview_create_selected, "copy").pack(side=tk.LEFT, padx=(0, 6))
        self._make_btn(story_actions, "Create All", self._preview_create_all, "copy").pack(side=tk.LEFT, padx=6)
        tk.Label(
            story_actions,
            text="Preview only for now — Paydirt shows the stories/subtasks it would create, but does not write to Jira yet.",
            bg=BG2,
            fg=FG2,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=10)

        self.story_detail = scrolledtext.ScrolledText(
            story_frame,
            height=12,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 10),
        )
        self.story_detail.pack(fill=tk.BOTH, expand=False, padx=8, pady=(0, 8))
        self.story_detail.insert("1.0", "Select a draft story to inspect the previewed description and subtasks.\n")
        self.story_detail.config(state=tk.DISABLED)

        reports_frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(reports_frame, text="Reports")
        self.reports_tree = self._make_tree(reports_frame, ("env", "report_date", "size_mb", "last_modified", "locator"), (90, 120, 80, 170, 760))
        self.reports_tree.bind("<Double-1>", self._on_report_double_click)

        findings_frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(findings_frame, text="Replay Findings")
        self.findings_tree = self._make_tree(
            findings_frame,
            ("cve", "severity", "package", "version", "fixed_version", "image", "namespace", "cluster"),
            (130, 80, 200, 120, 140, 360, 150, 170),
        )

        changes_frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(changes_frame, text="Replay Changes")
        self.changes_tree = self._make_tree(
            changes_frame,
            ("state", "cve", "severity", "package", "version", "fixed_version", "image", "namespace"),
            (90, 130, 80, 200, 120, 140, 360, 150),
        )

        footer = tk.Frame(self, bg=BG2)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(
            footer,
            textvariable=self.footer_var,
            fg=FG2,
            bg=BG2,
            font=("Segoe UI", 9),
            anchor="w",
            padx=10,
            pady=4,
        ).pack(fill=tk.X)
        self._apply_settings_to_ui()
        self._update_tab_counts()

    def _make_btn(self, parent, text, command, icon_name=None):
        return tk.Button(
            parent,
            text=f" {text}",
            image=self._icons.get(icon_name) if icon_name else None,
            compound=tk.LEFT if icon_name else tk.NONE,
            command=command,
            bg=BG3,
            fg=FG,
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            padx=8,
            pady=4,
            cursor="hand2",
        )

    def _setup_tree_styles(self):
        style = ttk.Style()
        try:
            style.theme_use(style.theme_use())
        except Exception:
            pass
        style.configure("Paydirt.Treeview", background=BG3, fieldbackground=BG3, foreground=FG, bordercolor=BG, relief="flat", rowheight=24)
        style.map("Paydirt.Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#ffffff")])
        style.configure("Paydirt.Treeview.Heading", background=BG2, foreground=FG, relief="flat", bordercolor=BG, font=("Segoe UI", 9, "bold"))
        style.map("Paydirt.Treeview.Heading", background=[("active", BG4)], foreground=[("active", "#ffffff")])

    def _make_tree(self, parent, columns, widths):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(outer, columns=columns, show="headings", style="Paydirt.Treeview", selectmode="extended")
        vsb = ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        for col, width in zip(columns, widths):
            tree.heading(col, text=col.replace("_", " ").title(), command=lambda c=col, t=tree: self._sort_tree_column(t, c, False))
            tree.column(col, width=width, anchor="w")
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        add_treeview_menu(tree)
        for tag, bg, fg in (
            ("critical", "#4a1010", "#ff9b9b"),
            ("high", "#5c2d00", "#ffb27d"),
            ("medium", "#4d4300", "#ffe27a"),
            ("low", "#2f3a2f", "#9ce0a6"),
            ("unknown", "#333333", FG),
            ("new", "#19361d", "#9ce0a6"),
            ("resolved", "#4a1010", "#ff9b9b"),
            ("persistent", "#1c2a3b", "#b6d8ff"),
        ):
            tree.tag_configure(tag, background=bg, foreground=fg)
        return tree

    def _make_story_tree(self, parent):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True)
        columns = ("severity", "records", "new", "persistent", "envs", "title")
        tree = ttk.Treeview(outer, columns=columns, show="tree headings", style="Paydirt.Treeview", selectmode="extended")
        tree.heading("#0", text="Draft")
        tree.column("#0", width=130, anchor="w", stretch=False)
        for col, width in (
            ("severity", 85),
            ("records", 75),
            ("new", 65),
            ("persistent", 90),
            ("envs", 170),
            ("title", 620),
        ):
            tree.heading(col, text=col.replace("_", " ").title())
            tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(outer, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        add_treeview_menu(tree)
        for tag, bg, fg in (
            ("critical", "#4a1010", "#ff9b9b"),
            ("high", "#5c2d00", "#ffb27d"),
            ("medium", "#4d4300", "#ffe27a"),
            ("low", "#2f3a2f", "#9ce0a6"),
            ("unknown", "#333333", FG),
            ("subtask", "#20252b", "#cfd8dc"),
        ):
            tree.tag_configure(tag, background=bg, foreground=fg)
        return tree

    def _sort_tree_column(self, tree: ttk.Treeview, column: str, reverse: bool):
        def sort_key(item_id: str):
            value = tree.set(item_id, column)
            lowered = (value or "").strip().lower()
            if column == "severity":
                return (_paydirt.SEVERITY_ORDER.get(lowered, 99), lowered)
            if column.endswith("_date") or column == "last_modified":
                return (0, value)
            if lowered.isdigit():
                return (0, int(lowered))
            return (1, lowered)

        items = list(tree.get_children(""))
        items.sort(key=sort_key, reverse=reverse)
        for index, item_id in enumerate(items):
            tree.move(item_id, "", index)
        tree.heading(column, command=lambda c=column, t=tree: self._sort_tree_column(t, c, not reverse))

    def _apply_settings_to_ui(self):
        bucket = str(self.settings.get("bucket") or _paydirt.DEFAULT_BUCKET)
        prefix = str(self.settings.get("prefix") or _paydirt.DEFAULT_PREFIX)
        targets = [target for target in self.settings.get("monitor_targets", []) if target.get("enabled", True)]
        mode = str(self.settings.get("workflow_mode") or "manual").strip().lower()
        self.source_var.set(f"Source: s3://{bucket}/{prefix}")
        self.mode_var.set(
            "Mode: Manual workflow — process reports, review tracked CVEs, then preview Jira stories."
            if mode == "manual"
            else "Mode: Auto preview — Paydirt still stays read-only, but the UI is optimized for monitoring and reporting."
        )
        self.targets_var.set(f"Tracked scope: {len(targets)} active monitor targets. Use Settings to edit namespaces, clusters, bucket, and prefix.")
        self.footer_var.set(
            "Paydirt uses the fixable CSV from each daily Prisma ZIP. Jira creation remains preview-only until the workflow is proven and auto mode is ready."
        )

    def _load_defaults(self):
        self.settings = _paydirt.load_settings()
        self._apply_settings_to_ui()
        self._set_status("Loaded Paydirt workflow settings", SUCCESS)
        self._refresh_s3_async()

    def _refresh_s3_async(self):
        bucket = str(self.settings.get("bucket") or _paydirt.DEFAULT_BUCKET)
        prefix = str(self.settings.get("prefix") or _paydirt.DEFAULT_PREFIX)
        self._set_status(f"Listing S3 reports from s3://{bucket}/{prefix}", WARN)

        def worker():
            try:
                client = _paydirt.make_s3_client(region=str(self.settings.get("region") or _paydirt.DEFAULT_REGION))
                reports = _paydirt.list_s3_archives(bucket=bucket, prefix=prefix, client=client)
                latest = _paydirt.build_latest_summary(reports, client=client)
                self.after(0, lambda: self._finish_refresh(reports, latest))
            except Exception as exc:
                self.after(0, lambda exc=exc: self._show_error("Paydirt Refresh", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_refresh(self, reports: list[_paydirt.ReportArchive], latest: list[dict[str, object]]):
        self._reports = reports
        self._latest_env_summaries = latest
        self._populate_reports_tree()
        envs = [env for env in ENV_VALUES if any(report.env == env for report in reports)]
        if not envs:
            self._render_workflow()
            self._set_status("No Prisma ZIPs found under the configured S3 prefix", ERROR)
            return
        if self.env_var.get() not in envs:
            self.env_var.set("prod" if "prod" in envs else envs[0])
        self.env_combo.configure(values=envs)
        self._refresh_dates()
        self._set_status(f"Loaded {len(reports)} S3 report archives", SUCCESS)
        self._process_today_async(auto_started=True)
        self._load_selected_async()

    def _process_today_async(self, auto_started: bool = False):
        if not self._reports:
            messagebox.showinfo("Paydirt", "Refresh S3 first so Paydirt can process the latest ZIP files.", parent=self)
            return
        self._set_status("Processing latest ZIP files for the configured monitored scope", WARN)

        def worker():
            try:
                client = _paydirt.make_s3_client(region=str(self.settings.get("region") or _paydirt.DEFAULT_REGION))
                workflow = _paydirt.build_workflow_run(self._reports, self.settings, client=client)
                self.after(0, lambda: self._finish_workflow(workflow, auto_started=auto_started))
            except Exception as exc:
                self.after(0, lambda exc=exc: self._show_error("Paydirt Workflow", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_workflow(self, workflow: dict[str, object], *, auto_started: bool):
        self._workflow_result = workflow
        self._render_workflow()
        self._apply_filters()
        issues = workflow.get("issues", [])
        env_runs = workflow.get("env_runs", [])
        if issues:
            self._set_status(f"Processed latest ZIPs with {len(issues)} coverage issue(s)", WARN)
        elif env_runs:
            prefix = "Auto-processed" if auto_started else "Processed"
            self._set_status(f"{prefix} latest ZIPs for {len(env_runs)} monitored environment(s)", SUCCESS)
        else:
            self._set_status("No monitored environments could be processed from the current scope", WARN)

    def _refresh_dates(self):
        env = self.env_var.get().strip().lower()
        dates = sorted({report.report_date for report in self._reports if report.env == env}, reverse=True)
        self.date_combo.configure(values=dates)
        if dates and self.date_var.get() not in dates:
            self.date_var.set(dates[0])

    def _on_env_change(self):
        self._refresh_dates()
        self._load_selected_async()

    def _jump_to_latest(self):
        self._refresh_dates()
        self._load_selected_async()

    def _selected_archive(self) -> _paydirt.ReportArchive | None:
        env = self.env_var.get().strip().lower()
        report_date = self.date_var.get().strip()
        matches = [report for report in self._reports if report.env == env and report.report_date == report_date]
        if not matches:
            return None
        return sorted(matches, key=lambda item: item.locator)[-1]

    def _load_selected_async(self):
        current = self._selected_archive()
        if not current:
            return
        previous = _paydirt.previous_archive(self._reports, current)
        self._set_status(f"Loading replay for {current.label}", WARN)

        def worker():
            try:
                client = _paydirt.make_s3_client(region=str(self.settings.get("region") or _paydirt.DEFAULT_REGION)) if current.source == "s3" else None
                current_snapshot = _paydirt.load_snapshot(current, client=client)
                previous_snapshot = _paydirt.load_snapshot(previous, client=client) if previous else None
                comparison = _paydirt.compare_snapshots(current_snapshot, previous_snapshot)
                self.after(0, lambda: self._finish_load(current_snapshot, previous_snapshot, comparison))
            except Exception as exc:
                self.after(0, lambda exc=exc: self._show_error("Paydirt Replay", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_load(self, current: _paydirt.Snapshot, previous: _paydirt.Snapshot | None, comparison: dict[str, object]):
        self._current_snapshot = current
        self._previous_snapshot = previous
        self._comparison = comparison
        self._apply_filters()
        previous_note = previous.archive.report_date if previous else "no prior report"
        self._set_status(f"Loaded replay {_paydirt.env_label(current.archive.env)} {current.archive.report_date} against {previous_note}", SUCCESS)

    def _populate_reports_tree(self):
        self.reports_tree.delete(*self.reports_tree.get_children())
        for idx, report in enumerate(sorted(self._reports, key=lambda item: (_paydirt.ENV_ORDER.get(item.env, 99), item.report_date), reverse=True)):
            self.reports_tree.insert(
                "",
                tk.END,
                iid=f"report-{idx}",
                values=(
                    _paydirt.env_label(report.env),
                    report.report_date,
                    _paydirt.archive_size_mb(report),
                    report.last_modified,
                    report.locator,
                ),
            )

    def _on_report_double_click(self, _event=None):
        selected = self.reports_tree.selection()
        if not selected:
            return
        values = self.reports_tree.item(selected[0], "values")
        if not values:
            return
        self.env_var.set(str(values[0]).strip().lower())
        self._refresh_dates()
        self.date_var.set(values[1])
        self._load_selected_async()

    def _apply_filters(self):
        query = self.filter_var.get().strip().lower()
        severity = self.severity_var.get().strip().lower()
        scope_tracked_only = self.scope_var.get().strip().lower() == "tracked only"

        replay_rows = list(self._current_snapshot.rows) if self._current_snapshot else []
        if scope_tracked_only:
            replay_rows = _paydirt.filter_rows(replay_rows, self.settings.get("monitor_targets"))
        if severity and severity != "all":
            replay_rows = [row for row in replay_rows if (row.get("severity") or "").lower() == severity]
        if query:
            replay_rows = [row for row in replay_rows if query in json.dumps(row, ensure_ascii=False).lower()]
        self._filtered_current_rows = replay_rows

        change_rows: list[dict[str, str]] = []
        if self._comparison:
            for state, source_key in (("New", "new_rows"), ("Resolved", "resolved_rows"), ("Persistent", "persistent_rows")):
                rows = self._comparison.get(source_key, [])
                if scope_tracked_only:
                    rows = _paydirt.filter_rows(rows, self.settings.get("monitor_targets"))
                for row in rows:
                    if severity and severity != "all" and (row.get("severity") or "").lower() != severity:
                        continue
                    if query and query not in json.dumps(row, ensure_ascii=False).lower():
                        continue
                    change_rows.append({"state": state, **row})
        change_state = self.change_state_var.get().strip().lower()
        if change_state and change_state != "all":
            change_rows = [row for row in change_rows if row.get("state", "").lower() == change_state]
        self._filtered_change_rows = change_rows

        tracked_rows = list((self._workflow_result or {}).get("tracked_current_rows", []))
        if severity and severity != "all":
            tracked_rows = [row for row in tracked_rows if (row.get("severity") or "").lower() == severity]
        if query:
            tracked_rows = [row for row in tracked_rows if query in json.dumps(row, ensure_ascii=False).lower()]
        self._filtered_tracked_rows = tracked_rows

        story_drafts = list((self._workflow_result or {}).get("story_drafts", []))
        if severity and severity != "all":
            story_drafts = [draft for draft in story_drafts if str(draft.get("severity") or "").strip().lower() == severity]
        if query:
            story_drafts = [
                draft
                for draft in story_drafts
                if query in json.dumps(draft, ensure_ascii=False).lower()
            ]
        self._filtered_story_drafts = story_drafts

        self._render_tracked_tree()
        self._render_story_tree()
        self._render_findings_tree()
        self._render_changes_tree()
        self._render_workflow()
        self._update_tab_counts()

    def _render_tracked_tree(self):
        self.tracked_tree.delete(*self.tracked_tree.get_children())
        limited = self._filtered_tracked_rows[:DISPLAY_LIMIT]
        for idx, row in enumerate(limited):
            severity = (row.get("severity") or "unknown").lower()
            namespaces = ", ".join(_paydirt.matched_scope_namespaces(row, self.settings.get("monitor_targets"))) or row.get("namespace", "")
            self.tracked_tree.insert(
                "",
                tk.END,
                iid=f"tracked-{idx}",
                values=(
                    _paydirt.env_label(row.get("env", "")),
                    namespaces,
                    row.get("cluster", ""),
                    row.get("cve", ""),
                    row.get("severity", ""),
                    row.get("package", ""),
                    row.get("version", ""),
                    row.get("image", ""),
                ),
                tags=(severity if severity in {"critical", "high", "medium", "low"} else "unknown",),
            )

    def _render_story_tree(self):
        selected_story_id = None
        selected_image = None
        current_selection = self.story_tree.selection()
        if current_selection:
            current_payload = self._story_tree_map.get(current_selection[0], {})
            selected_story_id = current_payload.get("story_id")
            selected_image = current_payload.get("subtask", {}).get("image") if current_payload.get("kind") == "subtask" else None
        self.story_tree.delete(*self.story_tree.get_children())
        self._story_tree_map = {}
        limited = self._filtered_story_drafts[:DISPLAY_LIMIT]
        selected_iid = ""
        for idx, draft in enumerate(limited):
            iid = f"story-{idx}"
            self._story_tree_map[iid] = {"kind": "story", "story_id": draft.get("story_id"), "draft": draft}
            severity = str(draft.get("severity") or "").strip().lower()
            self.story_tree.insert(
                "",
                tk.END,
                iid=iid,
                text="Story",
                values=(
                    draft.get("severity", ""),
                    draft.get("current_findings", 0),
                    draft.get("new_findings", 0),
                    draft.get("persistent_findings", 0),
                    ", ".join(draft.get("env_labels", [])),
                    draft.get("title", ""),
                ),
                tags=(severity if severity in {"critical", "high", "medium", "low"} else "unknown",),
                open=True,
            )
            for sub_idx, subtask in enumerate(draft.get("subtasks", [])):
                child_iid = f"{iid}-sub-{sub_idx}"
                self._story_tree_map[child_iid] = {"kind": "subtask", "story_id": draft.get("story_id"), "draft": draft, "subtask": subtask}
                self.story_tree.insert(
                    iid,
                    tk.END,
                    iid=child_iid,
                    text="Subtask",
                    values=(
                        "",
                        subtask.get("findings", 0),
                        "",
                        "",
                        ", ".join(subtask.get("environment_labels", [])),
                        subtask.get("title", ""),
                    ),
                    tags=("subtask",),
                )
            if draft.get("story_id") == selected_story_id:
                selected_iid = iid
                if selected_image:
                    for sub_idx, subtask in enumerate(draft.get("subtasks", [])):
                        if subtask.get("image") == selected_image:
                            selected_iid = f"{iid}-sub-{sub_idx}"
                            break
        if not selected_iid and limited:
            selected_iid = "story-0"
        if selected_iid:
            self.story_tree.selection_set(selected_iid)
            self.story_tree.focus(selected_iid)
        self._render_story_detail()

    def _render_story_detail(self):
        selection = self.story_tree.selection()
        payload = self._story_tree_map.get(selection[0]) if selection else None
        if payload is None:
            text = "No draft stories are currently in view.\n"
        elif payload.get("kind") == "subtask":
            draft = payload.get("draft", {})
            subtask = payload.get("subtask", {})
            lines = [
                f"Subtask preview for {draft.get('cve', '')}",
                "",
                f"Story title: {draft.get('title', '')}",
                f"Subtask title: {subtask.get('title', '')}",
                f"Image: {subtask.get('image', '')}",
                f"Environments: {', '.join(subtask.get('environment_labels', [])) or 'none'}",
                f"Namespaces: {', '.join(subtask.get('namespaces', [])) or 'none'}",
                f"Clusters: {', '.join(subtask.get('clusters', [])) or 'none'}",
                f"Findings for this image/CVE pair: {subtask.get('findings', 0)}",
                f"Critical: {subtask.get('critical', 0)} | High: {subtask.get('high', 0)}",
            ]
            text = "\n".join(lines).rstrip() + "\n"
        else:
            draft = payload.get("draft", {})
            lines = [
                draft.get("title", ""),
                "",
                f"CVE: {draft.get('cve', '')}",
                f"Short description: {draft.get('short_description', '') or 'n/a'}",
                f"Report date: {draft.get('report_date', '')}",
                f"Environments: {', '.join(draft.get('env_labels', [])) or 'none'}",
                f"Namespaces: {', '.join(draft.get('namespaces', [])) or 'none'}",
                f"Current findings: {draft.get('current_findings', 0)}",
                f"New findings: {draft.get('new_findings', 0)}",
                f"Persistent findings: {draft.get('persistent_findings', 0)}",
                f"Resolved findings: {draft.get('resolved_findings', 0)}",
                f"Unique CVEs: {draft.get('unique_cves', 0)} | Unique Images: {draft.get('unique_images', 0)}",
                "",
                draft.get("description", ""),
                "",
                "Previewed subtasks:",
            ]
            subtasks = draft.get("subtasks", [])
            if subtasks:
                for idx, subtask in enumerate(subtasks, start=1):
                    lines.append(
                        f"{idx}. {subtask.get('summary', '')} | findings={subtask.get('findings', 0)} | envs={', '.join(subtask.get('environment_labels', [])) or 'none'} | namespaces={', '.join(subtask.get('namespaces', [])[:6]) or 'none'} | critical={subtask.get('critical', 0)} | high={subtask.get('high', 0)}"
                    )
            else:
                lines.append("1. No image-specific subtasks were drafted because there are no new or persistent tracked findings in scope.")
            text = "\n".join(lines).rstrip() + "\n"
        self.story_detail.config(state=tk.NORMAL)
        self.story_detail.delete("1.0", tk.END)
        self.story_detail.insert("1.0", text)
        self.story_detail.config(state=tk.DISABLED)

    def _render_findings_tree(self):
        self.findings_tree.delete(*self.findings_tree.get_children())
        limited = self._filtered_current_rows[:DISPLAY_LIMIT]
        for idx, row in enumerate(limited):
            severity = (row.get("severity") or "unknown").lower()
            self.findings_tree.insert(
                "",
                tk.END,
                iid=f"finding-{idx}",
                values=(
                    row.get("cve", ""),
                    row.get("severity", ""),
                    row.get("package", ""),
                    row.get("version", ""),
                    row.get("fixed_version", ""),
                    row.get("image", ""),
                    row.get("namespace", ""),
                    row.get("cluster", ""),
                ),
                tags=(severity if severity in {"critical", "high", "medium", "low"} else "unknown",),
            )

    def _render_changes_tree(self):
        self.changes_tree.delete(*self.changes_tree.get_children())
        limited = self._filtered_change_rows[:DISPLAY_LIMIT]
        for idx, row in enumerate(limited):
            severity = (row.get("severity") or "unknown").lower()
            state = (row.get("state") or "").lower()
            tags = [severity if severity in {"critical", "high", "medium", "low"} else "unknown"]
            if state in {"new", "resolved", "persistent"}:
                tags.append(state)
            self.changes_tree.insert(
                "",
                tk.END,
                iid=f"change-{idx}",
                values=(
                    row.get("state", ""),
                    row.get("cve", ""),
                    row.get("severity", ""),
                    row.get("package", ""),
                    row.get("version", ""),
                    row.get("fixed_version", ""),
                    row.get("image", ""),
                    row.get("namespace", ""),
                ),
                tags=tuple(tags),
            )

    def _render_workflow(self):
        lines = [
            "PAYDIRT WORKFLOW",
            "",
            self.source_var.get(),
            self.mode_var.get(),
            self.targets_var.get(),
            "",
            "1. Process today's ZIP files",
        ]
        workflow = self._workflow_result
        if not workflow:
            lines.extend(
                [
                    "   Status: Pending",
                    "   Action: Refresh S3, then click Process Today.",
                    "",
                    "2. Review tracked CVEs",
                    "   Status: Waiting for processed reports.",
                    "",
                    "3. Review Jira story drafts",
                    "   Status: Waiting for processed reports.",
                ]
            )
        else:
            env_runs = workflow.get("env_runs", [])
            issues = workflow.get("issues", [])
            reference_date = workflow.get("reference_date", "")
            summary = workflow.get("summary", {})
            lines.append(f"   Status: Processed {len(env_runs)} monitored environment(s) from the latest available ZIP set ({reference_date or 'n/a'}).")
            for env_run in env_runs:
                tracked_summary = env_run.get("tracked_summary", {})
                namespaces = ", ".join(env_run.get("tracked_namespaces", [])[:6]) or "none"
                lines.append(
                    "   - {env} {date}: tracked findings={findings} | unique CVEs={cves} | critical={critical} | high={high} | namespaces={namespaces}".format(
                        env=_paydirt.env_label(env_run.get("env", "")),
                        date=env_run.get("report_date", ""),
                        findings=env_run.get("tracked_findings", 0),
                        cves=tracked_summary.get("unique_cves", 0),
                        critical=tracked_summary.get("critical", 0),
                        high=tracked_summary.get("high", 0),
                        namespaces=namespaces,
                    )
                )
            if issues:
                lines.append("   Coverage notes:")
                for issue in issues:
                    lines.append(f"   - {issue}")
            lines.extend(
                [
                    "",
                    "2. Review tracked CVEs",
                    "   Status: Ready",
                    "   In-scope findings currently shown in workflow: {rows} | unique CVEs={cves} | unique images={images}".format(
                        rows=summary.get("rows", 0),
                        cves=summary.get("unique_cves", 0),
                        images=summary.get("unique_images", 0),
                    ),
                    "   Use the Tracked CVEs tab for the scoped backlog and Replay Findings/Replay Changes for a selected report drill-down.",
                    "",
                    "3. Review Jira story drafts",
                    "   Status: Ready",
                    f"   Draft stories available: {summary.get('story_count', 0)}",
                    "   Preview only: Create Selected / Create All shows what Paydirt would write once automation is enabled.",
                ]
            )

        if self._current_snapshot:
            current = self._current_snapshot
            previous = self._comparison.get("previous_date", "") if self._comparison else ""
            replay_summary = current.summary
            lines.extend(
                [
                    "",
                    "Selected replay",
                    f"   {_paydirt.env_label(current.archive.env)} {current.archive.report_date} | member={current.member_name}",
                    "   Replay rows={rows} | unique CVEs={cves} | critical={critical} | high={high}".format(
                        rows=replay_summary.get("rows", 0),
                        cves=replay_summary.get("unique_cves", 0),
                        critical=replay_summary.get("critical", 0),
                        high=replay_summary.get("high", 0),
                    ),
                    f"   Previous report: {previous or 'none'}",
                    f"   Filtered replay findings: {len(self._filtered_current_rows)}",
                    f"   Filtered replay changes: {len(self._filtered_change_rows)}",
                ]
            )
        if len(self._filtered_tracked_rows) > DISPLAY_LIMIT:
            lines.append(f"Tracked CVE table display is capped at {DISPLAY_LIMIT} rows; export for the full filtered set.")
        if len(self._filtered_current_rows) > DISPLAY_LIMIT:
            lines.append(f"Replay Findings table display is capped at {DISPLAY_LIMIT} rows; export for the full filtered set.")
        if len(self._filtered_change_rows) > DISPLAY_LIMIT:
            lines.append(f"Replay Changes table display is capped at {DISPLAY_LIMIT} rows; export for the full filtered set.")

        self.workflow_text.config(state=tk.NORMAL)
        self.workflow_text.delete("1.0", tk.END)
        self.workflow_text.insert("1.0", "\n".join(lines).rstrip() + "\n")
        self.workflow_text.config(state=tk.DISABLED)

    def _update_tab_counts(self):
        tab = self.nb.tab(self.nb.select(), "text") if self.nb.tabs() else ""
        if tab == "Tracked CVEs":
            count = len(self._filtered_tracked_rows)
            suffix = f" (display capped at {DISPLAY_LIMIT})" if count > DISPLAY_LIMIT else ""
            text = f"Counts: {count} tracked CVE row(s){suffix}"
        elif tab == "Jira Drafts":
            stories = len(self._filtered_story_drafts)
            subtasks = sum(len(draft.get("subtasks", [])) for draft in self._filtered_story_drafts)
            text = f"Counts: {stories} story row(s) | {subtasks} subtask row(s)"
        elif tab == "Reports":
            count = len(self._reports)
            text = f"Counts: {count} report archive row(s)"
        elif tab == "Replay Findings":
            count = len(self._filtered_current_rows)
            suffix = f" (display capped at {DISPLAY_LIMIT})" if count > DISPLAY_LIMIT else ""
            text = f"Counts: {count} replay finding row(s){suffix}"
        elif tab == "Replay Changes":
            count = len(self._filtered_change_rows)
            suffix = f" (display capped at {DISPLAY_LIMIT})" if count > DISPLAY_LIMIT else ""
            text = f"Counts: {count} replay change row(s){suffix}"
        elif tab == "Workflow":
            workflow = self._workflow_result or {}
            env_runs = len(workflow.get("env_runs", []))
            stories = len(workflow.get("story_drafts", []))
            subtasks = sum(len(draft.get("subtasks", [])) for draft in workflow.get("story_drafts", []))
            text = f"Counts: {env_runs} processed environment(s) | {stories} draft story row(s) | {subtasks} draft subtask row(s)"
        else:
            text = "Counts: waiting for data"
        self.tab_count_var.set(text)

    def _preview_create_selected(self):
        seen = {}
        for item_id in self.story_tree.selection():
            payload = self._story_tree_map.get(item_id)
            if not payload:
                continue
            draft = payload.get("draft", payload)
            if draft.get("story_id"):
                seen[draft["story_id"]] = draft
        drafts = list(seen.values())
        if not drafts:
            messagebox.showinfo("Paydirt", "Select one or more draft stories first.", parent=self)
            return
        messagebox.showinfo(
            "Paydirt Preview",
            "Preview only — these stories are not created yet:\n\n" + "\n".join(f"- {draft.get('title', '')}" for draft in drafts),
            parent=self,
        )

    def _preview_create_all(self):
        drafts = list(self._filtered_story_drafts)
        if not drafts:
            messagebox.showinfo("Paydirt", "No draft stories are currently in view.", parent=self)
            return
        messagebox.showinfo(
            "Paydirt Preview",
            "Preview only — Paydirt would currently create these stories:\n\n" + "\n".join(f"- {draft.get('title', '')}" for draft in drafts[:25]) + ("\n\n(list truncated)" if len(drafts) > 25 else ""),
            parent=self,
        )

    def _export_active_view(self):
        tab = self.nb.tab(self.nb.select(), "text")
        if tab == "Tracked CVEs":
            rows = self._filtered_tracked_rows
            default_name = "paydirt-tracked-cves.csv"
        elif tab == "Jira Drafts":
            rows = self._filtered_story_drafts
            default_name = "paydirt-jira-drafts.csv"
        elif tab == "Reports":
            rows = [
                {
                    "env": report.env,
                    "report_date": report.report_date,
                    "size_mb": _paydirt.archive_size_mb(report),
                    "last_modified": report.last_modified,
                    "locator": report.locator,
                }
                for report in self._reports
            ]
            default_name = "paydirt-reports.csv"
        elif tab == "Replay Findings":
            rows = self._filtered_current_rows
            default_name = "paydirt-replay-findings.csv"
        elif tab == "Replay Changes":
            rows = self._filtered_change_rows
            default_name = "paydirt-replay-changes.csv"
        else:
            messagebox.showinfo("Export View", "Switch to Tracked CVEs, Jira Drafts, Reports, Replay Findings, or Replay Changes before exporting.", parent=self)
            return

        if not rows:
            messagebox.showinfo("Export View", "Nothing to export in the current view.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Export Current View",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not path:
            return
        fieldnames = sorted({key for row in rows for key in row})
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        self._set_status(f"Exported {len(rows)} rows to {Path(path).name}", SUCCESS)

    def _open_settings_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Paydirt Settings")
        dialog.configure(bg=BG)
        dialog.geometry("980x680")
        dialog.grab_set()

        settings = deepcopy(self.settings)
        targets = deepcopy(settings.get("monitor_targets", []))
        bucket_var = tk.StringVar(value=str(settings.get("bucket") or _paydirt.DEFAULT_BUCKET))
        prefix_var = tk.StringVar(value=str(settings.get("prefix") or _paydirt.DEFAULT_PREFIX))
        mode_var = tk.StringVar(value=str(settings.get("workflow_mode") or "manual").title())

        target_name_var = tk.StringVar()
        target_env_var = tk.StringVar(value="staging")
        target_clusters_var = tk.StringVar()
        target_namespaces_var = tk.StringVar()
        target_enabled_var = tk.BooleanVar(value=True)
        selected_index = {"value": None}

        tk.Label(dialog, text="Paydirt Settings", font=("Segoe UI", 13, "bold"), fg=ACCENT2, bg=BG).pack(anchor="w", padx=18, pady=(16, 8))

        top = tk.Frame(dialog, bg=BG)
        top.pack(fill=tk.X, padx=18, pady=(0, 12))
        for col in range(4):
            top.columnconfigure(col, weight=1 if col in {1, 3} else 0)
        tk.Label(top, text="Bucket:", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 6), pady=4)
        tk.Entry(top, textvariable=bucket_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=4)
        tk.Label(top, text="Prefix:", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=0, column=2, sticky="w", padx=(0, 6), pady=4)
        tk.Entry(top, textvariable=prefix_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(row=0, column=3, sticky="ew", pady=4)
        tk.Label(top, text="Workflow Mode:", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", padx=(0, 6), pady=4)
        ttk.Combobox(top, textvariable=mode_var, values=["Manual", "Auto"], width=14, state="readonly").grid(row=1, column=1, sticky="w", pady=4)
        tk.Label(
            top,
            text="Auto mode is still preview-only for now — it changes the UI emphasis to monitoring/reporting but does not create Jira issues yet.",
            bg=BG,
            fg=FG2,
            font=("Segoe UI", 9),
            anchor="w",
        ).grid(row=1, column=2, columnspan=2, sticky="w", pady=4)

        mid = tk.Frame(dialog, bg=BG)
        mid.pack(fill=tk.BOTH, expand=True, padx=18, pady=(0, 12))

        left = tk.Frame(mid, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(left, text="Monitored Targets", font=("Segoe UI", 11, "bold"), fg=FG, bg=BG).pack(anchor="w", pady=(0, 6))
        target_tree = ttk.Treeview(
            left,
            columns=("enabled", "name", "env", "clusters", "namespaces"),
            show="headings",
            style="Paydirt.Treeview",
            selectmode="browse",
        )
        for col, width in (("enabled", 70), ("name", 160), ("env", 90), ("clusters", 220), ("namespaces", 320)):
            target_tree.heading(col, text=col.title())
            target_tree.column(col, width=width, anchor="w")
        target_tree.pack(fill=tk.BOTH, expand=True)

        right = tk.Frame(mid, bg=BG2)
        right.pack(side=tk.LEFT, fill=tk.Y, padx=(14, 0))
        tk.Label(right, text="Target Editor", font=("Segoe UI", 11, "bold"), fg=FG, bg=BG2).pack(anchor="w", padx=14, pady=(12, 10))

        editor = tk.Frame(right, bg=BG2)
        editor.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
        for col in range(2):
            editor.columnconfigure(col, weight=1)
        tk.Checkbutton(
            editor,
            text="Enabled",
            variable=target_enabled_var,
            bg=BG2,
            fg=FG,
            selectcolor=BG3,
            activebackground=BG2,
            activeforeground=FG,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
        tk.Label(editor, text="Name", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(editor, textvariable=target_name_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        tk.Label(editor, text="Environment", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(editor, textvariable=target_env_var, values=["prod", "staging", "dev", "all"], width=14, state="readonly").grid(row=4, column=0, sticky="w", pady=(0, 8))
        tk.Label(editor, text="Cluster patterns (comma-separated, * allowed)", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=5, column=0, columnspan=2, sticky="w", pady=4)
        tk.Entry(editor, textvariable=target_clusters_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        tk.Label(editor, text="Namespace patterns (comma-separated, * allowed)", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(row=7, column=0, columnspan=2, sticky="w", pady=4)
        tk.Entry(editor, textvariable=target_namespaces_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(row=8, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        tk.Label(
            editor,
            text="Examples: assist-prod, assist-staging06, data-pipeline, kafka*.\nRows that list multiple namespaces are matched against each namespace token.",
            bg=BG2,
            fg=FG2,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=(0, 12))

        button_row = tk.Frame(editor, bg=BG2)
        button_row.grid(row=10, column=0, columnspan=2, sticky="w", pady=(0, 10))

        def fill_editor(target=None):
            target = target or {}
            target_name_var.set(str(target.get("name") or ""))
            target_env_var.set(str(target.get("env") or "staging"))
            target_clusters_var.set(", ".join(target.get("cluster_patterns", [])))
            target_namespaces_var.set(", ".join(target.get("namespace_patterns", [])))
            target_enabled_var.set(bool(target.get("enabled", True)))

        def refresh_target_tree():
            target_tree.delete(*target_tree.get_children())
            for idx, target in enumerate(targets):
                target_tree.insert(
                    "",
                    tk.END,
                    iid=f"target-{idx}",
                    values=(
                        "Yes" if target.get("enabled", True) else "No",
                        target.get("name", ""),
                        target.get("env", ""),
                        ", ".join(target.get("cluster_patterns", [])),
                        ", ".join(target.get("namespace_patterns", [])),
                    ),
                )

        def build_target_from_editor():
            name = target_name_var.get().strip()
            if not name:
                messagebox.showwarning("Paydirt Settings", "Target name is required.", parent=dialog)
                return None
            target = {
                "enabled": bool(target_enabled_var.get()),
                "name": name,
                "env": target_env_var.get().strip().lower() or "all",
                "cluster_patterns": [part.strip() for part in target_clusters_var.get().split(",") if part.strip()],
                "namespace_patterns": [part.strip() for part in target_namespaces_var.get().split(",") if part.strip()],
            }
            if not target["cluster_patterns"] and not target["namespace_patterns"]:
                messagebox.showwarning("Paydirt Settings", "Add at least one cluster or namespace pattern for the target.", parent=dialog)
                return None
            return target

        def add_or_update_target():
            target = build_target_from_editor()
            if target is None:
                return
            index = selected_index["value"]
            if index is None:
                targets.append(target)
            else:
                targets[index] = target
            refresh_target_tree()
            selected_index["value"] = None
            fill_editor()

        def remove_target():
            index = selected_index["value"]
            if index is None:
                messagebox.showinfo("Paydirt Settings", "Select a target to remove.", parent=dialog)
                return
            del targets[index]
            selected_index["value"] = None
            refresh_target_tree()
            fill_editor()

        def load_default_targets():
            targets.clear()
            targets.extend(_paydirt.default_monitor_targets())
            selected_index["value"] = None
            refresh_target_tree()
            fill_editor()

        def on_target_select(_event=None):
            selection = target_tree.selection()
            if not selection:
                selected_index["value"] = None
                fill_editor()
                return
            index = int(selection[0].split("-")[1])
            selected_index["value"] = index
            fill_editor(targets[index])

        tk.Button(button_row, text="Add / Update", command=add_or_update_target, bg=ACCENT, fg="white", relief=tk.FLAT, padx=12, pady=5).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(button_row, text="Remove", command=remove_target, bg=BG3, fg=FG, relief=tk.FLAT, padx=12, pady=5).pack(side=tk.LEFT, padx=6)
        tk.Button(button_row, text="Load Defaults", command=load_default_targets, bg=BG3, fg=FG, relief=tk.FLAT, padx=12, pady=5).pack(side=tk.LEFT, padx=6)

        target_tree.bind("<<TreeviewSelect>>", on_target_select)
        refresh_target_tree()
        fill_editor()

        bottom = tk.Frame(dialog, bg=BG)
        bottom.pack(fill=tk.X, padx=18, pady=(0, 16))

        def save_and_close():
            bucket = bucket_var.get().strip()
            prefix = prefix_var.get().strip()
            if not bucket or not prefix:
                messagebox.showwarning("Paydirt Settings", "Bucket and prefix are required.", parent=dialog)
                return
            self.settings = _paydirt.save_settings(
                {
                    "bucket": bucket,
                    "prefix": prefix,
                    "region": self.settings.get("region"),
                    "workflow_mode": mode_var.get().strip().lower(),
                    "monitor_targets": targets,
                }
            )
            self._apply_settings_to_ui()
            dialog.destroy()
            self._refresh_s3_async()

        tk.Button(bottom, text="Save", command=save_and_close, bg=ACCENT, fg="white", relief=tk.FLAT, padx=16, pady=6).pack(side=tk.RIGHT, padx=(6, 0))
        tk.Button(bottom, text="Cancel", command=dialog.destroy, bg=BG3, fg=FG, relief=tk.FLAT, padx=16, pady=6).pack(side=tk.RIGHT, padx=6)

    def _show_error(self, title: str, exc: Exception):
        self._set_status(str(exc), ERROR)
        messagebox.showerror(title, str(exc), parent=self)

    def _set_status(self, text: str, color=FG2):
        self.status_var.set(text)
        self.status_label.configure(fg=color)
