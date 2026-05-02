"""
Explorer Widget - File System Browser
Browse and view files on all mounted volumes and local container filesystem.

Mounts surfaced:
  /host          → full host root (read-only, via AUGER_HOST_ROOT or /host)
  ~/repos        → git repositories
  ~/.auger       → auger config / shared history
  ~/.copilot     → copilot session state
  ~/.kube        → kubeconfig
  /              → container root (local files)

Uses lazy-loading (expand on demand) so large trees don't block the UI.
"""

import os
import stat
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu
from pathlib import Path
from datetime import datetime

from auger.ui import icons as _icons

# ── Theme colours ──────────────────────────────────────────────────────────────
BG  = '#1e1e1e'
BG2 = '#252526'
BG3 = '#2d2d2d'
FG  = '#e0e0e0'
FG2 = '#a0a0a0'
ACCENT  = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR   = '#f44747'
WARNING = '#ce9178'

# ── Viewable text extensions ───────────────────────────────────────────────────
TEXT_EXTS = {
    '.txt', '.md', '.rst', '.log', '.json', '.yaml', '.yml', '.toml', '.ini',
    '.cfg', '.conf', '.env', '.sh', '.bash', '.zsh', '.py', '.js', '.ts',
    '.jsx', '.tsx', '.html', '.htm', '.xml', '.css', '.scss', '.sql', '.tf',
    '.hcl', '.go', '.java', '.c', '.cpp', '.h', '.rs', '.rb', '.pl', '.lua',
    '.dockerfile', '.gitignore', '.gitattributes', '.editorconfig',
    '.properties', '.gradle', '.pom', '.makefile', '', '.lock', '.sum',
}
MAX_PREVIEW_BYTES = 512 * 1024  # 512 KB


