"""
Host Tools Widget - Manage and launch tools on the host machine from within the container.
Tools are registered in ~/.auger/host_tools.json and launched via the Host Tools Daemon.
"""

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import threading
import json
from pathlib import Path
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu, auger_home as _auger_home

BG = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
FG = '#e0e0e0'
ACCENT = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR = '#f44747'
SUCCESS = '#4ec9b0'
WARNING = '#ce9178'

# Well-known tools to offer in the "Add Tool" dialog
KNOWN_TOOLS = [
    {"key": "vscode",              "name": "VS Code",           "binaries": ["/snap/bin/code", "code"]},
    {"key": "intellij-community",  "name": "IntelliJ Community","binaries": ["/snap/bin/intellij-idea-community", "intellij-idea-community"]},
    {"key": "intellij-ultimate",   "name": "IntelliJ Ultimate", "binaries": ["/snap/bin/intellij-idea-ultimate", "intellij-idea-ultimate"]},
    {"key": "pycharm",             "name": "PyCharm",           "binaries": ["/snap/bin/pycharm", "pycharm"]},
    {"key": "postman",             "name": "Postman",           "binaries": ["/snap/bin/postman", "postman"]},
    {"key": "datagrip",            "name": "DataGrip",          "binaries": ["/snap/bin/datagrip", "datagrip"]},
    {"key": "eclipse",             "name": "Eclipse",           "binaries": ["/snap/bin/eclipse", "eclipse"]},
    {"key": "chrome",              "name": "Chrome",            "binaries": ["google-chrome", "/opt/google/chrome/google-chrome"]},
    {"key": "terminal",            "name": "Terminal",          "binaries": ["gnome-terminal", "xterm", "konsole"]},
    {"key": "nautilus",            "name": "Files (Nautilus)",  "binaries": ["nautilus"]},
    {"key": "custom",              "name": "Custom...",         "binaries": []},
]

TOOL_ICONS = {
    "vscode":    "VS",
    "intellij":  "IJ",
    "pycharm":   "Py",
    "chrome":    "Ch",
    "terminal":  "Tm",
    "nautilus":  "Fs",
    "postman":   "Po",
    "dbeaver":   "DB",
    "slack":     "Sl",
}



