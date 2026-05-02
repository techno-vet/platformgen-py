"""
Help Viewer Widget — renders markdown docs in a tabbed interface.

Each open doc gets its own inner tab. Calling open_doc() with an already-open
path simply activates that tab instead of creating a duplicate.
"""

import tkinter as tk
from tkinter import ttk
from pathlib import Path
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu
from auger.ui.help_docs import all_docs as _all_docs

BG     = '#1e1e1e'
BG2    = '#252526'
BG3    = '#2d2d2d'
FG     = '#e0e0e0'
ACCENT = '#007acc'
ACCENT2= '#4ec9b0'
SUBTLE = '#888888'
H1_FG  = '#4fc1ff'
H2_FG  = '#4ec9b0'
H3_FG  = '#ce9178'
CODE_BG= '#1a1a1a'
CODE_FG= '#9cdcfe'
LINK_FG= '#569cd6'

# Markdown → Text widget tag styles
_TAG_STYLES = {
    'h1':     {'font': ('Segoe UI', 16, 'bold'), 'foreground': H1_FG,    'spacing1': 10, 'spacing3': 6},
    'h2':     {'font': ('Segoe UI', 13, 'bold'), 'foreground': H2_FG,    'spacing1': 8,  'spacing3': 4},
    'h3':     {'font': ('Segoe UI', 11, 'bold'), 'foreground': H3_FG,    'spacing1': 6,  'spacing3': 2},
    'bold':   {'font': ('Segoe UI', 10, 'bold'), 'foreground': FG},
    'italic': {'font': ('Segoe UI', 10, 'italic'), 'foreground': FG},
    'code':   {'font': ('Consolas', 9),           'foreground': CODE_FG,  'background': CODE_BG},
    'fence':  {'font': ('Consolas', 9),           'foreground': CODE_FG,  'background': CODE_BG,
                'lmargin1': 12, 'lmargin2': 12, 'spacing1': 2, 'spacing3': 2},
    'bullet': {'font': ('Segoe UI', 10),          'foreground': FG,
                'lmargin1': 20, 'lmargin2': 30},
    'hr':     {'font': ('Segoe UI', 4),           'foreground': '#444',   'spacing1': 4, 'spacing3': 4},
    'normal': {'font': ('Segoe UI', 10),          'foreground': FG,       'spacing1': 1, 'spacing3': 1},
    'tip':    {'font': ('Segoe UI', 10, 'italic'),'foreground': ACCENT2,  'lmargin1': 12, 'lmargin2': 12},
}



