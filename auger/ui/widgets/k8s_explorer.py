"""
K8s Explorer Widget — Kubernetes Cluster Browser for Auger
Full-featured K8s explorer: pods, deployments, services, events,
log streaming, and (dev-only) exec into container.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import threading
import json
import os
import re
import ssl
import base64
import queue
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
import requests
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_treeview_menu, auger_home as _auger_home
from auger.ui import icons as _icons

# ── Colour palette (matches Auger theme) ───────────────────────────────────
BG  = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
BG4 = '#333333'
FG  = '#e0e0e0'
FG2 = '#a0a0a0'
ACCENT  = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR   = '#f44747'
WARNING = '#ce9178'
SUCCESS = '#4ec9b0'
YELLOW  = '#dcdcaa'
PURPLE  = '#c586c0'
ORANGE  = '#ff8c00'

# ── Cluster definitions ────────────────────────────────────────────────────
CLUSTERS = {
    'DEV':     {'id': 'c-m-qpv8hf6m', 'label': 'DEV',     'exec_ok': True,  'env': 'dev'},
    'STAGING': {'id': 'c-xkd99',       'label': 'STAGING', 'exec_ok': False, 'env': 'staging'},
    'PROD':    {'id': 'c-2bsb4',       'label': 'PROD',    'exec_ok': False, 'env': 'prod'},
}

LOG_COLORS = {
    'ERROR':   ERROR,
    'WARN':    WARNING,
    'WARNING': WARNING,
    'INFO':    FG2,
    'DEBUG':   '#6a9955',
    'TRACE':   '#569cd6',
}

# ── All widget styles configured once at module level ─────────────────────
# Using unique per-tree style names (id(tree)) triggers a Tk C-level crash
# when many styles are registered in rapid succession. One shared style avoids
# this entirely.  Notebook styles are also guarded to avoid repeated configure
# calls when the widget is opened multiple times in a session.
_TREE_STYLE_NAME = 'K8sExplorer.Treeview'
_styles_ready = False

def _ensure_styles():
    global _styles_ready
    if _styles_ready:
        return
    try:
        s = ttk.Style()
        # Treeview (shared across all 6 trees in the widget)
        s.configure(_TREE_STYLE_NAME, background=BG, fieldbackground=BG,
                    foreground=FG, font=('Segoe UI', 9), rowheight=22)
        s.map(_TREE_STYLE_NAME, background=[('selected', ACCENT)],
              foreground=[('selected', 'white')])
        s.configure(f'{_TREE_STYLE_NAME}.Heading', background=BG2,
                    foreground=ACCENT2, font=('Segoe UI', 9, 'bold'))
        # Resource notebook tabs
        s.configure('K8s.TNotebook', background=BG2, borderwidth=0)
        s.configure('K8s.TNotebook.Tab', background=BG3, foreground=FG,
                    padding=[10, 4])
        s.map('K8s.TNotebook.Tab',
              background=[('selected', ACCENT)],
              foreground=[('selected', 'white')])
        # Detail/log notebook tabs
        s.configure('Detail.TNotebook', background=BG2, borderwidth=0)
        s.configure('Detail.TNotebook.Tab', background=BG3, foreground=FG,
                    padding=[8, 3])
        s.map('Detail.TNotebook.Tab',
              background=[('selected', BG4)],
              foreground=[('selected', ACCENT2)])
        _styles_ready = True
    except Exception:
        pass

# Keep old name as alias so any external references don't break
def _ensure_tree_style():
    _ensure_styles()

# ── Icon (K8s helm-wheel inspired) ────────────────────────────────────────
def make_icon(size=18, color='#326ce5'):
    from PIL import Image, ImageDraw
    import math
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = s2 // 2
    r_outer = s2 // 2 - 2
    r_inner = s2 // 5
    r_hub   = s2 // 8
    spoke_w = max(2, s2 // 12)
    # outer ring
    d.ellipse([cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer],
              outline=color, width=max(2, s2 // 14))
    # spokes (7 like K8s logo)
    for i in range(7):
        angle = math.radians(i * 360 / 7 - 90)
        x1 = cx + r_inner * math.cos(angle)
        y1 = cy + r_inner * math.sin(angle)
        x2 = cx + r_outer * math.cos(angle)
        y2 = cy + r_outer * math.sin(angle)
        d.line([(x1, y1), (x2, y2)], fill=color, width=spoke_w)
    # hub
    d.ellipse([cx - r_hub, cy - r_hub, cx + r_hub, cy + r_hub],
              fill=color)
    return img.resize((size, size), Image.LANCZOS)


# ── Tab icons (PIL-drawn, no emoji) ───────────────────────────────────────
def _make_pods_icon(size=16, color='#4ec9b0'):
    """Hexagonal pod icon."""
    from PIL import Image, ImageDraw
    import math
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size / 2
    r = size / 2 - 1.5
    pts = [(cx + r * math.cos(math.radians(i * 60 - 30)),
            cy + r * math.sin(math.radians(i * 60 - 30))) for i in range(6)]
    d.polygon(pts, outline=color, fill=None)
    # small dot center
    d.ellipse([cx - 2, cy - 2, cx + 2, cy + 2], fill=color)
    return img


def _make_deploy_icon(size=16, color='#569cd6'):
    """Stacked rectangles — deployments."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = size - 4
    for i, y in enumerate([2, 6, 10]):
        fill = color if i == 0 else None
        d.rectangle([2, y, 2 + w, y + 3], outline=color, fill=fill)
    return img


def _make_svc_icon(size=16, color='#dcdcaa'):
    """Two circles connected by a line — services."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = 3
    d.ellipse([1, size // 2 - r, 1 + r * 2, size // 2 + r], outline=color)
    d.ellipse([size - 1 - r * 2, size // 2 - r, size - 1, size // 2 + r], outline=color)
    d.line([(1 + r * 2, size // 2), (size - 1 - r * 2, size // 2)], fill=color, width=1)
    return img


def _make_events_icon(size=16, color='#ce9178'):
    """Three horizontal lines — events list."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in [4, 8, 12]:
        d.line([(2, y), (size - 2, y)], fill=color, width=1)
    # bullet dots on left
    for y in [4, 8, 12]:
        d.ellipse([2, y - 1, 4, y + 1], fill=color)
    return img


def _make_logs_icon(size=16, color='#a0a0a0'):
    """Document with lines — logs panel."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([2, 1, size - 2, size - 1], outline=color)
    for y in [5, 8, 11]:
        d.line([(4, y), (size - 4, y)], fill=color, width=1)
    return img


def _make_describe_icon(size=16, color='#a0a0a0'):
    """Magnifying glass — describe panel."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 2 - 4
    cx = cy = size // 2 - 2
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color)
    handle_x = cx + int(r * 0.7)
    handle_y = cy + int(r * 0.7)
    d.line([(handle_x, handle_y), (size - 2, size - 2)], fill=color, width=2)
    return img


