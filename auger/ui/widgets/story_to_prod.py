"""
Story to Prod Widget — Full Pipeline Visibility
Jira Story → Branch/PR → Jenkins Build → Artifactory Image → Flux Config → Env Status → Prod

Phase 1: Read-only pipeline view. Every stage clickable for detail.
Phase 2 (TODO): Promote button creates Flux PR.
Phase 3 (TODO): AI deployment doc generation.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
import json
import re
import os
import time
import webbrowser
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
import requests
import yaml

try:
    from auger.tools.stakeholder_mention import mention_on_block
except ImportError:
    def mention_on_block(**kwargs):
        return {'sent': False, 'error': 'stakeholder_mention not available'}

# ── Colour palette ─────────────────────────────────────────────────────────
BG   = '#1e1e1e'
BG2  = '#252526'
BG3  = '#2d2d2d'
BG4  = '#333333'
FG   = '#e0e0e0'
FG2  = '#a0a0a0'
ACCENT  = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR   = '#f44747'
WARNING = '#ce9178'
SUCCESS = '#4ec9b0'
YELLOW  = '#dcdcaa'
PURPLE  = '#c586c0'
ORANGE  = '#ff8c00'
BLUE    = '#569cd6'

# ── Flux config repos cloned locally ───────────────────────────────────────
# Paths where we clone/cache the flux repos for fast YAML parsing
FLUX_CACHE_DIR = Path.home() / '.auger' / 'flux_cache'

# Service → GHE repo mapping (name used in Jenkins + flux files)
SERVICE_REPO_MAP = {
    'accrual':              'core-assist-accrual',
    'agreement':            'core-assist-agreement',
    'assist1':              'core-assist-assist1',
    'assist2-services':     'core-assist-assist2',
    'assist2-web':          'core-assist-assist2-web',
    'billing':              'core-assist-billing',
    'cm-static-content':    'core-assist-cm-static-content',
    'cprm':                 'core-assist-cprm',
    'document-management':  'core-assist-document-management',
    'dojo':                 'core-assist-dojo',
    'esign-document':       'core-assist-esign-document',
    'fpds-integration':     'core-assist-fpds-integration',
    'funding-service':      'core-assist-funding-service',
    'gsa-pay-gov':          'core-assist-gsa-pay-gov',
    'handle-email':         'core-assist-handle-email',
    'ia-service':           'core-assist-ia-service',
    'idm-service':          'core-assist-idm-service',
    'portal':               'core-assist-portal',
    'portal-web':           'core-assist-portal-web',
    'reports':              'core-assist-reports',
    'support-tools':        'core-assist-support-tools',
    'support-tools-web':    'core-assist-support-tools-web',
    'timekeeping':          'core-assist-timekeeping',
    'timekeeping-web':      'core-assist-timekeeping-web',
}

# Reverse map
REPO_SERVICE_MAP = {v: k for k, v in SERVICE_REPO_MAP.items()}

ALL_SERVICES = sorted(SERVICE_REPO_MAP.keys())

# Environment definitions for Flux config
# (env_label, flux_repo, path_pattern)
ENVS = [
    ('DEV01',    'dev',      'development/dev01'),
    ('DEV09',    'dev',      'development/dev09'),
    ('STAGING01','staging',  'staging/stage01'),
    ('STAGING06','staging',  'staging/stage06'),
    ('PROD',     'prod',     'production'),
]

# ── Icon ────────────────────────────────────────────────────────────────────
def make_icon(size=18, color='#4ec9b0'):
    from PIL import Image, ImageDraw
    import math
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    # Draw a pipeline arrow chain
    y = s2 // 2
    step = s2 // 5
    for i in range(4):
        x = m + i * step
        d.ellipse([x, y - m*2, x + m*3, y + m*2], fill=color)
        if i < 3:
            d.line([(x + m*3, y), (x + step, y)], fill=color, width=m)
    # rocket tip at end
    x = m + 4 * step
    pts = [(x, y - m*3), (x + m*4, y), (x, y + m*3)]
    d.polygon(pts, fill=color)
    return img.resize((size, size), Image.LANCZOS)


try:
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw, ImageTk as _PILImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def _make_s2p_jira_icon(size=14, color='#5db0d7'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.rectangle([s2//4, s2//8, 3*s2//4, 7*s2//8], outline=color, width=m)
    d.line([(s2//4+m*2, s2//3), (3*s2//4-m*2, s2//3)], fill=color, width=m)
    d.line([(s2//4+m*2, s2//2), (3*s2//4-m*2, s2//2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_branch_icon(size=14, color='#4ec9b0'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.ellipse([s2//2-m*2, m, s2//2+m*2, m*5], fill=color)
    d.ellipse([s2//4-m*2, s2-m*5, s2//4+m*2, s2-m], fill=color)
    d.ellipse([3*s2//4-m*2, s2-m*5, 3*s2//4+m*2, s2-m], fill=color)
    d.line([(s2//2, m*5), (s2//2, s2//2)], fill=color, width=m)
    d.line([(s2//2, s2//2), (s2//4, s2-m*5)], fill=color, width=m)
    d.line([(s2//2, s2//2), (3*s2//4, s2-m*5)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_localenv_icon(size=14, color='#569cd6'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.rectangle([m*2, m*3, s2-m*2, s2-m*2], outline=color, width=m)
    d.line([(m*2, m*3+m*3), (s2-m*2, m*3+m*3)], fill=color, width=m)
    d.rectangle([s2//2-m*2, m*3-m*2, s2//2+m*2, m*3], fill=color)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_dev_icon(size=14, color='#dcdcaa'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.rectangle([m, m*2, s2-m, s2-m*4], outline=color, width=m)
    d.line([(s2//3, s2-m*4), (s2//3, s2-m*2)], fill=color, width=m)
    d.line([(2*s2//3, s2-m*4), (2*s2//3, s2-m*2)], fill=color, width=m)
    d.line([(s2//4, s2-m*2), (3*s2//4, s2-m*2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_pr_icon(size=14, color='#c586c0'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.ellipse([m, m, m*5, m*5], outline=color, width=m)
    d.ellipse([s2-m*5, s2-m*5, s2-m, s2-m], outline=color, width=m)
    d.line([(m*3, m*5), (s2-m*3, s2-m*5)], fill=color, width=m)
    d.polygon([(s2-m*3, s2-m*8), (s2-m*3, s2-m*5), (s2-m*6, s2-m*5)], fill=color)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_jenkins_icon(size=14, color='#ce9178'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    cx, cy = s2//2, s2//2
    r = s2//2 - m*2
    d.ellipse([cx-r, cy-r, cx+r, cy+r], outline=color, width=m)
    ri = r - m*2
    d.ellipse([cx-ri, cy-ri, cx+ri, cy+ri], outline=color, width=m)
    d.line([(cx, m), (cx, m*3)], fill=color, width=m)
    d.line([(cx, s2-m*3), (cx, s2-m)], fill=color, width=m)
    d.line([(m, cy), (m*3, cy)], fill=color, width=m)
    d.line([(s2-m*3, cy), (s2-m, cy)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_image_icon(size=14, color='#4ec9b0'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.rectangle([m*2, m*4, s2-m*2, s2-m*2], outline=color, width=m)
    d.polygon([(s2//4, m*4), (3*s2//4, m*4), (s2//2, m)], outline=color)
    d.line([(s2//4, m*4), (s2//4, m*4+m*2)], fill=color, width=m)
    d.line([(3*s2//4, m*4), (3*s2//4, m*4+m*2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_flux_icon(size=14, color='#569cd6'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.line([(s2//2, m), (s2//2, s2//2)], fill=color, width=m)
    d.line([(s2//2, s2//2), (m*2, s2-m*2)], fill=color, width=m)
    d.line([(s2//2, s2//2), (s2-m*2, s2-m*2)], fill=color, width=m)
    d.ellipse([s2//2-m*3, m, s2//2+m*3, m*7], outline=color, width=m)
    d.line([(m, s2-m*2), (s2-m, s2-m*2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_s2p_pods_icon(size=14, color='#4ec9b0'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    import math
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    cx, cy = s2 / 2, s2 / 2
    r = s2 / 2 - m * 2
    pts = [(cx + r * math.cos(math.radians(i * 60 - 30)),
            cy + r * math.sin(math.radians(i * 60 - 30))) for i in range(6)]
    d.polygon(pts, outline=color)
    return img.resize((size, size), Image.LANCZOS)


# ── Helpers ─────────────────────────────────────────────────────────────────
def _ts_age(ts_ms):
    if not ts_ms:
        return '?'
    try:
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        delta = datetime.now(timezone.utc) - dt
        s = int(delta.total_seconds())
        if s < 60:    return f'{s}s ago'
        if s < 3600:  return f'{s//60}m ago'
        if s < 86400: return f'{s//3600}h ago'
        return f'{s//86400}d ago'
    except Exception:
        return '?'

def _short_tag(tag):
    """Shorten image tag to key parts."""
    if not tag:
        return '—'
    # release-ASSIST_4.4.5.0_DME-BUILD30-65f60c2-1772032707892
    m = re.match(r'release-ASSIST_([\d.]+_\w+)-BUILD(\d+)-([0-9a-f]+)', tag)
    if m:
        return f'{m.group(1)}-B{m.group(2)}-{m.group(3)[:7]}'
    return tag[-40:] if len(tag) > 40 else tag


# ════════════════════════════════════════════════════════════════════════════
class StoryToProdWidget(tk.Frame):
    """Story → Prod Pipeline View Widget."""

    WIDGET_TITLE    = 'Story → Prod'
    WIDGET_ICON_COLOR = '#4ec9b0'
    WIDGET_ICON_FUNC = staticmethod(make_icon)

    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self.context_builder_callback = context_builder_callback

        load_dotenv(Path.home() / '.auger' / '.env')
        self._ghe_url   = os.environ.get('GHE_URL', 'https://github.helix.gsa.gov')
        self._ghe_token = os.environ.get('GHE_TOKEN', '')
        self._jenkins_url   = os.environ.get('JENKINS_URL', 'https://jenkins-mcaas.helix.gsa.gov')
        self._jenkins_user  = os.environ.get('JENKINS_USER', '')
        self._jenkins_token = os.environ.get('JENKINS_API_TOKEN', '')
        self._artifactory_url = os.environ.get('ARTIFACTORY_URL', 'https://artifactory.helix.gsa.gov')
        self._artifactory_key = os.environ.get('ARTIFACTORY_API_KEY', '')
        self._rancher_url   = os.environ.get('RANCHER_URL', '').rstrip('/')
        self._rancher_token = os.environ.get('RANCHER_BEARER_TOKEN', '')
        self._jira_url      = os.environ.get('JIRA_BASE_URL', '')
        self._jira_user     = os.environ.get('JIRA_USERNAME', '')
        self._jira_token    = os.environ.get('JIRA_API_TOKEN', '')

        self._pipeline_data  = {}   # stage → data dict
        self._story_key      = tk.StringVar()
        self._service_var    = tk.StringVar()
        self._status_msg     = tk.StringVar(value='Enter a Jira story key to begin')
        self._loading        = False

        # Pipeline state
        self._skip_local_env = tk.BooleanVar(value=False)
        self._loop_a_iters   = 0   # Local Env iteration count
        self._loop_b_iters   = 0   # Dev Deploy iteration count
        self._active_stage   = None
        self._tab_icons      = {}   # GC guard for PIL PhotoImages

        FLUX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self._flux_dev_path  = FLUX_CACHE_DIR / 'assist-flux-config'
        self._flux_prod_path = FLUX_CACHE_DIR / 'assist-prod-flux-config'

        self._build_ui()
        self._sync_flux_repos_bg()

    # ── API helpers ──────────────────────────────────────────────────────────
    def _ghe_get(self, path, timeout=15):
        url = f'{self._ghe_url}/api/v3/{path}'
        r = requests.get(url, headers={'Authorization': f'token {self._ghe_token}'},
                         verify=False, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def _jenkins_get(self, path, timeout=15):
        url = f'{self._jenkins_url}/{path}'
        r = requests.get(url, auth=(self._jenkins_user, self._jenkins_token),
                         verify=False, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def _artifactory_get(self, path, timeout=15):
        url = f'{self._artifactory_url}/artifactory/{path}'
        r = requests.get(url, headers={'X-JFrog-Art-Api': self._artifactory_key},
                         verify=False, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def _rancher_get(self, path, timeout=15):
        url = f'{self._rancher_url}/{path}'
        r = requests.get(url, headers={'Authorization': f'Bearer {self._rancher_token}'},
                         verify=False, timeout=timeout)
        r.raise_for_status()
        return r.json()

    def _jira_get(self, path, timeout=15):
        url = f'{self._jira_url}/rest/api/2/{path}'
        r = requests.get(url, auth=(self._jira_user, self._jira_token),
                         verify=False, timeout=timeout)
        r.raise_for_status()
        return r.json()

    # ── UI Build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        self._build_search_bar()
        self._build_pipeline_canvas()
        self._build_detail_pane()
        self._build_status_bar()

    def _build_search_bar(self):
        sb = tk.Frame(self, bg=BG2, pady=6)
        sb.pack(fill=tk.X, padx=0, pady=0)

        tk.Label(sb, text='Story Key:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(10, 4))

        e = tk.Entry(sb, textvariable=self._story_key, width=20,
                     bg=BG3, fg=FG, insertbackground=FG,
                     font=('Segoe UI', 11, 'bold'))
        e.pack(side=tk.LEFT, padx=4)
        e.bind('<Return>', lambda _: self._run_pipeline())
        # Pre-populate with current active story
        placeholder = 'e.g. ASSIST3-38045'
        if not self._story_key.get():
            self._story_key.set('ASSIST3-31091')
            e.config(fg=FG)
        e.bind('<FocusIn>',  lambda _: (e.delete(0, tk.END), e.config(fg=FG))
               if e.get() == placeholder else None)
        e.bind('<FocusOut>', lambda _: (e.insert(0, placeholder), e.config(fg=FG2))
               if not e.get() else None)

        tk.Label(sb, text='Service:', fg=FG2, bg=BG2,
                 font=('Segoe UI', 10)).pack(side=tk.LEFT, padx=(12, 4))
        svc_cb = ttk.Combobox(sb, textvariable=self._service_var,
                              values=['(auto-detect)'] + ALL_SERVICES,
                              width=22, font=('Segoe UI', 9))
        svc_cb.set('(auto-detect)')
        svc_cb.pack(side=tk.LEFT, padx=4)

        tk.Button(sb, text='Run Pipeline', command=self._run_pipeline,
                  bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                  relief=tk.FLAT, padx=16, pady=4).pack(side=tk.LEFT, padx=8)

        tk.Button(sb, text='Refresh Flux', command=self._sync_flux_repos_bg,
                  bg=BG3, fg=FG2, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=2)

        self._flux_label = tk.Label(sb, text='Flux: syncing…', fg=FG2, bg=BG2,
                                    font=('Segoe UI', 8, 'italic'))
        self._flux_label.pack(side=tk.RIGHT, padx=10)

    def _build_pipeline_canvas(self):
        """Horizontal pipeline flow with two collaboration loops."""
        outer = tk.Frame(self, bg=BG3, height=210)
        outer.pack(fill=tk.X, padx=6, pady=4)
        outer.pack_propagate(False)

        # scrollable horizontally
        self._pipeline_canvas = tk.Canvas(outer, bg=BG3, height=210,
                                          highlightthickness=0)
        hsb = ttk.Scrollbar(outer, orient=tk.HORIZONTAL,
                            command=self._pipeline_canvas.xview)
        self._pipeline_canvas.configure(xscrollcommand=hsb.set)
        hsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._pipeline_canvas.pack(fill=tk.BOTH, expand=True)

        self._stage_frames = {}
        self._draw_empty_pipeline()

    def _build_detail_pane(self):
        """Lower section: tabbed detail for selected stage."""
        style = ttk.Style()
        style.configure('S2P.TNotebook', background=BG2, borderwidth=0)
        style.configure('S2P.TNotebook.Tab', background=BG3, foreground=FG,
                         padding=[10, 4], font=('Segoe UI', 9, 'bold'))
        style.map('S2P.TNotebook.Tab',
                  background=[('selected', BG4)],
                  foreground=[('selected', ACCENT2)])

        self._detail_nb = ttk.Notebook(self, style='S2P.TNotebook')
        self._detail_nb.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0, 4))

        self._jira_frame       = tk.Frame(self._detail_nb, bg=BG)
        self._branch_frame     = tk.Frame(self._detail_nb, bg=BG)
        self._local_env_frame  = tk.Frame(self._detail_nb, bg=BG)
        self._dev_frame        = tk.Frame(self._detail_nb, bg=BG)
        self._pr_frame         = tk.Frame(self._detail_nb, bg=BG)
        self._build_frame      = tk.Frame(self._detail_nb, bg=BG)
        self._image_frame      = tk.Frame(self._detail_nb, bg=BG)
        self._flux_frame       = tk.Frame(self._detail_nb, bg=BG)
        self._pods_frame       = tk.Frame(self._detail_nb, bg=BG)

        self._detail_nb.add(self._jira_frame,      text='  Jira Story  ')
        self._detail_nb.add(self._branch_frame,    text='  Branch  ')
        self._detail_nb.add(self._local_env_frame, text='  Local Env  ')
        self._detail_nb.add(self._dev_frame,       text='  Dev Deploy  ')
        self._detail_nb.add(self._pr_frame,        text='  PR  ')
        self._detail_nb.add(self._build_frame,     text='  Jenkins Build  ')
        self._detail_nb.add(self._image_frame,     text='  Image Tags  ')
        self._detail_nb.add(self._flux_frame,      text='  Flux / Envs  ')
        self._detail_nb.add(self._pods_frame,      text='  Pod Status  ')
        self.after(0, self._apply_s2p_tab_icons)

        self._build_jira_panel()
        self._build_branch_panel()
        self._build_local_env_panel()
        self._build_dev_panel()
        self._build_pr_panel()
        self._build_jenkins_panel()
        self._build_image_panel()
        self._build_flux_panel()
        self._build_pods_panel()

    def _build_status_bar(self):
        sb = tk.Frame(self, bg=BG2, height=22)
        sb.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_lbl = tk.Label(sb, textvariable=self._status_msg,
                                    fg=FG2, bg=BG2, font=('Segoe UI', 8),
                                    anchor=tk.W)
        self._status_lbl.pack(side=tk.LEFT, padx=8)
        self._spinner_lbl = tk.Label(sb, text='', fg=ACCENT, bg=BG2,
                                     font=('Segoe UI', 8))
        self._spinner_lbl.pack(side=tk.RIGHT, padx=8)

    # ── Jira panel ───────────────────────────────────────────────────────────
    def _apply_s2p_tab_icons(self):
        """Apply emoji labels to detail sub-tabs via safe nb.tab() calls.
        nb.tab() does not trigger SIGSEGV — only nb.add(text=...) with emoji is unsafe."""
        tabs_config = [
            (self._jira_frame,      '📋 Jira Story'),
            (self._branch_frame,    '🌿 Branch'),
            (self._local_env_frame, '🐳 Local Env'),
            (self._dev_frame,       '💻 Dev Deploy'),
            (self._pr_frame,        '🔀 PR'),
            (self._build_frame,     '🔨 Jenkins Build'),
            (self._image_frame,     '📦 Image Tags'),
            (self._flux_frame,      '⚓ Flux / Envs'),
            (self._pods_frame,      '⬡ Pod Status'),
        ]
        for frame, label in tabs_config:
            try:
                self._detail_nb.tab(frame, text=f'  {label}  ')
            except Exception:
                pass

    def _build_jira_panel(self):
        f = self._jira_frame
        self._jira_text = scrolledtext.ScrolledText(
            f, bg='#0d0d0d', fg=FG, font=('Segoe UI', 9),
            wrap=tk.WORD, state=tk.DISABLED, height=10)
        self._jira_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._jira_text.tag_config('key',    foreground=ACCENT2, font=('Segoe UI', 11, 'bold'))
        self._jira_text.tag_config('label',  foreground=FG2)
        self._jira_text.tag_config('value',  foreground=FG)
        self._jira_text.tag_config('status', foreground=YELLOW, font=('Segoe UI', 9, 'bold'))
        self._jira_text.tag_config('link',   foreground=BLUE)
        self._jira_text.tag_config('desc',   foreground=FG2, font=('Segoe UI', 8))

    # ── Branch panel ──────────────────────────────────────────────────────────
    def _build_branch_panel(self):
        """Branch stage: create/show feature branch across repos."""
        f = self._branch_frame

        ab = tk.Frame(f, bg=BG2)
        ab.pack(fill=tk.X, padx=4, pady=2)
        tk.Button(ab, text='Open in GHE', command=self._open_pr_url,
                  bg=BG3, fg=FG, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)

        self._branch_text = scrolledtext.ScrolledText(
            f, bg='#0d0d0d', fg=FG, font=('Segoe UI', 9),
            wrap=tk.WORD, state=tk.DISABLED, height=10)
        self._branch_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._branch_text.tag_config('header', foreground=ACCENT2, font=('Segoe UI', 10, 'bold'))
        self._branch_text.tag_config('label',  foreground=FG2)
        self._branch_text.tag_config('value',  foreground=FG)
        self._branch_text.tag_config('ok',     foreground=SUCCESS)
        self._branch_text.tag_config('warn',   foreground=WARNING)
        self._branch_text.tag_config('detail', foreground=FG2, font=('Segoe UI', 8))

        self._branch_text.config(state=tk.NORMAL)
        self._branch_text.insert(tk.END, 'Branch Stage\n', 'header')
        self._branch_text.insert(tk.END, '\nRun the pipeline to detect feature branches.\n', 'detail')
        self._branch_text.insert(tk.END, '\nNaming convention: ', 'label')
        self._branch_text.insert(tk.END, 'feature/{STORY_KEY}-{slug}\n', 'value')
        self._branch_text.config(state=tk.DISABLED)

    # ── Local Env panel ───────────────────────────────────────────────────────
    def _build_local_env_panel(self):
        """Local Env stage: optional docker-based dev/test loop before Dev Deploy."""
        f = self._local_env_frame

        # Header + Skip toggle
        ab = tk.Frame(f, bg=BG2)
        ab.pack(fill=tk.X, padx=4, pady=4)

        tk.Label(ab, text='Local Environment  ', fg=ACCENT2, bg=BG2,
                 font=('Segoe UI', 10, 'bold')).pack(side=tk.LEFT, padx=4)

        skip_cb = tk.Checkbutton(
            ab, text='Skip Local Env (config-only / infra fix)',
            variable=self._skip_local_env,
            command=self._on_skip_local_env_toggle,
            fg=WARNING, bg=BG2, selectcolor=BG3, activebackground=BG2,
            font=('Segoe UI', 9))
        skip_cb.pack(side=tk.LEFT, padx=10)

        # Loop counter
        self._loop_a_label = tk.Label(ab, text='Loop A: 0 iterations',
                                       fg=FG2, bg=BG2, font=('Segoe UI', 8, 'italic'))
        self._loop_a_label.pack(side=tk.RIGHT, padx=10)

        # Info/log area
        self._local_env_text = scrolledtext.ScrolledText(
            f, bg='#0d0d0d', fg=FG, font=('Segoe UI', 9),
            wrap=tk.WORD, state=tk.DISABLED, height=10)
        self._local_env_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))
        self._local_env_text.tag_config('header', foreground=ACCENT2, font=('Segoe UI', 10, 'bold'))
        self._local_env_text.tag_config('label',  foreground=FG2)
        self._local_env_text.tag_config('value',  foreground=FG)
        self._local_env_text.tag_config('skip',   foreground=WARNING)
        self._local_env_text.tag_config('detail', foreground=FG2, font=('Segoe UI', 8))
        self._local_env_text.tag_config('cmd',    foreground=YELLOW, font=('Courier New', 9))

        self._local_env_text.config(state=tk.NORMAL)
        self._local_env_text.insert(tk.END, 'Local Env — Collaboration Loop A\n', 'header')
        self._local_env_text.insert(tk.END,
            '\nUse this stage when the fix involves application code that can be\n'
            'validated with docker-compose before deploying to Dev.\n\n', 'detail')
        self._local_env_text.insert(tk.END, 'When to skip:\n', 'label')
        self._local_env_text.insert(tk.END,
            '  • Flux config / infra-only changes (like ASSIST3-31091)\n'
            '  • Changes requiring real TLS termination (Istio/ALB)\n'
            '  • Secrets or environment-specific configs\n\n', 'detail')
        self._local_env_text.insert(tk.END, 'Typical local test:\n', 'label')
        self._local_env_text.insert(tk.END,
            '  docker-compose up --build\n'
            '  curl -I http://localhost:8080/hub/login  # check Set-Cookie headers\n', 'cmd')
        self._local_env_text.config(state=tk.DISABLED)

    def _on_skip_local_env_toggle(self):
        """Update canvas stage when skip checkbox toggled."""
        if self._skip_local_env.get():
            self._update_stage('local_env', 'unknown', 'SKIPPED')
            self._local_env_log('⏭  Local Env skipped — proceeding straight to Dev Deploy\n', 'skip')
        else:
            self._update_stage('local_env', 'pending', 'pending')
            self._local_env_log('✅ Local Env enabled\n', 'value')

    def _local_env_log(self, text, tag='value'):
        self._local_env_text.config(state=tk.NORMAL)
        self._local_env_text.insert(tk.END, text, tag)
        self._local_env_text.config(state=tk.DISABLED)
        self._local_env_text.see(tk.END)

    # ── PR panel ─────────────────────────────────────────────────────────────
    def _build_pr_panel(self):
        f = self._pr_frame

        # action bar
        ab = tk.Frame(f, bg=BG2)
        ab.pack(fill=tk.X, padx=4, pady=2)
        tk.Button(ab, text='Open in GHE', command=self._open_pr_url,
                  bg=BG3, fg=FG, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)

        cols = ('repo', 'branch', 'pr', 'status', 'checks', 'updated')
        self._pr_tree = ttk.Treeview(f, columns=cols, show='headings',
                                     selectmode='browse', height=6)
        ws = dict(repo=160, branch=260, pr=50, status=80, checks=80, updated=90)
        hs = dict(repo='Repo', branch='Branch', pr='PR#', status='Status',
                  checks='Checks', updated='Updated')
        for c in cols:
            self._pr_tree.heading(c, text=hs[c])
            self._pr_tree.column(c, width=ws[c], anchor=tk.W)
        self._style_tree(self._pr_tree)
        vsb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._pr_tree.yview)
        self._pr_tree.configure(yscrollcommand=vsb.set)
        self._pr_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._pr_tree.tag_configure('merged', background='#1a1a3a', foreground=PURPLE)
        self._pr_tree.tag_configure('open',   background='#1a3a1a', foreground=SUCCESS)
        self._pr_tree.tag_configure('closed', background=BG3,       foreground=FG2)
        self._pr_tree.tag_configure('fail',   background='#3a0000', foreground=ERROR)

        self._pr_url = ''

    # ── Dev Deploy panel ──────────────────────────────────────────────────────
    def _build_dev_panel(self):
        """Dev Deploy stage: Auger deploys to Dev namespace, developer validates. Loop B."""
        f = self._dev_frame

        # Action bar
        ab = tk.Frame(f, bg=BG2)
        ab.pack(fill=tk.X, padx=4, pady=2)
        tk.Button(ab, text='@Mention Developer', command=self._mention_developer,
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=10).pack(side=tk.LEFT, padx=4)
        tk.Button(ab, text='@Mention SRE Lead', command=self._mention_sre_lead,
                  bg=BG3, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=2)
        self._mention_event_var = tk.StringVar(value='build_failure')
        events = ['build_failure', 'merge_conflict', 'pr_stale', 'code_question',
                  'flux_pr_needs_approval', 'prod_drift', 'prod_incident',
                  'scope_question', 'priority_question']
        ev_cb = ttk.Combobox(ab, textvariable=self._mention_event_var,
                             values=events, width=26, font=('Segoe UI', 8))
        ev_cb.pack(side=tk.LEFT, padx=6)
        tk.Label(ab, text='event type', fg=FG2, bg=BG2,
                 font=('Segoe UI', 8, 'italic')).pack(side=tk.LEFT)

        # Loop B counter
        self._loop_b_label = tk.Label(ab, text='Loop B: 0 iterations',
                                       fg=FG2, bg=BG2, font=('Segoe UI', 8, 'italic'))
        self._loop_b_label.pack(side=tk.RIGHT, padx=10)

        # Status/log area
        self._dev_text = scrolledtext.ScrolledText(
            f, bg='#0d0d0d', fg=FG, font=('Segoe UI', 9),
            wrap=tk.WORD, state=tk.DISABLED, height=10)
        self._dev_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._dev_text.tag_config('header',  foreground=ACCENT2, font=('Segoe UI', 10, 'bold'))
        self._dev_text.tag_config('label',   foreground=FG2)
        self._dev_text.tag_config('value',   foreground=FG)
        self._dev_text.tag_config('auger',   foreground=BLUE)
        self._dev_text.tag_config('human',   foreground=YELLOW)
        self._dev_text.tag_config('sent',    foreground=SUCCESS)
        self._dev_text.tag_config('error',   foreground=ERROR)
        self._dev_text.tag_config('detail',  foreground=FG2, font=('Segoe UI', 8))

        self._dev_log('Dev Deploy — Collaboration Loop B\n', 'header')
        self._dev_log('\nRun the pipeline to see who is working on this story.\n', 'detail')
        self._dev_log('  💻 Auger  ', 'auger')
        self._dev_log('— deploys to Dev namespace via Flux PR\n', 'detail')
        self._dev_log('  🧑 Human  ', 'human')
        self._dev_log('— validates in Dev Env, reports back; @mentioned when blocked\n', 'detail')

    def _dev_log(self, text, tag='value'):
        self._dev_text.config(state=tk.NORMAL)
        self._dev_text.insert(tk.END, text, tag)
        self._dev_text.config(state=tk.DISABLED)
        self._dev_text.see(tk.END)

    def _mention_developer(self):
        self._fire_mention(role='developer')

    def _mention_sre_lead(self):
        self._fire_mention(role='sre_lead')

    def _fire_mention(self, role: str):
        story_key  = self._pipeline_data.get('story_key', '?')
        event      = self._mention_event_var.get()
        jira_data  = self._pipeline_data.get('jira', {})
        assignee   = (jira_data.get('fields') or {}).get('assignee') or {}
        assignee_email = assignee.get('emailAddress', '')

        # Build detail from pipeline state
        builds = self._pipeline_data.get('builds', [])
        failed = [b for b in builds if b.get('result') == 'FAILURE']
        detail = (f'Build #{failed[0]["build_num"]} failed on `{failed[0]["branch"]}`'
                  if failed else f'Pipeline stage: triggered from {story_key} dev panel')
        link = failed[0].get('url', '') if failed else ''

        self._set_status(f'Sending @mention ({event}) to {role}…', ACCENT)
        self._dev_log(f'\n⟳ Sending @mention: event={event} role={role}\n', 'label')

        def _do():
            result = mention_on_block(
                event=event,
                story_key=story_key,
                stage='Dev',
                detail=detail,
                link=link or None,
                jira_assignee_email=assignee_email or None,
            )
            if result['sent']:
                names = ', '.join(r['name'] for r in result['recipients'])
                self.after(0, self._dev_log,
                           f'✅ @mention sent to: {names}\n', 'sent')
                self.after(0, self._set_status,
                           f'@mention sent → {names}', SUCCESS)
            else:
                self.after(0, self._dev_log,
                           f'❌ Failed: {result["error"]}\n', 'error')
                self.after(0, self._set_status,
                           f'@mention failed: {result["error"]}', ERROR)
            # Log preview of message
            self.after(0, self._dev_log,
                       f'\nMessage preview:\n{result["message"][:300]}\n', 'detail')

        threading.Thread(target=_do, daemon=True).start()

    # ── Jenkins panel ────────────────────────────────────────────────────────
    def _build_jenkins_panel(self):
        f = self._build_frame

        ab = tk.Frame(f, bg=BG2)
        ab.pack(fill=tk.X, padx=4, pady=2)
        tk.Button(ab, text='Open Jenkins', command=self._open_jenkins_url,
                  bg=BG3, fg=FG, font=('Segoe UI', 8), relief=tk.FLAT,
                  padx=6).pack(side=tk.LEFT, padx=2)

        cols = ('service', 'branch', 'build', 'result', 'age', 'url')
        self._build_tree = ttk.Treeview(f, columns=cols, show='headings',
                                        selectmode='browse', height=6)
        ws   = dict(service=120, branch=260, build=60, result=80, age=90, url=60)
        hs   = dict(service='Service', branch='Branch', build='Build#',
                    result='Result', age='Age', url='Link')
        for c in cols:
            self._build_tree.heading(c, text=hs[c])
            self._build_tree.column(c, width=ws[c], anchor=tk.W)
        self._style_tree(self._build_tree)
        vsb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._build_tree.yview)
        self._build_tree.configure(yscrollcommand=vsb.set)
        self._build_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._build_tree.tag_configure('SUCCESS',  background='#1a3a1a', foreground=SUCCESS)
        self._build_tree.tag_configure('FAILURE',  background='#3a0000', foreground=ERROR)
        self._build_tree.tag_configure('ABORTED',  background=BG3,       foreground=FG2)
        self._build_tree.tag_configure('BUILDING', background='#1a2a3a', foreground=YELLOW)

        self._build_tree.bind('<Double-1>', self._open_jenkins_url)
        self._jenkins_url_sel = ''

    # ── Image panel ──────────────────────────────────────────────────────────
    def _build_image_panel(self):
        f = self._image_frame

        cols = ('service', 'tag', 'short', 'created')
        self._image_tree = ttk.Treeview(f, columns=cols, show='headings',
                                        selectmode='browse', height=6)
        ws = dict(service=120, tag=380, short=180, created=120)
        hs = dict(service='Service', tag='Full Tag', short='Short', created='Built')
        for c in cols:
            self._image_tree.heading(c, text=hs[c])
            self._image_tree.column(c, width=ws[c], anchor=tk.W)
        self._style_tree(self._image_tree)
        vsb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._image_tree.yview)
        self._image_tree.configure(yscrollcommand=vsb.set)
        self._image_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

    # ── Flux/Env panel ───────────────────────────────────────────────────────
    def _build_flux_panel(self):
        f = self._flux_frame

        # promote button row
        ab = tk.Frame(f, bg=BG2)
        ab.pack(fill=tk.X, padx=4, pady=2)
        tk.Label(ab, text='Promote image tag to environment:',
                 fg=FG2, bg=BG2, font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=4)
        self._promote_env_var = tk.StringVar(value='DEV01')
        for env_label, _, _ in ENVS[:-1]:  # all except prod
            tk.Radiobutton(ab, text=env_label, variable=self._promote_env_var,
                           value=env_label, bg=BG2, fg=FG, selectcolor=BG3,
                           activebackground=BG2, font=('Segoe UI', 8)
                           ).pack(side=tk.LEFT, padx=3)
        tk.Button(ab, text='Create Flux PR', command=self._create_flux_pr,
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=10).pack(side=tk.LEFT, padx=8)
        tk.Label(ab, text='(2 approvals required for prod)',
                 fg=WARNING, bg=BG2, font=('Segoe UI', 8, 'italic')
                 ).pack(side=tk.LEFT)

        cols = ('env', 'namespace', 'service', 'current_tag', 'short_tag', 'drift')
        self._flux_tree = ttk.Treeview(f, columns=cols, show='headings',
                                       selectmode='browse', height=8)
        ws = dict(env=80, namespace=120, service=120, current_tag=350,
                  short_tag=180, drift=60)
        hs = dict(env='Env', namespace='Namespace', service='Service',
                  current_tag='Image Tag', short_tag='Short', drift='Match?')
        for c in cols:
            self._flux_tree.heading(c, text=hs[c])
            self._flux_tree.column(c, width=ws[c], anchor=tk.W)
        self._style_tree(self._flux_tree)
        vsb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._flux_tree.yview)
        self._flux_tree.configure(yscrollcommand=vsb.set)
        self._flux_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._flux_tree.tag_configure('match',   background='#1a3a1a', foreground=SUCCESS)
        self._flux_tree.tag_configure('behind',  background='#3a2000', foreground=ORANGE)
        self._flux_tree.tag_configure('unknown', background=BG3,       foreground=FG2)

    # ── Pods panel ────────────────────────────────────────────────────────────
    def _build_pods_panel(self):
        f = self._pods_frame

        cols = ('env', 'namespace', 'pod', 'status', 'ready', 'restarts', 'image_tag')
        self._pods_tree = ttk.Treeview(f, columns=cols, show='headings',
                                       selectmode='browse', height=8)
        ws = dict(env=70, namespace=120, pod=220, status=100,
                  ready=60, restarts=65, image_tag=280)
        hs = dict(env='Env', namespace='Namespace', pod='Pod', status='Status',
                  ready='Ready', restarts='↺', image_tag='Running Tag')
        for c in cols:
            self._pods_tree.heading(c, text=hs[c])
            self._pods_tree.column(c, width=ws[c], anchor=tk.W)
        self._style_tree(self._pods_tree)
        vsb = ttk.Scrollbar(f, orient=tk.VERTICAL, command=self._pods_tree.yview)
        self._pods_tree.configure(yscrollcommand=vsb.set)
        self._pods_tree.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self._pods_tree.tag_configure('running',   background='#1a3a1a', foreground=SUCCESS)
        self._pods_tree.tag_configure('pending',   background='#3a3a00', foreground=YELLOW)
        self._pods_tree.tag_configure('error',     background='#3a0000', foreground=ERROR)
        self._pods_tree.tag_configure('unknown',   background=BG3,       foreground=FG2)

    # ── Pipeline canvas ───────────────────────────────────────────────────────
    def _draw_empty_pipeline(self):
        c = self._pipeline_canvas
        c.delete('all')

        # ── Stage definitions ────────────────────────────────────────────────
        # local_env gets a SKIP badge; dev_deploy is the Loop B anchor
        skip = self._skip_local_env.get()
        local_env_color = FG2 if not skip else BG4
        stages = [
            ('📋', 'Jira',       'jira',       FG2),
            ('🌿', 'Branch',     'branch',     FG2),
            ('🐳', 'Local Env',  'local_env',  local_env_color),
            ('💻', 'Dev Deploy', 'dev_deploy', FG2),
            ('🔀', 'PR',         'pr',         FG2),
            ('🔨', 'Jenkins',    'build',      FG2),
            ('📦', 'Image',      'image',      FG2),
            ('⚓', 'Staging',    'flux_stg',   FG2),
            ('🚀', 'PROD',       'flux_prd',   FG2),
        ]
        self._stage_positions = {}
        x = 20
        y = 80
        box_w, box_h = 105, 66
        gap = 28

        for icon, label, key, color in stages:
            if x > 20:
                c.create_line(x - gap, y, x, y, fill=BG4, width=2,
                              arrow=tk.LAST, arrowshape=(8, 10, 4))
            tag = f'stage_{key}'
            c.create_rectangle(x, y - box_h//2, x + box_w, y + box_h//2,
                                fill=BG3, outline=BG4, width=1, tags=(tag,))
            c.create_text(x + box_w//2, y - 16, text=icon,
                          font=('Segoe UI', 14), fill=color, tags=(tag,))
            c.create_text(x + box_w//2, y + 4, text=label,
                          font=('Segoe UI', 8, 'bold'), fill=color, tags=(tag,))
            sub_id = c.create_text(
                x + box_w//2, y + 20, text='—',
                font=('Courier New', 7), fill=FG2, tags=(tag,))
            self._stage_positions[key] = (x, y, box_w, box_h, sub_id)

            # SKIP badge on local_env
            if key == 'local_env' and skip:
                c.create_text(x + box_w//2, y - 30, text='SKIP',
                              font=('Segoe UI', 7, 'bold'), fill=WARNING, tags=(tag,))

            c.tag_bind(tag, '<Button-1>',
                       lambda e, k=key: self._on_stage_click(k))
            c.tag_bind(tag, '<Enter>',
                       lambda e, k=key: self._on_stage_hover(k, True))
            c.tag_bind(tag, '<Leave>',
                       lambda e, k=key: self._on_stage_hover(k, False))

            x += box_w + gap

        # ── Loop arrows (drawn below the stage row) ──────────────────────────
        # Loop A: Local Env ↔ Dev Deploy  (indexes 2 and 3)
        pos_local = self._stage_positions.get('local_env')
        pos_dev   = self._stage_positions.get('dev_deploy')
        if pos_local and pos_dev and not skip:
            lx = pos_local[0] + box_w // 2
            dx = pos_dev[0] + box_w // 2
            loop_y = y + box_h // 2 + 12
            arc_y  = loop_y + 22
            c.create_line(lx, loop_y, lx, arc_y, dx, arc_y, dx, loop_y,
                          fill='#4a4a6a', width=1, smooth=True,
                          arrow=tk.LAST, arrowshape=(6, 8, 3))
            iters_a = self._loop_a_iters
            loop_a_color = PURPLE if iters_a > 0 else '#4a4a6a'
            c.create_text((lx + dx) // 2, arc_y + 8,
                          text=f'↺ Loop A  ({iters_a})',
                          font=('Segoe UI', 7), fill=loop_a_color)

        # Loop B: Dev Deploy self-loop (re-deploy + re-validate)
        if pos_dev:
            dx = pos_dev[0] + box_w // 2
            loop_y2 = y + box_h // 2 + 12
            if skip:
                loop_y2 += 0  # same y since loop A not drawn
            arc_y2 = loop_y2 + 22 if skip else loop_y2 + 22
            lx2 = dx - 30
            rx2 = dx + 30
            c.create_line(dx, loop_y2, rx2, loop_y2, rx2, arc_y2, lx2, arc_y2, lx2, loop_y2,
                          fill='#2a4a4a', width=1, smooth=True,
                          arrow=tk.LAST, arrowshape=(6, 8, 3))
            iters_b = self._loop_b_iters
            loop_b_color = ACCENT2 if iters_b > 0 else '#2a4a4a'
            c.create_text(dx, arc_y2 + 8,
                          text=f'↺ Loop B  ({iters_b})',
                          font=('Segoe UI', 7), fill=loop_b_color)

        c.configure(scrollregion=c.bbox('all'))

    def _update_stage(self, key, status, subtitle='', color=None):
        """Update a pipeline stage box color and subtitle."""
        STATUS_COLORS = {
            'ok':       ('#1a3a1a', SUCCESS),
            'error':    ('#3a0000', ERROR),
            'pending':  ('#3a3a00', YELLOW),
            'running':  ('#1a2a3a', ACCENT),
            'behind':   ('#3a2000', ORANGE),
            'unknown':  (BG3, FG2),
            'loading':  ('#1a1a2a', BLUE),
        }
        bg, fg = STATUS_COLORS.get(status, (BG3, FG2))
        if color:
            fg = color
        c = self._pipeline_canvas
        tag = f'stage_{key}'
        items = c.find_withtag(tag)
        for item in items:
            itype = c.type(item)
            if itype == 'rectangle':
                c.itemconfig(item, fill=bg, outline=fg)
            elif itype == 'text':
                coords = c.coords(item)
                if coords:
                    # subtitle is the lowest text in the box
                    pos = self._stage_positions.get(key)
                    if pos:
                        _, y, _, box_h, sub_id = pos
                        if item == sub_id:
                            c.itemconfig(item, text=subtitle or '—', fill=FG2)
                        else:
                            c.itemconfig(item, fill=fg)

    def _on_stage_click(self, key):
        tab_map = {
            'jira': 0, 'branch': 1, 'local_env': 2, 'dev_deploy': 3,
            'pr': 4, 'build': 5, 'image': 6,
            'flux_stg': 7, 'flux_prd': 7, 'pods': 8,
        }
        idx = tab_map.get(key, 0)
        self._detail_nb.select(idx)

    def _on_stage_hover(self, key, entering):
        c = self._pipeline_canvas
        tag = f'stage_{key}'
        for item in c.find_withtag(tag):
            if c.type(item) == 'rectangle':
                if entering:
                    c.itemconfig(item, outline=ACCENT2)
                else:
                    c.itemconfig(item, outline=BG4)

    # ── Main pipeline runner ─────────────────────────────────────────────────
    def _run_pipeline(self):
        story_key = self._story_key.get().strip().upper()
        if not story_key or story_key == 'E.G. ASSIST3-38045':
            self._set_status('Enter a valid Jira story key', WARNING)
            return
        if not re.match(r'^[A-Z]+-\d+$', story_key):
            self._set_status('Invalid key format. Expected e.g. ASSIST3-38045', ERROR)
            return

        self._pipeline_data = {'story_key': story_key}
        self._clear_all_panels()
        self._draw_empty_pipeline()

        # Auto-skip Local Env for flux/config-only stories
        if story_key == 'ASSIST3-31091':
            self._skip_local_env.set(True)
            self._update_stage('local_env', 'unknown', 'SKIPPED')
            self._update_stage('dev_deploy', 'pending', 'ready')
            self._detail_nb.select(3)  # open Dev Deploy tab

        # Detect service from selection or auto
        svc = self._service_var.get()
        if svc == '(auto-detect)':
            svc = None

        self._set_status(f'Running pipeline for {story_key}…', ACCENT)
        self._set_spinner('⟳ Working…')

        def _pipeline():
            try:
                # Stage 1: Jira
                self.after(0, lambda: self._update_stage('jira', 'loading', 'loading…'))
                jira_data = self._fetch_jira(story_key)
                self._pipeline_data['jira'] = jira_data
                self.after(0, self._render_jira, jira_data)

                # Stage 2: GHE branch/PR
                self.after(0, lambda: self._update_stage('pr', 'loading', 'searching…'))
                pr_data = self._fetch_prs(story_key)
                self._pipeline_data['prs'] = pr_data
                self.after(0, self._render_prs, pr_data)

                # Determine services to track
                services = self._detect_services(story_key, svc, pr_data)
                self._pipeline_data['services'] = services

                # Stage 3: Jenkins builds
                self.after(0, lambda: self._update_stage('build', 'loading', 'building…'))
                build_data = self._fetch_builds(story_key, services)
                self._pipeline_data['builds'] = build_data
                self.after(0, self._render_builds, build_data)

                # Stage 4: Artifactory image tags
                self.after(0, lambda: self._update_stage('image', 'loading', 'pulling…'))
                image_data = self._fetch_images(services)
                self._pipeline_data['images'] = image_data
                self.after(0, self._render_images, image_data)

                # Stage 5 & 6: Flux config (staging, prod)
                self.after(0, lambda: self._update_stage('flux_stg', 'loading', 'reading…'))
                self.after(0, lambda: self._update_stage('flux_prd', 'loading', 'reading…'))
                latest_tags = {svc: self._latest_tag(image_data, svc) for svc in services}
                flux_data = self._fetch_flux_status(services, latest_tags)
                self._pipeline_data['flux'] = flux_data
                self.after(0, self._render_flux, flux_data, latest_tags)

                # Stage 7: Pod status from Rancher
                pod_data = self._fetch_pod_status(services)
                self._pipeline_data['pods'] = pod_data
                self.after(0, self._render_pods, pod_data)

                self.after(0, self._set_status,
                           f'Pipeline complete for {story_key}', SUCCESS)
                self.after(0, self._set_spinner, '')
            except Exception as e:
                self.after(0, self._set_status, f'Pipeline error: {e}', ERROR)
                self.after(0, self._set_spinner, '')

        threading.Thread(target=_pipeline, daemon=True).start()

    # ── Fetch: Jira ──────────────────────────────────────────────────────────
    def _fetch_jira(self, key):
        try:
            data = self._jira_get(f'issue/{key}?fields=summary,status,assignee,description,priority,issuetype,labels,customfield_14310,customfield_14311,comment')
            return data
        except Exception as e:
            return {'error': str(e), 'key': key}

    def _render_jira(self, data):
        t = self._jira_text
        t.config(state=tk.NORMAL)
        t.delete('1.0', tk.END)

        if 'error' in data:
            # Jira may not be configured — show what we have
            t.insert(tk.END, f'{data.get("key","?")}\n', 'key')
            t.insert(tk.END, f'Jira not reachable: {data["error"]}\n', 'desc')
            self._update_stage('jira', 'unknown', 'no jira')
            t.config(state=tk.DISABLED)
            return

        fields = data.get('fields', {})
        key    = data.get('key', '')
        summary = fields.get('summary', '')
        status  = fields.get('status', {}).get('name', '?')
        assignee = (fields.get('assignee') or {}).get('displayName', 'Unassigned')
        priority = (fields.get('priority') or {}).get('name', '?')
        itype    = (fields.get('issuetype') or {}).get('name', '?')
        labels   = ', '.join(fields.get('labels', [])) or '—'
        start    = (fields.get('customfield_14310') or '—')
        end      = (fields.get('customfield_14311') or '—')

        t.insert(tk.END, f'{key}  ', 'key')
        t.insert(tk.END, f'[{itype}]  ', 'label')
        t.insert(tk.END, f'{summary}\n\n', 'value')

        for label, val in [
            ('Status', status), ('Assignee', assignee),
            ('Priority', priority), ('Labels', labels),
            ('Target Start', start), ('Target End', end),
        ]:
            t.insert(tk.END, f'  {label:16}: ', 'label')
            t.insert(tk.END, f'{val}\n', 'status' if label == 'Status' else 'value')

        # Last 2 comments
        comments = (fields.get('comment') or {}).get('comments', [])
        if comments:
            t.insert(tk.END, '\nLatest Comments:\n', 'label')
            for c in comments[-2:]:
                author = (c.get('author') or {}).get('displayName', '?')
                body = c.get('body', '')[:200]
                t.insert(tk.END, f'  [{author}] ', 'label')
                t.insert(tk.END, f'{body}\n', 'desc')

        t.config(state=tk.DISABLED)

        status_stage = {
            'In Progress': 'running', 'Done': 'ok', 'Closed': 'ok',
            'Blocked': 'error', 'Open': 'pending', 'To Do': 'pending',
        }.get(status, 'unknown')
        self._update_stage('jira', status_stage, status[:12])

        # Populate dev panel with assignee info
        assignee_email = (fields.get('assignee') or {}).get('emailAddress', '')
        assignee_name  = (fields.get('assignee') or {}).get('displayName', 'Unassigned')
        self._dev_log(f'\n📋 Story: {key}\n', 'header')
        self._dev_log(f'  Assignee : ', 'label')
        self._dev_log(f'{assignee_name}', 'human')
        self._dev_log(f' ({assignee_email})\n' if assignee_email else '\n', 'detail')
        self._dev_log(f'  Status   : ', 'label')
        self._dev_log(f'{status}\n', 'value')
        self._dev_log(f'\n  💻 Auger will handle: branch detection, image promotion, Flux PR\n', 'auger')
        self._dev_log(f'  🧑 Human needed for: code fixes, build failures, PR approval\n', 'human')

    # ── Fetch: GHE PRs ────────────────────────────────────────────────────────
    def _fetch_prs(self, story_key):
        results = []
        # Search across all relevant repos for branches containing story key
        repos_to_search = list(SERVICE_REPO_MAP.values()) + ['assist-java17-jboss8']
        for repo in repos_to_search[:20]:  # limit to avoid rate-limit
            try:
                branches = self._ghe_get(
                    f'repos/assist/{repo}/branches?per_page=50')
                for b in branches:
                    bname = b.get('name', '')
                    if story_key.lower() in bname.lower():
                        # Found a matching branch — check for PRs
                        prs = self._ghe_get(
                            f'repos/assist/{repo}/pulls?head=assist:{bname}&state=all&per_page=5')
                        if prs:
                            for pr in prs:
                                checks_url = pr.get('statuses_url', '')
                                check_state = '?'
                                try:
                                    cdata = self._ghe_get(
                                        f'repos/assist/{repo}/commits/{pr["head"]["sha"]}/status')
                                    check_state = cdata.get('state', '?')
                                except Exception:
                                    pass
                                results.append({
                                    'repo': repo, 'branch': bname,
                                    'pr_number': pr.get('number'),
                                    'pr_url': pr.get('html_url', ''),
                                    'state': pr.get('state', '?'),
                                    'merged': pr.get('merged_at') is not None,
                                    'checks': check_state,
                                    'updated': pr.get('updated_at', '')[:10],
                                    'title': pr.get('title', ''),
                                })
                        else:
                            # Branch exists, no PR yet
                            results.append({
                                'repo': repo, 'branch': bname,
                                'pr_number': None, 'pr_url': '',
                                'state': 'no PR', 'merged': False,
                                'checks': '?', 'updated': '?',
                            })
            except Exception:
                continue
        return results

    def _render_prs(self, data):
        for row in self._pr_tree.get_children():
            self._pr_tree.delete(row)

        if not data:
            self._update_stage('pr', 'unknown', 'no branch')
            self._update_stage('branch', 'unknown', 'no branch')
            return

        for item in data:
            state  = item.get('state', '?')
            merged = item.get('merged', False)
            tag    = 'merged' if merged else ('open' if state == 'open' else 'closed')
            if item.get('checks') in ('failure', 'error'):
                tag = 'fail'
            self._pr_tree.insert('', tk.END, values=(
                item['repo'], item['branch'],
                f'#{item["pr_number"]}' if item['pr_number'] else '—',
                'MERGED' if merged else state.upper(),
                item.get('checks', '?'),
                item.get('updated', '?'),
            ), tags=(tag,))
            if item.get('pr_url'):
                self._pr_url = item['pr_url']

        # branch stage — branches found
        branch_count = len(data)
        self._update_stage('branch', 'ok' if branch_count else 'pending',
                           f'{branch_count} found' if branch_count else 'none')

        # Update branch panel log
        self._branch_text.config(state=tk.NORMAL)
        self._branch_text.delete('1.0', tk.END)
        self._branch_text.insert(tk.END, 'Feature Branches Found\n', 'header')
        for item in data:
            has_pr = bool(item.get('pr_number'))
            self._branch_text.insert(tk.END, f'\n  [{item["repo"]}]\n', 'label')
            self._branch_text.insert(tk.END, f'  Branch : ', 'label')
            self._branch_text.insert(tk.END, f'{item["branch"]}\n', 'value')
            self._branch_text.insert(tk.END, f'  PR     : ', 'label')
            self._branch_text.insert(tk.END,
                f'#{item["pr_number"]} ({item["state"]})\n' if has_pr else 'No PR yet\n',
                'ok' if has_pr else 'warn')
        self._branch_text.config(state=tk.DISABLED)

        # pipeline stage status
        merged_count = sum(1 for i in data if i.get('merged'))
        open_count   = sum(1 for i in data if i.get('state') == 'open')
        if merged_count:
            self._update_stage('pr', 'ok', f'{merged_count} merged')
        elif open_count:
            self._update_stage('pr', 'running', f'{open_count} open')
        else:
            self._update_stage('pr', 'pending', 'branches found')

    # ── Fetch: Jenkins builds ────────────────────────────────────────────────
    def _detect_services(self, story_key, explicit_svc, pr_data):
        if explicit_svc:
            return [explicit_svc]
        # Derive from PR repo names
        services = []
        for pr in pr_data:
            repo = pr.get('repo', '')
            if repo in REPO_SERVICE_MAP:
                svc = REPO_SERVICE_MAP[repo]
                if svc not in services:
                    services.append(svc)
        return services or list(SERVICE_REPO_MAP.keys())[:5]  # fallback to first 5

    def _fetch_builds(self, story_key, services):
        results = []
        jenkins_base = 'job/ASSIST/job/core/job/assist'
        for svc in services:
            repo = SERVICE_REPO_MAP.get(svc)
            if not repo:
                continue
            job_name = repo
            try:
                # Get branches for this job
                job_data = self._jenkins_get(
                    f'{jenkins_base}/job/{job_name}/api/json?depth=1&'
                    f'tree=jobs[name,lastBuild[id,result,timestamp,url,building]]')
                for branch in job_data.get('jobs', []):
                    bname = branch.get('name', '')
                    # Match story key or is main/release branch
                    is_story = story_key.replace('/', '%2F').lower() in bname.lower() or \
                               story_key.lower() in bname.lower()
                    is_main  = bname.lower() in ('main', 'master')
                    if is_story or is_main:
                        lb = branch.get('lastBuild') or {}
                        results.append({
                            'service': svc,
                            'branch': bname.replace('%2F', '/').replace('%252F', '/'),
                            'build_num': lb.get('id', '?'),
                            'result': 'BUILDING' if lb.get('building') else (lb.get('result') or '?'),
                            'timestamp': lb.get('timestamp', 0),
                            'url': lb.get('url', ''),
                            'is_story': is_story,
                        })
            except Exception:
                continue
        return results

    def _render_builds(self, data):
        for row in self._build_tree.get_children():
            self._build_tree.delete(row)

        story_builds = [b for b in data if b.get('is_story')]
        if not story_builds:
            story_builds = data  # show main if no story branch

        ok_count  = sum(1 for b in story_builds if b.get('result') == 'SUCCESS')
        err_count = sum(1 for b in story_builds if b.get('result') in ('FAILURE','ABORTED'))

        for item in story_builds[:20]:
            result = item.get('result', '?')
            self._build_tree.insert('', tk.END, values=(
                item['service'], item['branch'],
                f'#{item["build_num"]}', result,
                _ts_age(item.get('timestamp', 0)),
                '🌐 open',
            ), tags=(result,))

        if ok_count:
            self._update_stage('build', 'ok', f'{ok_count} passed')
            self._update_stage('dev_deploy', 'ok', 'build passed')
        elif err_count:
            self._update_stage('build', 'error', f'{err_count} failed')
            self._update_stage('dev_deploy', 'error', 'build failed')
            # Auto-fire @mention to developer on build failure
            self._auto_mention_build_failure(data)
        elif story_builds:
            self._update_stage('build', 'running', 'building')
            self._update_stage('dev_deploy', 'running', 'in progress')
        else:
            self._update_stage('build', 'unknown', 'no builds')
            self._update_stage('dev_deploy', 'pending', 'awaiting dev')

    # ── Auto-mention on build failure ────────────────────────────────────────
    def _auto_mention_build_failure(self, builds):
        """Fire a GChat @mention to the story assignee when a build fails."""
        failed = [b for b in builds if b.get('result') == 'FAILURE']
        if not failed:
            return
        story_key = self._pipeline_data.get('story_key', '?')
        jira_data  = self._pipeline_data.get('jira', {})
        assignee   = (jira_data.get('fields') or {}).get('assignee') or {}
        assignee_email = assignee.get('emailAddress', '')

        b = failed[0]
        detail = f'`{b["service"]}` build #{b["build_num"]} failed on `{b["branch"]}`'
        link   = b.get('url', '') or None

        self._dev_log(f'\n🔴 Build failure detected — auto-mentioning developer…\n', 'error')

        def _do():
            result = mention_on_block(
                event='build_failure',
                story_key=story_key,
                stage='Jenkins',
                detail=detail,
                link=link,
                jira_assignee_email=assignee_email or None,
            )
            if result['sent']:
                names = ', '.join(r['name'] for r in result['recipients'])
                self.after(0, self._dev_log,
                           f'📣 Auto-mention sent → {names}\n', 'sent')
                self.after(0, self._set_status,
                           f'Build failure — @mentioned {names}', WARNING)
            else:
                self.after(0, self._dev_log,
                           f'(auto-mention skipped: {result["error"]})\n', 'detail')

        threading.Thread(target=_do, daemon=True).start()

    # ── Fetch: Artifactory images ────────────────────────────────────────────
    def _fetch_images(self, services):
        results = []
        for svc in services:
            image_name = f'core-assist-{svc}'
            try:
                data = self._artifactory_get(
                    f'api/storage/gs-assist-docker-repo/{image_name}')
                children = [c['uri'].lstrip('/') for c in data.get('children', [])
                            if not c.get('folder') or c['uri'] != '/_uploads']
                # Sort by name (which includes timestamp) desc
                tags = sorted([c for c in children
                               if c.startswith('release-')], reverse=True)
                latest = tags[0] if tags else None
                results.append({
                    'service': svc,
                    'image_name': image_name,
                    'latest_tag': latest,
                    'recent_tags': tags[:5],
                })
            except Exception as e:
                results.append({'service': svc, 'image_name': image_name,
                                'latest_tag': None, 'recent_tags': [],
                                'error': str(e)})
        return results

    def _latest_tag(self, image_data, service):
        for item in image_data:
            if item['service'] == service:
                return item.get('latest_tag')
        return None

    def _render_images(self, data):
        for row in self._image_tree.get_children():
            self._image_tree.delete(row)

        for item in data:
            tag = item.get('latest_tag') or item.get('error', '—')
            self._image_tree.insert('', tk.END, values=(
                item['service'], tag, _short_tag(tag), '—'))

        if any(i.get('latest_tag') for i in data):
            self._update_stage('image', 'ok', _short_tag(
                next(i['latest_tag'] for i in data if i.get('latest_tag'))))
        else:
            self._update_stage('image', 'unknown', 'no images')

    # ── Fetch: Flux config YAML parsing ──────────────────────────────────────
    def _fetch_flux_status(self, services, latest_tags):
        results = []
        for env_label, repo_key, path_part in ENVS:
            if repo_key == 'prod':
                base = self._flux_prod_path
                yaml_path_tmpl = f'core/production/apps/{{service}}.yaml'
            else:
                base = self._flux_dev_path
                yaml_path_tmpl = f'core/{path_part}/apps/{{service}}.yaml'

            if not base.exists():
                continue

            for svc in services:
                yaml_path = base / yaml_path_tmpl.format(service=svc)
                if not yaml_path.exists():
                    # try configmap pattern
                    yaml_path = base / yaml_path_tmpl.format(service=svc)
                if yaml_path.exists():
                    try:
                        with open(yaml_path) as f:
                            doc = yaml.safe_load(f)
                        # Navigate to image tag
                        tag = None
                        try:
                            tag = (doc['spec']['values']['deployment']
                                   ['containers']['jboss']['image']['tag'])
                        except (KeyError, TypeError):
                            pass

                        latest = latest_tags.get(svc)
                        if tag and latest:
                            drift = '✓' if tag == latest else '↓ behind'
                            drift_tag = 'match' if tag == latest else 'behind'
                        else:
                            drift = '?'
                            drift_tag = 'unknown'

                        ns = path_part.split('/')[-1]
                        if repo_key == 'prod':
                            ns = 'assist-prod'
                        else:
                            ns = f'assist-{ns}'

                        results.append({
                            'env': env_label, 'namespace': ns,
                            'service': svc, 'current_tag': tag or '—',
                            'short_tag': _short_tag(tag),
                            'drift': drift, 'drift_tag': drift_tag,
                        })
                    except Exception as e:
                        results.append({
                            'env': env_label, 'namespace': '?',
                            'service': svc, 'current_tag': f'error: {e}',
                            'short_tag': '—', 'drift': '?',
                            'drift_tag': 'unknown',
                        })
        return results

    def _render_flux(self, data, latest_tags):
        for row in self._flux_tree.get_children():
            self._flux_tree.delete(row)

        dev_ok = stg_ok = prd_ok = 0
        for item in data:
            self._flux_tree.insert('', tk.END, values=(
                item['env'], item['namespace'], item['service'],
                item['current_tag'], item['short_tag'], item['drift'],
            ), tags=(item['drift_tag'],))
            if item['drift'] == '✓':
                if 'DEV' in item['env']:
                    dev_ok += 1
                elif 'STAGING' in item['env']:
                    stg_ok += 1
                elif 'PROD' in item['env']:
                    prd_ok += 1

        self._update_stage('flux_stg', 'ok' if stg_ok else 'behind',
                           f'{stg_ok} current' if stg_ok else 'behind')
        self._update_stage('flux_prd', 'ok' if prd_ok else 'behind',
                           f'{prd_ok} current' if prd_ok else 'behind')

    # ── Fetch: Pod status ────────────────────────────────────────────────────
    def _fetch_pod_status(self, services):
        results = []
        # Check key namespaces: dev01, dev09, stage01, prod
        check_ns = [
            ('DEV01', 'c-m-qpv8hf6m', 'assist-dev01'),
            ('DEV09', 'c-m-qpv8hf6m', 'assist-dev09'),
            ('STG01', 'c-xkd99',      'assist-staging01'),
            ('PROD',  'c-2bsb4',      'assist-prod'),
        ]
        for env_label, cluster_id, ns in check_ns:
            for svc in services:
                try:
                    url = (f'{self._rancher_url}/k8s/clusters/{cluster_id}'
                           f'/api/v1/namespaces/{ns}/pods?labelSelector=app%3D{svc}')
                    resp = requests.get(url,
                        headers={'Authorization': f'Bearer {self._rancher_token}'},
                        verify=False, timeout=8)
                    if resp.status_code != 200:
                        continue
                    data = resp.json()
                    for pod in data.get('items', []):
                        pname   = pod['metadata']['name']
                        phase   = pod.get('status', {}).get('phase', 'Unknown')
                        cs_list = pod.get('status', {}).get('containerStatuses', [])
                        ready   = sum(1 for c in cs_list if c.get('ready'))
                        total   = len(cs_list)
                        restarts = sum(c.get('restartCount', 0) for c in cs_list)
                        # Get running image tag
                        containers = pod.get('spec', {}).get('containers', [])
                        img_tag = ''
                        if containers:
                            img = containers[0].get('image', '')
                            img_tag = img.split(':')[-1] if ':' in img else img
                        results.append({
                            'env': env_label, 'namespace': ns,
                            'pod': pname, 'status': phase,
                            'ready': f'{ready}/{total}',
                            'restarts': restarts,
                            'image_tag': _short_tag(img_tag),
                            'phase': phase,
                        })
                except Exception:
                    continue
        return results

    def _render_pods(self, data):
        for row in self._pods_tree.get_children():
            self._pods_tree.delete(row)

        for item in data:
            phase = item.get('phase', 'Unknown')
            tag = {'Running': 'running', 'Pending': 'pending',
                   'Failed': 'error', 'Unknown': 'unknown'}.get(phase, 'unknown')
            self._pods_tree.insert('', tk.END, values=(
                item['env'], item['namespace'], item['pod'],
                item['status'], item['ready'], item['restarts'],
                item['image_tag'],
            ), tags=(tag,))

    # ── Flux PR creation ─────────────────────────────────────────────────────
    def _create_flux_pr(self):
        story_key = self._story_key.get().strip().upper()
        env_label = self._promote_env_var.get()
        services  = self._pipeline_data.get('services', [])
        images    = self._pipeline_data.get('images', [])

        if not services or not images:
            messagebox.showwarning('No Data',
                'Run the pipeline first to detect services and image tags.',
                parent=self)
            return

        # Build summary of what will change
        changes = []
        for svc in services:
            tag = self._latest_tag(images, svc)
            if tag:
                changes.append(f'  • {svc}: → {_short_tag(tag)}')

        if not changes:
            messagebox.showwarning('No Tags', 'No image tags found to promote.', parent=self)
            return

        env_to_repo = {
            'DEV01': ('assist-flux-config', 'development/dev01'),
            'DEV09': ('assist-flux-config', 'development/dev09'),
            'STAGING01': ('assist-flux-config', 'staging/stage01'),
            'STAGING06': ('assist-flux-config', 'staging/stage06'),
            'PROD': ('assist-prod-flux-config', 'production'),
        }
        repo_name, path_part = env_to_repo.get(env_label, (None, None))
        if not repo_name:
            messagebox.showerror('Unknown Env', f'Unknown env: {env_label}', parent=self)
            return

        if not messagebox.askyesno(
            'Create Flux PR',
            f'Create a Flux config PR to promote to {env_label}?\n\n'
            + '\n'.join(changes) +
            f'\n\nRepo: {repo_name}\nPath: core/{path_part}/apps/\n\n'
            + ('⚠️  PROD requires 2 approvals before merge.' if 'prod' in repo_name.lower() else ''),
            parent=self):
            return

        self._set_status(f'Creating Flux PR for {env_label}…', ACCENT)
        threading.Thread(target=self._do_create_flux_pr,
                         args=(story_key, env_label, repo_name, path_part, services, images),
                         daemon=True).start()

    def _do_create_flux_pr(self, story_key, env_label, repo_name, path_part, services, images):
        try:
            GHE = self._ghe_url
            HEADERS = {
                'Authorization': f'token {self._ghe_token}',
                'Content-Type': 'application/json',
            }
            API = f'{GHE}/api/v3'

            # Get default branch SHA
            repo_info = self._ghe_get(f'repos/assist/{repo_name}')
            default_branch = repo_info.get('default_branch', 'main')
            ref_data = self._ghe_get(f'repos/assist/{repo_name}/git/ref/heads/{default_branch}')
            base_sha = ref_data['object']['sha']

            # Create new branch
            branch_name = f'feature/{story_key}-promote-{env_label.lower()}-{int(time.time())}'
            requests.post(f'{API}/repos/assist/{repo_name}/git/refs',
                headers=HEADERS, verify=False,
                json={'ref': f'refs/heads/{branch_name}', 'sha': base_sha})

            # Update each service YAML
            updated = []
            for svc in services:
                new_tag = self._latest_tag(images, svc)
                if not new_tag:
                    continue
                if 'prod' in repo_name:
                    yaml_path = f'core/production/apps/{svc}.yaml'
                else:
                    yaml_path = f'core/{path_part}/apps/{svc}.yaml'

                # Get current file
                try:
                    file_data = self._ghe_get(
                        f'repos/assist/{repo_name}/contents/{yaml_path}?ref={branch_name}')
                    content_b64 = file_data.get('content', '').replace('\n', '')
                    sha = file_data.get('sha', '')
                    import base64
                    content = base64.b64decode(content_b64).decode('utf-8')

                    # Replace image tag line
                    new_content = re.sub(
                        r'(tag:\s*)release-ASSIST_[^\s#\n]+',
                        f'\\g<1>{new_tag}',
                        content)

                    if new_content == content:
                        continue  # no change needed

                    import base64 as b64
                    encoded = b64.b64encode(new_content.encode()).decode()
                    requests.put(f'{API}/repos/assist/{repo_name}/contents/{yaml_path}',
                        headers=HEADERS, verify=False,
                        json={
                            'message': f'feat({story_key}): promote {svc} to {env_label}\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>',
                            'content': encoded,
                            'sha': sha,
                            'branch': branch_name,
                        })
                    updated.append(svc)
                except Exception as e:
                    self.after(0, self._set_status, f'Error updating {svc}: {e}', ERROR)

            if not updated:
                self.after(0, self._set_status, 'No files updated — tags already current?', WARNING)
                return

            # Create PR
            pr_body = (
                f'## Flux Promotion: {story_key} → {env_label}\n\n'
                f'Services updated:\n' +
                '\n'.join(f'- `{s}`' for s in updated) +
                f'\n\n'
                f'**Story:** [{story_key}]({self._jira_url}/browse/{story_key})\n\n'
                + ('> ⚠️ **PROD** — 2 approvals required before merging.\n\n'
                   if 'prod' in repo_name.lower() else '') +
                'Created by Auger Story→Prod pipeline.\n\n'
                'Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>'
            )
            pr_resp = requests.post(
                f'{API}/repos/assist/{repo_name}/pulls',
                headers=HEADERS, verify=False,
                json={
                    'title': f'feat({story_key}): promote to {env_label}',
                    'body': pr_body,
                    'head': branch_name,
                    'base': default_branch,
                })
            pr_data = pr_resp.json()
            pr_url  = pr_data.get('html_url', '')
            pr_num  = pr_data.get('number', '?')

            self.after(0, self._set_status,
                       f'PR #{pr_num} created: {pr_url}', SUCCESS)
            self.after(0, messagebox.showinfo, 'PR Created',
                       f'Flux PR #{pr_num} created for {env_label}!\n\n{pr_url}'
                       + ('\n\n⚠️ Needs 2 approvals before merge.' if 'prod' in repo_name.lower() else ''))
        except Exception as e:
            self.after(0, self._set_status, f'PR creation failed: {e}', ERROR)

    # ── Flux repo sync ────────────────────────────────────────────────────────
    def _sync_flux_repos_bg(self):
        self._flux_label.config(text='Flux: syncing…', fg=YELLOW)
        threading.Thread(target=self._sync_flux_repos, daemon=True).start()

    def _sync_flux_repos(self):
        import subprocess
        try:
            token = self._ghe_token
            ghe   = self._ghe_url

            for repo_name, local_path in [
                ('assist-flux-config',      self._flux_dev_path),
                ('assist-prod-flux-config', self._flux_prod_path),
            ]:
                url = f'https://{token}@{ghe.replace("https://","")}/assist/{repo_name}.git'
                if local_path.exists():
                    subprocess.run(['git', '-C', str(local_path), 'pull', '--ff-only', '-q'],
                                   capture_output=True, timeout=60)
                else:
                    subprocess.run(['git', 'clone', '--depth=1', '-q', url, str(local_path)],
                                   capture_output=True, timeout=120)

            self.after(0, self._flux_label.config,
                       {'text': f'Flux: synced {datetime.now().strftime("%H:%M")}',
                        'fg': SUCCESS})
        except Exception as e:
            self.after(0, self._flux_label.config,
                       {'text': f'Flux: sync error', 'fg': ERROR})

    # ── Clear panels ──────────────────────────────────────────────────────────
    def _clear_all_panels(self):
        self._jira_text.config(state=tk.NORMAL)
        self._jira_text.delete('1.0', tk.END)
        self._jira_text.config(state=tk.DISABLED)
        self._branch_text.config(state=tk.NORMAL)
        self._branch_text.delete('1.0', tk.END)
        self._branch_text.config(state=tk.DISABLED)
        for tree in (self._pr_tree, self._build_tree, self._image_tree,
                     self._flux_tree, self._pods_tree):
            for row in tree.get_children():
                tree.delete(row)
        # Reset loop counters
        self._loop_a_iters = 0
        self._loop_b_iters = 0
        self._loop_a_label.config(text='Loop A: 0 iterations')
        self._loop_b_label.config(text='Loop B: 0 iterations')

    # ── Open URLs ─────────────────────────────────────────────────────────────
    def _open_pr_url(self):
        if self._pr_url:
            webbrowser.open(self._pr_url)

    def _open_jenkins_url(self, _event=None):
        sel = self._build_tree.selection()
        if sel:
            idx = self._build_tree.index(sel[0])
            builds = self._pipeline_data.get('builds', [])
            if idx < len(builds):
                url = builds[idx].get('url', '')
                if url:
                    webbrowser.open(url)

    # ── Style helper ──────────────────────────────────────────────────────────
    def _style_tree(self, tree):
        style = ttk.Style()
        s = f'S2P{id(tree)}.Treeview'
        style.configure(s, background=BG, fieldbackground=BG,
                        foreground=FG, font=('Segoe UI', 9), rowheight=22)
        style.map(s, background=[('selected', ACCENT)],
                  foreground=[('selected', 'white')])
        style.configure(f'{s}.Heading', background=BG2, foreground=ACCENT2,
                        font=('Segoe UI', 9, 'bold'))
        tree.configure(style=s)

    # ── Status helpers ─────────────────────────────────────────────────────────
    def _set_status(self, msg, color=FG2):
        self._status_msg.set(msg)
        self._status_lbl.config(fg=color)

    def _set_spinner(self, text):
        self._spinner_lbl.config(text=text)

    # ── Context builder ───────────────────────────────────────────────────────
    def build_context(self):
        ctx = 'STORY TO PROD CONTEXT\n\n'
        key = self._pipeline_data.get('story_key', '?')
        ctx += f'Story: {key}\n'
        svcs = self._pipeline_data.get('services', [])
        ctx += f'Services: {", ".join(svcs) or "none detected"}\n'
        prs = self._pipeline_data.get('prs', [])
        if prs:
            ctx += f'PRs: {len(prs)} found\n'
            for p in prs[:3]:
                ctx += f'  {p["repo"]}/{p["branch"]} — {p["state"]}\n'
        builds = self._pipeline_data.get('builds', [])
        if builds:
            ok = sum(1 for b in builds if b.get('result') == 'SUCCESS')
            ctx += f'Builds: {ok}/{len(builds)} passed\n'
        return ctx


def create_widget(parent, context_builder_callback=None):
    return StoryToProdWidget(parent, context_builder_callback)