class HelpViewerWidget(tk.Frame):
    """Tabbed markdown help doc viewer."""

    WIDGET_NAME      = "help_viewer"
    WIDGET_TITLE     = "Help"
    WIDGET_ICON_NAME = "help"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._doc_tabs: dict[str, tk.Frame] = {}   # path → frame
        self._tab_icons: list = []                  # keep refs alive
        self._create_ui()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _create_ui(self):
        # Header
        hdr = tk.Frame(self, bg=BG2)
        hdr.pack(fill=tk.X, padx=5, pady=(5, 0))
        try:
            ico = _icons.get('help', 18)
            self._tab_icons.append(ico)
            tk.Label(hdr, image=ico, bg=BG2).pack(side=tk.LEFT, padx=(8, 4), pady=6)
        except Exception:
            pass
        tk.Label(hdr, text="Help & Documentation",
                 font=('Segoe UI', 12, 'bold'), fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, pady=6)
        tk.Label(hdr, text="  Tip: Ask Auger anything — just type in the chat below",
                 font=('Segoe UI', 9, 'italic'), fg=SUBTLE, bg=BG2).pack(side=tk.LEFT, pady=6)

        # Dropdown selector on the right side of header
        self._build_doc_selector(hdr)

        # Inner notebook for doc tabs
        style = ttk.Style()
        style.configure('Help.TNotebook',        background=BG,  borderwidth=0)
        style.configure('Help.TNotebook.Tab',    background=BG2, foreground=FG,
                         padding=[8, 4], font=('Segoe UI', 9))
        style.map('Help.TNotebook.Tab',
                  background=[('selected', BG3)],
                  foreground=[('selected', ACCENT2)])

        self._notebook = ttk.Notebook(self, style='Help.TNotebook')
        self._notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Welcome splash shown when no docs open
        self._splash = self._make_splash()
        self._notebook.add(self._splash, text="  Welcome  ")

    def _build_doc_selector(self, parent: tk.Frame):
        """Build the right-side dropdown that lists all available docs."""
        docs = _all_docs()
        if not docs:
            return
        self._doc_map = {label: str(path) for label, path in docs}
        labels = [label for label, _ in docs]

        tk.Label(parent, text="Open doc:", font=('Segoe UI', 9),
                 fg=SUBTLE, bg=BG2).pack(side=tk.RIGHT, padx=(0, 4), pady=6)

        self._doc_var = tk.StringVar(value="")
        combo = ttk.Combobox(parent, textvariable=self._doc_var,
                             values=labels, state='readonly',
                             font=('Segoe UI', 9), width=22)
        combo.pack(side=tk.RIGHT, padx=(0, 8), pady=6)

        style = ttk.Style()
        style.configure('DocSelect.TCombobox', fieldbackground=BG3,
                         background=BG2, foreground=FG, arrowcolor=ACCENT2)
        combo.configure(style='DocSelect.TCombobox')

        combo.bind('<<ComboboxSelected>>', self._on_doc_selected)

    def _on_doc_selected(self, event=None):
        label = self._doc_var.get()
        if not label:
            return
        path = self._doc_map.get(label)
        if path:
            self.open_doc(path, label)
        # Reset so the same item can be re-selected
        self._doc_var.set("")

    def _make_splash(self) -> tk.Frame:
        f = tk.Frame(self._notebook, bg=BG)
        tk.Label(f, text="[?]", font=('Segoe UI', 36), bg=BG, fg=ACCENT).pack(pady=(40, 8))
        tk.Label(f, text="Help & Documentation",
                 font=('Segoe UI', 14, 'bold'), fg=ACCENT2, bg=BG).pack()
        tk.Label(f,
                 text="Select a topic from the Help menu  or  Widgets → Help\n\n"
                      "Or just Ask Auger — type your question in the chat below.",
                 font=('Segoe UI', 10), fg=SUBTLE, bg=BG, justify=tk.CENTER).pack(pady=12)
        return f

    # ── Public API ────────────────────────────────────────────────────────────

    def open_doc(self, path: str, title: str):
        """Open a markdown doc in a tab. If already open, activate that tab."""
        key = str(path)
        if key in self._doc_tabs:
            self._notebook.select(self._doc_tabs[key])
            return

        doc_path = Path(path)
        if not doc_path.exists():
            self._open_error_tab(title, f"File not found:\n{path}")
            return

        try:
            md_text = doc_path.read_text(errors='replace')
        except Exception as e:
            self._open_error_tab(title, str(e))
            return

        frame = tk.Frame(self._notebook, bg=BG)
        self._build_doc_tab(frame, md_text, title, key)
        tab_label = f"  {title}  "
        try:
            ico = _icons.get('file', 14)
            self._tab_icons.append(ico)
            self._notebook.add(frame, image=ico, text=tab_label, compound=tk.LEFT)
        except Exception:
            self._notebook.add(frame, text=tab_label)
        self._notebook.select(frame)
        self._doc_tabs[key] = frame

    def _open_error_tab(self, title: str, msg: str):
        frame = tk.Frame(self._notebook, bg=BG)
        tk.Label(frame, text=f"Error loading '{title}':\n\n{msg}",
                 font=('Consolas', 10), fg='#f44747', bg=BG,
                 justify=tk.LEFT).pack(padx=20, pady=20)
        self._notebook.add(frame, text=f"  {title} (error)  ")
        self._notebook.select(frame)

    # ── Markdown renderer ─────────────────────────────────────────────────────

    def _build_doc_tab(self, parent: tk.Frame, md: str, title: str, key: str):
        """Render markdown into a scrollable Text widget."""
        # Toolbar
        toolbar = tk.Frame(parent, bg=BG2)
        toolbar.pack(fill=tk.X)
        tk.Label(toolbar, text=title, font=('Segoe UI', 10, 'bold'),
                 fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, padx=10, pady=4)
        tk.Button(toolbar, text=" X Close",
                  font=('Segoe UI', 8), fg=FG, bg=BG2, relief=tk.FLAT, bd=0,
                  activebackground='#3a3a3a', activeforeground='#f44747',
                  command=lambda k=key: self._close_tab(k)).pack(side=tk.RIGHT, padx=6)

        # Scrollable text
        txt_frame = tk.Frame(parent, bg=BG)
        txt_frame.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(txt_frame, orient=tk.VERTICAL)
        txt = tk.Text(txt_frame, bg=BG, fg=FG, font=('Segoe UI', 10),
                      relief=tk.FLAT, bd=0, padx=18, pady=14,
                      wrap=tk.WORD, cursor='arrow',
                      state=tk.NORMAL,
                      yscrollcommand=scrollbar.set,
                      selectbackground=ACCENT, selectforeground='white',
                      insertbackground=BG)
        scrollbar.config(command=txt.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        make_text_copyable(txt)

        # Configure tags
        for tag, opts in _TAG_STYLES.items():
            txt.tag_configure(tag, **opts)

        self._render_markdown(txt, md)
        txt.config(state=tk.DISABLED)

    def _close_tab(self, key: str):
        frame = self._doc_tabs.pop(key, None)
        if frame:
            self._notebook.forget(frame)
            frame.destroy()

    def _render_markdown(self, txt: tk.Text, md: str):
        """Naive but effective markdown → Tk Text renderer."""
        import re
        lines = md.splitlines()
        in_fence = False
        fence_buf: list[str] = []

        def insert(content, *tags):
            txt.insert(tk.END, content, tags)

        i = 0
        while i < len(lines):
            line = lines[i]

            # Fenced code blocks
            if line.strip().startswith('```'):
                if not in_fence:
                    in_fence = True
                    fence_buf = []
                    i += 1
                    continue
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

            # Horizontal rule
            if re.match(r'^[-*_]{3,}\s*$', line):
                insert('─' * 60 + '\n', 'hr')
                i += 1
                continue

            # Headings
            m = re.match(r'^(#{1,3})\s+(.*)', line)
            if m:
                level = len(m.group(1))
                tag = f'h{level}'
                text = re.sub(r'\*\*(.+?)\*\*', r'\1', m.group(2))
                text = re.sub(r'`(.+?)`', r'\1', text)
                insert(text + '\n', tag)
                i += 1
                continue

            # Bullet / list items
            m = re.match(r'^(\s*)[-*+]\s+(.*)', line)
            if m:
                indent = len(m.group(1))
                bullet = '  ' * (indent // 2) + '• '
                self._insert_inline(txt, bullet + m.group(2) + '\n', base_tag='bullet')
                i += 1
                continue

            # Numbered list
            m = re.match(r'^(\s*)\d+\.\s+(.*)', line)
            if m:
                bullet = '  ' * (len(m.group(1)) // 2) + '  '
                self._insert_inline(txt, bullet + m.group(2) + '\n', base_tag='bullet')
                i += 1
                continue

            # Blank line
            if not line.strip():
                insert('\n', 'normal')
                i += 1
                continue

            # Normal paragraph line
            self._insert_inline(txt, line + '\n', base_tag='normal')
            i += 1

    def _insert_inline(self, txt: tk.Text, text: str, base_tag='normal'):
        """Insert text handling inline **bold**, *italic*, and `code`."""
        import re
        # Pattern: **bold**, *italic*, `code`
        pattern = re.compile(r'(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)')
        pos = 0
        for m in pattern.finditer(text):
            # Insert plain text before match
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