def _make_env_icon(size=16, color='#c586c0'):
    """2x2 dot grid — env vars / settings."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = 2
    for cx, cy in [(4, 4), (12, 4), (4, 12), (12, 12)]:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)
    return img


def _make_labels_icon(size=16, color='#a0a0a0'):
    """Tag shape — labels/annotations."""
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pts = [(2, 3), (10, 3), (size - 2, size // 2), (10, size - 3), (2, size - 3)]
    d.polygon(pts, outline=color, fill=None)
    d.ellipse([4, size // 2 - 2, 8, size // 2 + 2], fill=color)
    return img


def _make_nb_photo(fn, size=15):
    """Render a PIL icon function to an ImageTk.PhotoImage. Returns None on failure."""
    try:
        from PIL import ImageTk
        return ImageTk.PhotoImage(fn(size=size))
    except Exception:
        return None


# ── Helpers ────────────────────────────────────────────────────────────────
def _age(ts_str):
    """Human-readable age from ISO timestamp."""
    if not ts_str:
        return '?'
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        delta = datetime.now(timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 60:    return f'{s}s'
        if s < 3600:  return f'{s//60}m'
        if s < 86400: return f'{s//3600}h'
        return f'{s//86400}d'
    except Exception:
        return '?'

def _pod_status(pod):
    """Derive display status + tag from pod dict."""
    phase = pod.get('status', {}).get('phase', 'Unknown')
    cs_list = pod.get('status', {}).get('containerStatuses', [])
    for cs in cs_list:
        state = cs.get('state', {})
        if 'waiting' in state:
            reason = state['waiting'].get('reason', 'Waiting')
            if 'CrashLoop' in reason:
                return reason, 'crashloop'
            return reason, 'pending'
        if 'terminated' in state:
            reason = state['terminated'].get('reason', 'Terminated')
            exit_code = state['terminated'].get('exitCode', 0)
            if exit_code != 0:
                return f'{reason}({exit_code})', 'error'
            return reason, 'completed'
    if phase == 'Running':
        ready = sum(1 for c in cs_list if c.get('ready'))
        total = len(cs_list)
        if ready < total:
            return f'Running ({ready}/{total})', 'degraded'
        return 'Running', 'running'
    if phase == 'Pending':
        return 'Pending', 'pending'
    if phase == 'Succeeded':
        return 'Succeeded', 'completed'
    if phase in ('Failed', 'Unknown'):
        return phase, 'error'
    return phase, 'unknown'

def _restarts(pod):
    total = sum(c.get('restartCount', 0)
                for c in pod.get('status', {}).get('containerStatuses', []))
    return total

def _ready_str(pod):
    cs_list = pod.get('status', {}).get('containerStatuses', [])
    if not cs_list:
        return '0/0'
    ready = sum(1 for c in cs_list if c.get('ready'))
    return f'{ready}/{len(cs_list)}'

def _containers(pod):
    return [c['name'] for c in pod.get('spec', {}).get('containers', [])]


# ══════════════════════════════════════════════════════════════════════════
class K8sExplorerWidget(tk.Frame):
    """Full-featured Kubernetes Explorer Widget."""

    WIDGET_TITLE    = 'K8s Explorer'
    WIDGET_ICON_COLOR = '#326ce5'
    WIDGET_ICON_FUNC = staticmethod(make_icon)

    # ── init ──────────────────────────────────────────────────────────────
    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self.context_builder_callback = context_builder_callback

        load_dotenv(_auger_home() / '.auger' / '.env')
        self._rancher_url   = os.environ.get('RANCHER_URL', '').rstrip('/')
        self._rancher_token = os.environ.get('RANCHER_BEARER_TOKEN', '')

        self._cluster_id   = CLUSTERS['DEV']['id']
        self._cluster_env  = 'dev'
        self._exec_ok      = True
        self._namespace    = 'assist-dev01'
        self._all_namespaces = False

        self._pod_data   = []
        self._deploy_data = []
        self._svc_data   = []
        self._event_data = []

        self._log_thread    = None
        self._log_stop      = threading.Event()
        self._log_follow    = tk.BooleanVar(value=False)
        self._log_search    = tk.StringVar()
        self._log_lines     = tk.IntVar(value=200)
        self._auto_refresh  = tk.BooleanVar(value=False)
        self._refresh_secs  = tk.IntVar(value=30)
        self._ar_job        = None
        self._status_msg    = tk.StringVar(value='Ready')

        self._icons = {}
        for name in ('refresh', 'search', 'delete', 'play', 'download'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        # GC guard for PIL PhotoImages on notebook tabs
        self._tab_icons = {}

        self._q = queue.Queue()
        self._build_ui()
        self.after(200, self._load_namespaces)
        # Defer ImageTk.PhotoImage creation to main thread (safe from hot-reload thread)
        self.after(0, self._apply_tab_icons)
        self.after(50, self._poll_q)

    def _poll_q(self):
        try:
            while True:
                fn, args = self._q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        try:
            self.after(50, self._poll_q)
        except Exception:
            pass

    def _safe(self, fn, *args):
        """Queue a callable for execution on the main Tk thread."""
        self._q.put((fn, args))

    # ── API helpers ────────────────────────────────────────────────────────
    def _headers(self):
        return {'Authorization': f'Bearer {self._rancher_token}'}

    def _k8s(self, path, timeout=15):
        """GET from k8s API via Rancher proxy."""
        url = f'{self._rancher_url}/k8s/clusters/{self._cluster_id}/{path}'
        resp = requests.get(url, headers=self._headers(),
                            verify=False, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _v3(self, path, timeout=15):
        url = f'{self._rancher_url}/v3/{path}'
        resp = requests.get(url, headers=self._headers(),
                            verify=False, timeout=timeout)
        resp.raise_for_status()
        return resp.json()

    def _ns_path(self, resource, ns=None):
        ns = ns or (None if self._all_namespaces else self._namespace)
        if ns:
            return f'api/v1/namespaces/{ns}/{resource}'
        return f'api/v1/{resource}'

    def _apps_ns_path(self, resource, ns=None):
        ns = ns or (None if self._all_namespaces else self._namespace)
        if ns:
            return f'apis/apps/v1/namespaces/{ns}/{resource}'
        return f'apis/apps/v1/{resource}'

    # ── UI build ───────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_toolbar()
        self._build_main_pane()
        self._build_status_bar()

    def _apply_tab_icons(self):
        """Apply emoji labels to sub-tabs via safe nb.tab() calls.
        nb.tab() does not trigger SIGSEGV — only nb.add(text=...) with emoji is unsafe."""
        pairs_main = [
            (self._nb, self._pods_frame,   '⬡ Pods'),
            (self._nb, self._deploy_frame, '🚀 Deployments'),
            (self._nb, self._svc_frame,    '🔗 Services'),
            (self._nb, self._events_frame, '📋 Events'),
        ]
        pairs_detail = [
            (self._detail_nb, self._log_frame,    '📄 Logs'),
            (self._detail_nb, self._desc_frame,   '🔍 Describe'),
            (self._detail_nb, self._env_frame,    '🔑 Env Vars'),
            (self._detail_nb, self._labels_frame, '🏷 Labels/Annotations'),
        ]
        for nb, frame, label in pairs_main + pairs_detail:
            try:
                nb.tab(frame, text=f'  {label}  ')
            except Exception:
                pass

    def _build_toolbar(self):
        tb = tk.Frame(self, bg=BG2, pady=4)
        tb.pack(fill=tk.X, padx=0, pady=0)

        # ── cluster selector ──
        tk.Label(tb, text='Cluster:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(8, 2))
        self._cluster_var = tk.StringVar(value='DEV')
        self._cluster_rbs = {}
        for key, info in CLUSTERS.items():
            rb = tk.Radiobutton(
                tb, text=info['label'], variable=self._cluster_var,
                value=key, command=self._on_cluster_change,
                indicatoron=False,
                bg=BG3, fg=FG, selectcolor=ACCENT,
                activebackground=BG4, activeforeground=FG,
                relief=tk.FLAT, overrelief=tk.FLAT,
                font=('Segoe UI', 9, 'bold'), padx=8, pady=2)
            rb.pack(side=tk.LEFT, padx=2)
            self._cluster_rbs[key] = rb

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y,
                                                    padx=6, pady=2)

        # ── namespace ──
        tk.Label(tb, text='Namespace:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(0, 2))
        self._ns_var = tk.StringVar(value=self._namespace)
        self._ns_combo = ttk.Combobox(tb, textvariable=self._ns_var,
                                      width=20, font=('Segoe UI', 9))
        self._ns_combo.pack(side=tk.LEFT, padx=2)
        self._ns_combo.bind('<<ComboboxSelected>>', lambda _: self._refresh())

        self._all_ns_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            tb, text='All NS', variable=self._all_ns_var,
            command=self._on_all_ns_toggle,
            bg=BG2, fg=FG, selectcolor=BG3, activebackground=BG2,
            font=('Segoe UI', 9)
        ).pack(side=tk.LEFT, padx=4)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y,
                                                    padx=6, pady=2)

        # ── search filter ──
        tk.Label(tb, text='Filter:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(0, 2))
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add('write', lambda *_: self._apply_filter())
        tk.Entry(tb, textvariable=self._filter_var, width=16,
                 bg=BG3, fg=FG, insertbackground=FG,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=2)

        ttk.Separator(tb, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y,
                                                    padx=6, pady=2)

        # ── auto-refresh ──
        tk.Checkbutton(
            tb, text='Auto', variable=self._auto_refresh,
            command=self._toggle_auto_refresh,
            bg=BG2, fg=FG, selectcolor=BG3, activebackground=BG2,
            font=('Segoe UI', 9)
        ).pack(side=tk.LEFT)
        ttk.Combobox(tb, textvariable=self._refresh_secs,
                     values=[15, 30, 60, 120], width=4,
                     font=('Segoe UI', 9)).pack(side=tk.LEFT)
        tk.Label(tb, text='s', fg=FG2, bg=BG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(0, 4))

        # ── refresh btn ──
        tk.Button(
            tb, text='Refresh', command=self._refresh,
            bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT, padx=10, pady=3
        ).pack(side=tk.LEFT, padx=4)

        # ── right side: exec warning label ──
        self._exec_label = tk.Label(
            tb, text='', fg=WARNING, bg=BG2, font=('Segoe UI', 8, 'italic'))
        self._exec_label.pack(side=tk.RIGHT, padx=8)

    def _build_main_pane(self):
        # Vertical pane: top = resource tabs, bottom = detail/log panel
        self._vpane = tk.PanedWindow(self, orient=tk.VERTICAL,
                                     bg=BG3, sashwidth=6, sashrelief=tk.FLAT)
        self._vpane.pack(fill=tk.BOTH, expand=True)

        # ── top: resource notebook ──────────────────────────────────────
        top = tk.Frame(self._vpane, bg=BG)
        self._vpane.add(top, minsize=150)

        _ensure_styles()  # All styles registered once at module level

        self._nb = ttk.Notebook(top, style='K8s.TNotebook')
        self._nb.pack(fill=tk.BOTH, expand=True)
        self._nb.bind('<<NotebookTabChanged>>', self._on_tab_changed)

        self._pods_frame    = tk.Frame(self._nb, bg=BG)
        self._deploy_frame  = tk.Frame(self._nb, bg=BG)
        self._svc_frame     = tk.Frame(self._nb, bg=BG)
        self._events_frame  = tk.Frame(self._nb, bg=BG)

        # Add tabs with text only — icons applied later on main thread via after()
        self._nb.add(self._pods_frame,   text=' Pods')
        self._nb.add(self._deploy_frame, text=' Deployments')
        self._nb.add(self._svc_frame,    text=' Services')
        self._nb.add(self._events_frame, text=' Events')

        self._build_pods_tab()
        self._build_deploy_tab()
        self._build_svc_tab()
        self._build_events_tab()

        # ── bottom: detail/log panel ─────────────────────────────────────
        bot = tk.Frame(self._vpane, bg=BG)
        self._vpane.add(bot, minsize=120)

        # styles already configured at module level by _ensure_styles()

        self._detail_nb = ttk.Notebook(bot, style='Detail.TNotebook')
        self._detail_nb.pack(fill=tk.BOTH, expand=True)

        self._log_frame     = tk.Frame(self._detail_nb, bg=BG)
        self._desc_frame    = tk.Frame(self._detail_nb, bg=BG)
        self._env_frame     = tk.Frame(self._detail_nb, bg=BG)
        self._labels_frame  = tk.Frame(self._detail_nb, bg=BG)

        # Add tabs with text only — icons applied later on main thread via after()
        self._detail_nb.add(self._log_frame,    text=' Logs')
        self._detail_nb.add(self._desc_frame,   text=' Describe')
        self._detail_nb.add(self._env_frame,    text=' Env Vars')
        self._detail_nb.add(self._labels_frame, text=' Labels/Annotations')

        self._build_log_panel()
        self._build_describe_panel()
        self._build_env_panel()
        self._build_labels_panel()

    def _build_status_bar(self):
        sb = tk.Frame(self, bg=BG2, height=22)
        sb.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(sb, textvariable=self._status_msg, fg=FG2, bg=BG2,
                 font=('Segoe UI', 8), anchor=tk.W).pack(
                     side=tk.LEFT, padx=8)
        self._count_label = tk.Label(sb, text='', fg=ACCENT2, bg=BG2,
                                     font=('Segoe UI', 8, 'bold'))
        self._count_label.pack(side=tk.RIGHT, padx=8)

    # ── Pods tab ──────────────────────────────────────────────────────────
    def _build_pods_tab(self):
        parent = self._pods_frame

        # action buttons
        ab = tk.Frame(parent, bg=BG2)
        ab.pack(fill=tk.X, padx=4, pady=2)

        tk.Button(ab, text='Copy Name', command=self._copy_pod_name,
                  bg=BG3, fg=FG, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)
        tk.Button(ab, text='View Logs', command=self._load_logs,
                  bg=BG3, fg=FG, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)
        tk.Button(ab, text='Describe', command=self._describe_pod,
                  bg=BG3, fg=FG, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)
        self._exec_btn = tk.Button(
            ab, text='Exec Shell', command=self._exec_into_pod,
            bg=ACCENT2, fg='black', font=('Segoe UI', 8, 'bold'),
            relief=tk.FLAT, padx=6)
        self._exec_btn.pack(side=tk.LEFT, padx=2)
        tk.Button(ab, text='Restart Pod', command=self._restart_pod,
                  bg=BG3, fg=WARNING, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)
        tk.Button(ab, text='Save Logs', command=self._save_logs,
                  bg=BG3, fg=FG, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)

        # container selector
        tk.Label(ab, text='Container:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(8, 2))
        self._container_var = tk.StringVar()
        self._container_combo = ttk.Combobox(
            ab, textvariable=self._container_var, width=18,
            font=('Segoe UI', 8))
        self._container_combo.pack(side=tk.LEFT, padx=2)

        # treeview
        cols = ('namespace', 'name', 'ready', 'status',
                'restarts', 'age', 'node', 'ip')
        self._pod_tree = ttk.Treeview(parent, columns=cols,
                                      show='headings', selectmode='browse')
        widths = dict(namespace=130, name=240, ready=60,
                      status=120, restarts=65, age=55, node=160, ip=110)
        heads  = dict(namespace='Namespace', name='Pod', ready='Ready',
                      status='Status', restarts='↺', age='Age',
                      node='Node', ip='Pod IP')
        for c in cols:
            self._pod_tree.heading(c, text=heads[c],
                                   command=lambda _c=c: self._sort_pods(_c))
            self._pod_tree.column(c, width=widths[c], anchor=tk.W)

        self._style_tree(self._pod_tree)
        vsb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                            command=self._pod_tree.yview)
        hsb = ttk.Scrollbar(parent, orient=tk.HORIZONTAL,
                            command=self._pod_tree.xview)
        self._pod_tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self._pod_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 0))
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)

        self._pod_tree.tag_configure('running',   background='#1a3a1a', foreground=SUCCESS)
        self._pod_tree.tag_configure('pending',   background='#3a3a00', foreground=YELLOW)
        self._pod_tree.tag_configure('error',     background='#3a0000', foreground=ERROR)
        self._pod_tree.tag_configure('crashloop', background='#5a0000', foreground=ERROR)
        self._pod_tree.tag_configure('completed', background='#1a2a3a', foreground=FG2)
        self._pod_tree.tag_configure('degraded',  background='#3a2000', foreground=ORANGE)
        self._pod_tree.tag_configure('unknown',   background=BG3,       foreground=FG2)

        self._pod_tree.bind('<<TreeviewSelect>>', self._on_pod_select)
        self._pod_tree.bind('<Double-1>', lambda _: self._load_logs())
        add_treeview_menu(self._pod_tree)

        self._pod_sort_col = 'name'
        self._pod_sort_rev = False

    # ── Deployments tab ───────────────────────────────────────────────────
    def _build_deploy_tab(self):
        cols = ('namespace', 'name', 'ready', 'up_to_date', 'available', 'age', 'image')
        self._deploy_tree = ttk.Treeview(self._deploy_frame, columns=cols,
                                         show='headings', selectmode='browse')
        widths = dict(namespace=130, name=220, ready=70,
                      up_to_date=90, available=80, age=55, image=300)
        heads  = dict(namespace='Namespace', name='Deployment', ready='Ready',
                      up_to_date='Up-To-Date', available='Available',
                      age='Age', image='Image')
        for c in cols:
            self._deploy_tree.heading(c, text=heads[c])
            self._deploy_tree.column(c, width=widths[c], anchor=tk.W)

        self._style_tree(self._deploy_tree)
        vsb = ttk.Scrollbar(self._deploy_frame, orient=tk.VERTICAL,
                            command=self._deploy_tree.yview)
        self._deploy_tree.configure(yscrollcommand=vsb.set)
        self._deploy_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._deploy_tree.tag_configure('ok',      background='#1a3a1a', foreground=SUCCESS)
        self._deploy_tree.tag_configure('degraded', background='#3a2000', foreground=ORANGE)
        self._deploy_tree.tag_configure('down',     background='#3a0000', foreground=ERROR)

        self._deploy_tree.bind('<<TreeviewSelect>>', self._on_deploy_select)

    # ── Services tab ─────────────────────────────────────────────────────
    def _build_svc_tab(self):
        cols = ('namespace', 'name', 'type', 'cluster_ip', 'external_ip', 'ports', 'age')
        self._svc_tree = ttk.Treeview(self._svc_frame, columns=cols,
                                      show='headings', selectmode='browse')
        widths = dict(namespace=130, name=200, type=80,
                      cluster_ip=110, external_ip=120, ports=200, age=55)
        heads  = dict(namespace='Namespace', name='Service', type='Type',
                      cluster_ip='Cluster IP', external_ip='External IP',
                      ports='Ports', age='Age')
        for c in cols:
            self._svc_tree.heading(c, text=heads[c])
            self._svc_tree.column(c, width=widths[c], anchor=tk.W)

        self._style_tree(self._svc_tree)
        vsb = ttk.Scrollbar(self._svc_frame, orient=tk.VERTICAL,
                            command=self._svc_tree.yview)
        self._svc_tree.configure(yscrollcommand=vsb.set)
        self._svc_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    # ── Events tab ────────────────────────────────────────────────────────
    def _build_events_tab(self):
        ef = self._events_frame
        # filter bar
        fb = tk.Frame(ef, bg=BG2)
        fb.pack(fill=tk.X, padx=4, pady=2)
        self._event_type_var = tk.StringVar(value='All')
        for val in ('All', 'Warning', 'Normal'):
            tk.Radiobutton(fb, text=val, variable=self._event_type_var,
                           value=val, command=self._apply_event_filter,
                           bg=BG2, fg=FG, selectcolor=BG3,
                           activebackground=BG2, font=('Segoe UI', 9)
                           ).pack(side=tk.LEFT, padx=4)

        cols = ('namespace', 'type', 'reason', 'object', 'message', 'count', 'last_seen')
        self._event_tree = ttk.Treeview(ef, columns=cols,
                                        show='headings', selectmode='browse')
        widths = dict(namespace=130, type=70, reason=120, object=200,
                      message=350, count=50, last_seen=80)
        heads  = dict(namespace='Namespace', type='Type', reason='Reason',
                      object='Object', message='Message', count='#', last_seen='Last Seen')
        for c in cols:
            self._event_tree.heading(c, text=heads[c])
            self._event_tree.column(c, width=widths[c], anchor=tk.W)

        self._style_tree(self._event_tree)
        vsb = ttk.Scrollbar(ef, orient=tk.VERTICAL,
                            command=self._event_tree.yview)
        self._event_tree.configure(yscrollcommand=vsb.set)
        self._event_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._event_tree.tag_configure('warning', background='#3a2000', foreground=WARNING)
        self._event_tree.tag_configure('normal',  background=BG, foreground=FG2)
        self._all_events = []

    # ── Log panel ─────────────────────────────────────────────────────────
    def _build_log_panel(self):
        lf = self._log_frame

        # toolbar
        lt = tk.Frame(lf, bg=BG2)
        lt.pack(fill=tk.X, padx=4, pady=2)

        tk.Label(lt, text='Lines:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(2, 1))
        ttk.Combobox(lt, textvariable=self._log_lines,
                     values=[50, 100, 200, 500, 1000, 5000],
                     width=5, font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=2)

        tk.Checkbutton(
            lt, text='Follow', variable=self._log_follow,
            command=self._toggle_log_follow,
            bg=BG2, fg=FG, selectcolor=BG3, activebackground=BG2,
            font=('Segoe UI', 8)
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(lt, text='Load', command=self._load_logs,
                  bg=ACCENT, fg='white', font=('Segoe UI', 8, 'bold'),
                  relief=tk.FLAT, padx=6).pack(side=tk.LEFT, padx=2)
        tk.Button(lt, text='Stop', command=self._stop_log_follow,
                  bg=BG3, fg=ERROR, font=('Segoe UI', 8),
                  relief=tk.FLAT, padx=6).pack(side=tk.LEFT, padx=2)
        tk.Button(lt, text='Clear', command=self._clear_logs,
                  bg=BG3, fg=FG, font=('Segoe UI', 8),
                  relief=tk.FLAT, padx=6).pack(side=tk.LEFT, padx=2)
        tk.Button(lt, text='Save', command=self._save_logs,
                  bg=BG3, fg=FG, font=('Segoe UI', 8),
                  relief=tk.FLAT, padx=6).pack(side=tk.LEFT, padx=2)

        # search
        tk.Label(lt, text='Search:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(8, 2))
        se = tk.Entry(lt, textvariable=self._log_search, width=18,
                      bg=BG3, fg=FG, insertbackground=FG,
                      font=('Segoe UI', 8))
        se.pack(side=tk.LEFT, padx=2)
        se.bind('<Return>', lambda _: self._highlight_log_search())
        tk.Button(lt, text='Find', command=self._highlight_log_search,
                  bg=BG3, fg=ACCENT2, font=('Segoe UI', 8),
                  relief=tk.FLAT, padx=4).pack(side=tk.LEFT, padx=2)

        self._log_status = tk.Label(lt, text='', fg=FG2, bg=BG2,
                                    font=('Segoe UI', 8))
        self._log_status.pack(side=tk.RIGHT, padx=8)

        # log text area
        self._log_text = scrolledtext.ScrolledText(
            lf, bg='#0d0d0d', fg=FG, font=('Courier New', 8),
            insertbackground=FG, wrap=tk.NONE, state=tk.DISABLED)
        self._log_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        # colour tags for log levels
        for level, color in LOG_COLORS.items():
            self._log_text.tag_config(f'level_{level}', foreground=color)
        self._log_text.tag_config('search_hit',
                                  background=YELLOW, foreground='black')
        self._log_text.tag_config('ts',   foreground='#569cd6')
        self._log_text.tag_config('svc',  foreground=PURPLE)

        make_text_copyable(self._log_text)

    # ── Describe panel ────────────────────────────────────────────────────
    def _build_describe_panel(self):
        self._desc_text = scrolledtext.ScrolledText(
            self._desc_frame, bg='#0d0d0d', fg=ACCENT2,
            font=('Courier New', 8), insertbackground=FG,
            wrap=tk.NONE, state=tk.DISABLED)
        self._desc_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        make_text_copyable(self._desc_text)

    # ── Env vars panel ────────────────────────────────────────────────────
    def _build_env_panel(self):
        cols = ('name', 'value')
        self._env_tree = ttk.Treeview(self._env_frame, columns=cols,
                                      show='headings', selectmode='browse')
        self._env_tree.heading('name',  text='Variable')
        self._env_tree.heading('value', text='Value')
        self._env_tree.column('name',  width=260, anchor=tk.W)
        self._env_tree.column('value', width=400, anchor=tk.W)
        self._style_tree(self._env_tree)
        vsb = ttk.Scrollbar(self._env_frame, orient=tk.VERTICAL,
                            command=self._env_tree.yview)
        self._env_tree.configure(yscrollcommand=vsb.set)
        self._env_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        # mask sensitive values toggle
        ctrl = tk.Frame(self._env_frame, bg=BG2)
        ctrl.pack(fill=tk.X, padx=4, pady=2)
        self._mask_env = tk.BooleanVar(value=True)
        tk.Checkbutton(ctrl, text='Mask sensitive values',
                       variable=self._mask_env, bg=BG2, fg=FG,
                       selectcolor=BG3, activebackground=BG2,
                       font=('Segoe UI', 8)).pack(side=tk.LEFT)

    # ── Labels panel ─────────────────────────────────────────────────────
    def _build_labels_panel(self):
        cols = ('key', 'value', 'kind')
        self._labels_tree = ttk.Treeview(self._labels_frame, columns=cols,
                                         show='headings', selectmode='browse')
        self._labels_tree.heading('key',   text='Key')
        self._labels_tree.heading('value', text='Value')
        self._labels_tree.heading('kind',  text='Kind')
        self._labels_tree.column('key',   width=260, anchor=tk.W)
        self._labels_tree.column('value', width=300, anchor=tk.W)
        self._labels_tree.column('kind',  width=100, anchor=tk.W)
        self._style_tree(self._labels_tree)
        vsb = ttk.Scrollbar(self._labels_frame, orient=tk.VERTICAL,
                            command=self._labels_tree.yview)
        self._labels_tree.configure(yscrollcommand=vsb.set)
        self._labels_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    # ── Style helper ─────────────────────────────────────────────────────
    def _style_tree(self, tree):
        _ensure_tree_style()
        tree.configure(style=_TREE_STYLE_NAME)

    # ── Namespace load ────────────────────────────────────────────────────
    def _load_namespaces(self):
        def _fetch():
            try:
                data = self._v3(f'clusters/{self._cluster_id}/namespaces?limit=200')
                ns_list = sorted(
                    i['name'] for i in data.get('data', [])
                    if 'assist' in i['name'].lower()
                )
                if not ns_list:
                    ns_list = sorted(i['name'] for i in data.get('data', []))
                self._safe(self._update_ns_combo, ns_list)
            except Exception as e:
                self._safe(self._set_status, f'Namespace load failed: {e}', ERROR)
        threading.Thread(target=_fetch, daemon=True).start()

    def _update_ns_combo(self, ns_list):
        self._ns_combo['values'] = ns_list
        current = self._ns_var.get()
        if current not in ns_list and ns_list:
            self._ns_var.set(ns_list[0])
            self._namespace = ns_list[0]

    # ── Refresh / fetch ───────────────────────────────────────────────────
    def _refresh(self):
        self._namespace    = self._ns_var.get()
        self._all_namespaces = self._all_ns_var.get()
        tab = self._nb.index(self._nb.select())
        if tab == 0:  self._fetch_pods()
        elif tab == 1: self._fetch_deployments()
        elif tab == 2: self._fetch_services()
        elif tab == 3: self._fetch_events()

    def _on_tab_changed(self, _event=None):
        self._refresh()

    def _fetch_pods(self):
        self._set_status('Loading pods…')
        def _work():
            try:
                data  = self._k8s(self._ns_path('pods') + '?limit=500')
                items = data.get('items', [])
                self._safe(self._render_pods, items)
            except Exception as e:
                self._safe(self._set_status, f'Pod fetch failed: {e}', ERROR)
        threading.Thread(target=_work, daemon=True).start()

    def _render_pods(self, items):
        self._pod_data = items
        self._apply_filter()
        self._set_status(f'Loaded {len(items)} pods', SUCCESS)
        self._count_label.config(text=f'{len(items)} pods')

    def _apply_filter(self, *_):
        flt = self._filter_var.get().lower()
        for row in self._pod_tree.get_children():
            self._pod_tree.delete(row)
        for pod in self._pod_data:
            ns    = pod['metadata'].get('namespace', '')
            name  = pod['metadata']['name']
            node  = pod.get('spec', {}).get('nodeName', '')
            ip    = pod.get('status', {}).get('podIP', '')
            if flt and flt not in name.lower() and flt not in ns.lower():
                continue
            status, tag = _pod_status(pod)
            self._pod_tree.insert('', tk.END, values=(
                ns, name, _ready_str(pod), status,
                _restarts(pod),
                _age(pod.get('metadata', {}).get('creationTimestamp')),
                node, ip
            ), tags=(tag,))

    def _sort_pods(self, col):
        if self._pod_sort_col == col:
            self._pod_sort_rev = not self._pod_sort_rev
        else:
            self._pod_sort_col = col
            self._pod_sort_rev = False
        col_map = {'namespace': 0, 'name': 1, 'ready': 2,
                   'status': 3, 'restarts': 4, 'age': 5}
        idx = col_map.get(col, 1)
        rows = [(self._pod_tree.set(r, col), r)
                for r in self._pod_tree.get_children()]
        rows.sort(key=lambda x: x[0], reverse=self._pod_sort_rev)
        for i, (_, r) in enumerate(rows):
            self._pod_tree.move(r, '', i)

    def _fetch_deployments(self):
        self._set_status('Loading deployments…')
        def _work():
            try:
                data  = self._k8s(self._apps_ns_path('deployments') + '?limit=500')
                items = data.get('items', [])
                self._safe(self._render_deployments, items)
            except Exception as e:
                self._safe(self._set_status, f'Deployment fetch failed: {e}', ERROR)
        threading.Thread(target=_work, daemon=True).start()

    def _render_deployments(self, items):
        self._deploy_data = items
        for row in self._deploy_tree.get_children():
            self._deploy_tree.delete(row)
        flt = self._filter_var.get().lower()
        for dep in items:
            ns   = dep['metadata'].get('namespace', '')
            name = dep['metadata']['name']
            if flt and flt not in name.lower() and flt not in ns.lower():
                continue
            spec   = dep.get('spec', {})
            status = dep.get('status', {})
            desired   = spec.get('replicas', 0)
            ready     = status.get('readyReplicas', 0)
            uptodate  = status.get('updatedReplicas', 0)
            available = status.get('availableReplicas', 0)
            containers = dep.get('spec', {}).get('template', {}).get(
                'spec', {}).get('containers', [])
            image = containers[0].get('image', '') if containers else ''
            # shorten image
            if '/' in image:
                image = image.split('/')[-1]
            ready_str = f'{ready}/{desired}'
            tag = 'ok' if ready == desired and desired > 0 else (
                  'degraded' if ready and ready < desired else 'down')
            self._deploy_tree.insert('', tk.END, values=(
                ns, name, ready_str, uptodate, available,
                _age(dep['metadata'].get('creationTimestamp')), image
            ), tags=(tag,))
        self._set_status(f'Loaded {len(items)} deployments', SUCCESS)

    def _fetch_services(self):
        self._set_status('Loading services…')
        def _work():
            try:
                data  = self._k8s(self._ns_path('services') + '?limit=500')
                items = data.get('items', [])
                self._safe(self._render_services, items)
            except Exception as e:
                self._safe(self._set_status, f'Service fetch failed: {e}', ERROR)
        threading.Thread(target=_work, daemon=True).start()

    def _render_services(self, items):
        self._svc_data = items
        for row in self._svc_tree.get_children():
            self._svc_tree.delete(row)
        flt = self._filter_var.get().lower()
        for svc in items:
            ns   = svc['metadata'].get('namespace', '')
            name = svc['metadata']['name']
            if flt and flt not in name.lower() and flt not in ns.lower():
                continue
            spec  = svc.get('spec', {})
            stype = spec.get('type', 'ClusterIP')
            cip   = spec.get('clusterIP', '')
            lbs   = svc.get('status', {}).get('loadBalancer', {}).get('ingress', [])
            ext   = lbs[0].get('ip') or lbs[0].get('hostname') if lbs else ''
            ports = ', '.join(
                f"{p.get('port')}/{p.get('protocol','TCP')}"
                + (f'→{p["nodePort"]}' if 'nodePort' in p else '')
                for p in spec.get('ports', []))
            self._svc_tree.insert('', tk.END, values=(
                ns, name, stype, cip, ext or '—', ports,
                _age(svc['metadata'].get('creationTimestamp'))))
        self._set_status(f'Loaded {len(items)} services', SUCCESS)

    def _fetch_events(self):
        self._set_status('Loading events…')
        def _work():
            try:
                data  = self._k8s(self._ns_path('events') + '?limit=300')
                items = data.get('items', [])
                self._safe(self._render_events, items)
            except Exception as e:
                self._safe(self._set_status, f'Event fetch failed: {e}', ERROR)
        threading.Thread(target=_work, daemon=True).start()

    def _render_events(self, items):
        self._all_events = items
        self._apply_event_filter()

    def _apply_event_filter(self):
        for row in self._event_tree.get_children():
            self._event_tree.delete(row)
        etype_filter = self._event_type_var.get()
        items = sorted(self._all_events,
                       key=lambda e: e.get('lastTimestamp') or '', reverse=True)
        for evt in items:
            etype  = evt.get('type', 'Normal')
            if etype_filter != 'All' and etype != etype_filter:
                continue
            ns     = evt['metadata'].get('namespace', '')
            reason = evt.get('reason', '')
            obj_ref = evt.get('involvedObject', {})
            obj    = f"{obj_ref.get('kind','')}/{obj_ref.get('name','')}"
            msg    = evt.get('message', '').replace('\n', ' ')
            count  = evt.get('count', 1)
            last   = _age(evt.get('lastTimestamp'))
            tag    = 'warning' if etype == 'Warning' else 'normal'
            self._event_tree.insert('', tk.END, values=(
                ns, etype, reason, obj, msg, count, last), tags=(tag,))
        self._set_status(f'Loaded {len(items)} events', SUCCESS)

    # ── Pod selection ─────────────────────────────────────────────────────
    def _selected_pod(self):
        sel = self._pod_tree.selection()
        if not sel:
            return None, None, None
        vals = self._pod_tree.item(sel[0], 'values')
        ns, name = vals[0], vals[1]
        pod = next((p for p in self._pod_data
                    if p['metadata']['name'] == name and
                    p['metadata'].get('namespace') == ns), None)
        return ns, name, pod

    def _on_pod_select(self, _event=None):
        ns, name, pod = self._selected_pod()
        if not pod:
            return
        # update container combo
        containers = _containers(pod)
        self._container_combo['values'] = containers
        if containers:
            self._container_var.set(containers[0])
        # populate detail panels immediately on selection
        self._show_describe_json(pod)
        self._load_env_vars(pod)
        self._load_labels(pod)

    def _on_deploy_select(self, _event=None):
        sel = self._deploy_tree.selection()
        if not sel:
            return
        vals  = self._deploy_tree.item(sel[0], 'values')
        ns, name = vals[0], vals[1]
        dep = next((d for d in self._deploy_data
                    if d['metadata']['name'] == name), None)
        if dep:
            self._show_describe_json(dep)

    # ── Log streaming ─────────────────────────────────────────────────────
    def _load_logs(self):
        # Stop any existing stream by setting its own event, then create a
        # fresh event for this new session — avoids the race where the old
        # thread sees the cleared flag and keeps running.
        self._log_stop.set()
        my_stop = threading.Event()
        self._log_stop = my_stop

        ns, name, pod = self._selected_pod()
        if not pod:
            self._set_status('Select a pod first', WARNING)
            return
        container = self._container_var.get()
        tail      = self._log_lines.get()
        follow    = self._log_follow.get()

        self._clear_logs()
        self._log_status.config(text=f'{ns}/{name}:{container}', fg=ACCENT2)

        def _stream(stop_event):
            try:
                params = f'tailLines={tail}&container={container}'
                if follow:
                    params += '&follow=true'
                url = (f'{self._rancher_url}/k8s/clusters/{self._cluster_id}'
                       f'/api/v1/namespaces/{ns}/pods/{name}/log?{params}')
                with requests.get(url, headers=self._headers(),
                                  verify=False, stream=True,
                                  timeout=(10, 300)) as resp:
                    resp.raise_for_status()
                    for raw_line in resp.iter_lines():
                        if stop_event.is_set():
                            break
                        if raw_line:
                            line = raw_line.decode('utf-8', errors='replace')
                            self._safe(self._append_log_line, line)
                if not stop_event.is_set():
                    self._safe(lambda: self._log_status.config(
                        text='Stream ended', fg=FG2))
            except Exception as e:
                if not stop_event.is_set():
                    self._safe(self._set_status, f'Log error: {e}', ERROR)

        self._log_thread = threading.Thread(target=_stream,
                                            args=(my_stop,), daemon=True)
        self._log_thread.start()

    def _toggle_log_follow(self):
        if self._log_follow.get():
            self._load_logs()

    def _stop_log_follow(self):
        self._log_stop.set()

    def _append_log_line(self, raw):
        """Parse JSON log lines (JBoss structured) or plain text."""
        text = raw
        level = None
        ts    = None
        try:
            obj = json.loads(raw)
            ts      = obj.get('timestamp', '')
            level   = obj.get('status', obj.get('level', '')).upper()
            message = obj.get('message', raw)
            svc     = obj.get('mdc', {}).get('dd.service', '')
            text    = f'[{ts[:23] if ts else ""}] [{level:5}] {("["+svc+"] ") if svc else ""}{message}'
        except Exception:
            # plain text: detect level
            for lvl in ('ERROR', 'WARN', 'WARNING', 'INFO', 'DEBUG', 'TRACE'):
                if lvl in raw.upper():
                    level = lvl
                    break

        self._log_text.config(state=tk.NORMAL)
        self._log_text.insert(tk.END, text + '\n')

        # apply colour tags to last line
        last_line = int(self._log_text.index(tk.END).split('.')[0]) - 1
        start = f'{last_line}.0'
        end   = f'{last_line}.end'
        if level and level in LOG_COLORS:
            self._log_text.tag_add(f'level_{level}', start, end)

        self._log_text.config(state=tk.DISABLED)
        self._log_text.see(tk.END)

    def _clear_logs(self):
        self._log_text.config(state=tk.NORMAL)
        self._log_text.delete('1.0', tk.END)
        self._log_text.config(state=tk.DISABLED)

    def _highlight_log_search(self):
        self._log_text.tag_remove('search_hit', '1.0', tk.END)
        term = self._log_search.get()
        if not term:
            return
        start = '1.0'
        count = 0
        while True:
            pos = self._log_text.search(term, start, stopindex=tk.END,
                                        nocase=True)
            if not pos:
                break
            end = f'{pos}+{len(term)}c'
            self._log_text.tag_add('search_hit', pos, end)
            start = end
            count += 1
        self._log_status.config(text=f'{count} hits for "{term}"',
                                fg=YELLOW if count else ERROR)

    def _save_logs(self):
        _, name, _ = self._selected_pod()
        fname = filedialog.asksaveasfilename(
            defaultextension='.log',
            filetypes=[('Log files', '*.log'), ('Text', '*.txt')],
            initialfile=f'{name or "pod"}.log')
        if fname:
            content = self._log_text.get('1.0', tk.END)
            Path(fname).write_text(content)
            self._set_status(f'Saved → {fname}', SUCCESS)

    # ── Describe ──────────────────────────────────────────────────────────
    def _describe_pod(self):
        ns, name, pod = self._selected_pod()
        if not pod:
            self._set_status('Select a pod first', WARNING)
            return
        self._show_describe_json(pod)
        self._detail_nb.select(1)

    def _show_describe_json(self, obj):
        text = json.dumps(obj, indent=2, default=str)
        self._desc_text.config(state=tk.NORMAL)
        self._desc_text.delete('1.0', tk.END)
        self._desc_text.insert(tk.END, text)
        self._desc_text.config(state=tk.DISABLED)

    # ── Env vars ──────────────────────────────────────────────────────────
    def _load_env_vars(self, pod):
        for row in self._env_tree.get_children():
            self._env_tree.delete(row)
        mask = self._mask_env.get()
        sensitive = {'password', 'secret', 'token', 'key', 'pass', 'credential'}
        for container in pod.get('spec', {}).get('containers', []):
            for env in container.get('env', []):
                k = env.get('name', '')
                v = env.get('value', env.get('valueFrom', {}).get(
                    'secretKeyRef', {}).get('name', '(secret ref)'))
                if mask and any(s in k.lower() for s in sensitive):
                    v = '••••••••'
                self._env_tree.insert('', tk.END, values=(k, v, container['name']))

    # ── Labels/Annotations ────────────────────────────────────────────────
    def _load_labels(self, obj):
        for row in self._labels_tree.get_children():
            self._labels_tree.delete(row)
        meta = obj.get('metadata', {})
        for k, v in sorted((meta.get('labels') or {}).items()):
            self._labels_tree.insert('', tk.END, values=(k, v, 'label'))
        for k, v in sorted((meta.get('annotations') or {}).items()):
            self._labels_tree.insert('', tk.END, values=(k, v, 'annotation'))

    # ── Copy pod name ─────────────────────────────────────────────────────
    def _copy_pod_name(self):
        _, name, _ = self._selected_pod()
        if name:
            self.clipboard_clear()
            self.clipboard_append(name)
            self._set_status(f'Copied: {name}', SUCCESS)

    # ── Restart pod ───────────────────────────────────────────────────────
    def _restart_pod(self):
        ns, name, pod = self._selected_pod()
        if not pod:
            self._set_status('Select a pod first', WARNING)
            return
        if not self._exec_ok:
            messagebox.showwarning('Not Allowed',
                'Pod restart is only available in the DEV cluster.\n'
                'For staging/prod, use a Flux config PR.',
                parent=self)
            return
        if not messagebox.askyesno('Restart Pod',
                f'Delete pod {name} in {ns}?\n(It will be recreated by the deployment.)',
                parent=self):
            return
        def _do():
            try:
                url = (f'{self._rancher_url}/k8s/clusters/{self._cluster_id}'
                       f'/api/v1/namespaces/{ns}/pods/{name}')
                resp = requests.delete(url, headers=self._headers(), verify=False, timeout=10)
                resp.raise_for_status()
                self._safe(self._set_status, f'Deleted {name} — will restart', SUCCESS)
                time.sleep(2)
                self._safe(self._fetch_pods)
            except Exception as e:
                self._safe(self._set_status, f'Restart failed: {e}', ERROR)
        threading.Thread(target=_do, daemon=True).start()

    # ── Exec into container ───────────────────────────────────────────────
    def _exec_into_pod(self):
        ns, name, pod = self._selected_pod()
        if not pod:
            self._set_status('Select a pod first', WARNING)
            return
        if not self._exec_ok:
            messagebox.showwarning(
                'Exec Not Available',
                f'Container exec is only available in DEV.\n'
                f'Current cluster: {self._cluster_var.get()}\n\n'
                f'For troubleshooting staging/prod, use:\n'
                f'  • Log streaming (Logs tab)\n'
                f'  • Describe (JSON detail)\n'
                f'  • DataDog traces',
                parent=self)
            return
        container = self._container_var.get() or _containers(pod)[0] if _containers(pod) else 'jboss'
        self._open_exec_terminal(ns, name, container)

    def _open_exec_terminal(self, ns, pod_name, container):
        """Open a popup terminal window with exec session via websocket.

        Uses pyte (VT100/xterm emulator) to render ANSI colour output cleanly.
        Falls back to raw ANSI-stripped text if pyte is unavailable.
        """
        # ── pyte screen (80 cols × 24 rows, grows via scrollback append) ──
        try:
            import pyte as _pyte
            _screen = _pyte.Screen(220, 50)
            _stream = _pyte.ByteStream(_screen)
            _pyte_ok = True
        except ImportError:
            _pyte_ok = False

        # ANSI-256 colour palette (for pyte colour mapping)
        _ANSI_NAMES = {
            'black': '#1e1e1e', 'red': '#f44747', 'green': '#00ff41',
            'brown': '#ce9178', 'blue': '#569cd6', 'magenta': '#c586c0',
            'cyan':  '#9cdcfe', 'white': '#d4d4d4',
            'brightblack': '#808080', 'brightred': '#f44747',
            'brightgreen': '#6a9955', 'brightbrown': '#dcdcaa',
            'brightblue':  '#4fc1ff', 'brightmagenta': '#c586c0',
            'brightcyan':  '#9cdcfe', 'brightwhite': '#ffffff',
        }

        win = tk.Toplevel(self)
        win.title(f'💻  {pod_name} [{container}]  — {self._cluster_env.upper()}')
        win.geometry('1000x600')
        win.configure(bg=BG)

        # ── header ─────────────────────────────────────────────────────────
        hdr = tk.Frame(win, bg='#0d1a30')
        hdr.pack(fill=tk.X)
        tk.Label(hdr,
                 text=f'  ⬡  {self._cluster_env.upper()}  ·  {ns}  ·  {pod_name}  ·  {container}',
                 fg=ACCENT2, bg='#0d1a30', font=('Segoe UI', 10, 'bold')
                 ).pack(side=tk.LEFT, padx=8, pady=4)
        env_badge = 'DEV ONLY' if self._cluster_env == 'dev' else self._cluster_env.upper()
        tk.Label(hdr, text=env_badge, fg=SUCCESS, bg='#0d1a30',
                 font=('Segoe UI', 9, 'bold')).pack(side=tk.RIGHT, padx=8)

        # ── output Text widget (scrollable, monospace) ─────────────────────
        out_frame = tk.Frame(win, bg='#0a0a0a')
        out_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))
        out_scroll = tk.Scrollbar(out_frame)
        out_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        out = tk.Text(out_frame, bg='#0a0a0a', fg='#00ff41',
                      font=('Courier New', 10),
                      insertbackground='#00ff41',
                      wrap=tk.WORD, state=tk.DISABLED,
                      yscrollcommand=out_scroll.set,
                      relief=tk.FLAT, padx=6, pady=4)
        out.pack(fill=tk.BOTH, expand=True)
        out_scroll.config(command=out.yview)

        # pre-register colour tags for pyte ANSI colours
        out.tag_config('_info',  foreground=FG2)
        out.tag_config('_error', foreground=ERROR)
        for name, colour in _ANSI_NAMES.items():
            out.tag_config(f'fg_{name}', foreground=colour)
            out.tag_config(f'bg_{name}', background=colour)
        # bold / dim
        out.tag_config('_bold', font=('Courier New', 10, 'bold'))
        out.tag_config('_dim',  foreground='#666666')

        # ── quick commands bar ─────────────────────────────────────────────
        qb = tk.Frame(win, bg=BG3)
        qb.pack(fill=tk.X, padx=4, pady=(2, 0))

        # ── input bar ──────────────────────────────────────────────────────
        ib = tk.Frame(win, bg=BG2)
        ib.pack(fill=tk.X, padx=4, pady=4)
        tk.Label(ib, text='$', fg='#00ff41', bg=BG2,
                 font=('Courier New', 12, 'bold')).pack(side=tk.LEFT, padx=4)
        cmd_var = tk.StringVar()
        cmd_entry = tk.Entry(ib, textvariable=cmd_var, bg='#0a0a0a',
                             fg='#00ff41', insertbackground='#00ff41',
                             font=('Courier New', 10), relief=tk.FLAT)
        cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2)
        cmd_entry.focus_set()

        history  = []
        hist_idx = [0]
        stop_event = threading.Event()
        ws_holder  = [None]
        q = queue.Queue()

        # ── pyte render: flush screen buffer to tk.Text ────────────────────
        def _render_pyte():
            """Re-render the full pyte screen buffer into the Text widget."""
            out.config(state=tk.NORMAL)
            out.delete('1.0', tk.END)
            for row_idx in sorted(_screen.buffer.keys()):
                row = _screen.buffer[row_idx]
                for col_idx in sorted(row.keys()):
                    char = row[col_idx]
                    if not char.data:
                        continue
                    tags = []
                    fg = char.fg
                    if fg and fg != 'default':
                        tag = f'fg_{fg}'
                        if tag in out.tag_names():
                            tags.append(tag)
                        else:
                            # Hex colour from pyte (e.g. "color123" or hex)
                            try:
                                out.tag_config(tag, foreground=f'#{fg}' if len(fg) == 6 else fg)
                                tags.append(tag)
                            except Exception:
                                pass
                    bg = char.bg
                    if bg and bg != 'default':
                        tag = f'bg_{bg}'
                        if tag not in out.tag_names():
                            try:
                                out.tag_config(tag, background=f'#{bg}' if len(bg) == 6 else bg)
                            except Exception:
                                pass
                        tags.append(tag)
                    if char.bold:
                        tags.append('_bold')
                    if char.italics:
                        tags.append('_dim')
                    out.insert(tk.END, char.data, tuple(tags) if tags else ())
                out.insert(tk.END, '\n')
            out.config(state=tk.DISABLED)
            out.see(tk.END)

        # ── simple append (fallback / info messages) ────────────────────────
        def _append(text, tag=None):
            out.config(state=tk.NORMAL)
            out.insert(tk.END, text, (tag,) if tag else ())
            out.config(state=tk.DISABLED)
            out.see(tk.END)

        def _flush_queue():
            dirty = False
            while not q.empty():
                raw_bytes, is_err = q.get_nowait()
                if raw_bytes is None:           # sentinel: info string in is_err
                    _append(is_err + '\n', '_info')
                    continue
                if _pyte_ok:
                    _stream.feed(raw_bytes)
                    dirty = True
                else:
                    # Strip ANSI codes and append plain
                    import re as _re
                    text = raw_bytes.decode('utf-8', errors='replace')
                    text = _re.sub(r'\x1b\[[0-9;?]*[a-zA-Z]', '', text)
                    text = _re.sub(r'\x1b\][^\x07]*\x07', '', text)
                    _append(text, '_error' if is_err else None)
            if dirty and _pyte_ok:
                _render_pyte()
            if not stop_event.is_set():
                win.after(50, _flush_queue)

        def _on_close():
            stop_event.set()
            if ws_holder[0]:
                try:
                    ws_holder[0].close()
                except Exception:
                    pass
            win.destroy()

        win.protocol('WM_DELETE_WINDOW', _on_close)

        def _ws_thread():
            import websocket as ws_lib
            url = (f'{self._rancher_url.replace("https://","wss://").replace("http://","ws://")}'
                   f'/k8s/clusters/{self._cluster_id}'
                   f'/api/v1/namespaces/{ns}/pods/{pod_name}/exec'
                   f'?command=/bin/bash&stdin=1&stdout=1&stderr=1&tty=1'
                   f'&container={container}')
            headers = [f'Authorization: Bearer {self._rancher_token}']

            def on_open(ws):
                ws_holder[0] = ws
                q.put((None, f'Connected to container shell. Type commands below.\n{"─"*60}'))

            def on_message(ws, msg):
                if isinstance(msg, bytes) and len(msg) > 1:
                    channel = msg[0]
                    if channel in (1, 2):           # stdout=1, stderr=2
                        q.put((msg[1:], channel == 2))
                elif isinstance(msg, str):
                    q.put((msg.encode('utf-8', errors='replace'), False))

            def on_error(ws, err):
                q.put((None, f'\n[ERROR] {err}'))

            def on_close(ws, *a):
                q.put((None, '\n[Connection closed]'))

            try:
                wsa = ws_lib.WebSocketApp(
                    url, header=headers,
                    on_open=on_open, on_message=on_message,
                    on_error=on_error, on_close=on_close)
                wsa.run_forever(sslopt={'cert_reqs': ssl.CERT_NONE})
            except Exception as e:
                q.put((None, f'[WebSocket error: {e}]'))

        def _send_command(*_):
            cmd = cmd_var.get()
            if not cmd:
                return
            history.append(cmd)
            hist_idx[0] = len(history)
            cmd_var.set('')
            ws = ws_holder[0]
            if ws:
                try:
                    ws.send(b'\x00' + (cmd + '\n').encode(), opcode=0x2)
                except Exception as e:
                    _append(f'[Send error: {e}]\n', '_error')
            else:
                _append('[Not connected]\n', '_error')

        def _history_up(_):
            if history and hist_idx[0] > 0:
                hist_idx[0] -= 1
                cmd_var.set(history[hist_idx[0]])
            return 'break'

        def _history_down(_):
            if hist_idx[0] < len(history) - 1:
                hist_idx[0] += 1
                cmd_var.set(history[hist_idx[0]])
            else:
                hist_idx[0] = len(history)
                cmd_var.set('')
            return 'break'

        cmd_entry.bind('<Return>',    _send_command)
        cmd_entry.bind('<Up>',        _history_up)
        cmd_entry.bind('<Down>',      _history_down)
        cmd_entry.bind('<Control-c>', lambda _: (
            ws_holder[0].send(b'\x00\x03', opcode=0x2) if ws_holder[0] else None))
        cmd_entry.bind('<Tab>',       lambda _: (
            ws_holder[0].send(b'\x00\x09', opcode=0x2) if ws_holder[0] else None) or 'break')

        tk.Button(ib, text='Send', command=_send_command,
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=4)
        tk.Button(ib, text='Close', command=_on_close,
                  bg=BG3, fg=ERROR, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=4).pack(side=tk.LEFT)

        quick_cmds = [
            ('ls -la', 'ls -la'), ('ps aux', 'ps aux'),
            ('df -h', 'df -h'), ('free -m', 'free -m'),
            ('env | sort', 'env | sort'),
            ('cat /etc/hosts', 'cat /etc/hosts'),
            ('curl localhost:8080/health',
             'curl -s localhost:8080/health 2>/dev/null || echo "no health endpoint"'),
            ('whoami', 'whoami'),
        ]
        for label, cmd in quick_cmds:
            def _make_cmd(c):
                return lambda: (cmd_var.set(c), _send_command())
            tk.Button(qb, text=label, command=_make_cmd(cmd),
                      bg=BG4, fg=ACCENT2, font=('Courier New', 7),
                      relief=tk.FLAT, padx=4, pady=1
                      ).pack(side=tk.LEFT, padx=1, pady=2)

        win.after(100, _flush_queue)
        threading.Thread(target=_ws_thread, daemon=True).start()

    # ── Cluster / namespace toggles ───────────────────────────────────────
    def _on_cluster_change(self):
        key = self._cluster_var.get()
        info = CLUSTERS[key]
        self._cluster_id  = info['id']
        self._cluster_env = info['env']
        self._exec_ok     = info['exec_ok']
        if not self._exec_ok:
            self._exec_btn.config(state=tk.DISABLED, bg=BG3, fg=FG2)
            self._exec_label.config(
                text=f'⚠ Exec disabled in {key}')
        else:
            self._exec_btn.config(state=tk.NORMAL, bg=ACCENT2, fg='black')
            self._exec_label.config(text='')
        self._load_namespaces()
        self._refresh()

    def _on_all_ns_toggle(self):
        self._all_namespaces = self._all_ns_var.get()
        state = tk.DISABLED if self._all_namespaces else tk.NORMAL
        self._ns_combo.config(state=state)
        self._refresh()

    # ── Auto-refresh ──────────────────────────────────────────────────────
    def _toggle_auto_refresh(self):
        if self._ar_job:
            self.after_cancel(self._ar_job)
            self._ar_job = None
        if self._auto_refresh.get():
            self._schedule_auto_refresh()

    def _schedule_auto_refresh(self):
        self._refresh()
        secs = max(10, self._refresh_secs.get())
        self._ar_job = self.after(secs * 1000, self._schedule_auto_refresh)

    # ── Status helpers ────────────────────────────────────────────────────
    def _set_status(self, msg, color=FG2):
        self._status_msg.set(msg)
        # find the status label and recolor
        for w in self.winfo_children():
            if isinstance(w, tk.Frame):
                for c in w.winfo_children():
                    if isinstance(c, tk.Label) and c.cget('textvariable'):
                        try:
                            c.config(fg=color)
                        except Exception:
                            pass

    # ── Context builder ───────────────────────────────────────────────────
    def build_context(self):
        ctx = 'K8S EXPLORER CONTEXT\n\n'
        ctx += f'Cluster: {self._cluster_var.get()} ({self._cluster_id})\n'
        ctx += f'Namespace: {"ALL" if self._all_namespaces else self._namespace}\n\n'
        if self._pod_data:
            counts: dict = {}
            for p in self._pod_data:
                _, tag = _pod_status(p)
                counts[tag] = counts.get(tag, 0) + 1
            ctx += f'Pods: {len(self._pod_data)} total\n'
            for tag, n in sorted(counts.items()):
                ctx += f'  {tag}: {n}\n'
            problems = [p for p in self._pod_data
                        if _pod_status(p)[1] in ('error', 'crashloop', 'degraded')]
            if problems:
                ctx += f'\nProblem pods ({len(problems)}):\n'
                for p in problems[:10]:
                    s, _ = _pod_status(p)
                    ctx += (f'  {p["metadata"].get("namespace","")}'
                            f'/{p["metadata"]["name"]} — {s}\n')
        return ctx


# ── Factory ───────────────────────────────────────────────────────────────
def create_widget(parent, context_builder_callback=None):
    return K8sExplorerWidget(parent, context_builder_callback)