def _is_viewable(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTS:
        return True
    # No extension — try common names
    if path.name.lower() in {'makefile', 'dockerfile', 'readme', 'license',
                              'changelog', 'authors', 'notice', 'copying'}:
        return True
    return False


def _human_size(n: int) -> str:
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ── Bookmarks: well-known mount points ────────────────────────────────────────
def _bookmarks() -> list[tuple[str, Path]]:
    """Return (label, path) for key mount points that exist."""
    host_root = Path(os.environ.get('AUGER_HOST_ROOT', '/host'))
    home = Path.home()
    candidates = [
        ('Host Root (/host)',       host_root),
        ('Host ~/repos',           host_root / home.relative_to('/') / 'repos'
                                   if host_root != Path('/') else home / 'repos'),
        ('Container /home/auger',  Path('/home/auger')),
        ('Repos (in container)',   home / 'repos'),
        ('~/.auger',               home / '.auger'),
        ('~/.copilot',             home / '.copilot'),
        ('~/.kube',                home / '.kube'),
        ('Container Root (/)',     Path('/')),
    ]
    return [(label, p) for label, p in candidates if p.exists()]



class ExplorerWidget(tk.Frame):
    """File system explorer with lazy-loading tree and inline file viewer."""

    WIDGET_ICON_NAME = "explorer"

    # Sentinel value inserted as placeholder child so folder shows expand arrow
    _PLACEHOLDER = '<<placeholder>>'

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._current_file: Path | None = None
        self._tools_cache: list = []        # refreshed from daemon
        self._ctx_menu: tk.Menu | None = None
        self._create_ui()
        self._refresh_tools()

    # ── UI construction ────────────────────────────────────────────────────────

    def _create_ui(self):
        # Header
        header = tk.Frame(self, bg=ACCENT, height=40)
        header.pack(fill=tk.X)
        header.pack_propagate(False)

        try:
            self._header_icon = _icons.get('explorer', 28)
            tk.Label(header, image=self._header_icon, bg=ACCENT).pack(side=tk.LEFT, padx=(15, 4), pady=6)
        except Exception:
            pass

        tk.Label(header, text="Explorer",
                 font=('Segoe UI', 12, 'bold'), fg='#ffffff', bg=ACCENT
                 ).pack(side=tk.LEFT, padx=(0, 5), pady=10)
        tk.Label(header, text="Browse host and container filesystems",
                 font=('Segoe UI', 9), fg=FG, bg=ACCENT
                 ).pack(side=tk.LEFT, padx=5)

        # Bookmark toolbar
        bm_frame = tk.Frame(self, bg=BG2)
        bm_frame.pack(fill=tk.X, padx=0, pady=0)
        tk.Label(bm_frame, text="Quick access:", fg=FG2, bg=BG2,
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(8, 4), pady=4)
        for label, path in _bookmarks():
            btn = tk.Button(
                bm_frame, text=label,
                command=lambda p=path: self._navigate_to(p),
                bg=BG3, fg=ACCENT2, relief=tk.FLAT,
                font=('Segoe UI', 8), padx=6, pady=2,
                cursor='hand2', activebackground=ACCENT, activeforeground='white'
            )
            btn.pack(side=tk.LEFT, padx=2, pady=3)

        # Address bar
        addr_frame = tk.Frame(self, bg=BG2)
        addr_frame.pack(fill=tk.X, padx=0, pady=0)
        tk.Label(addr_frame, text="Path:", fg=FG2, bg=BG2,
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(8, 4), pady=3)
        self._path_var = tk.StringVar()
        path_entry = tk.Entry(addr_frame, textvariable=self._path_var,
                              bg=BG3, fg=FG, insertbackground=FG,
                              relief=tk.FLAT, font=('Consolas', 9))
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4), pady=3)
        path_entry.bind('<Return>', lambda e: self._navigate_to(
            Path(self._path_var.get().strip())))
        tk.Button(addr_frame, text="Go", command=lambda: self._navigate_to(
            Path(self._path_var.get().strip())),
            bg=ACCENT, fg='white', relief=tk.FLAT, font=('Segoe UI', 8),
            padx=8, pady=2
        ).pack(side=tk.LEFT, padx=(0, 8), pady=3)

        # Main pane: tree LEFT, viewer RIGHT
        pane = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=BG,
                              sashwidth=4, sashrelief=tk.FLAT)
        pane.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        # ── Left: tree ────────────────────────────────────────────────────────
        tree_frame = tk.Frame(pane, bg=BG2)
        pane.add(tree_frame, minsize=220, width=300)

        style = ttk.Style()
        style.configure('Explorer.Treeview',
                        background=BG2, foreground=FG,
                        fieldbackground=BG2, rowheight=22,
                        font=('Segoe UI', 9))
        style.configure('Explorer.Treeview.Heading',
                        background=BG3, foreground=ACCENT2,
                        font=('Segoe UI', 9, 'bold'))
        style.map('Explorer.Treeview',
                  background=[('selected', ACCENT)],
                  foreground=[('selected', 'white')])

        tree_scroll_y = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL)
        tree_scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        tree_scroll_x = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL)
        tree_scroll_x.pack(side=tk.BOTTOM, fill=tk.X)

        self._tree = ttk.Treeview(
            tree_frame, style='Explorer.Treeview',
            yscrollcommand=tree_scroll_y.set,
            xscrollcommand=tree_scroll_x.set,
            selectmode='browse', show='tree'
        )
        tree_scroll_y.config(command=self._tree.yview)
        tree_scroll_x.config(command=self._tree.xview)
        self._tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self._tree)
        self._tree.bind('<<TreeviewOpen>>', self._on_expand)
        self._tree.bind('<<TreeviewSelect>>', self._on_select)
        self._tree.bind('<Button-3>', self._on_right_click)   # right-click menu

        # ── Right: viewer ─────────────────────────────────────────────────────
        viewer_frame = tk.Frame(pane, bg=BG)
        pane.add(viewer_frame, minsize=300)

        # Viewer toolbar
        vbar = tk.Frame(viewer_frame, bg=BG2)
        vbar.pack(fill=tk.X)
        self._file_label = tk.Label(vbar, text="No file selected",
                                    fg=ACCENT2, bg=BG2,
                                    font=('Segoe UI', 9, 'bold'), anchor=tk.W)
        self._file_label.pack(side=tk.LEFT, padx=8, pady=4, fill=tk.X, expand=True)
        self._size_label = tk.Label(vbar, text="", fg=FG2, bg=BG2,
                                    font=('Segoe UI', 8))
        self._size_label.pack(side=tk.RIGHT, padx=8, pady=4)

        self._viewer = scrolledtext.ScrolledText(
            viewer_frame, wrap=tk.NONE,
            font=('Consolas', 10),
            bg=BG3, fg=FG, insertbackground=FG,
            state=tk.DISABLED
        )
        self._viewer.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(self._viewer)

        # Status bar
        self._status_var = tk.StringVar(value="Select a bookmark or type a path to start browsing")
        tk.Label(self, textvariable=self._status_var,
                 bg=BG2, fg=ACCENT2, anchor=tk.W,
                 padx=10, pady=4, font=('Segoe UI', 8)
                 ).pack(fill=tk.X, side=tk.BOTTOM)

        # Seed tree with bookmarks
        self._seed_bookmarks()

    # ── Tree seeding & lazy loading ───────────────────────────────────────────

    def _seed_bookmarks(self):
        """Populate the tree root with bookmark mount points."""
        for label, path in _bookmarks():
            node = self._tree.insert(
                '', 'end',
                text=f"  {label}",
                values=(str(path),),
                tags=('root',), open=False
            )
            # Add placeholder so expand arrow appears
            self._tree.insert(node, 'end', iid=f'{node}{self._PLACEHOLDER}',
                               text='Loading...')

    def _on_expand(self, event):
        """Lazy-load children when a node is expanded."""
        node = self._tree.focus()
        children = self._tree.get_children(node)
        # If only placeholder child exists, load real children
        if len(children) == 1 and str(children[0]).endswith(self._PLACEHOLDER):
            self._tree.delete(children[0])
            values = self._tree.item(node, 'values')
            if values:
                path = Path(values[0])
                threading.Thread(
                    target=self._load_children,
                    args=(node, path), daemon=True
                ).start()

    def _load_children(self, parent_node: str, path: Path):
        """Background: read directory and insert children into tree."""
        try:
            items = sorted(path.iterdir(),
                           key=lambda x: (not x.is_dir(), x.name.lower()))
        except PermissionError:
            self.after(0, lambda: self._tree.insert(
                parent_node, 'end', text='  [permission denied]',
                tags=('error',)))
            return
        except Exception as e:
            self.after(0, lambda: self._tree.insert(
                parent_node, 'end', text=f'  [{e}]', tags=('error',)))
            return

        def _insert():
            for item in items:
                try:
                    is_dir = item.is_dir()
                    is_link = item.is_symlink()
                    prefix = '  '
                    if is_link:
                        icon = '🔗 '
                    elif is_dir:
                        icon = '📁 '
                    else:
                        icon = '📄 '
                    label = f"{prefix}{icon}{item.name}"
                    node = self._tree.insert(
                        parent_node, 'end',
                        text=label,
                        values=(str(item),),
                        tags=('directory' if is_dir else 'file',)
                    )
                    if is_dir:
                        # Placeholder so expand arrow shows
                        self._tree.insert(node, 'end',
                                          iid=f'{node}{self._PLACEHOLDER}',
                                          text='Loading...')
                except Exception:
                    pass
            if not items:
                self._tree.insert(parent_node, 'end',
                                  text='  [empty]', tags=('info',))

        self.after(0, _insert)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate_to(self, path: Path):
        """Jump directly to a path — add as new root node if not already there."""
        if not path.exists():
            self._status_var.set(f"Path not found: {path}")
            return
        self._path_var.set(str(path))
        if path.is_dir():
            # Check if already in tree as root
            for node in self._tree.get_children(''):
                vals = self._tree.item(node, 'values')
                if vals and Path(vals[0]) == path:
                    self._tree.see(node)
                    self._tree.item(node, open=True)
                    self._on_expand(None)  # trigger load
                    return
            # Add as new root
            node = self._tree.insert(
                '', 'end',
                text=f"  📁 {path.name or str(path)}",
                values=(str(path),), tags=('root',), open=True
            )
            self._tree.insert(node, 'end',
                              iid=f'{node}{self._PLACEHOLDER}',
                              text='Loading...')
            self._tree.see(node)
            self._tree.focus(node)
            self._tree.selection_set(node)
            self.after(50, lambda: self._on_expand(None))
        else:
            self._show_file(path)

    # ── Selection / file display ──────────────────────────────────────────────

    def _on_select(self, event):
        """Called when tree selection changes."""
        sel = self._tree.selection()
        if not sel:
            return
        node = sel[0]
        values = self._tree.item(node, 'values')
        if not values:
            return
        path = Path(values[0])
        self._path_var.set(str(path))
        if path.is_file():
            self._show_file(path)
        else:
            self._status_var.set(str(path))

    def _show_file(self, path: Path):
        """Display a file's contents in the viewer."""
        self._current_file = path
        self._file_label.config(text=path.name)

        try:
            file_stat = path.stat()
            size = file_stat.st_size
            mtime = datetime.fromtimestamp(file_stat.st_mtime).strftime('%Y-%m-%d %H:%M')
            self._size_label.config(text=f"{_human_size(size)}  {mtime}")
        except Exception:
            self._size_label.config(text="")

        self._viewer.config(state=tk.NORMAL)
        self._viewer.delete('1.0', tk.END)

        if not _is_viewable(path):
            self._viewer.insert('1.0',
                f"Binary or unsupported file type: {path.suffix or '(no extension)'}\n\n"
                f"Path: {path}\n"
            )
            self._viewer.config(state=tk.DISABLED)
            self._status_var.set(f"Binary file: {path}")
            return

        threading.Thread(target=self._read_file, args=(path,), daemon=True).start()

    def _read_file(self, path: Path):
        """Background: read file and update viewer."""
        try:
            size = path.stat().st_size
            if size > MAX_PREVIEW_BYTES:
                with open(path, 'r', encoding='utf-8', errors='replace') as f:
                    content = f.read(MAX_PREVIEW_BYTES)
                content += f'\n\n[... truncated — file is {_human_size(size)}, showing first 512 KB ...]'
            else:
                content = path.read_text(encoding='utf-8', errors='replace')

            def _update():
                self._viewer.config(state=tk.NORMAL)
                self._viewer.delete('1.0', tk.END)
                self._viewer.insert('1.0', content)
                self._viewer.config(state=tk.DISABLED)
                self._status_var.set(str(path))

            self.after(0, _update)

        except PermissionError:
            self.after(0, lambda: self._set_viewer_text(
                f"Permission denied: {path}"))
        except Exception as e:
            self.after(0, lambda: self._set_viewer_text(
                f"Error reading file: {e}"))

    def _set_viewer_text(self, text: str):
        self._viewer.config(state=tk.NORMAL)
        self._viewer.delete('1.0', tk.END)
        self._viewer.insert('1.0', text)
        self._viewer.config(state=tk.DISABLED)

    # ── Host tools helpers ────────────────────────────────────────────────────

    def _refresh_tools(self):
        """Fetch registered host tools from daemon in background."""
        def _thread():
            try:
                from auger.tools.host_cmd import list_tools
                tools = list_tools()
                self.after(0, lambda: setattr(self, '_tools_cache', tools))
            except Exception:
                pass
        threading.Thread(target=_thread, daemon=True).start()

    @staticmethod
    def _host_path(container_path: str) -> str:
        """Convert a container-side path to its host equivalent.

        /host/home/user/...  →  /home/user/...
        /host                →  /
        /home/auger/repos/x  →  same (already host-relative inside container)
        """
        p = container_path
        if p.startswith('/host/'):
            return p[5:]
        if p == '/host':
            return '/'
        return p

    # ── Right-click context menu ───────────────────────────────────────────────

    def _on_right_click(self, event):
        """Show context menu on right-click over a tree node."""
        # Identify the row under cursor
        row = self._tree.identify_row(event.y)
        if row:
            self._tree.selection_set(row)
            self._tree.focus(row)

        values = self._tree.item(row, 'values') if row else None
        path_str = values[0] if values else None
        path = Path(path_str) if path_str else None

        # Refresh tools each time menu opens
        self._refresh_tools()

        menu = tk.Menu(self, tearoff=False, bg=BG3, fg=FG,
                       activebackground=ACCENT, activeforeground='white',
                       font=('Segoe UI', 9))
        self._ctx_menu = menu  # keep reference

        if path:
            # ── VS Code shortcut ─────────────────────────────────────────────
            vscode = next((t for t in self._tools_cache if t.get('key') == 'vscode'), None)
            if vscode:
                menu.add_command(
                    label=f"  Open in VS Code",
                    command=lambda p=path_str: self._open_with('vscode', p)
                )
                menu.add_separator()

            # ── Open With submenu ────────────────────────────────────────────
            if self._tools_cache:
                open_menu = tk.Menu(menu, tearoff=False, bg=BG3, fg=FG,
                                    activebackground=ACCENT, activeforeground='white',
                                    font=('Segoe UI', 9))
                for t in self._tools_cache:
                    key = t.get('key', '')
                    name = t.get('name', key)
                    open_menu.add_command(
                        label=f"  {name}",
                        command=lambda k=key, p=path_str: self._open_with(k, p)
                    )
                menu.add_cascade(label="  Open With →", menu=open_menu)
            else:
                menu.add_command(label="  Open With → (no tools registered)",
                                 state=tk.DISABLED)

            menu.add_separator()

            # ── Copy path ────────────────────────────────────────────────────
            menu.add_command(label="  Copy Container Path",
                             command=lambda p=path_str: self._copy_to_clipboard(p))
            host_p = self._host_path(path_str)
            if host_p != path_str:
                menu.add_command(label=f"  Copy Host Path  ({host_p})",
                                 command=lambda p=host_p: self._copy_to_clipboard(p))

            menu.add_separator()

        # ── Add / manage tools ────────────────────────────────────────────────
        menu.add_command(label="  Add Host Tool…", command=self._add_tool_dialog)
        menu.add_command(label="  Auto-detect Host Tools",
                         command=self._auto_detect_tools)
        menu.add_command(label="  Refresh Tools List",
                         command=self._refresh_tools)

        menu.post(event.x_root, event.y_root)

    def _open_with(self, tool_key: str, path_str: str):
        """Send open_path command to daemon in background."""
        def _thread():
            try:
                from auger.tools.host_cmd import open_path
                result = open_path(tool_key, path_str)
                msg = result.get('message', '')
                if result.get('status') == 'ok':
                    self.after(0, lambda: self._status_var.set(
                        f"Opened: {self._host_path(path_str)}"))
                else:
                    self.after(0, lambda: self._status_var.set(
                        f"Error: {msg}"))
            except Exception as e:
                self.after(0, lambda: self._status_var.set(f"Error: {e}"))
        threading.Thread(target=_thread, daemon=True).start()

    def _copy_to_clipboard(self, text: str):
        """Copy text to system clipboard."""
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._status_var.set(f"Copied: {text}")
        except Exception as e:
            self._status_var.set(f"Clipboard error: {e}")

    def _auto_detect_tools(self):
        """Ask daemon to auto-detect host tools and refresh cache."""
        self._status_var.set("Detecting host tools…")
        def _thread():
            try:
                from auger.tools.host_cmd import auto_detect_tools
                tools = auto_detect_tools()
                self.after(0, lambda: setattr(self, '_tools_cache', tools))
                self.after(0, lambda: self._status_var.set(
                    f"Detected {len(tools)} tool(s)"))
            except Exception as e:
                self.after(0, lambda: self._status_var.set(f"Error: {e}"))
        threading.Thread(target=_thread, daemon=True).start()

    def _add_tool_dialog(self):
        """Reuse the Host Tools 'Add Tool' dialog from HostToolsWidget."""
        try:
            from auger.ui.widgets.host_tools import HostToolsWidget
            # Instantiate a hidden dummy just to call its dialog
            dummy = HostToolsWidget.__new__(HostToolsWidget)
            dummy.winfo_id = self.winfo_id
            dummy.after = self.after
            dummy.status_var = tk.StringVar()
            dummy._show_tool_form(None)
        except Exception as e:
            messagebox.showwarning("Add Tool",
                f"Could not open Add Tool dialog:\n{e}\n\n"
                "You can add tools via the Host Tools widget.", parent=self)
