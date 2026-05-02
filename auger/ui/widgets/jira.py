"""
Jira Widget — My Stories, Sprint Board, Status Transitions, Story Detail

Connects to Jira Cloud instances via API token authentication (Basic Auth).
Configuration via API Keys+ widget (JIRA_BASE_URL, JIRA_USERNAME, JIRA_API_TOKEN).

Features:
  - My Stories tab:   issues assigned to me, filterable by project
  - Sprint Board tab: issues in active sprint, grouped by status column
  - Story Detail:     rendered HTML description with clickable links
  - Add comment:      post comments directly from the widget
  - Quick actions:    transition status, copy issue key, open in browser
"""
import tkinter as tk
from tkinter import ttk, scrolledtext
import threading
import queue
from pathlib import Path
import sys
import os
import base64
import requests
from dotenv import load_dotenv

try:
    from tksheet import Sheet as _Sheet
    TKSHEET_AVAILABLE = True
except ImportError:
    TKSHEET_AVAILABLE = False

try:
    from bs4 import BeautifulSoup, NavigableString, Tag
    _BS4_OK = True
except ImportError:
    _BS4_OK = False

try:
    from PIL import Image, ImageDraw, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu, auger_home as _auger_home

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
WARNING = '#f0c040'
JIRA_BLUE = '#0052cc'

# Status colours — (row_bg, row_fg) for treeview tag
_STATUS_COLORS = {
    'To Do':       ('#3a3a3a', '#cccccc'),
    'In Progress': ('#003d7a', '#7ec8ff'),
    'In Review':   ('#5c4400', '#f0c040'),
    'In Testing':  ('#1a4a2e', '#5dbb7f'),   # green tint — visible on dark bg
    'Done':        ('#1a3a2a', '#4ec9b0'),
    'Blocked':     ('#4a1010', '#ff7070'),
    'Closed':      ('#2a2a2a', '#888888'),
    'Resolved':    ('#1a3a2a', '#4ec9b0'),
}

def _status_color(status_name: str):
    for key, colors in _STATUS_COLORS.items():
        if key.lower() in status_name.lower():
            return colors
    return ('#3a3a3a', FG)  # default: visible dark grey

# ── PIL icon cache ─────────────────────────────────────────────────────────────

_pil_icon_cache: dict = {}

