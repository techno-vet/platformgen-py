"""
Artifactory Widget — Browse, pull, push, and run images from JFrog Artifactory.

Credentials are read from ~/.auger/.env:
    ARTIFACTORY_URL             https://artifactory.helix.gsa.gov
    ARTIFACTORY_USERNAME        your username
    ARTIFACTORY_IDENTITY_TOKEN  (preferred) identity token
    ARTIFACTORY_API_KEY         (fallback)
    ARTIFACTORY_PASSWORD        (fallback)
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext, simpledialog
import threading
import os
import json
import base64
import urllib.request
import urllib.parse
import subprocess
from pathlib import Path
from dotenv import load_dotenv
from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu, auger_home as _auger_home

BG    = '#1e1e1e'
BG2   = '#252526'
BG3   = '#2d2d2d'
FG    = '#e0e0e0'
FG2   = '#888888'
ACCENT  = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR   = '#f44747'
SUCCESS = '#4ec9b0'
WARN    = '#ce9178'

PACKAGE_ICONS = {'Docker': 'Docker', 'Maven': 'Maven', 'Npm': 'NPM',
                 'Generic': 'Files', 'Pypi': 'PyPI', 'Helm': 'Helm'}


def _load_env() -> dict:
    env_file = _auger_home() / '.auger' / '.env'
    load_dotenv(env_file, override=True)
    return {
        'url':      os.getenv('ARTIFACTORY_URL', '').rstrip('/'),
        'username': os.getenv('ARTIFACTORY_USERNAME', ''),
        'password': (os.getenv('ARTIFACTORY_IDENTITY_TOKEN') or
                     os.getenv('ARTIFACTORY_API_KEY') or
                     os.getenv('ARTIFACTORY_PASSWORD', '')),
    }



class ArtifactoryClient:
    """Lightweight Artifactory REST API client (no external deps)."""

    def __init__(self):
        cfg = _load_env()
        self.base_url = cfg['url']
        self.api_base = f"{self.base_url}/artifactory"
        creds = base64.b64encode(f"{cfg['username']}:{cfg['password']}".encode()).decode()
        self._headers = {
            'Authorization': f'Basic {creds}',
            'Content-Type': 'application/json',
        }

    def _get(self, path: str, timeout: int = 15) -> dict | list:
        req = urllib.request.Request(f"{self.api_base}{path}", headers=self._headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())

    def list_repos(self) -> list:
        return self._get('/api/repositories')

    def list_docker_images(self, repo: str) -> list:
        data = self._get(f'/api/docker/{repo}/v2/_catalog', timeout=20)
        return sorted(data.get('repositories', []))

    def list_docker_tags(self, repo: str, image: str) -> list:
        data = self._get(f'/api/docker/{repo}/v2/{image}/tags/list', timeout=15)
        return sorted(data.get('tags', []) or [], reverse=True)

    def storage_children(self, repo: str, path: str = '/') -> list:
        norm = path.lstrip('/')
        endpoint = f'/api/storage/{repo}/{norm}' if norm else f'/api/storage/{repo}/'
        data = self._get(endpoint, timeout=15)
        return data.get('children', [])

    def full_image_ref(self, repo: str, image: str, tag: str) -> str:
        host = self.base_url.replace('https://', '').replace('http://', '')
        return f"{host}/{repo}/{image}:{tag}"


class ArtifactoryWidget(tk.Frame):
    """Browse Artifactory repos, pull/push Docker images, exec into containers."""

    WIDGET_NAME  = "artifactory"
    WIDGET_TITLE = "Artifactory"
    WIDGET_ICON  = "AF"
    WIDGET_ICON_NAME = "artifactory"

    def __init__(self, parent, context_builder_callback=None, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self.context_builder_callback = context_builder_callback
        self._client = None
        self._docker_process = None
        self._selected_image = None   # persists across listbox focus changes
        self._selected_tag = None
        self._icons = {}
        self._create_ui()
        self.after(100, self._connect)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _create_ui(self):
        # Pre-create icons (must happen after Tk root exists)
        for name in ('refresh', 'pull', 'push', 'bash', 'copy', 'download',
                     'folder', 'file', 'add', 'delete', 'error', 'check',
                     'artifactory'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        # Header
        hdr = tk.Frame(self, bg=BG2)
        hdr.pack(fill=tk.X, padx=5, pady=(5, 0))
        _ico_hdr = self._icons.get('artifactory')
        if _ico_hdr:
            tk.Label(hdr, image=_ico_hdr, bg=BG2).pack(side=tk.LEFT, padx=(10, 4), pady=8)
        tk.Label(hdr, text="Artifactory", font=('Segoe UI', 13, 'bold'),
                 fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, padx=(0, 6), pady=8)
        self._status_var = tk.StringVar(value="Connecting...")
        tk.Label(hdr, textvariable=self._status_var, font=('Segoe UI', 9),
                 fg=FG2, bg=BG2).pack(side=tk.LEFT, padx=6)
        tk.Button(hdr, text=" Refresh", image=self._icons.get('refresh'),
                  compound=tk.LEFT, command=self._connect,
                  bg=BG3, fg=FG, font=('Segoe UI', 9), relief=tk.FLAT,
                  padx=10, pady=3).pack(side=tk.RIGHT, padx=8, pady=4)

        # Notebook
        self._nb = ttk.Notebook(self)
        self._nb.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        style = ttk.Style()
        style.configure('TNotebook', background=BG2)
        style.configure('TNotebook.Tab', background=BG3, foreground=FG, padding=[10, 4])

        self._create_repos_tab()
        self._create_docker_tab()
        self._create_browse_tab()
        self._create_terminal_tab()

    # ── Repos Tab ──────────────────────────────────────────────────────────────

    def _create_repos_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        self._nb.add(frame, text="Repositories")

        # Filter bar
        top = tk.Frame(frame, bg=BG2)
        top.pack(fill=tk.X, padx=5, pady=4)
        tk.Label(top, text="Filter:", bg=BG2, fg=FG, font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=4)
        self._repo_filter = tk.StringVar()
        self._repo_filter.trace_add('write', lambda *_: self._filter_repos())
        tk.Entry(top, textvariable=self._repo_filter, bg=BG3, fg=FG,
                 font=('Segoe UI', 9), relief=tk.FLAT, width=30).pack(side=tk.LEFT, padx=4)

        # Tree
        cols = ('Type', 'Package', 'URL')
        self._repo_tree = ttk.Treeview(frame, columns=cols, show='headings', selectmode='browse')
        for c, w in zip(cols, (80, 80, 500)):
            self._repo_tree.heading(c, text=c)
            self._repo_tree.column(c, width=w, anchor='w')
        self._repo_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=4)
        add_treeview_menu(self._repo_tree)

        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._repo_tree.yview)
        self._repo_tree.configure(yscrollcommand=sb.set)
        sb.place(relx=1.0, rely=0, relheight=1.0, anchor='ne')
        self._repos_data = []

    def _filter_repos(self):
        q = self._repo_filter.get().lower()
        self._render_repos([r for r in self._repos_data
                            if not q or q in r.get('key', '').lower()
                            or q in r.get('packageType', '').lower()])

    def _render_repos(self, repos):
        self._repo_tree.delete(*self._repo_tree.get_children())
        for r in repos:
            self._repo_tree.insert('', tk.END, values=(
                r.get('type', ''), r.get('packageType', ''), r.get('url', '')
            ), text=r.get('key', ''), iid=r.get('key', ''))

    # ── Docker Tab ─────────────────────────────────────────────────────────────

    def _create_docker_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        self._nb.add(frame, text="Docker Images")

        # Left panel — image/tag browser
        pane = tk.PanedWindow(frame, orient=tk.HORIZONTAL, bg=BG, sashwidth=4)
        pane.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(pane, bg=BG2, width=280)
        pane.add(left, minsize=200)

        # Repo selector
        top = tk.Frame(left, bg=BG2)
        top.pack(fill=tk.X, padx=6, pady=4)
        tk.Label(top, text="Repo:", bg=BG2, fg=FG, font=('Segoe UI', 9)).pack(side=tk.LEFT)
        self._docker_repo_var = tk.StringVar()
        self._docker_repo_combo = ttk.Combobox(top, textvariable=self._docker_repo_var,
                                                state='readonly', width=22)
        self._docker_repo_combo.pack(side=tk.LEFT, padx=4)
        self._docker_repo_combo.bind('<<ComboboxSelected>>', lambda _: self._load_docker_images())

        # Image filter
        tf = tk.Frame(left, bg=BG2)
        tf.pack(fill=tk.X, padx=6, pady=2)
        tk.Label(tf, text="Filter:", bg=BG2, fg=FG, font=('Segoe UI', 9)).pack(side=tk.LEFT)
        self._img_filter = tk.StringVar()
        self._img_filter.trace_add('write', lambda *_: self._filter_images())
        tk.Entry(tf, textvariable=self._img_filter, bg=BG3, fg=FG,
                 font=('Segoe UI', 9), relief=tk.FLAT).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        # Image listbox — exportselection=0 keeps highlight when focus moves to tag list
        self._img_list = tk.Listbox(left, bg=BG3, fg=FG, font=('Consolas', 9),
                                     selectbackground=ACCENT, relief=tk.FLAT,
                                     exportselection=0)
        self._img_list.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        add_listbox_menu(self._img_list)
        self._img_list.bind('<<ListboxSelect>>', lambda _: self._load_tags())
        self._images_data = []

        # Right panel — tag list + actions
        right = tk.Frame(pane, bg=BG)
        pane.add(right, minsize=300)

        tk.Label(right, text="Tags", font=('Segoe UI', 10, 'bold'),
                 fg=ACCENT2, bg=BG).pack(anchor='w', padx=8, pady=(6, 2))

        self._tag_list = tk.Listbox(right, bg=BG3, fg=FG, font=('Consolas', 9),
                                     selectbackground=ACCENT, relief=tk.FLAT, height=12,
                                     exportselection=0)
        self._tag_list.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        add_listbox_menu(self._tag_list)

        # Selected image ref display
        self._img_ref_var = tk.StringVar(value='Select an image and tag')
        tk.Label(right, textvariable=self._img_ref_var, font=('Consolas', 9),
                 fg=WARN, bg=BG, wraplength=380, justify='left').pack(anchor='w', padx=8)

        self._tag_list.bind('<<ListboxSelect>>', self._on_tag_select)

        # Action buttons
        btn_frame = tk.Frame(right, bg=BG)
        btn_frame.pack(fill=tk.X, padx=8, pady=8)

        self._pull_btn = tk.Button(btn_frame, text=" Pull Image",
                                    image=self._icons.get('pull'),
                                    compound=tk.LEFT,
                                    command=self._pull_image,
                                    bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                                    relief=tk.FLAT, padx=12, pady=4)
        self._pull_btn.pack(side=tk.LEFT, padx=2)

        self._push_btn = tk.Button(btn_frame, text=" Push Local Tag",
                                    image=self._icons.get('push'),
                                    compound=tk.LEFT,
                                    command=self._push_image,
                                    bg=BG3, fg=FG, font=('Segoe UI', 9),
                                    relief=tk.FLAT, padx=12, pady=4)
        self._push_btn.pack(side=tk.LEFT, padx=2)

        self._run_btn = tk.Button(btn_frame, text=" Run /bin/bash",
                                   image=self._icons.get('bash'),
                                   compound=tk.LEFT,
                                   command=self._run_bash,
                                   bg=BG3, fg=FG, font=('Segoe UI', 9),
                                   relief=tk.FLAT, padx=12, pady=4)
        self._run_btn.pack(side=tk.LEFT, padx=2)

        # Copy ref button
        tk.Button(btn_frame, text=" Copy Ref",
                  image=self._icons.get('copy'),
                  compound=tk.LEFT,
                  command=self._copy_ref,
                  bg=BG3, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=10, pady=4).pack(side=tk.LEFT, padx=2)

    # ── Browse Tab (non-Docker repos) ──────────────────────────────────────────

    def _create_browse_tab(self):
        """Storage browser for Maven/NPM/Generic repos using /api/storage API."""
        frame = tk.Frame(self._nb, bg=BG)
        self._nb.add(frame, text="Browse Files")

        # Top bar: repo selector + path breadcrumb
        top = tk.Frame(frame, bg=BG2)
        top.pack(fill=tk.X, padx=5, pady=4)
        tk.Label(top, text="Repo:", bg=BG2, fg=FG, font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=4)
        self._browse_repo_var = tk.StringVar()
        self._browse_repo_combo = ttk.Combobox(top, textvariable=self._browse_repo_var,
                                                state='readonly', width=28)
        self._browse_repo_combo.pack(side=tk.LEFT, padx=4)
        self._browse_repo_combo.bind('<<ComboboxSelected>>', lambda _: self._browse_root())
        tk.Button(top, text=" Up", image=self._icons.get('folder'),
                  compound=tk.LEFT, command=self._browse_up,
                  bg=BG3, fg=FG, font=('Segoe UI', 9), relief=tk.FLAT,
                  padx=8, pady=2).pack(side=tk.LEFT, padx=4)
        tk.Button(top, text=" Root", command=self._browse_root,
                  bg=BG3, fg=FG, font=('Segoe UI', 9), relief=tk.FLAT,
                  padx=8, pady=2).pack(side=tk.LEFT, padx=2)

        self._browse_path_var = tk.StringVar(value='/')
        tk.Label(top, textvariable=self._browse_path_var, font=('Consolas', 9),
                 fg=WARN, bg=BG2).pack(side=tk.LEFT, padx=8)

        # Download button (for files)
        self._browse_dl_btn = tk.Button(top, text=" Download URL",
                                         image=self._icons.get('download'),
                                         compound=tk.LEFT,
                                         command=self._browse_copy_url,
                                         bg=ACCENT, fg='white', font=('Segoe UI', 9),
                                         relief=tk.FLAT, padx=10, pady=2,
                                         state=tk.DISABLED)
        self._browse_dl_btn.pack(side=tk.RIGHT, padx=6)

        # Tree view: Name | Size | Modified
        cols = ('Size', 'Modified')
        self._browse_tree = ttk.Treeview(frame, columns=cols, show='tree headings',
                                          selectmode='browse')
        self._browse_tree.heading('#0', text='Name')
        self._browse_tree.column('#0', width=340)
        self._browse_tree.heading('Size', text='Size')
        self._browse_tree.column('Size', width=90, anchor='e')
        self._browse_tree.heading('Modified', text='Modified')
        self._browse_tree.column('Modified', width=160)
        sb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self._browse_tree.yview)
        self._browse_tree.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y, pady=4)
        self._browse_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=4)
        add_treeview_menu(self._browse_tree)
        self._browse_tree.bind('<Double-1>', self._browse_enter)
        self._browse_tree.bind('<<TreeviewSelect>>', self._browse_select)

        self._browse_path = '/'      # current path in repo
        self._browse_items = {}      # iid -> {uri, folder, ...}

    def _browse_root(self):
        self._browse_path = '/'
        self._browse_path_var.set('/')
        repo = self._browse_repo_var.get()
        if repo:
            threading.Thread(target=self._browse_load, args=(repo, '/'), daemon=True).start()

    def _browse_up(self):
        if self._browse_path in ('/', ''):
            return
        parent = '/'.join(self._browse_path.rstrip('/').split('/')[:-1]) or '/'
        self._browse_path = parent
        self._browse_path_var.set(parent or '/')
        repo = self._browse_repo_var.get()
        if repo:
            threading.Thread(target=self._browse_load, args=(repo, parent), daemon=True).start()

    def _browse_enter(self, _event):
        sel = self._browse_tree.selection()
        if not sel:
            return
        iid = sel[0]
        item = self._browse_items.get(iid)
        if not item or not item.get('folder'):
            return
        new_path = (self._browse_path.rstrip('/') + item['uri'])
        self._browse_path = new_path
        self._browse_path_var.set(new_path)
        repo = self._browse_repo_var.get()
        threading.Thread(target=self._browse_load, args=(repo, new_path), daemon=True).start()

    def _browse_select(self, _event):
        sel = self._browse_tree.selection()
        if not sel:
            return
        item = self._browse_items.get(sel[0], {})
        is_file = not item.get('folder', True)
        self._browse_dl_btn.config(state=tk.NORMAL if is_file else tk.DISABLED)

    def _browse_load(self, repo, path):
        self.after(0, lambda: self._status_var.set(f"Browsing {repo}{path}..."))
        try:
            children = self._client.storage_children(repo, path)
            # For files, also try to get metadata
            self.after(0, lambda: self._browse_render(children, path))
            self.after(0, lambda: self._status_var.set(
                f"{len(children)} items in {repo}{path}"))
        except Exception as e:
            self.after(0, lambda: self._status_var.set(f"Browse error: {e}"))

    def _browse_render(self, children, path):
        self._browse_tree.delete(*self._browse_tree.get_children())
        self._browse_items = {}
        # Sort: folders first, then files
        children = sorted(children, key=lambda c: (not c.get('folder', False), c['uri'].lower()))
        for c in children:
            uri = c['uri']          # e.g. "/somefile.jar" or "/somefolder"
            name = uri.lstrip('/')
            is_folder = c.get('folder', False)
            prefix = '[+] ' if is_folder else '    '
            iid = self._browse_tree.insert(
                '', tk.END,
                text=f"{prefix}{name}",
                values=('—' if is_folder else '', ''),
                open=False
            )
            self._browse_items[iid] = c

    def _browse_copy_url(self):
        sel = self._browse_tree.selection()
        if not sel:
            return
        item = self._browse_items.get(sel[0], {})
        if not self._client:
            return
        uri = item.get('uri', '')
        repo = self._browse_repo_var.get()
        url = f"{self._client.api_base}/{repo}{self._browse_path.rstrip('/')}{uri}"
        self.clipboard_clear()
        self.clipboard_append(url)
        self._status_var.set(f"Copied: {url}")

    # ── Terminal Tab ───────────────────────────────────────────────────────────

    def _create_terminal_tab(self):
        frame = tk.Frame(self._nb, bg=BG)
        self._nb.add(frame, text="Output / Terminal")

        toolbar = tk.Frame(frame, bg=BG2)
        toolbar.pack(fill=tk.X, padx=5, pady=4)
        tk.Label(toolbar, text="Output", font=('Segoe UI', 10, 'bold'),
                 fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, padx=8)
        self._op_status = tk.StringVar(value='Ready')
        tk.Label(toolbar, textvariable=self._op_status, font=('Segoe UI', 9),
                 fg=FG2, bg=BG2).pack(side=tk.LEFT, padx=6)
        tk.Button(toolbar, text=" Clear", image=self._icons.get('delete'),
                  compound=tk.LEFT, command=self._clear_terminal,
                  bg=BG3, fg=FG, font=('Segoe UI', 9), relief=tk.FLAT,
                  padx=8, pady=2).pack(side=tk.RIGHT, padx=6)
        self._stop_btn = tk.Button(toolbar, text=" Stop",
                                    image=self._icons.get('error'),
                                    compound=tk.LEFT,
                                    command=self._stop_container,
                                    state=tk.DISABLED,
                                    bg=ERROR, fg='white', font=('Segoe UI', 9, 'bold'),
                                    relief=tk.FLAT, padx=10, pady=2)
        self._stop_btn.pack(side=tk.RIGHT, padx=4)

        self._terminal = scrolledtext.ScrolledText(
            frame, wrap=tk.CHAR, font=('Consolas', 9),
            bg='#0c0c0c', fg='#00ff00', insertbackground='#00ff00',
            relief=tk.FLAT, state=tk.DISABLED
        )
        self._terminal.pack(fill=tk.BOTH, expand=True, padx=5, pady=4)
        make_text_copyable(self._terminal)

        # Command input (for bash sessions)
        inp_frame = tk.Frame(frame, bg=BG)
        inp_frame.pack(fill=tk.X, padx=5, pady=(0, 5))
        tk.Label(inp_frame, text="$", font=('Consolas', 10), bg=BG, fg=SUCCESS).pack(side=tk.LEFT)
        self._cmd_input = tk.Entry(inp_frame, font=('Consolas', 10),
                                    bg=BG3, fg=FG, insertbackground=FG, relief=tk.FLAT)
        self._cmd_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)
        self._cmd_input.bind('<Return>', self._send_cmd)
        tk.Button(inp_frame, text=" Send", image=self._icons.get('add'),
                  compound=tk.LEFT, command=self._send_cmd,
                  bg=ACCENT, fg='white', relief=tk.FLAT, padx=8, pady=2).pack(side=tk.LEFT, padx=4)

    # ── Connection & Data Loading ──────────────────────────────────────────────

    def _connect(self):
        self._status_var.set("Connecting...")
        threading.Thread(target=self._connect_thread, daemon=True).start()

    def _connect_thread(self):
        try:
            self._client = ArtifactoryClient()
            repos = self._client.list_repos()
            self._repos_data = repos
            docker_repos = [r['key'] for r in repos if r.get('packageType') == 'Docker']

            self.after(0, lambda: self._render_repos(repos))
            self.after(0, lambda: self._docker_repo_combo.config(values=docker_repos))
            if docker_repos:
                self.after(0, lambda: self._docker_repo_var.set(docker_repos[0]))
                self.after(0, self._load_docker_images)

            # Populate Browse tab with all repos
            all_keys = [r['key'] for r in repos]
            self.after(0, lambda: self._browse_repo_combo.config(values=all_keys))
            if all_keys:
                non_docker = [r['key'] for r in repos if r.get('packageType') != 'Docker']
                first = non_docker[0] if non_docker else all_keys[0]
                self.after(0, lambda: self._browse_repo_var.set(first))
                self.after(0, self._browse_root)

            self.after(0, lambda: self._status_var.set(
                f"Connected — {len(repos)} repos ({len(docker_repos)} Docker)"))
        except Exception as e:
            self.after(0, lambda: self._status_var.set(f"Error: {e}"))
            self.after(0, lambda: messagebox.showerror(
                "Artifactory", f"Cannot connect:\n{e}\n\nCheck ARTIFACTORY_* in ~/.auger/.env"))

    def _load_docker_images(self):
        repo = self._docker_repo_var.get()
        if not repo or not self._client:
            return
        self._img_list.delete(0, tk.END)
        self._tag_list.delete(0, tk.END)
        self._status_var.set(f"Loading images from {repo}...")
        threading.Thread(target=self._load_images_thread, args=(repo,), daemon=True).start()

    def _load_images_thread(self, repo):
        try:
            images = self._client.list_docker_images(repo)
            self._images_data = images
            self.after(0, lambda: self._render_images(images))
            self.after(0, lambda: self._status_var.set(f"{len(images)} images in {repo}"))
        except Exception as e:
            self.after(0, lambda: self._status_var.set(f"Error: {e}"))

    def _render_images(self, images):
        self._img_list.delete(0, tk.END)
        for img in images:
            self._img_list.insert(tk.END, img)

    def _filter_images(self):
        q = self._img_filter.get().lower()
        filtered = [i for i in self._images_data if not q or q in i.lower()]
        self._render_images(filtered)

    def _load_tags(self):
        sel = self._img_list.curselection()
        if not sel:
            return
        image = self._img_list.get(sel[0])
        self._selected_image = image  # persist so button clicks don't lose it
        repo = self._docker_repo_var.get()
        self._tag_list.delete(0, tk.END)
        self._tag_list.insert(tk.END, 'Loading...')
        threading.Thread(target=self._load_tags_thread, args=(repo, image), daemon=True).start()

    def _load_tags_thread(self, repo, image):
        try:
            tags = self._client.list_docker_tags(repo, image)
            self.after(0, lambda: self._render_tags(tags, repo, image))
        except Exception as e:
            self.after(0, lambda: self._render_tags([f'Error: {e}'], repo, image))

    def _render_tags(self, tags, repo, image):
        self._tag_list.delete(0, tk.END)
        for t in tags:
            self._tag_list.insert(tk.END, t)
        if tags and not tags[0].startswith('Error'):
            self._tag_list.selection_set(0)
            self._selected_tag = tags[0]
            ref = self._client.full_image_ref(repo, image, tags[0])
            self._img_ref_var.set(ref)

    def _on_tag_select(self, _event):
        tag_sel = self._tag_list.curselection()
        if not tag_sel:
            return
        tag = self._tag_list.get(tag_sel[0])
        if tag.startswith('Error') or tag == 'Loading...':
            return
        self._selected_tag = tag
        repo = self._docker_repo_var.get()
        image = self._selected_image
        if image and self._client:
            ref = self._client.full_image_ref(repo, image, tag)
            self._img_ref_var.set(ref)

    def _selected_image_ref(self):
        ref = self._img_ref_var.get()
        return ref if ':' in ref and not ref.startswith('Select') else None

    # ── Actions ────────────────────────────────────────────────────────────────

    def _docker_env(self):
        """Return env dict with DOCKER_CONFIG pointing to writable ~/.auger/.docker."""
        env = os.environ.copy()
        env['DOCKER_CONFIG'] = str(_auger_home() / '.auger' / '.docker')
        return env

    def _docker_login(self):
        """Login to Artifactory registry using writable DOCKER_CONFIG."""
        cfg = _load_env()
        registry = cfg['url'].replace('https://', '').replace('http://', '').rstrip('/')
        if not registry or not cfg['username'] or not cfg['password']:
            return False, 'Missing ARTIFACTORY credentials in ~/.auger/.env'
        r = subprocess.run(
            ['docker', 'login', registry, '-u', cfg['username'], '--password-stdin'],
            input=cfg['password'].encode(), capture_output=True,
            env=self._docker_env()
        )
        if r.returncode == 0:
            return True, f'Logged in to {registry}'
        return False, (r.stderr.decode().strip() or r.stdout.decode().strip())

    def _pull_image(self):
        ref = self._selected_image_ref()
        if not ref:
            messagebox.showwarning("Pull", "Select an image and tag first.")
            return
        self._nb.select(3)
        self._log(f"$ docker pull {ref}\n")
        self._op_status.set("Pulling...")
        threading.Thread(target=self._run_docker_cmd,
                         args=(['docker', 'pull', ref], 'Pull'), daemon=True).start()

    def _push_image(self):
        ref = self._selected_image_ref()
        src = simpledialog.askstring(
            "Push Image",
            "Local image:tag to push to Artifactory\n(leave blank to push selected ref directly):",
            initialvalue='',
            parent=self
        )
        if src is None:
            return
        target = ref
        self._nb.select(3)
        if src and src != target:
            self._log(f"$ docker tag {src} {target}\n")
            r = subprocess.run(['docker', 'tag', src, target], capture_output=True, text=True)
            if r.returncode != 0:
                self._log(f"Tag failed: {r.stderr}\n", error=True)
                return
        self._log(f"$ docker push {target}\n")
        self._op_status.set("Pushing...")
        threading.Thread(target=self._run_docker_cmd,
                         args=(['docker', 'push', target], 'Push'), daemon=True).start()

    def _run_docker_cmd(self, cmd: list, label: str):
        """Run a docker command directly (socket is mounted), stream output to terminal."""
        # Login first
        ok, msg = self._docker_login()
        self.after(0, lambda m=msg: self._log(f'  {m}\n'))
        if not ok:
            self.after(0, lambda m=msg: self._log(f'Login failed: {m}\n', error=True))
            self.after(0, lambda: self._op_status.set('Login failed'))
            return
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, bufsize=1, env=self._docker_env())
            for line in proc.stdout:
                self.after(0, lambda l=line.rstrip(): self._log(l + '\n'))
            proc.wait()
            if proc.returncode == 0:
                self.after(0, lambda: self._op_status.set(f'{label} complete'))
                self.after(0, lambda: self._log(f'[Done]\n'))
            else:
                self.after(0, lambda: self._op_status.set(f'{label} failed'))
                self.after(0, lambda: self._log(f'[Exit {proc.returncode}]\n', error=True))
        except Exception as e:
            self.after(0, lambda: self._log(f'Error: {e}\n', error=True))
            self.after(0, lambda: self._op_status.set(f'Error'))

    def _run_bash(self):
        ref = self._selected_image_ref()
        if not ref:
            messagebox.showwarning("Run", "Select an image and tag first.")
            return
        if self._docker_process:
            messagebox.showwarning("Run", "A container is already running. Stop it first.")
            return
        self._nb.select(3)
        self._log(f"$ docker run -i --rm --entrypoint /bin/bash {ref}\n")
        self._op_status.set("Starting container...")
        self._run_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)
        threading.Thread(target=self._run_bash_thread, args=(ref,), daemon=True).start()

    def _run_bash_thread(self, ref):
        ok, msg = self._docker_login()
        self.after(0, lambda m=msg: self._log(f'  {m}\n'))
        try:
            proc = subprocess.Popen(
                ['docker', 'run', '-i', '--rm', '--entrypoint', '/bin/bash', ref],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                env=self._docker_env()
            )
            self._docker_process = proc
            self.after(0, lambda: self._op_status.set('Container running — type commands below'))
            # Send initial prompt setup
            proc.stdin.write(b"export PS1='container# '\necho '=== Ready ==='\n")
            proc.stdin.flush()
            os.set_blocking(proc.stdout.fileno(), False)
            import time
            while proc.poll() is None:
                try:
                    data = proc.stdout.read(4096)
                    if data:
                        text = data.decode('utf-8', errors='replace')
                        self.after(0, lambda t=text: self._log(t))
                except BlockingIOError:
                    time.sleep(0.05)
            # Drain remaining output
            try:
                rest = proc.stdout.read()
                if rest:
                    self.after(0, lambda t=rest.decode('utf-8', errors='replace'): self._log(t))
            except Exception:
                pass
        except Exception as e:
            self.after(0, lambda: self._log(f'Error: {e}\n', error=True))
        finally:
            self._docker_process = None
            self.after(0, lambda: self._run_btn.config(state=tk.NORMAL))
            self.after(0, lambda: self._stop_btn.config(state=tk.DISABLED))
            self.after(0, lambda: self._op_status.set('Container exited'))
            self.after(0, lambda: self._log('\n[Container exited]\n'))

    def _copy_ref(self):
        ref = self._selected_image_ref()
        if ref:
            self.clipboard_clear()
            self.clipboard_append(ref)
            self._status_var.set(f"Copied: {ref}")

    def _stop_container(self):
        if self._docker_process:
            try:
                self._docker_process.terminate()
            except Exception:
                pass
        self._docker_process = None
        self._stop_btn.config(state=tk.DISABLED)
        self._run_btn.config(state=tk.NORMAL)
        self._op_status.set('Ready')
        self._log('\n[Stopped]\n')

    def _send_cmd(self, _event=None):
        cmd = self._cmd_input.get().strip()
        if not cmd:
            return
        self._cmd_input.delete(0, tk.END)
        self._log(f"$ {cmd}\n")
        if self._docker_process and self._docker_process.poll() is None:
            try:
                self._docker_process.stdin.write((cmd + '\n').encode())
                self._docker_process.stdin.flush()
            except Exception as e:
                self._log(f'Send error: {e}\n', error=True)
        else:
            self._log('  (no container running)\n', error=True)

    def _log(self, text: str, error: bool = False):
        self._terminal.config(state=tk.NORMAL)
        color = ERROR if error else '#00ff00'
        tag = 'err' if error else 'ok'
        self._terminal.tag_config(tag, foreground=color)
        self._terminal.insert(tk.END, text, tag)
        self._terminal.see(tk.END)
        self._terminal.config(state=tk.DISABLED)

    def _clear_terminal(self):
        self._terminal.config(state=tk.NORMAL)
        self._terminal.delete('1.0', tk.END)
        self._terminal.config(state=tk.DISABLED)
