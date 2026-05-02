"""
Tasks Widget — Local task tracker with SQLite CRUD.

DB: ~/.auger/tasks.db
Fields: id, title, description, status, priority, category, created_at, updated_at
"""
import tkinter as tk
from tkinter import ttk, messagebox
import sqlite3
from pathlib import Path
from datetime import datetime, timezone, timedelta

try:
    from auger.ui.utils import add_treeview_menu, make_text_copyable, bind_mousewheel
except ImportError:
    def add_treeview_menu(t, **kw): pass
    def make_text_copyable(t): pass
    def bind_mousewheel(t): pass

_EST = timezone(timedelta(hours=-5), name='EST')

def _now_est() -> str:
    """Current time as ISO string in EST/EDT."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo('America/New_York')).isoformat(timespec='seconds')
    except Exception:
        return datetime.now(_EST).isoformat(timespec='seconds')

def _fmt_est(iso_str: str) -> str:
    """Convert stored ISO datetime to EST display string MM/DD HH:MM."""
    if not iso_str:
        return ''
    try:
        from zoneinfo import ZoneInfo
        ny = ZoneInfo('America/New_York')
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ny).strftime('%m/%d %H:%M')
    except Exception:
        try:
            dt = datetime.fromisoformat(iso_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(_EST).strftime('%m/%d %H:%M')
        except Exception:
            return iso_str[:16]


BG      = '#1e1e1e'
BG2     = '#252526'
BG3     = '#2d2d2d'
BG4     = '#333333'
FG      = '#e0e0e0'
FG2     = '#888888'
ACCENT  = '#007acc'
ACCENT2 = '#4ec9b0'
SUCCESS = '#4ec9b0'
ERROR   = '#f44747'
WARN    = '#f0c040'

_STATUSES   = ['Open', 'In Progress', 'Done', 'Blocked']
_PRIORITIES = ['High', 'Medium', 'Low']

# (row_bg, row_fg) by status
_STATUS_COLORS = {
    'Open':        ('#3a3a3a', '#cccccc'),
    'In Progress': ('#003d7a', '#7ec8ff'),
    'Done':        ('#1a3a2a', '#4ec9b0'),
    'Blocked':     ('#4a1010', '#ff7070'),
}

_PRIORITY_COLORS = {
    'High':   '#f44747',
    'Medium': '#f0c040',
    'Low':    '#4ec9b0',
}

DB_PATH = Path.home() / '.auger' / 'tasks.db'

_SEED_TASKS = [
    {
        'title': 'Story to Prod widget — define scope',
        'category': 'Story to Prod',
        'priority': 'High',
        'status': 'In Progress',
        'description': (
            'Define pipeline stages: Jira → Branch/PR → Build → Image → Flux Config → '
            'Env Status → Prod. Key questions: flux repo location, naming conventions, '
            'deployment doc format, environments.'
        ),
    },
    {
        'title': 'Story to Prod — AI deployment doc generation',
        'category': 'Story to Prod',
        'priority': 'High',
        'status': 'Open',
        'description': (
            'Auger auto-generates release notes from Jira story + PR diff + image changes. '
            'Push to Confluence. Source of truth for deploy.'
        ),
    },
    {
        'title': 'Story to Prod — autonomous Work Story button',
        'category': 'Story to Prod',
        'priority': 'Medium',
        'status': 'Open',
        'description': (
            'One button drives story to prod autonomously. Creates branch, writes code, '
            'opens PR, monitors CI, generates flux PR. Hands off to developer when blocked, '
            'resumes when unblocked.'
        ),
    },
    {
        'title': 'Jira widget — clean up field discovery logging',
        'category': 'Jira Widget',
        'priority': 'Low',
        'status': 'Open',
        'description': (
            'Remove temp jira_fields.log debug code from _on_issue_select now that '
            'customfield_14310/14311 are confirmed.'
        ),
    },
    {
        'title': 'Push Docker image to Artifactory',
        'category': 'Platform',
        'priority': 'Medium',
        'status': 'Open',
        'description': (
            'Container image is many commits behind. Rebuild and push to Artifactory so '
            'container restarts don\'t lose Jira widget work.'
        ),
    },
    {
        'title': 'Jira widget — test transitions and comments',
        'category': 'Jira Widget',
        'priority': 'Medium',
        'status': 'Open',
        'description': 'Verify Move To buttons and Post Comment work end-to-end.',
    },
]



class TasksWidget(tk.Frame):
    WIDGET_TITLE     = 'Tasks'
    WIDGET_ICON_NAME = 'check'

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._editing_id  = None  # None = new task, int = editing existing
        self._all_tasks   = []    # cache for filter
        self._db_fingerprint = None  # (count, max_updated) — detect external changes

        self._init_db()
        self._build_ui()
        self._load_tasks()
        self.after(3000, self._poll_db)

    def _poll_db(self):
        """Poll DB every 5s; auto-refresh treeview if external changes detected."""
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*), MAX(updated_at) FROM tasks"
                ).fetchone()
            fp = (row[0], row[1])
            if self._db_fingerprint is None:
                self._db_fingerprint = fp  # initialize on first poll
            elif fp != self._db_fingerprint:
                self._db_fingerprint = fp
                self._load_tasks(self._filter_var.get() if hasattr(self, '_filter_var') else '')
        except Exception:
            pass
        self.after(5000, self._poll_db)

    # ── DB helpers ────────────────────────────────────────────────────────────

    def _get_conn(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(DB_PATH)

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    title       TEXT    NOT NULL,
                    description TEXT    DEFAULT '',
                    status      TEXT    DEFAULT 'Open',
                    priority    TEXT    DEFAULT 'Medium',
                    category    TEXT    DEFAULT '',
                    created_at  TEXT,
                    updated_at  TEXT
                )
            """)
            conn.commit()
            # Seed only if empty
            count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
            if count == 0:
                now = _now_est()
                for t in _SEED_TASKS:
                    conn.execute(
                        "INSERT INTO tasks (title, description, status, priority, category, "
                        "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                        (t['title'], t['description'], t['status'],
                         t['priority'], t['category'], now, now)
                    )
                conn.commit()

    def _load_tasks(self, query: str = ''):
        """Fetch tasks (optionally filtered) and repopulate treeview."""
        with self._get_conn() as conn:
            if query:
                like = f'%{query}%'
                rows = conn.execute(
                    "SELECT id, title, status, priority, category, updated_at "
                    "FROM tasks WHERE title LIKE ? OR description LIKE ? OR category LIKE ? "
                    "ORDER BY id DESC",
                    (like, like, like)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, title, status, priority, category, updated_at "
                    "FROM tasks ORDER BY id DESC"
                ).fetchall()

        self._tree.delete(*self._tree.get_children())
        for row in rows:
            tid, title, status, priority, category, updated_at = row
            short_dt = _fmt_est(updated_at)
            pri_label = priority or ''
            self._tree.insert(
                '', 'end', iid=str(tid),
                values=(tid, pri_label, title, status, category, short_dt),
                tags=(status,)
            )
        self._apply_row_colors()

    def _apply_row_colors(self):
        for status, (bg, fg) in _STATUS_COLORS.items():
            self._tree.tag_configure(status, background=bg, foreground=fg)

    def _get_task(self, task_id: int) -> dict:
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT id, title, description, status, priority, category, created_at, updated_at "
                "FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
        if not row:
            return {}
        keys = ('id', 'title', 'description', 'status', 'priority', 'category',
                'created_at', 'updated_at')
        return dict(zip(keys, row))

    def _save_task(self):
        title = self._title_var.get().strip()
        if not title:
            messagebox.showwarning('Validation', 'Title is required.', parent=self)
            self._title_entry.focus_set()
            return
        status   = self._status_var.get()
        priority = self._priority_var.get()
        category = self._category_var.get().strip()
        desc     = self._desc_text.get('1.0', tk.END).strip()
        now      = _now_est()

        with self._get_conn() as conn:
            if self._editing_id is None:
                conn.execute(
                    "INSERT INTO tasks (title, description, status, priority, category, "
                    "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (title, desc, status, priority, category, now, now)
                )
            else:
                conn.execute(
                    "UPDATE tasks SET title=?, description=?, status=?, priority=?, "
                    "category=?, updated_at=? WHERE id=?",
                    (title, desc, status, priority, category, now, self._editing_id)
                )
            conn.commit()

        self._load_tasks(self._filter_var.get())
        self._clear_form()

    def _delete_task(self):
        sel = self._tree.selection()
        if not sel:
            return
        task_id = int(sel[0])
        task    = self._get_task(task_id)
        if not messagebox.askyesno(
            'Confirm Delete',
            f'Delete task:\n"{task.get("title", "")}"?',
            parent=self
        ):
            return
        with self._get_conn() as conn:
            conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
            conn.commit()
        self._load_tasks(self._filter_var.get())
        self._clear_form()

    def _filter_tasks(self, *_):
        self._load_tasks(self._filter_var.get())

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._setup_style()

        # Header bar
        header = tk.Frame(self, bg=ACCENT, height=32)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        tk.Label(header, text='  Tasks', bg=ACCENT, fg='white',
                 font=('Segoe UI', 11, 'bold')).pack(side=tk.LEFT, padx=6)

        # Toolbar
        toolbar = tk.Frame(self, bg=BG2, pady=4)
        toolbar.pack(fill=tk.X, padx=4)

        def _btn(parent, text, cmd, fg_color=FG):
            return tk.Button(
                parent, text=text, command=cmd,
                bg=BG4, fg=fg_color, activebackground=ACCENT,
                activeforeground='white', relief=tk.FLAT,
                font=('Segoe UI', 9), padx=8, pady=2, cursor='hand2'
            )

        _btn(toolbar, '+ New',  self._on_new).pack(side=tk.LEFT, padx=(2, 2))
        _btn(toolbar, 'Edit',   self._on_edit).pack(side=tk.LEFT, padx=2)
        _btn(toolbar, 'Delete', self._on_delete, fg_color=ERROR).pack(side=tk.LEFT, padx=2)

        tk.Label(toolbar, text='Filter:', bg=BG2, fg=FG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(12, 2))
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add('write', self._filter_tasks)
        filter_entry = tk.Entry(toolbar, textvariable=self._filter_var,
                                bg=BG3, fg=FG, insertbackground=FG,
                                relief=tk.FLAT, font=('Segoe UI', 9), width=24)
        filter_entry.pack(side=tk.LEFT, padx=2, ipady=3)

        # Treeview
        tree_frame = tk.Frame(self, bg=BG)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

        cols = ('id', 'priority', 'title', 'status', 'category', 'updated')
        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show='headings',
            style='Tasks.Treeview', selectmode='browse'
        )
        # (cid, heading, width, minwidth, anchor, stretch)
        col_cfg = [
            ('id',       '#',         40,   40,  tk.CENTER, False),
            ('priority', 'Pri',       55,   55,  tk.CENTER, False),
            ('title',    'Title',    260,   80,  tk.W,      True),
            ('status',   'Status',    90,   70,  tk.CENTER, True),
            ('category', 'Category', 110,   60,  tk.W,      True),
            ('updated',  'Updated',  130,   80,  tk.CENTER, True),
        ]
        for cid, heading, width, minw, anchor, stretch in col_cfg:
            self._tree.heading(cid, text=heading,
                               command=lambda c=cid: self._sort_by(c))
            self._tree.column(cid, width=width, minwidth=minw,
                              anchor=anchor, stretch=stretch)

        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,   command=self._tree.yview)
        hsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._tree.bind('<<TreeviewSelect>>', self._on_select)
        self._tree.bind('<Double-1>', self._on_double_click)
        add_treeview_menu(self._tree)

        # Detail / edit panel
        detail_outer = tk.Frame(self, bg=BG2, pady=6)
        detail_outer.pack(fill=tk.X, padx=4, pady=4)

        row0 = tk.Frame(detail_outer, bg=BG2)
        row0.pack(fill=tk.X, padx=6)

        # Title
        tk.Label(row0, text='Title:', bg=BG2, fg=FG2,
                 font=('Segoe UI', 9)).grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        self._title_var   = tk.StringVar()
        self._title_entry = tk.Entry(row0, textvariable=self._title_var,
                                     bg=BG3, fg=FG, insertbackground=FG,
                                     relief=tk.FLAT, font=('Segoe UI', 10), width=40)
        self._title_entry.grid(row=0, column=1, sticky=tk.EW, padx=(0, 12), ipady=3)

        # Status
        tk.Label(row0, text='Status:', bg=BG2, fg=FG2,
                 font=('Segoe UI', 9)).grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        self._status_var = tk.StringVar(value='Open')
        ttk.Combobox(row0, textvariable=self._status_var,
                     values=_STATUSES, state='readonly',
                     style='Tasks.TCombobox', width=14
                     ).grid(row=0, column=3, sticky=tk.W)

        row0.columnconfigure(1, weight=1)

        row1 = tk.Frame(detail_outer, bg=BG2)
        row1.pack(fill=tk.X, padx=6, pady=(4, 0))

        # Priority
        tk.Label(row1, text='Priority:', bg=BG2, fg=FG2,
                 font=('Segoe UI', 9)).grid(row=0, column=0, sticky=tk.W, padx=(0, 4))
        self._priority_var = tk.StringVar(value='Medium')
        ttk.Combobox(row1, textvariable=self._priority_var,
                     values=_PRIORITIES, state='readonly',
                     style='Tasks.TCombobox', width=10
                     ).grid(row=0, column=1, sticky=tk.W, padx=(0, 12))

        # Category
        tk.Label(row1, text='Category:', bg=BG2, fg=FG2,
                 font=('Segoe UI', 9)).grid(row=0, column=2, sticky=tk.W, padx=(0, 4))
        self._category_var = tk.StringVar()
        tk.Entry(row1, textvariable=self._category_var,
                 bg=BG3, fg=FG, insertbackground=FG,
                 relief=tk.FLAT, font=('Segoe UI', 9), width=24
                 ).grid(row=0, column=3, sticky=tk.W, ipady=3)

        # Description
        row2 = tk.Frame(detail_outer, bg=BG2)
        row2.pack(fill=tk.X, padx=6, pady=(6, 0))
        tk.Label(row2, text='Description:', bg=BG2, fg=FG2,
                 font=('Segoe UI', 9)).pack(anchor=tk.W)

        self._desc_text = tk.Text(
            detail_outer, bg=BG3, fg=FG, insertbackground=FG,
            relief=tk.FLAT, font=('Segoe UI', 9),
            height=5, wrap=tk.WORD, padx=4, pady=4
        )
        self._desc_text.pack(fill=tk.X, padx=6, pady=(2, 0))
        make_text_copyable(self._desc_text)

        # Save / Cancel buttons
        btn_row = tk.Frame(detail_outer, bg=BG2)
        btn_row.pack(fill=tk.X, padx=6, pady=(6, 0))

        self._save_btn = tk.Button(
            btn_row, text='Add Task', command=self._save_task,
            bg=ACCENT, fg='white', activebackground='#005f9e',
            activeforeground='white', relief=tk.FLAT,
            font=('Segoe UI', 9, 'bold'), padx=12, pady=3, cursor='hand2'
        )
        self._save_btn.pack(side=tk.RIGHT, padx=(4, 0))

        tk.Button(
            btn_row, text='Cancel', command=self._clear_form,
            bg=BG4, fg=FG, activebackground=BG3,
            activeforeground=FG, relief=tk.FLAT,
            font=('Segoe UI', 9), padx=12, pady=3, cursor='hand2'
        ).pack(side=tk.RIGHT)

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use('default')
        style.configure('Tasks.Treeview',
                        background=BG2, foreground=FG,
                        fieldbackground=BG2, rowheight=24,
                        font=('Segoe UI', 9))
        style.configure('Tasks.Treeview.Heading',
                        background=BG4, foreground=FG2,
                        relief='flat', font=('Segoe UI', 9, 'bold'))
        style.map('Tasks.Treeview',
                  background=[('selected', ACCENT)],
                  foreground=[('selected', 'white')])
        style.configure('Tasks.TCombobox',
                        fieldbackground=BG3, background=BG3,
                        foreground=FG, arrowcolor=FG2)

    # ── Interaction handlers ──────────────────────────────────────────────────

    def _on_select(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        task = self._get_task(int(sel[0]))
        if not task:
            return
        self._populate_form(task, edit_mode=False)

    def _on_double_click(self, _event=None):
        sel = self._tree.selection()
        if not sel:
            return
        task = self._get_task(int(sel[0]))
        if task:
            self._populate_form(task, edit_mode=True)

    def _on_new(self):
        self._clear_form()
        self._title_entry.focus_set()

    def _on_edit(self):
        sel = self._tree.selection()
        if not sel:
            return
        task = self._get_task(int(sel[0]))
        if task:
            self._populate_form(task, edit_mode=True)

    def _on_delete(self):
        self._delete_task()

    def _populate_form(self, task: dict, edit_mode: bool = False):
        self._editing_id = task['id'] if edit_mode else None
        if edit_mode:
            self._editing_id = task['id']
            self._save_btn.config(text='Update Task')
        else:
            self._editing_id = None
            self._save_btn.config(text='Add Task')

        self._title_var.set(task.get('title', ''))
        self._status_var.set(task.get('status', 'Open'))
        self._priority_var.set(task.get('priority', 'Medium'))
        self._category_var.set(task.get('category', ''))

        self._desc_text.config(state=tk.NORMAL)
        self._desc_text.delete('1.0', tk.END)
        self._desc_text.insert('1.0', task.get('description', ''))

        if not edit_mode:
            self._desc_text.config(state=tk.DISABLED)
            # Show we're in read mode but still allow copy
        else:
            self._desc_text.config(state=tk.NORMAL)
            # If not in edit mode, clicking Edit or double-click re-enables
            # Re-enable editing_id
            self._editing_id = task['id']
            self._save_btn.config(text='Update Task')

    def _clear_form(self):
        self._editing_id = None
        self._title_var.set('')
        self._status_var.set('Open')
        self._priority_var.set('Medium')
        self._category_var.set('')
        self._desc_text.config(state=tk.NORMAL)
        self._desc_text.delete('1.0', tk.END)
        self._save_btn.config(text='Add Task')
        self._tree.selection_remove(self._tree.selection())

    def _sort_by(self, col: str):
        """Sort treeview by column (toggle asc/desc)."""
        items = [(self._tree.set(iid, col), iid) for iid in self._tree.get_children()]
        reverse = getattr(self, f'_sort_{col}_rev', False)
        items.sort(reverse=reverse)
        for idx, (_, iid) in enumerate(items):
            self._tree.move(iid, '', idx)
        setattr(self, f'_sort_{col}_rev', not reverse)
