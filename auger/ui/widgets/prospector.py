"""
Prospector Widget - CVE Analysis Tool
Integrated version of Au Prospector for the Auger SRE Platform
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import subprocess
import json
import os
import re
import requests
from datetime import datetime
import threading
from pathlib import Path
import sys
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu

from auger.tools.jenkins import (
    JenkinsAuthError,
    JenkinsConfigError,
    get_all_repositories,
    get_repository_branches,
    get_branch_build_numbers,
    parse_prisma_vulnerabilities,
    parse_prisma_compliance,
)
from dotenv import load_dotenv
load_dotenv(Path.home() / '.auger' / '.env')

# Auger Platform Colors
BG = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
FG = '#e0e0e0'
ACCENT = '#007acc'
ACCENT2 = '#4ec9b0'
SUCCESS = '#4ec9b0'
ERROR = '#f44747'
WARNING = '#ce9178'



class ProspectorWidget(tk.Frame):
    """CVE Analysis and Security Scanning Widget"""
    WIDGET_ICON_NAME = "prospector"
    
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        
        # Get Jenkins credentials from environment
        self.jenkins_url = os.environ.get("JENKINS_URL", "https://jenkins-mcaas.helix.gsa.gov")
        self.jenkins_user = (
            os.environ.get("JENKINS_USER")
            or os.environ.get("GHE_USERNAME")
            or os.environ.get("USER")
        )
        self.jenkins_token = os.environ.get("JENKINS_API_TOKEN") or os.environ.get("JENKINS_API_KEY")
        
        # Initialize data storage
        self.vulnerabilities_data = []
        self.compliance_data = []
        self.console_log_data = ""
        self.current_git_info = None
        self.current_docker_image = None
        
        # Configure ttk combobox dropdown font size
        self.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))
        
        self._create_ui()
        
        # Load repositories on startup
        self.after(100, self.load_repositories)
    
    def _create_ui(self):
        """Create the widget UI"""
        # Pre-create tab icons
        self._tab_icon_console = _icons.get('terminal', 18)
        self._tab_icon_summary = _icons.get('check', 18)
        self._tab_icon_vulns = _icons.get('warning', 18)
        self._tab_icon_compliance = _icons.get('error', 18)
        self._tab_icon_repo = _icons.get('folder', 18)
        self._tab_icon_docker = _icons.get('docker', 18)
        self._tab_icon_cvediff = _icons.get('search', 18)
        # Header
        header = tk.Frame(self, bg=ACCENT, height=40)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        try:
            _ico = _icons.get('prospector', 22)
            tk.Label(header, image=_ico, bg=ACCENT).pack(side=tk.LEFT, padx=(15, 4), pady=8)
        except Exception:
            pass

        tk.Label(
            header,
            text="Prospector - CVE Analysis",
            font=('Segoe UI', 12, 'bold'),
            fg='#ffffff',
            bg=ACCENT
        ).pack(side=tk.LEFT, padx=(0, 5), pady=10)
        
        tk.Label(
            header,
            text="Security vulnerability scanner for Jenkins builds",
            font=('Segoe UI', 9),
            fg=FG,
            bg=ACCENT
        ).pack(side=tk.LEFT, padx=5)
        
        # Main content with scrollbar
        content_frame = tk.Frame(self, bg=BG)
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # Input controls panel
        self._create_input_panel(content_frame)
        
        # Notebook for tabs
        self.notebook = ttk.Notebook(content_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Tab 1: Console Log
        self._create_console_tab()
        
        # Tab 2: Summary
        self._create_summary_tab()
        
        # Tab 3: Vulnerabilities
        self._create_vulnerabilities_tab()
        
        # Tab 4: Compliance Issues
        self._create_compliance_tab()
        
        # Tab 5: Repository
        self._create_repository_tab()
        
        # Tab 6: Docker Image
        self._create_docker_tab()
        
        # Status bar
        self.status_var = tk.StringVar(value="Ready - Click Refresh to load repositories")
        status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            bg=BG2,
            fg=ACCENT2,
            anchor=tk.W,
            padx=10,
            pady=5
        )
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
    
    def _create_input_panel(self, parent):
        """Create input controls panel"""
        input_frame = tk.Frame(parent, bg=BG2)
        input_frame.pack(fill=tk.X, padx=10, pady=10)
        
        # Use grid layout for precise alignment
        input_frame.columnconfigure(1, weight=1)  # Repository combo expands
        input_frame.columnconfigure(3, weight=1)  # Branch combo expands
        input_frame.columnconfigure(5, weight=1)  # Build combo expands
        
        # Row 0: Primary controls (Repository, Branch, Build #)
        row = 0
        
        # Repository
        tk.Label(
            input_frame, 
            text="Repository:", 
            font=('Segoe UI', 10, 'bold'), 
            fg=FG, 
            bg=BG2
        ).grid(row=row, column=0, sticky=tk.W, padx=(5, 5), pady=5)
        
        self.repo_var = tk.StringVar()
        self.repo_combo = ttk.Combobox(
            input_frame, 
            textvariable=self.repo_var, 
            width=35, 
            state="readonly",
            font=('Segoe UI', 10)
        )
        self.repo_combo.grid(row=row, column=1, sticky=tk.W, padx=2, pady=5)
        self.repo_combo.bind('<<ComboboxSelected>>', self.on_repo_selected)
        
        # Branch
        tk.Label(
            input_frame, 
            text="Branch:", 
            font=('Segoe UI', 10, 'bold'), 
            fg=FG, 
            bg=BG2
        ).grid(row=row, column=2, sticky=tk.W, padx=(15, 5), pady=5)
        
        self.branch_var = tk.StringVar()
        self.branch_combo = ttk.Combobox(
            input_frame, 
            textvariable=self.branch_var, 
            width=35, 
            state="readonly",
            font=('Segoe UI', 10)
        )
        self.branch_combo.grid(row=row, column=3, sticky=tk.W, padx=2, pady=5)
        self.branch_combo.bind('<<ComboboxSelected>>', self.on_branch_selected)
        
        # Build #
        tk.Label(
            input_frame, 
            text="Build #:", 
            font=('Segoe UI', 10, 'bold'), 
            fg=FG, 
            bg=BG2
        ).grid(row=row, column=4, sticky=tk.W, padx=(15, 5), pady=5)
        
        self.build_var = tk.StringVar()
        self.build_combo = ttk.Combobox(
            input_frame, 
            textvariable=self.build_var, 
            width=18, 
            state="readonly",
            font=('Segoe UI', 10)
        )
        self.build_combo.grid(row=row, column=5, sticky=tk.W, padx=2, pady=5)
        
        # Get Logs button
        tk.Button(
            input_frame,
            text="Get Logs",
            command=self.get_logs,
            bg=ACCENT,
            fg='white',
            font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT,
            padx=20,
            pady=6
        ).grid(row=row, column=6, sticky=tk.W, padx=15, pady=5)
        
        # Row 1: Diff controls (directly below row 0)
        row = 1
        
        # Diff Branch (directly below Branch)
        tk.Label(
            input_frame, 
            text="Diff Branch:", 
            font=('Segoe UI', 10, 'bold'), 
            fg=WARNING, 
            bg=BG2
        ).grid(row=row, column=2, sticky=tk.W, padx=(15, 5), pady=5)
        
        self.diff_branch_var = tk.StringVar()
        self.diff_branch_combo = ttk.Combobox(
            input_frame, 
            textvariable=self.diff_branch_var, 
            width=35, 
            state="readonly",
            font=('Segoe UI', 10)
        )
        self.diff_branch_combo.grid(row=row, column=3, sticky=tk.W, padx=2, pady=5)
        self.diff_branch_combo.bind('<<ComboboxSelected>>', self.on_diff_branch_selected)
        
        # Diff Build # (directly below Build #)
        tk.Label(
            input_frame, 
            text="Diff Build #:", 
            font=('Segoe UI', 10, 'bold'), 
            fg=WARNING, 
            bg=BG2
        ).grid(row=row, column=4, sticky=tk.W, padx=(15, 5), pady=5)
        
        self.diff_build_var = tk.StringVar()
        self.diff_build_combo = ttk.Combobox(
            input_frame, 
            textvariable=self.diff_build_var, 
            width=18, 
            state="readonly",
            font=('Segoe UI', 10)
        )
        self.diff_build_combo.grid(row=row, column=5, sticky=tk.W, padx=2, pady=5)
        
        # Diff CVEs button (directly below Get Logs)
        tk.Button(
            input_frame,
            text="Diff CVEs",
            command=self.diff_cves,
            bg=WARNING,
            fg='black',
            font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT,
            padx=20,
            pady=6
        ).grid(row=row, column=6, sticky=tk.W, padx=15, pady=5)
    
    def _create_console_tab(self):
        """Create Console Log tab"""
        self.log_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.log_frame, image=self._tab_icon_console, text=" Console Log", compound=tk.LEFT)
        
        # Build status banner
        status_banner = tk.Frame(self.log_frame, bg=BG3, height=40, relief=tk.RAISED, borderwidth=1)
        status_banner.pack(fill=tk.X, padx=5, pady=5)
        
        self.build_status_label = tk.Label(
            status_banner,
            text="Build Status: Unknown",
            font=('Segoe UI', 11, 'bold'),
            bg=BG3,
            fg=FG,
            pady=8
        )
        self.build_status_label.pack(fill=tk.BOTH, expand=True)
        
        # Console log text
        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            wrap=tk.WORD,
            font=('Consolas', 9),
            bg=BG3,
            fg=FG,
            insertbackground=FG
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 5))
        make_text_copyable(self.log_text)
    
    def _create_summary_tab(self):
        """Create Summary tab"""
        self.summary_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.summary_frame, image=self._tab_icon_summary, text=" Summary", compound=tk.LEFT)
        
        self.summary_text = scrolledtext.ScrolledText(
            self.summary_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg=BG3,
            fg=FG,
            insertbackground=FG
        )
        self.summary_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        make_text_copyable(self.summary_text)
    
    def _create_vulnerabilities_tab(self):
        """Create Vulnerabilities tab"""
        self.vuln_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.vuln_frame, image=self._tab_icon_vulns, text=" Vulnerabilities (0)", compound=tk.LEFT)
        
        # Vulnerabilities table
        table_frame = tk.Frame(self.vuln_frame, bg=BG)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Scrollbar
        vuln_scroll = ttk.Scrollbar(table_frame)
        vuln_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Treeview
        self.vuln_tree = ttk.Treeview(
            table_frame,
            yscrollcommand=vuln_scroll.set,
            selectmode='browse'
        )
        self.vuln_tree["columns"] = ("cve", "severity", "cvss", "package", "version", "description")
        self.vuln_tree.column("#0", width=0, stretch=tk.NO)
        self.vuln_tree.column("cve", width=130, anchor=tk.W)
        self.vuln_tree.column("severity", width=80, anchor=tk.CENTER)
        self.vuln_tree.column("cvss", width=60, anchor=tk.CENTER)
        self.vuln_tree.column("package", width=200, anchor=tk.W)
        self.vuln_tree.column("version", width=120, anchor=tk.W)
        self.vuln_tree.column("description", width=400, anchor=tk.W)
        
        self.vuln_tree.heading("cve", text="CVE ID")
        self.vuln_tree.heading("severity", text="Severity")
        self.vuln_tree.heading("cvss", text="CVSS")
        self.vuln_tree.heading("package", text="Package")
        self.vuln_tree.heading("version", text="Version")
        self.vuln_tree.heading("description", text="Description")
        
        self.vuln_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        add_treeview_menu(self.vuln_tree)
        vuln_scroll.config(command=self.vuln_tree.yview)
        
        # Configure tag colors for severity
        self.vuln_tree.tag_configure('critical', background='#5c1a1a', foreground='#ffcccc')
        self.vuln_tree.tag_configure('high', background='#5c2a1a', foreground='#ffddcc')
        self.vuln_tree.tag_configure('medium', background='#5c4a1a', foreground='#ffffcc')
        self.vuln_tree.tag_configure('low', background='#3a3a3a', foreground='#dddddd')
    
    def _create_compliance_tab(self):
        """Create Compliance Issues tab"""
        self.comp_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.comp_frame, image=self._tab_icon_compliance, text=" Compliance Issues (0)", compound=tk.LEFT)
        
        # Compliance table
        table_frame = tk.Frame(self.comp_frame, bg=BG)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Scrollbar
        comp_scroll = ttk.Scrollbar(table_frame)
        comp_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Treeview
        self.comp_tree = ttk.Treeview(
            table_frame,
            yscrollcommand=comp_scroll.set,
            selectmode='browse'
        )
        self.comp_tree["columns"] = ("severity", "description")
        self.comp_tree.column("#0", width=0, stretch=tk.NO)
        self.comp_tree.column("severity", width=120, anchor=tk.CENTER)
        self.comp_tree.column("description", width=900, anchor=tk.W)
        
        self.comp_tree.heading("severity", text="Severity")
        self.comp_tree.heading("description", text="Description")
        
        self.comp_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        add_treeview_menu(self.comp_tree)
        comp_scroll.config(command=self.comp_tree.yview)
        
        # Configure tag colors for severity
        self.comp_tree.tag_configure('high', background='#5c2a1a', foreground='#ffddcc')
        self.comp_tree.tag_configure('medium', background='#5c4a1a', foreground='#ffffcc')
        self.comp_tree.tag_configure('low', background='#3a3a3a', foreground='#dddddd')
    
    def _create_repository_tab(self):
        """Create Repository tab with file browser"""
        self.repo_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.repo_frame, image=self._tab_icon_repo, text=" Repository", compound=tk.LEFT)
        
        # Repository toolbar
        repo_toolbar = tk.Frame(self.repo_frame, bg=BG2)
        repo_toolbar.pack(fill=tk.X, padx=5, pady=5)
        
        tk.Button(
            repo_toolbar,
            text=" Clone/Checkout Repository",
            command=self.clone_repository,
            bg=ACCENT,
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT,
            padx=10,
            pady=5
        ).pack(side=tk.LEFT, padx=5)
        
        self.repo_status_var = tk.StringVar(value="Repository not cloned yet. Click Clone/Checkout to clone.")
        tk.Label(
            repo_toolbar,
            textvariable=self.repo_status_var,
            bg=BG2,
            fg=FG,
            font=('Segoe UI', 9)
        ).pack(side=tk.LEFT, padx=10)
        
        # Split pane: treeview on left, file viewer on right
        repo_paned = tk.PanedWindow(
            self.repo_frame,
            orient=tk.HORIZONTAL,
            sashrelief=tk.RAISED,
            sashwidth=5,
            bg=BG
        )
        repo_paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Left: File tree
        tree_frame = tk.Frame(repo_paned, bg=BG2)
        repo_paned.add(tree_frame, minsize=200)
        
        tk.Label(
            tree_frame,
            text="Repository Files",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2
        ).pack(anchor=tk.W, padx=5, pady=5)
        
        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.repo_tree = ttk.Treeview(
            tree_frame,
            yscrollcommand=tree_scroll_y.set,
            xscrollcommand=tree_scroll_x.set,
            selectmode='browse'
        )
        self.repo_tree.pack(fill=tk.BOTH, expand=True, padx=5)
        add_treeview_menu(self.repo_tree)
        tree_scroll_y.config(command=self.repo_tree.yview)
        tree_scroll_x.config(command=self.repo_tree.xview)
        
        self.repo_tree.bind('<<TreeviewSelect>>', self.on_repo_file_select)
        
        # Right: File viewer
        viewer_frame = tk.Frame(repo_paned, bg=BG2)
        repo_paned.add(viewer_frame, minsize=400)
        
        tk.Label(
            viewer_frame,
            text="File Contents",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG2
        ).pack(anchor=tk.W, padx=5, pady=5)
        
        self.file_viewer = scrolledtext.ScrolledText(
            viewer_frame,
            wrap=tk.NONE,
            font=('Consolas', 10),
            bg=BG3,
            fg=FG,
            insertbackground=FG
        )
        self.file_viewer.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        make_text_copyable(self.file_viewer)
        
        # Store git info for cloning
        self.git_repo_url = None
        self.git_branch = None
        self.git_commit = None
        self.repo_path = None
    
    def _create_docker_tab(self):
        """Create Docker Image tab with interactive container terminal"""
        self.docker_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.docker_frame, image=self._tab_icon_docker, text=" Docker Image", compound=tk.LEFT)
        
        # Toolbar at the top
        toolbar_frame = tk.Frame(self.docker_frame, bg=BG2)
        toolbar_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.docker_run_btn = tk.Button(
            toolbar_frame,
            text="Run Container (Bash)",
            command=self.run_docker_container,
            bg=ACCENT,
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT,
            padx=10,
            pady=5
        )
        self.docker_run_btn.pack(side=tk.LEFT, padx=5)
        
        self.docker_stop_btn = tk.Button(
            toolbar_frame,
            text="Stop Container",
            command=self.stop_docker_container,
            state=tk.DISABLED,
            bg=ERROR,
            fg='white',
            font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT,
            padx=10,
            pady=5
        )
        self.docker_stop_btn.pack(side=tk.LEFT, padx=5)
        
        # Status label
        self.docker_status_var = tk.StringVar(value="No container running")
        tk.Label(
            toolbar_frame,
            textvariable=self.docker_status_var,
            bg=BG2,
            fg=FG,
            font=('Segoe UI', 9)
        ).pack(side=tk.LEFT, padx=10)
        
        # Terminal area
        terminal_frame = tk.Frame(self.docker_frame, bg=BG)
        terminal_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        tk.Label(
            terminal_frame,
            text="Container Terminal (Output)",
            font=('Segoe UI', 10, 'bold'),
            fg=ACCENT2,
            bg=BG
        ).pack(anchor=tk.W)
        
        self.docker_terminal = scrolledtext.ScrolledText(
            terminal_frame,
            wrap=tk.CHAR,
            height=25,
            font=('Consolas', 10),
            bg='#0c0c0c',
            fg='#00ff00',
            insertbackground='#00ff00',
            state=tk.DISABLED
        )
        self.docker_terminal.pack(fill=tk.BOTH, expand=True, pady=5)
        make_text_copyable(self.docker_terminal)
        self.docker_terminal.config(state=tk.NORMAL)
        self.docker_terminal.insert('1.0', "Click 'Run Container' to start an interactive bash session with the Docker image.\n")
        self.docker_terminal.config(state=tk.DISABLED)
        
        # Command input area
        input_container = tk.Frame(terminal_frame, bg=BG)
        input_container.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(
            input_container,
            text="Command:",
            font=('Consolas', 10),
            bg=BG,
            fg=FG
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        self.docker_input = tk.Entry(
            input_container,
            font=('Consolas', 10),
            bg=BG3,
            fg=FG,
            insertbackground=FG
        )
        self.docker_input.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.docker_input.bind("<Return>", self.on_docker_input_enter)
        
        tk.Button(
            input_container,
            text="Send",
            command=self.send_docker_command,
            bg=ACCENT,
            fg='white',
            relief=tk.FLAT,
            padx=10,
            pady=3
        ).pack(side=tk.LEFT, padx=(5, 0))
        
        # Docker state
        self.docker_image_url = None
        self.docker_process = None
        self.docker_shell_id = None
    
    # Repository/Branch/Build Loading Methods
    def load_repositories(self):
        """Load repositories from Jenkins"""
        self.status_var.set("Loading repositories...")
        thread = threading.Thread(target=self._load_repositories_thread, daemon=True)
        thread.start()
    
    def _load_repositories_thread(self):
        """Background thread to load repositories"""
        try:
            repos = get_all_repositories(self.jenkins_url, self.jenkins_user, self.jenkins_token)
            if repos:
                self.after(0, lambda: self._update_repo_combo(repos))
            else:
                self.after(0, lambda: self.status_var.set("❌ No repositories found"))
        except JenkinsConfigError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins config missing - check API Keys+"))
        except JenkinsAuthError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins auth failed - update JENKINS_USER / JENKINS_API_TOKEN"))
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"❌ Error loading repos: {str(e)}"))
    
    def _update_repo_combo(self, repos):
        """Update repository combobox"""
        self.repo_combo['values'] = repos
        self.status_var.set(f"✓ Loaded {len(repos)} repositories")
    
    def on_repo_selected(self, event):
        """Handle repository selection"""
        self.branch_var.set('')
        self.build_var.set('')
        self.diff_branch_var.set('')
        self.diff_build_var.set('')
        self.branch_combo['values'] = []
        self.build_combo['values'] = []
        self.diff_branch_combo['values'] = []
        self.diff_build_combo['values'] = []
        self.load_branches()
    
    def load_branches(self):
        """Load branches for selected repository"""
        repo = self.repo_var.get()
        if not repo:
            return
        
        self.status_var.set(f"Loading branches for {repo}...")
        thread = threading.Thread(target=self._load_branches_thread, args=(repo,), daemon=True)
        thread.start()
    
    def _load_branches_thread(self, repo):
        """Background thread to load branches"""
        try:
            branches = get_repository_branches(self.jenkins_url, self.jenkins_user, self.jenkins_token, repo)
            if branches:
                self.after(0, lambda: self._update_branch_combo(branches))
            else:
                self.after(0, lambda: self.status_var.set(f"❌ No branches found for {repo}"))
        except JenkinsConfigError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins config missing - check API Keys+"))
        except JenkinsAuthError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins auth failed - update JENKINS_USER / JENKINS_API_TOKEN"))
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"❌ Error loading branches: {str(e)}"))
    
    def _update_branch_combo(self, branches):
        """Update branch comboboxes with custom sorting"""
        # Custom sort: release/ branches first (descending), then others (descending)
        release_branches = []
        other_branches = []
        
        for branch in branches:
            if branch.startswith('release/'):
                release_branches.append(branch)
            else:
                other_branches.append(branch)
        
        # Sort both groups in descending order (reverse alphabetical)
        release_branches.sort(reverse=True)
        other_branches.sort(reverse=True)
        
        # Combine: release branches first, then others
        sorted_branches = release_branches + other_branches
        
        self.branch_combo['values'] = sorted_branches
        self.diff_branch_combo['values'] = sorted_branches
        self.status_var.set(f"✓ Loaded {len(branches)} branches")
    
    def on_branch_selected(self, event):
        """Handle branch selection"""
        self.build_var.set('')
        self.build_combo['values'] = []
        self.load_builds()
    
    def load_builds(self):
        """Load build numbers for selected branch"""
        repo = self.repo_var.get()
        branch = self.branch_var.get()
        if not repo or not branch:
            return
        
        self.status_var.set(f"Loading builds for {branch}...")
        thread = threading.Thread(target=self._load_builds_thread, args=(repo, branch), daemon=True)
        thread.start()
    
    def _load_builds_thread(self, repo, branch):
        """Background thread to load builds"""
        try:
            builds = get_branch_build_numbers(self.jenkins_url, self.jenkins_user, self.jenkins_token, repo, branch)
            if builds:
                self.after(0, lambda: self._update_build_combo(builds))
            else:
                self.after(0, lambda: self.status_var.set(f"❌ No builds found for {branch}"))
        except JenkinsConfigError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins config missing - check API Keys+"))
        except JenkinsAuthError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins auth failed - update JENKINS_USER / JENKINS_API_TOKEN"))
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"❌ Error loading builds: {str(e)}"))
    
    def _update_build_combo(self, builds):
        """Update build combobox"""
        # Extract just the build numbers from the dict list
        build_numbers = [str(b.get('number', b)) for b in builds] if builds and isinstance(builds[0], dict) else builds
        self.build_combo['values'] = build_numbers
        self.status_var.set(f"✓ Loaded {len(build_numbers)} builds")
    
    def on_diff_branch_selected(self, event):
        """Handle diff branch selection"""
        self.diff_build_var.set('')
        self.diff_build_combo['values'] = []
        self.load_diff_builds()
    
    def load_diff_builds(self):
        """Load build numbers for diff branch"""
        repo = self.repo_var.get()
        branch = self.diff_branch_var.get()
        if not repo or not branch:
            return
        
        thread = threading.Thread(target=self._load_diff_builds_thread, args=(repo, branch), daemon=True)
        thread.start()
    
    def _load_diff_builds_thread(self, repo, branch):
        """Background thread to load diff builds"""
        try:
            builds = get_branch_build_numbers(self.jenkins_url, self.jenkins_user, self.jenkins_token, repo, branch)
            if builds:
                self.after(0, lambda: self._update_diff_build_combo(builds))
        except JenkinsConfigError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins config missing - check API Keys+"))
        except JenkinsAuthError:
            self.after(0, lambda: self.status_var.set("❌ Jenkins auth failed - update JENKINS_USER / JENKINS_API_TOKEN"))
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"❌ Error loading diff builds: {str(e)}"))
    
    def _update_diff_build_combo(self, builds):
        """Update diff build combobox"""
        # Extract just the build numbers from the dict list
        build_numbers = [str(b.get('number', b)) for b in builds] if builds and isinstance(builds[0], dict) else builds
        self.diff_build_combo['values'] = build_numbers
    
    def get_logs(self):
        """Get logs for selected build"""
        repo = self.repo_var.get()
        branch = self.branch_var.get()
        build = self.build_var.get()
        
        if not repo or not branch:
            messagebox.showwarning("Missing Input", "Please select repository and branch")
            return
        
        self.status_var.set("Fetching build logs...")
        thread = threading.Thread(target=self._get_logs_thread, args=(repo, branch, build), daemon=True)
        thread.start()
    
    def _get_logs_thread(self, repo, branch, build):
        """Background thread to fetch logs"""
        try:
            from auger.tools.jenkins import build_job_name
            
            # Build job name
            job_name = build_job_name(repo, branch)
            
            # Use lastBuild if no build number specified
            if not build:
                build = "lastBuild"
            
            # Fetch build log from Jenkins
            import requests
            api_url = f"{self.jenkins_url}/job/{job_name}/{build}/consoleText"
            response = requests.get(api_url, auth=(self.jenkins_user, self.jenkins_token), timeout=60)
            
            if response.status_code == 200:
                log_content = response.text
                
                # Parse vulnerabilities and compliance from the log
                vulnerabilities = parse_prisma_vulnerabilities(log_content)
                compliance_issues = parse_prisma_compliance(log_content)
                
                # Extract git info and docker image from log
                git_info = self._extract_git_info(log_content)
                docker_image = self._extract_docker_image(log_content)
                
                # Build data dict
                data = {
                    'console_log': log_content,
                    'vulnerabilities': vulnerabilities,
                    'compliance_issues': compliance_issues,
                    'git_info': git_info,
                    'docker_image': docker_image
                }
                
                self.after(0, lambda: self._display_logs(data))
            else:
                error = f"HTTP {response.status_code}: {response.reason}"
                self.after(0, lambda: self.status_var.set(f"❌ Error: {error}"))
                self.after(0, lambda: messagebox.showerror("Jenkins Error", f"Failed to fetch build log:\n{error}"))
                
        except Exception as e:
            import traceback
            error_msg = f"Error fetching logs: {str(e)}\n{traceback.format_exc()}"
            self.after(0, lambda: self.status_var.set(f"❌ Error: {str(e)}"))
            self.after(0, lambda: messagebox.showerror("Error", error_msg))
    
    def _extract_git_info(self, log_content):
        """Extract git information from build log"""
        git_info = {}
        
        lines = log_content.split('\n')
        
        repo_url = None
        branch = None
        commit = None
        
        for line in lines:
            # Look for git fetch command with repo URL
            # Example: git fetch --no-tags --progress -- https://github.helix.gsa.gov/ASSIST/core-assist-api.git +refs/heads/release/ASSIST_4.4.4.0_DME:refs/remotes/origin/release/ASSIST_4.4.4.0_DME
            if 'git fetch' in line and 'github.helix.gsa.gov' in line:
                match = re.search(r'--\s+(https://[^\s]+)\s+\+refs/heads/([^:]+):', line)
                if match:
                    repo_url = match.group(1)
                    branch = match.group(2)
            
            # Look for git checkout command with commit hash
            # Example: git checkout -f abc123def456
            if 'git checkout -f' in line:
                match = re.search(r'git checkout -f\s+([a-f0-9]+)', line)
                if match:
                    commit = match.group(1)
        
        if repo_url:
            git_info['url'] = repo_url  # Keep HTTPS - token auth used at clone time
            git_info['branch'] = branch
            git_info['commit'] = commit
            
            # Extract repo name for display
            repo_name = repo_url.split('/')[-1].replace('.git', '')
            git_info['repo'] = repo_name
        
        return git_info
    
    def _get_authenticated_git_url(self, https_url):
        """Inject GHE token into HTTPS URL for authenticated clone."""
        token = os.environ.get('GHE_TOKEN', '')
        username = os.environ.get('GHE_USERNAME', 'git')
        if token and https_url.startswith('https://'):
            # https://github.helix.gsa.gov/... -> https://token@github.helix.gsa.gov/...
            return https_url.replace('https://', f'https://{username}:{token}@', 1)
        return https_url

    def _git_env(self):
        """Return env dict for git subprocess - fixes 'no user exists for uid' error."""
        env = os.environ.copy()
        env['GIT_AUTHOR_NAME'] = env.get('GHE_USERNAME', 'auger')
        env['GIT_COMMITTER_NAME'] = env.get('GHE_USERNAME', 'auger')
        env['GIT_AUTHOR_EMAIL'] = f"{env.get('GHE_USERNAME', 'auger')}@gsa.gov"
        env['GIT_COMMITTER_EMAIL'] = f"{env.get('GHE_USERNAME', 'auger')}@gsa.gov"
        env['GIT_TERMINAL_PROMPT'] = '0'
        return env
    
    def _extract_docker_image(self, log_content):
        """Extract Docker image from build log"""
        # Look for docker image patterns
        patterns = [
            r'Image:\s*(\S+)',
            r'Docker\s+[Ii]mage:\s*(\S+)',
            r'artifactory[\w\-\.]+/[\w\-/]+:[\w\-\.]+',
            r'Building\s+image:\s*(\S+)',
            r'Pushing\s+image:\s*(\S+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, log_content, re.IGNORECASE)
            if match:
                # Try to get group 1 if it exists, otherwise group 0
                try:
                    return match.group(1)
                except:
                    return match.group(0)
        
        return None
    
    def clone_repository(self):
        """Clone and checkout the git repository"""
        if not self.git_repo_url:
            messagebox.showerror("Error", "No git repository information found.\n\nPlease fetch build logs first to extract git URL.")
            return
        
        # Show what will be cloned
        repo_name = self.git_repo_url.split('/')[-1].replace('.git', '') if self.git_repo_url else "Unknown"
        branch_info = f"\nBranch: {self.git_branch}" if self.git_branch else ""
        commit_info = f"\nCommit: {self.git_commit[:8]}" if self.git_commit else ""
        
        # Run in background thread
        thread = threading.Thread(target=self._clone_repository_thread, daemon=True)
        thread.start()

    def _ensure_writable_prisma_repos_dir(self):
        """Return a writable ~/.auger/prisma-repos directory, migrating stale copies if needed."""
        auger_dir = Path.home() / '.auger'
        auger_dir.mkdir(parents=True, exist_ok=True)
        repos_dir = auger_dir / 'prisma-repos'

        if not repos_dir.exists():
            repos_dir.mkdir(parents=True, exist_ok=True)
            return repos_dir

        if repos_dir.is_dir() and os.access(repos_dir, os.W_OK | os.X_OK):
            return repos_dir

        backup_dir = auger_dir / f"prisma-repos-legacy-{datetime.now():%Y%m%d-%H%M%S}"
        try:
            repos_dir.rename(backup_dir)
            repos_dir.mkdir(parents=True, exist_ok=True)
            self.after(
                0,
                lambda: self.repo_status_var.set(
                    f"Moved unwritable prisma-repos aside to {backup_dir.name}"
                ),
            )
            return repos_dir
        except Exception as exc:
            raise PermissionError(
                f"{repos_dir} exists but is not writable by the current user. "
                f"Tried to move it aside to {backup_dir.name} and recreate it, but that failed: {exc}"
            ) from exc
    
    def _clone_repository_thread(self):
        """Thread function to clone repository"""
        try:
            self.after(0, lambda: self.repo_status_var.set("Cloning repository..."))
            
            repos_dir = self._ensure_writable_prisma_repos_dir()
            
            # Extract repo name
            repo_name = self.git_repo_url.split('/')[-1].replace('.git', '')
            self.repo_path = repos_dir / repo_name
            
            # Clone or update repo
            if self.repo_path.exists():
                # Repository already exists, just fetch
                self.after(0, lambda: self.repo_status_var.set("Fetching updates..."))
                
                # Fetch all branches
                result = subprocess.run(
                    ['git', '-C', str(self.repo_path), 'fetch', 'origin'],
                    capture_output=True, text=True, env=self._git_env()
                )
                
                if result.returncode != 0:
                    self.after(0, lambda err=result.stderr: messagebox.showwarning("Fetch Warning", f"Git fetch failed: {err}\nContinuing with existing repo..."))
            else:
                # Clone the repository
                self.after(0, lambda: self.repo_status_var.set(f"Cloning {repo_name}..."))
                auth_url = self._get_authenticated_git_url(self.git_repo_url)
                result = subprocess.run(
                    ['git', 'clone', auth_url, str(self.repo_path)],
                    capture_output=True, text=True, env=self._git_env()
                )
                
                if result.returncode != 0:
                    self.after(0, lambda err=result.stderr: messagebox.showerror("Error", f"Git clone failed: {err}"))
                    self.after(0, lambda: self.repo_status_var.set("Clone failed"))
                    return
            
            # Checkout specific commit or branch
            if self.git_commit:
                self.after(0, lambda: self.repo_status_var.set(f"Checking out commit {self.git_commit[:8]}..."))
                
                # First, ensure we have the branch
                if self.git_branch:
                    subprocess.run(
                        ['git', '-C', str(self.repo_path), 'checkout', '-B', self.git_branch, f'origin/{self.git_branch}'],
                        capture_output=True,
                        text=True
                    )
                
                # Now checkout the specific commit
                result = subprocess.run(
                    ['git', '-C', str(self.repo_path), 'checkout', self.git_commit],
                    capture_output=True,
                    text=True
                )
            elif self.git_branch:
                self.after(0, lambda: self.repo_status_var.set(f"Checking out branch {self.git_branch}..."))
                result = subprocess.run(
                    ['git', '-C', str(self.repo_path), 'checkout', self.git_branch],
                    capture_output=True,
                    text=True
                )
            else:
                result = subprocess.CompletedProcess([], 0)  # Success if no checkout needed
            
            if result.returncode != 0:
                self.after(0, lambda err=result.stderr: messagebox.showerror("Error", f"Git checkout failed: {err}"))
                self.after(0, lambda: self.repo_status_var.set("Checkout failed"))
                return
            
            # Populate tree view
            self.after(0, lambda: self._populate_repo_tree())
            self.after(0, lambda: self.repo_status_var.set(f"✓ Repository ready: {repo_name}"))
            
        except Exception as e:
            import traceback
            error_msg = f"Failed to clone repository: {str(e)}\n{traceback.format_exc()}"
            self.after(0, lambda: messagebox.showerror("Error", error_msg))
            self.after(0, lambda: self.repo_status_var.set("Error cloning repository"))
    
    def _populate_repo_tree(self):
        """Populate the tree view with repository files"""
        # Clear existing items
        for item in self.repo_tree.get_children():
            self.repo_tree.delete(item)
        
        if not self.repo_path or not self.repo_path.exists():
            return
        
        # Insert root
        root_id = self.repo_tree.insert(
            '', 'end',
            text=f"📁 {self.repo_path.name}",
            open=True,
            values=(str(self.repo_path),),
            tags=('directory',)
        )
        
        # Recursively add files and directories
        self._add_tree_nodes(root_id, self.repo_path)
    
    def _add_tree_nodes(self, parent, path):
        """Recursively add nodes to tree view"""
        try:
            items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
            
            for item in items:
                # Skip .git directory
                if item.name == '.git':
                    continue
                
                if item.is_dir():
                    # Add directory
                    node = self.repo_tree.insert(
                        parent, 'end',
                        text=f"📁 {item.name}",
                        values=(str(item),),
                        tags=('directory',)
                    )
                    # Recursively add subdirectories
                    self._add_tree_nodes(node, item)
                else:
                    # Add file
                    self.repo_tree.insert(
                        parent, 'end',
                        text=f"📄 {item.name}",
                        values=(str(item),),
                        tags=('file',)
                    )
                    
        except PermissionError:
            pass
        except Exception as e:
            print(f"Error adding tree nodes for {path}: {e}")
    
    def on_repo_file_select(self, event):
        """Handle file selection in repo tree"""
        selection = self.repo_tree.selection()
        if not selection:
            return
        
        item = selection[0]
        
        # Get the full path stored in the item values
        values = self.repo_tree.item(item, 'values')
        if not values:
            return
        
        file_path = Path(values[0])
        
        # Check if it's a file
        if file_path.is_file():
            self._display_file_contents(file_path)
    
    def _display_file_contents(self, file_path):
        """Display file contents in the viewer"""
        try:
            # Try to read as text
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                contents = f.read()
            
            self.file_viewer.delete('1.0', tk.END)
            self.file_viewer.insert('1.0', contents)
            
        except Exception as e:
            self.file_viewer.delete('1.0', tk.END)
            self.file_viewer.insert('1.0', f"Error reading file: {str(e)}")
    
    def _docker_login(self):
        """Login to Artifactory Docker registry using credentials from .env"""
        registry = os.environ.get('ARTIFACTORY_URL', 'https://artifactory.helix.gsa.gov').replace('https://', '').replace('http://', '')
        username = os.environ.get('ARTIFACTORY_USERNAME', '')
        password = (os.environ.get('ARTIFACTORY_API_KEY') or
                    os.environ.get('ARTIFACTORY_IDENTITY_TOKEN') or
                    os.environ.get('ARTIFACTORY_PASSWORD', ''))
        if not username or not password:
            return False, "Artifactory credentials not set in API Keys+ widget"
        try:
            # Use ~/.auger/.docker as DOCKER_CONFIG - always writable in container
            docker_cfg = Path.home() / '.auger' / '.docker'
            docker_cfg.mkdir(parents=True, exist_ok=True)
            env = os.environ.copy()
            env['DOCKER_CONFIG'] = str(docker_cfg)
            result = subprocess.run(
                ['docker', 'login', registry, '-u', username, '--password-stdin'],
                input=password.encode(), capture_output=True, timeout=30, env=env
            )
            if result.returncode == 0:
                return True, f"Logged in to {registry}"
            else:
                return False, result.stderr.decode().strip()
        except Exception as e:
            return False, str(e)

    def run_docker_container(self):
        """Start a Docker container with interactive bash session"""
        if not self.docker_image_url:
            messagebox.showerror("Error", "No Docker image URL available. Please fetch logs first.")
            return
        
        if self.docker_shell_id:
            messagebox.showwarning("Warning", "A container is already running. Stop it first.")
            return
        
        # Update status
        self.docker_status_var.set("Starting container...")
        self.docker_run_btn.config(state=tk.DISABLED)
        self.docker_terminal.config(state=tk.NORMAL)
        self.docker_terminal.delete('1.0', tk.END)
        self.docker_terminal.config(state=tk.DISABLED)
        
        # Run in a separate thread to avoid blocking UI
        thread = threading.Thread(target=self._run_docker_container_thread, daemon=True)
        thread.start()
    
    def _run_docker_container_thread(self):
        """Thread function to run docker container"""
        try:
            import uuid
            
            self.docker_shell_id = f"docker_{uuid.uuid4().hex[:8]}"
            
            # Login to Artifactory before pulling image
            self.after(0, lambda: self._append_to_terminal("🔑 Logging in to Artifactory...\n"))
            ok, msg = self._docker_login()
            self.after(0, lambda m=msg: self._append_to_terminal(f"   {m}\n\n"))
            if not ok:
                self.after(0, lambda: self._append_to_terminal("⚠️  Login failed - pull may fail if image is not cached locally\n\n"))

            # Start docker run command without -t flag (no TTY allocation)
            # Use -i for interactive stdin
            cmd = ["docker", "run", "-i", "--rm", "--entrypoint", "/bin/bash", self.docker_image_url]

            cmd_str = " ".join(cmd)
            self.after(0, lambda: self._append_to_terminal(f"$ {cmd_str}\n"))
            self.after(0, lambda: self._append_to_terminal("Pulling image if needed...\n\n"))
            
            # Execute docker command with unbuffered output
            env = os.environ.copy()
            env['DOCKER_BUILDKIT'] = '0'  # Disable BuildKit fancy output
            env['DOCKER_CONFIG'] = str(Path.home() / '.auger' / '.docker')
            
            result = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # Use binary mode for non-blocking I/O
                bufsize=0,  # Unbuffered
                env=env
            )
            
            self.docker_process = result
            
            # Set stdout and stderr to non-blocking mode
            os.set_blocking(result.stdout.fileno(), False)
            os.set_blocking(result.stderr.fileno(), False)
            
            # Update UI
            self.after(0, lambda: self.docker_status_var.set("Container running"))
            self.after(0, lambda: self.docker_stop_btn.config(state=tk.NORMAL))
            
            # Start reading output in separate thread
            reader_thread = threading.Thread(target=self._read_docker_output_thread, daemon=True)
            reader_thread.start()
            
            # Also start stderr reader thread
            stderr_thread = threading.Thread(target=self._read_docker_stderr_thread, daemon=True)
            stderr_thread.start()
            
            # Give it a moment for container to start, then send initial command
            import time
            time.sleep(1)
            
            # Send a command to get bash to output something
            try:
                self.docker_process.stdin.write(b"echo 'Container ready. Type commands below:'\n")
                self.docker_process.stdin.write(b"export PS1='root@container:# '\n")
                self.docker_process.stdin.flush()
            except:
                pass
            
        except Exception as e:
            import traceback
            error_msg = f"\nError: {str(e)}\n{traceback.format_exc()}\n"
            self.after(0, lambda: self._append_to_terminal(error_msg))
            self.after(0, lambda: self.docker_status_var.set("Error starting container"))
            self.after(0, lambda: self.docker_run_btn.config(state=tk.NORMAL))
            self.docker_shell_id = None
    
    def _read_docker_output_thread(self):
        """Thread to continuously read stdout from docker container"""
        try:
            import time
            while self.docker_process and self.docker_process.poll() is None:
                try:
                    # Read available data (non-blocking)
                    data = self.docker_process.stdout.read(4096)
                    if data:
                        # Decode bytes to string
                        text = data.decode('utf-8', errors='replace')
                        self.after(0, lambda t=text: self._append_to_terminal(t))
                except BlockingIOError:
                    # No data available yet, sleep briefly
                    time.sleep(0.1)
                    continue
            
            # Read any remaining output
            try:
                remaining = self.docker_process.stdout.read()
                if remaining:
                    text = remaining.decode('utf-8', errors='replace')
                    self.after(0, lambda t=text: self._append_to_terminal(t))
            except:
                pass
                
        except Exception as e:
            self.after(0, lambda e=e: self._append_to_terminal(f"\nError reading stdout: {str(e)}\n"))
        
        # Process ended
        self.after(0, lambda: self._append_to_terminal("\n\n[Container exited]\n"))
        self.after(0, lambda: self.docker_status_var.set("Container stopped"))
        self.after(0, lambda: self.docker_run_btn.config(state=tk.NORMAL))
        self.after(0, lambda: self.docker_stop_btn.config(state=tk.DISABLED))
        self.docker_shell_id = None
        self.docker_process = None
    
    def _read_docker_stderr_thread(self):
        """Thread to continuously read stderr from docker container"""
        try:
            import time
            while self.docker_process and self.docker_process.poll() is None:
                try:
                    # Read available data (non-blocking)
                    data = self.docker_process.stderr.read(4096)
                    if data:
                        # Decode bytes to string
                        text = data.decode('utf-8', errors='replace')
                        self.after(0, lambda t=text: self._append_to_terminal(t))
                except BlockingIOError:
                    # No data available yet, sleep briefly
                    time.sleep(0.1)
                    continue
            
            # Read any remaining stderr
            try:
                remaining = self.docker_process.stderr.read()
                if remaining:
                    text = remaining.decode('utf-8', errors='replace')
                    self.after(0, lambda t=text: self._append_to_terminal(t))
            except:
                pass
                
        except Exception as e:
            self.after(0, lambda e=e: self._append_to_terminal(f"\nError reading stderr: {str(e)}\n"))
    
    def _append_to_terminal(self, text):
        """Append text to terminal and auto-scroll"""
        self.docker_terminal.config(state=tk.NORMAL)
        self.docker_terminal.insert(tk.END, text)
        self.docker_terminal.see(tk.END)  # Auto-scroll to bottom
        self.docker_terminal.config(state=tk.DISABLED)
    
    def stop_docker_container(self):
        """Stop the running Docker container"""
        if self.docker_process:
            try:
                self.docker_process.terminate()
                self.docker_process.wait(timeout=5)
            except:
                self.docker_process.kill()
            
            self.docker_process = None
            self.docker_shell_id = None
            self.docker_status_var.set("Container stopped")
            self.docker_run_btn.config(state=tk.NORMAL)
            self.docker_stop_btn.config(state=tk.DISABLED)
            self._append_to_terminal("\n\n[Container stopped by user]\n")
    
    def on_docker_input_enter(self, event):
        """Handle Enter key in docker input box"""
        self.send_docker_command()
        return "break"  # Prevent default behavior
    
    def send_docker_command(self):
        """Send command from input box to docker container"""
        if not self.docker_process:
            return
        
        command = self.docker_input.get().strip()
        if not command:
            return
        
        # Echo command to terminal
        self._append_to_terminal(f"$ {command}\n")
        
        # Send to docker container (encode to bytes)
        try:
            cmd = (command + "\n").encode('utf-8')
            self.docker_process.stdin.write(cmd)
            self.docker_process.stdin.flush()
        except Exception as e:
            self._append_to_terminal(f"Error sending command: {str(e)}\n")
        
        # Clear input box
        self.docker_input.delete(0, tk.END)
    
    def _display_logs(self, data):
        """Display fetched logs"""
        # Extract data
        self.console_log_data = data.get('console_log', '')
        self.vulnerabilities_data = data.get('vulnerabilities', [])
        self.compliance_data = data.get('compliance_issues', [])
        self.current_git_info = data.get('git_info', {})
        self.current_docker_image = data.get('docker_image', '')
        
        # Update Console Log
        self.log_text.delete('1.0', tk.END)
        self.log_text.insert('1.0', self.console_log_data)
        
        # Update build status
        if 'SUCCESS' in self.console_log_data:
            self.build_status_label.config(text="Build Status: SUCCESS", bg='#2a4a2a', fg='#00ff00')
        elif 'FAILURE' in self.console_log_data:
            self.build_status_label.config(text="Build Status: FAILURE", bg='#4a2a2a', fg='#ff0000')
        else:
            self.build_status_label.config(text="Build Status: Unknown", bg=BG3, fg=FG)
        
        # Update Vulnerabilities
        self._display_vulnerabilities()
        
        # Update Compliance
        self._display_compliance()
        
        # Update Summary
        self._display_summary()
        
        # Update Repository tab
        self._display_repository_info()
        
        # Update Docker tab
        self._display_docker_info()
        
        vuln_count = len(self.vulnerabilities_data)
        comp_count = len(self.compliance_data)
        self.status_var.set(f"✓ Loaded: {vuln_count} vulnerabilities, {comp_count} compliance issues")
    
    def _display_vulnerabilities(self):
        """Display vulnerabilities in tree view"""
        # Clear existing
        for item in self.vuln_tree.get_children():
            self.vuln_tree.delete(item)
        
        # Add vulnerabilities
        for vuln in self.vulnerabilities_data:
            cve = vuln.get('cve', 'N/A')
            severity = vuln.get('severity', 'Unknown').upper()
            cvss = vuln.get('cvss', 'N/A')
            package = vuln.get('package', 'N/A')
            version = vuln.get('version', 'N/A')
            desc = vuln.get('description', 'N/A')[:80]
            
            tag = severity.lower() if severity.lower() in ['critical', 'high', 'medium', 'low'] else 'low'
            
            self.vuln_tree.insert('', tk.END, values=(cve, severity, cvss, package, version, desc), tags=(tag,))
        
        # Update tab title
        count = len(self.vulnerabilities_data)
        for idx, tab_id in enumerate(self.notebook.tabs()):
            if idx == 2:  # Vulnerabilities tab
                self.notebook.tab(tab_id, text=f"Vulnerabilities ({count})")
    
    def _display_compliance(self):
        """Display compliance issues in tree view"""
        # Clear existing
        for item in self.comp_tree.get_children():
            self.comp_tree.delete(item)
        
        # Add compliance issues
        for issue in self.compliance_data:
            severity = issue.get('severity', 'Unknown').upper()
            description = issue.get('description', 'N/A')
            
            tag = severity.lower() if severity.lower() in ['high', 'medium', 'low'] else 'low'
            
            self.comp_tree.insert('', tk.END, values=(severity, description), tags=(tag,))
        
        # Update tab title
        count = len(self.compliance_data)
        for idx, tab_id in enumerate(self.notebook.tabs()):
            if idx == 3:  # Compliance Issues tab
                self.notebook.tab(tab_id, text=f"Compliance Issues ({count})")
    
    def _display_repository_info(self):
        """Display repository information and extract git URL for cloning"""
        if self.current_git_info:
            # Extract git URL for cloning
            self.git_repo_url = self.current_git_info.get('url')
            self.git_branch = self.current_git_info.get('branch')
            self.git_commit = self.current_git_info.get('commit')
            
            # Update status message
            if self.git_repo_url:
                self.repo_status_var.set(f"Ready to clone. Click 🔄 to checkout code.")
            else:
                self.repo_status_var.set("Git URL not found in logs. Cannot clone repository.")
        else:
            self.repo_status_var.set("Repository not cloned yet. Load build logs first.")
    
    def _display_docker_info(self):
        """Extract and display Docker image information from Artifactory"""
        # Extract Artifactory URL from log
        docker_image = self._extract_artifactory_url(self.console_log_data)
        
        if docker_image:
            self.docker_image_url = docker_image
            
            # Update tab title with image name
            if '/' in docker_image:
                image_name = docker_image.split('/')[-1]
                for idx, tab_id in enumerate(self.notebook.tabs()):
                    if idx == 5:  # Docker Image tab
                        self.notebook.tab(tab_id, text=f" {image_name}", image=self._tab_icon_docker, compound=tk.LEFT)
            
            # Update terminal with image info
            self.docker_terminal.config(state=tk.NORMAL)
            self.docker_terminal.delete('1.0', tk.END)
            
            display_text = "Docker Image Information\n"
            display_text += "=" * 80 + "\n\n"
            display_text += f"Image URL: {docker_image}\n\n"
            
            # Parse components
            if '/' in docker_image and ':' in docker_image:
                registry_and_repo = docker_image.split(':')[0]
                tag = docker_image.split(':')[1] if ':' in docker_image else 'latest'
                
                display_text += f"Repository: {registry_and_repo}\n"
                display_text += f"Tag: {tag}\n\n"
            
            display_text += "\nClick 'Run Container' button to start an interactive bash session.\n"
            display_text += f"This will execute: docker run -i --rm --entrypoint /bin/bash {docker_image}\n"
            
            self.docker_terminal.insert('1.0', display_text)
            self.docker_terminal.config(state=tk.DISABLED)
        else:
            # No Docker image found
            for idx, tab_id in enumerate(self.notebook.tabs()):
                if idx == 5:  # Docker Image tab
                    self.notebook.tab(tab_id, text=" Docker Image", image=self._tab_icon_docker, compound=tk.LEFT)
            
            self.docker_terminal.config(state=tk.NORMAL)
            self.docker_terminal.delete('1.0', tk.END)
            self.docker_terminal.insert('1.0', "No Docker image URL found in build log.\n\nThis may be a build that didn't produce a Docker image.")
            self.docker_terminal.config(state=tk.DISABLED)
    
    def _extract_artifactory_url(self, log_content):
        """Extract Artifactory docker image URL from log content"""
        # Look for docker push command with artifactory URL
        # Pattern: docker push artifactory.helix.gsa.gov/...
        # We want the build-specific tag (not -latest), so we collect all and prefer non-latest
        lines = log_content.split('\n')
        
        found_urls = []
        for line in lines:
            # Match actual docker push commands (not "The push refers to repository" messages)
            if 'docker' in line and 'push artifactory' in line:
                # Extract the URL after 'push'
                parts = line.split('push')
                if len(parts) > 1:
                    # Get everything after 'push' and clean it up
                    url_part = parts[1].strip()
                    # Remove any trailing shell characters or quotes
                    url_part = url_part.split()[0] if url_part.split() else url_part
                    
                    # Validate it looks like an artifactory URL
                    if url_part.startswith('artifactory.helix.gsa.gov'):
                        found_urls.append(url_part)
        
        # Prefer URLs that don't end with -latest (these are build-specific)
        url_part = None
        for url in found_urls:
            if not url.endswith('-latest'):
                url_part = url
                break
        
        # If no build-specific URL found, use the last one
        if not url_part and found_urls:
            url_part = found_urls[-1]
        
        return url_part
    
    def _display_summary(self):
        """Display summary"""
        self.summary_text.delete('1.0', tk.END)
        
        # Repository info
        if self.current_git_info:
            self.summary_text.insert(tk.END, "=== Repository Information ===\n", 'header')
            self.summary_text.insert(tk.END, f"Repository: {self.current_git_info.get('repo', 'Unknown')}\n")
            self.summary_text.insert(tk.END, f"Branch: {self.current_git_info.get('branch', 'Unknown')}\n")
            self.summary_text.insert(tk.END, f"Commit: {self.current_git_info.get('commit', 'Unknown')}\n\n")
        
        # Docker image
        if self.current_docker_image:
            self.summary_text.insert(tk.END, f"Docker Image: {self.current_docker_image}\n\n")
        
        # Vulnerability summary
        if self.vulnerabilities_data:
            self.summary_text.insert(tk.END, "=== Vulnerability Summary ===\n", 'header')
            self.summary_text.insert(tk.END, f"Total: {len(self.vulnerabilities_data)}\n\n")
            
            # Count by severity
            crit = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'critical'])
            high = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'high'])
            med = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'medium'])
            low = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'low'])
            
            self.summary_text.insert(tk.END, f"  Critical: {crit}\n", 'critical')
            self.summary_text.insert(tk.END, f"  High: {high}\n", 'high')
            self.summary_text.insert(tk.END, f"  Medium: {med}\n", 'medium')
            self.summary_text.insert(tk.END, f"  Low: {low}\n\n", 'low')
        
        # Compliance summary
        if self.compliance_data:
            self.summary_text.insert(tk.END, "=== Compliance Issues ===\n", 'header')
            self.summary_text.insert(tk.END, f"Total: {len(self.compliance_data)}\n")
        
        # Configure tags
        self.summary_text.tag_configure('header', font=('Consolas', 10, 'bold'), foreground=ACCENT2)
        self.summary_text.tag_configure('critical', foreground=ERROR)
        self.summary_text.tag_configure('high', foreground='#ff6666')
        self.summary_text.tag_configure('medium', foreground=WARNING)
        self.summary_text.tag_configure('low', foreground='#999999')
    
    def diff_cves(self):
        """Compare CVEs between two builds"""
        repo = self.repo_var.get()
        branch = self.branch_var.get()
        build = self.build_var.get()
        diff_branch = self.diff_branch_var.get()
        diff_build = self.diff_build_var.get()
        
        if not repo or not branch or not diff_branch:
            messagebox.showwarning("Missing Input", "Please select repository, branch, and diff branch")
            return
        
        self.status_var.set("Comparing CVEs...")
        thread = threading.Thread(
            target=self._diff_cves_thread,
            args=(repo, branch, build, diff_branch, diff_build),
            daemon=True
        )
        thread.start()
    
    def _diff_cves_thread(self, repo, branch, build, diff_branch, diff_build):
        """Background thread to compare CVEs"""
        try:
            self.after(0, lambda: self.status_var.set("Fetching Build 1 CVE data..."))
            
            # Fetch build 1 data
            data1 = self._fetch_build_data(repo, branch, build)
            if not data1:
                self.after(0, lambda: self.status_var.set("Failed to fetch Build 1"))
                return
            
            self.after(0, lambda: self.status_var.set("Fetching Build 2 CVE data..."))
            
            # Fetch build 2 data
            data2 = self._fetch_build_data(repo, diff_branch, diff_build)
            if not data2:
                self.after(0, lambda: self.status_var.set("Failed to fetch Build 2"))
                return
            
            # Extract vulnerabilities
            vulnerabilities1 = data1.get('vulnerabilities', [])
            vulnerabilities2 = data2.get('vulnerabilities', [])
            
            # Compare CVEs
            self.after(0, lambda: self.status_var.set("Comparing CVEs..."))
            
            # Create CVE dictionaries for comparison
            cve_dict1 = {v.get('cve'): v for v in vulnerabilities1 if v.get('cve')}
            cve_dict2 = {v.get('cve'): v for v in vulnerabilities2 if v.get('cve')}
            
            # Find differences
            cve_set1 = set(cve_dict1.keys())
            cve_set2 = set(cve_dict2.keys())
            
            fixed_cves = {cve: cve_dict1[cve] for cve in (cve_set1 - cve_set2)}  # In build 1 but not in build 2
            new_cves = {cve: cve_dict2[cve] for cve in (cve_set2 - cve_set1)}    # In build 2 but not in build 1
            unchanged_cves = {cve: cve_dict1[cve] for cve in (cve_set1 & cve_set2)}  # In both builds
            
            # Display results
            self.after(0, lambda: self._display_diff(
                branch, build or 'latest',
                diff_branch, diff_build or 'latest',
                fixed_cves, new_cves, unchanged_cves
            ))
            
        except Exception as e:
            import traceback
            error_msg = f"Exception occurred:\n{str(e)}\n{traceback.format_exc()}"
            self.after(0, lambda: messagebox.showerror("Error", error_msg))
            self.after(0, lambda: self.status_var.set("Error comparing CVEs"))
    
    def _fetch_build_data(self, repo, branch, build):
        """Fetch build data for CVE comparison"""
        try:
            # Import jenkins functions
            from auger.tools.jenkins import build_job_name
            
            # Build job name
            job_name = build_job_name(repo, branch)
            
            # Use lastBuild if no build number specified
            if not build:
                build = "lastBuild"
            
            # Fetch build log from Jenkins
            api_url = f"{self.jenkins_url}/job/{job_name}/{build}/consoleText"
            response = requests.get(api_url, auth=(self.jenkins_user, self.jenkins_token), timeout=60)
            
            if response.status_code == 200:
                log_content = response.text
                
                # Parse vulnerabilities from the log
                vulnerabilities = parse_prisma_vulnerabilities(log_content)
                
                return {
                    'vulnerabilities': vulnerabilities,
                    'branch': branch,
                    'build': build
                }
            else:
                return None
                
        except Exception as e:
            print(f"Error fetching build data: {e}")
            return None
    
    def _display_diff(self, branch1, build1, branch2, build2, fixed_cves, new_cves, unchanged_cves):
        """Display CVE diff results in a new tab"""
        # Remove existing CVE Diff tab if it exists
        for i in range(self.notebook.index('end')):
            try:
                if self.notebook.tab(i, 'text') == 'CVE Diff':
                    self.notebook.forget(i)
                    break
            except:
                pass
        
        # Create new CVE Diff tab (after Docker Image tab, which is index 5)
        diff_frame = tk.Frame(self.notebook, bg=BG)
        self.notebook.add(diff_frame, image=self._tab_icon_cvediff, text=' CVE Diff', compound=tk.LEFT)
        
        # Switch to the new tab
        self.notebook.select(diff_frame)
        
        # Create scrolled text widget for diff results
        diff_text = scrolledtext.ScrolledText(
            diff_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            bg=BG3,
            fg=FG,
            insertbackground=FG
        )
        diff_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        make_text_copyable(diff_text)
        
        # Configure text tags for colors
        diff_text.tag_config("header", font=("Consolas", 11, "bold"), foreground=ACCENT2)
        diff_text.tag_config("fixed", foreground="#00ff00")  # Bright green
        diff_text.tag_config("new", foreground=ERROR)  # Red
        diff_text.tag_config("critical", foreground="#ff0000")  # Bright red
        diff_text.tag_config("high", foreground="#ff6666")  # Light red
        diff_text.tag_config("medium", foreground=WARNING)  # Orange
        diff_text.tag_config("low", foreground="#999999")  # Gray
        
        # Build diff report
        report_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Header
        diff_text.insert(tk.END, "=" * 80 + "\n", "header")
        diff_text.insert(tk.END, "CVE DIFF REPORT\n", "header")
        diff_text.insert(tk.END, "=" * 80 + "\n\n", "header")
        
        diff_text.insert(tk.END, f"Build 1: {branch1} #{build1}\n")
        diff_text.insert(tk.END, f"Build 2: {branch2} #{build2}\n")
        diff_text.insert(tk.END, f"Report Date: {report_date}\n\n")
        
        # Summary
        diff_text.insert(tk.END, "=" * 80 + "\n", "header")
        diff_text.insert(tk.END, "SUMMARY\n", "header")
        diff_text.insert(tk.END, "=" * 80 + "\n\n", "header")
        
        diff_text.insert(tk.END, f"Fixed CVEs (in Build 1, not in Build 2): ", "fixed")
        diff_text.insert(tk.END, f"{len(fixed_cves)}\n", "fixed")
        diff_text.insert(tk.END, f"New CVEs (in Build 2, not in Build 1): ", "new")
        diff_text.insert(tk.END, f"{len(new_cves)}\n", "new")
        diff_text.insert(tk.END, f"Unchanged CVEs (in both builds): {len(unchanged_cves)}\n\n")
        
        # Severity breakdown for fixed CVEs
        if fixed_cves:
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            for cve_data in fixed_cves.values():
                severity = cve_data.get('severity', 'unknown').lower()
                if severity in severity_counts:
                    severity_counts[severity] += 1
            
            diff_text.insert(tk.END, "Fixed CVEs by Severity:\n")
            for severity, count in severity_counts.items():
                if count > 0:
                    diff_text.insert(tk.END, f"  {severity.capitalize()}: {count}\n", severity)
            diff_text.insert(tk.END, "\n")
        
        # Severity breakdown for new CVEs
        if new_cves:
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
            for cve_data in new_cves.values():
                severity = cve_data.get('severity', 'unknown').lower()
                if severity in severity_counts:
                    severity_counts[severity] += 1
            
            diff_text.insert(tk.END, "New CVEs by Severity:\n")
            for severity, count in severity_counts.items():
                if count > 0:
                    diff_text.insert(tk.END, f"  {severity.capitalize()}: {count}\n", severity)
            diff_text.insert(tk.END, "\n")
        
        # Fixed CVEs details
        if fixed_cves:
            diff_text.insert(tk.END, "=" * 80 + "\n", "header")
            diff_text.insert(tk.END, f"FIXED CVEs ({len(fixed_cves)})\n", "header")
            diff_text.insert(tk.END, "=" * 80 + "\n\n", "header")
            
            # Sort by severity
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_fixed = sorted(fixed_cves.items(), 
                                 key=lambda x: (severity_order.get(x[1].get('severity', 'unknown').lower(), 4), x[0]))
            
            for idx, (cve_id, cve_data) in enumerate(sorted_fixed, 1):
                severity = cve_data.get('severity', 'unknown').lower()
                cvss_score = cve_data.get('cvss', 'N/A')
                package = cve_data.get('package', 'unknown')
                version = cve_data.get('version', '')
                description = cve_data.get('description', 'No description available')
                
                # Truncate description
                if len(description) > 100:
                    description = description[:97] + "..."
                
                diff_text.insert(tk.END, f"{idx}. {cve_id} ", "fixed")
                diff_text.insert(tk.END, f"({severity})", severity)
                diff_text.insert(tk.END, f" - CVSS: {cvss_score}\n")
                diff_text.insert(tk.END, f"   Package: {package} {version}\n")
                diff_text.insert(tk.END, f"   Description: {description}\n\n")
        
        # New CVEs details
        if new_cves:
            diff_text.insert(tk.END, "=" * 80 + "\n", "header")
            diff_text.insert(tk.END, f"NEW CVEs ({len(new_cves)})\n", "header")
            diff_text.insert(tk.END, "=" * 80 + "\n\n", "header")
            
            # Sort by severity
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_new = sorted(new_cves.items(), 
                               key=lambda x: (severity_order.get(x[1].get('severity', 'unknown').lower(), 4), x[0]))
            
            for idx, (cve_id, cve_data) in enumerate(sorted_new, 1):
                severity = cve_data.get('severity', 'unknown').lower()
                cvss_score = cve_data.get('cvss', 'N/A')
                package = cve_data.get('package', 'unknown')
                version = cve_data.get('version', '')
                description = cve_data.get('description', 'No description available')
                
                # Truncate description
                if len(description) > 100:
                    description = description[:97] + "..."
                
                diff_text.insert(tk.END, f"{idx}. {cve_id} ", "new")
                diff_text.insert(tk.END, f"({severity})", severity)
                diff_text.insert(tk.END, f" - CVSS: {cvss_score}\n")
                diff_text.insert(tk.END, f"   Package: {package} {version}\n")
                diff_text.insert(tk.END, f"   Description: {description}\n\n")
        
        # Unchanged CVEs (top 20)
        if unchanged_cves:
            diff_text.insert(tk.END, "=" * 80 + "\n", "header")
            diff_text.insert(tk.END, f"UNCHANGED CVEs (showing top 20 of {len(unchanged_cves)})\n", "header")
            diff_text.insert(tk.END, "=" * 80 + "\n\n", "header")
            
            # Sort by severity and limit to top 20
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            sorted_unchanged = sorted(unchanged_cves.items(), 
                                     key=lambda x: (severity_order.get(x[1].get('severity', 'unknown').lower(), 4), x[0]))[:20]
            
            for idx, (cve_id, cve_data) in enumerate(sorted_unchanged, 1):
                severity = cve_data.get('severity', 'unknown').lower()
                cvss_score = cve_data.get('cvss', 'N/A')
                package = cve_data.get('package', 'unknown')
                version = cve_data.get('version', '')
                
                diff_text.insert(tk.END, f"{idx}. {cve_id} ")
                diff_text.insert(tk.END, f"({severity})", severity)
                diff_text.insert(tk.END, f" - CVSS: {cvss_score}\n")
                diff_text.insert(tk.END, f"   Package: {package} {version}\n\n")
        
        diff_text.config(state=tk.DISABLED)
        
        # Switch to the new CVE Diff tab
        self.notebook.select(diff_frame)
        
        self.status_var.set(f"✓ CVE diff complete: {len(fixed_cves)} fixed, {len(new_cves)} new")
    
    def get_context_for_auger(self):
        """Build context string for Ask Auger panel"""
        context_parts = []
        
        # Repository info
        if self.current_git_info:
            context_parts.append(f"REPOSITORY: {self.current_git_info.get('repo', 'Unknown')}")
            context_parts.append(f"BRANCH: {self.current_git_info.get('branch', 'Unknown')}")
            context_parts.append(f"COMMIT: {self.current_git_info.get('commit', 'Unknown')}")
        
        # Docker image
        if self.current_docker_image:
            context_parts.append(f"DOCKER IMAGE: {self.current_docker_image}")
        
        # Vulnerability summary
        if self.vulnerabilities_data:
            context_parts.append(f"\nVULNERABILITIES: {len(self.vulnerabilities_data)} total")
            
            crit = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'critical'])
            high = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'high'])
            med = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'medium'])
            low = len([v for v in self.vulnerabilities_data if v.get('severity', '').lower() == 'low'])
            
            context_parts.append(f"  - Critical: {crit}")
            context_parts.append(f"  - High: {high}")
            context_parts.append(f"  - Medium: {med}")
            context_parts.append(f"  - Low: {low}")
            
            # Add sample vulnerabilities
            context_parts.append("\nVULNERABILITY DETAILS (sample):")
            for i, vuln in enumerate(self.vulnerabilities_data[:20]):
                cve = vuln.get('cve', 'N/A')
                severity = vuln.get('severity', 'N/A')
                package = vuln.get('package', 'N/A')
                version = vuln.get('version', 'N/A')
                cvss = vuln.get('cvss', 'N/A')
                desc = vuln.get('description', 'N/A')[:100]
                context_parts.append(f"  {i+1}. {cve} ({severity}) - {package} {version} - CVSS: {cvss}")
                context_parts.append(f"     {desc}")
        
        return "\n".join(context_parts)
