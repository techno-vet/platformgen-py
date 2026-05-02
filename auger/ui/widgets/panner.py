"""
Panner Widget - DataDog Log Downloader (Rover) for Auger
Download logs from DataDog with advanced filtering and display
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import subprocess
import json
import os
import queue
from pathlib import Path
from dotenv import load_dotenv
import threading
import datetime
import urllib.parse
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu, auger_home as _auger_home
import webbrowser
import platform

# --- file-based debug logger (visible even when stdout is a closed pipe) ---
_PANNER_LOG = Path('/tmp/panner_debug.log')
_panner_log_fh = None

def _plog(msg):
    """Append a timestamped line to /tmp/panner_debug.log."""
    global _panner_log_fh
    try:
        if _panner_log_fh is None or _panner_log_fh.closed:
            _panner_log_fh = _PANNER_LOG.open('a', buffering=1)
        ts = datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]
        _panner_log_fh.write(f"{ts} {msg}\n")
        _panner_log_fh.flush()
    except Exception:
        pass

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
FG2 = '#a0a0a0'



class PannerWidget(tk.Frame):
    """DataDog log downloader widget (Rover/Panner)"""
    
    # Widget metadata
    WIDGET_NAME = "panner"
    WIDGET_TITLE = "Panner"
    WIDGET_ICON = "📡"
    WIDGET_ICON_NAME = "panner"
    
    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        
        self.context_builder_callback = context_builder_callback
        self.log_data = []
        self._iid_to_record = {}   # treeview iid → full raw record (for details panel)
        self._all_rows = []        # [(iid, values, tags)] — used for search/filter
        self._user_scrolled = False  # True when user manually scrolls away from bottom

        # Streaming state
        self._stream_process = None
        self._streaming = False
        self._stream_count = 0
        self._poll_after_id = None
        self._autoscroll = True
        self._row_queue = queue.Queue()   # background thread → main thread
        self._drain_after_id = None       # after() id for row-drain loop
        self._do_live_after_drain = False # set by _finalize_stream for live repoll

        # kubectl streaming state
        self._kubectl_ws = None           # active websocket connection (kubectl follow)
        self._log_source = 'datadog'      # 'kubectl' or 'datadog' — set per-download
        self._kubectl_pod = None          # (cluster_id, namespace, pod_name, container)
        self._kubectl_processes = []      # active curl subprocesses (one per streamed pod)
        
        # Get widget directory for resources
        self.widget_dir = Path(__file__).parent
        self.resources_dir = self.widget_dir / "panner_resources"

        # Find the directory that has node_modules (may be the baked copy)
        self.node_dir = self._find_node_dir()
        
        # Load environment for DataDog credentials
        load_dotenv(_auger_home() / '.auger' / '.env')
        
        # Load options from resource files
        self.cluster_options = self._load_options("ddog_assist_clusters")
        self.namespace_options = self._load_options("ddog_assist_namespaces")
        self.service_options = self._load_options("ddog_assist_services")
        self.dockerfile_service_options = self._load_options("ddog_dockerfile_services")
        self.all_service_options = self.service_options + self.dockerfile_service_options

        # Rancher-driven dynamic selector state
        # _cluster_id_map: display_name → rancher_cluster_id
        self._cluster_id_map = {}
        self._rancher_ns_cache   = {}   # cluster_id → [namespace, ...]
        self._rancher_svc_cache  = {}   # (cluster_id, namespace) → [service_name, ...]
        self._rancher_pod_cache  = {}   # (cluster_id, namespace, service) → [(pod_name, container, age_str, restarts)]
        self._pod_cache_time     = {}   # key → epoch time of last fetch (30s TTL)
        self._dynamic_enabled    = bool(os.getenv('RANCHER_URL') and os.getenv('RANCHER_BEARER_TOKEN'))
        
        self._create_ui()
        self._check_dependencies()

    def _show_stop_btn(self):
        """Swap Download button out, show Stop button."""
        self._download_btn.pack_forget()
        self._stop_btn.pack(side=tk.LEFT, padx=5)

    def _show_download_btn(self):
        """Swap Stop button out, restore Download button."""
        self._stop_btn.pack_forget()
        if not self._download_btn.winfo_ismapped():
            self._download_btn.pack(side=tk.LEFT, padx=5)

    def _start_drain_loop(self, insert_top=False):
        """Start periodic queue-draining in the main thread (100ms interval)."""
        if self._drain_after_id:
            self.after_cancel(self._drain_after_id)
        self._drain_after_id = self.after(100, self._drain_row_queue, insert_top)

    # Maximum rows kept live in the Treeview — oldest pruned when exceeded
    _MAX_TABLE_ROWS = 5000
    _PRUNE_ROWS     = 1000   # delete this many oldest rows when cap is hit

    def _drain_row_queue(self, insert_top=False):
        """Drain up to 50 rows from queue per tick, then reschedule."""
        try:
            drained = 0
            needs_scroll = False
            while drained < 50:
                try:
                    item = self._row_queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:  # sentinel — stream finished, do final UI update
                    self._drain_after_id = None
                    self._streaming = False   # ensure all background threads stop
                    _plog(f"[Panner] drain loop: None sentinel received — streaming={self._stream_count} rows")
                    self.count_var.set(f"{self._stream_count} logs")
                    self.status_var.set(f"✓ {self._stream_count} log rows streamed")
                    self._show_download_btn()
                    if self.live_tail_var.get():  # safe: this is the main thread
                        self._poll_after_id = self.after(30_000, self._live_repoll)
                        self.status_var.set(f"✓ {self._stream_count} rows — 🔴 Live re-poll in 30s…")
                    return
                self._append_row(item, insert_top=insert_top)
                self._stream_count += 1
                drained += 1
                if not insert_top:
                    needs_scroll = True
            if drained > 0:
                # Prune oldest rows if Treeview is too large
                children = self.table.get_children()
                if len(children) > self._MAX_TABLE_ROWS:
                    to_delete = children[:self._PRUNE_ROWS]
                    for iid in to_delete:
                        self.table.delete(iid)
                        self._iid_to_record.pop(iid, None)
                    # Trim _all_rows to match
                    self._all_rows = self._all_rows[self._PRUNE_ROWS:]
                # Scroll once per batch instead of per row
                if needs_scroll and self._autoscroll and not self._user_scrolled:
                    self.table.yview_moveto(1.0)
                self.count_var.set(f"{self._stream_count} logs")
                if self._log_source == 'kubectl':
                    self.status_var.set(f"🟢 [LIVE kubectl] {self._stream_count} rows — streaming…")
                else:
                    self.status_var.set(f"⏳ Streaming… {self._stream_count} rows")
        except Exception as e:
            _plog(f"[Panner] _drain_row_queue error: {e}")
        self._drain_after_id = self.after(100, self._drain_row_queue, insert_top)

    def _find_node_dir(self):
        """Return the directory that contains node_modules for index.mjs."""
        if (self.widget_dir / "node_modules").exists():
            return self.widget_dir
        # Fallback to known baked location
        baked = _auger_home() / "auger-platform" / "auger_baked" / "ui" / "widgets"
        if (baked / "node_modules").exists():
            return baked
        return self.widget_dir  # fallback (will show install warning)

    def _show_error(self, title, message):
        """Show a copyable error dialog with 'Copy to Ask Auger' support."""
        _CopyableErrorDialog(self.winfo_toplevel(), title, message,
                             ask_auger_cb=self._copy_to_ask_auger)

    def _copy_to_ask_auger(self, text):
        """Copy error text to clipboard prefixed for Ask Auger."""
        payload = f"I got this error in the Panner widget — can you help?\n\n{text}"
        try:
            self.clipboard_clear()
            self.clipboard_append(payload)
        except Exception:
            pass

    def _load_options(self, filename):
        """Load options from resource file"""
        filepath = self.resources_dir / filename
        try:
            with open(filepath, "r") as f:
                return [line.strip() for line in f if line.strip()]
        except FileNotFoundError:
            print(f"Resource file not found: {filepath}")
            return []
    
    def _check_dependencies(self):
        """Check if node.js and dependencies are installed"""
        if not (self.node_dir / "node_modules").exists():
            self.status_var.set("⚠️ Node dependencies not installed. Click 'Install Dependencies'")
        else:
            self.status_var.set("✓ Ready to download logs")
    
    def _create_ui(self):
        """Create the widget UI"""
        self._icons = {}
        for name in ('delete', 'refresh', 'download', 'search', 'copy', 'play'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        # Main container with scrolling
        main_frame = tk.Frame(self, bg=BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Top: Query and filters
        self._create_query_section(main_frame)
        
        # Middle: Configuration options
        self._create_config_section(main_frame)
        
        # Buttons
        self._create_button_section(main_frame)
        
        # Results table
        self._create_results_table(main_frame)
        
        # Log details view
        self._create_details_section(main_frame)
        
        # Status bar
        self._create_status_bar(main_frame)
    
    def _create_query_section(self, parent):
        """Create query and filter section with cascading Rancher-driven selectors."""
        query_frame = tk.Frame(parent, bg=BG2)
        query_frame.pack(fill=tk.X, padx=5, pady=5)

        tk.Label(
            query_frame, text="Query:", font=('Segoe UI', 10, 'bold'),
            fg=FG, bg=BG2
        ).grid(row=0, column=0, sticky=tk.W, padx=5, pady=5)

        self.query_var = tk.StringVar()
        self.query_entry = tk.Entry(
            query_frame, textvariable=self.query_var, width=80,
            font=('Segoe UI', 10), bg=BG3, fg=FG
        )
        self.query_entry.grid(row=0, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=5)
        query_frame.columnconfigure(1, weight=1)

        # ── Cascading listboxes ──────────────────────────────────────────
        filter_frame = tk.Frame(parent, bg=BG2)
        filter_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Row 0: header frames (label + inline filter entry for Namespace/Service)
        # Row 1: listboxes

        # ── Cluster header: "Cluster: [filter entry]" ──
        cl_hdr = tk.Frame(filter_frame, bg=BG2)
        cl_hdr.grid(row=0, column=0, sticky=tk.EW, padx=5, pady=2)
        tk.Label(cl_hdr, text="Cluster:", font=('Segoe UI', 10, 'bold'),
                 fg=FG, bg=BG2).pack(side=tk.LEFT)
        self._cl_filter_var = tk.StringVar()
        self._cl_filter_var.trace_add('write', lambda *_: self._filter_cl_list())
        tk.Entry(cl_hdr, textvariable=self._cl_filter_var,
                 font=('Segoe UI', 8), bg=BG3, fg=FG2, insertbackground=FG,
                 relief=tk.FLAT, width=12).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # ── Namespace header: "Namespace: [filter entry]" ──
        ns_hdr = tk.Frame(filter_frame, bg=BG2)
        ns_hdr.grid(row=0, column=1, sticky=tk.EW, padx=5, pady=2)
        tk.Label(ns_hdr, text="Namespace:", font=('Segoe UI', 10, 'bold'),
                 fg=FG, bg=BG2).pack(side=tk.LEFT)
        self._ns_filter_var = tk.StringVar()
        self._ns_filter_var.trace_add('write', lambda *_: self._filter_ns_list())
        tk.Entry(ns_hdr, textvariable=self._ns_filter_var,
                 font=('Segoe UI', 8), bg=BG3, fg=FG2, insertbackground=FG,
                 relief=tk.FLAT, width=12).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # ── Service header: "Service: [filter entry]" ──
        svc_hdr = tk.Frame(filter_frame, bg=BG2)
        svc_hdr.grid(row=0, column=2, sticky=tk.EW, padx=5, pady=2)
        tk.Label(svc_hdr, text="Service:", font=('Segoe UI', 10, 'bold'),
                 fg=FG, bg=BG2).pack(side=tk.LEFT)
        self._svc_filter_var = tk.StringVar()
        self._svc_filter_var.trace_add('write', lambda *_: self._filter_svc_list())
        tk.Entry(svc_hdr, textvariable=self._svc_filter_var,
                 font=('Segoe UI', 8), bg=BG3, fg=FG2, insertbackground=FG,
                 relief=tk.FLAT, width=12).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # ── Pod header: "Pod: [filter entry]" ──
        pod_hdr = tk.Frame(filter_frame, bg=BG2)
        pod_hdr.grid(row=0, column=3, sticky=tk.EW, padx=5, pady=2)
        tk.Label(pod_hdr, text="Pod:", font=('Segoe UI', 10, 'bold'),
                 fg=FG, bg=BG2).pack(side=tk.LEFT)
        self._pod_filter_var = tk.StringVar()
        self._pod_filter_var.trace_add('write', lambda *_: self._filter_pod_list())
        tk.Entry(pod_hdr, textvariable=self._pod_filter_var,
                 font=('Segoe UI', 8), bg=BG3, fg=FG2, insertbackground=FG,
                 relief=tk.FLAT, width=12).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # ── Cluster listbox ──
        self._all_cl_items = list(self.cluster_options)
        self.cluster_listbox = tk.Listbox(
            filter_frame, selectmode=tk.SINGLE, height=6, exportselection=False,
            bg=BG3, fg=FG, font=('Segoe UI', 9)
        )
        if self._dynamic_enabled:
            self.cluster_listbox.insert(tk.END, 'Loading…')
        else:
            for option in self.cluster_options:
                self.cluster_listbox.insert(tk.END, option)
        self.cluster_listbox.grid(row=1, column=0, sticky=tk.NSEW, padx=5, pady=2)
        add_listbox_menu(self.cluster_listbox)
        self.cluster_listbox.bind("<ButtonRelease-1>", self._on_cluster_select)

        # ── Namespace listbox ──
        self._all_ns_items = list(self.namespace_options)
        self.namespace_listbox = tk.Listbox(
            filter_frame, selectmode=tk.SINGLE, height=6, exportselection=False,
            bg=BG3, fg=FG, font=('Segoe UI', 9)
        )
        if not self._dynamic_enabled:
            for option in self.namespace_options:
                self.namespace_listbox.insert(tk.END, option)
        self.namespace_listbox.grid(row=1, column=1, sticky=tk.NSEW, padx=5, pady=2)
        add_listbox_menu(self.namespace_listbox)
        self.namespace_listbox.bind("<ButtonRelease-1>", self._on_namespace_select)

        # ── Service listbox ──
        self._all_svc_items = list(self.all_service_options)
        self.service_listbox = tk.Listbox(
            filter_frame, selectmode=tk.SINGLE, height=6, exportselection=False,
            bg=BG3, fg=FG, font=('Segoe UI', 9)
        )
        if not self._dynamic_enabled:
            for option in self.all_service_options:
                self.service_listbox.insert(tk.END, option)
        self.service_listbox.grid(row=1, column=2, sticky=tk.NSEW, padx=5, pady=2)
        add_listbox_menu(self.service_listbox)
        self.service_listbox.bind("<ButtonRelease-1>", self._on_service_select)

        # ── Pod listbox ──
        self.pod_listbox = tk.Listbox(
            filter_frame, selectmode=tk.SINGLE, height=6, exportselection=False,
            bg=BG3, fg=FG2, font=('Segoe UI', 9)
        )
        self.pod_listbox.grid(row=1, column=3, sticky=tk.NSEW, padx=5, pady=2)
        self.pod_listbox.bind("<ButtonRelease-1>", self._on_pod_select)
        self._pod_detail_map = {}

        filter_frame.columnconfigure(0, weight=1)
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(2, weight=1)
        filter_frame.columnconfigure(3, weight=1)
        filter_frame.rowconfigure(1, weight=1)

        # Kick off cluster list discovery in background if Rancher is available
        if self._dynamic_enabled:
            threading.Thread(target=self._load_clusters_async, daemon=True).start()
    
    def _create_config_section(self, parent):
        """Create configuration options section"""
        config_frame = tk.Frame(parent, bg=BG2)
        config_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Row 0: Index, Page Size, From, To
        tk.Label(
            config_frame, text="Index:", font=('Segoe UI', 10),
            fg=FG, bg=BG2
        ).grid(row=0, column=0, sticky=tk.W, padx=5, pady=2)
        
        self.index_entry = tk.Entry(config_frame, width=10, font=('Segoe UI', 10), bg=BG3, fg=FG)
        self.index_entry.insert(0, "main")
        self.index_entry.grid(row=0, column=1, sticky=tk.W, padx=5, pady=2)
        
        tk.Label(
            config_frame, text="Page Size:", font=('Segoe UI', 10),
            fg=FG, bg=BG2
        ).grid(row=0, column=2, sticky=tk.W, padx=5, pady=2)
        
        self.page_size_entry = tk.Entry(config_frame, width=8, font=('Segoe UI', 10), bg=BG3, fg=FG)
        self.page_size_entry.insert(0, "5000")
        self.page_size_entry.grid(row=0, column=3, sticky=tk.W, padx=5, pady=2)
        
        tk.Label(
            config_frame, text="From (min ago):", font=('Segoe UI', 10),
            fg=FG, bg=BG2
        ).grid(row=0, column=4, sticky=tk.W, padx=(15, 5), pady=2)
        
        self.from_entry = tk.Entry(config_frame, width=8, font=('Segoe UI', 10), bg=BG3, fg=FG)
        self.from_entry.insert(0, "30")
        self.from_entry.grid(row=0, column=5, sticky=tk.W, padx=5, pady=2)
        
        tk.Label(
            config_frame, text="To:", font=('Segoe UI', 10),
            fg=FG, bg=BG2
        ).grid(row=0, column=6, sticky=tk.W, padx=(15, 5), pady=2)
        
        self.to_entry = tk.Entry(config_frame, width=8, font=('Segoe UI', 10), bg=BG3, fg=FG)
        self.to_entry.grid(row=0, column=7, sticky=tk.W, padx=5, pady=2)
        
        # Row 1: Output, Format, DataDog URL Builder controls
        tk.Label(
            config_frame, text="Output:", font=('Segoe UI', 10),
            fg=FG, bg=BG2
        ).grid(row=1, column=0, sticky=tk.W, padx=5, pady=2)
        
        self.output_entry = tk.Entry(config_frame, width=15, font=('Segoe UI', 10), bg=BG3, fg=FG)
        self.output_entry.insert(0, "results.json")
        self.output_entry.grid(row=1, column=1, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        tk.Label(
            config_frame, text="Format:", font=('Segoe UI', 10),
            fg=FG, bg=BG2
        ).grid(row=1, column=3, sticky=tk.W, padx=5, pady=2)
        
        self.format_var = tk.StringVar(value="json")
        self.format_dropdown = ttk.Combobox(
            config_frame, textvariable=self.format_var, values=["json", "ndjson"],
            width=8, state="readonly", font=('Segoe UI', 10)
        )
        self.format_dropdown.grid(row=1, column=4, sticky=tk.W, padx=5, pady=2)
        
        # DataDog URL Builder (inline on row 1)
        tk.Label(
            config_frame, text="URL:", font=('Segoe UI', 12),
            fg=ACCENT2, bg=BG2
        ).grid(row=1, column=5, sticky=tk.W, padx=(15, 2), pady=2)
        
        # Checkboxes
        self.launch_logs_var = tk.BooleanVar(value=True)
        self.launch_pods_var = tk.BooleanVar(value=False)
        self.live_tail_var = tk.BooleanVar(value=False)
        
        checkbox_frame = tk.Frame(config_frame, bg=BG2)
        checkbox_frame.grid(row=1, column=6, columnspan=2, sticky=tk.W, padx=5, pady=2)
        
        tk.Checkbutton(
            checkbox_frame, text="Logs", variable=self.launch_logs_var,
            bg=BG2, fg=FG, selectcolor=BG3, font=('Segoe UI', 9),
            activebackground=BG2, activeforeground=FG
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Checkbutton(
            checkbox_frame, text="Pods", variable=self.launch_pods_var,
            bg=BG2, fg=FG, selectcolor=BG3, font=('Segoe UI', 9),
            activebackground=BG2, activeforeground=FG
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Checkbutton(
            checkbox_frame, text="Live", variable=self.live_tail_var,
            bg=BG2, fg=WARNING, selectcolor=BG3, font=('Segoe UI', 9),
            activebackground=BG2, activeforeground=WARNING
        ).pack(side=tk.LEFT, padx=2)
        
        # Open DataDog button
        tk.Button(
            config_frame, text=" DataDog",
            image=self._icons.get('play'), compound=tk.LEFT,
            command=self._open_in_datadog,
            bg=ACCENT2, fg='black', font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT, padx=12, pady=4
        ).grid(row=1, column=8, sticky=tk.W, padx=5, pady=2)
    
    def _create_button_section(self, parent):
        """Create action buttons"""
        button_frame = tk.Frame(parent, bg=BG2)
        button_frame.pack(fill=tk.X, padx=5, pady=5)

        # Wrapper so Download and Stop swap in the SAME slot (keeps button order stable)
        self._btn_slot = tk.Frame(button_frame, bg=BG2)
        self._btn_slot.pack(side=tk.LEFT, padx=0)

        self._download_btn = tk.Button(
            self._btn_slot, text="Stream Logs",
            image=self._icons.get('download'), compound=tk.LEFT,
            command=self.download_logs,
            bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT, padx=20, pady=8
        )
        self._download_btn.pack(side=tk.LEFT, padx=5)

        self._stop_btn = tk.Button(
            self._btn_slot, text="Stop",
            command=self._stop_stream,
            bg=ERROR, fg='white', font=('Segoe UI', 10, 'bold'),
            relief=tk.FLAT, padx=20, pady=8,
            cursor='hand2'
        )
        # Stop button starts hidden — shown via pack when streaming begins

        tk.Button(
            button_frame, text=" Clear Results",
            image=self._icons.get('delete'), compound=tk.LEFT,
            command=self._clear_results,
            bg=BG3, fg=FG, font=('Segoe UI', 10),
            relief=tk.FLAT, padx=20, pady=8
        ).pack(side=tk.LEFT, padx=5)

        # Autoscroll toggle
        self._autoscroll_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            button_frame, text="Auto-scroll", variable=self._autoscroll_var,
            bg=BG2, fg=FG2, selectcolor=BG3, font=('Segoe UI', 9),
            activebackground=BG2, activeforeground=FG,
            command=lambda: setattr(self, '_autoscroll', self._autoscroll_var.get())
        ).pack(side=tk.LEFT, padx=10)
    
    def _create_results_table(self, parent):
        """Create results table with search/filter bar"""
        table_frame = tk.Frame(parent, bg=BG2)
        table_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Header row: "Log Results" label + search bar
        header_row = tk.Frame(table_frame, bg=BG2)
        header_row.pack(fill=tk.X, padx=5, pady=(5, 2))

        tk.Label(
            header_row, text="Log Results", font=('Segoe UI', 11, 'bold'),
            fg=FG, bg=BG2
        ).pack(side=tk.LEFT)

        tk.Label(header_row, text="Filter:", bg=BG2, fg=FG2,
                 font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(20, 3))

        self._search_var = tk.StringVar()
        self._search_var.trace_add('write', lambda *_: self._apply_filter())
        self._search_entry = tk.Entry(
            header_row, textvariable=self._search_var,
            width=30, font=('Segoe UI', 9), bg=BG3, fg=FG,
            insertbackground=FG, relief=tk.FLAT
        )
        self._search_entry.pack(side=tk.LEFT, padx=3, ipady=3)

        tk.Button(
            header_row, text="X",
            command=lambda: self._search_var.set(''),
            bg=BG3, fg=FG2, font=('Segoe UI', 8), relief=tk.FLAT, padx=4
        ).pack(side=tk.LEFT, padx=1)

        self._match_count_var = tk.StringVar(value="")
        tk.Label(
            header_row, textvariable=self._match_count_var,
            font=('Segoe UI', 9), fg=FG2, bg=BG2
        ).pack(side=tk.LEFT, padx=8)

        # Scrollbars + treeview
        scroll_frame = tk.Frame(table_frame, bg=BG2)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        v_scroll = tk.Scrollbar(scroll_frame, orient=tk.VERTICAL)
        v_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        h_scroll = tk.Scrollbar(scroll_frame, orient=tk.HORIZONTAL)
        h_scroll.pack(side=tk.BOTTOM, fill=tk.X)

        self.table = ttk.Treeview(
            scroll_frame,
            columns=("cluster_name", "kube_namespace", "service", "container_name", "status", "timestamp", "message"),
            show="headings",
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set
        )

        # Configure columns
        self.table.heading("cluster_name", text="Cluster")
        self.table.heading("kube_namespace", text="Namespace")
        self.table.heading("service", text="Service")
        self.table.heading("container_name", text="Pod")
        self.table.heading("status", text="Status")
        self.table.heading("timestamp", text="Timestamp")
        self.table.heading("message", text="Message")

        self.table.column("cluster_name", width=100)
        self.table.column("kube_namespace", width=100)
        self.table.column("service", width=100)
        self.table.column("container_name", width=120)
        self.table.column("status", width=70)
        self.table.column("timestamp", width=150)
        self.table.column("message", width=500)

        self.table.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self.table)

        v_scroll.config(command=self.table.yview)

        # Style
        style = ttk.Style()
        style.configure("Treeview", background=BG3, foreground=FG, fieldbackground=BG3, rowheight=25)
        style.configure("Treeview.Heading", background=BG2, foreground=FG)
        style.map("Treeview", background=[('selected', ACCENT)])

        # Bind selection → details panel
        self.table.bind("<ButtonRelease-1>", self._display_log_details)

        # Detect manual scroll — disable auto-scroll while user is browsing
        v_scroll.config(command=self._on_vscroll)
        self._v_scroll = v_scroll

        # Error row highlight
        self.table.tag_configure('error', background=ERROR, foreground='#ffffff')
        self.table.tag_configure('match', background='#1e3a2f', foreground=FG)   # subtle green tint for search matches
        # Per-pod tint colors for multi-pod streaming
        self.table.tag_configure('pod0', background='#152b15', foreground=FG)   # dark green
        self.table.tag_configure('pod1', background='#15152b', foreground=FG)   # dark blue
        self.table.tag_configure('pod2', background='#2b1515', foreground=FG)   # dark red
        self.table.tag_configure('pod3', background='#15232b', foreground=FG)   # dark teal

    def _on_vscroll(self, *args):
        """Track vertical scroll — note if user scrolled away from bottom."""
        self.table.yview(*args)
        self._user_scrolled = True
        # After tk processes the scroll, check if we're back at the bottom
        self.after(10, self._check_scroll_position)

    def _check_scroll_position(self):
        """Re-enable auto-scroll if user scrolls back to the bottom."""
        try:
            _, bottom = self.table.yview()
            if bottom >= 0.999:
                self._user_scrolled = False  # back at bottom — re-enable auto-scroll
            # _autoscroll_var reflects current state for checkbox
            self._autoscroll_var.set(not self._user_scrolled)
        except Exception:
            pass

    def _apply_filter(self):
        """Show only rows whose message/timestamp match the search text."""
        term = self._search_var.get().strip().lower()
        # Detach all rows first
        for iid in self.table.get_children():
            self.table.detach(iid)
        # Re-attach matching rows in order
        match_count = 0
        for iid, values, tags in self._all_rows:
            if not term or any(term in str(v).lower() for v in values):
                self.table.reattach(iid, '', tk.END)
                # Highlight matched rows
                new_tags = [t for t in tags if t != 'match']
                if term:
                    new_tags.append('match')
                self.table.item(iid, tags=new_tags)
                match_count += 1
        if term:
            self._match_count_var.set(f"{match_count} match{'es' if match_count != 1 else ''}")
        else:
            self._match_count_var.set("")
    
    def _create_details_section(self, parent):
        """Create log details view"""
        details_frame = tk.Frame(parent, bg=BG2)
        details_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        tk.Label(
            details_frame, text="Log Details (JSON)", font=('Segoe UI', 11, 'bold'),
            fg=FG, bg=BG2
        ).pack(fill=tk.X, padx=5, pady=(5, 2))

        self.details_text = scrolledtext.ScrolledText(
            details_frame, height=10, wrap=tk.NONE,
            bg=BG3, fg=FG, font=('Consolas', 9)
        )
        self.details_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        # Tag for search term highlight
        self.details_text.tag_configure(
            'search_highlight',
            background='#f0c040', foreground='#1e1e1e', font=('Consolas', 9, 'bold')
        )
        make_text_copyable(self.details_text)
    
    def _create_status_bar(self, parent):
        """Create status bar"""
        status_frame = tk.Frame(parent, bg=BG2)
        status_frame.pack(fill=tk.X, pady=(5, 0))

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(
            status_frame, textvariable=self.status_var, font=('Segoe UI', 9),
            fg=FG, bg=BG2, anchor=tk.W
        ).pack(side=tk.LEFT, padx=5, pady=3)

        self.count_var = tk.StringVar(value="")
        tk.Label(
            status_frame, textvariable=self.count_var, font=('Segoe UI', 9),
            fg=ACCENT, bg=BG2, anchor=tk.E
        ).pack(side=tk.RIGHT, padx=5, pady=3)

        # Source badge — shows [LIVE kubectl] or [DataDog] while streaming
        self._source_var = tk.StringVar(value="")
        self._source_label = tk.Label(
            status_frame, textvariable=self._source_var,
            font=('Segoe UI', 9, 'bold'), bg=BG2, anchor=tk.E
        )
        self._source_label.pack(side=tk.RIGHT, padx=10, pady=3)
    
    def _format_listbox_selections(self, listbox, field_name):
        """Format selected options from listbox for query"""
        selected_indices = listbox.curselection()
        if not selected_indices:
            return ""
        selected_values = [listbox.get(i) for i in selected_indices]
        if len(selected_values) == 1:
            return f"{field_name}:{selected_values[0]}"
        else:
            values = " OR ".join(selected_values)
            return f"{field_name}:({values})"

    def _update_query_field(self, event=None):
        """Update query field based on listbox selections"""
        cluster_selections   = self._format_listbox_selections(self.cluster_listbox,   "kube_cluster_name")
        namespace_selections = self._format_listbox_selections(self.namespace_listbox, "kube_namespace")
        service_selections   = self._format_listbox_selections(self.service_listbox,   "service")
        query_parts = [p for p in [cluster_selections, namespace_selections, service_selections] if p]
        self.query_var.set(" ".join(query_parts))
        self.query_entry.update_idletasks()

    # ------------------------------------------------------------------ #
    #  Dynamic Rancher-driven cascade selectors                           #
    # ------------------------------------------------------------------ #

    _PINNED_CLUSTERS = ['assist-core-development', 'assist-core-staging', 'assist-core-production']

    def _rancher_get(self, path, timeout=6):
        """GET from Rancher API. Returns parsed JSON or None on error."""
        import urllib.request, ssl
        rancher_url  = os.getenv('RANCHER_URL', '').rstrip('/')
        rancher_token = os.getenv('RANCHER_BEARER_TOKEN', '')
        url = f"{rancher_url}{path}"
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode    = ssl.CERT_NONE
        req = urllib.request.Request(url, headers={'Authorization': f'Bearer {rancher_token}'})
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return json.loads(resp.read())
        except Exception as e:
            _plog(f"[Panner] Rancher GET {path} failed: {e}")
            return None

    def _load_clusters_async(self):
        """Background: discover all Rancher clusters, update cluster listbox."""
        data = self._rancher_get('/v3/clusters?limit=200')
        if not data:
            return
        discovered = {}
        for item in data.get('data', []):
            name = item.get('name', '')
            cid  = item.get('id', '')
            if name and cid:
                discovered[name] = cid

        # Build ordered list: pinned first, then sorted rest
        pinned  = [n for n in self._PINNED_CLUSTERS if n in discovered]
        others  = sorted(n for n in discovered if n not in self._PINNED_CLUSTERS)
        ordered = pinned + (['---'] if others else []) + others

        def update():
            self._cluster_id_map = discovered
            self.cluster_options = [n for n in ordered if n != '---']
            self.cluster_listbox.delete(0, tk.END)
            for name in ordered:
                if name == '---':
                    self.cluster_listbox.insert(tk.END, '─────────────────')
                    self.cluster_listbox.itemconfig(tk.END, fg=BG3, selectbackground=BG3)
                else:
                    self.cluster_listbox.insert(tk.END, name)
        self.after(0, update)

    def _on_cluster_select(self, event=None):
        """Cluster clicked — load namespaces for selected cluster."""
        self._update_query_field()
        sel = self.cluster_listbox.curselection()
        if not sel:
            return
        name = self.cluster_listbox.get(sel[0])
        # Ignore separators and placeholder
        if name.startswith('─') or name in ('Loading…',):
            self.cluster_listbox.selection_clear(0, tk.END)
            return
        cluster_id = self._cluster_id_map.get(name) or self._resolve_cluster_id(name)
        if not cluster_id or not self._dynamic_enabled:
            return
        # Clear dependent selectors
        self._set_listbox(self.namespace_listbox, ['Loading…'])
        self._set_listbox(self.service_listbox, [])
        self._hide_pod_picker()
        threading.Thread(target=self._load_namespaces_async,
                         args=(cluster_id,), daemon=True).start()

    def _load_namespaces_async(self, cluster_id):
        """Background: load namespaces for cluster, populate listbox."""
        if cluster_id in self._rancher_ns_cache:
            namespaces = self._rancher_ns_cache[cluster_id]
        else:
            data = self._rancher_get(f'/k8s/clusters/{cluster_id}/api/v1/namespaces')
            if not data:
                self.after(0, lambda: self._set_listbox(
                    self.namespace_listbox, self.namespace_options))
                return
            namespaces = sorted(
                item['metadata']['name'] for item in data.get('items', [])
            )
            self._rancher_ns_cache[cluster_id] = namespaces
        self.after(0, lambda: self._set_listbox(self.namespace_listbox, namespaces))

    def _on_namespace_select(self, event=None):
        """Namespace clicked — load services (pod name prefixes) for cluster+namespace."""
        self._update_query_field()
        ns_sel = self.namespace_listbox.curselection()
        cl_sel = self.cluster_listbox.curselection()
        if not ns_sel:
            return
        namespace  = self.namespace_listbox.get(ns_sel[0])
        cluster_name = self.cluster_listbox.get(cl_sel[0]) if cl_sel else None
        cluster_id = (self._cluster_id_map.get(cluster_name)
                      or self._resolve_cluster_id(cluster_name or '')) if cluster_name else None
        if not cluster_id or not self._dynamic_enabled:
            return
        self._set_listbox(self.service_listbox, ['Loading…'])
        self._hide_pod_picker()
        threading.Thread(target=self._load_services_async,
                         args=(cluster_id, namespace), daemon=True).start()

    def _load_services_async(self, cluster_id, namespace):
        """Background: derive service names from pod names, populate service listbox."""
        import re as _re
        key = (cluster_id, namespace)
        if key in self._rancher_svc_cache:
            services = self._rancher_svc_cache[key]
        else:
            data = self._rancher_get(
                f'/k8s/clusters/{cluster_id}/api/v1/namespaces/{namespace}/pods')
            if not data:
                self.after(0, lambda: self._set_listbox(
                    self.service_listbox, self.all_service_options))
                return
            # Strip replica-set hash suffixes: name-<rs>-<pod> or name-<pod>
            svc_set = set()
            for pod in data.get('items', []):
                name = pod['metadata']['name']
                # Remove trailing -{5alphanum}-{5alphanum} or -{10alphanum}
                stripped = _re.sub(r'-[a-z0-9]{5,10}-[a-z0-9]{5}$', '', name)
                stripped = _re.sub(r'-[a-z0-9]{8,12}$', '', stripped)
                svc_set.add(stripped)
            services = sorted(svc_set)
            self._rancher_svc_cache[key] = services
        self.after(0, lambda: self._set_listbox(self.service_listbox, services))

    def _on_service_select(self, event=None):
        """Service clicked — load running pods for pod picker combobox."""
        self._update_query_field()
        svc_sel = self.service_listbox.curselection()
        ns_sel  = self.namespace_listbox.curselection()
        cl_sel  = self.cluster_listbox.curselection()
        if not svc_sel:
            self._hide_pod_picker()
            return
        service   = self.service_listbox.get(svc_sel[0])
        namespace = self.namespace_listbox.get(ns_sel[0]) if ns_sel else None
        cluster_name = self.cluster_listbox.get(cl_sel[0]) if cl_sel else None
        cluster_id = (self._cluster_id_map.get(cluster_name)
                      or self._resolve_cluster_id(cluster_name or '')) if cluster_name else None
        if not cluster_id or not namespace or not self._dynamic_enabled:
            self._hide_pod_picker()
            return
        threading.Thread(target=self._load_pods_async,
                         args=(cluster_id, namespace, service), daemon=True).start()

    def _load_pods_async(self, cluster_id, namespace, service):
        """Background: fetch running pods for service, update pod combobox."""
        import time as _time, re as _re
        key = (cluster_id, namespace, service)
        now = _time.time()
        # Cache with 30s TTL
        if key in self._rancher_pod_cache and now - self._pod_cache_time.get(key, 0) < 30:
            pods = self._rancher_pod_cache[key]
        else:
            data = self._rancher_get(
                f'/k8s/clusters/{cluster_id}/api/v1/namespaces/{namespace}/pods')
            if not data:
                self.after(0, self._hide_pod_picker)
                return
            pods = []
            for pod in data.get('items', []):
                name  = pod['metadata']['name']
                phase = pod['status'].get('phase', '')
                # Strip replica-set hash suffixes (same logic as _load_services_async)
                # so "assist2-services-abc12-def34" → "assist2-services" ≠ "assist2"
                stripped = _re.sub(r'-[a-z0-9]{5,10}-[a-z0-9]{5}$', '', name)
                stripped = _re.sub(r'-[a-z0-9]{8,12}$', '', stripped)
                if phase != 'Running' or stripped != service:
                    continue
                # Age
                ctime = pod['metadata'].get('creationTimestamp', '')
                try:
                    from datetime import datetime, timezone
                    created = datetime.fromisoformat(ctime.replace('Z', '+00:00'))
                    age_secs = (datetime.now(timezone.utc) - created).total_seconds()
                    age_str = (f"{int(age_secs//3600)}h" if age_secs >= 3600
                               else f"{int(age_secs//60)}m")
                except Exception:
                    age_str = '?'
                # Restarts
                restarts = sum(
                    cs.get('restartCount', 0)
                    for cs in pod['status'].get('containerStatuses', [])
                )
                # Primary container
                container = next(
                    (cs['name'] for cs in pod['status'].get('containerStatuses', [])
                     if cs.get('ready') and 'istio' not in cs['name']),
                    pod['spec']['containers'][0]['name'] if pod['spec'].get('containers') else 'app'
                )
                label = f"{name}  [{age_str}, {restarts}r]"
                pods.append((label, name, container))
            self._rancher_pod_cache[key] = pods
            self._pod_cache_time[key] = now

        def update():
            if not pods:
                self._hide_pod_picker()
                return
            self._pod_detail_map = {p[0]: (p[1], p[2]) for p in pods}
            if len(pods) > 1:
                all_label = f"All Pods ({len(pods)} running)"
                self._pod_detail_map[all_label] = '__all__'
                labels = [all_label] + [p[0] for p in pods]
            else:
                labels = [p[0] for p in pods]
            self._all_pod_items = list(labels)
            if hasattr(self, '_pod_filter_var'):
                self._pod_filter_var.set('')
            self.pod_listbox.delete(0, tk.END)
            for lbl in labels:
                self.pod_listbox.insert(tk.END, lbl)
            self.pod_listbox.selection_set(0)   # default to first
        self.after(0, update)

    def _hide_pod_picker(self):
        """Clear the pod listbox when no service is selected."""
        if hasattr(self, 'pod_listbox'):
            self.pod_listbox.delete(0, tk.END)
        self._pod_detail_map = {}
        self._all_pod_items = []
        if hasattr(self, '_pod_filter_var'):
            self._pod_filter_var.set('')

    def _set_listbox(self, listbox, items):
        """Replace listbox contents with items list."""
        listbox.delete(0, tk.END)
        for item in items:
            listbox.insert(tk.END, item)
        # Track full item lists for namespace/service filter
        if hasattr(self, 'cluster_listbox') and listbox is self.cluster_listbox:
            self._all_cl_items = list(items)
            if hasattr(self, '_cl_filter_var'):
                self._cl_filter_var.set('')
        elif hasattr(self, 'namespace_listbox') and listbox is self.namespace_listbox:
            self._all_ns_items = list(items)
            if hasattr(self, '_ns_filter_var'):
                self._ns_filter_var.set('')
        elif hasattr(self, 'service_listbox') and listbox is self.service_listbox:
            self._all_svc_items = list(items)
            if hasattr(self, '_svc_filter_var'):
                self._svc_filter_var.set('')

    def _filter_cl_list(self):
        """Filter cluster listbox by quick-filter entry."""
        q = self._cl_filter_var.get().lower().strip()
        items = self._all_cl_items if hasattr(self, '_all_cl_items') else []
        filtered = [i for i in items if q in i.lower()] if q else items
        self.cluster_listbox.delete(0, tk.END)
        for item in filtered:
            self.cluster_listbox.insert(tk.END, item)

    def _filter_ns_list(self):
        """Filter namespace listbox by quick-filter entry."""
        q = self._ns_filter_var.get().lower().strip()
        items = self._all_ns_items if hasattr(self, '_all_ns_items') else []
        filtered = [i for i in items if q in i.lower()] if q else items
        self.namespace_listbox.delete(0, tk.END)
        for item in filtered:
            self.namespace_listbox.insert(tk.END, item)

    def _filter_svc_list(self):
        """Filter service listbox by quick-filter entry."""
        q = self._svc_filter_var.get().lower().strip()
        items = self._all_svc_items if hasattr(self, '_all_svc_items') else []
        filtered = [i for i in items if q in i.lower()] if q else items
        self.service_listbox.delete(0, tk.END)
        for item in filtered:
            self.service_listbox.insert(tk.END, item)

    def _filter_pod_list(self):
        """Filter pod listbox by quick-filter entry."""
        q = self._pod_filter_var.get().lower().strip()
        items = self._all_pod_items if hasattr(self, '_all_pod_items') else []
        filtered = [i for i in items if q in i.lower()] if q else items
        self.pod_listbox.delete(0, tk.END)
        for item in filtered:
            self.pod_listbox.insert(tk.END, item)

    def _on_pod_select(self, event=None):
        """Pod listbox clicked — update query field."""
        self._update_query_field()

    def _resolve_cluster_id(self, cluster_name):
        """Fallback: map DataDog-style cluster display name to Rancher cluster ID."""
        key = cluster_name.lower()
        for k in sorted(self._RANCHER_CLUSTERS, key=len, reverse=True):
            if k in key:
                return self._RANCHER_CLUSTERS[k]
        return None
    
    def _display_log_details(self, event):
        """Display complete JSON for selected log entry in the details panel."""
        selected = self.table.selection()
        if not selected:
            return
        iid = selected[0]
        record = self._iid_to_record.get(iid)
        if record is None:
            return
        # For kubectl flat records, reconstruct a clean JSON from raw fields
        if 'kube_namespace' in record:
            raw_msg = record.get('message', '')
            try:
                if raw_msg and raw_msg.startswith('{'):
                    detail_obj = json.loads(raw_msg)
                else:
                    detail_obj = {
                        'timestamp': record.get('timestamp', ''),
                        'pod':       record.get('service', ''),
                        'container': record.get('container_name', ''),
                        'namespace': record.get('kube_namespace', ''),
                        'message':   raw_msg,
                    }
            except Exception:
                detail_obj = record
            json_string = json.dumps(detail_obj, indent=2, default=str)
        else:
            json_string = json.dumps(record, indent=2, default=str)

        self.details_text.delete("1.0", tk.END)
        self.details_text.insert("1.0", json_string)

        # Highlight the active search term throughout the details panel
        term = self._search_var.get().strip() if hasattr(self, '_search_var') else ''
        if term:
            self.details_text.tag_remove('search_highlight', '1.0', tk.END)
            start = '1.0'
            term_lower = term.lower()
            content_lower = json_string.lower()
            idx = 0
            while True:
                pos = content_lower.find(term_lower, idx)
                if pos == -1:
                    break
                # Convert char offset to Tk text index
                line_no = json_string[:pos].count('\n') + 1
                col_no  = pos - json_string[:pos].rfind('\n') - 1
                end_col = col_no + len(term)
                t_start = f"{line_no}.{col_no}"
                t_end   = f"{line_no}.{end_col}"
                self.details_text.tag_add('search_highlight', t_start, t_end)
                idx = pos + len(term)
            # Scroll to first highlight
            try:
                first = self.details_text.tag_ranges('search_highlight')
                if first:
                    self.details_text.see(first[0])
            except Exception:
                pass
    
    def _clear_results(self):
        """Clear results table and details"""
        for item in self.table.get_children():
            self.table.delete(item)
        self.details_text.delete("1.0", tk.END)
        self.log_data = []
        self._iid_to_record = {}
        self._all_rows = []
        self.count_var.set("")
        self.status_var.set("Results cleared")
        if hasattr(self, '_match_count_var'):
            self._match_count_var.set("")
    
    def _open_in_datadog(self):
        """Open DataDog logs/pods view in browser based on current selections"""
        # Get selected values from listboxes
        selected_clusters = [self.cluster_options[i] for i in self.cluster_listbox.curselection()]
        selected_namespaces = [self.namespace_options[i] for i in self.namespace_listbox.curselection()]
        selected_services = [self.all_service_options[i] for i in self.service_listbox.curselection()]
        
        # Convert time range to timestamps if needed
        from_ts = self._convert_minutes_to_timestamp(self.from_entry.get())
        to_ts = self._convert_minutes_to_timestamp(self.to_entry.get())
        
        live = self.live_tail_var.get()
        
        # Launch logs if checked
        if self.launch_logs_var.get():
            url = self._build_datadog_url(
                "logs",
                selected_clusters,
                selected_namespaces,
                selected_services,
                from_ts,
                to_ts,
                live
            )
            self._open_url(url)
            self.status_var.set("✓ Opened DataDog Logs in browser")
        
        # Launch pods if checked
        if self.launch_pods_var.get():
            url = self._build_datadog_url(
                "pods",
                selected_clusters,
                selected_namespaces,
                selected_services,
                from_ts,
                to_ts,
                live
            )
            self._open_url(url)
            self.status_var.set("✓ Opened DataDog Pods in browser")
        
        if not self.launch_logs_var.get() and not self.launch_pods_var.get():
            messagebox.showwarning("No Selection", "Please check 'Launch Logs' or 'Launch Pods'")
    
    def _convert_minutes_to_timestamp(self, minutes_str):
        """Convert minutes ago to Unix timestamp in milliseconds"""
        if not minutes_str:
            return None
        
        try:
            minutes_ago = int(minutes_str)
            dt = datetime.datetime.now() - datetime.timedelta(minutes=minutes_ago)
            timestamp_seconds = dt.timestamp()
            return int(timestamp_seconds * 1000)
        except ValueError:
            return None
    
    def _build_datadog_url(self, view_type, clusters, namespaces, services, from_ts, to_ts, live):
        """Build DataDog URL with query parameters"""
        if view_type == "logs":
            base_url = "https://fcs-mcaas-assist.ddog-gov.com/logs"
            service_param = "service"
        elif view_type == "pods":
            base_url = "https://fcs-mcaas-assist.ddog-gov.com/orchestration/explorer/pod"
            service_param = "kube_service"
        else:
            return ""
        
        # Build query string
        query_parts = []
        
        if clusters:
            if len(clusters) == 1:
                query_parts.append(f"kube_cluster_name:{clusters[0]}")
            else:
                query_parts.append(f"kube_cluster_name:({' OR '.join(clusters)})")
        
        if namespaces:
            if len(namespaces) == 1:
                query_parts.append(f"kube_namespace:{namespaces[0]}")
            else:
                query_parts.append(f"kube_namespace:({' OR '.join(namespaces)})")
        
        if services:
            if len(services) == 1:
                query_parts.append(f"{service_param}:{services[0]}")
            else:
                query_parts.append(f"{service_param}:({' OR '.join(services)})")
        
        query = " ".join(query_parts)
        
        # Build URL parameters
        params = {}
        if query:
            params["query"] = query
        if from_ts:
            params["from_ts"] = from_ts
        if to_ts:
            params["to_ts"] = to_ts
        params["live"] = str(live).lower()
        
        # Construct final URL
        url = base_url
        if params:
            url += "?" + urllib.parse.urlencode(params)
        
        return url
    
    def _open_url(self, url):
        """Open URL in host browser via Host Tools Daemon."""
        try:
            from auger.tools.host_cmd import open_url as host_open_url
            result = host_open_url(url)
            if result.get("status") == "ok":
                return
        except Exception:
            pass

        # Fallback: copyable dialog
        dialog = tk.Toplevel(self)
        dialog.title("Open in Browser")
        dialog.configure(bg=BG)
        dialog.geometry("700x120")
        tk.Label(dialog, text="Copy this URL and open in your host browser:",
                 font=('Segoe UI', 10), fg=FG, bg=BG).pack(padx=10, pady=(10, 4))
        url_var = tk.StringVar(value=url)
        entry = tk.Entry(dialog, textvariable=url_var, font=('Segoe UI', 9),
                         bg=BG3, fg=ACCENT2, width=90)
        entry.pack(padx=10, pady=4, fill=tk.X)
        entry.select_range(0, tk.END)
        entry.focus_set()
        def copy_and_close():
            dialog.clipboard_clear()
            dialog.clipboard_append(url)
            dialog.destroy()
        tk.Button(dialog, text=" Copy & Close",
                  image=self._icons.get('copy'), compound=tk.LEFT,
                  command=copy_and_close,
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=10).pack(pady=4)
    
    def _install_dependencies(self):
        """Install node dependencies"""
        self.status_var.set("Installing dependencies...")
        threading.Thread(target=self._install_dependencies_thread, daemon=True).start()
    
    def _install_dependencies_thread(self):
        """Install dependencies in background"""
        try:
            original_dir = os.getcwd()
            os.chdir(self.widget_dir)  # install into the repo widgets dir
            
            process = subprocess.Popen(
                ["npm", "install", "--verbose", "--strict-ssl=false"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate()
            
            os.chdir(original_dir)
            
            if process.returncode == 0:
                self.node_dir = self.widget_dir  # now has node_modules
                self.after(0, lambda: self.status_var.set("✓ Dependencies installed successfully"))
                self.after(0, lambda: messagebox.showinfo("Success", "Node dependencies installed!"))
            else:
                self.after(0, lambda: self.status_var.set("✗ Dependency installation failed"))
                self.after(0, lambda s=stderr: self._show_error("npm install failed", s))
        
        except Exception as e:
            self.after(0, lambda: self.status_var.set(f"✗ Error: {str(e)}"))
            self.after(0, lambda s=str(e): self._show_error("Install Error", s))
    
    def download_logs(self):
        """Download/stream logs — auto-routes to kubectl (live pod) or DataDog (fallback)."""
        query = self.query_var.get().strip()
        if not query:
            messagebox.showwarning("No Query", "Please enter a query or select filters")
            return

        # Cancel any existing poll loop
        if self._poll_after_id:
            self.after_cancel(self._poll_after_id)
            self._poll_after_id = None

        # Capture all UI state here on the main thread (Tkinter is NOT thread-safe)
        ns_indices  = self.namespace_listbox.curselection()
        svc_indices = self.service_listbox.curselection()
        cl_indices  = self.cluster_listbox.curselection()
        cluster_name = self.cluster_listbox.get(cl_sel := cl_indices[0]) if cl_indices else None
        namespace    = self.namespace_listbox.get(ns_indices[0])  if ns_indices  else None
        service      = self.service_listbox.get(svc_indices[0])   if svc_indices else None

        # If pod listbox has a selection, use its pre-resolved pod info
        pod_detail_map = getattr(self, '_pod_detail_map', {})
        pod_sel = self.pod_listbox.curselection() if hasattr(self, 'pod_listbox') else ()
        pod_label = self.pod_listbox.get(pod_sel[0]) if pod_sel else ''
        raw_selection = pod_detail_map.get(pod_label)  # (pod_name, container), '__all__', or None

        if raw_selection == '__all__':
            # User chose "All Pods" — pass full list of (pod_name, container) tuples
            all_pods = [v for v in pod_detail_map.values() if isinstance(v, tuple)]
            selected_pod = None
            selected_all_pods = all_pods
        else:
            selected_pod = raw_selection          # (pod_name, container) or None
            selected_all_pods = None

        cluster_id = (self._cluster_id_map.get(cluster_name)
                      or self._resolve_cluster_id(cluster_name or '')) if cluster_name else None

        ui_state = {
            'namespace':        namespace,
            'service':          service,
            'cluster':          cluster_name,
            'cluster_id':       cluster_id,
            'from_val':         self.from_entry.get().strip(),
            'selected_pod':     selected_pod,       # (pod_name, container) — single explicit pick
            'selected_all_pods': selected_all_pods, # [(pod_name, container), ...] — stream all
        }

        # Clear table and prepare shared state
        self._clear_results()
        self._streaming = True
        self._stream_count = 0
        self._do_live_after_drain = False
        self._row_queue = queue.Queue()
        self._kubectl_processes = []
        self._autoscroll = self._autoscroll_var.get()
        self._user_scrolled = False   # reset — start at bottom
        self.status_var.set("⏳ Checking for live pod…")
        self._source_var.set("")
        self._show_stop_btn()
        self._start_drain_loop(insert_top=False)

        # Route decision happens in background to avoid blocking UI during Rancher check
        threading.Thread(target=self._route_and_stream, args=(ui_state,), daemon=True).start()

    def _route_and_stream(self, ui_state):
        """Background: check for live pod(s), then stream kubectl or DataDog."""
        try:
            pod_info = self._find_kubectl_pod(ui_state)
        except Exception as e:
            pod_info = None
            _plog(f"[Panner] _find_kubectl_pod error: {e}")

        if pod_info:
            # Normalise to always a list so we can handle 1 or N pods uniformly
            pod_list = pod_info if isinstance(pod_info, list) else [pod_info]
            n = len(pod_list)
            service = ui_state.get('service', '')
            self._kubectl_pod = pod_list[0]
            self._log_source = 'kubectl'

            pod_names = ', '.join(p[2] for p in pod_list)
            self.after(0, lambda: self._source_var.set(
                f"[LIVE kubectl × {n}]" if n > 1 else "[LIVE kubectl]"))
            self.after(0, lambda: self._source_label.config(fg=SUCCESS))
            self.after(0, lambda: self.status_var.set(
                f"🟢 kubectl → {pod_names}"))

            # Per-pod tint colors for visual distinction (cycles if >4 pods)
            _POD_TINTS = ['pod0', 'pod1', 'pod2', 'pod3']
            _POD_COLORS = ['#1a2a1a', '#1a1a2a', '#2a1a1a', '#1a2a2a']

            # Use a thread-safe counter: each thread puts one None sentinel when done.
            # The drain loop already handles None by finalizing — so we need a wrapper
            # that only puts None after ALL threads are done.
            import threading as _threading
            _done_count = [0]
            _done_lock  = _threading.Lock()

            def stream_pod(pod_tuple, tint_tag):
                cid, ns, pname, ctr = pod_tuple
                try:
                    self._kubectl_stream_thread(cid, ns, pname, ctr, ui_state,
                                                row_tag=tint_tag)
                except Exception as e:
                    _plog(f"[Panner] stream_pod exception {pname}: {e}")
                finally:
                    with _done_lock:
                        _done_count[0] += 1
                        _plog(f"[Panner] stream_pod finally {pname}: done={_done_count[0]}/{n} _streaming={self._streaming}")
                        if _done_count[0] == n:
                            _plog(f"[Panner] stream_pod: all {n} threads done — putting None sentinel")
                            self._row_queue.put(None)

            for i, pt in enumerate(pod_list):
                tag = _POD_TINTS[i % len(_POD_TINTS)]
                t = threading.Thread(target=stream_pod, args=(pt, tag), daemon=True)
                t.start()
        else:
            # No live pod — fall back to DataDog (historical, ~30s lag)
            ns  = ui_state.get('namespace') or '(none)'
            svc = ui_state.get('service') or '(none)'
            clu = ui_state.get('cluster') or '(none)'
            dd_api_key = os.getenv('DATADOG_API_KEY')
            dd_app_key = os.getenv('DATADOG_APP_KEY')
            if not dd_api_key or not dd_app_key:
                self._streaming = False
                self.after(0, self._show_download_btn)
                self.after(0, lambda: self._source_var.set(""))
                self.after(0, lambda: messagebox.showerror(
                    "No Live Pod + No DataDog Credentials",
                    f"No running pod found for {svc} in {ns} ({clu}).\n\n"
                    "DataDog fallback is also unavailable — API Key / App Key not configured.\n\n"
                    "Configure in API Config widget:\n  DATADOG_API_KEY\n  DATADOG_APP_KEY"
                ))
                return
            self._log_source = 'datadog'
            self.after(0, lambda: self._source_var.set("[DataDog ⚠ ~30s lag]"))
            self.after(0, lambda: self._source_label.config(fg=WARNING))
            self.after(0, lambda: self.status_var.set(
                f"⚠ No live pod for {svc} — fetching from DataDog API (~30s delay)…"))
            try:
                self._stream_logs_thread()
            except Exception as e:
                _plog(f"[Panner] _stream_logs_thread error: {e}")
                self.after(0, lambda: self.status_var.set(f"✗ Stream error: {e}"))
                self._row_queue.put(None)
                self._finalize_stream()

    # ------------------------------------------------------------------ #
    #  Rancher kubectl pod discovery                                       #
    # ------------------------------------------------------------------ #

    # Map DataDog cluster names → Rancher cluster IDs
    _RANCHER_CLUSTERS = {
        'dev':        'c-m-qpv8hf6m',
        'staging':    'c-xkd99',
        'production': 'c-2bsb4',
        'prod':        'c-2bsb4',
    }

    def _find_kubectl_pod(self, ui_state):
        """
        Check Rancher API for Running pods matching selected namespace+service.
        Returns:
          - list of (cluster_id, namespace, pod_name, container) when streaming all pods
          - single (cluster_id, namespace, pod_name, container) tuple for one pod
          - None if no live pod found
        ui_state dict is pre-captured on main thread (thread-safety).
        """
        rancher_url   = os.getenv('RANCHER_URL', '').rstrip('/')
        rancher_token = os.getenv('RANCHER_BEARER_TOKEN', '')
        if not rancher_url or not rancher_token:
            return None

        namespace  = ui_state.get('namespace')
        service    = ui_state.get('service')
        cluster_id = ui_state.get('cluster_id')

        if not namespace or not service:
            return None

        # "All Pods" selected — stream all pods from combobox list
        all_pods = ui_state.get('selected_all_pods')
        if all_pods and cluster_id:
            return [(cluster_id, namespace, pod_name, container)
                    for pod_name, container in all_pods]

        # Single pod explicitly chosen from combobox
        selected_pod = ui_state.get('selected_pod')
        if selected_pod and cluster_id:
            pod_name, container = selected_pod
            return (cluster_id, namespace, pod_name, container)

        # Resolve cluster_id if not already done
        if not cluster_id:
            cluster_id = self._resolve_cluster_id(ui_state.get('cluster') or 'dev')
        if not cluster_id:
            return None

        # Query Rancher for running pods in namespace matching service
        data = self._rancher_get(
            f'/k8s/clusters/{cluster_id}/api/v1/namespaces/{namespace}/pods')
        if not data:
            return None

        # Find most-recently-created Running pod whose name contains service name
        best = None
        best_time = ''
        for pod in data.get('items', []):
            name   = pod['metadata']['name']
            phase  = pod['status'].get('phase', '')
            ctime  = pod['metadata'].get('creationTimestamp', '')
            if phase != 'Running' or service not in name:
                continue
            if ctime > best_time:
                best_time = ctime
                container = None
                for cs in pod['status'].get('containerStatuses', []):
                    if cs.get('ready') and 'istio' not in cs['name']:
                        container = cs['name']
                        break
                if not container:
                    specs = pod['spec'].get('containers', [])
                    container = specs[0]['name'] if specs else 'python'
                best = (cluster_id, namespace, name, container)

        return best

    # ------------------------------------------------------------------ #
    #  kubectl log streaming via Rancher websocket                        #
    # ------------------------------------------------------------------ #

    def _kubectl_stream_thread(self, cluster_id, namespace, pod_name, container,
                               ui_state=None, row_tag=None):
        """Stream pod logs via curl → Rancher k8s API.

        Uses curl instead of urllib to handle long-lived chunked HTTPS connections
        reliably.  Reconnects automatically on any connection drop until
        self._streaming is set False (user pressed Stop).
        """
        import subprocess, time

        rancher_url   = os.getenv('RANCHER_URL', '').rstrip('/')
        rancher_token = os.getenv('RANCHER_BEARER_TOKEN', '')

        # Short pod label: last two hash segments for display
        pod_short = (pod_name.split('-')[-2] + '-' + pod_name.split('-')[-1]
                     if pod_name.count('-') >= 2 else pod_name)
        pod_col = f"{pod_short}/{container}"

        from_val = (ui_state or {}).get('from_val') or '30'
        since_seconds = None
        try:
            since_seconds = int(from_val) * 60
        except ValueError:
            pass

        rows_total    = 0
        last_ts_raw   = ''
        reconnect_num = 0

        def _status(msg):
            try:
                self.after(0, lambda m=msg: self.status_var.set(m))
            except Exception:
                pass

        while self._streaming:
            params = f"container={container}&follow=true&timestamps=true"
            if since_seconds is not None:
                params += f"&sinceSeconds={since_seconds}"

            url = (f"{rancher_url}/k8s/clusters/{cluster_id}"
                   f"/api/v1/namespaces/{namespace}/pods/{pod_name}/log?{params}")

            cmd = [
                'curl', '-s', '-k', '-N',   # silent, insecure (self-signed), no buffering
                '--http1.1',                # force HTTP/1.1 — avoids HTTP/2 stream resets (exit 92)
                '--max-time', '0',          # no overall timeout
                '--connect-timeout', '15',  # 15s connect timeout
                '-H', f'Authorization: Bearer {rancher_token}',
                url
            ]

            if reconnect_num == 0:
                _status(f"🟢 [LIVE kubectl] Connecting to {pod_short}…")
            else:
                _status(f"🟢 [LIVE kubectl] Reconnect #{reconnect_num} → {pod_short}…")

            proc = None
            rows_this_conn = 0
            curl_exit = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self._kubectl_processes.append(proc)

                _status(f"🟢 [LIVE kubectl] {pod_short} — streaming…")

                for raw_bytes in proc.stdout:
                    if not self._streaming:
                        break
                    raw = raw_bytes.decode('utf-8', errors='replace').rstrip('\n').rstrip('\r')
                    if not raw:
                        continue

                    ts, _, msg = raw.partition(' ')

                    # Skip duplicates on reconnect (overlap window)
                    if reconnect_num > 0 and ts and ts <= last_ts_raw:
                        continue
                    if ts:
                        last_ts_raw = ts

                    record = {
                        'cluster_name':   (ui_state or {}).get('cluster') or cluster_id,
                        'kube_namespace':  namespace,
                        'service':        (ui_state or {}).get('service') or pod_name,
                        'container_name':  pod_col,
                        'status':         'info',
                        'timestamp':      self._fmt_timestamp(ts),
                        'message':        msg,
                        '_raw':           raw,
                        '_pod':           pod_name,
                        '_row_tag':       row_tag,
                    }
                    self._row_queue.put(record)
                    rows_this_conn += 1
                    rows_total     += 1
                    if rows_total % 50 == 0:
                        n = rows_total
                        _status(f"🟢 [LIVE kubectl] {pod_short} — {n} rows")

            except Exception as e:
                if self._streaming:
                    _plog(f"[Panner] curl stream error ({pod_name}): {e}")
            finally:
                if proc is not None:
                    try:
                        proc.terminate()
                        proc.wait(timeout=2)
                    except Exception:
                        pass
                    curl_exit = proc.returncode
                    # Log curl stderr + exit code for diagnostics
                    try:
                        curl_err = (proc.stderr.read() or b'').decode('utf-8', errors='replace').strip()
                        _plog(f"[Panner] curl exit={curl_exit} rows={rows_this_conn} pod={pod_short} _streaming={self._streaming} stderr={curl_err[:100]!r}")
                    except Exception as log_e:
                        _plog(f"[Panner] curl exit={curl_exit} rows={rows_this_conn} pod={pod_short} _streaming={self._streaming} (log err: {log_e})")
                    try:
                        self._kubectl_processes.remove(proc)
                    except ValueError:
                        pass

            if not self._streaming:
                _plog(f"[Panner] {pod_short}: _streaming=False after curl exit={curl_exit}, breaking reconnect loop")
                break

            if rows_this_conn == 0:
                _status(f"🟢 [LIVE kubectl] {pod_short} — quiet (no new logs), reconnecting…")
            else:
                _status(f"🟢 [LIVE kubectl] {pod_short} — {rows_this_conn} rows, reconnecting…")
            time.sleep(1)
            reconnect_num += 1
            since_seconds = 60   # overlap; dedup via last_ts_raw above

        # Single-pod path (no row_tag): signal drain loop directly
        if not row_tag:
            self._row_queue.put(None)
            self._finalize_stream()
        # Multi-pod: stream_pod wrapper handles the countdown sentinel

    def _build_node_command(self, from_time=None, to_time=None, output_path=None):
        """Build the node index.mjs command list."""
        query = self.query_var.get()
        index = self.index_entry.get()
        from_arg = from_time or self.from_entry.get()
        to_arg   = to_time   or self.to_entry.get()
        page_size = self.page_size_entry.get()

        # NODE_PATH in _make_env() points node_modules to the baked location,
        # so we can run widget_dir/index.mjs directly (editable, hot-reloadable).
        index_mjs = str(self.widget_dir / "index.mjs")
        command = [
            "node", index_mjs,
            "--query", query,
            "--index", index,
            "--pageSize", page_size,
            "--format", "ndjson",
        ]
        if output_path:
            command.extend(["--output", str(output_path)])
        if from_arg:
            command.extend(["--from", from_arg])
        if to_arg:
            command.extend(["--to", to_arg])
        command.extend(["--sort", "asc"])
        return command

    def _make_env(self):
        env = os.environ.copy()
        env['DD_API_KEY'] = os.getenv('DATADOG_API_KEY', '')
        env['DD_APP_KEY'] = os.getenv('DATADOG_APP_KEY', '')
        env['DD_SITE']    = os.getenv('DATADOG_SITE', 'ddog-gov.com')
        return env

    def _stream_logs_thread(self, from_time=None, to_time=None, append=False):
        """Run index.mjs writing NDJSON to a temp file; tail that file live."""
        import time

        output_dir = _auger_home() / '.auger' / 'panner'
        output_dir.mkdir(parents=True, exist_ok=True)
        stream_file = output_dir / 'stream.ndjson'
        debug_log  = output_dir / 'debug.log'

        def dbg(msg):
            with open(debug_log, 'a') as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")

        dbg(f"--- NEW RUN streaming={self._streaming} ---")

        # Clear the file so we don't read stale rows
        stream_file.write_text('')

        stderr_lines = []

        def _read_stderr(proc):
            for line in proc.stderr:
                stderr_lines.append(line)

        try:
            command = self._build_node_command(
                from_time=from_time, to_time=to_time, output_path=stream_file)
            dbg(f"command: {' '.join(str(c) for c in command[:6])}")
            self._stream_process = subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,  # we read via file; avoid pipe buffer deadlock
                stderr=subprocess.PIPE,
                text=True,
                env=self._make_env(),
                cwd=str(self.widget_dir)  # node_modules symlink now points to baked location
            )
            dbg(f"node PID: {self._stream_process.pid}")
            # Drain stderr in background so it never blocks the process
            import threading as _threading
            _threading.Thread(target=_read_stderr, args=(self._stream_process,), daemon=True).start()
        except FileNotFoundError as e:
            dbg(f"FileNotFoundError: {e}")
            self.after(0, lambda: self.status_var.set("✗ Node.js not found"))
            self.after(0, lambda: self._show_error(
                "Node.js not found",
                "Node.js not found. Install Node.js or click 'Install Dependencies' in the Panner widget."))
            self._finalize_stream()
            return

        # Tail stream_file as the ndjson writer fills it
        rows_queued = 0
        try:
            with open(stream_file, 'r') as fh:
                while True:
                    if not self._streaming:
                        dbg(f"_streaming=False, stopping. rows_queued={rows_queued}")
                        try:
                            self._stream_process.terminate()
                        except Exception:
                            pass
                        break

                    line = fh.readline()
                    if line:
                        line = line.rstrip('\n')
                        if line:
                            try:
                                obj = json.loads(line)
                                if not append:
                                    self.log_data.append(obj)
                                self._row_queue.put(obj)
                                rows_queued += 1
                            except json.JSONDecodeError:
                                pass
                    else:
                        # No new data yet — check if node is done
                        if self._stream_process.poll() is not None:
                            dbg(f"node exited. rows_queued={rows_queued}")
                            break
                        time.sleep(0.05)  # 50ms poll

            dbg(f"readline loop done. rows_queued={rows_queued}")

        except Exception as e:
            dbg(f"Exception in readline loop: {e}")
            err = str(e)
            self.after(0, lambda: self.status_var.set(f"✗ Error: {err}"))

        # Show stderr if no rows came through (indicates a JS/node error)
        self._stream_process.wait()
        if self._row_queue.empty() and self._stream_count == 0 and stderr_lines:
            stderr_text = ''.join(stderr_lines)
            dbg(f"STDERR: {stderr_text[:200]}")
            self.after(0, lambda s=stderr_text: self._show_error("DataDog Error", s))

        dbg(f"putting None sentinel. rows_queued={rows_queued}")
        self._row_queue.put(None)  # sentinel so drain loop stops rescheduling
        self._finalize_stream()

    def _finalize_stream(self):
        """Called from background thread when stream finishes. Drain loop handles UI."""
        import traceback, io
        _plog(f"[Panner] _finalize_stream called — setting _streaming=False")
        buf = io.StringIO()
        traceback.print_stack(file=buf, limit=6)
        _plog(buf.getvalue().strip())
        self._streaming = False
        self._stream_process = None
        # NOTE: do NOT touch tkinter vars here (background thread) —
        # drain loop reads live_tail_var on the main thread when it hits the sentinel

    def _stop_stream(self):
        """User pressed Stop — kill subprocess/connection and cancel re-poll."""
        _plog("[Panner] _stop_stream called by user")
        self._streaming = False
        if self._poll_after_id:
            self.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        if self._drain_after_id:
            self.after_cancel(self._drain_after_id)
            self._drain_after_id = None
        # Kill DataDog node process if running
        if self._stream_process:
            try:
                self._stream_process.terminate()
            except Exception:
                pass
        # Kill any active kubectl curl processes
        for proc in self._kubectl_processes:
            try:
                proc.terminate()
            except Exception:
                pass
        self._kubectl_processes = []
        self._kubectl_pod = None
        self.after(0, lambda: self.status_var.set(f"Stopped — {self._stream_count} rows"))
        self.after(0, lambda: self._source_var.set(""))
        self.after(0, self._show_download_btn)

    def _live_repoll(self):
        """Re-poll last 2 minutes for new rows (Live tail simulation)."""
        if not self.live_tail_var.get():
            return  # user unchecked Live — stop
        now = datetime.datetime.utcnow()
        t_from = (now - datetime.timedelta(minutes=2)).strftime('%Y-%m-%dT%H:%M:%SZ')
        t_to   = now.strftime('%Y-%m-%dT%H:%M:%SZ')
        self._streaming = True
        self._stream_process = None
        self._show_stop_btn()
        self._start_drain_loop(insert_top=True)
        self.status_var.set("🔴 Live re-poll…")
        threading.Thread(
            target=self._stream_logs_thread,
            kwargs={'from_time': t_from, 'to_time': t_to, 'append': True},
            daemon=True
        ).start()

    def _fmt_timestamp(self, raw):
        """Convert ISO 8601 UTC timestamp to ET (EDT/EST) using zoneinfo for accurate DST."""
        if raw == "N/A" or not raw:
            return raw
        try:
            import re as _re
            s = _re.sub(r'Z$', '+00:00', raw)
            if '.' in s:
                s = _re.sub(r'\.\d+', '', s)
            dt_utc = datetime.datetime.fromisoformat(s)
            try:
                from zoneinfo import ZoneInfo
                tz_et = ZoneInfo("America/New_York")
                dt_et = dt_utc.replace(tzinfo=datetime.timezone.utc).astimezone(tz_et)
                tz_label = dt_et.strftime("%Z")  # "EDT" or "EST" automatically
                return dt_et.strftime(f"%Y-%m-%d %H:%M:%S {tz_label}")
            except ImportError:
                # zoneinfo not available — fall back to manual offset
                # DST: second Sunday of March through first Sunday of November
                year  = dt_utc.year
                month = dt_utc.month
                day   = dt_utc.day
                # Second Sunday of March
                import calendar
                first_day = calendar.weekday(year, 3, 1)  # 0=Mon
                march_dst_start = (7 - first_day) % 7 + 8  # second Sunday
                # First Sunday of November
                first_day_nov = calendar.weekday(year, 11, 1)
                nov_dst_end = (6 - first_day_nov) % 7 + 1  # first Sunday
                is_edt = (
                    (month == 3  and day >= march_dst_start) or
                    (4 <= month <= 10) or
                    (month == 11 and day < nov_dst_end)
                )
                offset = datetime.timedelta(hours=-4 if is_edt else -5)
                dt_et = dt_utc + offset
                tz_label = "EDT" if is_edt else "EST"
                return dt_et.strftime(f"%Y-%m-%d %H:%M:%S {tz_label}")
        except Exception:
            return raw

    def _append_row(self, record, insert_top=False):
        """Append (or prepend) a single log row to the table (called from main thread)."""
        try:
            # kubectl rows are flat; DataDog rows use nested 'attributes'
            if 'kube_namespace' in record:
                cluster_name   = record.get('cluster_name',   'N/A')
                kube_namespace = record.get('kube_namespace',  'N/A')
                service        = record.get('service',         'N/A')
                container_name = record.get('container_name',  'N/A')
                status         = record.get('status',          'info')
                timestamp      = record.get('timestamp',       'N/A')
                raw_msg        = record.get('message',         'N/A')
                # If the log line is JSON, extract the 'message'/'msg' key for display
                display_msg = raw_msg
                if raw_msg and raw_msg.startswith('{'):
                    try:
                        parsed = json.loads(raw_msg)
                        display_msg = (parsed.get('message')
                                       or parsed.get('msg')
                                       or parsed.get('log')
                                       or raw_msg)
                    except (json.JSONDecodeError, AttributeError):
                        pass
            else:
                attributes = record.get("attributes", {})
                cluster_name = "N/A"
                kube_namespace = "N/A"
                container_name = "N/A"
                tags = attributes.get("tags", [])
                for tag in tags:
                    if "cluster_name:" in tag:
                        cluster_name = tag.split(":", 1)[1]
                    elif "kube_namespace:" in tag:
                        kube_namespace = tag.split(":", 1)[1]
                    elif "container_name:" in tag:
                        container_name = tag.split(":", 1)[1]
                service     = attributes.get("service",   "N/A")
                status      = attributes.get("status",    "N/A")
                timestamp   = self._fmt_timestamp(attributes.get("timestamp", "N/A"))
                display_msg = attributes.get("message",   "N/A")

            row_tags = ['error'] if status == "error" else []

            # Per-pod tint for kubectl multi-pod streaming
            pod_tint = record.get('_row_tag') if isinstance(record, dict) else None
            if pod_tint:
                row_tags.append(pod_tint)

            # Apply current search filter: if search is active and row doesn't match, skip display
            term = self._search_var.get().strip().lower() if hasattr(self, '_search_var') else ''
            values = (cluster_name, kube_namespace, service, container_name, status, timestamp, display_msg)
            hidden = bool(term and not any(term in str(v).lower() for v in values))
            if term and not hidden:
                row_tags.append('match')

            pos = 0 if insert_top else tk.END
            iid = self.table.insert("", pos, values=values,
                                    tags=row_tags if not hidden else ())
            if hidden:
                self.table.detach(iid)  # filtered out — keep in _all_rows but hide

            # Track for details panel and filter
            self._iid_to_record[iid] = record
            self._all_rows.insert(0 if insert_top else len(self._all_rows),
                                  (iid, values, tuple(row_tags)))

        except Exception as e:
            _plog(f"[Panner] _append_row error: {e}")

    def _download_logs_thread(self):
        """Legacy: now delegates to streaming thread (kept for compatibility)."""
        self._stream_logs_thread()
    
    def _populate_table(self, data):
        """Populate table with log data"""
        # Clear existing
        for item in self.table.get_children():
            self.table.delete(item)
        
        # Store data
        self.log_data = data
        
        # Populate
        for record in data:
            try:
                attributes = record.get("attributes", {})
                
                # Extract values
                cluster_name = "N/A"
                kube_namespace = "N/A"
                container_name = "N/A"
                
                # Parse tags
                tags = attributes.get("tags", [])
                for tag in tags:
                    if "cluster_name:" in tag:
                        cluster_name = tag.split(":", 1)[1]
                    elif "kube_namespace:" in tag:
                        kube_namespace = tag.split(":", 1)[1]
                    elif "container_name:" in tag:
                        container_name = tag.split(":", 1)[1]
                
                service = attributes.get("service", "N/A")
                status = attributes.get("status", "N/A")
                timestamp = self._fmt_timestamp(attributes.get("timestamp", "N/A"))
                message = attributes.get("message", "N/A")
                
                # Determine row style
                tag = ('error',) if status == "error" else ()
                
                # Insert row
                self.table.insert(
                    "", tk.END,
                    values=(cluster_name, kube_namespace, service, container_name, status, timestamp, message),
                    tags=tag
                )
            
            except Exception as e:
                print(f"Error processing record: {e}")
                continue
    
    def build_context(self):
        """Build context for Ask Auger panel"""
        context = "PANNER WIDGET CONTEXT (DataDog Log Downloader)\n\n"
        
        query = self.query_var.get()
        if query:
            context += f"Current Query: {query}\n\n"
        
        if self.log_data:
            context += f"Log Results: {len(self.log_data)} entries loaded\n\n"
            context += "Recent logs:\n"
            for i, log in enumerate(self.log_data[:5], 1):
                attrs = log.get("attributes", {})
                msg = attrs.get("message", "N/A")[:100]
                context += f"{i}. {msg}\n"
        else:
            context += "No logs downloaded yet\n"
        
        return context


class _CopyableErrorDialog(tk.Toplevel):
    """A dialog that shows error text in a selectable/copyable text box,
    with a standard Copy button and a 'Copy to Ask Auger' button."""

    def __init__(self, parent, title, message, ask_auger_cb=None):
        super().__init__(parent)
        self.title(title)
        self.configure(bg=BG2)
        self.resizable(True, True)
        self.grab_set()

        # Title bar
        tk.Label(self, text=f"⚠  {title}", font=('Segoe UI', 11, 'bold'),
                 fg=ERROR, bg=BG2, anchor='w').pack(fill=tk.X, padx=12, pady=(10, 4))

        # Scrollable text area — user can select/copy freely
        from tkinter import scrolledtext as _st
        txt = _st.ScrolledText(self, wrap=tk.WORD, font=('Consolas', 9),
                               bg=BG3, fg=FG, insertbackground=FG,
                               relief=tk.FLAT, borderwidth=1, height=14, width=72)
        txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        txt.insert('1.0', message)
        txt.config(state=tk.DISABLED)

        # Button row
        btn_frame = tk.Frame(self, bg=BG2)
        btn_frame.pack(fill=tk.X, padx=12, pady=(4, 10))

        def _copy():
            self.clipboard_clear()
            self.clipboard_append(message)
            _copy_btn.config(text="✓ Copied!")
            self.after(1500, lambda: _copy_btn.config(text=" Copy"))

        _copy_btn = tk.Button(btn_frame, text=" Copy",
                              bg=BG3, fg=FG, font=('Segoe UI', 9),
                              relief=tk.FLAT, padx=12, pady=5, command=_copy)
        _copy_btn.pack(side=tk.LEFT, padx=(0, 6))

        if ask_auger_cb:
            def _copy_ask():
                ask_auger_cb(message)
                _ask_btn.config(text="✓ Copied for Ask Auger!")
                self.after(1800, lambda: _ask_btn.config(text="Copy to Ask Auger"))

            _ask_btn = tk.Button(btn_frame, text="Copy to Ask Auger",
                                 bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                                 relief=tk.FLAT, padx=12, pady=5, command=_copy_ask)
            _ask_btn.pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(btn_frame, text="Close", bg=BG3, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=12, pady=5, command=self.destroy).pack(side=tk.RIGHT)

        # Center on parent
        self.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(0,x)}+{max(0,y)}")


# Widget registration
def create_widget(parent, context_builder_callback=None):
    """Factory function for widget creation"""
    return PannerWidget(parent, context_builder_callback)
