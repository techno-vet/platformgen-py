"""
Database Widget - SQL Workbench for PlatformGen
Provides SQL query execution, schema browsing, and connection management
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import json
import os
import re
import shutil
from pathlib import Path
from datetime import datetime
import csv
from platformgen.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu, auger_home as _auger_home
from platformgen.runtime import assistant_name, state_dir

try:
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw, ImageTk as _PILImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# Color scheme (matching PlatformGen theme)
BG = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
FG = '#e0e0e0'
ACCENT = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR = '#f44747'
WARNING = '#ce9178'
SUCCESS = '#4ec9b0'


def _make_db_workbench_icon(size=14, color='#5db0d7'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    for i, y in enumerate([m*2, s2//2-m, s2-m*4]):
        d.rectangle([m*2, y, s2-m*2, y+m*2], outline=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_db_library_icon(size=14, color='#4ec9b0'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    for i, x in enumerate([m*2, s2//2-m, s2-m*4]):
        d.rectangle([x, m*2, x+m*2, s2-m*2], outline=color, width=m)
    d.line([(m*2, s2-m*2), (s2-m*2, s2-m*2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_db_conn_icon(size=14, color='#569cd6'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    r = m * 3
    d.ellipse([m, s2//2-r, m+r*2, s2//2+r], outline=color, width=m)
    d.ellipse([s2-m-r*2, s2//2-r, s2-m, s2//2+r], outline=color, width=m)
    d.line([(m+r*2, s2//2), (s2-m-r*2, s2//2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


# ---------------------------------------------------------------------------
# AQL pre-loaded history — 20+ useful statements for BAs, POs, Data Engineers
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# AQL Library — grouped statements visible in the AQL Library tab.
# Structure: list of (group_label, [ (subgroup_label, [ (name, sql), ... ]), ... ])
# ---------------------------------------------------------------------------
# AQL Library — grouped statements visible in the AQL Library tab.
# Structure: list of (group_label, [ (subgroup_label, [ (name, sql), ... ]), ... ])
_AQL_LIBRARY = [

    # ════════════════════════════════════════════════════════════════════════
    ("📊 Business Analysts (BAs)", [
        ("Basic Queries", [
            ("SELECT all rows (limited)",
             "SELECT *\nFROM schema_name.table_name\nLIMIT 100;"),
            ("COUNT by status",
             "SELECT status_cd, COUNT(*) AS cnt\nFROM schema_name.table_name\nGROUP BY status_cd\nORDER BY cnt DESC;"),
            ("Recent records",
             "SELECT *\nFROM schema_name.table_name\nWHERE create_dt >= CURRENT_DATE - INTERVAL '30 days'\nORDER BY create_dt DESC\nLIMIT 100;"),
        ]),
        ("Aggregations & Summaries", [
            ("Sum and average",
             "SELECT status_cd,\n       COUNT(*) AS record_count,\n       SUM(amount) AS total_amount,\n       AVG(amount) AS avg_amount\nFROM schema_name.table_name\nGROUP BY status_cd\nORDER BY total_amount DESC;"),
            ("Date range analysis",
             "SELECT DATE(create_dt) AS date,\n       COUNT(*) AS daily_count\nFROM schema_name.table_name\nWHERE create_dt >= CURRENT_DATE - INTERVAL '30 days'\nGROUP BY DATE(create_dt)\nORDER BY date DESC;"),
        ]),
    ]),

    # ════════════════════════════════════════════════════════════════════════
    ("📋 Procurement Officers (POs)", [
        ("Contracts & Modifications", [
            ("Active contracts",
             "SELECT *\nFROM schema_name.contracts\nWHERE status_cd = 'ACTIVE'\nLIMIT 100;"),
            ("Recent modifications",
             "SELECT *\nFROM schema_name.contract_mods\nWHERE mod_date >= CURRENT_DATE - INTERVAL '30 days'\nORDER BY mod_date DESC\nLIMIT 100;"),
        ]),
        ("Spend Analysis", [
            ("Total spend by vendor",
             "SELECT vendor_id, vendor_name,\n       SUM(amount) AS total_spend\nFROM schema_name.contract_items\nGROUP BY vendor_id, vendor_name\nORDER BY total_spend DESC\nLIMIT 50;"),
        ]),
    ]),

    # ════════════════════════════════════════════════════════════════════════
    ("📊 Data Engineers (DevOps, Analytics, Reporting)", [
        ("Schema Exploration", [
            ("Show all tables",
             "SELECT table_name\nFROM information_schema.tables\nWHERE table_schema NOT IN ('pg_catalog', 'information_schema')\nORDER BY table_name;"),
            ("Show table columns",
             "SELECT column_name, data_type, is_nullable\nFROM information_schema.columns\nWHERE table_name = 'your_table_name'\nORDER BY ordinal_position;"),
            ("Show table size",
             "SELECT\n    schemaname,\n    tablename,\n    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size\nFROM pg_tables\nWHERE schemaname NOT IN ('pg_catalog','information_schema')\nORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;"),
        ]),
        ("Data Quality", [
            ("NULL check",
             "SELECT column_name, COUNT(*) AS null_count\nFROM schema_name.table_name\nWHERE column_name IS NULL\nGROUP BY column_name;"),
            ("Duplicate key check",
             "SELECT key_column, COUNT(*) AS cnt\nFROM schema_name.table_name\nGROUP BY key_column\nHAVING COUNT(*) > 1\nORDER BY cnt DESC;"),
        ]),
    ]),

    # ════════════════════════════════════════════════════════════════════════
    ("🔧 DBA / Database Administration", [
        ("Connection & Session Info", [
            ("Active connections",
             "SELECT pid, usename, datname, client_addr, state\nFROM pg_stat_activity\nWHERE state IS NOT NULL\nORDER BY query_start DESC;"),
            ("Long-running queries",
             "SELECT pid, usename, query,\n       EXTRACT(EPOCH FROM (NOW() - query_start)) AS duration_sec\nFROM pg_stat_activity\nWHERE query_start < NOW() - INTERVAL '5 minutes'\nORDER BY query_start ASC;"),
        ]),
        ("Index Management", [
            ("Index sizes",
             "SELECT indexname, pg_size_pretty(pg_relation_size(indexrelname)) AS size\nFROM pg_indexes\nWHERE schemaname NOT IN ('pg_catalog', 'information_schema')\nORDER BY pg_relation_size(indexrelname) DESC;"),
        ]),
    ]),

    # ════════════════════════════════════════════════════════════════════════
    ("🔑 Advanced Patterns", [
        ("Common Table Expressions (CTEs)", [
            ("WITH clause (CTE)",
             "WITH recent AS (\n    SELECT *\n    FROM schema_name.table_name\n    WHERE create_dt >= CURRENT_DATE - INTERVAL '7 days'\n)\nSELECT *\nFROM recent\nLIMIT 100;"),
        ]),
        ("INSERT / UPDATE / DELETE", [
            ("INSERT single row",
             "INSERT INTO schema_name.table_name\n    (col1, col2, col3)\nVALUES\n    ('value1', 'value2', NOW())\nRETURNING *;"),
            ("UPDATE with WHERE",
             "UPDATE schema_name.table_name\nSET    status_cd  = 'UPDATED',\n       update_dt = NOW()\nWHERE  id = 12345\nRETURNING *;"),
            ("DELETE with WHERE (safe — LIMIT via CTE)",
             "WITH target AS (\n    SELECT id FROM schema_name.table_name\n    WHERE status_cd = 'OBSOLETE'\n    LIMIT 100\n)\nDELETE FROM schema_name.table_name\nWHERE id IN (SELECT id FROM target)\nRETURNING *;"),
            ("UPSERT (INSERT … ON CONFLICT)",
             "INSERT INTO schema_name.table_name (id, col1, col2)\nVALUES (1, 'foo', 'bar')\nON CONFLICT (id) DO UPDATE\n    SET col1 = EXCLUDED.col1,\n        col2 = EXCLUDED.col2,\n        update_dt = NOW()\nRETURNING *;"),
        ]),
    ]),
]



# Flat list for Ctrl+↑/↓ history (one entry per statement from the library)
_AQL_PRELOADED_HISTORY = [
    sql
    for _group, subcats in _AQL_LIBRARY
    for _sub, items in subcats
    for _name, sql in items
]

# Regex that matches known assistant / Copilot CLI metadata lines that may be
# appended after the SQL in streamed responses.
_CLI_METADATA_RE = re.compile(
    r'(?m)^[^\n]*(?:'
    r'API time spent'
    r'|Total session time'
    r'|Total code changes'
    r'|Breakdown by AI model'
    r'|Total usage est'
    r'|Premium request'
    r'|tokens used'
    r'|usage est:'
    r')[^\n]*\n?',
    re.IGNORECASE,
)

# Import database drivers
try:
    import sqlalchemy
    from sqlalchemy import create_engine, inspect, text
    SQLALCHEMY_AVAILABLE = True
except ImportError:
    SQLALCHEMY_AVAILABLE = False

try:
    import psycopg2
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

try:
    import pymysql
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False

try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False

try:
    from pygments import lex
    from pygments.lexers import SqlLexer
    from pygments.token import Token
    PYGMENTS_AVAILABLE = True
except ImportError:
    PYGMENTS_AVAILABLE = False



class DatabaseWidget(tk.Frame):
    """SQL Workbench widget for PlatformGen"""
    
    # Widget metadata
    WIDGET_NAME = "database"
    WIDGET_TITLE = "Database"
    WIDGET_ICON = "🗄️"
    WIDGET_ICON_NAME = "database"
    
    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        
        # Configure dropdown font globally
        self.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))
        
        self.context_builder_callback = context_builder_callback
        self.current_connection = None
        self.current_engine = None
        self.query_history = []
        # AQL history: pre-populated + grows as queries are executed
        self.aql_history = list(_AQL_PRELOADED_HISTORY)
        self.aql_history_index = -1   # -1 = not navigating
        self._aql_history_draft = ""  # saves in-progress text when navigating
        self.connections_file = str(state_dir() / 'db_connections.json')
        # Pre-populated connections from flux config (read-only, merged at load time)
        _here = os.path.dirname(os.path.abspath(__file__))
        self._preset_file = os.path.join(_here, '..', '..', 'data', 'db_connections.yaml')
        
        # Load saved connections
        self.saved_connections = self._load_connections()
        
        self._tab_icons = {}   # GC guard for PIL PhotoImages
        self._create_ui()
        self._check_dependencies()
        # Pre-fill selector password if already saved
        saved_pwd = self._load_selector_password()
        if saved_pwd:
            self.password_var.set(saved_pwd)
    
    def _check_dependencies(self):
        """Check which database drivers are available"""
        # Only surface a status warning for the truly required driver (sqlalchemy).
        # Optional dialect drivers (psycopg2, pymysql, pyodbc) are only needed when
        # the user actually tries to connect with that DB type, so don't clutter the
        # status bar on every widget load with a scary "Missing drivers" message.
        if not SQLALCHEMY_AVAILABLE:
            self.status_var.set("⚠️ Missing required driver: sqlalchemy — run: pip install sqlalchemy")
        else:
            self.status_var.set("Not connected")
    
    def _create_ui(self):
        """Create the widget UI — three tabs: Workbench, AQL Library, Connections"""
        style = ttk.Style()
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=BG2, foreground=FG,
                        padding=[12, 4], font=('Segoe UI', 10))
        style.map('TNotebook.Tab',
                  background=[('selected', BG3)],
                  foreground=[('selected', ACCENT2)])

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ── Tab 1: Workbench ──
        self._wb_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(self._wb_tab, text='  Workbench  ')
        self._create_workbench_tab(self._wb_tab)

        # ── Tab 2: AQL Library ──
        self._aql_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(self._aql_tab, text='  AQL Library  ')
        self._create_aql_library_tab(self._aql_tab)

        # ── Tab 3: Connections ──
        self._conn_tab = tk.Frame(self.nb, bg=BG)
        self.nb.add(self._conn_tab, text='  Connections  ')
        self._create_connections_tab(self._conn_tab)
        self.after(0, self._apply_db_tab_icons)

    def _apply_db_tab_icons(self):
        """Apply emoji labels to database sub-tabs via safe nb.tab() calls.
        nb.tab() does not trigger SIGSEGV — only nb.add(text=...) with emoji is unsafe."""
        tabs_config = [
            (self._wb_tab,   '🛢️ Workbench'),
            (self._aql_tab,  '📚 AQL Library'),
            (self._conn_tab, '🔌 Connections'),
        ]
        for frame, label in tabs_config:
            try:
                self.nb.tab(frame, text=f'  {label}  ')
            except Exception:
                pass

    def _create_aql_library_tab(self, parent):
        """AQL Library tab: grouped SQL statements; double-click → load into Workbench."""
        style = ttk.Style()
        style.configure("Lib.Treeview", background=BG3, foreground=FG,
                        fieldbackground=BG3, rowheight=22, font=('Segoe UI', 9))
        style.configure("Lib.Treeview.Heading", background=BG2, foreground=FG,
                        font=('Segoe UI', 9, 'bold'), relief='flat')
        style.map("Lib.Treeview",
                  background=[('selected', ACCENT)],
                  foreground=[('selected', '#ffffff')])

        # ── Header ──
        hdr = tk.Frame(parent, bg=BG2)
        hdr.pack(fill=tk.X, padx=5, pady=(5, 0))
        tk.Label(hdr, text="AQL Library",
                 font=('Segoe UI', 11, 'bold'), fg=FG, bg=BG2).pack(side=tk.LEFT, padx=5)
        total_stmts = sum(len(items)
                          for _g, subcats in _AQL_LIBRARY
                          for _s, items in subcats)
        tk.Label(hdr, text=f"({total_stmts} statements — double-click to load into Workbench)",
                 font=('Segoe UI', 9), fg='#888', bg=BG2).pack(side=tk.LEFT, padx=4)
        tk.Button(hdr, text="Copy SQL", command=self._aql_lib_copy,
                  bg=BG3, fg=FG, font=('Segoe UI', 9), relief=tk.FLAT,
                  padx=10).pack(side=tk.RIGHT, padx=5)
        tk.Button(hdr, text="Load → Workbench", command=self._aql_lib_load,
                  bg=SUCCESS, fg='black', font=('Segoe UI', 9, 'bold'), relief=tk.FLAT,
                  padx=10).pack(side=tk.RIGHT, padx=5)

        # ── Search bar ──
        sf = tk.Frame(parent, bg=BG2)
        sf.pack(fill=tk.X, padx=5, pady=(3, 4))
        tk.Label(sf, text="Search:", bg=BG2, fg=FG).pack(side=tk.LEFT, padx=(5, 2))
        self._lib_filter_var = tk.StringVar()
        self._lib_filter_var.trace_add('write', lambda *_: self._filter_aql_library())
        tk.Entry(sf, textvariable=self._lib_filter_var, width=50,
                 font=('Segoe UI', 9), bg=BG3, fg=FG,
                 insertbackground=FG, relief=tk.FLAT).pack(side=tk.LEFT, padx=5, ipady=3)
        tk.Label(sf, text="filter by name or SQL keyword",
                 font=('Segoe UI', 8), fg='#666', bg=BG2).pack(side=tk.LEFT)

        # ── Paned: tree on left, preview on right ──
        paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL, bg=BG2, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: tree
        tree_frame = tk.Frame(paned, bg=BG2)
        sb_y = tk.Scrollbar(tree_frame)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        self._lib_tree = ttk.Treeview(tree_frame, style='Lib.Treeview',
                                       yscrollcommand=sb_y.set,
                                       selectmode='browse', show='tree')
        self._lib_tree.pack(fill=tk.BOTH, expand=True)
        sb_y.config(command=self._lib_tree.yview)
        add_treeview_menu(self._lib_tree)

        # Right: SQL preview
        preview_frame = tk.Frame(paned, bg=BG2)
        tk.Label(preview_frame, text="SQL Preview",
                 font=('Segoe UI', 10, 'bold'), fg=FG, bg=BG2).pack(
            fill=tk.X, padx=5, pady=(5, 2))
        self._lib_preview = scrolledtext.ScrolledText(
            preview_frame, height=8, wrap=tk.NONE,
            bg=BG3, fg=FG, font=('Consolas', 10),
            insertbackground=FG, state=tk.DISABLED
        )
        self._lib_preview.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        make_text_copyable(self._lib_preview)

        paned.add(tree_frame, width=320)
        paned.add(preview_frame)

        # ── Status hint ──
        tk.Label(parent,
                 text="Double-click a statement to load it into the Workbench editor  |  Ctrl+↑/↓ in Workbench to cycle history",
                 font=('Segoe UI', 8), fg='#666', bg=BG).pack(side=tk.BOTTOM, pady=(0, 4))

        # ── Populate tree ──
        self._lib_all_items = []   # list of (tree_iid, name, sql) for filtering
        self._lib_sql_map   = {}   # iid → sql
        self._lib_name_map  = {}   # iid → display name
        self._populate_aql_library()

        # Bindings
        self._lib_tree.bind('<<TreeviewSelect>>', self._on_lib_select)
        self._lib_tree.bind('<Double-1>',          self._on_lib_double_click)
        self._lib_tree.bind('<Return>',            self._on_lib_double_click)

    def _populate_aql_library(self, filter_text=''):
        """Build / rebuild the AQL library tree, optionally filtered."""
        self._lib_tree.delete(*self._lib_tree.get_children())
        self._lib_sql_map.clear()
        self._lib_name_map.clear()
        ft = filter_text.lower()

        group_icons = {
            'Business Analysts': '📊',
            'Procurement Officers': '📋',
            'Data Engineers': '⚙️',
            'SRE': '🔴',
            'Finance': '💰',
            'CRUD': '📝',
        }

        for group_label, subcats in _AQL_LIBRARY:
            # Collect matching items for this group first
            group_matches = []
            for sub_label, items in subcats:
                sub_matches = []
                for name, sql in items:
                    if ft and ft not in name.lower() and ft not in sql.lower():
                        continue
                    sub_matches.append((name, sql))
                if sub_matches:
                    group_matches.append((sub_label, sub_matches))

            if not group_matches:
                continue

            g_iid = self._lib_tree.insert(
                '', tk.END, text=f"  {group_label}",
                open=bool(ft),
                tags=('group',)
            )
            for sub_label, sub_matches in group_matches:
                s_iid = self._lib_tree.insert(
                    g_iid, tk.END, text=f"    {sub_label}",
                    open=bool(ft),
                    tags=('subgroup',)
                )
                for name, sql in sub_matches:
                    i_iid = self._lib_tree.insert(
                        s_iid, tk.END, text=f"      {name}",
                        tags=('item',)
                    )
                    self._lib_sql_map[i_iid]  = sql
                    self._lib_name_map[i_iid] = name

        self._lib_tree.tag_configure('group',    font=('Segoe UI', 9, 'bold'), foreground=ACCENT2)
        self._lib_tree.tag_configure('subgroup', font=('Segoe UI', 9, 'bold'), foreground=WARNING)
        self._lib_tree.tag_configure('item',     font=('Consolas', 9),         foreground=FG)

    def _filter_aql_library(self):
        self._populate_aql_library(self._lib_filter_var.get())

    def _selected_lib_sql(self):
        """Return (name, sql) for the currently selected tree item, or (None, None)."""
        sel = self._lib_tree.selection()
        if not sel:
            return None, None
        iid = sel[0]
        return self._lib_name_map.get(iid), self._lib_sql_map.get(iid)

    def _on_lib_select(self, event=None):
        """Update preview pane when a library item is selected."""
        name, sql = self._selected_lib_sql()
        self._lib_preview.config(state=tk.NORMAL)
        self._lib_preview.delete('1.0', tk.END)
        if sql:
            self._lib_preview.insert('1.0', sql)
        self._lib_preview.config(state=tk.DISABLED)

    def _on_lib_double_click(self, event=None):
        """Load selected SQL into Workbench editor and switch to Workbench tab."""
        name, sql = self._selected_lib_sql()
        if not sql:
            return
        self.query_text.delete('1.0', tk.END)
        self.query_text.insert('1.0', f"-- {name}\n{sql}\n")
        self.nb.select(0)   # switch to Workbench tab (index 0)
        self.query_text.focus_set()
        self.status_var.set(f"Loaded: {name}  — press F5 to execute")

    def _aql_lib_load(self):
        """Button: Load → Workbench."""
        self._on_lib_double_click()

    def _aql_lib_copy(self):
        """Button: copy selected SQL to clipboard."""
        _, sql = self._selected_lib_sql()
        if sql:
            self.clipboard_clear()
            self.clipboard_append(sql)
            self.status_var.set("SQL copied to clipboard")

    def _create_connections_tab(self, parent):
        """Connections tab: table of all service credentials from flux config."""
        style = ttk.Style()
        style.configure("Conn.Treeview", background=BG3, foreground=FG,
                        fieldbackground=BG3, rowheight=22, font=('Segoe UI', 9))
        style.configure("Conn.Treeview.Heading", background=BG2, foreground=FG,
                        font=('Segoe UI', 9, 'bold'), relief='flat')
        style.map("Conn.Treeview", background=[('selected', ACCENT)])

        hdr = tk.Frame(parent, bg=BG2)
        hdr.pack(fill=tk.X, padx=5, pady=(5, 0))
        tk.Label(hdr, text="Service Credentials  ", font=('Segoe UI', 11, 'bold'),
                 fg=FG, bg=BG2).pack(side=tk.LEFT, padx=5)
        tk.Label(hdr, text="(encrypted passwords from flux config — not decrypted)",
                 font=('Segoe UI', 9), fg='#888', bg=BG2).pack(side=tk.LEFT)

        # Search filter
        filter_frame = tk.Frame(parent, bg=BG2)
        filter_frame.pack(fill=tk.X, padx=5, pady=(2, 4))
        tk.Label(filter_frame, text="Filter:", bg=BG2, fg=FG).pack(side=tk.LEFT, padx=(5, 2))
        self._conn_filter_var = tk.StringVar()
        self._conn_filter_var.trace_add('write', lambda *_: self._filter_conn_table())
        tk.Entry(filter_frame, textvariable=self._conn_filter_var, width=40,
                 font=('Segoe UI', 9), bg=BG3, fg=FG, insertbackground=FG,
                 relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        tk.Label(filter_frame, text="(filter by namespace, service, or user)",
                 font=('Segoe UI', 8), fg='#888', bg=BG2).pack(side=tk.LEFT)

        cols = ('env', 'namespace', 'service', 'user', 'database', 'enc_password')
        table_frame = tk.Frame(parent, bg=BG2)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        sb_y = tk.Scrollbar(table_frame, orient=tk.VERTICAL)
        sb_y.pack(side=tk.RIGHT, fill=tk.Y)
        sb_x = tk.Scrollbar(table_frame, orient=tk.HORIZONTAL)
        sb_x.pack(side=tk.BOTTOM, fill=tk.X)

        self._conn_tree = ttk.Treeview(
            table_frame, columns=cols, show='headings', style='Conn.Treeview',
            yscrollcommand=sb_y.set, xscrollcommand=sb_x.set
        )
        self._conn_tree.pack(fill=tk.BOTH, expand=True)
        sb_y.config(command=self._conn_tree.yview)
        sb_x.config(command=self._conn_tree.xview)

        widths = {'env': 85, 'namespace': 90, 'service': 180, 'user': 160,
                  'database': 80, 'enc_password': 400}
        for col in cols:
            self._conn_tree.heading(col, text=col.replace('_', ' ').title())
            self._conn_tree.column(col, width=widths.get(col, 120), minwidth=60, stretch=(col=='enc_password'))

        self._conn_all_rows = []
        self._load_conn_table()
        add_treeview_menu(self._conn_tree)

    def _load_conn_table(self):
        """Populate the connections table from db_connections.yaml service_credentials."""
        try:
            import yaml as _yaml
            preset = os.path.normpath(self._preset_file)
            with open(preset) as f:
                data = _yaml.safe_load(f)
            rows = []
            for r in data.get('service_credentials', []):
                rows.append((
                    r.get('env',''), r.get('namespace',''), r.get('service',''),
                    r.get('user',''), r.get('database',''), r.get('enc_password','')
                ))
            self._conn_all_rows = rows
            self._populate_conn_tree(rows)
        except Exception as e:
            print(f'[DB Widget] conn table load error: {e}')

    def _populate_conn_tree(self, rows):
        self._conn_tree.delete(*self._conn_tree.get_children())
        for row in rows:
            env = row[0]
            tag = 'dev' if env == 'development' else 'stage'
            self._conn_tree.insert('', tk.END, values=row, tags=(tag,))
        self._conn_tree.tag_configure('dev',   background='#152b15', foreground=FG)
        self._conn_tree.tag_configure('stage', background='#15152b', foreground=FG)

    def _filter_conn_table(self):
        q = self._conn_filter_var.get().lower().strip()
        if not q:
            self._populate_conn_tree(self._conn_all_rows)
            return
        filtered = [r for r in self._conn_all_rows
                    if any(q in str(v).lower() for v in r)]
        self._populate_conn_tree(filtered)

    def _create_workbench_tab(self, parent):
        """Workbench tab: connection picker + schema browser + query editor + results."""
        # Status bar at bottom
        self._create_status_bar(parent)

        # Connection bar at top
        self._create_connection_panel(parent)

        # Split pane: schema | query+results
        paned = tk.PanedWindow(parent, orient=tk.HORIZONTAL, bg=BG2, sashwidth=3)
        paned.pack(fill=tk.BOTH, expand=True, pady=(5, 0))

        self._create_schema_panel(paned)

        query_frame = tk.Frame(paned, bg=BG)
        self._create_query_panel(query_frame)
        self._create_results_panel(query_frame)

        paned.add(self.schema_frame, width=250)
        paned.add(query_frame)

    def _create_connection_panel(self, parent):
        """Compact connection bar for Workbench tab."""
        conn_frame = tk.Frame(parent, bg=BG2)
        conn_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(conn_frame, text="Connection:", font=('Segoe UI', 10, 'bold'),
                 fg=FG, bg=BG2).grid(row=0, column=0, sticky=tk.W, padx=5, pady=4)

        self.saved_conn_var = tk.StringVar()
        self.saved_conn_combo = ttk.Combobox(
            conn_frame, textvariable=self.saved_conn_var, width=32, state="readonly",
            font=('Segoe UI', 10)
        )
        self.saved_conn_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=4)
        self.saved_conn_combo.bind('<<ComboboxSelected>>', self._on_saved_conn_selected)
        self._update_saved_connections_combo()

        tk.Label(conn_frame, text="User:", font=('Segoe UI', 10), fg=FG, bg=BG2).grid(
            row=0, column=2, sticky=tk.W, padx=(15,5), pady=4)
        self.user_var = tk.StringVar(value='selector')
        tk.Entry(conn_frame, textvariable=self.user_var, width=16,
                 font=('Segoe UI', 10), bg=BG3, fg=FG).grid(row=0, column=3, padx=5, pady=4)

        tk.Label(conn_frame, text="Password:", font=('Segoe UI', 10), fg=FG, bg=BG2).grid(
            row=0, column=4, sticky=tk.W, padx=(15,5), pady=4)
        self.password_var = tk.StringVar()
        tk.Entry(conn_frame, textvariable=self.password_var, width=16, show='*',
                 font=('Segoe UI', 10), bg=BG3, fg=FG).grid(row=0, column=5, padx=5, pady=4)

        tk.Button(conn_frame, text="Connect", command=self.connect,
                  bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                  relief=tk.FLAT, padx=12).grid(row=0, column=6, padx=5, pady=4)
        tk.Button(conn_frame, text="Disconnect", command=self.disconnect,
                  bg=ERROR, fg='white', font=('Segoe UI', 10, 'bold'),
                  relief=tk.FLAT, padx=12).grid(row=0, column=7, padx=5, pady=4)

        # Hidden vars needed by connect() logic
        self.db_type_var = tk.StringVar(value='postgresql')
        self.host_var    = tk.StringVar(value='')
        self.port_var    = tk.StringVar(value='5432')
        self.database_var = tk.StringVar(value='')

    def _create_schema_panel(self, parent):
        """Create schema browser"""
        self.schema_frame = tk.Frame(parent, bg=BG2)
        
        tk.Label(
            self.schema_frame, text="Schema Browser", font=('Segoe UI', 11, 'bold'),
            fg=FG, bg=BG2
        ).pack(fill=tk.X, padx=5, pady=5)
        
        # Treeview for schema
        tree_frame = tk.Frame(self.schema_frame, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.schema_tree = ttk.Treeview(tree_frame, yscrollcommand=scrollbar.set, selectmode='browse')
        self.schema_tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.schema_tree)
        scrollbar.config(command=self.schema_tree.yview)
        
        # Style the treeview
        style = ttk.Style()
        style.configure("Treeview", background=BG3, foreground=FG, fieldbackground=BG3)
        style.configure("Treeview.Heading", background=BG2, foreground=FG, relief=tk.FLAT)
        
        self.schema_tree.bind('<Double-1>', self._on_schema_double_click)
        
        # Refresh button
        tk.Button(
            self.schema_frame, text="Refresh Schema", command=self.load_schema,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, pady=5
        ).pack(fill=tk.X, padx=5, pady=5)
    
    def _create_query_panel(self, parent):
        """Create query editor with AQL natural-language bar."""
        query_frame = tk.Frame(parent, bg=BG)
        query_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ── Header row ──
        header = tk.Frame(query_frame, bg=BG2)
        header.pack(fill=tk.X, pady=(0, 5))

        tk.Label(header, text="SQL Query Editor", font=('Segoe UI', 11, 'bold'), fg=FG, bg=BG2).pack(
            side=tk.LEFT, padx=5, pady=5
        )

        tk.Button(
            header, text="Execute (F5)", command=self.execute_query, bg=SUCCESS, fg='black',
            font=('Segoe UI', 10, 'bold'), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.RIGHT, padx=5)

        tk.Button(
            header, text="Clear", command=self._clear_query, bg=BG3, fg=FG,
            font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.RIGHT, padx=5)

        tk.Button(
            header, text="Load File", command=self._load_query_file, bg=BG3, fg=FG,
            font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.RIGHT, padx=5)

        # ── AQL bar ──
        aql_frame = tk.Frame(query_frame, bg=BG2)
        aql_frame.pack(fill=tk.X, pady=(0, 4))

        tk.Label(aql_frame, text="AQL", font=('Segoe UI', 9, 'bold'),
                 fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, padx=(8, 4))
        self._aql_var = tk.StringVar()
        self._aql_entry = tk.Entry(
            aql_frame, textvariable=self._aql_var, font=('Segoe UI', 10),
            bg=BG3, fg=FG, insertbackground=FG, relief=tk.FLAT
        )
        self._aql_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4, ipady=4)
        self._aql_entry.bind('<Return>', lambda e: self._run_aql())
        self._aql_entry.bind('<FocusIn>', lambda e: self._aql_entry.config(
            highlightthickness=1, highlightbackground=ACCENT2, highlightcolor=ACCENT2))
        self._aql_entry.bind('<FocusOut>', lambda e: self._aql_entry.config(highlightthickness=0))

        self._aql_btn = tk.Button(
            aql_frame, text=f"Ask {assistant_name()} →", command=self._run_aql,
            bg=ACCENT2, fg='black', font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT, padx=10
        )
        self._aql_btn.pack(side=tk.LEFT, padx=(4, 8))
        tk.Label(aql_frame, text=f"describe what you want — {assistant_name()} writes the SQL",
                 font=('Segoe UI', 8), fg='#666', bg=BG2).pack(side=tk.LEFT)

        # ── Query text area ──
        self.query_text = scrolledtext.ScrolledText(
            query_frame, height=10, wrap=tk.NONE, bg=BG3, fg=FG,
            font=('Consolas', 11), insertbackground=FG
        )
        self.query_text.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(self.query_text)
        self.query_text.bind('<F5>',           lambda e: self.execute_query() or 'break')
        self.query_text.bind('<Control-Up>',   self._on_ctrl_up)
        self.query_text.bind('<Control-Down>', self._on_ctrl_down)

        # Add syntax highlighting if available
        if PYGMENTS_AVAILABLE:
            self.query_text.bind('<KeyRelease>', self._highlight_sql)
            self._setup_syntax_tags()

    # ── AQL: Auger Query Language ─────────────────────────────────────────────

    # ── AQL history navigation ────────────────────────────────────────────────

    def _on_ctrl_up(self, event):
        self._history_up()
        return 'break'

    def _on_ctrl_down(self, event):
        self._history_down()
        return 'break'

    def _history_up(self):
        """Navigate to the previous AQL history entry (Ctrl+Up)."""
        if not self.aql_history:
            return
        if self.aql_history_index == -1:
            # Save whatever is currently in the editor
            self._aql_history_draft = self.query_text.get('1.0', tk.END).rstrip('\n')
            self.aql_history_index = len(self.aql_history) - 1
        elif self.aql_history_index > 0:
            self.aql_history_index -= 1
        self._load_history_entry()

    def _history_down(self):
        """Navigate to the next AQL history entry (Ctrl+Down)."""
        if self.aql_history_index == -1:
            return
        if self.aql_history_index < len(self.aql_history) - 1:
            self.aql_history_index += 1
            self._load_history_entry()
        else:
            # Past end of history — restore the draft
            self.aql_history_index = -1
            self.query_text.delete('1.0', tk.END)
            self.query_text.insert('1.0', self._aql_history_draft)
            self.query_text.mark_set(tk.INSERT, tk.END)
            self.status_var.set("AQL history: end (showing draft)")

    def _load_history_entry(self):
        self.query_text.delete('1.0', tk.END)
        entry = self.aql_history[self.aql_history_index]
        self.query_text.insert('1.0', entry)
        self.query_text.mark_set(tk.INSERT, tk.END)
        total = len(self.aql_history)
        idx = self.aql_history_index + 1
        self.status_var.set(f"AQL history [{idx}/{total}] — Ctrl+↑/↓ to navigate, F5 to run")


    def _get_schema_context(self):
        """Return a compact schema summary for AQL prompts.

        Tree structure: 📁 schema_name
                          📋 Tables (N)
                            📄 table_name
                          👁️ Views (N)
                            👁️ view_name
        """
        if not self.current_connection:
            return "(not connected)"
        conn = self.current_connection
        lines = [
            f"Database: {conn.get('type','postgresql')} — {conn.get('host','')} db={conn.get('database','')}",
            "Tables and views:"
        ]
        try:
            for schema_node in self.schema_tree.get_children():
                schema_text = self.schema_tree.item(schema_node)['text']
                schema_name = schema_text.replace('📁', '').strip()
                for group_node in self.schema_tree.get_children(schema_node):
                    group_text = self.schema_tree.item(group_node)['text']
                    kind = 'view' if '👁' in group_text else 'table'
                    for obj_node in self.schema_tree.get_children(group_node):
                        obj_text = self.schema_tree.item(obj_node)['text']
                        name = obj_text.replace('📄', '').replace('👁️', '').strip()
                        lines.append(f"  {schema_name}.{name} ({kind})")
        except Exception:
            pass
        if len(lines) <= 2:
            return "(schema not loaded — connect and click Refresh Schema first)"
        return "\n".join(lines)

    def _run_aql(self):
        """Translate AQL natural-language request → SQL via the assistant CLI, stream into editor."""
        prompt_text = self._aql_var.get().strip()
        if not prompt_text:
            self._aql_entry.focus_set()
            return

        schema = self._get_schema_context()
        full_prompt = (
            f"You are a PostgreSQL expert. Given this database schema:\n\n{schema}\n\n"
            f"Write a single SQL query (no explanation, just the SQL) to: {prompt_text}\n\n"
            f"Output ONLY valid SQL. No markdown fences, no commentary."
        )

        # MAX_ARG_STRLEN on Linux = 128KB per argument. Truncate schema if needed.
        MAX_PROMPT = 120_000
        if len(full_prompt.encode()) > MAX_PROMPT:
            # Rebuild with truncated schema
            budget = MAX_PROMPT - len(prompt_text.encode()) - 300
            schema_trunc = schema.encode()[:budget].decode('utf-8', errors='ignore')
            full_prompt = (
                f"You are a PostgreSQL expert. Given this database schema (truncated):\n\n{schema_trunc}\n\n"
                f"Write a single SQL query (no explanation, just the SQL) to: {prompt_text}\n\n"
                f"Output ONLY valid SQL. No markdown fences, no commentary."
            )

        self._aql_btn.config(text="…thinking", state=tk.DISABLED, bg=BG3, fg='#888')
        self.status_var.set(f"AQL: {prompt_text[:60]}…")
        self.query_text.delete('1.0', tk.END)
        self.query_text.insert('1.0', f"-- AQL: {prompt_text}\n")

        def _on_chunk(chunk):
            self.after(0, lambda c=chunk: self.query_text.insert(tk.END, c))

        def _on_done(full):
            def _finish():
                # Strip markdown fences if Auger wrapped it anyway
                raw = self.query_text.get('1.0', tk.END)
                cleaned = re.sub(r'```(?:sql)?\n?', '', raw, flags=re.IGNORECASE).replace('```', '').strip()
                # Strip all known Copilot CLI / assistant session metadata lines
                cleaned = _CLI_METADATA_RE.sub('', cleaned)
                # Strip any trailing pipe-table rows the CLI may emit
                cleaned = re.sub(r'(?m)^\s*\|[^\n]*\n?', '', cleaned)
                cleaned = cleaned.strip()
                # Keep the AQL comment header
                header_end = cleaned.find('\n')
                header = cleaned[:header_end+1] if header_end != -1 else ''
                sql_body = cleaned[header_end+1:].strip() if header_end != -1 else cleaned
                self.query_text.delete('1.0', tk.END)
                self.query_text.insert('1.0', header + '\n' + sql_body + '\n')
                self._aql_btn.config(text=f"Ask {assistant_name()} →", state=tk.NORMAL, bg=ACCENT2, fg='black')
                self._aql_var.set('')
                self.status_var.set("✓ AQL complete — review SQL and press F5 to execute")
            self.after(0, _finish)

        def _on_error(err):
            self.after(0, lambda: self.query_text.insert(tk.END, f"\n-- Error: {err}"))
            self.after(0, lambda: self._aql_btn.config(text=f"Ask {assistant_name()} →", state=tk.NORMAL, bg=ACCENT2, fg='black'))

        self._stream_ask(full_prompt, _on_chunk, _on_done, _on_error)

    def _stream_ask(self, prompt, on_chunk, on_done, on_error):
        """Stream a prompt through copilot directly via Python subprocess (no shell wrapper)."""
        import subprocess

        def _build_env():
            # Use a minimal environment — passing all of os.environ can exceed
            # execve's combined argv+envp limit in some container configs
            token = None
            for key in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
                token = os.environ.get(key)
                if token:
                    break
            # Also check the runtime .env for tokens
            env_file = state_dir() / ".env"
            if not token and env_file.exists():
                for line in env_file.read_text().splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, _, v = line.partition("=")
                        k, v = k.strip(), v.strip().strip('"').strip("'")
                        if k in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN") and v:
                            token = v
                            break
            env = {
                "HOME":                 str(_auger_home()),
                "PATH":                 os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "USER":                 os.environ.get("USER", ""),
                "TERM":                 "xterm-256color",
                "AUGER_CHAT_SOURCE":    "database_aql",
            }
            if token:
                env["COPILOT_GITHUB_TOKEN"] = token
                env["GH_TOKEN"] = token
                env["GITHUB_TOKEN"] = token
            # Pass through SSL/proxy vars if set (needed in corporate environments)
            for k in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE", "CURL_CA_BUNDLE",
                      "PIP_CERT", "http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
                      "no_proxy", "NO_PROXY"):
                if k in os.environ:
                    env[k] = os.environ[k]
            return env

        def _run():
            copilot_bin = shutil.which("copilot") or "/usr/local/bin/copilot"
            env = _build_env()
            env_size = sum(len(k)+len(v)+2 for k,v in env.items())
            prompt_size = len(prompt.encode())
            # Write debug to file (print goes to /dev/null in GUI process)
            try:
                dbg = state_dir() / "aql_debug.log"
                with open(dbg, "w") as f:
                    f.write(f"prompt_size={prompt_size}\nenv_size={env_size}\ncopilot={copilot_bin}\n")
                    f.write(f"PATH={os.environ.get('PATH','')}\n")
                    f.write(f"env keys: {list(env.keys())}\n")
                    f.write(f"prompt[:200]: {repr(prompt[:200])}\n")
                    f.write(f"full_env_size: {sum(len(k)+len(v)+2 for k,v in os.environ.items())}\n")
            except Exception:
                pass
            try:
                # Pass prompt directly as Python list — no shell, no bash expansion,
                # no $(cat) — avoids "Argument list too long" entirely
                proc = subprocess.Popen(
                    [copilot_bin, "-p", prompt, "--allow-all"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env=env
                )
                full = ""
                for line in proc.stdout:
                    clean = re.sub(r"\x1b\[[0-9;]*[mKJH]", "", line)
                    full += clean
                    on_chunk(clean)
                proc.wait()
                on_done(full)
            except Exception as e:
                try:
                    dbg = state_dir() / "aql_debug.log"
                    with open(dbg, "a") as f:
                        f.write(f"\nEXCEPTION: {e}\n")
                except Exception:
                    pass
                on_error(str(e))

        threading.Thread(target=_run, daemon=True).start()
    
    def _create_results_panel(self, parent):
        """Create results display"""
        results_frame = tk.Frame(parent, bg=BG)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Header
        header = tk.Frame(results_frame, bg=BG2)
        header.pack(fill=tk.X, pady=(0, 5))
        
        self.results_label = tk.Label(
            header, text="Results", font=('Segoe UI', 11, 'bold'), fg=FG, bg=BG2
        )
        self.results_label.pack(side=tk.LEFT, padx=5, pady=5)
        
        tk.Button(
            header, text="Export CSV", command=self._export_results, bg=BG3, fg=FG,
            font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.RIGHT, padx=5)
        
        # Results treeview with horizontal scroll
        tree_container = tk.Frame(results_frame, bg=BG2)
        tree_container.pack(fill=tk.BOTH, expand=True)
        
        vsb = tk.Scrollbar(tree_container, orient="vertical")
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        
        hsb = tk.Scrollbar(tree_container, orient="horizontal")
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.results_tree = ttk.Treeview(
            tree_container, yscrollcommand=vsb.set, xscrollcommand=hsb.set
        )
        self.results_tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.results_tree)
        
        vsb.config(command=self.results_tree.yview)
        hsb.config(command=self.results_tree.xview)
    
    def _create_status_bar(self, parent):
        """Create status bar"""
        status_frame = tk.Frame(parent, bg=BG2)
        status_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.status_var = tk.StringVar(value="Not connected")
        tk.Label(
            status_frame, textvariable=self.status_var, font=('Segoe UI', 9),
            fg=FG, bg=BG2, anchor=tk.W
        ).pack(side=tk.LEFT, padx=5, pady=3)
        
        self.query_time_var = tk.StringVar(value="")
        tk.Label(
            status_frame, textvariable=self.query_time_var, font=('Segoe UI', 9),
            fg=ACCENT, bg=BG2, anchor=tk.E
        ).pack(side=tk.RIGHT, padx=5, pady=3)
    
    def _setup_syntax_tags(self):
        """Setup syntax highlighting tags"""
        self.query_text.tag_configure('keyword', foreground='#569cd6')
        self.query_text.tag_configure('string', foreground='#ce9178')
        self.query_text.tag_configure('comment', foreground='#6a9955')
        self.query_text.tag_configure('number', foreground='#b5cea8')
        self.query_text.tag_configure('operator', foreground='#d4d4d4')
    
    def _highlight_sql(self, event=None):
        """Apply SQL syntax highlighting"""
        if not PYGMENTS_AVAILABLE:
            return
        
        # Simple debouncing - only highlight if idle for 500ms
        if hasattr(self, '_highlight_timer'):
            self.after_cancel(self._highlight_timer)
        
        self._highlight_timer = self.after(500, self._do_highlight)
    
    def _do_highlight(self):
        """Perform syntax highlighting"""
        content = self.query_text.get('1.0', tk.END)
        
        # Remove existing tags
        for tag in ['keyword', 'string', 'comment', 'number', 'operator']:
            self.query_text.tag_remove(tag, '1.0', tk.END)
        
        # Apply new tags
        tokens = lex(content, SqlLexer())
        line, col = 1, 0
        
        for token_type, value in tokens:
            start = f"{line}.{col}"
            col += len(value)
            if '\n' in value:
                line += value.count('\n')
                col = len(value.split('\n')[-1])
            end = f"{line}.{col}"
            
            if token_type in Token.Keyword:
                self.query_text.tag_add('keyword', start, end)
            elif token_type in Token.String:
                self.query_text.tag_add('string', start, end)
            elif token_type in Token.Comment:
                self.query_text.tag_add('comment', start, end)
            elif token_type in Token.Number:
                self.query_text.tag_add('number', start, end)
            elif token_type in Token.Operator:
                self.query_text.tag_add('operator', start, end)
    
    def _on_db_type_changed(self, event=None):
        """Update default port when database type changes"""
        db_type = self.db_type_var.get()
        ports = {
            'postgresql': '5432',
            'mysql': '3306',
            'sqlserver': '1433',
            'oracle': '1521',
            'sqlite': ''
        }
        self.port_var.set(ports.get(db_type, ''))
    
    def _on_saved_conn_selected(self, event=None):
        """Load selected saved connection"""
        conn_name = self.saved_conn_var.get()
        if conn_name and conn_name in self.saved_connections:
            conn = self.saved_connections[conn_name]
            self.db_type_var.set(conn.get('type', 'postgresql'))
            self.host_var.set(conn.get('host', 'localhost'))
            self.port_var.set(str(conn.get('port', '5432')))
            self.database_var.set(conn.get('database', ''))
            user = conn.get('user', 'selector')
            self.user_var.set(user)
            if user == 'selector':
                self.password_var.set(self._load_selector_password() or '')
            else:
                self.password_var.set('')
            self.status_var.set(f"Loaded: {conn_name} — ready to connect")
    
    def _on_schema_double_click(self, event):
        """Handle double-click on schema tree"""
        selection = self.schema_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        values = self.schema_tree.item(item)
        text = values.get('text', '')
        parent = self.schema_tree.parent(item)
        
        # If it's a table, generate SELECT query
        if parent and not self.schema_tree.parent(parent):
            table_name = text.split(' ')[0]  # Remove emoji
            query = f"SELECT * FROM {table_name} LIMIT 100;"
            self.query_text.delete('1.0', tk.END)
            self.query_text.insert('1.0', query)
    
    def _load_connections(self):
        """Load connections: merge pre-populated presets with user-saved overrides."""
        connections = {}

        # 1. Load pre-populated connections from auger/data/db_connections.yaml
        preset_path = getattr(self, '_preset_file',
                              os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'db_connections.yaml'))
        preset_path = os.path.normpath(preset_path)
        if os.path.exists(preset_path):
            try:
                import yaml as _yaml
                with open(preset_path) as f:
                    data = _yaml.safe_load(f)
                for conn in (data or {}).get('workbench', (data or {}).get('connections', [])):
                    name = conn.get('label', conn.get('name', ''))
                    if name:
                        connections[name] = {
                            'type':     conn.get('type', 'postgresql'),
                            'host':     conn.get('host', ''),
                            'port':     str(conn.get('port', 5432)),
                            'database': conn.get('database', ''),
                            'user':     conn.get('default_user', 'selector'),
                            'ssl_mode': conn.get('ssl_mode', 'require'),
                            '_preset':  True,
                        }
            except ImportError:
                pass  # yaml not available, skip presets
            except Exception as e:
                print(f"[DB Widget] Error loading presets: {e}")

        # 2. Load user-saved connections (override presets if same name)
        if os.path.exists(self.connections_file):
            try:
                with open(self.connections_file, 'r') as f:
                    user_conns = json.load(f)
                connections.update(user_conns)
            except Exception as e:
                print(f"[DB Widget] Error loading user connections: {e}")

        return connections
    
    def _save_connections(self):
        """Save connections to file"""
        try:
            with open(self.connections_file, 'w') as f:
                json.dump(self.saved_connections, f, indent=2)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save connections: {e}")
    
    def _update_saved_connections_combo(self):
        """Update saved connections dropdown"""
        names = list(self.saved_connections.keys())
        self.saved_conn_combo['values'] = names
    
    def _save_connection(self):
        """Save current connection details"""
        name = tk.simpledialog.askstring("Save Connection", "Enter connection name:")
        if not name:
            return
        
        self.saved_connections[name] = {
            'type': self.db_type_var.get(),
            'host': self.host_var.get(),
            'port': self.port_var.get(),
            'database': self.database_var.get(),
            'user': self.user_var.get()
            # Don't save password for security
        }
        
        self._save_connections()
        self._update_saved_connections_combo()
        messagebox.showinfo("Success", f"Connection '{name}' saved!")
    
    def _clear_query(self):
        """Clear query editor"""
        self.query_text.delete('1.0', tk.END)
    
    def _load_query_file(self):
        """Load SQL file into editor"""
        filename = filedialog.askopenfilename(
            title="Load SQL File",
            filetypes=[("SQL Files", "*.sql"), ("All Files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'r') as f:
                    content = f.read()
                    self.query_text.delete('1.0', tk.END)
                    self.query_text.insert('1.0', content)
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load file: {e}")
    
    def _export_results(self):
        """Export results to CSV"""
        if not hasattr(self, 'last_results') or not self.last_results:
            messagebox.showwarning("No Data", "No results to export")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Export Results",
            defaultextension=".csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        
        if filename:
            try:
                with open(filename, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(self.last_columns)
                    writer.writerows(self.last_results)
                messagebox.showinfo("Success", f"Results exported to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to export: {e}")
    
    def _load_selector_password(self):
        """Read DB_SELECTOR_PASSWORD from the runtime .env if present."""
        env_file = state_dir() / '.env'
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DB_SELECTOR_PASSWORD='):
                        return line.split('=', 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass
        return None

    def _save_selector_password(self, password):
        """Persist DB_SELECTOR_PASSWORD to the runtime .env."""
        env_file = state_dir() / '.env'
        try:
            lines = []
            try:
                with open(env_file) as f:
                    lines = f.readlines()
            except FileNotFoundError:
                pass
            new_lines = []
            found = False
            for line in lines:
                if line.strip().startswith('DB_SELECTOR_PASSWORD='):
                    new_lines.append('DB_SELECTOR_PASSWORD="' + password + '"\n')
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append('DB_SELECTOR_PASSWORD="' + password + '"\n')
            with open(env_file, 'w') as f:
                f.writelines(new_lines)
        except Exception as e:
            print(f'[DB Widget] could not save selector password: {e}')

    def connect(self):
        """Connect to database — auto-load/prompt/save selector password."""
        if not SQLALCHEMY_AVAILABLE:
            messagebox.showerror("Error", "SQLAlchemy not installed. Run: pip install sqlalchemy")
            return

        user = self.user_var.get().strip()
        if user == 'selector':
            pwd = self.password_var.get()
            if not pwd:
                saved = self._load_selector_password()
                if saved:
                    pwd = saved
                    self.password_var.set(pwd)
                else:
                    from tkinter import simpledialog
                    pwd = simpledialog.askstring(
                        "Selector Password",
                        f"Enter password for the 'selector' user:\n(saved to {state_dir() / '.env'} — won't ask again)",
                        show='*', parent=self
                    )
                    if not pwd:
                        self.status_var.set("Connection cancelled — no password entered")
                        return
                    self.password_var.set(pwd)
            # Always persist — covers the case where user typed it manually
            self._save_selector_password(pwd)

        self.status_var.set("Connecting...")
        threading.Thread(target=self._connect_thread, daemon=True).start()
    
    def _connect_thread(self):
        """Connect to database in background thread"""
        try:
            db_type = self.db_type_var.get()
            host = self.host_var.get()
            port = self.port_var.get()
            database = self.database_var.get()
            user = self.user_var.get()
            password = self.password_var.get()
            
            # Build connection string
            if db_type == 'sqlite':
                conn_str = f"sqlite:///{database}"
            elif db_type == 'postgresql':
                conn_str = f"postgresql://{user}:{password}@{host}:{port}/{database}"
            elif db_type == 'mysql':
                conn_str = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
            elif db_type == 'sqlserver':
                conn_str = f"mssql+pyodbc://{user}:{password}@{host}:{port}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
            elif db_type == 'oracle':
                conn_str = f"oracle+cx_oracle://{user}:{password}@{host}:{port}/{database}"
            else:
                raise ValueError(f"Unsupported database type: {db_type}")
            
            # Create engine
            self.current_engine = create_engine(conn_str)
            
            # Test connection
            with self.current_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            
            self.current_connection = {
                'type': db_type,
                'host': host,
                'port': port,
                'database': database,
                'user': user
            }
            
            self.after(0, lambda: self.status_var.set(
                f"✓ Connected to {db_type}://{host}:{port}/{database} as {user}"
            ))
            self.after(0, self.load_schema)
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Connection failed: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Connection Error", str(e)))
    
    def disconnect(self):
        """Disconnect from database"""
        if self.current_engine:
            self.current_engine.dispose()
            self.current_engine = None
            self.current_connection = None
            self.status_var.set("Disconnected")
            
            # Clear schema tree
            for item in self.schema_tree.get_children():
                self.schema_tree.delete(item)
    
    def load_schema(self):
        """Load database schema"""
        if not self.current_engine:
            messagebox.showwarning("Not Connected", "Please connect to a database first")
            return
        
        self.status_var.set("Loading schema...")
        threading.Thread(target=self._load_schema_thread, daemon=True).start()
    
    def _load_schema_thread(self):
        """Load schema in background thread"""
        try:
            inspector = inspect(self.current_engine)
            
            # Get schemas or just tables
            try:
                schemas = inspector.get_schema_names()
            except:
                schemas = [None]  # Some databases don't support schemas
            
            schema_data = {}
            
            for schema in schemas:
                if schema in ('information_schema', 'pg_catalog', 'pg_toast'):
                    continue  # Skip system schemas
                
                tables = inspector.get_table_names(schema=schema)
                views = inspector.get_view_names(schema=schema)
                
                schema_data[schema or 'default'] = {
                    'tables': tables,
                    'views': views
                }
            
            # Update UI
            self.after(0, lambda: self._display_schema(schema_data))
            
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Schema Error", str(e)))
            self.after(0, lambda: self.status_var.set(f"✗ Schema load failed: {str(e)}"))
    
    def _display_schema(self, schema_data):
        """Display schema in tree"""
        # Clear tree
        for item in self.schema_tree.get_children():
            self.schema_tree.delete(item)
        
        # Add schemas/tables/views
        for schema_name, data in schema_data.items():
            schema_id = self.schema_tree.insert('', 'end', text=f"📁 {schema_name}", open=True)
            
            if data['tables']:
                tables_id = self.schema_tree.insert(schema_id, 'end', text=f"📋 Tables ({len(data['tables'])})", open=True)
                for table in sorted(data['tables']):
                    self.schema_tree.insert(tables_id, 'end', text=f"📄 {table}")
            
            if data['views']:
                views_id = self.schema_tree.insert(schema_id, 'end', text=f"👁️ Views ({len(data['views'])})", open=True)
                for view in sorted(data['views']):
                    self.schema_tree.insert(views_id, 'end', text=f"👁️ {view}")
        
        self.status_var.set("✓ Schema loaded")
    
    def execute_query(self):
        """Execute SQL query"""
        if not self.current_engine:
            messagebox.showwarning("Not Connected", "Please connect to a database first")
            return
        
        query = self.query_text.get('1.0', tk.END).strip()
        if not query:
            messagebox.showwarning("No Query", "Please enter a SQL query")
            return

        # Final safety pass: strip any Auger/Copilot CLI metadata that slipped through
        query = _CLI_METADATA_RE.sub('', query).strip()

        # Save to AQL history (skip if identical to most recent entry)
        if query and (not self.aql_history or self.aql_history[-1] != query):
            self.aql_history.append(query)
        self.aql_history_index = -1  # reset navigation pointer
        
        self.status_var.set("Executing query...")
        self.query_time_var.set("")
        threading.Thread(target=self._execute_query_thread, args=(query,), daemon=True).start()
    
    def _execute_query_thread(self, query):
        """Execute query in background thread"""
        start_time = datetime.now()
        
        try:
            with self.current_engine.connect() as conn:
                result = conn.execute(text(query))
                
                # Check if it's a SELECT query (has results)
                if result.returns_rows:
                    rows = result.fetchall()
                    columns = list(result.keys())
                    
                    # Store for export
                    self.last_results = [tuple(row) for row in rows]
                    self.last_columns = columns
                    
                    # Update UI
                    elapsed = (datetime.now() - start_time).total_seconds()
                    self.after(0, lambda: self._display_results(columns, rows, elapsed))
                else:
                    # DML/DDL query
                    conn.commit()
                    affected = result.rowcount
                    elapsed = (datetime.now() - start_time).total_seconds()
                    self.after(0, lambda: self._display_dml_result(affected, elapsed))
            
            # Add to history
            self.query_history.append({
                'query': query,
                'timestamp': datetime.now().isoformat(),
                'success': True
            })
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds()
            err_msg = str(e)
            self.after(0, lambda: self.status_var.set("✗ Query failed"))
            self.after(0, lambda: self.query_time_var.set(f"Failed in {elapsed:.2f}s"))
            self.after(0, lambda: self._display_query_error(err_msg))
            
            self.query_history.append({
                'query': query,
                'timestamp': datetime.now().isoformat(),
                'success': False,
                'error': str(e)
            })
    
    def _display_results(self, columns, rows, elapsed):
        """Display query results"""
        # Clear existing results
        self.results_tree.delete(*self.results_tree.get_children())
        
        # Setup columns
        self.results_tree['columns'] = columns
        self.results_tree['show'] = 'headings'
        
        for col in columns:
            self.results_tree.heading(col, text=col)
            self.results_tree.column(col, width=150)
        
        # Add rows
        for row in rows:
            self.results_tree.insert('', 'end', values=row)
        
        # Update status
        self.results_label.config(text=f"Results ({len(rows)} rows)")
        self.status_var.set(f"✓ Query executed successfully")
        self.query_time_var.set(f"{len(rows)} rows in {elapsed:.2f}s")
    
    def _display_dml_result(self, affected, elapsed):
        """Display DML/DDL result"""
        # Clear results
        self.results_tree.delete(*self.results_tree.get_children())
        self.results_tree['columns'] = ['Result']
        self.results_tree['show'] = 'headings'
        self.results_tree.heading('Result', text='Result')
        self.results_tree.insert('', 'end', values=[f"Query executed successfully. {affected} rows affected."])
        
        self.results_label.config(text=f"Results")
        self.status_var.set(f"✓ Query executed successfully")
        self.query_time_var.set(f"{affected} rows affected in {elapsed:.2f}s")
    
    def set_query(self, sql: str):
        """Populate the query editor with SQL (called from Ask Genny)."""
        self.query_text.delete('1.0', tk.END)
        self.query_text.insert('1.0', sql)
        try:
            self._highlight_sql()
        except Exception:
            pass

    def _display_query_error(self, error_msg: str):
        """Show a query error inline in the results panel instead of a popup."""
        self.results_tree.delete(*self.results_tree.get_children())
        self.results_tree['columns'] = ['Error']
        self.results_tree['show'] = 'headings'
        self.results_tree.heading('Error', text='Query Error')
        self.results_tree.column('Error', width=800)
        first_line = error_msg.split('\n')[0][:500]
        self.results_tree.insert('', 'end', values=[first_line])
        if '\n' in error_msg:
            detail = ' | '.join(l.strip() for l in error_msg.split('\n')[1:4] if l.strip())
            if detail:
                self.results_tree.insert('', 'end', values=[detail])
        self.results_label.config(text="Error")

    def build_context(self):
        """Build context for the Ask Genny panel"""
        context = "DATABASE WIDGET CONTEXT\n\n"
        
        if self.current_connection:
            context += "Current Connection:\n"
            conn = self.current_connection
            context += f"  Type: {conn['type']}\n"
            context += f"  Host: {conn['host']}:{conn['port']}\n"
            context += f"  Database: {conn['database']}\n"
            context += f"  User: {conn['user']}\n\n"
        else:
            context += "Status: Not connected to any database\n\n"
        
        # Current query
        query = self.query_text.get('1.0', tk.END).strip()
        if query:
            context += f"Current Query:\n{query}\n\n"
        
        # Last results
        if hasattr(self, 'last_results') and self.last_results:
            context += f"Last Query Results: {len(self.last_results)} rows returned\n"
            context += f"Columns: {', '.join(self.last_columns)}\n\n"
        
        # Recent history
        if self.query_history:
            context += "Recent Query History:\n"
            for i, entry in enumerate(self.query_history[-5:], 1):
                status = "✓" if entry['success'] else "✗"
                context += f"{i}. [{status}] {entry['query'][:100]}...\n"
        
        return context


# Widget registration
def create_widget(parent, context_builder_callback=None):
    """Factory function for widget creation"""
    return DatabaseWidget(parent, context_builder_callback)