def _make_pil_icon(shape: str, color: str, size: int = 14) -> 'ImageTk.PhotoImage | None':
    """Create a small PIL icon: 'circle', 'square', 'diamond', 'triangle'."""
    if not _PIL_OK:
        return None
    key = (shape, color, size)
    if key in _pil_icon_cache:
        return _pil_icon_cache[key]
    img  = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m    = 1  # margin
    if shape == 'circle':
        draw.ellipse([m, m, size - m - 1, size - m - 1], fill=color)
    elif shape == 'square':
        draw.rectangle([m, m, size - m - 1, size - m - 1], fill=color)
    elif shape == 'diamond':
        cx, cy = size // 2, size // 2
        draw.polygon([(cx, m), (size - m - 1, cy), (cx, size - m - 1), (m, cy)], fill=color)
    elif shape == 'triangle':
        draw.polygon([(m, size - m - 1), (size - m - 1, size - m - 1), (cx := size // 2, m)], fill=color)
    photo = ImageTk.PhotoImage(img)
    _pil_icon_cache[key] = photo
    return photo


# Issue type → (shape, color)
_TYPE_ICON_SPEC = {
    'story':   ('square',   '#36b37e'),   # green
    'bug':     ('circle',   '#ff5630'),   # red
    'task':    ('square',   '#4c9aff'),   # blue
    'epic':    ('square',   '#998dd9'),   # purple
    'subtask': ('square',   '#79e2f2'),   # cyan
}
_TYPE_ICON_DEFAULT = ('square', '#888888')

# Priority → (shape, color)
_PRI_ICON_SPEC = {
    'blocker':  ('diamond', '#ff5630'),   # red
    'highest':  ('diamond', '#ff5630'),
    'high':     ('diamond', '#ff7452'),   # orange-red
    'medium':   ('diamond', '#f0c040'),   # yellow
    'low':      ('diamond', '#4c9aff'),   # blue
    'lowest':   ('diamond', '#8993a4'),   # grey
}
_PRI_ICON_DEFAULT = ('diamond', '#8993a4')


def _type_pil_icon(itype: str):
    t = (itype or '').lower()
    for key, spec in _TYPE_ICON_SPEC.items():
        if key in t:
            return _make_pil_icon(*spec)
    return _make_pil_icon(*_TYPE_ICON_DEFAULT)


def _pri_pil_icon(priority: str):
    p = (priority or '').lower()
    for key, spec in _PRI_ICON_SPEC.items():
        if key in p:
            return _make_pil_icon(*spec)
    return _make_pil_icon(*_PRI_ICON_DEFAULT)


def _priority_icon(priority: str) -> str:
    """Fallback text label when PIL unavailable."""
    p = (priority or '').lower()
    if 'highest' in p or 'blocker' in p: return '[BLOCKER]'
    if 'high'    in p:                   return '[HIGH]'
    if 'medium'  in p:                   return '[MED]'
    if 'low'     in p:                   return '[LOW]'
    return '[?]'

def _issue_type_icon(itype: str) -> str:
    """Fallback text label when PIL unavailable."""
    t = (itype or '').lower()
    if 'story'   in t: return '[Story]'
    if 'bug'     in t: return '[Bug]'
    if 'task'    in t: return '[Task]'
    if 'epic'    in t: return '[Epic]'
    if 'subtask' in t: return '[Sub]'
    return '[?]'


def _fmt_date(val: str) -> str:
    """Format YYYY-MM-DD → MM/DD/YY for compact display."""
    if not val:
        return ''
    try:
        parts = val[:10].split('-')
        return f'{parts[1]}/{parts[2]}/{parts[0][2:]}'
    except Exception:
        return val[:10]


def _priority_short(priority: str) -> str:
    p = (priority or '').lower()
    if 'blocker' in p or 'highest' in p:
        return 'Blocker'
    if 'high' in p:
        return 'High'
    if 'medium' in p:
        return 'Med'
    if 'low' in p:
        return 'Low'
    return (priority or '?')[:6] or '?'


# ── HTML → tk.Text renderer ────────────────────────────────────────────────────

def _setup_html_tags(text_widget: tk.Text, open_url_fn):
    """Configure all tags used by _render_html on a Text widget."""
    text_widget.tag_config('h1',      font=('Segoe UI', 13, 'bold'),  foreground=ACCENT2, spacing1=6)
    text_widget.tag_config('h2',      font=('Segoe UI', 11, 'bold'),  foreground=ACCENT2, spacing1=4)
    text_widget.tag_config('h3',      font=('Segoe UI', 10, 'bold'),  foreground=FG,      spacing1=3)
    text_widget.tag_config('bold',    font=('Segoe UI', 9,  'bold'),  foreground=FG)
    text_widget.tag_config('italic',  font=('Segoe UI', 9,  'italic'),foreground=FG)
    text_widget.tag_config('code',    font=('Consolas', 9),           foreground='#ce9178', background=BG3)
    text_widget.tag_config('pre',     font=('Consolas', 9),           foreground='#ce9178', background=BG3,
                           lmargin1=20, lmargin2=20, spacing1=4, spacing3=4)
    text_widget.tag_config('bullet',  font=('Segoe UI', 9),           foreground=FG,      lmargin1=16, lmargin2=28)
    text_widget.tag_config('num',     font=('Segoe UI', 9),           foreground=FG,      lmargin1=16, lmargin2=32)
    text_widget.tag_config('body',    font=('Segoe UI', 9),           foreground=FG)
    text_widget.tag_config('sep',     font=('Segoe UI', 7),           foreground=BG4)
    text_widget.tag_config('heading', font=('Segoe UI', 10, 'bold'),  foreground=ACCENT2)
    text_widget.tag_config('key',     font=('Segoe UI', 11, 'bold'),  foreground=ACCENT)
    text_widget.tag_config('status',  font=('Segoe UI', 9,  'bold'),  foreground=SUCCESS)
    text_widget.tag_config('priority',font=('Segoe UI', 9),           foreground=WARN)
    text_widget.tag_config('author',  font=('Segoe UI', 8,  'bold'),  foreground=FG2)

    # Pre-create a fixed pool of 60 numbered link tags — reused each render,
    # no dynamic tag_config/tag_delete which causes Tcl_Release crashes.
    _LINK_POOL = 60
    link_style = dict(font=('Segoe UI', 9, 'underline'), foreground=ACCENT)
    for i in range(_LINK_POOL):
        text_widget.tag_config(f'link_{i}', **link_style)

    # URL registry: tag_name → url, reset each render
    text_widget._link_urls   = {}
    text_widget._link_count  = 0
    text_widget._link_pool   = _LINK_POOL
    text_widget._open_url_fn = open_url_fn

    def _on_link_click(event, tw=text_widget):
        idx = tw.index(f'@{event.x},{event.y}')
        for tag in tw.tag_names(idx):
            url = tw._link_urls.get(tag)
            if url:
                fn = tw._open_url_fn
                if fn:
                    fn(url)
                break

    # Single click handler on the whole widget — checks tag at click position
    text_widget.bind('<Button-1>', _on_link_click)


def _render_html(text_widget: tk.Text, html: str, base_tag: str = 'body'):
    """Parse HTML and insert styled text into a tk.Text widget.
    Links are clickable and open via the host daemon."""
    if not _BS4_OK or not html:
        # Fallback: strip tags naively
        import re
        plain = re.sub(r'<[^>]+>', '', html or '')
        text_widget.insert(tk.END, plain + '\n', base_tag)
        return

    soup = BeautifulSoup(html, 'html.parser')
    _render_node(text_widget, soup, base_tag)


def _render_node(tw: tk.Text, node, inherited_tag: str = 'body'):
    """Recursively walk BeautifulSoup nodes and insert styled text."""
    if isinstance(node, NavigableString):
        text = str(node)
        if text.strip() or (text and inherited_tag in ('code', 'pre')):
            tw.insert(tk.END, text, inherited_tag)
        return

    tag = node.name if hasattr(node, 'name') else None

    # Block elements that add newlines
    if tag in ('p', 'div'):
        for child in node.children:
            _render_node(tw, child, inherited_tag)
        tw.insert(tk.END, '\n', 'body')

    elif tag in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        level = tag  # h1..h6 all have configured tags; h4-h6 fall back to h3 look
        actual = level if level in ('h1', 'h2', 'h3') else 'h3'
        tw.insert(tk.END, node.get_text() + '\n', actual)

    elif tag == 'br':
        tw.insert(tk.END, '\n', 'body')

    elif tag in ('strong', 'b'):
        for child in node.children:
            _render_node(tw, child, 'bold')

    elif tag in ('em', 'i'):
        for child in node.children:
            _render_node(tw, child, 'italic')

    elif tag in ('code', 'tt'):
        tw.insert(tk.END, node.get_text(), 'code')

    elif tag == 'pre':
        tw.insert(tk.END, '\n' + node.get_text() + '\n', 'pre')

    elif tag in ('ul', 'ol'):
        tw.insert(tk.END, '\n', 'body')
        for i, li in enumerate(node.find_all('li', recursive=False), 1):
            prefix = f'  • ' if tag == 'ul' else f'  {i}. '
            list_tag = 'bullet' if tag == 'ul' else 'num'
            tw.insert(tk.END, prefix, list_tag)
            for child in li.children:
                _render_node(tw, child, list_tag)
            tw.insert(tk.END, '\n', list_tag)
        tw.insert(tk.END, '\n', 'body')

    elif tag == 'li':
        tw.insert(tk.END, '  • ', 'bullet')
        for child in node.children:
            _render_node(tw, child, 'bullet')
        tw.insert(tk.END, '\n', 'bullet')

    elif tag == 'a':
        href  = node.get('href', '').strip().rstrip('*').rstrip()
        label = node.get_text().strip('* \t') or href
        if href and href.startswith('http'):
            # Grab next slot from the pre-created link tag pool
            idx      = getattr(tw, '_link_count', 0) % getattr(tw, '_link_pool', 60)
            tag_name = f'link_{idx}'
            tw._link_count = idx + 1
            tw._link_urls[tag_name] = href
            tw.insert(tk.END, label, tag_name)
        else:
            tw.insert(tk.END, label, inherited_tag)

    elif tag in ('table', 'tbody', 'tr', 'thead'):
        for child in node.children:
            _render_node(tw, child, inherited_tag)

    elif tag in ('td', 'th'):
        tw.insert(tk.END, node.get_text().strip() + '  ', inherited_tag)

    elif tag in ('hr',):
        tw.insert(tk.END, '─' * 60 + '\n', 'sep')

    elif tag in ('span',):
        # Jira uses spans heavily — just render children
        for child in node.children:
            _render_node(tw, child, inherited_tag)

    elif tag in ('img',):
        alt = node.get('alt', '[image]')
        tw.insert(tk.END, f'[{alt}]', 'italic')

    elif tag and tag not in ('script', 'style', 'head', 'meta', 'link'):
        # Unknown tag — render children with inherited tag
        for child in node.children:
            _render_node(tw, child, inherited_tag)



class JiraWidget(tk.Frame):
    WIDGET_TITLE       = 'Jira'
    WIDGET_ICON_NAME   = 'jira'

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        # Load configuration from .env
        load_dotenv(_auger_home() / '.auger' / '.env', override=True)
        self._jira_url = os.getenv('JIRA_BASE_URL', '').strip()
        self._jira_username = os.getenv('JIRA_USERNAME', '').strip()
        self._jira_token = os.getenv('JIRA_API_TOKEN', '').strip()
        self._jira_headers = {}  # Will be set by _init_session if auth succeeds
        
        self._jira      = None
        self._icons     = {}
        self._issues    = []          # current list (my stories or sprint)
        self._sel_issue = None        # currently selected full issue dict
        self._transitions = []        # transitions for selected issue
        self._suppress_tree_select = False
        self._issue_views = {}
        self._issue_col_keys = ('type', 'key', 'pri', 'summary', 'status', 'tstart', 'tend')
        # Thread-safe result queue — background threads push callables, main thread polls
        self._result_queue = queue.Queue()
        self._load_icons()
        self._create_ui()
        self.after(200, self._init_session)
        self.after(100, self._poll_results)

    # ── Icons ─────────────────────────────────────────────────────────────────

    def _load_icons(self):
        for name in ('refresh', 'login', 'browser', 'check', 'jira'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

    # ── Thread-safe result queue poll ─────────────────────────────────────────

    def _poll_results(self):
        """Drain the result queue on the main thread, then reschedule."""
        try:
            while True:
                fn = self._result_queue.get_nowait()
                try:
                    fn()
                except Exception as e:
                    import traceback, logging
                    logging.getLogger('jira_widget').error(
                        'Queue callback error:\n' + traceback.format_exc())
        except queue.Empty:
            pass
        self.after(50, self._poll_results)

    def _q(self, fn):
        """Push a zero-arg callable onto the result queue (thread-safe)."""
        self._result_queue.put(fn)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _create_ui(self):
        # ── Dark ttk styles ───────────────────────────────────────────────────
        style = ttk.Style()
        style.configure('Jira.Treeview',
                        background=BG2, fieldbackground=BG2, foreground=FG,
                        rowheight=22, font=('Segoe UI', 9))
        style.configure('Jira.Treeview.Heading',
                        background=BG3, foreground=ACCENT2,
                        font=('Segoe UI', 9, 'bold'), relief='flat')
        style.map('Jira.Treeview',
                  background=[('selected', '#094771')],
                  foreground=[('selected', 'white')])
        style.configure('Jira.TNotebook',       background=BG,  borderwidth=0)
        style.configure('Jira.TNotebook.Tab',   background=BG3, foreground=FG2,
                        padding=[10, 4])
        style.map('Jira.TNotebook.Tab',
                  background=[('selected', BG2)],
                  foreground=[('selected', FG)])

        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=JIRA_BLUE, height=42)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text='  Jira', font=('Segoe UI', 13, 'bold'),
                 fg='white', bg=JIRA_BLUE).pack(side=tk.LEFT, padx=4, pady=8)
        self._user_label = tk.Label(hdr, text='', font=('Segoe UI', 9),
                                    fg='#cce5ff', bg=JIRA_BLUE)
        self._user_label.pack(side=tk.LEFT, padx=8)

        # Auth status + config button on right
        self._auth_label = tk.Label(hdr, text='Connecting...',
                                    font=('Segoe UI', 9), fg='#ffcc44', bg=JIRA_BLUE)
        self._auth_label.pack(side=tk.RIGHT, padx=8)
        self._config_btn = tk.Button(
            hdr, text=' ⚙ Configure',
            image=self._icons.get('settings'), compound=tk.LEFT,
            command=self._show_config_help,
            bg='#0041a3', fg='white', font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT, padx=10, pady=2, cursor='hand2'
        )
        self._config_btn.pack(side=tk.RIGHT, padx=4, pady=6)

        # ── Toolbar ───────────────────────────────────────────────────────────
        tb = tk.Frame(self, bg=BG3)
        tb.pack(fill=tk.X)

        tk.Label(tb, text='Project:', bg=BG3, fg=FG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(8, 2), pady=4)
        self._proj_var = tk.StringVar(value='')
        tk.Entry(tb, textvariable=self._proj_var, width=10,
                 bg=BG4, fg=FG, insertbackground=FG,
                 font=('Segoe UI', 9), relief=tk.FLAT).pack(side=tk.LEFT, pady=4)

        tk.Label(tb, text='Story:', bg=BG3, fg=FG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(10, 2), pady=4)
        self._story_lookup_var = tk.StringVar(value='')
        story_entry = tk.Entry(
            tb, textvariable=self._story_lookup_var, width=14,
            bg=BG4, fg=FG, insertbackground=FG,
            font=('Segoe UI', 9), relief=tk.FLAT
        )
        story_entry.pack(side=tk.LEFT, pady=4)
        story_entry.bind('<Return>', self._lookup_issue)

        tk.Button(
            tb, text='Go',
            command=self._lookup_issue,
            bg=BG2, fg=FG, font=('Segoe UI', 9),
            relief=tk.FLAT, padx=8
        ).pack(side=tk.LEFT, padx=6, pady=4)

        tk.Label(tb, text='Filter:', bg=BG3, fg=FG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(10, 2), pady=4)
        self._issue_filter_var = tk.StringVar(value='')
        filter_entry = tk.Entry(
            tb, textvariable=self._issue_filter_var, width=20,
            bg=BG4, fg=FG, insertbackground=FG,
            font=('Segoe UI', 9), relief=tk.FLAT
        )
        filter_entry.pack(side=tk.LEFT, pady=4)
        self._issue_filter_var.trace_add('write', lambda *_: self._apply_issue_filters())

        tk.Button(
            tb, text='Clear',
            command=lambda: self._issue_filter_var.set(''),
            bg=BG2, fg=FG, font=('Segoe UI', 9),
            relief=tk.FLAT, padx=8
        ).pack(side=tk.LEFT, padx=6, pady=4)

        tk.Button(tb, text=' Refresh', image=self._icons.get('refresh'),
                  compound=tk.LEFT, command=self._refresh_current,
                  bg=BG2, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=8).pack(side=tk.LEFT, padx=6, pady=4)

        self._status_var = tk.StringVar(value='')
        tk.Label(tb, textvariable=self._status_var, bg=BG3, fg=FG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=6)

        # ── Main paned layout ─────────────────────────────────────────────────
        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL,
                              bg=BG, sashwidth=4, sashrelief=tk.FLAT)
        pane.pack(fill=tk.BOTH, expand=True)

        # Left: tabs (My Stories / Sprint Board)
        left = tk.Frame(pane, bg=BG)
        pane.add(left, minsize=320)

        self._nb = ttk.Notebook(left, style='Jira.TNotebook')
        self._nb.pack(fill=tk.BOTH, expand=True)
        self._nb.bind('<<NotebookTabChanged>>', self._on_tab_change)

        self._my_frame     = tk.Frame(self._nb, bg=BG)
        self._sprint_frame = tk.Frame(self._nb, bg=BG)
        self._nb.add(self._my_frame,     text=' My Stories ')
        self._nb.add(self._sprint_frame, text=' Sprint Board ')

        self._build_issue_list(self._my_frame,     '_my_tree')
        self._build_issue_list(self._sprint_frame, '_sprint_tree')

        # "Show closed" checkbox — placed over the notebook tab bar, right-aligned
        # place() overlays it on the tab strip row (~30px tall) in the left frame
        self._show_closed_var = tk.BooleanVar(value=False)
        self._show_closed_cb = tk.Checkbutton(
            left, text='Show closed',
            variable=self._show_closed_var,
            command=self._load_my_stories,
            bg='#2d2d30', fg=FG2, selectcolor=BG,
            activebackground='#2d2d30', activeforeground=FG,
            font=('Segoe UI', 9), bd=0, cursor='hand2',
        )
        # Place in top-right of `left`, overlapping the tab bar (y=4 centres it)
        self._show_closed_cb.place(relx=1.0, x=-6, y=5, anchor='ne')
        # Only visible on My Stories tab
        self._nb.bind('<<NotebookTabChanged>>',
                      lambda e: self._show_closed_cb.place(relx=1.0, x=-6, y=5, anchor='ne')
                      if self._nb.index(self._nb.select()) == 0
                      else self._show_closed_cb.place_forget(), add='+')

        # Right: detail panel
        right = tk.Frame(pane, bg=BG2)
        pane.add(right, minsize=380)
        self._build_detail_panel(right)

    def _build_issue_list(self, parent: tk.Frame, attr: str):
        meta = {
            'attr': attr,
            'all_issues': [],
            'visible_keys': [],
            'sort_col': None,
            'sort_desc': False,
            'mode': 'tree',
        }
        self._issue_views[attr] = meta

        if TKSHEET_AVAILABLE:
            headers = ['Type', 'Story', 'Pri', 'Summary', 'Status', 'Start', 'End']
            sheet = _Sheet(
                parent,
                headers=headers,
                data=[],
                theme='dark',
                show_row_index=False,
                row_height=24,
                header_height=28,
                font=('Segoe UI', 10, 'normal'),
                header_font=('Segoe UI', 10, 'bold'),
                column_width=120,
                header_bg=BG3,
                header_fg=ACCENT2,
                table_bg=BG2,
                table_fg=FG,
                frame_bg=BG,
                selected_rows_border_fg=ACCENT,
                selected_rows_bg='#1e3a5f',
                selected_rows_fg='#ffffff',
            )
            sheet.pack(fill=tk.BOTH, expand=True)
            sheet.set_column_widths([88, 118, 56, 280, 110, 72, 72])
            sheet.enable_bindings(
                'single_select', 'row_select', 'arrowkeys',
                'column_width_resize', 'column_select', 'rc_select',
            )
            sheet.readonly_columns(columns=list(range(len(headers))))
            sheet.extra_bindings([
                ('cell_select', lambda event, _attr=attr: self._on_issue_sheet_selected(_attr, event)),
                ('row_select', lambda event, _attr=attr: self._on_issue_sheet_selected(_attr, event)),
            ])
            sheet.CH.bind(
                '<ButtonRelease-1>',
                lambda event, _attr=attr: self._on_issue_sheet_header_clicked(_attr, event),
                add=True,
            )
            setattr(self, attr, sheet)
            meta['widget'] = sheet
            meta['mode'] = 'sheet'
            return

        # #0 = tree column used for type icon (PIL image); data cols have no 'type' col
        cols = ('key', 'pri', 'summary', 'status', 'tstart', 'tend')
        tv = ttk.Treeview(parent, columns=cols, show='tree headings',
                          selectmode='browse', style='Jira.Treeview')
        # Tree column (#0) — icon only, wide enough so image doesn't bleed into key col
        tv.column('#0',      width=28,  stretch=False, minwidth=28)
        tv.heading('#0',     text='')
        tv.heading('key',     text='Story',   anchor='w',
                   command=lambda _attr=attr: self._sort_issue_view(_attr, 'key'))
        tv.heading('pri',     text='Pri',     anchor='center',
                   command=lambda _attr=attr: self._sort_issue_view(_attr, 'pri'))
        tv.heading('summary', text='Summary', anchor='w',
                   command=lambda _attr=attr: self._sort_issue_view(_attr, 'summary'))
        tv.heading('status',  text='Status',  anchor='w',
                   command=lambda _attr=attr: self._sort_issue_view(_attr, 'status'))
        tv.heading('tstart',  text='Start',   anchor='center',
                   command=lambda _attr=attr: self._sort_issue_view(_attr, 'tstart'))
        tv.heading('tend',    text='End',     anchor='center',
                   command=lambda _attr=attr: self._sort_issue_view(_attr, 'tend'))
        tv.column('key',     width=116, stretch=False)
        tv.column('pri',     width=50,  stretch=False)
        tv.column('summary', width=220, stretch=True)
        tv.column('status',  width=100, stretch=False)
        tv.column('tstart',  width=68,  stretch=False)
        tv.column('tend',    width=68,  stretch=False)

        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=tv.yview)
        tv.configure(yscrollcommand=sb.set)
        tv.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        tv.bind('<<TreeviewSelect>>', self._on_issue_select)
        setattr(self, attr, tv)
        add_treeview_menu(tv)
        meta['widget'] = tv

        # Style tags per status
        for status, (bg, fg) in _STATUS_COLORS.items():
            tv.tag_configure(status.lower().replace(' ', '_'), foreground=fg, background=bg)

    def _build_detail_panel(self, parent: tk.Frame):
        # Title bar
        title_bar = tk.Frame(parent, bg=BG3)
        title_bar.pack(fill=tk.X)

        self._issue_key_var = tk.StringVar(value='Select a story')
        tk.Label(title_bar, textvariable=self._issue_key_var,
                 font=('Segoe UI', 11, 'bold'), fg=ACCENT, bg=BG3
                 ).pack(side=tk.LEFT, padx=10, pady=6)

        self._open_btn = tk.Button(
            title_bar, text='Open in Browser',
            image=self._icons.get('browser'), compound=tk.LEFT,
            command=self._open_in_browser,
            bg=BG2, fg=FG, font=('Segoe UI', 9),
            relief=tk.FLAT, padx=8, state=tk.DISABLED
        )
        self._open_btn.pack(side=tk.RIGHT, padx=6, pady=4)

        # Transition button bar (populated dynamically, hidden until story selected)
        self._trans_bar = tk.Frame(parent, bg=BG3)
        self._trans_bar.pack(fill=tk.X)
        tk.Label(self._trans_bar, text='Move to:', bg=BG3, fg=FG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(8, 4), pady=4)

        # Stable tk.Text for detail content — no dynamic widget create/destroy
        detail_frame = tk.Frame(parent, bg=BG2)
        detail_frame.pack(fill=tk.BOTH, expand=True)
        self._detail_text = tk.Text(
            detail_frame, wrap=tk.WORD, bg=BG2, fg=FG,
            font=('Segoe UI', 9), relief=tk.FLAT,
            padx=12, pady=8, state=tk.DISABLED,
            cursor='arrow', selectbackground=BG3
        )
        vsb = ttk.Scrollbar(detail_frame, orient=tk.VERTICAL,
                            command=self._detail_text.yview)
        self._detail_text.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._detail_text.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(self._detail_text)

        # Configure HTML rendering tags + link opener via host daemon
        _setup_html_tags(self._detail_text, self._open_url_via_daemon)

        # Comment entry at bottom
        comment_frame = tk.Frame(parent, bg=BG3)
        comment_frame.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Label(comment_frame, text='Add Comment:', bg=BG3, fg=FG2,
                 font=('Segoe UI', 9)).pack(anchor='w', padx=8, pady=(6, 2))
        self._comment_text = tk.Text(comment_frame, height=3,
                                     bg=BG4, fg=FG, insertbackground=FG,
                                     font=('Consolas', 9), relief=tk.FLAT,
                                     wrap=tk.WORD)
        self._comment_text.pack(fill=tk.X, padx=8, pady=(0, 4))
        make_text_copyable(self._comment_text)
        self._post_btn = tk.Button(
            comment_frame, text='Post Comment',
            command=self._post_comment,
            bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT, padx=10, pady=3, state=tk.DISABLED
        )
        self._post_btn.pack(anchor='e', padx=8, pady=(0, 6))

    # ── URL opener via host daemon ────────────────────────────────────────────

    def _open_url_via_daemon(self, url: str):
        """Open a URL in Chrome on the host via the host tools daemon."""
        def _run():
            try:
                from auger.tools.host_cmd import open_url
                open_url(url)
            except Exception as e:
                self._q(lambda: self._status_var.set(f'ERROR: Could not open URL: {e}'))
        threading.Thread(target=_run, daemon=True).start()

    # ── Session init ──────────────────────────────────────────────────────────

    def _init_session(self):
        """Initialize Jira session using API token authentication."""
        # Reload .env values (in case they were just updated by API Keys+ widget)
        load_dotenv(_auger_home() / '.auger' / '.env', override=True)
        self._jira_url = os.getenv('JIRA_BASE_URL', '').strip()
        self._jira_username = os.getenv('JIRA_USERNAME', '').strip()
        self._jira_token = os.getenv('JIRA_API_TOKEN', '').strip()
        
        def _check():
            # Check if configuration is complete
            if not self._jira_url or not self._jira_username or not self._jira_token:
                self._q(lambda: self._set_config_required())
                return
            
            try:
                # Test API connection with Basic Auth
                auth_str = base64.b64encode(
                    f"{self._jira_username}:{self._jira_token}".encode()
                ).decode()
                
                headers = {
                    'Authorization': f'Basic {auth_str}',
                    'Accept': 'application/json'
                }
                
                # Get current user
                resp = requests.get(
                    f"{self._jira_url.rstrip('/')}/rest/api/3/myself",
                    headers=headers,
                    timeout=10
                )
                
                if resp.status_code == 200:
                    user_data = resp.json()
                    display_name = user_data.get('displayName', user_data.get('name', 'Unknown'))
                    self._jira_headers = headers
                    self._q(lambda d=display_name: self._set_auth_ok(d))
                    self._q(self._load_my_stories)
                elif resp.status_code == 401:
                    self._q(lambda: self._set_auth_fail("Invalid credentials"))
                else:
                    self._q(lambda: self._set_auth_fail(f"HTTP {resp.status_code}"))
                    
            except requests.exceptions.ConnectionError:
                self._q(lambda: self._set_auth_fail("Cannot connect to Jira URL"))
            except requests.exceptions.Timeout:
                self._q(lambda: self._set_auth_fail("Connection timeout"))
            except Exception as e:
                self._q(lambda: self._set_auth_fail(str(e)[:80]))
        
        threading.Thread(target=_check, daemon=True).start()

    def _set_auth_ok(self, display_name: str):
        """Update UI to show successful authentication."""
        self._auth_label.config(text='✓ Authenticated', fg='#88ff88')
        self._user_label.config(text=f'👤 {display_name}')
        self._config_btn.config(state=tk.DISABLED)

    def _set_config_required(self):
        """Update UI to show that configuration is required."""
        self._auth_label.config(text='⚙ Configuration Required', fg=WARNING)
        self._status_var.set('Configure Jira in API Keys+ widget')
        self._config_btn.config(state=tk.NORMAL)
    
    def _set_auth_fail(self, msg: str = ''):
        """Update UI to show authentication failure."""
        self._auth_label.config(text=f'✗ Error: {msg}', fg=ERROR)
        self._config_btn.config(state=tk.NORMAL)
        self._status_var.set('Click ⚙ to configure Jira credentials')

    def _show_config_help(self):
        """Show configuration instructions and re-check after dialog closes."""
        from tkinter import messagebox
        messagebox.showinfo(
            'Configure Jira',
            'To use this Jira widget:\n\n'
            '1. Open the API Keys+ widget\n'
            '2. Scroll to the Jira section\n'
            '3. Enter your Jira base URL (e.g., https://yourname.atlassian.net)\n'
            '4. Enter your Jira username/email\n'
            '5. Generate an API token at:\n'
            '   https://id.atlassian.com/manage-profile/security/api-tokens\n'
            '6. Paste the API token\n\n'
            'This widget will auto-refresh when you save the configuration.'
        )
        # Re-check after dialog closes (user may have configured Jira in another window)
        self.after(500, self._init_session)

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_my_stories(self):
        if not self._jira_headers:
            self._status_var.set('Not authenticated - configure Jira in API Keys+')
            return
        self._status_var.set('Loading my stories…')
        proj = self._proj_var.get().strip()

        def _run():
            try:
                # JQL query for issues assigned to current user
                jql = 'assignee = currentUser() ORDER BY updated DESC'
                if proj:
                    jql = f'project = {proj} AND assignee = currentUser() ORDER BY updated DESC'
                
                url = f"{self._jira_url.rstrip('/')}/rest/api/3/search"
                params = {
                    'jql': jql,
                    'maxResults': 100,
                    'fields': 'summary,status,priority,issuetype,created,updated'
                }
                
                resp = requests.get(url, headers=self._jira_headers, params=params, timeout=10)
                resp.raise_for_status()
                
                issues = resp.json().get('issues', [])
                self._q(lambda: self._populate_issue_view('_my_tree', issues))
                self._q(lambda: self._status_var.set(f'{len(issues)} stories assigned to me'))
            except requests.exceptions.RequestException as e:
                self._q(lambda: self._status_var.set(f'ERROR loading stories: {e}'))
            except Exception as e:
                self._q(lambda: self._status_var.set(f'ERROR: {str(e)[:60]}'))

        threading.Thread(target=_run, daemon=True).start()

    def _load_sprint(self):
        if not self._jira_headers:
            self._status_var.set('Not authenticated - configure Jira in API Keys+')
            return
        self._status_var.set('Loading sprint issues…')
        proj = self._proj_var.get().strip()

        def _run():
            try:
                # Get active sprint
                board_url = f"{self._jira_url.rstrip('/')}/rest/agile/1.0/board"
                board_params = {'projectKey': proj} if proj else {}
                
                board_resp = requests.get(
                    board_url, headers=self._jira_headers, params=board_params, timeout=10
                )
                board_resp.raise_for_status()
                boards = board_resp.json().get('values', [])
                
                if not boards:
                    self._q(lambda: self._status_var.set('No boards found for project'))
                    return
                
                board_id = boards[0]['id']
                
                # Get active sprint for this board
                sprint_url = f"{self._jira_url.rstrip('/')}/rest/agile/1.0/board/{board_id}/sprint"
                sprint_params = {'state': 'active'}
                
                sprint_resp = requests.get(
                    sprint_url, headers=self._jira_headers, params=sprint_params, timeout=10
                )
                sprint_resp.raise_for_status()
                sprints = sprint_resp.json().get('values', [])
                
                if not sprints:
                    self._q(lambda: self._status_var.set('No active sprint found'))
                    return
                
                sprint_id = sprints[0]['id']
                
                # Get issues in active sprint
                issue_url = f"{self._jira_url.rstrip('/')}/rest/agile/1.0/sprint/{sprint_id}/issue"
                issue_params = {
                    'maxResults': 100,
                    'fields': 'summary,status,priority,issuetype,created,updated'
                }
                
                issue_resp = requests.get(
                    issue_url, headers=self._jira_headers, params=issue_params, timeout=10
                )
                issue_resp.raise_for_status()
                
                issues = issue_resp.json().get('issues', [])
                self._q(lambda: self._populate_issue_view('_sprint_tree', issues))
                self._q(lambda: self._status_var.set(f'{len(issues)} issues in active sprint'))
            except requests.exceptions.RequestException as e:
                self._q(lambda: self._status_var.set(f'ERROR loading sprint: {e}'))
            except Exception as e:
                self._q(lambda: self._status_var.set(f'ERROR: {str(e)[:60]}'))

        threading.Thread(target=_run, daemon=True).start()

    def _issue_filter_text(self) -> str:
        return (getattr(self, '_issue_filter_var', None).get() or '').strip().lower()

    def _issue_type_label(self, issue: dict) -> str:
        return (issue.get('fields', {}).get('issuetype', {}).get('name', '') or '?')[:12]

    def _issue_sort_value(self, issue: dict, col: str):
        f = issue.get('fields', {})
        if col == 'type':
            return self._issue_type_label(issue).lower()
        if col == 'key':
            return issue.get('key', '')
        if col == 'pri':
            pri = (f.get('priority', {}).get('name', '') or '').lower()
            order = {'blocker': 0, 'highest': 0, 'high': 1, 'medium': 2, 'low': 3, 'lowest': 4}
            for key, rank in order.items():
                if key in pri:
                    return (rank, pri)
            return (99, pri)
        if col == 'summary':
            return (f.get('summary', '') or '').lower()
        if col == 'status':
            return (f.get('status', {}).get('name', '') or '').lower()
        if col == 'tstart':
            return f.get('customfield_10022') or ''
        if col == 'tend':
            return f.get('customfield_10023') or ''
        return ''

    def _issue_matches_filter(self, issue: dict, filter_text: str) -> bool:
        if not filter_text:
            return True
        f = issue.get('fields', {})
        searchable = ' '.join([
            issue.get('key', ''),
            self._issue_type_label(issue),
            f.get('priority', {}).get('name', '') or '',
            f.get('summary', '') or '',
            f.get('status', {}).get('name', '') or '',
            _fmt_date(f.get('customfield_10022') or ''),
            _fmt_date(f.get('customfield_10023') or ''),
        ]).lower()
        return filter_text in searchable

    def _issue_row_values(self, issue: dict):
        f = issue.get('fields', {})
        return [
            self._issue_type_label(issue),
            issue.get('key', ''),
            _priority_short(f.get('priority', {}).get('name', '')),
            (f.get('summary', '') or '')[:100],
            f.get('status', {}).get('name', '') or '',
            _fmt_date(f.get('customfield_10022') or ''),
            _fmt_date(f.get('customfield_10023') or ''),
        ]

    def _populate_issue_view(self, attr: str, issues: list):
        meta = self._issue_views[attr]
        meta['all_issues'] = list(issues or [])
        self._apply_issue_filters(attr)

    def _apply_issue_filters(self, attr: str | None = None):
        attrs = [attr] if attr else list(self._issue_views.keys())
        filter_text = self._issue_filter_text()
        for view_attr in attrs:
            meta = self._issue_views.get(view_attr)
            if not meta:
                continue
            issues = [issue for issue in meta['all_issues'] if self._issue_matches_filter(issue, filter_text)]
            if meta.get('sort_col'):
                issues = sorted(
                    issues,
                    key=lambda issue, col=meta['sort_col']: self._issue_sort_value(issue, col),
                    reverse=bool(meta.get('sort_desc')),
                )
            meta['visible_keys'] = [issue.get('key', '') for issue in issues]
            widget = meta.get('widget')
            if meta.get('mode') == 'sheet':
                self._populate_sheet(widget, issues)
            else:
                self._populate_tree(widget, issues)
        self._update_issue_filter_status()

    def _update_issue_filter_status(self):
        visible_attr = self._visible_issue_attr()
        meta = self._issue_views.get(visible_attr)
        if not meta or not meta.get('all_issues'):
            return
        shown = len(meta.get('visible_keys', []))
        total = len(meta.get('all_issues', []))
        filter_text = self._issue_filter_text()
        if filter_text:
            self._status_var.set(f'Showing {shown} of {total} issues')

    def _populate_sheet(self, sheet, issues: list):
        if sheet is None:
            return
        rows = [self._issue_row_values(issue) for issue in issues]
        sheet.set_sheet_data(rows, reset_col_positions=False, redraw=False, reset_highlights=True)
        if rows:
            for row_idx, issue in enumerate(issues):
                status = issue.get('fields', {}).get('status', {}).get('name', '') or ''
                bg, fg = _status_color(status)
                sheet.highlight_rows(row_idx, bg=bg, fg=fg, highlight_index=False, redraw=False)
        sheet.refresh()

    def _populate_tree(self, tree: ttk.Treeview, issues: list):
        tree.delete(*tree.get_children())
        for issue in issues:
            f     = issue.get('fields', {})
            key   = issue.get('key', '')
            itype = f.get('issuetype', {}).get('name', '')
            pri   = f.get('priority',  {}).get('name', '')
            summ  = f.get('summary', '')
            stat  = f.get('status',   {}).get('name', '')
            tstart = _fmt_date(f.get('customfield_10022') or '')
            tend   = _fmt_date(f.get('customfield_10023') or '')
            bg, fg = _status_color(stat)
            tag    = stat.lower().replace(' ', '_')
            pri_short = _priority_short(pri)

            # Type icon via PIL in tree column #0
            type_img = _type_pil_icon(itype) if _PIL_OK else None

            kw = dict(
                values=(key, pri_short, summ[:80], stat, tstart, tend),
                tags=(tag,),
                text='',
            )
            if type_img:
                kw['image'] = type_img
            tree.insert('', tk.END, iid=key, **kw)
            tree.tag_configure(tag, foreground=fg, background=bg)

    def _visible_issue_attr(self) -> str:
        return '_my_tree' if self._nb.index(self._nb.select()) == 0 else '_sprint_tree'

    def _refresh_current(self):
        tab = self._nb.index(self._nb.select())
        if tab == 0:
            self._load_my_stories()
        else:
            self._load_sprint()

    def _normalize_issue_key(self, raw_key: str) -> str:
        raw = (raw_key or '').strip().upper()
        if not raw:
            return ''
        if raw.isdigit():
            proj = (self._proj_var.get().strip() or '').upper()
            if proj:
                return f'{proj}-{raw}'
            return raw
        if '-' not in raw and raw.split()[-1].isdigit():
            proj = (self._proj_var.get().strip() or '').upper()
            if proj:
                return f'{proj}-{raw.split()[-1]}'
            return raw
        return raw

    def _visible_tree(self):
        return getattr(self, self._visible_issue_attr())

    def _visible_issue_meta(self):
        return self._issue_views.get(self._visible_issue_attr())

    def _select_issue_in_visible_tree(self, issue_key: str):
        meta = self._visible_issue_meta()
        if not meta:
            return
        widget = meta.get('widget')
        if meta.get('mode') == 'sheet':
            try:
                row_idx = meta.get('visible_keys', []).index(issue_key)
            except ValueError:
                return
            self._suppress_tree_select = True
            widget.deselect('all', redraw=False)
            widget.select_row(row_idx, redraw=False, run_binding_func=False)
            widget.set_currently_selected(row=row_idx, column=0)
            widget.see(row=row_idx, column=0, redraw=False)
            widget.refresh()
            self.after(100, lambda: setattr(self, '_suppress_tree_select', False))
            return
        tree = widget
        if tree.exists(issue_key):
            self._suppress_tree_select = True
            tree.selection_set(issue_key)
            tree.focus(issue_key)
            tree.see(issue_key)
            self.after(100, lambda: setattr(self, '_suppress_tree_select', False))

    def _load_issue_detail(self, issue_key: str):
        if not self._jira_headers:
            self._status_var.set('Configure Jira in API Keys+ widget')
            return
        self._status_var.set(f'Loading {issue_key}…')

        def _run():
            try:
                url = f"{self._jira_url.rstrip('/')}/rest/api/3/issues/{issue_key}"
                params = {
                    'fields': 'summary,status,priority,issuetype,description,created,updated,comment,customfield_10022,customfield_10023',
                    'expand': 'changelog'
                }
                
                resp = requests.get(url, headers=self._jira_headers, params=params, timeout=10)
                
                if resp.status_code == 404:
                    self._q(lambda: self._status_var.set(f'Issue not found: {issue_key}'))
                    return
                
                resp.raise_for_status()
                issue = resp.json()
                
                # Get transitions
                trans_url = f"{url}/transitions"
                trans_resp = requests.get(trans_url, headers=self._jira_headers, timeout=10)
                trans = trans_resp.json().get('transitions', []) if trans_resp.status_code == 200 else []
                
                self._q(lambda: self._select_issue_in_visible_tree(issue_key))
                self._q(lambda: self._show_detail(issue, trans))
            except requests.exceptions.RequestException as e:
                self._q(lambda: self._status_var.set(f'ERROR loading {issue_key}: {e}'))
            except Exception as e:
                self._q(lambda: self._status_var.set(f'ERROR: {str(e)[:60]}'))

        threading.Thread(target=_run, daemon=True).start()

    def _lookup_issue(self, event=None):
        issue_key = self._normalize_issue_key(self._story_lookup_var.get())
        if not issue_key:
            self._status_var.set('Enter a story like 38803 or ASSIST3-38803')
            return
        self._load_issue_detail(issue_key)

    def _on_tab_change(self, event=None):
        if not self._jira_headers:
            return
        tab = self._nb.index(self._nb.select())
        sprint_meta = self._issue_views.get('_sprint_tree', {})
        if tab == 1 and not sprint_meta.get('all_issues'):
            self._load_sprint()
        self._update_issue_filter_status()

    # ── Issue selection ───────────────────────────────────────────────────────

    def _on_issue_sheet_header_clicked(self, attr: str, event=None):
        meta = self._issue_views.get(attr)
        if not meta or meta.get('mode') != 'sheet':
            return
        widget = meta.get('widget')
        try:
            col_idx = widget.MT.identify_col(x=event.x) if event is not None and hasattr(event, 'x') else None
        except Exception:
            col_idx = None
        if col_idx is None:
            return
        col_key = {idx: key for idx, key in enumerate(self._issue_col_keys)}.get(col_idx)
        if col_key:
            self._sort_issue_view(attr, col_key)

    def _sort_issue_view(self, attr: str, col: str):
        meta = self._issue_views.get(attr)
        if not meta:
            return
        if meta.get('sort_col') == col:
            meta['sort_desc'] = not meta.get('sort_desc', False)
        else:
            meta['sort_col'] = col
            meta['sort_desc'] = False
        self._apply_issue_filters(attr)

    def _on_issue_sheet_selected(self, attr: str, event=None):
        if self._suppress_tree_select:
            return
        meta = self._issue_views.get(attr)
        if not meta or meta.get('mode') != 'sheet':
            return
        widget = meta.get('widget')
        sel = widget.get_currently_selected()
        if not sel:
            return
        row_idx = sel.row if hasattr(sel, 'row') else (sel[0] if sel else None)
        if row_idx is None:
            return
        visible_keys = meta.get('visible_keys', [])
        if row_idx >= len(visible_keys):
            return
        self._load_issue_detail(visible_keys[row_idx])

    def _on_issue_select(self, event=None):
        # Determine which tree fired
        if self._suppress_tree_select:
            return
        tree = event.widget
        sel = tree.selection()
        if not sel or not self._jira_headers:
            return
        issue_key = sel[0]
        self._load_issue_detail(issue_key)

    def _show_detail(self, issue: dict | None, transitions: list):
        try:
            self._show_detail_inner(issue, transitions)
        except Exception as e:
            import traceback, pathlib
            log = _auger_home() / '.auger' / 'jira_widget.log'
            with open(str(log), 'a') as f:
                f.write('\n--- _show_detail crash ---\n')
                f.write(traceback.format_exc())
            self._status_var.set(f'ERROR: Detail render error: {e}')

    def _show_detail_inner(self, issue: dict | None, transitions: list):
        if not issue:
            self._status_var.set('WARN: Could not load issue')
            return
        self._sel_issue   = issue
        self._transitions = transitions
        key   = issue.get('key', '')
        f     = issue.get('fields', {})
        rf    = issue.get('renderedFields', {}) or {}   # HTML versions
        summ  = f.get('summary', '')
        stat  = f.get('status', {}).get('name', '')
        pri   = f.get('priority', {}).get('name', '')
        itype = f.get('issuetype', {}).get('name', '')
        tstart = _fmt_date(f.get('customfield_10022') or '')
        tend   = _fmt_date(f.get('customfield_10023') or '')
        # Prefer rendered HTML; fall back to plain text
        desc_html  = rf.get('description') or ''
        desc_plain = f.get('description') or '(no description)'
        comments_raw      = (f.get('comment')  or {}).get('comments', [])
        comments_rendered = (rf.get('comment') or {}).get('comments', [])

        self._issue_key_var.set(f'{_issue_type_icon(itype)} {key} - {summ[:60]}')
        self._open_btn.config(state=tk.NORMAL)
        self._post_btn.config(state=tk.NORMAL)
        self._status_var.set(f'{key} loaded — {len(comments_raw)} comment(s)')

        # ── Rebuild transition buttons ─────────────────────────────────────────
        for child in self._trans_bar.winfo_children():
            if isinstance(child, tk.Button):
                child.destroy()
        for t in transitions[:6]:
            tid   = t['id']
            tname = t['name']
            tbg, tfg = _status_color(tname)
            tk.Button(
                self._trans_bar, text=tname,
                bg=tbg, fg=tfg, font=('Segoe UI', 8),
                relief=tk.FLAT, padx=6, pady=2,
                command=lambda tid=tid, tname=tname: self._do_transition(key, tid, tname)
            ).pack(side=tk.LEFT, padx=2, pady=3)

        # ── Render into stable Text widget ────────────────────────────────────
        tw = self._detail_text
        tw.config(state=tk.NORMAL)
        # Reset link pool counter and URL registry (reuses pre-created tags — no tag_delete)
        tw._link_count = 0
        tw._link_urls  = {}
        tw.delete('1.0', tk.END)

        # Key + summary header
        tw.insert(tk.END, f'{key}\n', 'key')
        tw.insert(tk.END, f'{summ}\n\n', 'body')

        # Status / priority / dates line
        tw.insert(tk.END, 'Status: ',   'heading')
        tw.insert(tk.END, f'{stat}   ', 'status')
        tw.insert(tk.END, 'Priority: ', 'heading')
        tw.insert(tk.END, f'{_priority_icon(pri)} {pri}', 'priority')
        if tstart or tend:
            tw.insert(tk.END, '   Target: ', 'heading')
            tw.insert(tk.END, f'{tstart} - {tend}' if tend else tstart, 'body')
        tw.insert(tk.END, '\n\n', 'body')

        # Description — rendered HTML or plain fallback
        tw.insert(tk.END, 'Description\n', 'heading')
        tw.insert(tk.END, '─' * 60 + '\n', 'sep')
        if desc_html:
            _render_html(tw, desc_html)
        else:
            tw.insert(tk.END, desc_plain.strip() + '\n', 'body')
        tw.insert(tk.END, '\n', 'body')

        # Comments
        if comments_raw:
            tw.insert(tk.END, f'Comments ({len(comments_raw)})\n', 'heading')
            tw.insert(tk.END, '─' * 60 + '\n', 'sep')
            # Merge plain + rendered so we get HTML body where available
            rendered_map = {c.get('id'): c for c in comments_rendered}
            for c in comments_raw[-10:]:
                author  = c.get('author', {}).get('displayName', '?')
                updated = c.get('updated', '')[:10]
                cid     = c.get('id', '')
                tw.insert(tk.END, f'{author}  {updated}\n', 'author')
                rendered_body = rendered_map.get(cid, {}).get('body', '')
                if rendered_body:
                    _render_html(tw, rendered_body)
                else:
                    tw.insert(tk.END, c.get('body', '').strip()[:500] + '\n', 'body')
                tw.insert(tk.END, '\n', 'body')

        tw.config(state=tk.DISABLED)
        tw.see('1.0')

    # ── Actions ───────────────────────────────────────────────────────────────

    def _do_transition(self, issue_key: str, transition_id: str, transition_name: str):
        if not self._jira_headers:
            self._status_var.set('Not authenticated')
            return
        self._status_var.set(f'Moving {issue_key} → {transition_name}…')

        def _run():
            try:
                url = f"{self._jira_url.rstrip('/')}/rest/api/3/issues/{issue_key}/transitions"
                payload = {'transition': {'id': transition_id}}
                
                resp = requests.post(
                    url, json=payload, headers=self._jira_headers, timeout=10
                )
                
                if resp.status_code in (200, 204):
                    self._q(lambda: self._status_var.set(f'✓ {issue_key} → {transition_name}'))
                    self.after(500, self._refresh_current)
                    self.after(500, lambda: self._reload_detail(issue_key))
                else:
                    self._q(lambda: self._status_var.set(
                        f'ERROR: HTTP {resp.status_code}'))
            except requests.exceptions.RequestException as e:
                self._q(lambda: self._status_var.set(f'ERROR: {e}'))
            except Exception as e:
                self._q(lambda: self._status_var.set(f'ERROR: {str(e)[:50]}'))

        threading.Thread(target=_run, daemon=True).start()

    def _reload_detail(self, issue_key: str):
        if not self._jira_headers:
            return
        def _run():
            try:
                url = f"{self._jira_url.rstrip('/')}/rest/api/3/issues/{issue_key}"
                params = {'fields': 'summary,status,priority,issuetype,description,created,updated'}
                
                resp = requests.get(url, headers=self._jira_headers, params=params, timeout=10)
                resp.raise_for_status()
                issue = resp.json()
                
                # Get transitions
                trans_url = f"{url}/transitions"
                trans_resp = requests.get(trans_url, headers=self._jira_headers, timeout=10)
                trans = trans_resp.json().get('transitions', []) if trans_resp.status_code == 200 else []
                
                self._q(lambda: self._show_detail(issue, trans))
            except Exception as e:
                self._q(lambda: self._status_var.set(f'ERROR loading detail: {str(e)[:50]}'))
        
        threading.Thread(target=_run, daemon=True).start()

    def _post_comment(self):
        if not self._jira_headers or not self._sel_issue:
            return
        body = self._comment_text.get('1.0', tk.END).strip()
        if not body:
            return
        key = self._sel_issue.get('key', '')
        self._post_btn.config(state=tk.DISABLED)

        def _run():
            try:
                url = f"{self._jira_url.rstrip('/')}/rest/api/3/issues/{key}/comments"
                payload = {'body': {'content': [{'type': 'paragraph', 'content': [{'type': 'text', 'text': body}]}]}}
                
                resp = requests.post(
                    url, json=payload, headers=self._jira_headers, timeout=10
                )
                
                if resp.status_code in (200, 201):
                    self._q(lambda: self._comment_text.delete('1.0', tk.END))
                    self._q(lambda: self._status_var.set(f'✓ Comment posted to {key}'))
                    self.after(500, lambda: self._reload_detail(key))
                else:
                    self._q(lambda: self._status_var.set(f'ERROR: HTTP {resp.status_code}'))
            except requests.exceptions.RequestException as e:
                self._q(lambda: self._status_var.set(f'ERROR: {e}'))
            except Exception as e:
                self._q(lambda: self._status_var.set(f'ERROR: {str(e)[:50]}'))
            finally:
                self._q(lambda: self._post_btn.config(state=tk.NORMAL))

        threading.Thread(target=_run, daemon=True).start()

    def _open_in_browser(self):
        if not self._sel_issue:
            return
        key = self._sel_issue.get('key', '')
        # Open issue in Jira instance
        url = f"{self._jira_url.rstrip('/')}/browse/{key}"
        self._open_url_via_daemon(url)
