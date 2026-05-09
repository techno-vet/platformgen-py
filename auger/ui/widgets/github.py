"""
GitHub Widget - Repository browser and management for PlatformGen
Provides repository browsing, issues, PRs, commits, and actions monitoring
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, simpledialog
import threading
import json
import os
from datetime import datetime
from dotenv import load_dotenv
from pathlib import Path
from platformgen.ui import icons as _icons
from platformgen.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu, auger_home as _auger_home
from platformgen.runtime import state_dir

try:
    from tksheet import Sheet as _Sheet
    TKSHEET_AVAILABLE = True
except ImportError:
    TKSHEET_AVAILABLE = False

# Color scheme (matching Auger theme)
BG = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
FG = '#e0e0e0'
ACCENT = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR = '#f44747'
WARNING = '#ce9178'
SUCCESS = '#4ec9b0'

# Import GitHub library
try:
    from github import Github, GithubException
    import requests
    GITHUB_AVAILABLE = True
except ImportError:
    GITHUB_AVAILABLE = False



class GitHubWidget(tk.Frame):
    """GitHub repository browser and management widget"""
    
    # Widget metadata
    WIDGET_NAME = "github"
    WIDGET_TITLE = "GitHub"
    WIDGET_ICON = "🐙"
    WIDGET_ICON_NAME = "github"
    
    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        
        # Configure dropdown font globally
        self.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))
        
        self.context_builder_callback = context_builder_callback
        self.github_client = None
        self.current_repo = None
        self.current_user = None
        self.token_file = str(state_dir() / ".github_token")
        self.legacy_token_file = os.path.join(os.path.expanduser('~'), '.auger_github_token')
        self._selected_open_pr = None        # (repo_name, pr_number)
        self._selected_open_pr_obj = None    # cached PyGitHub PR object
        self._loaded_open_pr_target = None   # last PR whose detail pane finished loading
        self._open_prs_after_id = None       # after() handle for auto-refresh
        self._open_prs_loading = False       # prevent overlapping loads
        self._pr_filter_vars = {}            # populated by _create_open_prs_tab
        self._pr_filter_entries = {}
        self._open_prs_sort_col = 'updated'  # default newest-first sort
        self._open_prs_sort_desc = True
        self._pr_filter_frame = None         # grid container for filter entries
        self._pr_col_defs = []               # column defs for filter width sync
        self._pr_list_frame = None           # list_frame ref for resize events
        self._pr_paned = None                # PanedWindow ref for sash drag binding
        self._pr_resize_after_id = None      # debounced tksheet resize callback
        self._pr_last_table_width = None     # last measured table canvas width
        self._pr_files_data = []             # changed files for the selected PR
        self._pr_file_tree_map = {}          # tree item id -> file metadata
        self._selected_pr_file = None        # selected changed file metadata
        self._bulk_pr_action_running = False # suppress refresh while bulk approve runs
        self._open_prs_menu = None           # fallback treeview context menu
        self._open_prs_sheet_menu = None     # tksheet context menu
        self._open_pr_row_anchor = None      # anchor row for shift-range selection
        self._suppress_open_pr_selection_event = False
        
        # GHE org filtering
        self._selected_org = None  # Current selected org for filtering
        self._available_orgs = []  # List of accessible orgs
        
        # Load environment variables
        load_dotenv(_auger_home() / '.auger' / '.env')
        
        self._icons = {}
        self._create_ui()
        
        # Try to load token from API config first, then saved token
        self._load_token_from_env()
    
    def _load_token_from_env(self):
        """Load GitHub token from .env file (API config)"""
        token = os.getenv('GHE_TOKEN')
        if token:
            self.token_var.set(token)
            self.after(100, self.authenticate)  # Auto-authenticate after UI is ready
        else:
            # Fallback to saved token file
            self._load_saved_token()

    def _create_ui(self):
        """Create the widget UI"""
        # Pre-create icons
        for name in ('connect', 'refresh', 'search', 'play', 'add', 'branch', 'check', 'warning', 'github', 'folder'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass
        self._tab_icon_overview = _icons.get('github', 18)
        self._tab_icon_issues = _icons.get('warning', 18)
        self._tab_icon_prs = _icons.get('branch', 18)
        self._tab_icon_commits = _icons.get('check', 18)
        self._tab_icon_branches = _icons.get('branch', 18)
        self._tab_icon_actions = _icons.get('play', 18)
        # Main container
        main_frame = tk.Frame(self, bg=BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Top: Auth panel
        self._create_auth_panel(main_frame)
        
        # Repository selection
        self._create_repo_panel(main_frame)
        
        # Tabs for different views
        self._create_tabs(main_frame)
        
        # Bottom: Status bar
        self._create_status_bar(main_frame)
    
    def _create_auth_panel(self, parent):
        """Create authentication controls"""
        auth_frame = tk.Frame(parent, bg=BG2)
        auth_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(
            auth_frame, text="GitHub Token:", font=('Segoe UI', 10, 'bold'),
            fg=FG, bg=BG2
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Label(
            auth_frame, text="(from API Config)", font=('Segoe UI', 9, 'italic'),
            fg='#808080', bg=BG2
        ).pack(side=tk.LEFT, padx=0)
        
        self.token_var = tk.StringVar()
        token_entry = tk.Entry(
            auth_frame, textvariable=self.token_var, width=50, show="*",
            font=('Segoe UI', 10), bg=BG3, fg=FG
        )
        token_entry.pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            auth_frame, text=" Connect",
            image=self._icons.get('connect'), compound=tk.LEFT,
            command=self.authenticate,
            bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            auth_frame, text="Get Token", command=self._show_token_help,
            bg=BG3, fg=FG, font=('Segoe UI', 10),
            relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        self.user_label = tk.Label(
            auth_frame, text="Not authenticated", font=('Segoe UI', 10),
            fg=WARNING, bg=BG2
        )
        self.user_label.pack(side=tk.LEFT, padx=15)
    
    def _create_repo_panel(self, parent):
        """Create repository selection controls"""
        repo_frame = tk.Frame(parent, bg=BG2)
        repo_frame.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(
            repo_frame, text="Organization:", font=('Segoe UI', 10, 'bold'),
            fg=FG, bg=BG2
        ).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)
        
        self.org_var = tk.StringVar()
        self.org_combo = ttk.Combobox(
            repo_frame, textvariable=self.org_var, width=30, state="readonly",
            font=('Segoe UI', 10)
        )
        self.org_combo.grid(row=0, column=1, sticky=tk.W, padx=5, pady=5)
        self.org_combo.bind('<<ComboboxSelected>>', lambda e: self.on_org_selected())
        
        tk.Label(
            repo_frame, text="Repository:", font=('Segoe UI', 10, 'bold'),
            fg=FG, bg=BG2
        ).grid(row=1, column=0, sticky=tk.W, padx=5, pady=5)
        
        self.repo_var = tk.StringVar()
        self.repo_combo = ttk.Combobox(
            repo_frame, textvariable=self.repo_var, width=50, state="readonly",
            font=('Segoe UI', 10)
        )
        self.repo_combo.grid(row=1, column=1, sticky=tk.W, padx=5, pady=5)
        self.repo_combo.bind('<<ComboboxSelected>>', self.on_repo_selected)
        
        tk.Button(
            repo_frame, text=" Refresh",
            image=self._icons.get('refresh'), compound=tk.LEFT,
            command=self.load_repositories,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).grid(row=1, column=2, padx=5, pady=5)
        
        tk.Button(
            repo_frame, text=" Open in Browser",
            image=self._icons.get('play'), compound=tk.LEFT,
            command=self._open_repo_in_browser,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).grid(row=1, column=3, padx=5, pady=5)
        
        # Repo info labels
        self.repo_info_label = tk.Label(
            repo_frame, text="", font=('Segoe UI', 9),
            fg=FG, bg=BG2, anchor=tk.W
        )
        self.repo_info_label.grid(row=2, column=0, columnspan=4, sticky=tk.W, padx=5, pady=2)
    
    def _create_tabs(self, parent):
        """Create tabbed interface"""
        self.notebook = ttk.Notebook(parent)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Style the notebook
        style = ttk.Style()
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab', background=BG2, foreground=FG, padding=[10, 5])
        style.map('TNotebook.Tab', background=[('selected', BG3)], foreground=[('selected', FG)])

        # Dark theme for all Treeviews in this widget
        style.configure('Auger.Treeview',
            background=BG2, foreground=FG, fieldbackground=BG2,
            rowheight=24, borderwidth=0, font=('Segoe UI', 10))
        style.configure('Auger.Treeview.Heading',
            background=BG3, foreground=ACCENT2, font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT, borderwidth=1)
        style.map('Auger.Treeview',
            background=[('selected', ACCENT)], foreground=[('selected', '#ffffff')])
        
        # Create tabs — Open PRs FIRST (it's the default/landing tab)
        self._create_open_prs_tab()
        self._create_overview_tab()
        self._create_issues_tab()
        self._create_prs_tab()
        self._create_commits_tab()
        self._create_branches_tab()
        self._create_actions_tab()
    
    def _create_overview_tab(self):
        """Create repository overview tab"""
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, image=self._tab_icon_overview, text=" Overview", compound=tk.LEFT)
        
        # Scrollable text for README and stats
        self.overview_text = scrolledtext.ScrolledText(
            tab, wrap=tk.WORD, bg=BG3, fg=FG,
            font=('Segoe UI', 10), state='disabled'
        )
        self.overview_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        make_text_copyable(self.overview_text)
    
    def _create_issues_tab(self):
        """Create issues browser tab"""
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, image=self._tab_icon_issues, text=" Issues", compound=tk.LEFT)
        
        # Controls
        controls = tk.Frame(tab, bg=BG2)
        controls.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(controls, text="State:", font=('Segoe UI', 10, 'bold'), fg=FG, bg=BG2).pack(side=tk.LEFT, padx=5)
        
        self.issue_state_var = tk.StringVar(value="open")
        for state in ["open", "closed", "all"]:
            tk.Radiobutton(
                controls, text=state.capitalize(), variable=self.issue_state_var,
                value=state, command=self.load_issues, bg=BG2, fg=FG,
                selectcolor=BG3, font=('Segoe UI', 10)
            ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            controls, text=" Refresh",
            image=self._icons.get('refresh'), compound=tk.LEFT,
            command=self.load_issues,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            controls, text=" Create Issue",
            image=self._icons.get('add'), compound=tk.LEFT,
            command=self._create_issue,
            bg=SUCCESS, fg='black', font=('Segoe UI', 10, 'bold'), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        # Issues tree
        tree_frame = tk.Frame(tab, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.issues_tree = ttk.Treeview(
            tree_frame, columns=('number', 'title', 'author', 'state', 'created'),
            show='headings', yscrollcommand=scrollbar.set, style='Auger.Treeview'
        )
        
        self.issues_tree.heading('number', text='#')
        self.issues_tree.heading('title', text='Title')
        self.issues_tree.heading('author', text='Author')
        self.issues_tree.heading('state', text='State')
        self.issues_tree.heading('created', text='Created')
        
        self.issues_tree.column('number', width=60)
        self.issues_tree.column('title', width=400)
        self.issues_tree.column('author', width=120)
        self.issues_tree.column('state', width=80)
        self.issues_tree.column('created', width=150)
        
        self.issues_tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.issues_tree)
        
        self.issues_tree.bind('<Double-1>', self._on_issue_double_click)
    
    def _create_prs_tab(self):
        """Create pull requests tab"""
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, image=self._tab_icon_prs, text=" Pull Requests", compound=tk.LEFT)
        
        # Controls
        controls = tk.Frame(tab, bg=BG2)
        controls.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(controls, text="State:", font=('Segoe UI', 10, 'bold'), fg=FG, bg=BG2).pack(side=tk.LEFT, padx=5)
        
        self.pr_state_var = tk.StringVar(value="open")
        for state in ["open", "closed", "all"]:
            tk.Radiobutton(
                controls, text=state.capitalize(), variable=self.pr_state_var,
                value=state, command=self.load_pull_requests, bg=BG2, fg=FG,
                selectcolor=BG3, font=('Segoe UI', 10)
            ).pack(side=tk.LEFT, padx=5)
        
        tk.Button(
            controls, text=" Refresh",
            image=self._icons.get('refresh'), compound=tk.LEFT,
            command=self.load_pull_requests,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        # PRs tree
        tree_frame = tk.Frame(tab, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.prs_tree = ttk.Treeview(
            tree_frame, columns=('number', 'title', 'author', 'state', 'created'),
            show='headings', yscrollcommand=scrollbar.set, style='Auger.Treeview'
        )
        
        self.prs_tree.heading('number', text='#')
        self.prs_tree.heading('title', text='Title')
        self.prs_tree.heading('author', text='Author')
        self.prs_tree.heading('state', text='State')
        self.prs_tree.heading('created', text='Created')
        
        self.prs_tree.column('number', width=60)
        self.prs_tree.column('title', width=400)
        self.prs_tree.column('author', width=120)
        self.prs_tree.column('state', width=80)
        self.prs_tree.column('created', width=150)
        
        self.prs_tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.prs_tree)
        
        self.prs_tree.bind('<Double-1>', self._on_pr_double_click)
    
    def _create_commits_tab(self):
        """Create commits history tab"""
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, image=self._tab_icon_commits, text=" Commits", compound=tk.LEFT)
        
        # Controls
        controls = tk.Frame(tab, bg=BG2)
        controls.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Label(controls, text="Branch:", font=('Segoe UI', 10, 'bold'), fg=FG, bg=BG2).pack(side=tk.LEFT, padx=5)
        
        self.commit_branch_var = tk.StringVar()
        self.commit_branch_combo = ttk.Combobox(
            controls, textvariable=self.commit_branch_var, width=30, state="readonly",
            font=('Segoe UI', 10)
        )
        self.commit_branch_combo.pack(side=tk.LEFT, padx=5)
        self.commit_branch_combo.bind('<<ComboboxSelected>>', lambda e: self.load_commits())
        
        tk.Button(
            controls, text=" Refresh",
            image=self._icons.get('refresh'), compound=tk.LEFT,
            command=self.load_commits,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Label(controls, text="Limit:", font=('Segoe UI', 10), fg=FG, bg=BG2).pack(side=tk.LEFT, padx=(15, 5))
        
        self.commit_limit_var = tk.StringVar(value="50")
        limit_spin = tk.Spinbox(
            controls, from_=10, to=500, increment=10, textvariable=self.commit_limit_var,
            width=8, font=('Segoe UI', 10), bg=BG3, fg=FG
        )
        limit_spin.pack(side=tk.LEFT, padx=5)
        
        # Commits tree
        tree_frame = tk.Frame(tab, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.commits_tree = ttk.Treeview(
            tree_frame, columns=('sha', 'message', 'author', 'date'),
            show='headings', yscrollcommand=scrollbar.set, style='Auger.Treeview'
        )
        
        self.commits_tree.heading('sha', text='SHA')
        self.commits_tree.heading('message', text='Message')
        self.commits_tree.heading('author', text='Author')
        self.commits_tree.heading('date', text='Date')
        
        self.commits_tree.column('sha', width=100)
        self.commits_tree.column('message', width=400)
        self.commits_tree.column('author', width=150)
        self.commits_tree.column('date', width=150)
        
        self.commits_tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.commits_tree)
        scrollbar.config(command=self.commits_tree.yview)
        
        self.commits_tree.bind('<Double-1>', self._on_commit_double_click)
    
    def _create_branches_tab(self):
        """Create branches tab"""
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, image=self._tab_icon_branches, text=" Branches", compound=tk.LEFT)
        
        # Controls
        controls = tk.Frame(tab, bg=BG2)
        controls.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Button(
            controls, text=" Refresh",
            image=self._icons.get('refresh'), compound=tk.LEFT,
            command=self.load_branches,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        # Branches tree
        tree_frame = tk.Frame(tab, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.branches_tree = ttk.Treeview(
            tree_frame, columns=('name', 'protected', 'sha'),
            show='headings', yscrollcommand=scrollbar.set, style='Auger.Treeview'
        )
        
        self.branches_tree.heading('name', text='Branch Name')
        self.branches_tree.heading('protected', text='Protected')
        self.branches_tree.heading('sha', text='Latest SHA')
        
        self.branches_tree.column('name', width=300)
        self.branches_tree.column('protected', width=100)
        self.branches_tree.column('sha', width=400)
        
        self.branches_tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.branches_tree)
        scrollbar.config(command=self.branches_tree.yview)
    
    def _create_actions_tab(self):
        """Create GitHub Actions tab"""
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, image=self._tab_icon_actions, text=" Actions", compound=tk.LEFT)
        
        # Controls
        controls = tk.Frame(tab, bg=BG2)
        controls.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Button(
            controls, text=" Refresh",
            image=self._icons.get('refresh'), compound=tk.LEFT,
            command=self.load_actions,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=15, pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        tk.Label(controls, text="Limit:", font=('Segoe UI', 10), fg=FG, bg=BG2).pack(side=tk.LEFT, padx=(15, 5))
        
        self.actions_limit_var = tk.StringVar(value="20")
        limit_spin = tk.Spinbox(
            controls, from_=5, to=100, increment=5, textvariable=self.actions_limit_var,
            width=8, font=('Segoe UI', 10), bg=BG3, fg=FG
        )
        limit_spin.pack(side=tk.LEFT, padx=5)
        
        # Actions tree
        tree_frame = tk.Frame(tab, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = tk.Scrollbar(tree_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.actions_tree = ttk.Treeview(
            tree_frame, columns=('id', 'workflow', 'status', 'conclusion', 'branch', 'created'),
            show='headings', yscrollcommand=scrollbar.set, style='Auger.Treeview'
        )
        
        self.actions_tree.heading('id', text='Run ID')
        self.actions_tree.heading('workflow', text='Workflow')
        self.actions_tree.heading('status', text='Status')
        self.actions_tree.heading('conclusion', text='Conclusion')
        self.actions_tree.heading('branch', text='Branch')
        self.actions_tree.heading('created', text='Created')
        
        self.actions_tree.column('id', width=100)
        self.actions_tree.column('workflow', width=200)
        self.actions_tree.column('status', width=100)
        self.actions_tree.column('conclusion', width=100)
        self.actions_tree.column('branch', width=150)
        self.actions_tree.column('created', width=150)
        
        self.actions_tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.actions_tree)
        scrollbar.config(command=self.actions_tree.yview)
        
        self.actions_tree.bind('<Double-1>', self._on_action_double_click)

    # ------------------------------------------------------------------
    # Open Pull Requests tab (org-wide, auto-refreshing, review + approve)
    # ------------------------------------------------------------------

    def _create_open_prs_tab(self):
        """First/default tab: open PRs across org with review & approve panel."""
        tab = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(tab, image=self._tab_icon_prs, text=" Open PRs", compound=tk.LEFT)

        # Controls bar
        controls = tk.Frame(tab, bg=BG2)
        controls.pack(fill=tk.X, padx=5, pady=5)

        tk.Button(
            controls, text=" Refresh",
            image=self._icons.get('refresh'), compound=tk.LEFT,
            command=self.load_open_prs,
            bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT, padx=12, pady=4
        ).pack(side=tk.LEFT, padx=5)

        tk.Label(controls, text="Scope:", font=('Segoe UI', 10), fg=FG, bg=BG2).pack(side=tk.LEFT, padx=(8, 3))
        self._open_prs_filter_var = tk.StringVar(value="open")
        scope_combo = ttk.Combobox(
            controls, textvariable=self._open_prs_filter_var,
            values=["review-requested", "assigned", "created", "open"],
            state="readonly", width=18, font=('Segoe UI', 10)
        )
        scope_combo.pack(side=tk.LEFT, padx=3)
        scope_combo.bind('<<ComboboxSelected>>', lambda e: self.load_open_prs())

        self._show_approved_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            controls, text="Show approved", variable=self._show_approved_var,
            command=self.load_open_prs,
            bg=BG2, fg=FG, selectcolor=BG3, activebackground=BG2,
            font=('Segoe UI', 10)
        ).pack(side=tk.LEFT, padx=(10, 3))

        self._open_prs_last_refresh_var = tk.StringVar(value="Not loaded")
        tk.Label(
            controls, textvariable=self._open_prs_last_refresh_var,
            font=('Segoe UI', 9), fg=WARNING, bg=BG2
        ).pack(side=tk.LEFT, padx=10)

        self._open_prs_status_var = tk.StringVar(value="⏱ Auto: 45s")
        tk.Label(
            controls, textvariable=self._open_prs_status_var,
            font=('Segoe UI', 9), fg=ACCENT2, bg=BG2
        ).pack(side=tk.RIGHT, padx=8)

        # Horizontal split: PR list (left) + detail panel (right)
        paned = tk.PanedWindow(tab, orient=tk.HORIZONTAL, bg=BG, sashwidth=5, sashrelief=tk.RAISED)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        # ---- Left: PR list ----
        list_frame = tk.Frame(paned, bg=BG2)

        # Store all loaded rows for client-side filtering
        self._open_prs_all_items = []  # list of (values_tuple, tag, updated_secs)
        self._open_prs_sort_col = 'updated'
        self._open_prs_sort_desc = True

        if TKSHEET_AVAILABLE:
            # Column definitions: (header, filter_placeholder, sheet_px, expand_weight)
            # sheet_px=0 → Title gets remaining space distributed by tksheet auto-sizing.
            PR_COL_DEFS = [
                ('Repo',    'Repo…',   210, 0),
                ('#',       '#…',       42, 0),
                ('Title',   'Title…',    0, 1),
                ('Author',  'Author…', 115, 0),
                ('Updated', '',         80, 0),
            ]

            # Filter row — entries are placed using place() keyed to actual sheet
            # column pixel positions (see _sync_filter_widths).  Fixed height so
            # it takes up exactly one row above the sheet header.
            filter_frame = tk.Frame(list_frame, bg='#2d2d2d', height=28)
            filter_frame.place(x=0, y=0, relwidth=1.0, height=28)
            self._pr_filter_vars = {}
            self._pr_filter_entries = {}

            for col_name, placeholder, px, _weight in PR_COL_DEFS:
                if not placeholder:
                    continue  # Updated — no filter
                v = tk.StringVar()
                self._pr_filter_vars[col_name] = v
                e = tk.Entry(filter_frame, textvariable=v,
                             bg='#1e1e1e', fg='#666666',
                             insertbackground='#e0e0e0', relief=tk.FLAT,
                             font=('Segoe UI', 9))
                e.insert(0, placeholder)
                self._pr_filter_entries[col_name] = (e, placeholder)

                def _on_fi(ev, en=e, ph=placeholder):
                    if en.get() == ph:
                        en.delete(0, tk.END)
                        en.config(fg='#e0e0e0')

                def _on_fo(ev, en=e, ph=placeholder):
                    if not en.get():
                        en.insert(0, ph)
                        en.config(fg='#666666')

                e.bind('<FocusIn>',  _on_fi)
                e.bind('<FocusOut>', _on_fo)
                v.trace_add('write', lambda *_: self._apply_pr_filters())
                # initial place() — will be corrected by _sync_filter_widths after render
                e.place(x=0, y=2, width=px or 120, height=24)

            sheet_widths = [px if px else 370 for _, _, px, _ in PR_COL_DEFS]

            self.open_prs_sheet = _Sheet(
                list_frame,
                headers=['Repo', '#', 'Title', 'Author', 'Updated'],
                data=[],
                theme='dark',
                show_row_index=False,
                row_height=24,
                header_height=28,
                font=('Segoe UI', 10, 'normal'),
                header_font=('Segoe UI', 10, 'bold'),
                column_width=120,
                header_bg='#2d2d2d',
                header_fg='#4ec9b0',
                table_bg='#252526',
                table_fg='#e0e0e0',
                frame_bg='#1e1e1e',
                table_selected_rows_border_fg='#007acc',
                table_selected_rows_bg='#1e3a5f',
                table_selected_rows_fg='#ffffff',
            )
            self._apply_open_pr_sheet_theme()
            self.open_prs_sheet.place(x=0, y=28, relwidth=1.0, relheight=1.0, height=-28)
            self.open_prs_sheet.set_column_widths(sheet_widths)
            self.open_prs_sheet.enable_bindings(
                'single_select', 'row_select', 'ctrl_select',
                'column_width_resize', 'arrowkeys', 'rc_select', 'sort_rows',
            )
            self._open_prs_sheet_menu = tk.Menu(self, tearoff=0)
            self._open_prs_sheet_menu.add_command(
                label="Quick Approve Selected PRs",
                command=self._bulk_approve_selected_open_prs,
            )
            self.open_prs_sheet.readonly_columns(columns=list(range(5)))
            self.open_prs_sheet.extra_bindings([
                ('cell_select',   self._on_sheet_pr_selected),
                ('row_select',    self._on_sheet_pr_selected),
                ('column_select', self._on_sheet_col_header_clicked),
            ])
            # Direct header-click sort (add=True preserves resize/drag handlers)
            self.open_prs_sheet.CH.bind(
                '<ButtonRelease-1>',
                self._on_sheet_col_header_clicked,
                add=True
            )
            # tksheet uses grid_propagate(0) internally — it won't auto-resize
            # when the containing frame changes size.  Bind list_frame <Configure>
            # to explicitly resize the sheet and re-sync filter positions.
            self._pr_list_frame = list_frame
            self._pr_filter_frame = filter_frame
            self._pr_col_defs = PR_COL_DEFS
            self._pr_paned = paned
            list_frame.bind('<Configure>', self._on_list_frame_resize)
            # Also bind paned sash drag so sheet refreshes during live drag
            paned.bind('<B1-Motion>', self._on_list_frame_resize, add=True)
            paned.bind('<ButtonRelease-1>', self._on_list_frame_resize, add=True)
            self.open_prs_sheet.CH.bind('<ButtonRelease-1>', self._sync_filter_widths, add=True)
            self.open_prs_sheet.MT.bind('<ButtonRelease-1>', self._promote_open_pr_sheet_selection, add=True)
            self.open_prs_sheet.MT.bind('<Button-3>', self._show_open_pr_sheet_menu, add=True)
            # Trigger initial placement after first render cycle
            self.after(150, self._resize_open_pr_sheet)
            self.open_prs_tree = None

        else:
            # Fallback: plain Treeview if tksheet not installed
            self.open_prs_sheet = None
            tree_frame = tk.Frame(list_frame, bg=BG2)
            tree_frame.pack(fill=tk.BOTH, expand=True)
            vscroll = tk.Scrollbar(tree_frame)
            vscroll.pack(side=tk.RIGHT, fill=tk.Y)
            self.open_prs_tree = ttk.Treeview(
                tree_frame,
                columns=('repo', 'num', 'title', 'author', 'updated'),
                show='headings', yscrollcommand=vscroll.set, selectmode='extended',
                style='Auger.Treeview'
            )
            for col, lbl, w in (('repo','Repo',150),('num','#',55),('title','Title',370),
                                 ('author','Author',110),('updated','Updated',90)):
                self.open_prs_tree.heading(
                    col,
                    text=lbl,
                    command=lambda _c=col: self._sort_open_prs(_c),
                )
                self.open_prs_tree.column(col, width=w, minwidth=50)
            vscroll.config(command=self.open_prs_tree.yview)
            self.open_prs_tree.pack(fill=tk.BOTH, expand=True)
            add_treeview_menu(self.open_prs_tree)
            self.open_prs_tree.bind('<<TreeviewSelect>>', self._on_open_pr_selected)
            self.open_prs_tree.bind('<Double-1>', lambda e: self._open_selected_pr_in_browser())
            self._open_prs_menu = tk.Menu(self, tearoff=0)
            self._open_prs_menu.add_command(
                label="Quick Approve Selected PRs",
                command=self._bulk_approve_selected_open_prs,
            )
            self.open_prs_tree.bind('<Button-3>', self._show_open_pr_tree_menu)

        paned.add(list_frame, minsize=420, stretch='always')

        # ---- Right: detail panel ----
        detail_frame = tk.Frame(paned, bg=BG2)

        btn_frame = tk.Frame(detail_frame, bg=BG2)
        btn_frame.pack(fill=tk.X, padx=5, pady=(8, 4))

        self._pr_approve_btn = tk.Button(
            btn_frame, text="Approve",
            command=self._approve_open_pr,
            bg='#1a3a1a', fg=SUCCESS, font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT, padx=10, pady=5, state='disabled'
        )
        self._pr_approve_btn.pack(side=tk.LEFT, padx=4)

        self._pr_changes_btn = tk.Button(
            btn_frame, text="Req. Changes",
            command=self._request_changes_open_pr,
            bg='#3a1a1a', fg=ERROR, font=('Segoe UI', 10),
            relief=tk.FLAT, padx=10, pady=5, state='disabled'
        )
        self._pr_changes_btn.pack(side=tk.LEFT, padx=4)

        self._pr_comment_btn = tk.Button(
            btn_frame, text="Comment",
            command=self._comment_open_pr,
            bg=BG3, fg=FG, font=('Segoe UI', 10),
            relief=tk.FLAT, padx=10, pady=5, state='disabled'
        )
        self._pr_comment_btn.pack(side=tk.LEFT, padx=4)

        tk.Button(
            btn_frame, text="Open PR",
            command=self._open_selected_pr_in_browser,
            bg=BG3, fg=ACCENT, font=('Segoe UI', 10),
            relief=tk.FLAT, padx=10, pady=5
        ).pack(side=tk.RIGHT, padx=4)

        self._pr_detail_header_var = tk.StringVar(value="Select a PR to view details")
        tk.Label(
            detail_frame, textvariable=self._pr_detail_header_var,
            font=('Segoe UI', 11, 'bold'), fg=FG, bg=BG2,
            wraplength=360, justify=tk.LEFT, anchor=tk.W
        ).pack(fill=tk.X, padx=10, pady=(4, 2))

        self._pr_detail_meta_var = tk.StringVar(value="")
        tk.Label(
            detail_frame, textvariable=self._pr_detail_meta_var,
            font=('Segoe UI', 9), fg=WARNING, bg=BG2, justify=tk.LEFT, anchor=tk.W
        ).pack(fill=tk.X, padx=10)

        self._pr_review_status_var = tk.StringVar(value="")
        tk.Label(
            detail_frame, textvariable=self._pr_review_status_var,
            font=('Segoe UI', 9), fg=ACCENT2, bg=BG2, justify=tk.LEFT, anchor=tk.W, wraplength=360
        ).pack(fill=tk.X, padx=10, pady=(2, 4))

        self._pr_detail_nb = ttk.Notebook(detail_frame)
        self._pr_detail_nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))

        overview_tab = tk.Frame(self._pr_detail_nb, bg=BG2)
        self._pr_detail_nb.add(overview_tab, text=" Overview ")

        files_tab = tk.Frame(self._pr_detail_nb, bg=BG2)
        self._pr_detail_nb.add(files_tab, text=" Files Changed ")

        desc_frame = tk.Frame(overview_tab, bg=BG2)
        desc_frame.pack(fill=tk.BOTH, expand=True)

        desc_vscroll = tk.Scrollbar(desc_frame)
        desc_vscroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._pr_detail_text = tk.Text(
            desc_frame, wrap=tk.WORD, bg=BG3, fg=FG,
            font=('Segoe UI', 10), relief=tk.FLAT, state='disabled', cursor='arrow',
            padx=12, pady=8,
            yscrollcommand=desc_vscroll.set
        )
        desc_vscroll.config(command=self._pr_detail_text.yview)
        _md_tags = {
            'h1':     {'font': ('Segoe UI', 14, 'bold'),  'foreground': '#4fc1ff', 'spacing1': 8, 'spacing3': 4},
            'h2':     {'font': ('Segoe UI', 12, 'bold'),  'foreground': '#4ec9b0', 'spacing1': 6, 'spacing3': 3},
            'h3':     {'font': ('Segoe UI', 11, 'bold'),  'foreground': '#ce9178', 'spacing1': 4, 'spacing3': 2},
            'bold':   {'font': ('Segoe UI', 10, 'bold'),  'foreground': FG},
            'italic': {'font': ('Segoe UI', 10, 'italic'),'foreground': FG},
            'code':   {'font': ('Consolas', 9),           'foreground': '#9cdcfe', 'background': '#1a1a1a'},
            'fence':  {'font': ('Consolas', 9),           'foreground': '#9cdcfe', 'background': '#1a1a1a',
                       'lmargin1': 12, 'lmargin2': 12, 'spacing1': 2, 'spacing3': 2},
            'bullet': {'font': ('Segoe UI', 10),          'foreground': FG,
                       'lmargin1': 20, 'lmargin2': 30},
            'hr':     {'font': ('Segoe UI', 4),           'foreground': '#444',    'spacing1': 4, 'spacing3': 4},
            'normal': {'font': ('Segoe UI', 10),          'foreground': FG,        'spacing1': 1, 'spacing3': 1},
            'commit': {'font': ('Consolas', 9),           'foreground': '#6a9955', 'lmargin1': 8, 'lmargin2': 8},
        }
        for tag, opts in _md_tags.items():
            self._pr_detail_text.tag_configure(tag, **opts)
        self._pr_detail_text.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(self._pr_detail_text)

        files_header = tk.Frame(files_tab, bg=BG2)
        files_header.pack(fill=tk.X, padx=2, pady=(2, 4))

        self._pr_files_summary_var = tk.StringVar(value="Select a PR to inspect changed files")
        tk.Label(
            files_header, textvariable=self._pr_files_summary_var,
            font=('Segoe UI', 9), fg=WARNING, bg=BG2, anchor=tk.W, justify=tk.LEFT
        ).pack(side=tk.LEFT, padx=6)

        files_paned = tk.PanedWindow(files_tab, orient=tk.HORIZONTAL, bg=BG, sashwidth=5, sashrelief=tk.RAISED)
        files_paned.pack(fill=tk.BOTH, expand=True)

        file_tree_frame = tk.Frame(files_paned, bg=BG2)
        file_tree_scroll = tk.Scrollbar(file_tree_frame)
        file_tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self._pr_files_tree = ttk.Treeview(
            file_tree_frame,
            columns=('status', 'additions', 'deletions'),
            show='tree headings',
            yscrollcommand=file_tree_scroll.set,
            style='Auger.Treeview'
        )
        self._pr_files_tree.heading('#0', text='Path')
        self._pr_files_tree.heading('status', text='Status')
        self._pr_files_tree.heading('additions', text='+')
        self._pr_files_tree.heading('deletions', text='-')
        self._pr_files_tree.column('#0', width=260, minwidth=180, stretch=True)
        self._pr_files_tree.column('status', width=90, minwidth=70, stretch=False, anchor=tk.CENTER)
        self._pr_files_tree.column('additions', width=55, minwidth=45, stretch=False, anchor=tk.E)
        self._pr_files_tree.column('deletions', width=55, minwidth=45, stretch=False, anchor=tk.E)
        self._pr_files_tree.pack(fill=tk.BOTH, expand=True)
        file_tree_scroll.config(command=self._pr_files_tree.yview)
        add_treeview_menu(self._pr_files_tree)
        self._pr_files_tree.bind('<<TreeviewSelect>>', self._on_pr_file_selected)
        self._pr_files_tree.bind('<Double-1>', lambda e: self._open_selected_pr_file_in_browser())

        file_diff_frame = tk.Frame(files_paned, bg=BG2)

        file_diff_header = tk.Frame(file_diff_frame, bg=BG2)
        file_diff_header.pack(fill=tk.X, padx=4, pady=(4, 2))

        self._pr_file_detail_var = tk.StringVar(value="Select a changed file to review its patch")
        tk.Label(
            file_diff_header, textvariable=self._pr_file_detail_var,
            font=('Segoe UI', 10, 'bold'), fg=FG, bg=BG2, anchor=tk.W, justify=tk.LEFT
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)

        self._pr_open_file_btn = tk.Button(
            file_diff_header, text="Open File",
            command=self._open_selected_pr_file_in_browser,
            bg=BG3, fg=ACCENT, font=('Segoe UI', 10),
            relief=tk.FLAT, padx=10, pady=4, state='disabled'
        )
        self._pr_open_file_btn.pack(side=tk.RIGHT, padx=4)

        file_diff_body = tk.Frame(file_diff_frame, bg=BG2)
        file_diff_body.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        file_diff_y = tk.Scrollbar(file_diff_body)
        file_diff_y.pack(side=tk.RIGHT, fill=tk.Y)
        file_diff_x = tk.Scrollbar(file_diff_body, orient=tk.HORIZONTAL)
        file_diff_x.pack(side=tk.BOTTOM, fill=tk.X)

        self._pr_file_diff_text = tk.Text(
            file_diff_body, wrap=tk.NONE, bg=BG3, fg=FG,
            font=('Consolas', 9), relief=tk.FLAT, state='disabled',
            padx=10, pady=8, yscrollcommand=file_diff_y.set, xscrollcommand=file_diff_x.set
        )
        self._pr_file_diff_text.pack(fill=tk.BOTH, expand=True)
        file_diff_y.config(command=self._pr_file_diff_text.yview)
        file_diff_x.config(command=self._pr_file_diff_text.xview)
        make_text_copyable(self._pr_file_diff_text)
        self._pr_file_diff_text.tag_configure('meta', foreground='#9cdcfe', font=('Segoe UI', 10, 'bold'))
        self._pr_file_diff_text.tag_configure('path', foreground=ACCENT2)
        self._pr_file_diff_text.tag_configure('hunk', foreground=WARNING)
        self._pr_file_diff_text.tag_configure('add', foreground='#6a9955')
        self._pr_file_diff_text.tag_configure('del', foreground='#d16969')
        self._pr_file_diff_text.tag_configure('context', foreground=FG)

        files_paned.add(file_tree_frame, minsize=220, stretch='always')
        files_paned.add(file_diff_frame, minsize=320, stretch='always')

        paned.add(detail_frame, minsize=300, stretch='always')

        # Start auto-refresh loop (fires every 45 s; guard skips if not authed)
        self._schedule_open_prs_refresh()

    def _apply_open_pr_sheet_theme(self):
        """Reapply the dark palette explicitly for newer tksheet releases."""
        if self.open_prs_sheet is None:
            return
        self.open_prs_sheet.set_options(
            redraw=False,
            frame_bg=BG,
            table_bg=BG2,
            table_fg=FG,
            table_grid_fg=BG3,
            table_selected_rows_border_fg=ACCENT,
            table_selected_rows_bg='#1e3a5f',
            table_selected_rows_fg='#ffffff',
            table_selected_cells_border_fg=ACCENT,
            table_selected_cells_bg='#1e3a5f',
            table_selected_cells_fg='#ffffff',
            header_bg=BG3,
            header_fg=ACCENT2,
            header_grid_fg=BG3,
            header_selected_columns_bg=ACCENT,
            header_selected_columns_fg='#ffffff',
            header_selected_cells_bg=ACCENT,
            header_selected_cells_fg='#ffffff',
            index_bg=BG2,
            index_fg=FG,
            index_grid_fg=BG3,
            popup_menu_bg=BG2,
            popup_menu_fg=FG,
            popup_menu_highlight_bg=ACCENT,
            popup_menu_highlight_fg='#ffffff',
            vertical_scroll_background=BG2,
            horizontal_scroll_background=BG2,
            vertical_scroll_troughcolor=BG,
            horizontal_scroll_troughcolor=BG,
            vertical_scroll_bordercolor=BG,
            horizontal_scroll_bordercolor=BG,
            vertical_scroll_not_active_bg=BG3,
            horizontal_scroll_not_active_bg=BG3,
            vertical_scroll_active_bg=ACCENT,
            horizontal_scroll_active_bg=ACCENT,
            vertical_scroll_pressed_bg=ACCENT,
            horizontal_scroll_pressed_bg=ACCENT,
        )
        self.open_prs_sheet.refresh()

    def load_open_prs(self):
        """Load open PRs from GHE org (non-blocking)."""
        if not self.github_client or not self.current_user:
            return
        if self._bulk_pr_action_running:
            self._open_prs_status_var.set("⏸ Bulk approve…")
            return
        if self._open_prs_loading:
            return
        self._open_prs_loading = True
        self._open_prs_status_var.set("⏱ Loading…")
        threading.Thread(target=self._load_open_prs_thread, daemon=True).start()

    def _load_open_prs_thread(self):
        """Background: search GHE for open PRs, populate tree."""
        try:
            from datetime import timezone
            login = self.current_user.login
            mode = self._open_prs_filter_var.get()
            show_approved = self._show_approved_var.get()

            if mode == "review-requested":
                query = f"is:pr is:open review-requested:{login}"
            elif mode == "assigned":
                query = f"is:pr is:open assignee:{login}"
            elif mode == "created":
                query = f"is:pr is:open author:{login}"
            else:
                query = "is:pr is:open"
            
            # Filter by selected org if set
            if self._selected_org:
                query += f" org:{self._selected_org}"

            # Server-side: exclude fully-approved PRs unless checkbox is on
            if not show_approved:
                query += " -review:approved"

            results = self.github_client.search_issues(query)

            now_utc = datetime.now(timezone.utc)
            items = []

            # get_page(0) fetches exactly one API call (30 results max) — no lazy iteration
            for issue in results.get_page(0):
                repo_name = issue.repository.full_name
                pr_num    = issue.number
                title     = (issue.title or "")[:65]
                author    = issue.user.login if issue.user else "?"
                updated   = issue.updated_at

                # Normalise timezone
                if updated and updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)

                if updated:
                    delta = now_utc - updated
                    days  = delta.days
                    if days == 0:
                        hrs = delta.seconds // 3600
                        ago = f"{hrs}h ago" if hrs > 0 else "just now"
                    elif days == 1:
                        ago = "1d ago"
                    else:
                        ago = f"{days}d ago"
                else:
                    ago = "?"

                short_repo = repo_name.split('/')[-1]
                updated_secs = int(delta.total_seconds()) if updated else 999999999
                values = (short_repo, f"#{pr_num}", title, author, ago)
                items.append((values, f"{repo_name}:{pr_num}", updated_secs))

            # Only replace tree contents after successful fetch (no blank flash)
            def _populate():
                # Guard against stale callbacks from destroyed widget instances
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return
                self._open_prs_all_items = self._sort_open_pr_items(list(items))
                ts = datetime.now().strftime('%I:%M %p')
                approved_note = "" if show_approved else "  (approved hidden)"
                self._open_prs_last_refresh_var.set(f"Updated {ts} ET  |  {len(items)} PRs{approved_note}")
                self._open_prs_status_var.set("⏱ Auto: 45s")
                self.status_var.set(f"✓ {len(items)} open PRs")
                self._apply_pr_filters()
                self._update_open_pr_heading_state()

            self.after(0, _populate)

        except Exception as exc:
            self.after(0, lambda: self._open_prs_status_var.set("⚠ Refresh failed"))
            self.after(0, lambda e=exc: self.status_var.set(f"✗ Open PRs: {e}"))
        finally:
            self._open_prs_loading = False

    def _sort_open_pr_items(self, items):
        """Return items sorted using the active Open PR sort state."""
        sort_col = self._open_prs_sort_col or 'updated'
        descending = bool(self._open_prs_sort_desc)

        if sort_col == 'updated':
            # Smaller age = newer item. Descending means newest-first.
            return sorted(items, key=lambda item: item[2], reverse=not descending)

        col_idx = {'repo': 0, 'num': 1, 'title': 2, 'author': 3}.get(sort_col, 0)

        def sort_key(item):
            value = item[0][col_idx]
            if sort_col == 'num':
                try:
                    return int(str(value).lstrip('#'))
                except ValueError:
                    return 0
            return str(value).lower()

        return sorted(items, key=sort_key, reverse=descending)

    def _capture_open_pr_selection_targets(self):
        """Capture current Open PR selection by logical PR identity, not row index."""
        selected_targets = self._get_selected_open_pr_targets()
        current_target = self._selected_open_pr if self._selected_open_pr else None
        anchor_target = None

        if TKSHEET_AVAILABLE and self.open_prs_sheet is not None and self._open_pr_row_anchor is not None:
            try:
                row_data = self.open_prs_sheet.get_row_data(self._open_pr_row_anchor)
                anchor_target = self._row_data_to_open_pr_target(row_data)
            except Exception:
                anchor_target = None

        return {
            'selected_targets': selected_targets,
            'current_target': current_target,
            'anchor_target': anchor_target,
        }

    def _restore_open_pr_selection_targets(self, selection_state):
        """Restore Open PR selection after data refresh using PR identity mapping."""
        if not selection_state:
            return

        selected_targets = selection_state.get('selected_targets') or []
        current_target = selection_state.get('current_target')
        anchor_target = selection_state.get('anchor_target')

        if TKSHEET_AVAILABLE and self.open_prs_sheet is not None:
            target_to_row = {}
            for idx, (values, tag, _secs) in enumerate(self._open_prs_all_items):
                colon = tag.rfind(':')
                if colon < 0:
                    continue
                try:
                    target_to_row[(tag[:colon], int(tag[colon + 1:]))] = idx
                except ValueError:
                    continue

            rows = [target_to_row[target] for target in selected_targets if target in target_to_row]
            if not rows:
                self._open_pr_row_anchor = None
                return

            try:
                self._suppress_open_pr_selection_event = True
                self.open_prs_sheet.deselect("all", redraw=False)
                for pos, row_idx in enumerate(rows):
                    if pos == 0:
                        self.open_prs_sheet.select_row(row_idx, redraw=False, run_binding_func=False)
                    else:
                        self.open_prs_sheet.add_row_selection(
                            row_idx,
                            redraw=False,
                            run_binding_func=False,
                            set_as_current=False,
                        )

                current_row = target_to_row.get(current_target, rows[0])
                self.open_prs_sheet.set_currently_selected(row=current_row, column=0)
                self._open_pr_row_anchor = target_to_row.get(anchor_target, current_row)
                self.open_prs_sheet.refresh()
            except Exception:
                return
            finally:
                self._suppress_open_pr_selection_event = False
            return

        if self.open_prs_tree is not None:
            try:
                self._suppress_open_pr_selection_event = True
                item_ids = []
                target_set = set(selected_targets)
                for item_id in self.open_prs_tree.get_children():
                    tags = self.open_prs_tree.item(item_id, 'tags')
                    if not tags:
                        continue
                    tag = tags[0]
                    colon = tag.rfind(':')
                    if colon < 0:
                        continue
                    try:
                        target = (tag[:colon], int(tag[colon + 1:]))
                    except ValueError:
                        continue
                    if target in target_set:
                        item_ids.append(item_id)
                if item_ids:
                    self.open_prs_tree.selection_set(item_ids)
                    self.open_prs_tree.focus(item_ids[0])
            except tk.TclError:
                return
            finally:
                self._suppress_open_pr_selection_event = False

    def _update_open_pr_heading_state(self):
        """Refresh fallback tree headings to reflect the active sort state."""
        if self.open_prs_tree is None:
            return
        col_labels = {'repo': 'Repo', 'num': '#', 'title': 'Title',
                      'author': 'Author', 'updated': 'Updated'}
        try:
            for col, label in col_labels.items():
                arrow = ''
                if col == self._open_prs_sort_col:
                    arrow = ' ▼' if self._open_prs_sort_desc else ' ▲'
                self.open_prs_tree.heading(
                    col,
                    text=label + arrow,
                    command=lambda _c=col: self._sort_open_prs(_c),
                )
        except tk.TclError:
            return

    def _sort_open_prs(self, col):
        """Sort Open PRs and keep that order across refresh/filter updates."""
        if self._open_prs_sort_col == col:
            self._open_prs_sort_desc = not self._open_prs_sort_desc
        else:
            self._open_prs_sort_col = col
            self._open_prs_sort_desc = (col == 'updated')

        self._open_prs_all_items = self._sort_open_pr_items(list(self._open_prs_all_items))
        self._apply_pr_filters()
        self._update_open_pr_heading_state()

    def _apply_pr_filters(self):
        """Client-side filter across all loaded rows."""
        if not hasattr(self, '_open_prs_all_items') or not hasattr(self, '_pr_filter_vars'):
            return
        selection_state = self._capture_open_pr_selection_targets()
        _placeholders = {'Repo': 'Repo…', '#': '#…', 'Title': 'Title…', 'Author': 'Author…'}
        filters = {col: (v.get().strip().lower() if v.get() != _placeholders.get(col, '') else '')
                   for col, v in self._pr_filter_vars.items()}
        active = any(filters.values())
        filtered_items = self._open_prs_all_items if not active else [
            item for item in self._open_prs_all_items
            if all(
                not f or f in str(item[0][{'Repo': 0, '#': 1, 'Title': 2, 'Author': 3}[col]]).lower()
                for col, f in filters.items()
            )
        ]

        if TKSHEET_AVAILABLE and self.open_prs_sheet is not None:
            rows = [list(values) for values, _tag, _secs in filtered_items]
            self.open_prs_sheet.set_sheet_data(rows, reset_col_positions=False, redraw=True)
        elif self.open_prs_tree is not None:
            try:
                self.open_prs_tree.delete(*self.open_prs_tree.get_children())
                for values, tag, _secs in filtered_items:
                    self.open_prs_tree.insert('', 'end', values=values, tags=(tag,))
            except tk.TclError:
                return
        self._restore_open_pr_selection_targets(selection_state)

    def _clear_pr_filters(self):
        """Clear all filter fields (restore placeholders)."""
        if not hasattr(self, '_pr_filter_entries'):
            return
        for col_name, (entry, placeholder) in self._pr_filter_entries.items():
            self._pr_filter_vars[col_name].set(placeholder)
            entry.config(fg='#666666')

    def _on_list_frame_resize(self, event):
        """Queue an explicit tksheet resize after the pane geometry changes.

        The surrounding Tk frame resizes correctly during sash drags, but
        tksheet keeps its own internal canvas geometry until it is told the new
        width/height explicitly.
        """
        if self.open_prs_sheet is None:
            return
        if self._pr_resize_after_id is not None:
            try:
                self.after_cancel(self._pr_resize_after_id)
            except Exception:
                pass
        self._pr_resize_after_id = self.after_idle(self._resize_open_pr_sheet)

    def _resize_open_pr_sheet(self):
        """Apply the current pane size to the Open PRs tksheet widget."""
        self._pr_resize_after_id = None
        if self.open_prs_sheet is None or self._pr_list_frame is None:
            return
        try:
            width = self._pr_list_frame.winfo_width()
            height = self._pr_list_frame.winfo_height() - 28
            if width <= 1 or height <= 1:
                return
            self.open_prs_sheet.height_and_width(width=width, height=height)
            self.open_prs_sheet.refresh()
            self._resize_open_pr_columns_to_fit()
            self._sync_filter_widths()
        except Exception:
            pass

    def _resize_open_pr_columns_to_fit(self):
        """Stretch weighted columns so the visible table width stays filled."""
        if self.open_prs_sheet is None or not self._pr_col_defs:
            return
        try:
            table_width = self.open_prs_sheet.MT.winfo_width()
        except Exception:
            return
        if table_width <= 1:
            return

        try:
            current_widths = list(self.open_prs_sheet.get_column_widths())
        except Exception:
            return
        if len(current_widths) != len(self._pr_col_defs):
            return

        weighted = [(idx, weight) for idx, (_name, _ph, _px, weight) in enumerate(self._pr_col_defs) if weight > 0]
        if not weighted:
            return

        # Ignore duplicate callbacks when the visible canvas width has not changed.
        if self._pr_last_table_width == table_width:
            return
        self._pr_last_table_width = table_width

        target_total = max(table_width - 4, 0)
        current_total = sum(current_widths)
        delta = target_total - current_total
        if delta == 0:
            return

        min_widths = []
        for _name, _ph, px, weight in self._pr_col_defs:
            if weight > 0:
                min_widths.append(px if px > 0 else 180)
            else:
                min_widths.append(px if px > 0 else 60)

        new_widths = list(current_widths)
        total_weight = sum(weight for _, weight in weighted)
        remaining_delta = delta

        for pos, (idx, weight) in enumerate(weighted):
            share = remaining_delta if pos == len(weighted) - 1 else int(delta * (weight / total_weight))
            proposed = new_widths[idx] + share
            min_width = min_widths[idx]
            if proposed < min_width:
                share += (min_width - proposed)
                proposed = min_width
            new_widths[idx] = proposed
            remaining_delta -= share

        if new_widths != current_widths:
            self.open_prs_sheet.set_column_widths(new_widths)
            self.open_prs_sheet.refresh()

    def _sync_filter_widths(self, event=None):
        """Place filter entries pixel-exactly over their tksheet columns.

        Uses place() geometry so entries are positioned by the cumulated sheet
        column widths regardless of filter_frame's own column grid.  Called on
        sheet <Configure> and after column-header drags.
        """
        if not self._pr_filter_frame or not self._pr_col_defs:
            return
        if self.open_prs_sheet is None:
            return
        try:
            col_widths = self.open_prs_sheet.get_column_widths()
            if not col_widths:
                return
            # Left offset: sheet x within list_frame + CH canvas x within sheet.
            # With show_row_index=False the row-index panel is hidden so CH starts
            # at x=0 of the sheet widget.  The sheet itself is packed at x=0 too.
            try:
                ch_x_offset = self.open_prs_sheet.CH.winfo_x()
            except Exception:
                ch_x_offset = 0

            entry_h = 24
            x = ch_x_offset
            for i, (col_name, placeholder, _px, _w) in enumerate(self._pr_col_defs):
                w = int(col_widths[i]) if i < len(col_widths) else _px or 80
                if col_name in self._pr_filter_entries:
                    entry, _ = self._pr_filter_entries[col_name]
                    entry.place(x=x, y=2, width=w - 2, height=entry_h)
                x += w
        except Exception:
            pass

    def _on_sheet_col_header_clicked(self, event=None):
        """Column header click → sort rows by that column (toggle asc/desc)."""
        if self.open_prs_sheet is None or not self._open_prs_all_items:
            return
        try:
            # Determine which column was clicked from the mouse event (if available)
            # Fall back to currently-selected column if no event x coord
            col_idx = None
            if event is not None and hasattr(event, 'x'):
                col_idx = self.open_prs_sheet.MT.identify_col(x=event.x)
            if col_idx is None:
                sel = self.open_prs_sheet.get_currently_selected()
                col_idx = sel.column if sel and hasattr(sel, 'column') else None
            if col_idx is None:
                return
            col_key = {0: 'repo', 1: 'num', 2: 'title', 3: 'author', 4: 'updated'}.get(col_idx)
            if col_key:
                self._sort_open_prs(col_key)
        except Exception:
            pass

    def _on_sheet_pr_selected(self, event=None):
        """tksheet row selection → load PR detail."""
        if self._suppress_open_pr_selection_event:
            return
        if self.open_prs_sheet is None:
            return
        sel = self.open_prs_sheet.get_currently_selected()
        if not sel:
            return
        row_idx = sel.row if hasattr(sel, 'row') else (sel[0] if sel else None)
        if row_idx is None:
            return
        # Map visible row back to _open_prs_all_items via values match
        row_data = self.open_prs_sheet.get_row_data(row_idx)
        target = self._row_data_to_open_pr_target(row_data)
        if not target:
            return
        if target == self._loaded_open_pr_target:
            return
        repo_name, pr_num = target
        preserve_detail_tab = (self._selected_open_pr == target)
        self._selected_open_pr = (repo_name, pr_num)
        self._pr_detail_header_var.set(f"Loading PR #{pr_num} from {repo_name}…")
        self._pr_detail_meta_var.set("")
        self._pr_review_status_var.set("")
        self._pr_detail_text.config(state='normal')
        self._pr_detail_text.delete('1.0', tk.END)
        self._pr_detail_text.insert('1.0', 'Fetching details…', ('normal',))
        self._pr_detail_text.config(state='disabled')
        self._reset_pr_files_view("Fetching changed files…")
        for btn in (self._pr_approve_btn, self._pr_changes_btn, self._pr_comment_btn):
            btn.config(state='disabled')
        self._pr_approve_btn.config(text="Approve")
        if not preserve_detail_tab:
            self._pr_detail_nb.select(0)
        threading.Thread(
            target=self._load_pr_detail_thread,
            args=(repo_name, pr_num),
            daemon=True
        ).start()

    def _promote_open_pr_sheet_selection(self, event=None):
        """Convert table clicks into full-row selection for review/bulk actions."""
        if self.open_prs_sheet is None:
            return
        try:
            row_idx = self.open_prs_sheet.identify_row(event, exclude_index=False, allow_end=False) if event else None
        except Exception:
            row_idx = None
        if row_idx is None:
            return

        existing_rows = set(self._get_selected_open_pr_row_indexes())
        state = getattr(event, 'state', 0) if event else 0
        shift_pressed = bool(state & 0x0001)
        ctrl_pressed = bool(state & 0x0004)
        is_right_click = bool(event is not None and getattr(event, 'num', None) == 3)

        try:
            if is_right_click and row_idx in existing_rows:
                return

            if shift_pressed and self._open_pr_row_anchor is not None:
                start, end = sorted((self._open_pr_row_anchor, row_idx))
                self.open_prs_sheet.deselect("all", redraw=False)
                self.open_prs_sheet.select_row(start, redraw=False, run_binding_func=False)
                for idx in range(start + 1, end + 1):
                    self.open_prs_sheet.add_row_selection(
                        idx,
                        redraw=False,
                        run_binding_func=False,
                        set_as_current=(idx == row_idx),
                    )
                self.open_prs_sheet.set_currently_selected(row=row_idx, column=0)
                self.open_prs_sheet.refresh()
            elif ctrl_pressed:
                if self.open_prs_sheet.row_selected(row_idx, cells=True):
                    self.open_prs_sheet.toggle_select_row(
                        row_idx,
                        add_selection=True,
                        redraw=True,
                        run_binding_func=False,
                        set_as_current=True,
                    )
                else:
                    self.open_prs_sheet.add_row_selection(
                        row_idx,
                        redraw=True,
                        run_binding_func=False,
                        set_as_current=True,
                    )
                self._open_pr_row_anchor = row_idx
            else:
                self.open_prs_sheet.deselect("all", redraw=False)
                self.open_prs_sheet.select_row(row_idx, redraw=True, run_binding_func=False)
                self._open_pr_row_anchor = row_idx
        except Exception:
            return

        self._on_sheet_pr_selected()

    def _show_open_pr_sheet_menu(self, event=None):
        """Show an explicit context menu for the tksheet Open PR table."""
        if self.open_prs_sheet is None or self._open_prs_sheet_menu is None:
            return
        self._promote_open_pr_sheet_selection(event)
        if not self._get_selected_open_pr_targets():
            return
        try:
            self._open_prs_sheet_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self._open_prs_sheet_menu.grab_release()

    def _on_open_pr_selected(self, event=None):
        """Treeview fallback: row click → load PR detail."""
        if self._suppress_open_pr_selection_event:
            return
        if self.open_prs_tree is None:
            return
        sel = self.open_prs_tree.selection()
        if not sel:
            return
        tags = self.open_prs_tree.item(sel[0], 'tags')
        if not tags:
            return
        tag = tags[0]
        colon = tag.rfind(':')
        if colon < 0:
            return
        repo_name  = tag[:colon]
        pr_number  = int(tag[colon + 1:])
        target = (repo_name, pr_number)
        if target == self._loaded_open_pr_target:
            return
        preserve_detail_tab = (self._selected_open_pr == target)
        self._selected_open_pr = target

        # Reset detail pane while loading
        self._pr_detail_header_var.set(f"Loading PR #{pr_number} from {repo_name}…")
        self._pr_detail_meta_var.set("")
        self._pr_review_status_var.set("")
        self._pr_detail_text.config(state='normal')
        self._pr_detail_text.delete('1.0', tk.END)
        self._pr_detail_text.insert('1.0', 'Fetching details…', ('normal',))
        self._pr_detail_text.config(state='disabled')
        self._reset_pr_files_view("Fetching changed files…")
        for btn in (self._pr_approve_btn, self._pr_changes_btn, self._pr_comment_btn):
            btn.config(state='disabled')
        self._pr_approve_btn.config(text="Approve")
        if not preserve_detail_tab:
            self._pr_detail_nb.select(0)

        threading.Thread(
            target=self._load_pr_detail_thread,
            args=(repo_name, pr_number),
            daemon=True
        ).start()

    def _show_open_pr_tree_menu(self, event):
        """Show fallback Treeview context menu for bulk approval."""
        if self.open_prs_tree is None or self._open_prs_menu is None:
            return
        row_id = self.open_prs_tree.identify_row(event.y)
        if row_id and row_id not in self.open_prs_tree.selection():
            self.open_prs_tree.selection_set(row_id)
            self._on_open_pr_selected()
        if self.open_prs_tree.selection():
            self._open_prs_menu.tk_popup(event.x_root, event.y_root)

    def _load_pr_detail_thread(self, repo_name, pr_number):
        """Background: fetch PR object, reviews, commits, populate detail panel."""
        try:
            repo = self.github_client.get_repo(repo_name)
            pr   = repo.get_pull(pr_number)

            # Reviews — latest state per reviewer
            review_map = {}
            for r in pr.get_reviews():
                if r.state != 'DISMISSED':
                    review_map[r.user.login] = r.state

            # Pending review requests
            try:
                requested_users, _ = pr.get_review_requests()
                pending = [u.login for u in requested_users]
            except Exception:
                pending = []

            # Build review status line
            approved  = [l for l, s in review_map.items() if s == 'APPROVED']
            changes   = [l for l, s in review_map.items() if s == 'CHANGES_REQUESTED']
            parts = []
            if approved: parts.append(f"✅ Approved: {', '.join(approved)}")
            if changes:  parts.append(f"🔴 Changes: {', '.join(changes)}")
            if pending:  parts.append(f"⏳ Awaiting: {', '.join(pending)}")
            review_status = "  |  ".join(parts) if parts else "No reviews yet"

            # Header + meta
            header = f"#{pr.number}: {pr.title}"
            meta   = (
                f"{pr.head.ref} → {pr.base.ref}  |  "
                f"+{pr.additions} −{pr.deletions}  |  "
                f"{pr.changed_files} file(s)  |  "
                f"by {pr.user.login}"
            )

            # Body — strip Windows \r, truncate
            body = (pr.body or "*(No description)*").replace('\r\n', '\n').replace('\r', '\n')[:2000]

            # Recent commits (up to 6) — formatted as a markdown section
            try:
                commits = list(pr.get_commits())[-6:]
                commit_lines = "\n".join(
                    f"  {c.sha[:8]}  {c.commit.message.splitlines()[0][:72]}"
                    for c in commits
                )
                commit_section = f"\n\n---\n\n**Recent commits** ({pr.commits} total)\n\n```\n{commit_lines}\n```\n"
            except Exception:
                commit_section = ""

            detail_md = body + commit_section

            files = []
            files_error = None
            try:
                for f in pr.get_files():
                    files.append({
                        'filename': f.filename,
                        'status': f.status,
                        'additions': f.additions,
                        'deletions': f.deletions,
                        'changes': f.changes,
                        'patch': getattr(f, 'patch', None),
                        'blob_url': getattr(f, 'blob_url', None),
                        'raw_url': getattr(f, 'raw_url', None),
                        'previous_filename': getattr(f, 'previous_filename', None),
                    })
            except Exception as exc:
                files_error = str(exc)

            # Can we approve? (can't approve your own PR, can re-approve if dismissed)
            my_login   = self.current_user.login
            own_pr     = (pr.user.login == my_login)
            already_ok = (review_map.get(my_login) == 'APPROVED')
            btn_state  = 'disabled' if own_pr or already_ok else 'normal'

            def _update():
                self._selected_open_pr_obj = pr
                self._loaded_open_pr_target = (repo_name, pr_number)
                self._pr_detail_header_var.set(header)
                self._pr_detail_meta_var.set(meta)
                self._pr_review_status_var.set(review_status)
                self._pr_detail_text.config(state='normal')
                self._pr_detail_text.delete('1.0', tk.END)
                self._render_pr_markdown(self._pr_detail_text, detail_md)
                self._pr_detail_text.config(state='disabled')
                self._pr_detail_text.yview_moveto(0)
                self._pr_approve_btn.config(state=btn_state)
                self._pr_changes_btn.config(state='normal')
                self._pr_comment_btn.config(state='normal')
                self._pr_approve_btn.config(text="Approve")
                self._populate_pr_files(files, files_error)
                if own_pr:
                    self._pr_approve_btn.config(text="Own PR")
                elif already_ok:
                    self._pr_approve_btn.config(text="Approved")

            self.after(0, _update)

        except Exception as exc:
            self.after(0, lambda e=exc: self._pr_detail_header_var.set(f"Error: {e}"))

    def _render_pr_markdown(self, txt: tk.Text, md: str):
        """Render PR body markdown into the styled Text widget."""
        import re
        lines = md.splitlines()
        in_fence = False
        fence_buf: list = []

        def insert(content, *tags):
            txt.insert(tk.END, content, tags)

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.strip().startswith('```'):
                if not in_fence:
                    in_fence = True
                    fence_buf = []
                else:
                    in_fence = False
                    insert('\n' + '\n'.join(fence_buf) + '\n\n', 'fence')
                    fence_buf = []
                i += 1
                continue
            if in_fence:
                fence_buf.append(line)
                i += 1
                continue
            if re.match(r'^[-*_]{3,}\s*$', line):
                insert('─' * 55 + '\n', 'hr')
                i += 1
                continue
            m = re.match(r'^(#{1,3})\s+(.*)', line)
            if m:
                tag = f'h{len(m.group(1))}'
                text = re.sub(r'\*\*(.+?)\*\*', r'\1', m.group(2))
                text = re.sub(r'`(.+?)`', r'\1', text)
                insert(text + '\n', tag)
                i += 1
                continue
            m = re.match(r'^(\s*)[-*+]\s+(.*)', line)
            if m:
                bullet = '  ' * (len(m.group(1)) // 2) + '• '
                self._insert_inline_pr(txt, bullet + m.group(2) + '\n', 'bullet')
                i += 1
                continue
            m = re.match(r'^(\s*)\d+\.\s+(.*)', line)
            if m:
                self._insert_inline_pr(txt, '  ' * (len(m.group(1)) // 2) + m.group(2) + '\n', 'bullet')
                i += 1
                continue
            if not line.strip():
                insert('\n', 'normal')
                i += 1
                continue
            self._insert_inline_pr(txt, line + '\n', 'normal')
            i += 1

    def _insert_inline_pr(self, txt: tk.Text, text: str, base_tag='normal'):
        """Insert text with inline **bold**, *italic*, `code` formatting."""
        import re
        pattern = re.compile(r'(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)')
        pos = 0
        for m in pattern.finditer(text):
            if m.start() > pos:
                txt.insert(tk.END, text[pos:m.start()], (base_tag,))
            raw = m.group(0)
            if raw.startswith('**'):
                txt.insert(tk.END, m.group(2), ('bold',))
            elif raw.startswith('*'):
                txt.insert(tk.END, m.group(3), ('italic',))
            elif raw.startswith('`'):
                txt.insert(tk.END, m.group(4), ('code',))
            pos = m.end()
        if pos < len(text):
            txt.insert(tk.END, text[pos:], (base_tag,))

    def _set_pr_file_diff_text(self, content: str = "", base_tag: str = 'context'):
        """Replace the file diff viewer contents safely."""
        self._pr_file_diff_text.config(state='normal')
        self._pr_file_diff_text.delete('1.0', tk.END)
        if content:
            self._pr_file_diff_text.insert('1.0', content, (base_tag,))
        self._pr_file_diff_text.config(state='disabled')
        self._pr_file_diff_text.yview_moveto(0)
        self._pr_file_diff_text.xview_moveto(0)

    def _reset_pr_files_view(self, message: str = "Select a PR to inspect changed files"):
        """Reset the changed-files tab while a PR is loading."""
        self._pr_files_data = []
        self._pr_file_tree_map = {}
        self._selected_pr_file = None
        self._pr_files_summary_var.set(message)
        self._pr_file_detail_var.set("Select a changed file to review its patch")
        self._pr_open_file_btn.config(state='disabled')
        if hasattr(self, '_pr_files_tree'):
            self._pr_files_tree.delete(*self._pr_files_tree.get_children())
        self._set_pr_file_diff_text(message)

    def _populate_pr_files(self, files, error=None):
        """Populate the Files Changed tab with a file tree and diff viewer."""
        self._pr_files_data = list(files or [])
        self._pr_file_tree_map = {}
        self._selected_pr_file = None
        self._pr_open_file_btn.config(state='disabled')
        self._pr_files_tree.delete(*self._pr_files_tree.get_children())

        if error:
            self._pr_files_summary_var.set(f"Files failed to load: {error}")
            self._pr_file_detail_var.set("Unable to load changed files")
            self._set_pr_file_diff_text(f"Could not load changed files.\n\n{error}")
            return
        if not self._pr_files_data:
            self._pr_files_summary_var.set("No changed files on this PR")
            self._pr_file_detail_var.set("No changed files")
            self._set_pr_file_diff_text("No changed files were returned for this PR.")
            return

        total_add = sum(int(f.get('additions') or 0) for f in self._pr_files_data)
        total_del = sum(int(f.get('deletions') or 0) for f in self._pr_files_data)
        renamed = sum(1 for f in self._pr_files_data if f.get('previous_filename'))
        self._pr_files_summary_var.set(
            f"{len(self._pr_files_data)} file(s)  |  +{total_add} -{total_del}"
            + (f"  |  {renamed} renamed" if renamed else "")
        )

        dir_nodes = {"": ""}
        first_file = None
        for idx, file_info in enumerate(sorted(self._pr_files_data, key=lambda item: item.get('filename', ''))):
            parts = (file_info.get('filename') or '').split('/')
            parent = ""
            current_path = ""
            for part in parts[:-1]:
                current_path = f"{current_path}/{part}" if current_path else part
                if current_path not in dir_nodes:
                    iid = f"dir:{current_path}"
                    dir_nodes[current_path] = iid
                    self._pr_files_tree.insert(parent, 'end', iid=iid, text=part, values=('', '', ''))
                parent = dir_nodes[current_path]
                self._pr_files_tree.item(parent, open=True)
            file_iid = f"file:{idx}"
            self._pr_file_tree_map[file_iid] = file_info
            self._pr_files_tree.insert(
                parent, 'end', iid=file_iid,
                text=parts[-1] if parts else file_info.get('filename', '(unknown)'),
                values=(
                    file_info.get('status', ''),
                    file_info.get('additions', 0),
                    file_info.get('deletions', 0),
                )
            )
            if first_file is None:
                first_file = file_iid

        if first_file:
            self._pr_files_tree.selection_set(first_file)
            self._pr_files_tree.focus(first_file)
            self._pr_files_tree.see(first_file)
            self._show_pr_file(self._pr_file_tree_map[first_file])
        else:
            self._pr_file_detail_var.set("Select a changed file to review its patch")
            self._set_pr_file_diff_text("Select a changed file to inspect its patch.")

    def _on_pr_file_selected(self, event=None):
        """Update the diff viewer when a changed file is selected."""
        selection = self._pr_files_tree.selection()
        if not selection:
            return
        file_info = self._pr_file_tree_map.get(selection[0])
        if not file_info:
            return
        self._show_pr_file(file_info)

    def _show_pr_file(self, file_info):
        """Render a changed file patch in the diff viewer."""
        self._selected_pr_file = file_info
        filename = file_info.get('filename') or '(unknown file)'
        status = (file_info.get('status') or 'modified').replace('_', ' ')
        self._pr_file_detail_var.set(
            f"{filename}  |  {status}  |  +{file_info.get('additions', 0)} -{file_info.get('deletions', 0)}"
        )
        self._pr_open_file_btn.config(state='normal' if file_info.get('blob_url') else 'disabled')

        self._pr_file_diff_text.config(state='normal')
        self._pr_file_diff_text.delete('1.0', tk.END)
        self._pr_file_diff_text.insert(tk.END, f"{filename}\n", ('meta',))
        if file_info.get('previous_filename'):
            self._pr_file_diff_text.insert(
                tk.END,
                f"renamed from {file_info['previous_filename']}\n",
                ('path',)
            )
        self._pr_file_diff_text.insert(
            tk.END,
            f"status: {status}  |  +{file_info.get('additions', 0)} -{file_info.get('deletions', 0)}\n\n",
            ('context',)
        )
        patch = file_info.get('patch')
        if not patch:
            self._pr_file_diff_text.insert(
                tk.END,
                "Patch preview is unavailable for this file (binary file, large diff, or GitHub omitted it).\n"
                "Use Open File or Open PR for the full hosted view.",
                ('context',)
            )
        else:
            lines = patch.splitlines()
            if len(lines) > 400:
                lines = lines[:400]
                lines.append('... diff truncated ...')
            for line in lines:
                tag = 'context'
                if line.startswith('@@'):
                    tag = 'hunk'
                elif line.startswith('+++') or line.startswith('---'):
                    tag = 'path'
                elif line.startswith('+') and not line.startswith('+++'):
                    tag = 'add'
                elif line.startswith('-') and not line.startswith('---'):
                    tag = 'del'
                self._pr_file_diff_text.insert(tk.END, line + '\n', (tag,))
        self._pr_file_diff_text.config(state='disabled')
        self._pr_file_diff_text.yview_moveto(0)
        self._pr_file_diff_text.xview_moveto(0)

    def _open_selected_pr_file_in_browser(self):
        """Open the selected changed file in the host browser."""
        if not self._selected_pr_file:
            return
        url = self._selected_pr_file.get('blob_url')
        if not url:
            return
        from platformgen.tools.host_cmd import open_url as _open_url
        _open_url(url)

    def _row_data_to_open_pr_target(self, row_data):
        """Map a visible row's displayed values back to (repo_name, pr_number)."""
        if not row_data or len(row_data) < 2:
            return None
        short_repo = str(row_data[0])
        pr_num_str = str(row_data[1]).lstrip('#')
        try:
            pr_num = int(pr_num_str)
        except ValueError:
            return None
        for values, tag, _secs in self._open_prs_all_items:
            if values[0] == short_repo and values[1] == f'#{pr_num}':
                colon = tag.rfind(':')
                if colon < 0:
                    return None
                return tag[:colon], pr_num
        return None

    def _get_selected_open_pr_row_indexes(self):
        """Return selected row indexes, inferring rows from cell selections when needed."""
        if self.open_prs_sheet is None:
            return []
        try:
            selected_rows = list(self.open_prs_sheet.get_selected_rows(return_tuple=True))
        except Exception:
            selected_rows = []
        if selected_rows:
            return sorted(dict.fromkeys(selected_rows))
        try:
            selected_rows = [row for row, _col in self.open_prs_sheet.get_selected_cells()]
        except Exception:
            selected_rows = []
        return sorted(dict.fromkeys(selected_rows))

    def _get_selected_open_pr_targets(self):
        """Return selected Open PR targets as [(repo_name, pr_number), ...]."""
        targets = []
        seen = set()
        if TKSHEET_AVAILABLE and self.open_prs_sheet is not None:
            selected_rows = self._get_selected_open_pr_row_indexes()
            for row_idx in selected_rows:
                target = self._row_data_to_open_pr_target(self.open_prs_sheet.get_row_data(row_idx))
                if target and target not in seen:
                    targets.append(target)
                    seen.add(target)
        elif self.open_prs_tree is not None:
            for item_id in self.open_prs_tree.selection():
                tags = self.open_prs_tree.item(item_id, 'tags')
                if not tags:
                    continue
                tag = tags[0]
                colon = tag.rfind(':')
                if colon < 0:
                    continue
                try:
                    target = (tag[:colon], int(tag[colon + 1:]))
                except ValueError:
                    continue
                if target not in seen:
                    targets.append(target)
                    seen.add(target)
        return targets

    def _bulk_approve_selected_open_prs(self):
        """Quick-approve one or more selected PRs."""
        if not self.github_client or not self.current_user:
            return
        if self._bulk_pr_action_running:
            messagebox.showinfo("Bulk Approve", "A bulk approve action is already running.")
            return
        targets = self._get_selected_open_pr_targets()
        if not targets:
            messagebox.showwarning("Bulk Approve", "Select one or more PRs first.")
            return

        note = simpledialog.askstring(
            "Quick Approve Selected PRs",
            f"Approval note for {len(targets)} selected PR(s):",
            initialvalue="Approved via Auger Platform"
        )
        if note is None:
            return
        note = note or "Approved via Auger Platform"

        preview = "\n".join(f"- {repo} #{num}" for repo, num in targets[:8])
        extra = f"\n... and {len(targets) - 8} more" if len(targets) > 8 else ""
        if not messagebox.askyesno(
            "Confirm Bulk Approve",
            f"Approve {len(targets)} selected PR(s)?\n\n{preview}{extra}\n\nReview note:\n{note}"
        ):
            return

        self._bulk_pr_action_running = True
        self._open_prs_status_var.set(f"Approving {len(targets)}...")
        self.status_var.set(f"Approving {len(targets)} selected PR(s)…")
        threading.Thread(
            target=self._bulk_approve_open_prs_thread,
            args=(targets, note),
            daemon=True
        ).start()

    def _bulk_approve_open_prs_thread(self, targets, note):
        """Approve selected PRs in the background and summarize results."""
        my_login = self.current_user.login if self.current_user else ""
        approved = []
        skipped = []
        failed = []

        for repo_name, pr_number in targets:
            try:
                repo = self.github_client.get_repo(repo_name)
                pr = repo.get_pull(pr_number)
                if my_login and pr.user and pr.user.login == my_login:
                    skipped.append((repo_name, pr_number, "own PR"))
                    continue

                already_approved = False
                try:
                    review_map = {}
                    for review in pr.get_reviews():
                        if review.state != 'DISMISSED' and review.user:
                            review_map[review.user.login] = review.state
                    already_approved = (review_map.get(my_login) == 'APPROVED')
                except Exception:
                    already_approved = False

                if already_approved:
                    skipped.append((repo_name, pr_number, "already approved"))
                    continue

                pr.create_review(body=note, event="APPROVE")
                approved.append((repo_name, pr_number))
            except Exception as exc:
                failed.append((repo_name, pr_number, str(exc)))

        def _finish():
            self._bulk_pr_action_running = False
            self.load_open_prs()

            lines = []
            if approved:
                lines.append(f"Approved: {len(approved)}")
            if skipped:
                lines.append(f"Skipped: {len(skipped)}")
            if failed:
                lines.append(f"Failed: {len(failed)}")
            self.status_var.set("Bulk approve complete" if lines else "Bulk approve finished")

            detail_lines = []
            if approved:
                detail_lines.append("Approved:")
                detail_lines.extend(f"  - {repo} #{num}" for repo, num in approved[:12])
            if skipped:
                detail_lines.append("\nSkipped:")
                detail_lines.extend(f"  - {repo} #{num} ({reason})" for repo, num, reason in skipped[:12])
            if failed:
                detail_lines.append("\nFailed:")
                detail_lines.extend(f"  - {repo} #{num}: {reason}" for repo, num, reason in failed[:8])
            if len(failed) > 8:
                detail_lines.append(f"  - ... {len(failed) - 8} more failures")

            title = "Bulk Approve Complete" if not failed else "Bulk Approve Finished with Errors"
            summary = "\n".join(lines + ([""] + detail_lines if detail_lines else [])).strip()
            self._open_prs_status_var.set("Auto: 45s")
            self.status_var.set("Bulk approve complete" if not failed else "Bulk approve finished with errors")
            if summary:
                messagebox.showinfo(title, summary)

        self.after(0, _finish)

    def _approve_open_pr(self):
        """Submit APPROVE review on the selected PR."""
        if not self._selected_open_pr_obj:
            messagebox.showwarning("No PR", "Select a PR first")
            return
        pr = self._selected_open_pr_obj
        body = simpledialog.askstring(
            "Approve PR",
            f"Approval note for #{pr.number} (optional):",
            initialvalue="Approved via Auger Platform"
        )
        if body is None:   # user cancelled
            return
        self._submit_open_pr_review_async(
            pr=pr,
            target=self._selected_open_pr,
            body=body or "Approved via Auger Platform",
            event="APPROVE",
            success_title="Approved",
            success_message=f"PR #{pr.number} approved",
            status_text=f"Approving PR #{pr.number}..."
        )

    def _request_changes_open_pr(self):
        """Submit REQUEST_CHANGES review on the selected PR."""
        if not self._selected_open_pr_obj:
            messagebox.showwarning("No PR", "Select a PR first")
            return
        pr = self._selected_open_pr_obj
        body = simpledialog.askstring(
            "Request Changes",
            f"What changes are needed for PR #{pr.number}? (required)"
        )
        if not body:
            return
        self._submit_open_pr_review_async(
            pr=pr,
            target=self._selected_open_pr,
            body=body,
            event="REQUEST_CHANGES",
            success_title="Done",
            success_message=f"Requested changes on PR #{pr.number}",
            status_text=f"Requesting changes on PR #{pr.number}..."
        )

    def _comment_open_pr(self):
        """Submit a COMMENT review on the selected PR."""
        if not self._selected_open_pr_obj:
            messagebox.showwarning("No PR", "Select a PR first")
            return
        pr = self._selected_open_pr_obj
        body = simpledialog.askstring("Comment", f"Comment on PR #{pr.number}:")
        if not body:
            return
        self._submit_open_pr_review_async(
            pr=pr,
            target=self._selected_open_pr,
            body=body,
            event="COMMENT",
            success_title="Done",
            success_message=f"Comment added to PR #{pr.number}",
            status_text=f"Commenting on PR #{pr.number}..."
        )

    def _submit_open_pr_review_async(self, pr, target, body, event, success_title, success_message, status_text):
        """Submit a single-PR review off the Tk UI thread, then refresh safely."""
        self.status_var.set(status_text)

        def _work():
            try:
                pr.create_review(body=body, event=event)
            except Exception as exc:
                self.after(0, lambda e=exc: messagebox.showerror("Error", f"{success_title} failed: {e}"))
                self.after(0, lambda e=exc: self.status_var.set(f"Review action failed: {e}"))
                return

            def _finish():
                try:
                    if not self.winfo_exists():
                        return
                except Exception:
                    return
                self.status_var.set(success_message)
                messagebox.showinfo(success_title, success_message)
                if target:
                    threading.Thread(target=self._load_pr_detail_thread, args=target, daemon=True).start()

            self.after(0, _finish)

        threading.Thread(target=_work, daemon=True).start()

    def _open_selected_pr_in_browser(self):
        """Open the selected PR in the host browser."""
        if self._selected_open_pr_obj:
            from platformgen.tools.host_cmd import open_url as _open_url
            _open_url(self._selected_open_pr_obj.html_url)

    def _schedule_open_prs_refresh(self):
        """Auto-refresh loop: reload open PRs every 45 seconds."""
        try:
            if not self.winfo_exists():
                return  # Widget was destroyed (e.g. hot-reload); stop the timer loop
        except Exception:
            return
        self.load_open_prs()
        self._open_prs_after_id = self.after(45_000, self._schedule_open_prs_refresh)

    def _create_status_bar(self, parent):
        """Create status bar"""
        status_frame = tk.Frame(parent, bg=BG2)
        status_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.status_var = tk.StringVar(value="Not authenticated")
        tk.Label(
            status_frame, textvariable=self.status_var, font=('Segoe UI', 9),
            fg=FG, bg=BG2, anchor=tk.W
        ).pack(side=tk.LEFT, padx=5, pady=3)
    
    def _show_token_help(self):
        """Show help for getting GitHub token"""
        msg = """GitHub Token is configured in API Config widget.

Current token source: GHE_TOKEN from .env file

To update the token:
1. Go to API Config widget (in Widgets menu)
2. Find "GitHub Enterprise (SSH)" section
3. Update the "API Token" field
4. Click "Save to .env"
5. Return here and click "Connect"

To generate a new token:
1. Go to GitHub Enterprise Settings
2. Developer settings → Personal access tokens
3. Generate new token (classic)
4. Required scopes: repo, read:org, workflow
"""
        messagebox.showinfo("GitHub Token Help", msg)
        ghe_url = os.getenv('GHE_URL', 'https://github.helix.gsa.gov')
        from platformgen.tools.host_cmd import open_url as _open_url; _open_url(f"{ghe_url}/settings/tokens")
    
    def _load_saved_token(self):
        """Load saved GitHub token"""
        for token_file in (self.token_file, self.legacy_token_file):
            if not os.path.exists(token_file):
                continue
            try:
                with open(token_file, 'r') as f:
                    token = f.read().strip()
                    if token:
                        self.token_var.set(token)
                        self.authenticate()
                        return
            except Exception as e:
                print(f"Error loading token: {e}")
    
    def _save_token(self, token):
        """Save GitHub token"""
        try:
            with open(self.token_file, 'w') as f:
                f.write(token)
            os.chmod(self.token_file, 0o600)  # Restrict permissions
        except Exception as e:
            print(f"Error saving token: {e}")
    
    def authenticate(self):
        """Authenticate with GitHub"""
        if not GITHUB_AVAILABLE:
            messagebox.showerror("Error", "PyGithub not installed. Run: pip install PyGithub requests")
            return
        
        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("No Token", "Please enter a GitHub token")
            return
        
        self.status_var.set("Authenticating...")
        threading.Thread(target=self._authenticate_thread, args=(token,), daemon=True).start()
    
    def _authenticate_thread(self, token):
        """Authenticate in background thread"""
        try:
            # Determine base URL from environment or use default
            ghe_url = os.getenv('GHE_URL', 'https://github.helix.gsa.gov')
            
            # If using GitHub Enterprise, configure base URL
            if 'github.helix.gsa.gov' in ghe_url:
                # GitHub Enterprise
                self.github_client = Github(base_url=f"{ghe_url}/api/v3", login_or_token=token)
            else:
                # GitHub.com
                self.github_client = Github(token)
            
            self.current_user = self.github_client.get_user()
            
            # Test authentication
            login = self.current_user.login
            name = self.current_user.name or login
            
            # Load available orgs
            try:
                orgs = self.current_user.get_orgs()
                self._available_orgs = sorted([org.login for org in orgs])
                # Also add user's personal repos by adding their login
                if login not in self._available_orgs:
                    self._available_orgs.insert(0, login)
            except Exception:
                self._available_orgs = [login]
            
            # Load preferred org from GHE_ORG or default to first available
            preferred_org = os.getenv('GHE_ORG', '').strip() or None
            if preferred_org and preferred_org in self._available_orgs:
                self._selected_org = preferred_org
            elif self._available_orgs:
                self._selected_org = self._available_orgs[0]
            
            self._save_token(token)
            
            self.after(0, lambda: self.user_label.config(text=f"✓ {name} (@{login})", fg=SUCCESS))
            self.after(0, lambda: self.status_var.set(f"✓ Authenticated as {login}"))
            self.after(0, self._update_org_selector)
            self.after(0, self.load_repositories)
            self.after(0, self.load_open_prs)
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Authentication failed: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Auth Error", str(e)))
    
    def _update_org_selector(self):
        """Update org dropdown with available orgs"""
        if self._available_orgs:
            self.org_combo.configure(values=self._available_orgs)
            if self._selected_org:
                self.org_var.set(self._selected_org)
            elif self._available_orgs:
                self.org_var.set(self._available_orgs[0])
                self._selected_org = self._available_orgs[0]
    
    def on_org_selected(self):
        """Handle org selection change"""
        self._selected_org = self.org_var.get()
        if self._selected_org:
            self.load_repositories()
    
    def load_repositories(self):
        """Load user repositories"""
        if not self.github_client:
            messagebox.showwarning("Not Authenticated", "Please authenticate first")
            return
        
        self.status_var.set("Loading repositories...")
        threading.Thread(target=self._load_repositories_thread, daemon=True).start()
    
    def _load_repositories_thread(self):
        """Load repositories in background thread"""
        try:
            repos = []  # Use list to preserve order by org

            # If filtering by org, load only that org's repos
            if self._selected_org and self._selected_org != self.current_user.login:
                org = self.github_client.get_organization(self._selected_org)
                for repo in org.get_repos():
                    repos.append(repo.full_name)
            # If personal repos selected, show only user repos
            elif self._selected_org == self.current_user.login:
                for repo in self.current_user.get_repos():
                    repos.append(repo.full_name)
            # Otherwise load all (fallback)
            else:
                for repo in self.current_user.get_repos():
                    repos.append(repo.full_name)
                for org in self.current_user.get_orgs():
                    for repo in org.get_repos():
                        repos.append(repo.full_name)
                repos = sorted(list(set(repos)))
            
            repos = sorted(repos)
            self.after(0, lambda: self.repo_combo.configure(values=repos))
            self.after(0, lambda: self.status_var.set(f"✓ Loaded {len(repos)} repositories"))
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Failed to load repos: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
    
    def on_repo_selected(self, event=None):
        """Handle repository selection"""
        repo_name = self.repo_var.get()
        if not repo_name:
            return
        
        self.status_var.set(f"Loading {repo_name}...")
        threading.Thread(target=self._load_repo_thread, args=(repo_name,), daemon=True).start()
    
    def _load_repo_thread(self, repo_name):
        """Load repository details in background"""
        try:
            self.current_repo = self.github_client.get_repo(repo_name)
            
            # Update repo info
            info = f"⭐ {self.current_repo.stargazers_count} | "
            info += f"🔱 {self.current_repo.forks_count} | "
            info += f"👁️ {self.current_repo.watchers_count} | "
            info += f"🐛 {self.current_repo.open_issues_count} open issues"
            
            if self.current_repo.language:
                info += f" | 💻 {self.current_repo.language}"
            
            self.after(0, lambda: self.repo_info_label.config(text=info))
            self.after(0, lambda: self.status_var.set(f"✓ Loaded {repo_name}"))
            
            # Load overview
            self.after(0, self._load_overview)
            
            # Load branches for commits tab
            self.after(0, self.load_branches)
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Failed to load repo: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
    
    def _load_overview(self):
        """Load repository overview"""
        if not self.current_repo:
            return
        
        self.overview_text.config(state='normal')
        self.overview_text.delete('1.0', tk.END)
        
        content = f"Repository: {self.current_repo.full_name}\n"
        content += f"{'=' * 60}\n\n"
        
        if self.current_repo.description:
            content += f"Description: {self.current_repo.description}\n\n"
        
        content += f"Default Branch: {self.current_repo.default_branch}\n"
        content += f"Stars: ⭐ {self.current_repo.stargazers_count}\n"
        content += f"Forks: 🔱 {self.current_repo.forks_count}\n"
        content += f"Watchers: 👁️ {self.current_repo.watchers_count}\n"
        content += f"Open Issues: 🐛 {self.current_repo.open_issues_count}\n"
        content += f"Language: {self.current_repo.language}\n"
        content += f"Size: {self.current_repo.size} KB\n"
        content += f"Created: {self.current_repo.created_at}\n"
        content += f"Updated: {self.current_repo.updated_at}\n"
        content += f"License: {self.current_repo.license.name if self.current_repo.license else 'None'}\n\n"
        
        if self.current_repo.homepage:
            content += f"Homepage: {self.current_repo.homepage}\n\n"
        
        content += f"{'=' * 60}\n\n"
        
        # Try to load README
        try:
            readme = self.current_repo.get_readme()
            content += "README\n"
            content += f"{'=' * 60}\n\n"
            content += readme.decoded_content.decode('utf-8')
        except:
            content += "No README found\n"
        
        self.overview_text.insert('1.0', content)
        self.overview_text.config(state='disabled')
    
    def load_issues(self):
        """Load repository issues"""
        if not self.current_repo:
            messagebox.showwarning("No Repository", "Please select a repository first")
            return
        
        self.status_var.set("Loading issues...")
        threading.Thread(target=self._load_issues_thread, daemon=True).start()
    
    def _load_issues_thread(self):
        """Load issues in background thread"""
        try:
            state = self.issue_state_var.get()
            issues = self.current_repo.get_issues(state=state)
            
            # Clear tree
            self.after(0, lambda: self.issues_tree.delete(*self.issues_tree.get_children()))
            
            count = 0
            for issue in issues:
                if issue.pull_request:
                    continue  # Skip PRs
                
                values = (
                    f"#{issue.number}",
                    issue.title[:80],
                    issue.user.login,
                    issue.state,
                    issue.created_at.strftime('%Y-%m-%d %H:%M')
                )
                
                self.after(0, lambda v=values: self.issues_tree.insert('', 'end', values=v))
                count += 1
                
                if count >= 100:  # Limit to 100
                    break
            
            self.after(0, lambda: self.status_var.set(f"✓ Loaded {count} issues"))
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Failed to load issues: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
    
    def load_pull_requests(self):
        """Load repository pull requests"""
        if not self.current_repo:
            messagebox.showwarning("No Repository", "Please select a repository first")
            return
        
        self.status_var.set("Loading pull requests...")
        threading.Thread(target=self._load_prs_thread, daemon=True).start()
    
    def _load_prs_thread(self):
        """Load PRs in background thread"""
        try:
            state = self.pr_state_var.get()
            pulls = self.current_repo.get_pulls(state=state)
            
            # Clear tree
            self.after(0, lambda: self.prs_tree.delete(*self.prs_tree.get_children()))
            
            count = 0
            for pr in pulls:
                values = (
                    f"#{pr.number}",
                    pr.title[:80],
                    pr.user.login,
                    pr.state,
                    pr.created_at.strftime('%Y-%m-%d %H:%M')
                )
                
                self.after(0, lambda v=values: self.prs_tree.insert('', 'end', values=v))
                count += 1
                
                if count >= 100:  # Limit to 100
                    break
            
            self.after(0, lambda: self.status_var.set(f"✓ Loaded {count} pull requests"))
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Failed to load PRs: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
    
    def load_commits(self):
        """Load repository commits"""
        if not self.current_repo:
            messagebox.showwarning("No Repository", "Please select a repository first")
            return
        
        branch = self.commit_branch_var.get() or self.current_repo.default_branch
        self.status_var.set(f"Loading commits from {branch}...")
        threading.Thread(target=self._load_commits_thread, args=(branch,), daemon=True).start()
    
    def _load_commits_thread(self, branch):
        """Load commits in background thread"""
        try:
            limit = int(self.commit_limit_var.get())
            commits = self.current_repo.get_commits(sha=branch)
            
            # Clear tree
            self.after(0, lambda: self.commits_tree.delete(*self.commits_tree.get_children()))
            
            count = 0
            for commit in commits:
                values = (
                    commit.sha[:8],
                    commit.commit.message.split('\n')[0][:100],
                    commit.commit.author.name,
                    commit.commit.author.date.strftime('%Y-%m-%d %H:%M')
                )
                
                self.after(0, lambda v=values: self.commits_tree.insert('', 'end', values=v))
                count += 1
                
                if count >= limit:
                    break
            
            self.after(0, lambda: self.status_var.set(f"✓ Loaded {count} commits"))
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Failed to load commits: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
    
    def load_branches(self):
        """Load repository branches"""
        if not self.current_repo:
            return
        
        self.status_var.set("Loading branches...")
        threading.Thread(target=self._load_branches_thread, daemon=True).start()
    
    def _load_branches_thread(self):
        """Load branches in background thread"""
        try:
            branches = self.current_repo.get_branches()
            
            # Clear tree
            self.after(0, lambda: self.branches_tree.delete(*self.branches_tree.get_children()))
            
            branch_names = []
            for branch in branches:
                values = (
                    branch.name,
                    "Yes" if branch.protected else "No",
                    branch.commit.sha[:40]
                )
                
                self.after(0, lambda v=values: self.branches_tree.insert('', 'end', values=v))
                branch_names.append(branch.name)
            
            # Update commit branch combo
            self.after(0, lambda: self.commit_branch_combo.configure(values=branch_names))
            if branch_names:
                self.after(0, lambda: self.commit_branch_var.set(self.current_repo.default_branch))
            
            self.after(0, lambda: self.status_var.set(f"✓ Loaded {len(branch_names)} branches"))
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Failed to load branches: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
    
    def load_actions(self):
        """Load GitHub Actions workflow runs"""
        if not self.current_repo:
            messagebox.showwarning("No Repository", "Please select a repository first")
            return
        
        self.status_var.set("Loading workflow runs...")
        threading.Thread(target=self._load_actions_thread, daemon=True).start()
    
    def _load_actions_thread(self):
        """Load actions in background thread"""
        try:
            limit = int(self.actions_limit_var.get())
            runs = self.current_repo.get_workflow_runs()
            
            # Clear tree
            self.after(0, lambda: self.actions_tree.delete(*self.actions_tree.get_children()))
            
            count = 0
            for run in runs:
                values = (
                    str(run.id),
                    run.name[:30],
                    run.status,
                    run.conclusion or "N/A",
                    run.head_branch,
                    run.created_at.strftime('%Y-%m-%d %H:%M')
                )
                
                self.after(0, lambda v=values: self.actions_tree.insert('', 'end', values=v))
                count += 1
                
                if count >= limit:
                    break
            
            self.after(0, lambda: self.status_var.set(f"✓ Loaded {count} workflow runs"))
            
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Failed to load actions: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
    
    def _open_repo_in_browser(self):
        """Open current repository in browser"""
        if self.current_repo:
            from platformgen.tools.host_cmd import open_url as _open_url; _open_url(self.current_repo.html_url)
    
    def _on_issue_double_click(self, event):
        """Open issue in browser"""
        selection = self.issues_tree.selection()
        if not selection:
            return
        
        values = self.issues_tree.item(selection[0])['values']
        issue_number = int(values[0].replace('#', ''))
        issue = self.current_repo.get_issue(issue_number)
        from platformgen.tools.host_cmd import open_url as _open_url; _open_url(issue.html_url)
    
    def _on_pr_double_click(self, event):
        """Open PR in browser"""
        selection = self.prs_tree.selection()
        if not selection:
            return
        
        values = self.prs_tree.item(selection[0])['values']
        pr_number = int(values[0].replace('#', ''))
        pr = self.current_repo.get_pull(pr_number)
        from platformgen.tools.host_cmd import open_url as _open_url; _open_url(pr.html_url)
    
    def _on_commit_double_click(self, event):
        """Open commit in browser"""
        selection = self.commits_tree.selection()
        if not selection:
            return
        
        values = self.commits_tree.item(selection[0])['values']
        sha = values[0]
        commit = self.current_repo.get_commit(sha)
        from platformgen.tools.host_cmd import open_url as _open_url; _open_url(commit.html_url)
    
    def _on_action_double_click(self, event):
        """Open workflow run in browser"""
        selection = self.actions_tree.selection()
        if not selection:
            return
        
        values = self.actions_tree.item(selection[0])['values']
        run_id = int(values[0])
        run = self.current_repo.get_workflow_run(run_id)
        from platformgen.tools.host_cmd import open_url as _open_url; _open_url(run.html_url)
    
    def _create_issue(self):
        """Create a new issue"""
        if not self.current_repo:
            messagebox.showwarning("No Repository", "Please select a repository first")
            return
        
        # Simple dialog for issue creation
        title = simpledialog.askstring("Create Issue", "Issue title:")
        if not title:
            return
        
        body = simpledialog.askstring("Create Issue", "Issue body (optional):")
        
        try:
            issue = self.current_repo.create_issue(title=title, body=body or "")
            messagebox.showinfo("Success", f"Issue #{issue.number} created!")
            self.load_issues()
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create issue: {e}")
    
    def build_context(self):
        """Build context for the Ask Genny panel"""
        context = "GITHUB WIDGET CONTEXT\n\n"
        
        if self.current_user:
            context += f"Authenticated as: {self.current_user.login}\n\n"
        
        if self.current_repo:
            context += f"Current Repository: {self.current_repo.full_name}\n"
            context += f"  Default Branch: {self.current_repo.default_branch}\n"
            context += f"  Stars: {self.current_repo.stargazers_count}\n"
            context += f"  Open Issues: {self.current_repo.open_issues_count}\n"
            context += f"  Language: {self.current_repo.language}\n\n"
        
        # Current tab
        current_tab = self.notebook.index(self.notebook.select())
        tab_names = ["Open PRs", "Overview", "Issues", "Pull Requests", "Commits", "Branches", "Actions"]
        if current_tab < len(tab_names):
            context += f"Current Tab: {tab_names[current_tab]}\n"
        
        return context


# Widget registration
def create_widget(parent, context_builder_callback=None):
    """Factory function for widget creation"""
    return GitHubWidget(parent, context_builder_callback)
