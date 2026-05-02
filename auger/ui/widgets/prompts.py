"""
Prompts Widget — parameterized prompt/command library.

Loads prompts from (in priority order):
  1. ~/.auger/prompts.yaml  (user overrides / additions)
  2. <repo>/config/prompts.yaml  (repo defaults shipped with app)

Prompts with the same id in the user file override repo defaults.
"""
import queue
import re
import subprocess
import threading
from pathlib import Path

import tkinter as tk
import tkinter.ttk as ttk
import yaml

from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu

try:
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw, ImageTk as _PILImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

# ── Colours (match app theme) ────────────────────────────────────────────────
BG     = "#1e1e1e"
BG2    = "#252526"
BG3    = "#2d2d2d"
ACCENT = "#37373d"
FG     = "#cccccc"
FG2    = "#858585"
BLUE   = "#4fc1ff"
GREEN  = "#4ec9b0"
YELLOW = "#dcdcaa"
RED    = "#f44747"
ORANGE = "#ce9178"
BORDER = "#3c3c3c"


def _make_pr_prompts_icon(size=14, color='#5db0d7'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.rectangle([m, m*2, s2-m, s2-m*4], outline=color, width=m)
    d.polygon([(m*3, s2-m*4), (m*6, s2-m), (m*3, s2-m)], fill=color)
    d.line([(m*3, s2//3), (s2-m*3, s2//3)], fill=color, width=m)
    d.line([(m*3, s2//2), (s2//2, s2//2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_pr_rules_icon(size=14, color='#4ec9b0'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    pts = [(s2//2, m), (s2-m*2, s2//3), (s2-m*2, 2*s2//3), (s2//2, s2-m), (m*2, 2*s2//3), (m*2, s2//3)]
    d.polygon(pts, outline=color)
    return img.resize((size, size), Image.LANCZOS)


def _make_pr_conv_icon(size=14, color='#dcdcaa'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.line([(m*2, s2-m*2), (s2//2, m*2), (s2-m*2, s2-m*2)], fill=color, width=m)
    d.line([(s2//4, s2//2), (3*s2//4, s2//2)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_pr_standards_icon(size=14, color='#ce9178'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.rectangle([m*2, m*2, s2-m*2, s2-m*2], outline=color, width=m)
    d.line([(m*4, s2//3), (s2-m*4, s2//3)], fill=color, width=m)
    d.line([(m*4, s2//2), (s2-m*4, s2//2)], fill=color, width=m)
    d.line([(m*4, 2*s2//3), (s2*3//4, 2*s2//3)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


# ── Paths ─────────────────────────────────────────────────────────────────────
# _REPO_PROMPTS: installed package ships prompts.yaml in auger/data/
# Falls back to repo config/ for dev/editable installs
_PKG_DATA       = Path(__file__).resolve().parents[2] / "data" / "prompts.yaml"
_REPO_PROMPTS   = _PKG_DATA if _PKG_DATA.exists() else Path(__file__).resolve().parents[3] / "config" / "prompts.yaml"
_USER_PROMPTS  = Path.home() / ".auger" / "prompts.yaml"
_REPOS_DIR     = Path.home() / "repos"

# ── Release branch validation ─────────────────────────────────────────────────
RELEASE_RE = re.compile(r'^[A-Z][A-Z0-9_]+-\d+\.\d+\.\d+\.\d+-[A-Z][A-Z0-9_]+$')


# ─────────────────────────────────────────────────────────────────────────────

class PromptsWidget(tk.Frame):
    """Parameterized prompt/command launcher widget."""

    WIDGET_ICON_NAME = "prompts"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._prompts      = {}        # id -> prompt dict (ordered by file position)
        self._prompt_order = []        # list of ids preserving display order
        self._param_vars   = {}        # param_name -> StringVar
        self._param_frames = {}        # param_name -> frame holding the row
        self._param_widgets= {}        # param_name -> the Entry/Combobox widget
        self._stream_proc  = None      # running subprocess
        self._stream_queue = queue.Queue()
        self._streaming    = False
        self._header_icon  = None      # GC guard
        self._tab_icons = {}

        self._val_cache        = {}   # id -> (ok: bool, errors: list, warnings: list)
        self._validate_debounce = None

        self._load_prompts()
        self._build_ui()

    # ── Prompt loading ────────────────────────────────────────────────────────

    def _load_prompts(self):
        """Load repo defaults then overlay user prompts."""
        loaded = {}
        order  = []
        for path in [_REPO_PROMPTS, _USER_PROMPTS]:
            if not path.exists():
                continue
            try:
                data = yaml.safe_load(path.read_text()) or {}
                for p in (data.get("prompts") or []):
                    pid = p.get("id")
                    if not pid:
                        continue
                    if pid not in loaded:
                        order.append(pid)
                    loaded[pid] = p
            except Exception as e:
                print(f"[Prompts] Failed to load {path}: {e}")
        self._prompts      = loaded
        self._prompt_order = order
        self._build_val_cache()

    def _categories(self):
        seen = {}
        for pid in self._prompt_order:
            cat = self._prompts[pid].get("category", "General")
            seen.setdefault(cat, []).append(pid)
        return seen

    def _display_names(self):
        """Flat list of display strings for the top dropdown."""
        names = []
        for pid in self._prompt_order:
            p = self._prompts[pid]
            cat  = p.get("category", "General")
            name = p.get("name", pid)
            names.append(f"{cat}  ›  {name}")
        return names

    # ── Validation ────────────────────────────────────────────────────────────

    VALID_BACKENDS = {"copilot", "shell_container", "shell_host"}
    _PLACEHOLDER_RE = re.compile(r'\{(\??)([A-Za-z_][A-Za-z0-9_]*)\}')

    @classmethod
    def validate_prompt(cls, p: dict):
        """Validate a single prompt dict.

        Returns (ok: bool, errors: list[str], warnings: list[str]).
        Errors = blocking problems; warnings = non-fatal issues.
        """
        errors   = []
        warnings = []

        # Required fields
        for field in ("id", "name", "backend", "template"):
            if not p.get(field, "").strip():
                errors.append(f"Missing required field: '{field}'")

        # Backend value
        backend = p.get("backend", "")
        if backend and backend not in cls.VALID_BACKENDS:
            errors.append(f"backend '{backend}' unknown — must be one of: "
                          f"{', '.join(sorted(cls.VALID_BACKENDS))}")

        template = p.get("template", "") or ""
        params   = p.get("params") or []

        # Collect placeholder names from template
        required_in_tpl = set()
        optional_in_tpl = set()
        for is_opt, name in cls._PLACEHOLDER_RE.findall(template):
            if is_opt:
                optional_in_tpl.add(name)
            else:
                required_in_tpl.add(name)

        # Param names defined
        param_names = set()
        for pdef in params:
            pname = pdef.get("name", "").strip()
            if not pname:
                errors.append("A param entry is missing 'name'")
                continue
            param_names.add(pname)

            # source_cmd required for combobox type
            ptype = pdef.get("type", "text")
            if ptype == "combobox" and not pdef.get("source_cmd") and not pdef.get("choices"):
                warnings.append(f"Param '{pname}': combobox needs 'source_cmd' or 'choices'")

            # depends_on target must exist
            dep = pdef.get("depends_on")
            if dep and dep not in param_names:
                errors.append(f"Param '{pname}': depends_on '{dep}' not defined above it")

            # validation regex compiles (supports plain string OR {pattern:, error_msg:} dict)
            val_re = pdef.get("validation")
            if val_re:
                pattern = val_re.get("pattern") if isinstance(val_re, dict) else val_re
                try:
                    re.compile(pattern)
                except (re.error, TypeError) as e:
                    errors.append(f"Param '{pname}': validation regex invalid — {e}")

        # Every required placeholder must have a param
        for name in sorted(required_in_tpl):
            if name not in param_names:
                errors.append(f"Template uses {{{name}}} but no param with that name")

        # Every optional placeholder must have a param
        for name in sorted(optional_in_tpl):
            if name not in param_names:
                warnings.append(f"Template uses {{?{name}}} but no param with that name")

        # Orphan params (defined but never used in template)
        used_in_tpl = required_in_tpl | optional_in_tpl
        for pname in param_names:
            if pname not in used_in_tpl:
                warnings.append(f"Param '{pname}' is defined but never used in template")

        # Layer 2: render check — fill defaults and look for unfilled placeholders
        if not errors:
            values = {}
            for pdef in params:
                pname   = pdef.get("name", "")
                default = pdef.get("default", "")
                choices = pdef.get("choices", [])
                optional = pdef.get("optional", False)
                if default:
                    values[pname] = str(default)
                elif choices:
                    values[pname] = str(choices[0])
                elif optional:
                    values[pname] = ""
                else:
                    values[pname] = f"<{pname}>"

            rendered = template
            # Strip optional blocks
            for pdef in params:
                if not pdef.get("optional"):
                    continue
                pname = pdef.get("name", "")
                rendered = re.sub(r'\{' + re.escape("?" + pname) + r'\}', "", rendered)
                rendered = rendered.replace(f"{{{pname}}}", values.get(pname, ""))
            # Fill required
            for pname, val in values.items():
                rendered = rendered.replace(f"{{{pname}}}", val)

            # Any {WORD} still in rendered template?
            remaining = re.findall(r'\{[A-Za-z_][A-Za-z0-9_]*\}', rendered)
            if remaining:
                warnings.append(f"After fill, unfilled placeholder(s): {', '.join(remaining)}")

        ok = len(errors) == 0
        return ok, errors, warnings

    def _build_val_cache(self):
        """Validate all loaded prompts and cache results."""
        self._val_cache = {}
        for pid, p in self._prompts.items():
            ok, errors, warnings = self.validate_prompt(p)
            self._val_cache[pid] = (ok, errors, warnings)

    def _val_icon(self, pid):
        """Return ✅ / ⚠️ / ❌ for a prompt id."""
        if pid not in self._val_cache:
            return "  "
        ok, errors, warnings = self._val_cache[pid]
        if errors:
            return "❌"
        if warnings:
            return "⚠️"
        return "✅"

    # ── UI build ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)  # body expands

        # ── Shared header (always visible) ───────────────────────────────────
        header = tk.Frame(self, bg=ACCENT, height=44)
        header.pack(fill=tk.X)
        header.pack_propagate(False)
        try:
            self._header_icon = _icons.get("prompts", 26)
            tk.Label(header, image=self._header_icon, bg=ACCENT
                     ).pack(side=tk.LEFT, padx=(14, 4), pady=8)
        except Exception:
            pass
        tk.Label(header, text="Prompts", font=("Segoe UI", 13, "bold"),
                 bg=ACCENT, fg=FG).pack(side=tk.LEFT, pady=8)

        self._reload_btn = tk.Button(header, text="Reload", font=("Segoe UI", 9),
                                     bg=ACCENT, fg=FG2, bd=0, padx=8,
                                     activebackground=BG2, activeforeground=FG,
                                     cursor="hand2", command=self._reload_prompts)
        self._reload_btn.pack(side=tk.RIGHT, padx=4)

        self._edit_toggle_btn = tk.Button(
            header, text="Edit Prompts", font=("Segoe UI", 9),
            bg=ACCENT, fg=FG2, bd=0, padx=8,
            activebackground=BG2, activeforeground=FG,
            cursor="hand2", command=self._show_edit_view)
        self._edit_toggle_btn.pack(side=tk.RIGHT, padx=4)

        # ── Notebook: Prompts + Rules + Conventions + Standards ───────────────
        self._notebook = ttk.Notebook(self)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Prompts (existing run/edit views)
        self._body = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(self._body, text="  Prompts  ")

        # Tab 2-4: new panels
        from auger.ui.widgets.rcs_panels import RulesPanel, ConventionsPanel, StandardsPanel
        self._rules_panel = RulesPanel(self._notebook)
        self._notebook.add(self._rules_panel, text="  Rules  ")
        self._conventions_panel = ConventionsPanel(self._notebook)
        self._notebook.add(self._conventions_panel, text="  Conventions  ")
        self._standards_panel = StandardsPanel(self._notebook)
        self._notebook.add(self._standards_panel, text="  Standards  ")
        self.after(0, self._apply_pr_tab_icons)

        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_change)

        self._body.columnconfigure(0, weight=1)
        self._body.rowconfigure(0, weight=1)

        self._run_view  = tk.Frame(self._body, bg=BG)
        self._edit_view = tk.Frame(self._body, bg=BG)
        for f in (self._run_view, self._edit_view):
            f.grid(row=0, column=0, sticky="nsew")

        self._build_run_view()
        self._build_edit_view()

        # Style ttk widgets
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=BG3, background=BG3,
                        foreground=FG, selectbackground=ACCENT,
                        selectforeground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", BG3)])
        style.configure("TNotebook", background=BG2, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG3, foreground=FG2,
                        padding=[12, 6], font=("Segoe UI", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", ACCENT)],
                  foreground=[("selected", FG)])

        self._show_run_view()

    # ── Notebook tab change ───────────────────────────────────────────────────

    def _apply_pr_tab_icons(self):
        """Apply emoji labels to Prompts sub-tabs via safe nb.tab() calls.
        nb.tab() does not trigger SIGSEGV — only nb.add(text=...) with emoji is unsafe."""
        tabs_config = [
            (self._body,                '📋 Prompts'),
            (self._rules_panel,         '🛡 Rules'),
            (self._conventions_panel,   '📐 Conventions'),
            (self._standards_panel,     '📚 Standards'),
        ]
        for frame, label in tabs_config:
            try:
                self._notebook.tab(frame, text=f'  {label}  ')
            except Exception:
                pass

    def _on_tab_change(self, event=None):
        tab = self._notebook.index(self._notebook.select())
        if tab == 0:
            self._edit_toggle_btn.pack(side=tk.RIGHT, padx=4)
            self._reload_btn.pack(side=tk.RIGHT, padx=4)
        else:
            self._edit_toggle_btn.pack_forget()
            self._reload_btn.pack_forget()

    # ── View switching ────────────────────────────────────────────────────────

    def _show_run_view(self):
        self._run_view.tkraise()
        self._edit_toggle_btn.config(text="Edit Prompts",
                                     command=self._show_edit_view)

    def _show_edit_view(self):
        self._refresh_edit_list()
        self._edit_view.tkraise()
        self._edit_toggle_btn.config(text="<< Back to Run",
                                     command=self._show_run_view)

    # ── Run view ──────────────────────────────────────────────────────────────

    def _build_run_view(self):
        v = self._run_view
        v.columnconfigure(0, weight=1)
        v.rowconfigure(3, weight=1)

        # Prompt selector row
        sel_frame = tk.Frame(v, bg=BG2, pady=6)
        sel_frame.pack(fill=tk.X)

        tk.Label(sel_frame, text="Prompt:", font=("Segoe UI", 10),
                 bg=BG2, fg=FG2, width=10, anchor="e"
                 ).pack(side=tk.LEFT, padx=(12, 4))

        self._sel_var = tk.StringVar()
        self._sel_combo = ttk.Combobox(sel_frame, textvariable=self._sel_var,
                                       state="readonly", width=48,
                                       font=("Segoe UI", 10))
        self._sel_combo["values"] = self._display_names()
        if self._prompt_order:
            self._sel_combo.current(0)
        self._sel_combo.pack(side=tk.LEFT, padx=(0, 8))
        self._sel_combo.bind("<<ComboboxSelected>>", lambda _: self._on_prompt_selected())

        self._desc_label = tk.Label(sel_frame, text="", font=("Segoe UI", 9, "italic"),
                                    bg=BG2, fg=FG2, wraplength=400, justify=tk.LEFT)
        self._desc_label.pack(side=tk.LEFT, padx=(4, 12))

        # Params pane
        params_outer = tk.Frame(v, bg=BG3)
        params_outer.pack(fill=tk.X)
        self._params_frame = tk.Frame(params_outer, bg=BG3)
        self._params_frame.pack(fill=tk.X, padx=16, pady=8)

        # Preview
        prev_frame = tk.Frame(v, bg=BG2)
        prev_frame.pack(fill=tk.X)
        tk.Label(prev_frame, text="Preview:", font=("Segoe UI", 9, "bold"),
                 bg=BG2, fg=FG2).pack(anchor=tk.W, padx=12, pady=(6, 2))
        self._preview_text = tk.Text(prev_frame, height=4, font=("Consolas", 9),
                                     bg=BG, fg=YELLOW, bd=0, wrap=tk.WORD,
                                     state=tk.DISABLED, insertbackground=FG,
                                     padx=10, pady=6)
        self._preview_text.pack(fill=tk.X, padx=8, pady=(0, 6))
        make_text_copyable(self._preview_text)

        # Toolbar
        toolbar = tk.Frame(v, bg=BG2, pady=4)
        toolbar.pack(fill=tk.X)

        self._run_btn = tk.Button(toolbar, text="Run", font=("Segoe UI", 10, "bold"),
                                  bg="#0e639c", fg="white", bd=0, padx=16, pady=5,
                                  activebackground="#1177bb", activeforeground="white",
                                  cursor="hand2", command=self._run)
        self._run_btn.pack(side=tk.LEFT, padx=(12, 6), pady=2)

        self._stop_btn = tk.Button(toolbar, text="Stop", font=("Segoe UI", 10),
                                   bg="#5a1d1d", fg=RED, bd=0, padx=12, pady=5,
                                   activebackground="#6e2020", activeforeground=RED,
                                   cursor="hand2", command=self._stop, state=tk.DISABLED)
        self._stop_btn.pack(side=tk.LEFT, padx=(0, 6), pady=2)

        copy_btn = tk.Button(toolbar, text="Copy Prompt", font=("Segoe UI", 9),
                             bg=ACCENT, fg=FG, bd=0, padx=10, pady=5,
                             activebackground=BG3, activeforeground=FG,
                             cursor="hand2", command=self._copy_prompt)
        copy_btn.pack(side=tk.LEFT, padx=(0, 6), pady=2)

        clear_btn = tk.Button(toolbar, text="Clear Output", font=("Segoe UI", 9),
                              bg=ACCENT, fg=FG, bd=0, padx=10, pady=5,
                              activebackground=BG3, activeforeground=FG,
                              cursor="hand2", command=self._clear_output)
        clear_btn.pack(side=tk.LEFT, padx=(0, 6), pady=2)

        self._status_label = tk.Label(toolbar, text="", font=("Segoe UI", 9),
                                      bg=BG2, fg=FG2)
        self._status_label.pack(side=tk.RIGHT, padx=12)

        # Output pane
        out_frame = tk.Frame(v, bg=BG)
        out_frame.pack(fill=tk.BOTH, expand=True)
        tk.Label(out_frame, text="Output", font=("Segoe UI", 9, "bold"),
                 bg=BG, fg=FG2).pack(anchor=tk.W, padx=12, pady=(6, 0))
        out_inner = tk.Frame(out_frame, bg=BG)
        out_inner.pack(fill=tk.BOTH, expand=True, padx=8, pady=(2, 8))
        self._output = tk.Text(out_inner, font=("Consolas", 10),
                               bg="#0d0d0d", fg=GREEN, bd=0, wrap=tk.WORD,
                               insertbackground=GREEN, state=tk.DISABLED,
                               padx=10, pady=8)
        scrollbar = ttk.Scrollbar(out_inner, orient=tk.VERTICAL,
                                  command=self._output.yview)
        self._output.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        make_text_copyable(self._output)

        if self._prompt_order:
            self._on_prompt_selected()

    # ── Edit view ─────────────────────────────────────────────────────────────

    def _build_edit_view(self):
        """Two-pane editor: left = prompt list, right = YAML editor + dry run."""
        v = self._edit_view
        v.columnconfigure(1, weight=1)
        v.rowconfigure(0, weight=1)

        # ── Left: prompt list ─────────────────────────────────────────────────
        left = tk.Frame(v, bg=BG2, width=220)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        lbl_frame = tk.Frame(left, bg=ACCENT, height=34)
        lbl_frame.pack(fill=tk.X)
        lbl_frame.pack_propagate(False)
        tk.Label(lbl_frame, text="Prompts", font=("Segoe UI", 10, "bold"),
                 bg=ACCENT, fg=FG).pack(side=tk.LEFT, padx=10, pady=6)

        list_frame = tk.Frame(left, bg=BG2)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._edit_listbox = tk.Listbox(list_frame, bg=BG2, fg=FG,
                                        selectbackground="#094771",
                                        selectforeground="white",
                                        font=("Segoe UI", 10), bd=0,
                                        highlightthickness=0, activestyle="none")
        lb_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL,
                                  command=self._edit_listbox.yview)
        self._edit_listbox.configure(yscrollcommand=lb_scroll.set)
        lb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._edit_listbox.pack(fill=tk.BOTH, expand=True)
        add_listbox_menu(self._edit_listbox)
        self._edit_listbox.bind("<<ListboxSelect>>", self._on_edit_list_select)

        # List buttons
        list_btns = tk.Frame(left, bg=BG2)
        list_btns.pack(fill=tk.X, padx=4, pady=(0, 4))

        tk.Button(list_btns, text="+ New", font=("Segoe UI", 9),
                  bg=BG3, fg=GREEN, bd=0, padx=8, pady=3,
                  activebackground=ACCENT, cursor="hand2",
                  command=self._new_prompt).pack(side=tk.LEFT, padx=(0, 4))

        self._del_btn = tk.Button(list_btns, text="Delete", font=("Segoe UI", 9),
                                  bg=BG3, fg=RED, bd=0, padx=8, pady=3,
                                  activebackground=ACCENT, cursor="hand2",
                                  command=self._delete_prompt, state=tk.DISABLED)
        self._del_btn.pack(side=tk.LEFT)

        # ── Right: editor ─────────────────────────────────────────────────────
        right = tk.Frame(v, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.rowconfigure(1, weight=2)
        right.rowconfigure(3, weight=1)
        right.columnconfigure(0, weight=1)

        # Top bar
        top_bar = tk.Frame(right, bg=ACCENT, height=34)
        top_bar.pack(fill=tk.X)
        top_bar.pack_propagate(False)
        self._edit_title = tk.Label(top_bar, text="Select a prompt to edit",
                                    font=("Segoe UI", 10, "bold"), bg=ACCENT, fg=FG)
        self._edit_title.pack(side=tk.LEFT, padx=12, pady=6)

        # Source label
        self._edit_source_label = tk.Label(top_bar, text="",
                                           font=("Segoe UI", 8), bg=ACCENT, fg=FG2)
        self._edit_source_label.pack(side=tk.LEFT, padx=4)

        # YAML editor area
        yaml_lbl_frame = tk.Frame(right, bg=BG3)
        yaml_lbl_frame.pack(fill=tk.X, padx=0)
        tk.Label(yaml_lbl_frame, text="YAML (edit directly):",
                 font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG2
                 ).pack(side=tk.LEFT, padx=12, pady=(6, 2))
        self._yaml_err_label = tk.Label(yaml_lbl_frame, text="",
                                        font=("Segoe UI", 9), bg=BG3, fg=RED)
        self._yaml_err_label.pack(side=tk.LEFT, padx=6)

        yaml_frame = tk.Frame(right, bg=BG)
        yaml_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

        self._yaml_editor = tk.Text(yaml_frame, font=("Consolas", 10),
                                    bg="#0d0d0d", fg=YELLOW, bd=0, wrap=tk.NONE,
                                    insertbackground=FG, padx=10, pady=8,
                                    undo=True)
        yaml_xscroll = ttk.Scrollbar(yaml_frame, orient=tk.HORIZONTAL,
                                     command=self._yaml_editor.xview)
        yaml_yscroll = ttk.Scrollbar(yaml_frame, orient=tk.VERTICAL,
                                     command=self._yaml_editor.yview)
        self._yaml_editor.configure(xscrollcommand=yaml_xscroll.set,
                                    yscrollcommand=yaml_yscroll.set)
        yaml_yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        yaml_xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self._yaml_editor.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(self._yaml_editor)
        self._yaml_editor.bind("<KeyRelease>", self._on_yaml_key)

        # Editor toolbar
        ed_toolbar = tk.Frame(right, bg=BG2, pady=4)
        ed_toolbar.pack(fill=tk.X)

        tk.Button(ed_toolbar, text="Save", font=("Segoe UI", 10, "bold"),
                  bg="#0e639c", fg="white", bd=0, padx=14, pady=5,
                  activebackground="#1177bb", cursor="hand2",
                  command=self._save_prompt).pack(side=tk.LEFT, padx=(12, 6))

        tk.Button(ed_toolbar, text="Discard", font=("Segoe UI", 9),
                  bg=ACCENT, fg=FG, bd=0, padx=10, pady=5,
                  activebackground=BG3, cursor="hand2",
                  command=self._discard_edit).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(ed_toolbar, text="Dry Run", font=("Segoe UI", 9),
                  bg="#1e3a1e", fg=GREEN, bd=0, padx=10, pady=5,
                  activebackground="#2a4a2a", cursor="hand2",
                  command=self._dry_run).pack(side=tk.LEFT, padx=(0, 6))

        self._edit_status = tk.Label(ed_toolbar, text="",
                                     font=("Segoe UI", 9), bg=BG2, fg=FG2)
        self._edit_status.pack(side=tk.RIGHT, padx=12)

        # Dry run pane
        dry_lbl_frame = tk.Frame(right, bg=BG3)
        dry_lbl_frame.pack(fill=tk.X)
        tk.Label(dry_lbl_frame, text="Dry Run — filled prompt preview:",
                 font=("Segoe UI", 9, "bold"), bg=BG3, fg=FG2
                 ).pack(side=tk.LEFT, padx=12, pady=(4, 2))

        dry_frame = tk.Frame(right, bg=BG)
        dry_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self._dry_output = tk.Text(dry_frame, font=("Consolas", 10),
                                   bg="#0d0d0d", fg=GREEN, bd=0, wrap=tk.WORD,
                                   insertbackground=FG, state=tk.DISABLED,
                                   padx=10, pady=8)
        dry_scroll = ttk.Scrollbar(dry_frame, orient=tk.VERTICAL,
                                   command=self._dry_output.yview)
        self._dry_output.configure(yscrollcommand=dry_scroll.set)
        dry_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._dry_output.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(self._dry_output)

        # Internal state
        self._edit_current_id  = None   # id of prompt being edited
        self._edit_is_new      = False
        self._edit_is_dirty    = False

    # ── Edit view logic ───────────────────────────────────────────────────────

    def _refresh_edit_list(self):
        self._edit_listbox.delete(0, tk.END)
        for pid in self._prompt_order:
            p    = self._prompts[pid]
            name = p.get("name", pid)
            src  = "👤" if self._is_user_prompt(pid) else "📦"
            icon = self._val_icon(pid)
            self._edit_listbox.insert(tk.END, f" {src} {icon} {name}")
        # Re-select current
        if self._edit_current_id and self._edit_current_id in self._prompt_order:
            idx = self._prompt_order.index(self._edit_current_id)
            self._edit_listbox.selection_set(idx)
            self._edit_listbox.see(idx)

    def _is_user_prompt(self, pid):
        """Returns True if this id exists in ~/.auger/prompts.yaml."""
        if not _USER_PROMPTS.exists():
            return False
        try:
            data = yaml.safe_load(_USER_PROMPTS.read_text()) or {}
            ids = [p.get("id") for p in (data.get("prompts") or [])]
            return pid in ids
        except Exception:
            return False

    def _on_edit_list_select(self, event=None):
        sel = self._edit_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx >= len(self._prompt_order):
            return
        if self._edit_is_dirty:
            if not self._confirm_discard():
                # Restore selection
                if self._edit_current_id in self._prompt_order:
                    old = self._prompt_order.index(self._edit_current_id)
                    self._edit_listbox.selection_clear(0, tk.END)
                    self._edit_listbox.selection_set(old)
                return
        pid = self._prompt_order[idx]
        self._load_prompt_into_editor(pid)

    def _load_prompt_into_editor(self, pid):
        p = self._prompts[pid]
        self._edit_current_id = pid
        self._edit_is_new     = False
        self._edit_is_dirty   = False

        is_user = self._is_user_prompt(pid)
        src_txt = "user override  (~/.auger/prompts.yaml)" if is_user else "repo default  (config/prompts.yaml)"
        self._edit_title.config(text=p.get("name", pid))
        self._edit_source_label.config(
            text=f"[{src_txt}]",
            fg=BLUE if is_user else FG2)

        # Render single-prompt YAML block
        single = {"prompts": [p]}
        self._yaml_editor.delete("1.0", tk.END)
        self._yaml_editor.insert(tk.END, yaml.dump(single, default_flow_style=False,
                                                    allow_unicode=True, sort_keys=False))
        self._yaml_err_label.config(text="")
        self._del_btn.config(state=tk.NORMAL if is_user else tk.DISABLED)
        self._set_edit_status("")
        self._clear_dry_output()

    def _on_yaml_key(self, event=None):
        self._edit_is_dirty = True
        # Debounce live validation — fire 500 ms after last keystroke
        if self._validate_debounce:
            self.after_cancel(self._validate_debounce)
        self._validate_debounce = self.after(500, self._live_validate)

    def _live_validate(self):
        """Parse editor YAML, validate, update err label + list icon."""
        self._validate_debounce = None
        raw = self._yaml_editor.get("1.0", tk.END).strip()
        if not raw:
            self._yaml_err_label.config(text="")
            return
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            self._yaml_err_label.config(text=f"❌ YAML: {e}", fg=RED)
            # Update list icon if editing an existing prompt
            if self._edit_current_id:
                self._val_cache[self._edit_current_id] = (False, [str(e)], [])
                self._refresh_edit_list()
            return

        if not data or not data.get("prompts"):
            self._yaml_err_label.config(text="[!] No 'prompts:' list found", fg=ORANGE)
            return

        prompt = data["prompts"][0]
        ok, errors, warnings = self.validate_prompt(prompt)
        pid = prompt.get("id") or self._edit_current_id

        if errors:
            msg = f"❌ {errors[0]}"
            if len(errors) > 1:
                msg += f"  (+{len(errors)-1} more)"
            self._yaml_err_label.config(text=msg, fg=RED)
        elif warnings:
            msg = f"⚠️  {warnings[0]}"
            if len(warnings) > 1:
                msg += f"  (+{len(warnings)-1} more)"
            self._yaml_err_label.config(text=msg, fg=ORANGE)
        else:
            self._yaml_err_label.config(text="[OK] Valid", fg=GREEN)

        # Update cache + list
        if pid:
            self._val_cache[pid] = (ok, errors, warnings)
            self._refresh_edit_list()

    def _confirm_discard(self):
        from tkinter import messagebox
        return messagebox.askyesno("Unsaved Changes",
                                   "You have unsaved changes. Discard them?")

    def _new_prompt(self):
        if self._edit_is_dirty:
            if not self._confirm_discard():
                return
        template = (
            "prompts:\n"
            "  - id: my_new_prompt\n"
            "    name: \"My New Prompt\"\n"
            "    category: \"My Category\"\n"
            "    backend: copilot\n"
            "    description: \"Describe what this prompt does.\"\n"
            "    template: |\n"
            "      Write your prompt here. Use {PARAM} for parameters.\n"
            "      Optional params use {?PARAM} in the template.\n"
            "    params:\n"
            "      - name: PARAM\n"
            "        type: text\n"
            "        label: \"Parameter Label\"\n"
            "        default: \"\"\n"
        )
        self._edit_current_id = None
        self._edit_is_new     = True
        self._edit_is_dirty   = True
        self._edit_title.config(text="New Prompt")
        self._edit_source_label.config(text="[will save to ~/.auger/prompts.yaml]", fg=GREEN)
        self._yaml_editor.delete("1.0", tk.END)
        self._yaml_editor.insert(tk.END, template)
        self._yaml_err_label.config(text="")
        self._del_btn.config(state=tk.DISABLED)
        self._edit_listbox.selection_clear(0, tk.END)
        self._clear_dry_output()

    def _delete_prompt(self):
        if not self._edit_current_id:
            return
        from tkinter import messagebox
        p = self._prompts.get(self._edit_current_id, {})
        if not messagebox.askyesno("Delete Prompt",
                                   f"Delete '{p.get('name', self._edit_current_id)}' "
                                   f"from your user prompts?\n\nThis cannot be undone."):
            return
        self._save_user_file(delete_id=self._edit_current_id)
        self._reload_prompts()
        self._refresh_edit_list()
        self._yaml_editor.delete("1.0", tk.END)
        self._edit_title.config(text="Select a prompt to edit")
        self._edit_source_label.config(text="")
        self._edit_current_id = None
        self._edit_is_dirty   = False
        self._del_btn.config(state=tk.DISABLED)
        self._set_edit_status("Prompt deleted")

    def _discard_edit(self):
        if self._edit_current_id:
            self._load_prompt_into_editor(self._edit_current_id)
        else:
            self._yaml_editor.delete("1.0", tk.END)
        self._edit_is_dirty = False
        self._set_edit_status("Changes discarded")

    def _save_prompt(self):
        """Parse YAML from editor and save to ~/.auger/prompts.yaml."""
        raw = self._yaml_editor.get("1.0", tk.END).strip()
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            self._yaml_err_label.config(text=f"YAML error: {e}")
            return

        if not data or "prompts" not in data or not data["prompts"]:
            self._yaml_err_label.config(text="Must contain a 'prompts:' list")
            return

        prompt = data["prompts"][0]
        pid = prompt.get("id", "").strip()
        if not pid:
            self._yaml_err_label.config(text="Prompt must have an 'id' field")
            return

        self._save_user_file(upsert_prompt=prompt)
        self._edit_current_id = pid
        self._edit_is_new     = False
        self._edit_is_dirty   = False
        self._reload_prompts()
        self._refresh_edit_list()
        self._load_prompt_into_editor(pid)
        self._set_edit_status(f"✅ Saved '{prompt.get('name', pid)}'")

    def _save_user_file(self, upsert_prompt=None, delete_id=None):
        """Read ~/.auger/prompts.yaml, upsert or delete a prompt, write back."""
        _USER_PROMPTS.parent.mkdir(parents=True, exist_ok=True)
        if _USER_PROMPTS.exists():
            try:
                existing = yaml.safe_load(_USER_PROMPTS.read_text()) or {}
            except Exception:
                existing = {}
        else:
            existing = {}

        prompts = existing.get("prompts", []) or []

        if delete_id:
            prompts = [p for p in prompts if p.get("id") != delete_id]
        elif upsert_prompt:
            pid = upsert_prompt.get("id")
            replaced = False
            for i, p in enumerate(prompts):
                if p.get("id") == pid:
                    prompts[i] = upsert_prompt
                    replaced = True
                    break
            if not replaced:
                prompts.append(upsert_prompt)

        existing["prompts"] = prompts
        _USER_PROMPTS.write_text(
            yaml.dump(existing, default_flow_style=False,
                      allow_unicode=True, sort_keys=False))

    def _dry_run(self):
        """Validate + render template with placeholder defaults. Shows full report."""
        raw = self._yaml_editor.get("1.0", tk.END).strip()
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            self._yaml_err_label.config(text=f"❌ YAML: {e}", fg=RED)
            return

        if not data or not data.get("prompts"):
            return

        prompt = data["prompts"][0]
        params = prompt.get("params") or []

        # ── Validation report ─────────────────────────────────────────────────
        ok, errors, warnings = self.validate_prompt(prompt)

        report_lines = []
        if errors:
            report_lines.append("── Validation ──────────────────────────────")
            for e in errors:
                report_lines.append(f"  ❌ {e}")
        if warnings:
            if not errors:
                report_lines.append("── Validation ──────────────────────────────")
            for w in warnings:
                report_lines.append(f"  ⚠️  {w}")
        if not errors and not warnings:
            report_lines.append("── Validation ──────────────────────────────")
            report_lines.append(f"  ✅ Structure valid  •  {len(params)} param(s) defined")

        report_lines.append("")

        # ── Fill with defaults / sample values ────────────────────────────────
        values = {}
        fill_notes = []
        for pdef in params:
            pname    = pdef.get("name", "")
            default  = pdef.get("default", "")
            choices  = pdef.get("choices", [])
            optional = pdef.get("optional", False)
            if default:
                values[pname] = str(default)
                fill_notes.append(f"  {pname} = \"{default}\"  (default)")
            elif choices:
                values[pname] = str(choices[0])
                fill_notes.append(f"  {pname} = \"{choices[0]}\"  (first choice)")
            elif optional:
                values[pname] = ""
                fill_notes.append(f"  {pname} = \"\"  (optional — left empty)")
            else:
                values[pname] = f"<{pname}>"
                fill_notes.append(f"  {pname} = \"<{pname}>\"  (no default — placeholder)")

        if fill_notes:
            report_lines.append("── Param fill values ────────────────────────")
            report_lines.extend(fill_notes)
            report_lines.append("")

        # ── Render template ───────────────────────────────────────────────────
        template = prompt.get("template", "")

        # Strip optional blocks
        for pdef in params:
            if not pdef.get("optional"):
                continue
            pname   = pdef.get("name", "")
            val     = values.get(pname, "")
            prefix  = pdef.get("prefix", "")
            suffix  = pdef.get("suffix", "")
            replacement = f"{prefix}{val}{suffix}" if val else ""
            template = re.sub(r'\{' + re.escape("?" + pname) + r'\}',
                               replacement, template)
            template = template.replace(f"{{{pname}}}", replacement)

        # Fill required
        for pname, val in values.items():
            template = template.replace(f"{{{pname}}}", val)

        lines  = [l for l in template.splitlines() if l.strip()]
        filled = "\n".join(lines).strip()

        # Unfilled check
        remaining = re.findall(r'\{[A-Za-z_][A-Za-z0-9_]*\}', filled)
        if remaining:
            report_lines.append(f"⚠️  Unfilled after render: {', '.join(remaining)}")
            report_lines.append("")

        report_lines.append("── Rendered output ──────────────────────────")
        report_lines.append(filled if filled else "(empty)")

        # ── Write to dry run pane ─────────────────────────────────────────────
        self._dry_output.config(state=tk.NORMAL)
        self._dry_output.delete("1.0", tk.END)
        self._dry_output.insert(tk.END, "\n".join(report_lines))
        self._dry_output.config(state=tk.DISABLED)

        # Update cache + list
        pid = prompt.get("id") or self._edit_current_id
        if pid:
            self._val_cache[pid] = (ok, errors, warnings)
            self._refresh_edit_list()

        status = "✅ Valid — dry run rendered ↓" if ok else f"❌ {len(errors)} error(s) — see report ↓"
        self._set_edit_status(status)

    def _clear_dry_output(self):
        self._dry_output.config(state=tk.NORMAL)
        self._dry_output.delete("1.0", tk.END)
        self._dry_output.config(state=tk.DISABLED)

    def _set_edit_status(self, msg):
        self._edit_status.config(text=msg)
        if msg:
            self.after(4000, lambda: self._edit_status.config(text=""))

    # ── Prompt selection ──────────────────────────────────────────────────────

    def _current_prompt(self):
        idx = self._sel_combo.current()
        if idx < 0 or idx >= len(self._prompt_order):
            return None
        return self._prompts[self._prompt_order[idx]]

    def _on_prompt_selected(self):
        p = self._current_prompt()
        if not p:
            return
        self._desc_label.config(text=p.get("description", ""))
        self._rebuild_params(p)
        self._update_preview()

    def _reload_prompts(self):
        """Reload YAML files and refresh UI."""
        self._load_prompts()
        self._sel_combo["values"] = self._display_names()
        if self._prompt_order:
            self._sel_combo.current(0)
            self._on_prompt_selected()
        self._set_status("Prompts reloaded")

    # ── Param form ────────────────────────────────────────────────────────────

    def _rebuild_params(self, prompt):
        """Destroy old param widgets and build fresh ones for the given prompt."""
        for w in self._params_frame.winfo_children():
            w.destroy()
        self._param_vars    = {}
        self._param_frames  = {}
        self._param_widgets = {}

        params = prompt.get("params") or []
        if not params:
            tk.Label(self._params_frame, text="(no parameters)",
                     font=("Segoe UI", 9, "italic"), bg=BG3, fg=FG2
                     ).pack(anchor=tk.W)
            return

        for param in params:
            self._build_param_row(param)

        # Initial dynamic population
        for param in params:
            if param.get("type") == "dynamic" and not param.get("depends_on"):
                self._populate_dynamic(param)

    def _build_param_row(self, param):
        name     = param["name"]
        ptype    = param.get("type", "text")
        label    = param.get("label", name)
        optional = param.get("optional", False)
        default  = param.get("default", "")

        row = tk.Frame(self._params_frame, bg=BG3)
        row.pack(fill=tk.X, pady=3)
        self._param_frames[name] = row

        # Label
        lbl_text = f"{label}{'  (optional)' if optional else ''}"
        tk.Label(row, text=lbl_text, font=("Segoe UI", 10),
                 bg=BG3, fg=FG if not optional else FG2,
                 width=24, anchor="w"
                 ).pack(side=tk.LEFT, padx=(0, 8))

        var = tk.StringVar(value=default)
        self._param_vars[name] = var

        if ptype == "dropdown":
            choices = list(param.get("choices", []))
            if optional:
                choices = [""] + [choice for choice in choices if choice != ""]
            w = ttk.Combobox(row, textvariable=var, values=choices,
                             state="readonly", width=36, font=("Segoe UI", 10))
            if default in choices:
                w.set(default)
            elif optional:
                w.set("")
                var.set("")
            elif choices:
                w.current(0)
                var.set(choices[0])
            w.pack(side=tk.LEFT)
            w.bind("<<ComboboxSelected>>", lambda _: self._update_preview())

        elif ptype == "dynamic":
            w = ttk.Combobox(row, textvariable=var, values=[],
                             state="normal", width=36, font=("Segoe UI", 10))
            w.pack(side=tk.LEFT)
            # Refresh button
            refresh_btn = tk.Button(row, text="Reload", font=("Segoe UI", 9),
                                    bg=BG3, fg=FG2, bd=0, padx=4,
                                    activebackground=ACCENT, cursor="hand2",
                                    command=lambda p=param: self._populate_dynamic(p))
            refresh_btn.pack(side=tk.LEFT, padx=4)
            w.bind("<<ComboboxSelected>>", lambda _, p=param: self._on_dynamic_selected(p))
            w.bind("<KeyRelease>", lambda _: self._update_preview())

        elif ptype == "validated_text":
            entry_frame = tk.Frame(row, bg=BG3)
            entry_frame.pack(side=tk.LEFT)

            ui_prefix = param.get("ui_prefix", "")
            if ui_prefix:
                tk.Label(entry_frame, text=ui_prefix, font=("Segoe UI", 10),
                         bg=BG3, fg=FG2).pack(side=tk.LEFT, padx=(0, 4))

            w = tk.Entry(entry_frame, textvariable=var, width=36,
                         font=("Segoe UI", 10), bg=BG, fg=FG, bd=1,
                         insertbackground=FG, relief=tk.FLAT,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=BLUE)
            placeholder = param.get("placeholder", "")
            if placeholder:
                w.insert(0, placeholder)
                w.config(fg=FG2)
                w.bind("<FocusIn>",  lambda e, ph=placeholder, ent=w: self._clear_placeholder(e, ph, ent))
                w.bind("<FocusOut>", lambda e, ph=placeholder, ent=w, v=var: self._restore_placeholder(e, ph, ent, v))
            w.pack(side=tk.LEFT)

            self._valid_label = tk.Label(entry_frame, text="", font=("Segoe UI", 10),
                                         bg=BG3, width=3)
            self._valid_label.pack(side=tk.LEFT, padx=4)

            err_label = tk.Label(row, text="", font=("Segoe UI", 8),
                                 bg=BG3, fg=RED)
            err_label.pack(side=tk.LEFT, padx=4)

            pattern    = param.get("validation", {}).get("pattern", "")
            error_msg  = param.get("validation", {}).get("error_msg", "Invalid format")
            suggest_cmd = param.get("suggest_cmd", "")
            suggest_dep = param.get("suggest_depends_on", "")

            def on_key(event, v=var, w=w, pat=pattern, em=error_msg,
                       el=err_label, sc=suggest_cmd, sd=suggest_dep, p=param):
                val = v.get().strip()
                if not val or val == param.get("placeholder", ""):
                    w.config(highlightbackground=BORDER)
                    self._valid_label.config(text="")
                    el.config(text="")
                elif pat and re.match(pat, val):
                    w.config(highlightbackground=GREEN)
                    self._valid_label.config(text="[OK]", fg=GREEN)
                    el.config(text="")
                    # Populate suggestions based on value
                    if sc:
                        self._run_suggest(w, sc, sd, val)
                else:
                    w.config(highlightbackground=RED)
                    self._valid_label.config(text="[X]", fg=RED)
                    el.config(text=em)
                self._update_preview()

            w.bind("<KeyRelease>", on_key)

            # Load suggestions immediately
            if suggest_cmd:
                self._run_suggest(w, suggest_cmd, suggest_dep, "")

        else:  # plain text
            entry_parent = row
            ui_prefix = param.get("ui_prefix", "")
            if ui_prefix:
                entry_parent = tk.Frame(row, bg=BG3)
                entry_parent.pack(side=tk.LEFT)
                tk.Label(entry_parent, text=ui_prefix, font=("Segoe UI", 10),
                         bg=BG3, fg=FG2).pack(side=tk.LEFT, padx=(0, 4))

            w = tk.Entry(entry_parent, textvariable=var, width=36,
                         font=("Segoe UI", 10), bg=BG, fg=FG, bd=1,
                         insertbackground=FG, relief=tk.FLAT,
                         highlightthickness=1, highlightbackground=BORDER,
                         highlightcolor=BLUE)
            placeholder = param.get("placeholder", "")
            if placeholder and not default:
                w.insert(0, placeholder)
                w.config(fg=FG2)
                w.bind("<FocusIn>",  lambda e, ph=placeholder, ent=w: self._clear_placeholder(e, ph, ent))
                w.bind("<FocusOut>", lambda e, ph=placeholder, ent=w, v=var: self._restore_placeholder(e, ph, ent, v))
            w.pack(side=tk.LEFT)
            w.bind("<KeyRelease>", lambda _: self._update_preview())

        self._param_widgets[name] = w

    def _clear_placeholder(self, event, placeholder, entry):
        if entry.get() == placeholder:
            entry.delete(0, tk.END)
            entry.config(fg=FG)

    def _restore_placeholder(self, event, placeholder, entry, var):
        if not entry.get().strip():
            entry.insert(0, placeholder)
            entry.config(fg=FG2)
            var.set("")

    # ── Dynamic param population ──────────────────────────────────────────────

    def _on_dynamic_selected(self, param):
        """When a dynamic param changes, re-populate dependents."""
        p = self._current_prompt()
        if not p:
            return
        name = param["name"]
        for dep_param in (p.get("params") or []):
            if dep_param.get("depends_on") == name:
                self._populate_dynamic(dep_param)
        self._update_preview()

    def _populate_dynamic(self, param):
        """Run source_cmd, fill Combobox with results."""
        name = param["name"]
        cmd  = param.get("source_cmd", "")
        if not cmd:
            return
        # Substitute any {DEP} references in the command
        for dep_name, dep_var in self._param_vars.items():
            cmd = cmd.replace(f"{{{dep_name}}}", dep_var.get())
        # Expand ~ to home
        cmd = cmd.replace("~", str(Path.home()))

        def run():
            try:
                result = subprocess.run(["bash", "-c", cmd], capture_output=True,
                                        text=True, timeout=10)
                items = [l.strip() for l in result.stdout.splitlines() if l.strip()]
                self.after(0, lambda: self._set_dynamic_values(name, param, items))
            except Exception as e:
                print(f"[Prompts] dynamic source_cmd failed for {name}: {e}")

        threading.Thread(target=run, daemon=True).start()

    @staticmethod
    def _sort_branches(items):
        """release/ branches first (descending), then everything else (descending)."""
        release = sorted([b for b in items if b.startswith("release/")], reverse=True)
        other   = sorted([b for b in items if not b.startswith("release/")], reverse=True)
        return release + other

    def _set_dynamic_values(self, name, param, items):
        w = self._param_widgets.get(name)
        if not isinstance(w, ttk.Combobox):
            return
        current = self._param_vars[name].get()
        optional = param.get("optional", False)
        if param.get("type") in ("combobox", "dynamic"):
            items = self._sort_branches(items)
        if optional:
            items = [""] + [item for item in items if item != ""]
        w["values"] = items
        selected = None
        if current in items:
            selected = current
        elif param.get("default", "") in items:
            selected = param.get("default", "")
        elif optional:
            selected = ""
        elif items:
            selected = items[0]

        if selected is not None:
            w.set(selected)
            self._param_vars[name].set(selected)
            p = self._current_prompt()
            if p:
                for dep_param in (p.get("params") or []):
                    if dep_param.get("depends_on") == name:
                        self._populate_dynamic(dep_param)
        self._update_preview()

    def _run_suggest(self, widget, suggest_cmd, suggest_dep, current_val):
        """Populate autocomplete suggestions for a validated_text field."""
        cmd = suggest_cmd
        if suggest_dep and suggest_dep in self._param_vars:
            dep_val = self._param_vars[suggest_dep].get()
            cmd = cmd.replace(f"{{{suggest_dep}}}", dep_val)
        cmd = cmd.replace("~", str(Path.home()))

        def run():
            try:
                result = subprocess.run(["bash", "-c", cmd], capture_output=True,
                                        text=True, timeout=10)
                items = [l.strip() for l in result.stdout.splitlines() if l.strip()]
                self.after(0, lambda: self._set_suggestions(widget, items))
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()

    def _set_suggestions(self, widget, items):
        if isinstance(widget, ttk.Combobox):
            widget["values"] = items
        # For Entry widget, attach a suggestion list (just store for now)

    # ── Template rendering ────────────────────────────────────────────────────

    def _fill_template(self):
        p = self._current_prompt()
        if not p:
            return ""
        template = p.get("template", "")

        # Build values dict
        values = {}
        for pdef in (p.get("params") or []):
            name = pdef["name"]
            var  = self._param_vars.get(name)
            val  = var.get().strip() if var else ""
            # Strip placeholder text
            placeholder = pdef.get("placeholder", "")
            if val == placeholder:
                val = ""
            values[name] = val

        # Handle optional params: {?PARAM} replaced with prefix+val+suffix or ""
        for pdef in (p.get("params") or []):
            if not pdef.get("optional"):
                continue
            name   = pdef["name"]
            val    = values.get(name, "")
            prefix = pdef.get("prefix", "")
            suffix = pdef.get("suffix", "")
            if val:
                replacement = f"{prefix}{val}{suffix}"
            else:
                replacement = ""
            template = re.sub(r'\{' + re.escape("?" + name) + r'\}',
                               replacement, template)
            # Also handle plain {NAME} for optional params
            template = template.replace(f"{{{name}}}", replacement)

        # Replace required {PARAM}
        for name, val in values.items():
            template = template.replace(f"{{{name}}}", val)

        # Clean up blank lines left by removed optional params
        lines = [l for l in template.splitlines() if l.strip()]
        return "\n".join(lines).strip()

    def _update_preview(self):
        filled = self._fill_template()
        self._preview_text.config(state=tk.NORMAL)
        self._preview_text.delete("1.0", tk.END)
        self._preview_text.insert(tk.END, filled)
        self._preview_text.config(state=tk.DISABLED)

    # ── Run / stream ──────────────────────────────────────────────────────────

    def _run(self):
        if self._streaming:
            return
        prompt = self._fill_template()
        if not prompt:
            self._set_status("Nothing to run — fill in the parameters first")
            return

        p = self._current_prompt()
        backend = p.get("backend", "copilot") if p else "copilot"

        self._clear_output()
        self._append_output(f"$ {backend}: {prompt[:120]}{'...' if len(prompt) > 120 else ''}\n\n")
        self._set_running(True)

        if backend == "shell_host":
            self._run_shell_host(prompt)
        elif backend == "shell_container":
            self._run_shell(prompt)
        else:
            self._run_copilot(prompt)

    def _run_copilot(self, prompt):
        """Stream output from: auger "<prompt>"."""
        def spawn():
            try:
                proc = subprocess.Popen(
                    ["auger", prompt],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1,
                    env=self._clean_env()
                )
                self._stream_proc = proc
                for line in proc.stdout:
                    self._stream_queue.put(line)
                proc.wait()
            except FileNotFoundError:
                self._stream_queue.put("❌  'auger' not found on PATH.\n")
            except Exception as e:
                self._stream_queue.put(f"❌  Error: {e}\n")
            finally:
                self._stream_queue.put(None)

        threading.Thread(target=spawn, daemon=True).start()
        self.after(50, self._poll_stream)

    def _run_shell(self, cmd):
        """Run a shell command inside the container and stream output."""
        def spawn():
            try:
                proc = subprocess.Popen(
                    ["bash", "-c", cmd],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1
                )
                self._stream_proc = proc
                for line in proc.stdout:
                    self._stream_queue.put(line)
                proc.wait()
            except Exception as e:
                self._stream_queue.put(f"❌  Error: {e}\n")
            finally:
                self._stream_queue.put(None)

        threading.Thread(target=spawn, daemon=True).start()
        self.after(50, self._poll_stream)

    def _run_shell_host(self, cmd):
        """Run command on host via daemon, stream output via shared file."""
        import time
        import json
        import http.client

        out_file = str(Path.home() / ".auger" / "prompt_stream.log")
        full_cmd = f"{cmd} > {out_file} 2>&1"
        host_file = f"/host/home/{Path.home().name}/.auger/prompt_stream.log"

        def spawn():
            try:
                # Clear file
                Path(host_file).write_text("") if Path(host_file).exists() else None
                # Register + launch tool via daemon
                payload_reg = json.dumps({
                    "action": "register_tool",
                    "key": "_prompt_run",
                    "name": "Prompt Run",
                    "binary": "/bin/bash",
                    "exec_cmd": f"bash -c '{full_cmd}'"
                }).encode()
                payload_launch = json.dumps({
                    "action": "launch_tool",
                    "tool": "_prompt_run"
                }).encode()

                conn = http.client.HTTPConnection("localhost", 7437, timeout=5)
                conn.request("POST", "/cmd",
                             body=payload_reg,
                             headers={"Content-Type": "application/json"})
                conn.getresponse().read()
                conn.request("POST", "/cmd",
                             body=payload_launch,
                             headers={"Content-Type": "application/json"})
                conn.getresponse().read()
                conn.close()

                # Tail the file
                pos = 0
                deadline = time.time() + 60
                while time.time() < deadline:
                    try:
                        content = Path(host_file).read_text()
                        if len(content) > pos:
                            chunk = content[pos:]
                            pos = len(content)
                            for line in chunk.splitlines(keepends=True):
                                self._stream_queue.put(line)
                    except Exception:
                        pass
                    time.sleep(0.15)
                    # Check if process finished (file unchanged for 1s)
                    if time.time() - deadline > -5:
                        break
            except Exception as e:
                self._stream_queue.put(f"❌  Daemon error: {e}\n")
            finally:
                self._stream_queue.put(None)

        threading.Thread(target=spawn, daemon=True).start()
        self.after(100, self._poll_stream)

    def _poll_stream(self):
        """Drain the stream queue into the output Text widget."""
        try:
            while True:
                line = self._stream_queue.get_nowait()
                if line is None:
                    self._set_running(False)
                    self._append_output("\n\n[Done]\n")
                    return
                self._append_output(line)
        except queue.Empty:
            pass
        self.after(50, self._poll_stream)

    def _stop(self):
        if self._stream_proc:
            try:
                self._stream_proc.terminate()
            except Exception:
                pass
        self._set_running(False)
        self._append_output("\n[Stopped]\n")

    def _set_running(self, running):
        self._streaming = running
        self._run_btn.config(state=tk.DISABLED if running else tk.NORMAL)
        self._stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)
        self._set_status("● Running…" if running else "")

    def _clean_env(self):
        """Return os.environ without VSCODE_IPC_HOOK_CLI (prevents VS Code IPC routing)."""
        import os
        env = dict(os.environ)
        env.pop("VSCODE_IPC_HOOK_CLI", None)
        return env

    # ── Output helpers ────────────────────────────────────────────────────────

    def _append_output(self, text):
        self._output.config(state=tk.NORMAL)
        self._output.insert(tk.END, text)
        self._output.see(tk.END)
        self._output.config(state=tk.DISABLED)

    def _clear_output(self):
        self._output.config(state=tk.NORMAL)
        self._output.delete("1.0", tk.END)
        self._output.config(state=tk.DISABLED)

    def _copy_prompt(self):
        filled = self._fill_template()
        self.clipboard_clear()
        self.clipboard_append(filled)
        self._set_status("Prompt copied to clipboard")

    def _set_status(self, msg):
        self._status_label.config(text=msg)
        if msg:
            self.after(4000, lambda: self._status_label.config(text=""))