class HostToolsWidget(tk.Frame):
    """Manage and launch host tools from within the Auger container."""

    WIDGET_NAME = "host_tools"
    WIDGET_TITLE = "Host Tools"
    WIDGET_ICON = "🛠️"
    WIDGET_ICON_NAME = "tools"
    WIDGET_SKIP_AUTO_OPEN = True  # Only open when daemon reports registered tools

    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self.context_builder_callback = context_builder_callback
        self.tools = []
        self._icons = {}
        self._tool_img_cache = {}   # key → PhotoImage (keeps refs alive)
        self._create_ui()
        self._refresh_tools(auto_detect_if_empty=True)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _create_ui(self):
        # Pre-create icons
        for name in ('add', 'search', 'terminal', 'refresh', 'tools',
                     'edit', 'delete', 'play', 'search'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        # Header
        header = tk.Frame(self, bg=BG2)
        header.pack(fill=tk.X, padx=5, pady=(5, 0))

        tk.Label(header, text="Host Tools", font=('Segoe UI', 13, 'bold'),
                 fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, padx=10, pady=8)

        tk.Label(header,
                 text="Launch tools on your host machine directly from the Auger container.",
                 font=('Segoe UI', 9), fg='#888', bg=BG2).pack(side=tk.LEFT, padx=5)

        # Toolbar
        toolbar = tk.Frame(self, bg=BG3)
        toolbar.pack(fill=tk.X, padx=5, pady=2)

        tk.Button(toolbar, text=" Add Tool", image=self._icons.get('add'),
                  compound=tk.LEFT, command=self._add_tool_dialog,
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=12, pady=4).pack(side=tk.LEFT, padx=4, pady=4)

        tk.Button(toolbar, text=" Auto-Detect", image=self._icons.get('search'),
                  compound=tk.LEFT, command=self._auto_detect,
                  bg=BG2, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=12, pady=4).pack(side=tk.LEFT, padx=2, pady=4)

        tk.Button(toolbar, text=" From Launcher", image=self._icons.get('terminal'),
                  compound=tk.LEFT, command=self._from_launcher,
                  bg=BG2, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=12, pady=4).pack(side=tk.LEFT, padx=2, pady=4)

        tk.Button(toolbar, text=" Refresh", image=self._icons.get('refresh'),
                  compound=tk.LEFT, command=self._refresh_tools,
                  bg=BG2, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=12, pady=4).pack(side=tk.LEFT, padx=2, pady=4)

        self.status_var = tk.StringVar(value="Loading tools...")
        tk.Label(toolbar, textvariable=self.status_var, font=('Segoe UI', 9),
                 fg='#888', bg=BG3).pack(side=tk.RIGHT, padx=10)

        # Tools grid frame (scrollable)
        canvas_frame = tk.Frame(self, bg=BG)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.canvas = tk.Canvas(canvas_frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.tools_frame = tk.Frame(self.canvas, bg=BG)
        self.canvas_window = self.canvas.create_window((0, 0), window=self.tools_frame, anchor='nw')

        self.tools_frame.bind('<Configure>', self._on_frame_configure)
        self.canvas.bind('<Configure>', self._on_canvas_configure)

        # Daemon status indicator
        status_bar = tk.Frame(self, bg=BG2)
        status_bar.pack(fill=tk.X, padx=5, pady=(0, 5))
        self.daemon_status_var = tk.StringVar(value="Checking daemon...")
        tk.Label(status_bar, textvariable=self.daemon_status_var,
                 font=('Segoe UI', 8), fg='#888', bg=BG2).pack(side=tk.LEFT, padx=8, pady=3)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox('all'))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    # ── Tool Loading ──────────────────────────────────────────────────────────

    def _refresh_tools(self, auto_detect_if_empty=False):
        """Load tools from daemon and render cards."""
        threading.Thread(target=self._refresh_thread,
                         args=(auto_detect_if_empty,), daemon=True).start()

    def _refresh_thread(self, auto_detect_if_empty=False):
        try:
            from auger.tools.host_cmd import list_tools, auto_detect_tools
            tools = list_tools()
            if not tools and auto_detect_if_empty:
                self.after(0, lambda: self.status_var.set("Auto-detecting tools..."))
                tools = auto_detect_tools()
            self.after(0, lambda: self.daemon_status_var.set("✅ Host tools loaded"))
            self.after(0, lambda: self._render_tools(tools))
            self.after(0, lambda: self.status_var.set(f"{len(tools)} tool(s) registered"))
        except Exception as e:
            self.after(0, lambda: self.daemon_status_var.set(f"⚠️  Error loading tools: {e}"))
            self.after(0, lambda: self.status_var.set("Error"))

    def _render_tools(self, tools):
        """Render tool cards in a responsive grid."""
        self.tools = tools
        # Clear existing
        for w in self.tools_frame.winfo_children():
            w.destroy()

        if not tools:
            tk.Label(self.tools_frame,
                     text="No tools registered yet.\nClick '➕ Add Tool' or '🔍 Auto-Detect' to get started.",
                     font=('Segoe UI', 11), fg='#666', bg=BG,
                     justify=tk.CENTER).pack(pady=60)
            return

        COLS = 3
        for i, tool in enumerate(tools):
            row, col = divmod(i, COLS)
            card = self._make_tool_card(tool)
            card.grid(row=row, column=col, padx=8, pady=8, sticky='nsew')

        for c in range(COLS):
            self.tools_frame.columnconfigure(c, weight=1)

    # PIL fallback icon mapping: tool key → icon name in icons.py
    _PIL_ICON_FALLBACK = {
        'vscode':             'terminal',
        'intellij-community': 'tools',
        'intellij-ultimate':  'tools',
        'pycharm':            'terminal',
        'chrome':             'search',
        'terminal':           'terminal',
        'nautilus':           'folder',
        'postman':            'connect',
        'datagrip':           'database',
        'dbeaver':            'database',
        'eclipse':            'tools',
        'slack':              'connect',
        'docker':             'docker',
        'kubectl':            'pods',
        'rancher':            'pods',
    }

    def _make_tool_card(self, tool):
        """Create a single tool card widget."""
        key = tool.get('key', '')
        name = tool.get('name', key)
        binary = tool.get('binary', '') or tool.get('exec_cmd', '')
        icon_name = tool.get('icon', '')  # from .desktop Icon= field

        card = tk.Frame(self.tools_frame, bg=BG2, relief=tk.FLAT, bd=1)

        # Icon label — starts with PIL fallback, replaced by host icon async
        icon_label = tk.Label(card, bg=BG2)
        icon_label.pack(pady=(14, 2))
        self._set_card_icon_pil_fallback(icon_label, key, size=48)

        tk.Label(card, text=name, font=('Segoe UI', 11, 'bold'), bg=BG2, fg=FG
                 ).pack()
        tk.Label(card, text=binary or "—", font=('Consolas', 8),
                 bg=BG2, fg='#555', wraplength=180
                 ).pack(pady=(2, 8))

        # Async: try to get real icon from host
        threading.Thread(target=self._load_host_icon,
                         args=(key, icon_name, icon_label), daemon=True).start()

        # Button row
        btn_row = tk.Frame(card, bg=BG2)
        btn_row.pack(pady=(0, 10))

        tk.Button(btn_row, text=" Launch",
                  image=self._icons.get('play'),
                  compound=tk.LEFT,
                  command=lambda k=key: self._launch_tool(k),
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=10, pady=3).pack(side=tk.LEFT, padx=4)

        tk.Button(btn_row, text=" Edit",
                  image=self._icons.get('edit'),
                  compound=tk.LEFT,
                  command=lambda t=tool: self._edit_tool(t),
                  bg=BG3, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=6, pady=3).pack(side=tk.LEFT, padx=2)

        tk.Button(btn_row, text=" Del",
                  image=self._icons.get('delete'),
                  compound=tk.LEFT,
                  command=lambda k=key: self._remove_tool(k),
                  bg=BG3, fg=ERROR, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=6, pady=3).pack(side=tk.LEFT, padx=2)

        return card

    def _set_card_icon_pil_fallback(self, label: tk.Label, key: str, size: int = 48):
        """Set label image to a PIL-drawn icon or a colored letter-box fallback."""
        # Only use a specific PIL icon if this tool key is explicitly mapped
        pil_key = self._PIL_ICON_FALLBACK.get(key)
        if pil_key:
            try:
                img = _icons.get(pil_key, size)
                label.config(image=img, text='')
                self._tool_img_cache[f'_pil_{key}'] = img
                return
            except Exception:
                pass
        # Default: colored rounded box with tool initials — distinctive per tool
        try:
            from PIL import Image, ImageDraw, ImageFont, ImageTk
            import io
            # Use first letter of each word, up to 2 chars
            words = key.replace('-', ' ').replace('_', ' ').split()
            abbrev = (''.join(w[0] for w in words)[:2] or key[:2]).upper()
            hue = sum(ord(c) for c in key) % 6
            colors = ['#007acc', '#4ec9b0', '#ce9178', '#9cdcfe', '#c586c0', '#dcdcaa']
            bg_col = colors[hue]
            img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle([2, 2, size-2, size-2], radius=10, fill=bg_col)
            try:
                font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                                         size // 3)
            except Exception:
                font = ImageFont.load_default()
            bbox = draw.textbbox((0, 0), abbrev, font=font)
            tx = (size - (bbox[2]-bbox[0])) // 2 - bbox[0]
            ty = (size - (bbox[3]-bbox[1])) // 2 - bbox[1]
            draw.text((tx, ty), abbrev, fill='white', font=font)
            buf = io.BytesIO()
            img.save(buf, 'PNG')
            photo = ImageTk.PhotoImage(data=buf.getvalue())
            label.config(image=photo, text='')
            self._tool_img_cache[f'_abbrev_{key}'] = photo
        except Exception:
            label.config(text=(key[:2] or '??').upper(),
                         font=('Segoe UI', 14, 'bold'), fg=ACCENT)

    def _load_host_icon(self, key: str, icon_name: str, label: tk.Label):
        """Background thread: fetch real icon from host, update label if found."""
        try:
            from auger.tools.host_cmd import get_tool_icon
            from PIL import Image, ImageTk
            import io
            raw = get_tool_icon(key, icon_name)
            if not raw:
                return
            img = Image.open(io.BytesIO(raw)).convert('RGBA')
            img = img.resize((48, 48), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, 'PNG')
            photo = ImageTk.PhotoImage(data=buf.getvalue())
            # Update on main thread — check widget still exists
            def _apply():
                try:
                    if label.winfo_exists():
                        label.config(image=photo, text='')
                        self._tool_img_cache[f'_host_{key}'] = photo
                except Exception:
                    pass
            self.after(0, _apply)
        except Exception:
            pass  # keep PIL fallback

    # ── Actions ───────────────────────────────────────────────────────────────

    def _launch_tool(self, key):
        """Launch a tool via the host daemon."""
        self.status_var.set(f"Launching {key}...")
        def _thread():
            try:
                from auger.tools.host_cmd import launch_tool
                result = launch_tool(key)
                if result.get('status') == 'ok':
                    self.after(0, lambda: self.status_var.set(f"✅ Launched {key}"))
                else:
                    msg = result.get('message', 'Unknown error')
                    self.after(0, lambda: messagebox.showerror("Launch Failed", msg))
                    self.after(0, lambda: self.status_var.set(f"❌ {msg}"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_thread, daemon=True).start()

    def _auto_detect(self):
        """Ask daemon to scan host for well-known tools and reload."""
        self.status_var.set("Auto-detecting tools...")
        def _thread():
            try:
                from auger.tools.host_cmd import auto_detect_tools
                tools = auto_detect_tools()
                self.after(0, lambda: self._render_tools(tools))
                self.after(0, lambda: self.status_var.set(f"Found {len(tools)} tool(s)"))
            except Exception as e:
                self.after(0, lambda: self.status_var.set(f"Error: {e}"))
        threading.Thread(target=_thread, daemon=True).start()

    def _from_launcher(self):
        """Fetch all .desktop apps from host launcher and show a picker."""
        self.status_var.set("Loading launcher apps from host...")
        def _thread():
            try:
                from auger.tools.host_cmd import list_desktop_apps
                apps = list_desktop_apps()
                if not apps:
                    self.after(0, lambda: messagebox.showinfo(
                        "No Apps Found", "No .desktop apps found on host."))
                    self.after(0, lambda: self.status_var.set("No launcher apps found"))
                    return
                self.after(0, lambda: self._show_launcher_picker(apps))
                self.after(0, lambda: self.status_var.set(f"Found {len(apps)} launcher apps"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
                self.after(0, lambda: self.status_var.set(f"Error: {e}"))
        threading.Thread(target=_thread, daemon=True).start()

    def _show_launcher_picker(self, apps):
        """Show a searchable picker dialog for launcher apps."""
        dialog = tk.Toplevel(self)
        dialog.title("Add from Launcher")
        dialog.configure(bg=BG)
        dialog.geometry("640x540")
        dialog.grab_set()

        hdr_f = tk.Frame(dialog, bg=BG)
        hdr_f.pack(pady=(15, 5))
        try:
            _ico = self._icons.get('terminal')
            if _ico:
                tk.Label(hdr_f, image=_ico, bg=BG).pack(side=tk.LEFT, padx=(0, 6))
        except Exception:
            pass
        tk.Label(hdr_f, text="Add from Launcher",
                 font=('Segoe UI', 13, 'bold'), fg=ACCENT2, bg=BG).pack(side=tk.LEFT)
        tk.Label(dialog, text="Select apps from your Ubuntu launcher to add as host tools.",
                 font=('Segoe UI', 9), fg='#888', bg=BG).pack(pady=(0, 8))

        # Search bar
        search_frame = tk.Frame(dialog, bg=BG)
        search_frame.pack(fill=tk.X, padx=20, pady=(0, 6))
        try:
            _sico = self._icons.get('search')
            if _sico:
                tk.Label(search_frame, image=_sico, bg=BG, fg=FG).pack(side=tk.LEFT)
        except Exception:
            pass
        search_var = tk.StringVar()
        search_entry = tk.Entry(search_frame, textvariable=search_var,
                                bg=BG3, fg=FG, font=('Segoe UI', 10), relief=tk.FLAT)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))

        # Listbox with scrollbar
        list_frame = tk.Frame(dialog, bg=BG)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=4)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        lb = tk.Listbox(list_frame, bg=BG3, fg=FG, font=('Segoe UI', 10),
                        selectmode=tk.EXTENDED, relief=tk.FLAT,
                        activestyle='dotbox', selectbackground=ACCENT,
                        yscrollcommand=scrollbar.set)
        scrollbar.config(command=lb.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        add_listbox_menu(lb)

        # Populate listbox, filter on search
        filtered_apps = list(apps)

        def populate(filter_text=''):
            lb.delete(0, tk.END)
            filtered_apps.clear()
            for app in apps:
                if filter_text.lower() in app['name'].lower():
                    filtered_apps.append(app)
                    lb.insert(tk.END, f"  {app['name']}   —   {app['exec_cmd'][:55]}{'…' if len(app['exec_cmd'])>55 else ''}")

        populate()
        search_var.trace_add('write', lambda *_: populate(search_var.get()))

        # Preview label
        preview_var = tk.StringVar(value="")
        tk.Label(dialog, textvariable=preview_var, font=('Consolas', 8),
                 fg='#666', bg=BG, anchor='w', wraplength=590).pack(fill=tk.X, padx=20, pady=2)

        def on_select(_event=None):
            idx = lb.curselection()
            if idx:
                app = filtered_apps[idx[-1]]
                preview_var.set(f"Exec: {app['exec_cmd']}")

        lb.bind('<<ListboxSelect>>', on_select)

        def add_selected():
            indices = lb.curselection()
            if not indices:
                messagebox.showwarning("No Selection", "Select at least one app.", parent=dialog)
                return
            from auger.tools.host_cmd import register_tool
            added = []
            for i in indices:
                app = filtered_apps[i]
                # Extract binary (first token before spaces/flags)
                import shlex
                try:
                    parts = shlex.split(app['exec_cmd'])
                    binary = parts[0] if parts else ''
                except Exception:
                    binary = app['exec_cmd'].split()[0] if app['exec_cmd'].split() else ''
                result = register_tool(
                    key=app['key'], name=app['name'],
                    binary=binary, exec_cmd=app['exec_cmd']
                )
                if result.get('status') == 'ok':
                    added.append(app['name'])
            if added:
                dialog.destroy()
                self._refresh_tools()
                self.status_var.set(f"✅ Added: {', '.join(added)}")
            else:
                messagebox.showerror("Error", "Failed to register tools.", parent=dialog)

        btn_row = tk.Frame(dialog, bg=BG)
        btn_row.pack(pady=10)
        tk.Button(btn_row, text=" Add Selected", command=add_selected,
                  bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                  relief=tk.FLAT, padx=16, pady=6).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Cancel", command=dialog.destroy,
                  bg=BG3, fg=FG, font=('Segoe UI', 10),
                  relief=tk.FLAT, padx=16, pady=6).pack(side=tk.LEFT, padx=6)
        search_entry.focus_set()

    def _remove_tool(self, key):
        """Remove a tool from the registry."""
        if not messagebox.askyesno("Remove Tool", f"Remove '{key}' from host tools?"):
            return
        tools_file = _auger_home() / '.auger' / 'host_tools.json'
        try:
            data = json.loads(tools_file.read_text())
            data['tools'] = [t for t in data.get('tools', []) if t.get('key') != key]
            tools_file.write_text(json.dumps(data, indent=2))
            self._refresh_tools()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _edit_tool(self, tool):
        """Open edit dialog for a tool."""
        self._show_tool_form(tool)

    def _add_tool_dialog(self):
        """Open Add Tool dialog."""
        self._show_tool_form(None)

    def _show_tool_form(self, existing_tool):
        """Show Add/Edit tool form."""
        dialog = tk.Toplevel(self)
        dialog.title("Edit Tool" if existing_tool else "Add Host Tool")
        dialog.configure(bg=BG)
        dialog.geometry("520x480")
        dialog.grab_set()

        tk.Label(dialog, text="Add Host Tool" if not existing_tool else "Edit Host Tool",
                 font=('Segoe UI', 13, 'bold'), fg=ACCENT2, bg=BG).pack(pady=(15, 5))

        form = tk.Frame(dialog, bg=BG)
        form.pack(fill=tk.BOTH, expand=True, padx=20)

        # Quick-add known tools (only when adding)
        if not existing_tool:
            tk.Label(form, text="Quick Add:", font=('Segoe UI', 10, 'bold'),
                     fg=FG, bg=BG).grid(row=0, column=0, sticky='w', pady=(10, 4))

            quick_frame = tk.Frame(form, bg=BG)
            quick_frame.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(0, 10))

            for kt in KNOWN_TOOLS[:-1]:  # skip "Custom..."
                tk.Button(quick_frame, text=f"{TOOL_ICONS.get(kt['key'], '?')} {kt['name']}",
                          command=lambda k=kt: self._quick_add(k, dialog),
                          bg=BG3, fg=FG, font=('Segoe UI', 8),
                          relief=tk.FLAT, padx=6, pady=3
                          ).pack(side=tk.LEFT, padx=2, pady=2)

            tk.Label(form, text="─── or configure manually ───",
                     font=('Segoe UI', 8), fg='#555', bg=BG
                     ).grid(row=2, column=0, columnspan=2, pady=8)
            row_offset = 3
        else:
            row_offset = 0

        def field(label, default='', row=0):
            tk.Label(form, text=label, font=('Segoe UI', 10), fg=FG, bg=BG
                     ).grid(row=row_offset+row, column=0, sticky='w', pady=4)
            var = tk.StringVar(value=default)
            tk.Entry(form, textvariable=var, font=('Segoe UI', 10),
                     bg=BG3, fg=FG, width=40
                     ).grid(row=row_offset+row, column=1, sticky='ew', padx=(10, 0), pady=4)
            return var

        name_var = field("Name:", existing_tool.get('name','') if existing_tool else '', 0)
        key_var  = field("Key (no spaces):", existing_tool.get('key','') if existing_tool else '', 1)
        bin_var  = field("Binary path:", existing_tool.get('binary','') if existing_tool else '', 2)
        icon_var = field("Icon (abbrev):", TOOL_ICONS.get(existing_tool.get('key',''), '?') if existing_tool else '?', 3)

        form.columnconfigure(1, weight=1)

        # Find binary button
        def find_binary():
            name = key_var.get() or name_var.get()
            if not name:
                return
            self.status_var.set(f"Searching for {name}...")
            def _thread():
                try:
                    from auger.tools.host_cmd import find_tool
                    path = find_tool(name.lower().replace(' ', ''))
                    if path:
                        self.after(0, lambda: bin_var.set(path))
                        self.after(0, lambda: self.status_var.set(f"Found: {path}"))
                    else:
                        self.after(0, lambda: self.status_var.set("Not found on host PATH"))
                except Exception as e:
                    self.after(0, lambda: self.status_var.set(f"Error: {e}"))
            threading.Thread(target=_thread, daemon=True).start()

        tk.Button(form, text=" Find on Host", command=find_binary,
                  bg=BG3, fg=FG, font=('Segoe UI', 9), relief=tk.FLAT, padx=10
                  ).grid(row=row_offset+4, column=1, sticky='w', padx=(10,0), pady=6)

        def save():
            name = name_var.get().strip()
            key  = key_var.get().strip().lower().replace(' ', '_')
            binary = bin_var.get().strip()
            ico    = icon_var.get().strip()

            if not name or not key or not binary:
                messagebox.showwarning("Missing Fields", "Name, Key, and Binary are required.")
                return

            # Update icon map in memory
            if ico:
                TOOL_ICONS[key] = ico

            try:
                from auger.tools.host_cmd import register_tool
                result = register_tool(key, name, binary)
                if result.get('status') == 'ok':
                    dialog.destroy()
                    self._refresh_tools()
                else:
                    messagebox.showerror("Error", result.get('message', 'Failed'))
            except Exception as e:
                messagebox.showerror("Error", str(e))

        btn_row = tk.Frame(dialog, bg=BG)
        btn_row.pack(pady=12)
        tk.Button(btn_row, text=" Save", command=save,
                  bg=ACCENT, fg='white', font=('Segoe UI', 10, 'bold'),
                  relief=tk.FLAT, padx=20, pady=6).pack(side=tk.LEFT, padx=6)
        tk.Button(btn_row, text="Cancel", command=dialog.destroy,
                  bg=BG3, fg=FG, font=('Segoe UI', 10),
                  relief=tk.FLAT, padx=20, pady=6).pack(side=tk.LEFT, padx=6)

    def _quick_add(self, known_tool, parent_dialog):
        """Quick-add a known tool by asking daemon to find it."""
        parent_dialog.destroy()
        self.status_var.set(f"Looking for {known_tool['name']} on host...")
        def _thread():
            try:
                from auger.tools.host_cmd import find_tool, register_tool
                binary = ''
                for b in known_tool['binaries']:
                    found = find_tool(b)
                    if found:
                        binary = found
                        break
                if not binary:
                    # Try the key itself
                    binary = find_tool(known_tool['key'])

                if binary:
                    result = register_tool(known_tool['key'], known_tool['name'], binary)
                    if result.get('status') == 'ok':
                        self.after(0, lambda: self.status_var.set(
                            f"✅ Added {known_tool['name']} ({binary})"))
                        self.after(0, self._refresh_tools)
                    else:
                        self.after(0, lambda: messagebox.showerror(
                            "Error", result.get('message', 'Failed')))
                else:
                    self.after(0, lambda: messagebox.showwarning(
                        "Not Found",
                        f"{known_tool['name']} was not found on your host.\n"
                        "Use 'Add Tool' to specify the path manually."))
                    self.after(0, lambda: self.status_var.set(
                        f"{known_tool['name']} not found on host"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", str(e)))
        threading.Thread(target=_thread, daemon=True).start()
