"""Prisma Cloud widget for CVE reconciliation and AI-assisted analysis."""

from __future__ import annotations

import csv
import io
import importlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from dotenv import dotenv_values, load_dotenv

from auger.tools.jira_session import JiraSession
from auger.tools import prisma_cloud as _prisma_cloud
from auger.tools import prisma_history as _prisma_history
from auger.ui import icons as _icons
from auger.ui.utils import add_treeview_menu, auger_home as _auger_home

BG = "#1e1e1e"
BG2 = "#252526"
BG3 = "#2d2d2d"
BG4 = "#333333"
FG = "#e0e0e0"
FG2 = "#888888"
ACCENT = "#007acc"
ACCENT2 = "#4ec9b0"
SUCCESS = "#4ec9b0"
ERROR = "#f44747"
WARN = "#f0c040"

_CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
_DONEISH = ("done", "resolved", "closed", "fixed", "complete", "completed", "remediated")
_CLI_METADATA_RE = re.compile(r"(?m)^(?:Working|I’m|I'm|Intent logged|● .*|✔ .*|Shell completed.*)$")


def _filter_relevant_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Use prisma_history filtering when available, otherwise fall back locally."""
    if hasattr(_prisma_history, "filter_relevant_rows"):
        return _prisma_history.filter_relevant_rows(rows)

    def namespace_is_relevant(env: str, namespace: str) -> bool:
        namespaces = [item.strip() for item in (namespace or "").split(",") if item.strip()]
        if not namespaces:
            return False
        if "assist-prod" in namespaces:
            return True
        if "assist-staging06" in namespaces:
            return True
        if env in {"stg", "prod"} and any(item.startswith("data-") for item in namespaces):
            return True
        return False

    return [
        row for row in rows
        if namespace_is_relevant((row.get("env") or "").strip().lower(), row.get("namespace", ""))
    ]


def _history_db_path() -> Path:
    if hasattr(_prisma_history, "history_db_path"):
        return Path(_prisma_history.history_db_path())
    return _auger_home() / ".auger" / "logs" / "prisma_cloud.db"


class PrismaCloudWidget(tk.Frame):
    """Live Prisma Cloud and Jira reconciliation widget."""

    WIDGET_NAME = "prisma_cloud"
    WIDGET_TITLE = "Prisma Cloud"
    WIDGET_ICON_NAME = "shield"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._icons: dict[str, object] = {}
        self._client = None
        self._last_auth_meta: dict[str, str] = {}
        self._last_fetch_meta: dict[str, str] = {}
        self._last_fetch_note = ""
        self.prisma_rows: list[dict[str, str]] = []
        self.filtered_prisma_rows: list[dict[str, str]] = []
        self.prisma_summary: dict[str, int] = {}
        self.prisma_stats: dict | None = None
        self.jira_records: list[dict[str, object]] = []
        self.jira_matches_by_cve: dict[str, list[dict[str, object]]] = {}
        self.history_summary: dict[str, object] = {}
        self.history_rows: list[dict[str, str]] = []
        self.comparison_rows: dict[str, list[dict[str, str]]] = {
            "only_prisma": [],
            "in_both": [],
            "validate_fixed": [],
            "likely_remediated": [],
            "only_jira": [],
        }
        self._analysis_thread: threading.Thread | None = None
        self._build_ui()
        self.after(100, self._reload_env)

    # ── UI ──────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._setup_tree_styles()
        for name in ("shield", "refresh", "download", "folder", "search", "check", "warning", "copy"):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        header = tk.Frame(self, bg=BG2)
        header.pack(fill=tk.X, padx=5, pady=(5, 0))

        if self._icons.get("shield"):
            tk.Label(header, image=self._icons["shield"], bg=BG2).pack(side=tk.LEFT, padx=(10, 4), pady=8)
        tk.Label(
            header,
            text="Prisma Cloud",
            font=("Segoe UI", 13, "bold"),
            fg=ACCENT2,
            bg=BG2,
        ).pack(side=tk.LEFT, padx=(0, 6), pady=8)
        tk.Label(
            header,
            text="Daily Prisma history, Jira reconciliation, and AI workflow help",
            font=("Segoe UI", 9),
            fg=FG2,
            bg=BG2,
        ).pack(side=tk.LEFT, padx=4)

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = tk.Label(header, textvariable=self.status_var, font=("Segoe UI", 9), fg=FG2, bg=BG2)
        self.status_label.pack(
            side=tk.RIGHT, padx=10
        )

        body = tk.Frame(self, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self._build_controls(body)

        self.nb = ttk.Notebook(body)
        self.nb.pack(fill=tk.BOTH, expand=True, pady=(6, 0))

        self._build_overview_tab()
        self._build_vulnerabilities_tab()
        self._build_jira_tab()
        self._build_compare_tab()
        self._build_history_tab()
        self._build_ai_tab()

        footer = tk.Frame(self, bg=BG2)
        footer.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(
            footer,
            text="Task 174 focus: use daily Prisma history plus Jira context to quickly spot what is still open vs already fixed or ready to validate.",
            fg=FG2,
            bg=BG2,
            font=("Segoe UI", 9),
            anchor="w",
            padx=10,
            pady=4,
        ).pack(fill=tk.X)

    def _build_controls(self, parent):
        controls = tk.Frame(parent, bg=BG2)
        controls.pack(fill=tk.X)

        self.url_var = tk.StringVar()
        self.access_key_var = tk.StringVar()
        self.secret_key_var = tk.StringVar()
        self.jql_var = tk.StringVar(value="project = ASSIST3 ORDER BY updated DESC")
        self.filter_var = tk.StringVar()
        self.severity_var = tk.StringVar(value="All")
        self.history_status_var = tk.StringVar(value="Open")

        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)
        controls.columnconfigure(5, weight=1)

        tk.Label(controls, text="Prisma URL:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=0, sticky="w", padx=(8, 5), pady=5
        )
        tk.Entry(controls, textvariable=self.url_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(
            row=0, column=1, sticky="ew", padx=4, pady=5
        )
        tk.Label(controls, text="Access Key:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=2, sticky="w", padx=(12, 5), pady=5
        )
        tk.Entry(controls, textvariable=self.access_key_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(
            row=0, column=3, sticky="ew", padx=4, pady=5
        )
        tk.Label(controls, text="Secret Key:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(
            row=0, column=4, sticky="w", padx=(12, 5), pady=5
        )
        tk.Entry(controls, textvariable=self.secret_key_var, bg=BG3, fg=FG, relief=tk.FLAT, show="*").grid(
            row=0, column=5, sticky="ew", padx=4, pady=5
        )

        tk.Label(controls, text="Jira JQL:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).grid(
            row=1, column=0, sticky="w", padx=(8, 5), pady=5
        )
        tk.Entry(controls, textvariable=self.jql_var, bg=BG3, fg=FG, relief=tk.FLAT).grid(
            row=1, column=1, columnspan=5, sticky="ew", padx=4, pady=5
        )

        btns = tk.Frame(controls, bg=BG2)
        btns.grid(row=2, column=0, columnspan=6, sticky="ew", padx=4, pady=(4, 6))

        self._make_btn(btns, "Reload Env", self._reload_env, "refresh").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Authenticate", self._authenticate_only, "check").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Fetch Live Prisma", self._fetch_live_prisma, "download").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Load Prisma CSV", self._load_prisma_csv_file, "folder").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Import Daily ZIPs", self._import_daily_zips, "folder").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Load Latest DB", self._load_latest_db, "refresh").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Load Jira API", self._load_jira_api, "download").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Load Jira CSV", self._load_jira_csv, "folder").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Run Compare", self._run_compare, "search").pack(side=tk.LEFT, padx=4)
        self._make_btn(btns, "Export Active View", self._export_active_view, "copy").pack(side=tk.LEFT, padx=4)

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

    def _build_overview_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="Overview")
        self.overview_text = scrolledtext.ScrolledText(
            frame,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 10),
        )
        self.overview_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.overview_text.insert("1.0", "Authenticate and fetch Prisma data to populate the widget.\n")
        self.overview_text.config(state=tk.DISABLED)

    def _build_vulnerabilities_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="Vulnerabilities")

        filter_bar = tk.Frame(frame, bg=BG2)
        filter_bar.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(filter_bar, text="Filter:", bg=BG2, fg=FG).pack(side=tk.LEFT, padx=(4, 4))
        tk.Entry(filter_bar, textvariable=self.filter_var, bg=BG3, fg=FG, relief=tk.FLAT, width=32).pack(
            side=tk.LEFT, padx=4
        )
        self.filter_var.trace_add("write", lambda *_: self._apply_prisma_filters())
        tk.Label(filter_bar, text="Severity:", bg=BG2, fg=FG).pack(side=tk.LEFT, padx=(12, 4))
        severity_combo = ttk.Combobox(
            filter_bar,
            textvariable=self.severity_var,
            values=["All", "Critical", "High", "Medium", "Low", "Unknown"],
            state="readonly",
            width=12,
        )
        severity_combo.pack(side=tk.LEFT, padx=4)
        severity_combo.bind("<<ComboboxSelected>>", lambda _e: self._apply_prisma_filters())

        pane = tk.PanedWindow(frame, orient=tk.VERTICAL, sashwidth=4, bg=BG)
        pane.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        top = tk.Frame(pane, bg=BG)
        bottom = tk.Frame(pane, bg=BG2, height=140)
        pane.add(top, minsize=200)
        pane.add(bottom, minsize=120)

        self.prisma_tree = self._make_tree(
            top,
            ("cve", "severity", "package", "version", "fixed_version", "jira_story", "jira_status", "image", "namespace", "cluster"),
            widths=(150, 90, 140, 110, 120, 80, 130, 240, 140, 140),
        )
        self.prisma_tree.bind("<<TreeviewSelect>>", self._on_select_prisma_row)

        tk.Label(bottom, text="Selected Finding", bg=BG2, fg=ACCENT2, font=("Segoe UI", 10, "bold")).pack(
            anchor="w", padx=8, pady=(6, 2)
        )
        self.detail_text = scrolledtext.ScrolledText(
            bottom,
            bg=BG3,
            fg=FG,
            relief=tk.FLAT,
            wrap=tk.WORD,
            height=8,
            font=("Consolas", 9),
        )
        self.detail_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.detail_text.config(state=tk.DISABLED)

    def _build_jira_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="Jira")

        self.jira_tree = self._make_tree(
            frame,
            ("issue", "status", "cve_count", "cves", "summary", "updated"),
            widths=(120, 120, 80, 200, 420, 130),
        )

    def _build_compare_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="Reconcile")

        self.compare_summary = tk.StringVar(value="Load Prisma and Jira data, then click Run Compare.")
        tk.Label(
            frame,
            textvariable=self.compare_summary,
            bg=BG2,
            fg=FG,
            anchor="w",
            padx=8,
            pady=6,
            wraplength=900,
            justify="left",
        ).pack(fill=tk.X, padx=8, pady=(8, 4))

        self.compare_nb = ttk.Notebook(frame)
        self.compare_nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self.compare_trees: dict[str, ttk.Treeview] = {}
        for key, label in (
            ("only_prisma", "Only in Prisma"),
            ("in_both", "In Both"),
            ("validate_fixed", "Validate Fixed"),
            ("likely_remediated", "Likely Remediated"),
            ("only_jira", "Only in Jira"),
        ):
            sub = tk.Frame(self.compare_nb, bg=BG)
            self.compare_nb.add(sub, text=label)
            tree = self._make_tree(
                sub,
                ("cve", "severity", "prisma_count", "jira_count", "jira_statuses", "details"),
                widths=(150, 90, 90, 90, 180, 420),
            )
            self.compare_trees[key] = tree

    def _build_history_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="History")

        top = tk.Frame(frame, bg=BG2)
        top.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(top, text="History View:", bg=BG2, fg=FG).pack(side=tk.LEFT, padx=(4, 6))
        history_filter = ttk.Combobox(
            top,
            textvariable=self.history_status_var,
            values=["Open", "Remediated", "All"],
            state="readonly",
            width=12,
        )
        history_filter.pack(side=tk.LEFT, padx=4)
        history_filter.bind("<<ComboboxSelected>>", lambda _e: self._refresh_history_tree())
        self.history_summary_var = tk.StringVar(value="No Prisma history DB loaded yet.")
        tk.Label(
            top,
            textvariable=self.history_summary_var,
            bg=BG2,
            fg=FG2,
            anchor="w",
            justify="left",
            wraplength=860,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=10)

        self.history_tree = self._make_tree(
            frame,
            ("cve", "status", "severity", "env", "namespace", "package", "image", "first_seen_date", "last_seen_date"),
            widths=(150, 120, 90, 70, 150, 140, 260, 120, 120),
        )

    def _build_ai_tab(self):
        frame = tk.Frame(self.nb, bg=BG)
        self.nb.add(frame, text="AI")

        top = tk.Frame(frame, bg=BG2)
        top.pack(fill=tk.X, padx=8, pady=(8, 4))
        tk.Label(top, text="Analysis Prompt:", bg=BG2, fg=FG, font=("Segoe UI", 9, "bold")).pack(
            side=tk.LEFT, padx=(4, 6)
        )
        self.ai_prompt_var = tk.StringVar(value="Summarize the current Prisma and Jira reconciliation state.")
        tk.Entry(top, textvariable=self.ai_prompt_var, bg=BG3, fg=FG, relief=tk.FLAT).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=4
        )
        self._make_btn(top, "Run AI", self._run_ai_prompt, "search").pack(side=tk.LEFT, padx=4)
        self._make_btn(top, "Copy Context", self._copy_context, "copy").pack(side=tk.LEFT, padx=4)

        quick = tk.Frame(frame, bg=BG)
        quick.pack(fill=tk.X, padx=8, pady=(0, 4))
        for label, prompt in (
            ("Summarize Findings", "Summarize the most important Prisma findings and what needs action next."),
            ("Draft Jira Update", "Draft a Jira/Scrum update covering current Prisma findings, in-both issues, and likely remediated CVEs."),
            ("Validate Fixed", "Focus on CVEs still present in Prisma but tied to done/resolved Jira tickets and explain what should be validated as already fixed."),
            ("Focus Likely Remediated", "Review the likely remediated CVEs and explain what should be validated or closed in Jira."),
        ):
            tk.Button(
                quick,
                text=label,
                command=lambda p=prompt: self._run_ai_prompt(p),
                bg=BG3,
                fg=FG,
                relief=tk.FLAT,
                font=("Segoe UI", 9),
                padx=8,
                pady=4,
                cursor="hand2",
            ).pack(side=tk.LEFT, padx=4)

        self.ai_output = scrolledtext.ScrolledText(
            frame,
            bg=BG3,
            fg=FG,
            insertbackground=FG,
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 10),
        )
        self.ai_output.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

    def _setup_tree_styles(self):
        style = ttk.Style()
        try:
            style.theme_use(style.theme_use())
        except Exception:
            pass
        style.configure(
            "Prisma.Treeview",
            background=BG3,
            fieldbackground=BG3,
            foreground=FG,
            bordercolor=BG,
            relief="flat",
            rowheight=24,
        )
        style.map(
            "Prisma.Treeview",
            background=[("selected", ACCENT)],
            foreground=[("selected", "#ffffff")],
        )
        style.configure(
            "Prisma.Treeview.Heading",
            background=BG2,
            foreground=FG,
            relief="flat",
            bordercolor=BG,
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "Prisma.Treeview.Heading",
            background=[("active", BG4)],
            foreground=[("active", "#ffffff")],
        )

    def _make_tree(self, parent, columns, widths):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True)
        tree = ttk.Treeview(outer, columns=columns, show="headings", style="Prisma.Treeview")
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
        tree.tag_configure("critical", background="#4a1010", foreground="#ff9b9b")
        tree.tag_configure("high", background="#5c2d00", foreground="#ffb27d")
        tree.tag_configure("medium", background="#4d4300", foreground="#ffe27a")
        tree.tag_configure("low", background="#2f3a2f", foreground="#9ce0a6")
        tree.tag_configure("unknown", background="#333333", foreground=FG)
        return tree

    def _sort_tree_column(self, tree: ttk.Treeview, column: str, reverse: bool):
        def sort_key(item_id: str):
            value = tree.set(item_id, column)
            text = (value or "").strip()
            lowered = text.lower()
            if column == "severity":
                return ({"critical": 0, "high": 1, "medium": 2, "low": 3}.get(lowered, 9), lowered)
            if text.isdigit():
                return (0, int(text))
            return (1, lowered)

        items = list(tree.get_children(""))
        items.sort(key=sort_key, reverse=reverse)
        for index, item_id in enumerate(items):
            tree.move(item_id, "", index)
        tree.heading(column, command=lambda c=column, t=tree: self._sort_tree_column(t, c, not reverse))

    # ── Data loading ─────────────────────────────────────────────────────────

    def _reload_env(self):
        env_file = _auger_home() / ".auger" / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=True)
        self.url_var.set(os.getenv("PRISMA_CLOUD_URL", "https://app.gov.prismacloud.io"))
        self.access_key_var.set(os.getenv("PRISMA_CLOUD_ACCESS_KEY", ""))
        self.secret_key_var.set(os.getenv("PRISMA_CLOUD_SECRET_KEY", ""))
        self._set_status("Reloaded Prisma credentials from ~/.auger/.env", SUCCESS)

    def _make_client(self) -> PrismaCloudClient:
        prisma_mod = self._load_prisma_module()
        return prisma_mod.PrismaCloudClient(
            base_url=self.url_var.get().strip(),
            access_key=self.access_key_var.get().strip(),
            secret_key=self.secret_key_var.get().strip(),
        )

    def _load_prisma_module(self):
        """Reload Prisma helper module so widget actions pick up latest helper code."""
        return importlib.reload(_prisma_cloud)

    def _authenticate_only(self):
        self._run_background("Authenticating to Prisma Cloud...", self._authenticate_worker)

    def _authenticate_worker(self):
        client = self._make_client()
        meta = client.authenticate()
        self._client = client
        self._last_auth_meta = meta
        self.after(0, lambda: self._set_status(f"Authenticated via {meta['mode']}", SUCCESS))
        self.after(0, self._render_overview)

    def _fetch_live_prisma(self):
        self._run_background("Fetching live Prisma findings...", self._fetch_live_prisma_worker)

    def _fetch_live_prisma_worker(self):
        client = self._client or self._make_client()
        meta = client.authenticate()
        fetch = client.fetch_images_csv()
        self._client = client
        self._last_auth_meta = meta
        self._last_fetch_meta = {
            "endpoint": str(fetch.get("endpoint", "")),
            "mode": str(fetch.get("mode", "")),
            "source_detail": str(fetch.get("source_detail", "")),
        }
        self._last_fetch_note = str(fetch.get("note", "")).strip()
        self.prisma_rows = _filter_relevant_rows(list(fetch["rows"]))  # type: ignore[arg-type]
        self.prisma_summary = self._load_prisma_module().summarize_findings(self.prisma_rows)
        self.prisma_stats = fetch.get("stats") if isinstance(fetch.get("stats"), dict) else client.fetch_vulnerability_stats()
        if self.jira_records:
            self._merge_jira_matches_into_prisma_rows()
        note = str(fetch.get("note_short") or fetch.get("note", "")).strip()
        self.after(0, lambda n=note: self._refresh_after_prisma_load(n))

    def _load_prisma_csv_file(self):
        filename = filedialog.askopenfilename(
            parent=self,
            title="Load Prisma CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not filename:
            return
        try:
            text = Path(filename).read_text(encoding="utf-8", errors="ignore")
            prisma_mod = self._load_prisma_module()
            rows = prisma_mod.parse_images_csv(text)
            rows = _filter_relevant_rows(rows)
            if not rows:
                raise ValueError("No in-scope Prisma rows found after namespace filtering")
            self.prisma_rows = rows
            self.prisma_summary = prisma_mod.summarize_findings(rows)
            if self.jira_records:
                self._merge_jira_matches_into_prisma_rows()
            self._last_fetch_meta = {"endpoint": filename, "mode": "Imported CSV"}
            self._refresh_after_prisma_load()
            self._set_status(f"Loaded {len(rows)} Prisma rows from CSV", SUCCESS)
        except Exception as exc:
            messagebox.showerror("Prisma CSV", f"Failed to load Prisma CSV:\n{exc}", parent=self)

    def _import_daily_zips(self):
        self._run_background("Importing daily Prisma ZIPs...", self._import_daily_zips_worker)

    def _import_daily_zips_worker(self):
        result = _prisma_history.import_download_archives()
        summary = dict(result.get("db_summary") or {})
        current_rows = list(result.get("latest_rows") or [])
        history_rows = _prisma_history.load_history_rows(status=self._history_status_key())
        archives = list(result.get("archives") or [])
        imported_reports = sum(int(item.get("reports_imported", 0)) for item in archives)
        imported_rows = sum(int(item.get("rows_imported", 0)) for item in archives)
        status = f"Imported {imported_reports} report files and loaded {len(current_rows)} current findings from Prisma history DB"
        note = f"Imported {len(archives)} ZIP archives / {imported_rows} CSV rows into {summary.get('db_path', '')}"
        self.after(
            0,
            lambda: self._apply_history_dataset(
                current_rows=current_rows,
                history_rows=history_rows,
                summary=summary,
                source_mode="Prisma History DB",
                source_detail=note,
                status_text=status,
            ),
        )

    def _load_latest_db(self):
        self._run_background("Loading Prisma history DB...", self._load_latest_db_worker)

    def _load_latest_db_worker(self):
        summary = _prisma_history.get_db_summary()
        current_rows = _prisma_history.load_current_findings()
        history_rows = _prisma_history.load_history_rows(status=self._history_status_key())
        self.after(
            0,
            lambda: self._apply_history_dataset(
                current_rows=current_rows,
                history_rows=history_rows,
                summary=summary,
                source_mode="Prisma History DB",
                source_detail=summary.get("db_path", ""),
                status_text=f"Loaded {len(current_rows)} current findings from Prisma history DB",
            ),
        )

    def _history_status_key(self) -> str:
        value = self.history_status_var.get().strip().lower()
        if value == "remediated":
            return "remediated"
        if value == "all":
            return "all"
        return "open"

    def _apply_history_dataset(
        self,
        *,
        current_rows: list[dict[str, str]],
        history_rows: list[dict[str, str]],
        summary: dict[str, object],
        source_mode: str,
        source_detail: str,
        status_text: str,
    ):
        self.history_summary = summary
        self.history_rows = list(history_rows)
        self.prisma_rows = _filter_relevant_rows(list(current_rows))
        self._load_persisted_jira_matches_into_prisma_rows()
        self.prisma_summary = self._load_prisma_module().summarize_findings(self.prisma_rows)
        if self.jira_records:
            self._merge_jira_matches_into_prisma_rows()
        self._last_fetch_meta = {
            "endpoint": str(summary.get("db_path", "")),
            "mode": source_mode,
            "source_detail": str(source_detail),
        }
        self._last_fetch_note = ""
        self._apply_prisma_filters()
        self._refresh_history_tree(render_only=True)
        self._render_overview()
        self._set_status(status_text, SUCCESS)

    def _load_persisted_jira_matches_into_prisma_rows(self):
        match_by_cve = self._load_persisted_jira_matches()
        if not match_by_cve:
            return
        for row in self.prisma_rows:
            if row.get("jira_story") or row.get("jira_status"):
                continue
            match = match_by_cve.get((row.get("cve") or "").upper())
            if not match:
                continue
            row["jira_story_key"] = match.get("jira_issue_key", "")
            row["jira_story"] = self._jira_story_suffix(match.get("jira_issue_key", ""))
            row["jira_status"] = match.get("jira_status", "")
            row["jira_story_summary"] = match.get("jira_summary", "")
            row["jira_updated"] = match.get("jira_updated", "")

    def _load_persisted_jira_matches(self) -> dict[str, dict[str, str]]:
        db_path = _history_db_path()
        if not db_path.exists():
            return {}
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(findings)").fetchall()}
            required = {"jira_issue_key", "jira_status", "jira_summary", "jira_updated"}
            if not required.issubset(columns):
                conn.close()
                return {}
            rows = conn.execute(
                """
                SELECT UPPER(cve) AS cve, jira_issue_key, jira_status, jira_summary, jira_updated
                FROM findings
                WHERE COALESCE(jira_issue_key, '') != ''
                """
            ).fetchall()
            conn.close()
        except Exception:
            return {}
        return {
            row["cve"]: {
                "jira_issue_key": row["jira_issue_key"] or "",
                "jira_status": row["jira_status"] or "",
                "jira_summary": row["jira_summary"] or "",
                "jira_updated": row["jira_updated"] or "",
            }
            for row in rows
        }

    def _refresh_history_tree(self, render_only: bool = False):
        if not render_only:
            try:
                self.history_rows = _prisma_history.load_history_rows(status=self._history_status_key())
            except Exception:
                self.history_rows = []

        if not hasattr(self, "history_tree"):
            return
        self.history_tree.delete(*self.history_tree.get_children())
        for idx, row in enumerate(self.history_rows):
            severity_key = (row.get("severity") or "unknown").lower()
            self.history_tree.insert(
                "",
                tk.END,
                iid=f"history-{idx}",
                values=(
                    row.get("cve", ""),
                    row.get("status", ""),
                    row.get("severity", ""),
                    row.get("env", ""),
                    row.get("namespace", ""),
                    row.get("package", ""),
                    row.get("image", ""),
                    row.get("first_seen_date", ""),
                    row.get("last_seen_date", ""),
                ),
                tags=(severity_key if severity_key in ("critical", "high", "medium", "low") else "unknown",),
            )
        self.history_summary_var.set(self._history_summary_text())

    def _history_summary_text(self) -> str:
        if not self.history_summary:
            return "No Prisma history DB loaded yet."
        latest = self.history_summary.get("latest_by_env") or {}
        open_by_env = self.history_summary.get("open_by_env") or {}
        latest_text = ", ".join(f"{env}={date}" for env, date in sorted(latest.items())) or "none"
        open_text = ", ".join(f"{env}={count}" for env, count in sorted(open_by_env.items())) or "none"
        return (
            f"DB: {self.history_summary.get('db_path', '')} | "
            f"Reports: {self.history_summary.get('report_runs', 0)} "
            f"(full {self.history_summary.get('full_reports', 0)} / fixable {self.history_summary.get('fixable_reports', 0)}) | "
            f"Findings: {self.history_summary.get('open_findings', 0)} open / "
            f"{self.history_summary.get('remediated_findings', 0)} remediated | "
            f"Latest: {latest_text} | Open by env: {open_text}"
        )

    def _load_jira_api(self):
        self._run_background("Loading Jira issues...", self._load_jira_api_worker)

    def _load_jira_api_worker(self):
        session = JiraSession()
        if not session.is_authenticated():
            raise self._load_prisma_module().PrismaCloudError(
                "Jira session is not authenticated. Refresh Jira MFA cookies first."
            )

        fields = ["summary", "description", "comment", "labels", "status", "updated", "assignee"]
        if self.prisma_rows:
            records = self._lookup_jira_records_for_current_cves(session, fields)
        else:
            response = session.session.post(
                f"{session.instance_url}/rest/api/3/search/jql",
                json={"jql": self.jql_var.get().strip(), "maxResults": 200, "fields": fields},
                timeout=30,
            )
            if not response.ok:
                raise self._load_prisma_module().PrismaCloudError(f"Jira query failed: HTTP {response.status_code}")
            records = [self._jira_issue_to_record(issue) for issue in response.json().get("issues", [])]

        self.jira_records = records
        self.jira_matches_by_cve = self._index_jira_records_by_cve(records)
        self.after(0, self._refresh_jira_tree)
        self.after(0, self._apply_jira_matches_to_prisma_rows)
        matched_cves = len(self.jira_matches_by_cve)
        self.after(0, lambda: self._set_status(f"Loaded {len(records)} Jira issues across {matched_cves} CVEs", SUCCESS))
        self.after(0, self._render_overview)

    def _load_jira_csv(self):
        filename = filedialog.askopenfilename(
            parent=self,
            title="Load Jira CSV",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not filename:
            return
        try:
            text = Path(filename).read_text(encoding="utf-8", errors="ignore")
            reader = csv.DictReader(io.StringIO(text))
            records: list[dict[str, object]] = []
            for row in reader:
                joined = "\n".join((value or "") for value in row.values())
                cves = sorted({match.upper() for match in _CVE_RE.findall(joined)})
                records.append(
                    {
                        "issue": row.get("Issue key") or row.get("Key") or row.get("Issue id") or "",
                        "summary": row.get("Summary", ""),
                        "status": row.get("Status", ""),
                        "updated": row.get("Updated", ""),
                        "assignee": row.get("Assignee", ""),
                        "cves": cves,
                    }
                )
            self.jira_records = records
            self.jira_matches_by_cve = self._index_jira_records_by_cve(records)
            self._apply_jira_matches_to_prisma_rows()
            self._refresh_jira_tree()
            self._render_overview()
            self._set_status(f"Loaded {len(records)} Jira CSV rows across {len(self.jira_matches_by_cve)} CVEs", SUCCESS)
        except Exception as exc:
            messagebox.showerror("Jira CSV", f"Failed to load Jira CSV:\n{exc}", parent=self)

    def _run_compare(self):
        self._compare_data()
        self._render_compare_trees()
        self._render_overview()
        self.nb.select(3)
        self._set_status("Updated Prisma/Jira reconciliation buckets", SUCCESS)

    # ── Transformations ───────────────────────────────────────────────────────

    def _jira_issue_to_record(self, issue: dict) -> dict[str, object]:
        fields = issue.get("fields") or {}
        assignee = fields.get("assignee") or {}
        joined = json.dumps(
            {
                "summary": fields.get("summary"),
                "description": fields.get("description"),
                "comment": fields.get("comment"),
                "labels": fields.get("labels"),
            },
            ensure_ascii=False,
        )
        cves = sorted({match.upper() for match in _CVE_RE.findall(joined)})
        return {
            "issue": issue.get("key", ""),
            "summary": fields.get("summary", ""),
            "status": ((fields.get("status") or {}).get("name") or ""),
            "updated": fields.get("updated", ""),
            "assignee": assignee.get("displayName") or assignee.get("name") or "",
            "cves": cves,
        }

    def _lookup_jira_records_for_current_cves(self, session: JiraSession, fields: list[str]) -> list[dict[str, object]]:
        cves = sorted({(row.get("cve") or "").upper() for row in self.prisma_rows if _CVE_RE.fullmatch((row.get("cve") or "").upper())})
        if not cves:
            return []

        base_jql = self._jira_lookup_base_jql()
        issue_map: dict[str, dict[str, object]] = {}
        for start in range(0, len(cves), 25):
            chunk = cves[start:start + 25]
            clauses = " OR ".join(f'summary ~ "{cve}"' for cve in chunk)
            jql = f"({base_jql}) AND ({clauses}) ORDER BY updated DESC"
            response = session.session.post(
                f"{session.instance_url}/rest/api/3/search/jql",
                json={"jql": jql, "maxResults": 200, "fields": fields},
                timeout=30,
            )
            if not response.ok:
                raise self._load_prisma_module().PrismaCloudError(
                    f"Jira CVE lookup failed: HTTP {response.status_code}"
                )
            for issue in response.json().get("issues", []):
                key = str(issue.get("key") or "")
                if key:
                    issue_map[key] = issue

        return [self._jira_issue_to_record(issue) for issue in issue_map.values()]

    def _jira_lookup_base_jql(self) -> str:
        raw = self.jql_var.get().strip() or "project = ASSIST3"
        cleaned = re.sub(r"(?is)\border\s+by\b.*$", "", raw).strip()
        return cleaned or "project = ASSIST3"

    def _index_jira_records_by_cve(self, records: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
        by_cve: dict[str, list[dict[str, object]]] = {}
        for record in records:
            for cve in record.get("cves", []):
                key = str(cve).upper()
                by_cve.setdefault(key, []).append(record)
        return by_cve

    def _merge_jira_matches_into_prisma_rows(self):
        for row in self.prisma_rows:
            cve = (row.get("cve") or "").upper()
            match = self._best_jira_match_for_cve(cve)
            row["jira_story"] = self._jira_story_suffix(str(match.get("issue", ""))) if match else ""
            row["jira_status"] = str(match.get("status", "")) if match else ""
            row["jira_story_key"] = str(match.get("issue", "")) if match else ""
            row["jira_story_summary"] = str(match.get("summary", "")) if match else ""
            row["jira_updated"] = str(match.get("updated", "")) if match else ""

    def _apply_jira_matches_to_prisma_rows(self):
        self._merge_jira_matches_into_prisma_rows()
        self._persist_jira_matches()
        self._apply_prisma_filters()
        self._render_overview()

    def _persist_jira_matches(self):
        best_by_cve: dict[str, dict[str, str]] = {}
        for cve in {str(key).upper() for key in self.jira_matches_by_cve}:
            match = self._best_jira_match_for_cve(cve)
            if not match:
                continue
            best_by_cve[cve] = {
                "jira_issue_key": str(match.get("issue", "")),
                "jira_status": str(match.get("status", "")),
                "jira_summary": str(match.get("summary", "")),
                "jira_updated": str(match.get("updated", "")),
            }
        if best_by_cve:
            if hasattr(_prisma_history, "save_jira_matches"):
                _prisma_history.save_jira_matches(best_by_cve)
            else:
                self._save_jira_matches_directly(best_by_cve)

    def _save_jira_matches_directly(self, best_by_cve: dict[str, dict[str, str]]):
        db_path = _history_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.row_factory = sqlite3.Row
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(findings)").fetchall()}
            for column_name in ("jira_issue_key", "jira_status", "jira_summary", "jira_updated"):
                if column_name not in columns:
                    conn.execute(f"ALTER TABLE findings ADD COLUMN {column_name} TEXT")
            for cve, match in best_by_cve.items():
                conn.execute(
                    """
                    UPDATE findings
                    SET jira_issue_key = ?, jira_status = ?, jira_summary = ?, jira_updated = ?
                    WHERE UPPER(cve) = ?
                    """,
                    (
                        match.get("jira_issue_key", ""),
                        match.get("jira_status", ""),
                        match.get("jira_summary", ""),
                        match.get("jira_updated", ""),
                        cve.upper(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def _best_jira_match_for_cve(self, cve: str) -> dict[str, object] | None:
        matches = list(self.jira_matches_by_cve.get(cve.upper(), []))
        if not matches:
            return None
        matches.sort(
            key=lambda record: (
                0 if str(record.get("summary", "")).upper().startswith(cve.upper()) else 1,
                0 if not any(done in str(record.get("status", "")).lower() for done in _DONEISH) else 1,
                str(record.get("updated", "")),
                str(record.get("issue", "")),
            ),
            reverse=False,
        )
        matches.sort(key=lambda record: str(record.get("updated", "")), reverse=True)
        matches.sort(
            key=lambda record: (
                0 if str(record.get("summary", "")).upper().startswith(cve.upper()) else 1,
                0 if not any(done in str(record.get("status", "")).lower() for done in _DONEISH) else 1,
            )
        )
        return matches[0]

    def _jira_story_suffix(self, issue_key: str) -> str:
        match = re.search(r"-(\d+)$", issue_key or "")
        if not match:
            return ""
        digits = match.group(1)
        return digits[-5:]

    def _compare_data(self):
        prisma_by_cve: dict[str, dict[str, object]] = {}
        for row in self.prisma_rows:
            cve = (row.get("cve") or "").upper()
            if not cve:
                continue
            entry = prisma_by_cve.setdefault(
                cve,
                {"rows": [], "images": set(), "severitys": set(), "packages": set()},
            )
            entry["rows"].append(row)
            if row.get("image"):
                entry["images"].add(row["image"])
            if row.get("severity"):
                entry["severitys"].add(row["severity"])
            if row.get("package"):
                entry["packages"].add(row["package"])

        jira_by_cve: dict[str, dict[str, object]] = {}
        for record in self.jira_records:
            for cve in record.get("cves", []):
                entry = jira_by_cve.setdefault(
                    str(cve).upper(),
                    {"issues": [], "statuses": set(), "summaries": [], "updated": set()},
                )
                entry["issues"].append(record)
                if record.get("status"):
                    entry["statuses"].add(str(record["status"]))
                if record.get("summary"):
                    entry["summaries"].append(str(record["summary"]))
                if record.get("updated"):
                    entry["updated"].add(str(record["updated"]))

        all_cves = sorted(set(prisma_by_cve) | set(jira_by_cve))
        buckets = {key: [] for key in self.comparison_rows}

        for cve in all_cves:
            p = prisma_by_cve.get(cve)
            j = jira_by_cve.get(cve)
            severity = ", ".join(sorted(p["severitys"])) if p else ""
            jira_statuses = ", ".join(sorted(j["statuses"])) if j else ""
            issue_keys = ", ".join(issue["issue"] for issue in (j["issues"] if j else [])[:5])
            images = ", ".join(sorted(p["images"])) if p else ""
            statuses_lower = jira_statuses.lower()
            row = {
                "cve": cve,
                "severity": severity or "Unknown",
                "prisma_count": str(len(p["rows"])) if p else "0",
                "jira_count": str(len(j["issues"])) if j else "0",
                "jira_statuses": jira_statuses,
                "details": issue_keys or images or "",
            }
            if p and j:
                if any(done in statuses_lower for done in _DONEISH):
                    buckets["validate_fixed"].append(row)
                else:
                    buckets["in_both"].append(row)
            elif p and not j:
                buckets["only_prisma"].append(row)
            elif j and not p:
                if any(done in statuses_lower for done in _DONEISH):
                    buckets["likely_remediated"].append(row)
                else:
                    buckets["only_jira"].append(row)

        self.comparison_rows = buckets
        self.compare_summary.set(
            "Only in Prisma: {only_prisma} | In Both: {in_both} | Validate Fixed: {validate_fixed} | "
            "Likely Remediated: {likely_remediated} | Only in Jira: {only_jira}".format(
                **{k: len(v) for k, v in buckets.items()}
            )
        )

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _refresh_after_prisma_load(self, note: str = ""):
        self._apply_prisma_filters()
        self._render_overview()
        if note:
            self._set_status(note, WARN)
            return
        self._set_status(
            f"Loaded {len(self.prisma_rows)} Prisma rows across {self.prisma_summary.get('unique_cves', 0)} CVEs",
            SUCCESS,
        )

    def _apply_prisma_filters(self):
        query = self.filter_var.get().strip().lower()
        severity = self.severity_var.get().strip().lower()
        rows = self.prisma_rows
        if severity and severity != "all":
            rows = [row for row in rows if (row.get("severity") or "").lower() == severity]
        if query:
            rows = [
                row
                for row in rows
                if query in json.dumps(row, ensure_ascii=False).lower()
            ]
        self.filtered_prisma_rows = rows
        self.prisma_tree.delete(*self.prisma_tree.get_children())
        for idx, row in enumerate(rows):
            severity_key = (row.get("severity") or "unknown").lower()
            self.prisma_tree.insert(
                "",
                tk.END,
                iid=f"prisma-{idx}",
                values=(
                    row.get("cve", ""),
                    row.get("severity", ""),
                    row.get("package", ""),
                    row.get("version", ""),
                    row.get("fixed_version", ""),
                    row.get("jira_story", ""),
                    row.get("jira_status", ""),
                    row.get("image", ""),
                    row.get("namespace", ""),
                    row.get("cluster", ""),
                ),
                tags=(severity_key if severity_key in ("critical", "high", "medium", "low") else "unknown",),
            )

    def _refresh_jira_tree(self):
        self.jira_tree.delete(*self.jira_tree.get_children())
        for idx, record in enumerate(self.jira_records):
            cves = record.get("cves", [])
            self.jira_tree.insert(
                "",
                tk.END,
                iid=f"jira-{idx}",
                values=(
                    record.get("issue", ""),
                    record.get("status", ""),
                    len(cves),
                    ", ".join(cves[:6]),
                    record.get("summary", ""),
                    record.get("updated", ""),
                ),
            )

    def _render_compare_trees(self):
        for bucket, tree in self.compare_trees.items():
            tree.delete(*tree.get_children())
            for idx, row in enumerate(self.comparison_rows.get(bucket, [])):
                severity_key = (row.get("severity") or "unknown").lower()
                tree.insert(
                    "",
                    tk.END,
                    iid=f"{bucket}-{idx}",
                    values=(
                        row.get("cve", ""),
                        row.get("severity", ""),
                        row.get("prisma_count", ""),
                        row.get("jira_count", ""),
                        row.get("jira_statuses", ""),
                        row.get("details", ""),
                    ),
                    tags=(severity_key if severity_key in ("critical", "high", "medium", "low") else "unknown",),
                )

    def _render_overview(self):
        lines = ["PRISMA CLOUD OVERVIEW", ""]
        if self._last_auth_meta:
            lines.append(f"Authenticated via: {self._last_auth_meta.get('mode', '')}")
            lines.append(f"Auth endpoint: {self._last_auth_meta.get('endpoint', '')}")
            lines.append("")
        if self._last_fetch_meta:
            lines.append(f"Last data source: {self._last_fetch_meta.get('mode', '')}")
            source_detail = self._last_fetch_meta.get("source_detail", "").strip()
            lines.append(f"Fetch endpoint/source: {source_detail or self._last_fetch_meta.get('endpoint', '')}")
            lines.append("")
        if self._last_fetch_note:
            lines.append("Fetch Note:")
            lines.append(self._last_fetch_note)
            lines.append("")
        if self.prisma_summary:
            lines.append("Prisma Summary:")
            for key in ("rows", "unique_cves", "unique_images", "critical", "high", "medium", "low", "unknown"):
                if key in self.prisma_summary:
                    lines.append(f"  {key.replace('_', ' ').title()}: {self.prisma_summary[key]}")
            lines.append("")
        if self.jira_records:
            tracked_cves = len({cve for rec in self.jira_records for cve in rec.get("cves", [])})
            lines.append(f"Jira issues loaded: {len(self.jira_records)}")
            lines.append(f"Unique Jira CVEs: {tracked_cves}")
            if self.prisma_rows:
                matched_rows = sum(1 for row in self.prisma_rows if row.get("jira_story"))
                matched_cves = len({(row.get("cve") or "").upper() for row in self.prisma_rows if row.get("jira_story")})
                lines.append(f"Prisma rows with Jira story: {matched_rows}")
                lines.append(f"Prisma CVEs with Jira story: {matched_cves}")
            lines.append("")
        if any(self.comparison_rows.values()):
            lines.append("Reconciliation Buckets:")
            for key, label in (
                ("only_prisma", "Only in Prisma"),
                ("in_both", "In Both"),
                ("validate_fixed", "Validate Fixed"),
                ("likely_remediated", "Likely Remediated"),
                ("only_jira", "Only in Jira"),
            ):
                lines.append(f"  {label}: {len(self.comparison_rows[key])}")
            lines.append("")
        if self.history_summary:
            lines.append("History DB:")
            lines.append(f"  Path: {self.history_summary.get('db_path', '')}")
            lines.append(
                f"  Reports: {self.history_summary.get('report_runs', 0)} "
                f"(full {self.history_summary.get('full_reports', 0)} / fixable {self.history_summary.get('fixable_reports', 0)})"
            )
            lines.append(
                f"  Findings: {self.history_summary.get('open_findings', 0)} open / "
                f"{self.history_summary.get('remediated_findings', 0)} remediated"
            )
            latest = self.history_summary.get("latest_by_env") or {}
            if isinstance(latest, dict) and latest:
                lines.append("  Latest full reports:")
                for env, date in sorted(latest.items()):
                    lines.append(f"    - {env}: {date}")
            lines.append("")
        if isinstance(self.prisma_stats, dict) and self.prisma_stats:
            lines.append("Live Stats Endpoint Response:")
            snippet = json.dumps(self.prisma_stats, indent=2)[:1200]
            lines.append(snippet)
            lines.append("")
        if self.prisma_rows:
            lines.append("Sample Findings:")
            for row in self.prisma_rows[:8]:
                lines.append(
                    f"  - {row.get('cve', '')} [{row.get('severity', '')}] "
                    f"{row.get('package', '')} {row.get('version', '')} :: {row.get('image', '')}"
                )
        if not self.prisma_rows and not self.jira_records:
            lines.append("Load live Prisma data or import CSV/Jira data to begin.")

        self.overview_text.config(state=tk.NORMAL)
        self.overview_text.delete("1.0", tk.END)
        self.overview_text.insert("1.0", "\n".join(lines))
        self.overview_text.config(state=tk.DISABLED)

    def _on_select_prisma_row(self, _event=None):
        sel = self.prisma_tree.selection()
        if not sel:
            return
        idx = self.prisma_tree.index(sel[0])
        if idx >= len(self.filtered_prisma_rows):
            return
        row = self.filtered_prisma_rows[idx]
        details = [
            f"CVE: {row.get('cve', '')}",
            f"Severity: {row.get('severity', '')}",
            f"Package: {row.get('package', '')}",
            f"Version: {row.get('version', '')}",
            f"Fixed Version: {row.get('fixed_version', '')}",
            f"Jira Story: {row.get('jira_story_key', '') or row.get('jira_story', '')}",
            f"Jira Status: {row.get('jira_status', '')}",
            f"Jira Summary: {row.get('jira_story_summary', '')}",
            f"Fixable: {row.get('fixable', '')}",
            f"Fix Date: {row.get('fix_date', '')}",
            f"Image: {row.get('image', '')}",
            f"Registry: {row.get('registry', '')}",
            f"Cluster: {row.get('cluster', '')}",
            f"Namespace: {row.get('namespace', '')}",
            f"Host: {row.get('host', '')}",
            f"First Seen: {row.get('first_seen_date', '')}",
            f"Last Seen: {row.get('last_seen_date', '')}",
            f"Link: {row.get('link', '')}",
            "",
            row.get("description", ""),
        ]
        self.detail_text.config(state=tk.NORMAL)
        self.detail_text.delete("1.0", tk.END)
        self.detail_text.insert("1.0", "\n".join(details).strip() + "\n")
        self.detail_text.config(state=tk.DISABLED)

    # ── AI helpers ────────────────────────────────────────────────────────────

    def _run_ai_prompt(self, prompt: str | None = None):
        text = (prompt or self.ai_prompt_var.get()).strip()
        if not text:
            return
        if self._analysis_thread and self._analysis_thread.is_alive():
            messagebox.showinfo("AI Busy", "Prisma AI analysis is still running.", parent=self)
            return

        self.ai_output.delete("1.0", tk.END)
        self.ai_output.insert("1.0", "Running AI analysis...\n\n")
        self._set_status("Running Prisma AI analysis...", WARN)

        full_prompt = (
            "You are helping with Prisma Cloud CVE remediation tracking for task 174 / ASSIST3-39486.\n\n"
            + self.get_context_for_auger()
            + "\n\nREQUEST:\n"
            + text
        )

        def on_chunk(chunk: str):
            self.after(0, lambda c=chunk: self.ai_output.insert(tk.END, c))

        def on_done(_full: str):
            self.after(0, lambda: self._set_status("AI analysis complete", SUCCESS))

        def on_error(err: str):
            self.after(0, lambda: self.ai_output.insert(tk.END, f"\n\nERROR: {err}\n"))
            self.after(0, lambda: self._set_status("AI analysis failed", ERROR))

        self._analysis_thread = threading.Thread(
            target=self._stream_ask,
            args=(full_prompt, on_chunk, on_done, on_error),
            daemon=True,
        )
        self._analysis_thread.start()

    def _stream_ask(self, prompt, on_chunk, on_done, on_error):
        try:
            copilot_bin = shutil.which("copilot") or "/usr/local/bin/copilot"
            if not Path(copilot_bin).exists():
                raise RuntimeError(f"copilot CLI not found at {copilot_bin}")
            proc = subprocess.Popen(
                [copilot_bin, "-p", prompt, "--allow-all"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._copilot_env(),
            )
            full = ""
            assert proc.stdout is not None
            for line in proc.stdout:
                clean = re.sub(r"\x1b\[[0-9;]*[mKJH]", "", line)
                full += clean
                on_chunk(clean)
            proc.wait()
            cleaned = _CLI_METADATA_RE.sub("", full).strip() + "\n"
            self.after(0, lambda: self._replace_ai_output(cleaned))
            on_done(cleaned)
        except Exception as exc:
            on_error(str(exc))

    def _replace_ai_output(self, text: str):
        self.ai_output.delete("1.0", tk.END)
        self.ai_output.insert("1.0", text)

    def _copilot_env(self):
        env = {
            "HOME": str(_auger_home()),
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
            "USER": os.environ.get("USER", ""),
            "TERM": "xterm-256color",
            "AUGER_CHAT_SOURCE": "prisma_widget",
        }
        env_file = _auger_home() / ".auger" / ".env"
        file_env = dotenv_values(env_file) if env_file.exists() else {}
        for key in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "GHE_TOKEN"):
            value = os.environ.get(key) or file_env.get(key)
            if value:
                for alias in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
                    env[alias] = str(value)
                break
        for key in (
            "REQUESTS_CA_BUNDLE",
            "SSL_CERT_FILE",
            "CURL_CA_BUNDLE",
            "PIP_CERT",
            "http_proxy",
            "https_proxy",
            "HTTP_PROXY",
            "HTTPS_PROXY",
            "no_proxy",
            "NO_PROXY",
        ):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def _copy_context(self):
        payload = self.get_context_for_auger()
        try:
            self.clipboard_clear()
            self.clipboard_append(payload)
            self._set_status("Copied Prisma context to clipboard", SUCCESS)
        except Exception as exc:
            messagebox.showerror("Clipboard", f"Failed to copy context:\n{exc}", parent=self)

    # ── Export ────────────────────────────────────────────────────────────────

    def _export_active_view(self):
        current = self.nb.tab(self.nb.select(), "text")
        dataset: list[dict[str, object]]
        if current == "Vulnerabilities":
            dataset = self.filtered_prisma_rows
        elif current == "Jira":
            dataset = self.jira_records
        elif current == "Reconcile":
            bucket_tab = self.compare_nb.tab(self.compare_nb.select(), "text")
            mapping = {
                "Only in Prisma": "only_prisma",
                "In Both": "in_both",
                "Validate Fixed": "validate_fixed",
                "Likely Remediated": "likely_remediated",
                "Only in Jira": "only_jira",
            }
            dataset = self.comparison_rows.get(mapping.get(bucket_tab, "only_prisma"), [])
        else:
            dataset = self.prisma_rows

        if not dataset:
            messagebox.showwarning("Export", "No rows available to export.", parent=self)
            return

        filename = filedialog.asksaveasfilename(
            parent=self,
            title="Export CSV",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if not filename:
            return

        keys = sorted({key for row in dataset for key in row.keys()})
        with open(filename, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=keys)
            writer.writeheader()
            for row in dataset:
                writer.writerow({key: self._csv_cell(row.get(key)) for key in keys})
        self._set_status(f"Exported {len(dataset)} rows to {filename}", SUCCESS)

    def _csv_cell(self, value):
        if isinstance(value, (list, tuple, set)):
            return ", ".join(str(v) for v in value)
        return value

    # ── Context / background helpers ─────────────────────────────────────────

    def get_context_for_auger(self):
        lines = ["PRISMA CLOUD WIDGET CONTEXT", ""]
        lines.append(f"Prisma URL: {self.url_var.get().strip()}")
        if self._last_auth_meta:
            lines.append(f"Authenticated via: {self._last_auth_meta.get('mode', '')}")
        lines.append("")
        if self.prisma_summary:
            lines.append("Prisma Findings:")
            for key in ("rows", "unique_cves", "unique_images", "critical", "high", "medium", "low"):
                if key in self.prisma_summary:
                    lines.append(f"- {key.replace('_', ' ').title()}: {self.prisma_summary[key]}")
            lines.append("")
        if self.prisma_rows:
            lines.append("Sample Prisma CVEs:")
            for row in self.prisma_rows[:12]:
                lines.append(
                    f"- {row.get('cve', '')} [{row.get('severity', '')}] "
                    f"{row.get('package', '')} {row.get('version', '')} :: {row.get('image', '')}"
                )
            lines.append("")
        if self.jira_records:
            lines.append(f"Jira JQL: {self.jql_var.get().strip()}")
            lines.append(f"Loaded Jira issues: {len(self.jira_records)}")
            jira_cves = sorted({cve for rec in self.jira_records for cve in rec.get("cves", [])})
            lines.append(f"Tracked Jira CVEs: {len(jira_cves)}")
            for rec in self.jira_records[:10]:
                lines.append(
                    f"- {rec.get('issue', '')} [{rec.get('status', '')}] "
                    f"CVEs={', '.join(rec.get('cves', [])[:4])} :: {rec.get('summary', '')}"
                )
            lines.append("")
        if any(self.comparison_rows.values()):
            lines.append("Reconciliation Buckets:")
            for key, label in (
                ("only_prisma", "Only in Prisma"),
                ("in_both", "In Both"),
                ("validate_fixed", "Validate Fixed"),
                ("likely_remediated", "Likely Remediated"),
                ("only_jira", "Only in Jira"),
            ):
                lines.append(f"- {label}: {len(self.comparison_rows[key])}")
            lines.append("")
        if self.history_summary:
            lines.append("History DB:")
            lines.append(f"- Path: {self.history_summary.get('db_path', '')}")
            lines.append(f"- Open findings: {self.history_summary.get('open_findings', 0)}")
            lines.append(f"- Remediated findings: {self.history_summary.get('remediated_findings', 0)}")
            latest = self.history_summary.get("latest_by_env") or {}
            if isinstance(latest, dict):
                for env, date in sorted(latest.items()):
                    lines.append(f"- Latest {env} report: {date}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def _run_background(self, status_text: str, worker):
        self._set_status(status_text, WARN)

        def runner():
            try:
                worker()
            except Exception as exc:
                self.after(0, lambda e=exc: self._background_error(e))

        threading.Thread(target=runner, daemon=True).start()

    def _background_error(self, exc: Exception):
        self._set_status(str(exc), ERROR)
        messagebox.showerror("Prisma Cloud", str(exc), parent=self)

    def _set_status(self, text: str, color=FG2):
        self.status_var.set(text)
        try:
            self.status_label.configure(fg=color)
        except Exception:
            pass

    def build_context(self):
        """Compatibility alias for widgets that expose build_context()."""
        return self.get_context_for_auger()


def create_widget(parent, **kwargs):
    """Widget factory."""
    return PrismaCloudWidget(parent, **kwargs)
