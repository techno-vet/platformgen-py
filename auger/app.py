#!/usr/bin/env python3
"""
PlatformGen - Main Application

A self-building AI-powered desktop tool for Site Reliability Engineers.
"""

import os
import socket
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox

from platformgen.runtime import daemon_port, product_name, state_dir, window_class
from platformgen.ui.content_area import ContentArea
from platformgen.ui.ask_genny import AskGennyPanel
from platformgen.ui.hot_reload import HotReloader
from platformgen.ui.first_run import maybe_show_wizard
from platformgen.ui.status_bar import PlatformGenStatusBar
from platformgen.ui.help_docs import DOCS_DIR as _DOCS_DIR, WIDGET_DOCS as _WIDGET_DOCS_RAW, GENERAL_DOCS as _GENERAL_DOCS

# Adapt widget docs list to legacy 3-tuple format used by menu building code
_WIDGET_DOCS = [(label, fname, None) for label, fname in _WIDGET_DOCS_RAW]


# Style constants
BG = "#1e1e1e"
BG2 = "#252526"
FG = "#e0e0e0"
ACCENT = "#007acc"
GREEN = "#4ec9b0"
RED = "#f44747"
YELLOW = "#f0c040"

def _runtime_mode() -> str:
    mode = (os.environ.get("AUGER_MODE") or "").strip().lower()
    return "venv" if mode == "venv" else "docker"


def _activation_socket_path() -> Path:
    suffix = "host" if _runtime_mode() == "venv" else "sre"
    return state_dir() / f"platform-activate-{suffix}.sock"


def _signal_existing_instance() -> bool:
    """Ask an already-running PlatformGen window to raise itself, if present."""
    socket_path = _activation_socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(0.5)
            client.connect(os.fspath(socket_path))
            client.sendall(b"activate\n")
        return True
    except OSError:
        return False


class PlatformGenApp(tk.Tk):
    """Main application window."""
    
    def __init__(self):
        super().__init__(className=window_class())

        self._runtime_mode = _runtime_mode()
        self.title(product_name())
        self.geometry("1400x920")
        self.minsize(900, 650)
        self.configure(bg=BG)

        # Set window icon (titlebar + taskbar/dock).
        # Save PNG to tmp then load with tk.PhotoImage — most reliable on X11.
        try:
            from platformgen.ui.icons import load_app_icon
            import tempfile, os
            _icon_img = load_app_icon(256).convert("RGBA")
            _icon_tmp = os.path.join(os.fspath(state_dir()), "app_icon.png")
            _icon_img.save(_icon_tmp)
            _icon_photo = tk.PhotoImage(file=_icon_tmp)
            self.iconphoto(True, _icon_photo)
            self._icon_photo_ref = _icon_photo  # prevent GC
        except Exception as _e:
            print(f"[!] iconphoto failed: {_e}")
        
        # Configure dark theme
        self._setup_theme()
        
        # Build UI
        self._build_menu()
        self._build_layout()
        
        # Start hot reloader
        widget_dir = Path(__file__).parent / 'ui' / 'widgets'
        self.reloader = HotReloader(watch_dir=str(widget_dir), interval=1.0, root=self)
        self.reloader.register_callback(self.content.hot_reload_update)
        # After first scan completes, restore the previously active tab
        self.reloader.register_first_scan_callback(
            lambda: self.after(100, self.content.restore_active_tab))
        self.reloader.start()

        # Wire View menu refresh into content area
        self.content._view_menu_refresh = self._rebuild_view_tabs

        # Conditionally open Host Tools tab if daemon has registered tools
        self.after(2000, self._maybe_open_host_tools)

        # Handle window close
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._activation_socket_path = _activation_socket_path()
        self._activation_server = None
        self._activation_stop = threading.Event()
        self._start_activation_listener()
        self.after(250, self._activate_window)

        # Override Tk's callback exception handler to surface widget crashes
        self._in_exception_handler = False
        self._callback_error_cooldowns: dict = {}  # signature → last_shown_time; suppress dupes for 5min
        self.report_callback_exception = self._handle_callback_exception

    
    def _setup_theme(self):
        """Configure ttk dark theme."""
        style = ttk.Style()
        style.theme_use('clam')

        combo_bg = BG2
        combo_bg_active = "#3a3f46"
        combo_fg = FG
        combo_dim = "#858585"
        combo_accent = "#4ec9b0"

        style.configure(
            'TCombobox',
            foreground=combo_fg,
            fieldbackground=combo_bg,
            background=combo_bg,
            bordercolor=combo_bg_active,
            darkcolor=combo_bg,
            lightcolor=combo_bg,
            arrowcolor=combo_accent,
            insertcolor=combo_fg,
            relief='flat',
            borderwidth=1,
            padding=(6, 2, 6, 2),
        )
        style.map(
            'TCombobox',
            fieldbackground=[
                ('readonly', combo_bg),
                ('disabled', BG),
                ('focus', combo_bg_active),
            ],
            background=[
                ('readonly', combo_bg),
                ('disabled', BG),
                ('focus', combo_bg_active),
            ],
            foreground=[
                ('readonly', combo_fg),
                ('disabled', combo_dim),
            ],
            bordercolor=[
                ('readonly', combo_bg_active),
                ('disabled', BG),
                ('focus', combo_accent),
            ],
            lightcolor=[
                ('readonly', combo_bg),
                ('disabled', BG),
                ('focus', combo_bg_active),
            ],
            darkcolor=[
                ('readonly', combo_bg),
                ('disabled', BG),
                ('focus', combo_bg_active),
            ],
            arrowcolor=[
                ('readonly', combo_accent),
                ('disabled', combo_dim),
                ('focus', combo_accent),
            ],
            selectbackground=[('readonly', combo_accent)],
            selectforeground=[('readonly', BG)],
        )
        for pattern, value in {
            '*TCombobox*Listbox.background': combo_bg,
            '*TCombobox*Listbox.foreground': combo_fg,
            '*TCombobox*Listbox.selectBackground': combo_accent,
            '*TCombobox*Listbox.selectForeground': BG,
        }.items():
            try:
                self.option_add(pattern, value)
            except Exception:
                pass
        
        # Configure notebook (tabs)
        style.configure('TNotebook', background=BG, borderwidth=0)
        style.configure('TNotebook.Tab',
                       background=BG2,
                       foreground=FG,
                       padding=[15, 8],
                       borderwidth=0)
        style.map('TNotebook.Tab',
                 background=[('selected', ACCENT)],
                 foreground=[('selected', 'white')])
        
        # Configure paned window
        style.configure('TPanedwindow', background=BG)
        
        # Configure scrollbar
        style.configure('Vertical.TScrollbar',
                       background=BG2,
                       troughcolor=BG,
                       borderwidth=0,
                       arrowcolor=FG)

    def _use_custom_menu_bar(self):
        """Use an in-window menu bar on Linux/X11 to avoid wrong-monitor menu bugs."""
        return sys.platform.startswith('linux')

    def _clear_top_menu_tracking(self, _event=None):
        button = getattr(self, "_active_top_menu_button", None)
        if button is not None and button.winfo_exists():
            button.configure(bg=BG2, fg=FG)
        self._active_top_menu = None
        self._active_top_menu_button = None

    def _dismiss_top_menu(self, _event=None):
        menu = getattr(self, "_active_top_menu", None)
        if menu is not None and menu.winfo_exists():
            try:
                menu.unpost()
            except tk.TclError:
                pass
        self._clear_top_menu_tracking()

    def _handle_global_menu_click(self, event):
        menu = getattr(self, "_active_top_menu", None)
        button = getattr(self, "_active_top_menu_button", None)
        if menu is None or button is None:
            return
        widget = event.widget
        if widget is button:
            return
        widget_name = str(widget)
        menu_name = str(menu)
        if widget_name == menu_name or widget_name.startswith(menu_name + "."):
            return
        self._dismiss_top_menu()

    def _popup_top_menu(self, menu, button):
        active_menu = getattr(self, "_active_top_menu", None)
        active_button = getattr(self, "_active_top_menu_button", None)
        if active_menu is menu and active_button is button:
            self._dismiss_top_menu()
            return
        self._dismiss_top_menu()
        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height()
        button.configure(bg=ACCENT, fg='white')
        self._active_top_menu = menu
        self._active_top_menu_button = button
        menu.post(x, y)

    def _add_menu_button(self, parent, label, menu):
        menu.bind("<Unmap>", self._clear_top_menu_tracking, add="+")
        btn = tk.Button(
            parent,
            text=label,
            bg=BG2,
            fg=FG,
            activebackground=ACCENT,
            activeforeground='white',
            relief=tk.FLAT,
            bd=0,
            padx=12,
            pady=6,
            font=('Segoe UI', 9),
            cursor='hand2',
            highlightthickness=0,
            command=lambda m=menu: self._popup_top_menu(m, btn),
        )
        btn.pack(side=tk.LEFT, padx=(2, 0), pady=0)
        return btn
    
    def _build_menu(self):
        """Build menu bar."""
        use_custom = self._use_custom_menu_bar()
        menubar = None
        if use_custom:
            self._menu_bar = tk.Frame(self, bg=BG2, height=30)
            self._menu_bar.pack(fill=tk.X, side=tk.TOP)
            self._menu_bar.pack_propagate(False)
            self._menu_bar_sep = tk.Frame(self, bg='#3c3c3c', height=1)
            self._menu_bar_sep.pack(fill=tk.X, side=tk.TOP)
            self.bind_all("<Button-1>", self._handle_global_menu_click, add="+")
            self.bind_all("<Escape>", self._dismiss_top_menu, add="+")
        else:
            menubar = tk.Menu(self, bg=BG2, fg=FG, activebackground=ACCENT, activeforeground='white')
            self.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT, activeforeground='white')
        if use_custom:
            self._add_menu_button(self._menu_bar, "File", file_menu)
        else:
            menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="New Session", accelerator="Ctrl+N", command=self._new_session)
        file_menu.add_command(label="Clear Chat", accelerator="Ctrl+L", command=self._clear_chat)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Ctrl+Q", command=self._on_close)
        
        # View menu
        self.view_menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT, activeforeground='white')
        if use_custom:
            self._add_menu_button(self._menu_bar, "View", self.view_menu)
        else:
            menubar.add_cascade(label="View", menu=self.view_menu)
        self.view_menu.add_command(label="Close Tab", accelerator="Ctrl+W",
                                   command=self._close_active_tab)
        self.view_menu.add_command(label="Next Tab", accelerator="Ctrl+Tab",
                                   command=lambda: self._cycle_tab(+1))
        self.view_menu.add_command(label="Prev Tab", accelerator="Ctrl+Shift+Tab",
                                   command=lambda: self._cycle_tab(-1))
        self.view_menu.add_separator()
        # Open-tabs section populated dynamically by _rebuild_view_tabs
        
        # Widgets menu (store reference for hot reload to add items dynamically)
        self.widgets_menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG, activebackground=ACCENT, activeforeground='white')
        if use_custom:
            self._add_menu_button(self._menu_bar, "Widgets", self.widgets_menu)
        else:
            menubar.add_cascade(label="Widgets", menu=self.widgets_menu)
        self.widgets_menu.add_command(label="Manage Widgets…", command=self._show_widget_help)
        self.widgets_menu.add_separator()
        
        # CRITICAL: Use sys.modules lookup for hot reload support
        self.widgets_menu.add_command(
            label="API Keys+",
            command=lambda: self.content.add_widget_tab(
                "API Keys+",
                sys.modules.get(
                    "auger.ui.widgets.api_config",
                    __import__("auger.ui.widgets.api_config", fromlist=["APIConfigWidget"])
                ).APIConfigWidget
            )
        )

        self.widgets_menu.add_command(
            label="Ask AImee",
            command=lambda: self.content.add_widget_tab(
                "Ask AImee",
                sys.modules.get(
                    "auger.ui.widgets.ask_genny_local",
                    __import__("auger.ui.widgets.ask_genny_local", fromlist=["AskGennyLocalWidget"])
                ).AskGennyLocalWidget
            )
        )

        self.widgets_menu.add_command(
            label="ComfyUI",
            command=lambda: self.content.add_widget_tab(
                "ComfyUI",
                sys.modules.get(
                    "auger.ui.widgets.comfy_ui",
                    __import__("auger.ui.widgets.comfy_ui", fromlist=["ComfyUIWidget"])
                ).ComfyUIWidget
            )
        )
        
        self.widgets_menu.add_command(
            label="Bash $",
            command=lambda: self.content.add_widget_tab(
                "Bash $",
                sys.modules.get(
                    "auger.ui.widgets.shell_terminal",
                    __import__("auger.ui.widgets.shell_terminal", fromlist=["ShellTerminalWidget"])
                ).ShellTerminalWidget
            )
        )
        
        self.widgets_menu.add_separator()
        
        self.widgets_menu.add_command(
            label="Artifactory",
            command=lambda: self.content.add_widget_tab(
                "Artifactory",
                sys.modules.get(
                    "auger.ui.widgets.artifactory",
                    __import__("auger.ui.widgets.artifactory", fromlist=["ArtifactoryWidget"])
                ).ArtifactoryWidget
            )
        )

        self.widgets_menu.add_command(
            label="Host Tools",
            command=lambda: self.content.add_widget_tab(
                "Host Tools",
                sys.modules.get(
                    "auger.ui.widgets.host_tools",
                    __import__("auger.ui.widgets.host_tools", fromlist=["HostToolsWidget"])
                ).HostToolsWidget
            )
        )

        self.widgets_menu.add_command(
            label="Explorer",
            command=lambda: self.content.add_widget_tab(
                "Explorer",
                sys.modules.get(
                    "auger.ui.widgets.explorer",
                    __import__("auger.ui.widgets.explorer", fromlist=["ExplorerWidget"])
                ).ExplorerWidget
            )
        )

        self.widgets_menu.add_command(
            label="Prompts",
            command=lambda: self.content.add_widget_tab(
                "Prompts",
                sys.modules.get(
                    "auger.ui.widgets.prompts",
                    __import__("auger.ui.widgets.prompts", fromlist=["PromptsWidget"])
                ).PromptsWidget
            )
        )

        self.widgets_menu.add_command(
            label="Flux Config",
            command=lambda: self.content.add_widget_tab(
                "Flux Config",
                sys.modules.get(
                    "auger.ui.widgets.flux_config",
                    __import__("auger.ui.widgets.flux_config", fromlist=["FluxConfigWidget"])
                ).FluxConfigWidget
            )
        )

        self.widgets_menu.add_command(
            label="Jira",
            command=lambda: self.content.add_widget_tab(
                "Jira",
                sys.modules.get(
                    "auger.ui.widgets.jira",
                    __import__("auger.ui.widgets.jira", fromlist=["JiraWidget"])
                ).JiraWidget
            )
        )

        self.widgets_menu.add_command(
            label="Tasks",
            command=lambda: self.content.add_widget_tab(
                "Tasks",
                sys.modules.get(
                    "auger.ui.widgets.tasks",
                    __import__("auger.ui.widgets.tasks", fromlist=["TasksWidget"])
                ).TasksWidget
            )
        )
        self.widgets_menu.add_command(
            label="Google Chat",
            command=lambda: self.content.add_widget_tab(
                "Google Chat",
                sys.modules.get(
                    "auger.ui.widgets.gchat",
                    __import__("auger.ui.widgets.gchat", fromlist=["GChatWidget"])
                ).GChatWidget
            )
        )


        self.widgets_menu.add_command(
            label="Help",
            command=lambda: self.content.add_widget_tab(
                "Help",
                sys.modules.get(
                    "auger.ui.widgets.help_viewer",
                    __import__("auger.ui.widgets.help_viewer", fromlist=["HelpViewerWidget"])
                ).HelpViewerWidget
            )
        )

        self.widgets_menu.add_separator()

        self.widgets_menu.add_command(
            label="Story → Prod",
            command=lambda: self.content.add_widget_tab(
                "Story → Prod",
                sys.modules.get(
                    "auger.ui.widgets.story_to_prod",
                    __import__("auger.ui.widgets.story_to_prod", fromlist=["StoryToProdWidget"])
                ).StoryToProdWidget
            )
        )

        self.widgets_menu.add_command(
            label="K8s Explorer",
            command=lambda: self.content.add_widget_tab(
                "K8s Explorer",
                sys.modules.get(
                    "auger.ui.widgets.k8s_explorer",
                    __import__("auger.ui.widgets.k8s_explorer", fromlist=["K8sExplorerWidget"])
                ).K8sExplorerWidget
            )
        )

        self.widgets_menu.add_command(
            label="GoDaddy DNS",
            command=lambda: self.content.add_widget_tab(
                "GoDaddy DNS",
                sys.modules.get(
                    "auger.ui.widgets.godaddy_dns",
                    __import__("auger.ui.widgets.godaddy_dns", fromlist=["GoDaddyDNSWidget"])
                ).GoDaddyDNSWidget
            )
        )

        self.widgets_menu.add_command(
            label="Panner",
            command=lambda: self.content.add_widget_tab(
                "Panner",
                sys.modules.get(
                    "auger.ui.widgets.panner",
                    __import__("auger.ui.widgets.panner", fromlist=["PannerWidget"])
                ).PannerWidget
            )
        )

        self.widgets_menu.add_command(
            label="Pods",
            command=lambda: self.content.add_widget_tab(
                "Pods",
                sys.modules.get(
                    "auger.ui.widgets.pods",
                    __import__("auger.ui.widgets.pods", fromlist=["PodsWidget"])
                ).PodsWidget
            )
        )

        # Per-widget Help submenu inside Widgets menu
        widget_help_sub = tk.Menu(self.widgets_menu, tearoff=0, bg=BG2, fg=FG,
                                  activebackground=ACCENT, activeforeground='white')
        for label, fname, _ in _WIDGET_DOCS:
            doc_path = str(_DOCS_DIR / fname)
            widget_help_sub.add_command(
                label=label,
                command=lambda p=doc_path, t=label: self.content.open_help_doc(p, t)
            )
        self.widgets_menu.add_cascade(label="Widget Help Docs", menu=widget_help_sub)

        self.widgets_menu.add_separator()
        
        self.widgets_menu.add_command(
            label="Service Health Monitor",
            command=lambda: self.ask_auger.set_prompt("create a service health monitor widget")
        )
        
        self.widgets_menu.add_command(
            label="Alert Manager",
            command=lambda: self.ask_auger.set_prompt("create an alert manager widget")
        )
        
        self.widgets_menu.add_command(
            label="Runbook Widget",
            command=lambda: self.ask_auger.set_prompt("create a runbook widget")
        )
        
        # Help menu
        help_menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG,
                            activebackground=ACCENT, activeforeground='white')
        if use_custom:
            self._add_menu_button(self._menu_bar, "Help", help_menu)
        else:
            menubar.add_cascade(label="Help", menu=help_menu)

        help_menu.add_command(
            label="What can Genny do?",
            command=lambda: self.ask_auger.set_prompt("what widgets can you create for me?")
        )
        help_menu.add_separator()

        # Per-widget docs
        help_menu.add_command(label="── Widget Help ──", state='disabled')
        for label, fname, _ in _WIDGET_DOCS:
            doc_path = str(_DOCS_DIR / fname)
            help_menu.add_command(
                label=f"  {label}",
                command=lambda p=doc_path, t=label: self.content.open_help_doc(p, t)
            )

        help_menu.add_separator()
        help_menu.add_command(label="── General Docs ──", state='disabled')
        for label, fname in _GENERAL_DOCS:
            doc_path = str(_DOCS_DIR / fname)
            help_menu.add_command(
                label=f"  {label}",
                command=lambda p=doc_path, t=label: self.content.open_help_doc(p, t)
            )

        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)
        
        # Keyboard shortcuts
        self.bind('<Control-n>', lambda e: self._new_session())
        self.bind('<Control-l>', lambda e: self._clear_chat())
        self.bind('<Control-q>', lambda e: self._on_close())
        self.bind('<Control-w>', lambda e: self._close_active_tab())
        self.bind('<Control-Tab>', lambda e: self._cycle_tab(+1))
        self.bind('<Control-Shift-Tab>', lambda e: self._cycle_tab(-1))
    
    def _build_layout(self):
        """Build main layout with vertical paned window."""
        # Status bar pinned to bottom
        self.status_bar = PlatformGenStatusBar(self)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        # Vertical paned window
        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True)
        
        # Top: Content area (tabs)
        self.content = ContentArea(paned)
        paned.add(self.content, weight=3)
        
        # Bottom: Ask Genny panel
        self.ask_auger = AskGennyPanel(paned, self.content)
        paned.add(self.ask_auger, weight=2)

        # Wire self-healing: widget crash overlay → Ask Genny
        self.content._ask_auger_cb = self._on_widget_crash
        self.status_bar._content = self.content
    
    def _maybe_open_host_tools(self):
        """Open Host Tools tab only if the daemon has registered tools."""
        import threading
        def _check():
            try:
                from platformgen.tools.host_cmd import list_tools
                tools = list_tools()
                if tools:
                    from auger.ui.widgets.host_tools import HostToolsWidget
                    self.after(0, lambda: self.content.add_widget_tab("Host Tools", HostToolsWidget))
            except Exception:
                pass
        threading.Thread(target=_check, daemon=True).start()

    def _new_session(self):
        """Start new session (stub)."""
        self._show_info("New session (stub)")
    
    def _clear_chat(self):
        """Clear Ask Genny chat."""
        self.ask_auger._on_clear()

    def _on_widget_crash(self, widget_name: str, tb_str: str, source_path: str, source_snippet: str):
        """Called by crash overlay 'Ask Genny to Fix' button. Pre-fills Ask Genny with a repair prompt."""
        prompt = (
            f"Widget '{widget_name}' crashed on load. Please diagnose and propose a fix.\n\n"
            f"## Traceback\n```\n{tb_str.strip()}\n```\n\n"
            f"## Source file\n`{source_path}`\n\n"
            f"## First 120 lines of source\n```python\n{source_snippet.strip()}\n```\n\n"
            f"Propose the minimal diff needed to fix the crash. "
            f"Follow the hot-reload convention: write the fix directly to the source file — "
            f"the watcher will pick it up automatically for widget files.\n\n"
            f"## Restart instructions\n"
            f"- If your fix is ONLY in `auger/ui/widgets/*.py` → no restart needed (hot-reload picks it up)\n"
            f"- If your fix touches `auger/app.py` or `auger/ui/content_area.py` → end your response by calling:\n"
            f"  `curl --noproxy localhost -X POST http://localhost:{daemon_port()}/schedule_restart "
            f"-H 'Content-Type: application/json' -d '{{\"delay\": 5}}'`\n"
            f"  This will deliver your response first, then restart the platform cleanly.\n"
            f"  Alternatively, the user can click 🔄 Restart Platform on the crash overlay."
        )
        self.ask_auger.set_prompt(prompt)
        self.ask_auger.input_text.focus_set()

    def _handle_callback_exception(self, exc_type, exc_val, exc_tb):
        """Override Tk's default handler to surface post-load widget exceptions via Ask Genny."""
        import traceback as _tb
        import inspect as _inspect
        import time as _time

        # Anti-recursion guard
        if self._in_exception_handler:
            print(f"[!] Exception in exception handler: {exc_val}")
            return
        self._in_exception_handler = True
        try:
            tb_str = ''.join(_tb.format_exception(exc_type, exc_val, exc_tb))
            print(f"[!] Callback exception caught: {exc_val}")

            # Rate-limit: same error signature (type + last frame) suppressed for 5 minutes
            frames = _tb.extract_tb(exc_tb)
            last_frame = f"{frames[-1].filename}:{frames[-1].lineno}" if frames else "?"
            err_sig = f"{exc_type.__name__}:{last_frame}"
            now = _time.monotonic()
            if now - self._callback_error_cooldowns.get(err_sig, 0) < 300:
                return  # Suppress duplicate — already shown in last 5 min
            self._callback_error_cooldowns[err_sig] = now

            # Try to identify which widget's source file appears in the traceback
            widget_name = "Unknown Widget"
            source_path = ''
            source_snippet = ''
            widgets_dir = Path(__file__).parent / 'ui' / 'widgets'

            for frame_info in _tb.extract_tb(exc_tb):
                fpath = Path(frame_info.filename)
                if fpath.parent == widgets_dir and fpath.suffix == '.py':
                    source_path = str(fpath)
                    widget_name = fpath.stem.replace('_', ' ').title()
                    # Check if we have a WIDGET_TITLE from the loaded tab
                    for tab_key, tab_info in self.content._tabs.items():
                        cls = tab_info.get('cls')
                        if cls and hasattr(cls, 'WIDGET_TITLE'):
                            try:
                                if Path(_inspect.getfile(cls)) == fpath:
                                    widget_name = cls.WIDGET_TITLE
                                    break
                            except (TypeError, OSError):
                                pass
                    try:
                        with open(source_path, 'r', encoding='utf-8') as f:
                            source_snippet = ''.join(f.readlines()[:120])
                    except Exception:
                        pass
                    break

            # Build Ask Genny prompt and show a non-blocking banner
            prompt = (
                f"Widget '{widget_name}' raised an exception during a Tk callback "
                f"(button click, timer, or event handler). Please diagnose and propose a fix.\n\n"
                f"## Traceback\n```\n{tb_str.strip()}\n```\n"
            )
            if source_path:
                prompt += (
                    f"\n## Source file\n`{source_path}`\n\n"
                    f"## First 120 lines of source\n```python\n{source_snippet.strip()}\n```\n"
                )
            prompt += (
                "\nPropose the minimal fix. Write it directly to the source file — "
                "the hot-reload watcher will pick it up automatically for widget files.\n\n"
                "## Restart instructions\n"
                "- Fix in `auger/ui/widgets/*.py` only → no restart needed\n"
                "- Fix in `auger/app.py` or `auger/ui/content_area.py` → call:\n"
                f"  `curl --noproxy localhost -X POST http://localhost:{daemon_port()}/schedule_restart "
                "-H 'Content-Type: application/json' -d '{\"delay\": 5}'`\n"
                "  This delivers your response first, then restarts cleanly."
            )

            # Show a transient banner in the content area header
            self._show_crash_banner(widget_name, prompt)

        finally:
            self._in_exception_handler = False

    def _show_crash_banner(self, widget_name: str, ask_genny_prompt: str):
        """Show a dismissible crash banner at the top of the content area."""
        import tkinter as _tk

        banner = _tk.Frame(self.content, bg='#5a1d1d', padx=8, pady=4)
        banner.pack(fill=_tk.X, side=_tk.TOP, before=self.content._tabbar)

        _tk.Label(banner,
                  text=f"⚠  {widget_name}: exception in callback — ",
                  font=('Segoe UI', 9), fg='#f88070', bg='#5a1d1d'
                  ).pack(side=_tk.LEFT)

        def _ask():
            self.ask_auger.set_prompt(ask_genny_prompt)
            self.ask_auger.input_text.focus_set()
            banner.destroy()

        _tk.Button(banner, text='Ask Genny to Fix', font=('Segoe UI', 9, 'bold'),
                   fg='#ffffff', bg='#0e639c', relief=_tk.FLAT, padx=6, pady=2,
                   cursor='hand2', command=_ask
                   ).pack(side=_tk.LEFT, padx=(0, 8))

        _tk.Button(banner, text='✕', font=('Segoe UI', 9),
                   fg='#888888', bg='#5a1d1d', relief=_tk.FLAT, padx=4,
                   cursor='hand2', command=banner.destroy
                   ).pack(side=_tk.RIGHT)

        # Auto-dismiss after 30s
        self.after(30000, lambda: banner.destroy() if banner.winfo_exists() else None)


    def _show_widget_help(self):
        """Show widget management help."""
        messagebox.showinfo(
            "Manage Widgets",
            "Widget Management\n\n"
            "• Widgets are Python files in ui/widgets/\n"
            "• They auto-load via hot reload (1 second scan)\n"
            "• Ask Genny to generate new widgets\n"
            "• Right-click tabs to close them\n\n"
            "Example prompts:\n"
            "  'create a service health monitor widget'\n"
            "  'create a log tail widget'\n"
            "  'create a metrics dashboard widget'"
        )
    
    def _show_about(self):
        """Show about dialog."""
        messagebox.showinfo(
            f"About {product_name()}",
            f"{product_name()} v1.0\n\n"
            "A self-building AI-powered tool for Site Reliability Engineers.\n\n"
            "Ask the Genny AI agent to generate custom widgets,\n"
            "configure APIs, monitor services, and automate your SRE workflows.\n\n"
            "Built with Python + Tkinter + AI"
        )
    
    def _show_info(self, message):
        """Show info message."""
        messagebox.showinfo("Info", message)

    # ── Tab management helpers ────────────────────────────────────────────────

    def _rebuild_view_tabs(self):
        """Rebuild the open-tabs section of the View menu."""
        # Remove dynamic entries (everything after the separator at index 3)
        try:
            end = self.view_menu.index('end')
            # Keep first 4 items (Close Tab, Next, Prev, separator); delete rest
            while self.view_menu.index('end') > 3:
                self.view_menu.delete(self.view_menu.index('end'))
        except Exception:
            return
        tabs = self.content.get_open_tabs()
        for key, text, is_active in tabs:
            label = f"{'✓ ' if is_active else '   '}{text}"
            self.view_menu.add_command(
                label=label,
                command=lambda k=key: self._focus_tab_by_key(k))

    def _focus_tab_by_key(self, key):
        tab_info = self.content._tabs.get(key)
        if tab_info:
            self.content.select(tab_info['frame'])

    def _close_active_tab(self):
        if self.content._current_frame:
            self.content._close_tab(self.content._current_frame)

    def _cycle_tab(self, direction):
        entries = self.content._tabbar._entries
        if not entries or not self.content._current_frame:
            return
        frames = [e['frame'] for e in entries]
        try:
            idx = frames.index(self.content._current_frame)
            next_idx = (idx + direction) % len(frames)
            self.content.select(frames[next_idx])
        except ValueError:
            pass

    def _start_activation_listener(self):
        """Listen for "activate" signals so launcher clicks reuse this window."""
        self._activation_socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._activation_socket_path.unlink()
        except FileNotFoundError:
            pass

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(os.fspath(self._activation_socket_path))
            server.listen(1)
            server.settimeout(1.0)
        except OSError:
            server.close()
            return

        self._activation_server = server

        def _serve():
            while not self._activation_stop.is_set():
                try:
                    conn, _addr = server.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    try:
                        conn.recv(1024)
                    except OSError:
                        pass
                    try:
                        conn.sendall(b"ok")
                    except OSError:
                        pass
                self.after(0, self._activate_window)

        threading.Thread(target=_serve, daemon=True).start()

    def _activate_window(self):
        """Bring the existing PlatformGen window to the foreground."""
        try:
            self.deiconify()
            self.update_idletasks()
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass

    def _stop_activation_listener(self):
        self._activation_stop.set()
        if self._activation_server is not None:
            try:
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                    client.settimeout(0.2)
                    client.connect(os.fspath(self._activation_socket_path))
                    client.sendall(b"shutdown\n")
            except OSError:
                pass
            try:
                self._activation_server.close()
            except OSError:
                pass
            self._activation_server = None
        try:
            self._activation_socket_path.unlink()
        except FileNotFoundError:
            pass

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def _on_close(self):
        """Handle window close."""
        self.content._save_tab_state()
        if self.reloader:
            self.reloader.stop()
        self._stop_activation_listener()
        self.destroy()

 
AugerSREPlatform = PlatformGenApp


def main():
    """Main entry point."""
    if _signal_existing_instance():
        return
    app = PlatformGenApp()
    # Show first-run wizard if GHE_TOKEN is not configured
    maybe_show_wizard(app)
    app.mainloop()


if __name__ == '__main__':
    main()
