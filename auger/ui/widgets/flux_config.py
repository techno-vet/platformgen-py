"""
Flux Config Widget - Browse, view, and update image tags in Flux HelmRelease config repos.

Reads two flux repos (configurable via ~/.auger/.env):
    FLUX_REPO_DEV   path to assist-flux-config        (default: ~/repos/assist-flux-config)
    FLUX_REPO_PROD  path to assist-prod-flux-config   (default: ~/repos/assist-prod-flux-config)

Features:
  - Browse env/namespace/service file tree for dev and prod repos
  - View all image tags per container in a HelmRelease YAML
  - Edit tags inline and write back (preserves YAML comments incl. imagepolicy)
  - Toggle .yaml ↔ .ignore (Airflow undeploy/redeploy pattern)

⚠️  PRODUCTION SAFETY RULE:
    NEVER commit, push, or merge changes to the PROD flux repo (assist-prod-flux-config)
    without EXPLICITLY asking the user for confirmation first.
    Lower environments (dev/staging/test) are lower risk but still confirm before pushing.

  - Git pull, status, diff, commit, push
"""

import os
import re
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, simpledialog, ttk

import yaml
from dotenv import load_dotenv

from auger.ui import icons as _icons
from auger.ui.utils import make_text_copyable, bind_mousewheel, add_listbox_menu, add_treeview_menu, auger_home as _auger_home

# ── Colour palette (matches platform dark theme) ──────────────────────────────
BG      = '#1e1e1e'
BG2     = '#252526'
BG3     = '#2d2d2d'
FG      = '#e0e0e0'
FG2     = '#888888'
ACCENT  = '#007acc'
ACCENT2 = '#4ec9b0'
ERROR   = '#f44747'
SUCCESS = '#4ec9b0'
WARN    = '#ce9178'
IGNORE_CLR = '#888888'


# ── Repo defaults ─────────────────────────────────────────────────────────────

def _load_repo_paths() -> dict:
    load_dotenv(_auger_home() / '.auger' / '.env', override=True)
    return {
        'dev':  Path(os.getenv('FLUX_REPO_DEV',  str(_auger_home() / 'repos' / 'assist-flux-config'))),
        'prod': Path(os.getenv('FLUX_REPO_PROD', str(_auger_home() / 'repos' / 'assist-prod-flux-config'))),
    }


def _discover_environments(repos: dict) -> list[tuple[str, str, Path, Path]]:
    """
    Scan repos and return list of (label, key, repo_root, env_dir) for each
    available environment, ordered: production first, then dev, staging, test.
    """
    envs = []

    # Prod repo: core/production
    prod_env = repos['prod'] / 'core' / 'production'
    if prod_env.exists():
        envs.append(('Production', 'production', repos['prod'], prod_env))

    # Dev repo: core/{development,staging,test}
    order = ['development', 'staging', 'test']
    labels = {'development': 'Development', 'staging': 'Staging', 'test': 'Test'}
    for name in order:
        env_dir = repos['dev'] / 'core' / name
        if env_dir.exists():
            envs.append((labels[name], name, repos['dev'], env_dir))

    return envs


# ── YAML helpers ──────────────────────────────────────────────────────────────

def _extract_image_entries(data: dict, path: str = '') -> list[dict]:
    """Recursively walk a parsed YAML dict and return all image{tag,repository} leaves."""
    results = []
    if isinstance(data, dict):
        if 'image' in data and isinstance(data['image'], dict):
            img = data['image']
            if 'tag' in img:
                results.append({
                    'path':       path,
                    'repository': img.get('repository', ''),
                    'tag':        str(img.get('tag', '')),
                })
        for k, v in data.items():
            results += _extract_image_entries(v, f'{path}.{k}' if path else k)
    return results


def _update_tag_in_file(file_path: Path, old_tag: str, new_tag: str) -> bool:
    """
    Replace `tag: <old_tag>` with `tag: <new_tag>` in file, preserving trailing
    comments (e.g. imagepolicy annotations).  Uses exact string match so it is
    safe even when multiple containers share a file.
    """
    text = file_path.read_text()
    # Match lines like:   tag: release-XXXX   or   tag: release-XXXX # comment
    pattern = re.compile(
        r'^(?P<indent>\s*)tag:\s*' + re.escape(old_tag) + r'(?P<comment>.*)$',
        re.MULTILINE
    )
    if not pattern.search(text):
        return False
    new_text = pattern.sub(r'\g<indent>tag: ' + new_tag + r'\g<comment>', text)
    file_path.write_text(new_text)
    return True


def _toggle_ignore(file_path: Path) -> Path:
    """Rename .yaml → .ignore or .ignore → .yaml and return new path."""
    if file_path.suffix == '.yaml':
        new_path = file_path.with_suffix('.ignore')
    elif file_path.suffix == '.ignore':
        new_path = file_path.with_suffix('.yaml')
    else:
        raise ValueError(f"Unexpected suffix: {file_path.suffix}")
    file_path.rename(new_path)
    return new_path


def _git(repo: Path, *args) -> tuple[int, str]:
    """Run a git command in repo, return (returncode, combined output)."""
    result = subprocess.run(
        ['git', '-C', str(repo)] + list(args),
        capture_output=True, text=True
    )
    out = (result.stdout or '') + (result.stderr or '')
    return result.returncode, out.strip()


def _repair_remote_ref_permissions(repo: Path, git_output: str) -> bool:
    """Delete stale remote ref/log files that git can't update due to ownership."""
    repaired = False
    if not git_output:
        return repaired

    branch_names = set()
    patterns = [
        r"refs/remotes/origin/([^\s':]+)",
        r"-> origin/([^\s]+)",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, git_output):
            branch_names.add(match)

    for branch in branch_names:
        for rel in (
            Path('.git/logs/refs/remotes/origin') / branch,
            Path('.git/refs/remotes/origin') / branch,
        ):
            try:
                path = repo / rel
                if path.exists():
                    path.unlink()
                    repaired = True
            except OSError:
                pass

    return repaired


def _git_fetch_no_merge(repo: Path) -> tuple[int, str]:
    """Fetch remote updates without merging local branches.

    Retries once if fetch fails because stale remote ref logs were created by a
    different uid and can be removed safely.
    """
    rc, out = _git(repo, 'fetch', '--no-write-fetch-head')
    if rc == 0 or 'Permission denied' not in (out or ''):
        return rc, out

    if _repair_remote_ref_permissions(repo, out):
        rc, out = _git(repo, 'fetch', '--no-write-fetch-head')
    return rc, out


# ── Icon ─────────────────────────────────────────────────────────────────────

def make_icon(size=18, color='#4fc3f7'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    cx = s2 // 2
    # Flux: two curved sync arrows forming a continuous cycle
    d.arc([m*2, m*2, s2 - m*2, s2 - m*2], start=300, end=60, fill=color, width=m*2)
    tip_x, tip_y = cx + int((cx - m*3) * 0.87), m*3 + m
    d.polygon([
        (tip_x, tip_y - m*2),
        (tip_x + m*2, tip_y + m*2),
        (tip_x - m*2, tip_y + m*2),
    ], fill=color)
    d.arc([m*2, m*2, s2 - m*2, s2 - m*2], start=120, end=240, fill=color, width=m*2)
    tip_x2, tip_y2 = cx - int((cx - m*3) * 0.87), s2 - m*3 - m
    d.polygon([
        (tip_x2, tip_y2 + m*2),
        (tip_x2 + m*2, tip_y2 - m*2),
        (tip_x2 - m*2, tip_y2 - m*2),
    ], fill=color)
    return img.resize((size, size), Image.LANCZOS)


# ── Main widget ───────────────────────────────────────────────────────────────


class FluxConfigWidget(tk.Frame):
    """Browse and update Flux HelmRelease config files."""

    WIDGET_NAME       = 'flux_config'
    WIDGET_TITLE      = 'Flux Config'
    WIDGET_ICON       = '⚡'
    WIDGET_ICON_NAME  = 'flux'
    WIDGET_ICON_FUNC  = staticmethod(make_icon)
    WIDGET_SKIP_AUTO_OPEN = True

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._repos   = _load_repo_paths()
        self._envs    = _discover_environments(self._repos)  # [(label, key, repo_root, env_dir)]
        self._current_file: Path | None = None
        self._tag_rows: list[dict] = []
        self._icons: dict = {}
        self._all_file_items: dict = {}   # iid → Path
        self._dir_items:      dict = {}   # iid → (directory Path, repo_root Path)
        self._create_ui()
        self.after(100, self._refresh_tree)

    # ── UI construction ───────────────────────────────────────────────────────

    def _create_ui(self):
        for name in ('refresh', 'edit', 'play', 'add', 'delete', 'terminal', 'tools'):
            try:
                self._icons[name] = _icons.get(name, 16)
            except Exception:
                pass

        # ── Header ────────────────────────────────────────────────────────────
        header = tk.Frame(self, bg=BG2)
        header.pack(fill=tk.X, padx=5, pady=(5, 0))
        tk.Label(header, text='Flux Config', font=('Segoe UI', 13, 'bold'),
                 fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, padx=10, pady=8)
        tk.Label(header, text='Browse and update Flux HelmRelease image tags',
                 font=('Segoe UI', 9), fg=FG2, bg=BG2).pack(side=tk.LEFT, padx=5)

        # ── Toolbar ───────────────────────────────────────────────────────────
        toolbar = tk.Frame(self, bg=BG3)
        toolbar.pack(fill=tk.X, padx=5, pady=2)

        tk.Button(toolbar, text=' Git Fetch All', image=self._icons.get('refresh'),
                  compound=tk.LEFT, command=self._git_pull,
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=10, pady=3).pack(side=tk.LEFT, padx=8, pady=4)

        tk.Button(toolbar, text=' Refresh', image=self._icons.get('refresh'),
                  compound=tk.LEFT, command=self._refresh_tree,
                  bg=BG2, fg=FG, font=('Segoe UI', 9),
                  relief=tk.FLAT, padx=10, pady=3).pack(side=tk.LEFT, padx=2, pady=4)

        # Status label
        self._status_var = tk.StringVar(value='')
        tk.Label(toolbar, textvariable=self._status_var, bg=BG3, fg=FG2,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=10)

        # Repo path display (shows repo of currently selected file)
        self._path_var = tk.StringVar(value='')
        tk.Label(toolbar, textvariable=self._path_var, bg=BG3, fg=FG2,
                 font=('Consolas', 8)).pack(side=tk.RIGHT, padx=8)

        # ── Main paned area ───────────────────────────────────────────────────
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # Left: file tree
        left = tk.Frame(paned, bg=BG2)
        paned.add(left, weight=1)
        self._build_tree(left)

        # Right: tabbed detail panel
        right = tk.Frame(paned, bg=BG)
        paned.add(right, weight=3)
        self._build_detail(right)

    def _build_tree(self, parent):
        tk.Label(parent, text='Files', font=('Segoe UI', 10, 'bold'),
                 fg=ACCENT2, bg=BG2).pack(anchor=tk.W, padx=8, pady=(6, 2))

        # Search filter
        filter_frame = tk.Frame(parent, bg=BG2)
        filter_frame.pack(fill=tk.X, padx=4, pady=2)
        self._filter_var = tk.StringVar()
        self._filter_var.trace_add('write', lambda *_: self._apply_filter())
        tk.Entry(filter_frame, textvariable=self._filter_var,
                 bg=BG3, fg=FG, insertbackground=FG, font=('Consolas', 9),
                 relief=tk.FLAT).pack(fill=tk.X, padx=2)

        tree_frame = tk.Frame(parent, bg=BG2)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        style = ttk.Style()
        style.configure('Flux.Treeview', background=BG3, fieldbackground=BG3,
                        foreground=FG, font=('Consolas', 9), rowheight=20)
        style.configure('Flux.Treeview.Heading', background=BG2, foreground=ACCENT2,
                        font=('Segoe UI', 9, 'bold'))
        style.map('Flux.Treeview', background=[('selected', ACCENT)])

        self._tree = ttk.Treeview(tree_frame, style='Flux.Treeview', show='tree')
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._tree.pack(fill=tk.BOTH, expand=True)
        add_treeview_menu(self._tree)

        self._tree.tag_configure('ignore', foreground=IGNORE_CLR)
        self._tree.tag_configure('yaml',   foreground=FG)
        self._tree.tag_configure('env',    foreground=ACCENT2, font=('Segoe UI', 9, 'bold'))
        self._tree.tag_configure('ns',     foreground=WARN)

        self._tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self._tree.bind('<Double-1>', self._on_tree_double_click)
        self._tree.bind('<<TreeviewOpen>>', self._on_tree_open)  # lazy expand

    def _build_detail(self, parent):
        self._notebook = ttk.Notebook(parent)
        self._notebook.pack(fill=tk.BOTH, expand=True)

        # ── Tab 1: Tags ────────────────────────────────────────────────────────
        self._tags_tab = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(self._tags_tab, text='  Image Tags  ')
        self._build_tags_tab(self._tags_tab)

        # ── Tab 2: YAML viewer ─────────────────────────────────────────────────
        self._yaml_tab = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(self._yaml_tab, text='  YAML  ')
        self._yaml_text = scrolledtext.ScrolledText(
            self._yaml_tab, bg=BG3, fg=FG, insertbackground=FG,
            font=('Consolas', 9), relief=tk.FLAT, wrap=tk.NONE)
        self._yaml_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        make_text_copyable(self._yaml_text)

        # ── Tab 3: Git ─────────────────────────────────────────────────────────
        self._git_tab = tk.Frame(self._notebook, bg=BG)
        self._notebook.add(self._git_tab, text='  Git  ')
        self._build_git_tab(self._git_tab)

    def _build_tags_tab(self, parent):
        # File action bar (shows when a file is loaded)
        self._file_action_bar = tk.Frame(parent, bg=BG2)
        self._file_action_bar.pack(fill=tk.X, padx=5, pady=(5, 0))

        self._file_label_var = tk.StringVar(value='Select a file from the tree')
        tk.Label(self._file_action_bar, textvariable=self._file_label_var,
                 font=('Consolas', 9), fg=ACCENT2, bg=BG2).pack(side=tk.LEFT, padx=8, pady=6)

        self._toggle_btn = tk.Button(
            self._file_action_bar, text='Toggle .yaml/.ignore',
            command=self._toggle_ignore, bg=WARN, fg='black',
            font=('Segoe UI', 9), relief=tk.FLAT, padx=10, pady=3)
        self._toggle_btn.pack(side=tk.RIGHT, padx=6, pady=4)
        self._toggle_btn.config(state=tk.DISABLED)

        # Tags table
        cols_frame = tk.Frame(parent, bg=BG2)
        cols_frame.pack(fill=tk.X, padx=5, pady=2)
        for col, width, anchor in [
            ('Container / Path', 220, 'w'),
            ('Current Tag', 320, 'w'),
            ('New Tag', 320, 'w'),
        ]:
            tk.Label(cols_frame, text=col, width=width//7, bg=BG2, fg=ACCENT2,
                     font=('Segoe UI', 9, 'bold'), anchor=anchor).pack(side=tk.LEFT, padx=4)

        # Scrollable rows area
        canvas_frame = tk.Frame(parent, bg=BG)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=2)

        self._canvas = tk.Canvas(canvas_frame, bg=BG3, highlightthickness=0)
        vsb = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._tags_inner = tk.Frame(self._canvas, bg=BG3)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=self._tags_inner, anchor='nw')
        self._tags_inner.bind('<Configure>',
            lambda e: self._canvas.configure(scrollregion=self._canvas.bbox('all')))
        self._canvas.bind('<Configure>',
            lambda e: self._canvas.itemconfig(self._canvas_window, width=e.width))

        # Save all / Save selected
        btn_bar = tk.Frame(parent, bg=BG2)
        btn_bar.pack(fill=tk.X, padx=5, pady=4)
        tk.Button(btn_bar, text='Apply All Tag Updates', command=self._apply_all_tags,
                  bg=SUCCESS, fg='black', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=12, pady=4).pack(side=tk.LEFT, padx=6, pady=4)
        tk.Label(btn_bar, text='(leave New Tag blank to skip)',
                 fg=FG2, bg=BG2, font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=4)

    def _build_git_tab(self, parent):
        toolbar = tk.Frame(parent, bg=BG2)
        toolbar.pack(fill=tk.X, padx=5, pady=(5, 2))

        for label, cmd in [
            ('Status', self._git_status),
            ('Diff',   self._git_diff),
            ('Fetch',  self._git_pull),
        ]:
            tk.Button(toolbar, text=label, command=cmd,
                      bg=BG3, fg=FG, font=('Segoe UI', 9),
                      relief=tk.FLAT, padx=10, pady=3).pack(side=tk.LEFT, padx=4, pady=4)

        # Commit area
        commit_frame = tk.LabelFrame(parent, text='  Commit  ', bg=BG2, fg=ACCENT2,
                                     font=('Segoe UI', 9, 'bold'), relief=tk.FLAT,
                                     padx=8, pady=6)
        commit_frame.pack(fill=tk.X, padx=5, pady=4)
        tk.Label(commit_frame, text='Message:', bg=BG2, fg=FG,
                 font=('Segoe UI', 9)).pack(anchor=tk.W)
        self._commit_msg = tk.Entry(commit_frame, bg=BG3, fg=FG,
                                    insertbackground=FG, font=('Consolas', 9),
                                    relief=tk.FLAT)
        self._commit_msg.pack(fill=tk.X, pady=(2, 6))
        self._commit_msg.insert(0, 'chore: update image tags')

        btn_row = tk.Frame(commit_frame, bg=BG2)
        btn_row.pack(fill=tk.X)
        tk.Button(btn_row, text='Commit', command=self._git_commit,
                  bg=ACCENT, fg='white', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=12, pady=3).pack(side=tk.LEFT, padx=4)
        tk.Button(btn_row, text='Commit + Push', command=self._git_commit_push,
                  bg=SUCCESS, fg='black', font=('Segoe UI', 9, 'bold'),
                  relief=tk.FLAT, padx=12, pady=3).pack(side=tk.LEFT, padx=4)

        # Output console
        self._git_output = scrolledtext.ScrolledText(
            parent, bg=BG3, fg=ACCENT2, insertbackground=FG,
            font=('Consolas', 9), relief=tk.FLAT, height=18)
        self._git_output.pack(fill=tk.BOTH, expand=True, padx=5, pady=4)
        make_text_copyable(self._git_output)
        self._git_output.tag_configure('err',  foreground=ERROR)
        self._git_output.tag_configure('ok',   foreground=SUCCESS)
        self._git_output.tag_configure('warn', foreground=WARN)
        self._git_output.tag_configure('head', foreground=ACCENT2,
                                       font=('Consolas', 9, 'bold'))

    # ── Tree management ───────────────────────────────────────────────────────

    def _repo_for_file(self, file_path: Path) -> Path:
        """Return the git repo root that owns the given file."""
        for _label, _key, repo_root, env_dir in self._envs:
            try:
                file_path.relative_to(repo_root)
                return repo_root
            except ValueError:
                pass
        return self._repos['prod']

    def _repo_path(self) -> Path:
        """Return repo root for currently selected file, or prod as fallback."""
        if self._current_file:
            return self._repo_for_file(self._current_file)
        return self._repos['prod']

    # Colour per environment tier (for top-level tree nodes)
    _ENV_COLORS = {
        'production':  '#f44747',   # red
        'staging':     '#f0c040',   # yellow
        'development': '#4ec9b0',   # teal
        'test':        '#888888',   # grey
    }

    def _refresh_tree(self):
        self._tree.delete(*self._tree.get_children())
        self._all_file_items = {}
        self._dir_items      = {}

        for label, key, repo_root, env_dir in self._envs:
            if not env_dir.exists():
                continue
            color = self._ENV_COLORS.get(key, ACCENT2)
            self._tree.tag_configure(f'top_{key}', foreground=color,
                                     font=('Segoe UI', 10, 'bold'))
            top_iid = self._tree.insert(
                '', tk.END,
                text=f'  {label.upper()}  ({repo_root.name})',
                tags=(f'top_{key}',),
                open=False,
            )
            # Insert placeholder so expand arrow shows immediately
            self._tree.insert(top_iid, tk.END, text='Loading...')
            self._dir_items[top_iid] = (env_dir, repo_root)

        self._status_var.set(f'{len(self._envs)} environments')

    def _populate_children(self, parent_iid: str, directory: Path, repo_root: Path):
        """Populate immediate children of directory into the tree."""
        try:
            entries = sorted(directory.iterdir(),
                             key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        for entry in entries:
            if entry.name.startswith('.') or entry.name.startswith('__'):
                continue
            if entry.is_dir():
                iid = self._tree.insert(parent_iid, tk.END,
                                        text=f'📂 {entry.name}',
                                        tags=('ns',))
                # Placeholder for lazy expand
                self._tree.insert(iid, tk.END, text='Loading...')
                self._dir_items[iid] = (entry, repo_root)
            elif entry.suffix in ('.yaml', '.ignore'):
                tag  = 'ignore' if entry.suffix == '.ignore' else 'yaml'
                icon = '⚫' if entry.suffix == '.ignore' else '📄'
                iid = self._tree.insert(parent_iid, tk.END,
                                        text=f'{icon} {entry.name}', tags=(tag,))
                self._all_file_items[iid] = entry

    def _on_tree_open(self, event=None):
        """Lazy-populate a directory node on first expand."""
        iid = self._tree.focus()
        if iid not in self._dir_items:
            return
        children = self._tree.get_children(iid)
        if not children:
            return
        if 'Loading' not in self._tree.item(children[0], 'text'):
            return  # already populated
        for child in children:
            self._tree.delete(child)
        directory, repo_root = self._dir_items[iid]
        self._populate_children(iid, directory, repo_root)

    def _apply_filter(self):
        q = self._filter_var.get().lower().strip()
        self._refresh_tree_filtered(q)

    def _refresh_tree_filtered(self, query: str):
        if not query:
            self._refresh_tree()
            return
        self._tree.delete(*self._tree.get_children())
        self._all_file_items = {}
        self._dir_items      = {}
        for _label, _key, _repo_root, env_dir in self._envs:
            if not env_dir.exists():
                continue
            for f in sorted(list(env_dir.rglob('*.yaml')) + list(env_dir.rglob('*.ignore'))):
                if query in f.name.lower() or query in str(f).lower():
                    iid = self._tree.insert('', tk.END, text=f.name,
                                            tags=('ignore' if f.suffix == '.ignore' else 'yaml',))
                    self._all_file_items[iid] = f

    # ── File selection ────────────────────────────────────────────────────────

    def _on_tree_select(self, event=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid not in self._all_file_items:
            return
        self._load_file(self._all_file_items[iid])

    def _on_tree_double_click(self, event=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in self._all_file_items:
            self._notebook.select(1)  # jump to YAML tab

    def _load_file(self, file_path: Path):
        self._current_file = file_path
        repo = self._repo_for_file(file_path)
        self._file_label_var.set(f'{file_path.name}  ─  {file_path.parent}')
        self._path_var.set(str(repo.name))
        self._toggle_btn.config(state=tk.NORMAL)

        # Load raw text into YAML tab
        try:
            raw = file_path.read_text()
        except Exception as e:
            raw = f'Error reading file: {e}'
        self._yaml_text.config(state=tk.NORMAL)
        self._yaml_text.delete('1.0', tk.END)
        self._yaml_text.insert('1.0', raw)

        # Parse and show tags
        self._tag_rows = []
        for w in self._tags_inner.winfo_children():
            w.destroy()

        if file_path.suffix == '.ignore':
            tk.Label(self._tags_inner,
                     text='[IGNORED] This file is disabled — rename to .yaml to re-enable',
                     fg=WARN, bg=BG3, font=('Segoe UI', 10),
                     pady=20).pack(padx=10, pady=20)
            return

        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError as e:
            tk.Label(self._tags_inner, text=f'YAML parse error:\n{e}',
                     fg=ERROR, bg=BG3, font=('Consolas', 9)).pack(padx=10, pady=10)
            return

        if not isinstance(data, dict) or data.get('kind') != 'HelmRelease':
            tk.Label(self._tags_inner, text='Not a HelmRelease file.',
                     fg=FG2, bg=BG3, font=('Segoe UI', 9)).pack(padx=10, pady=20)
            return

        entries = _extract_image_entries(data.get('spec', {}).get('values', {}))
        if not entries:
            tk.Label(self._tags_inner, text='No image tags found in this file.',
                     fg=FG2, bg=BG3, font=('Segoe UI', 9)).pack(padx=10, pady=20)
            return

        for idx, entry in enumerate(entries):
            row_bg = BG3 if idx % 2 == 0 else BG2
            row = tk.Frame(self._tags_inner, bg=row_bg)
            row.pack(fill=tk.X, padx=2, pady=1)

            # Container path (last 2 segments for readability)
            parts = entry['path'].strip('.').split('.')
            short = '.'.join(parts[-3:]) if len(parts) >= 3 else entry['path']
            tk.Label(row, text=short, bg=row_bg, fg=ACCENT2,
                     font=('Consolas', 9), width=28, anchor='w').pack(side=tk.LEFT, padx=6, pady=4)

            # Current tag (truncated with tooltip)
            cur_tag = entry['tag']
            display_tag = cur_tag if len(cur_tag) <= 45 else cur_tag[:42] + '…'
            tk.Label(row, text=display_tag, bg=row_bg, fg=FG,
                     font=('Consolas', 9), width=40, anchor='w').pack(side=tk.LEFT, padx=4)

            # New tag entry
            new_var = tk.StringVar()
            tk.Entry(row, textvariable=new_var, bg=BG, fg=FG,
                     insertbackground=FG, font=('Consolas', 9), width=42,
                     relief=tk.FLAT).pack(side=tk.LEFT, padx=4, pady=3)

            self._tag_rows.append({**entry, 'new_var': new_var})

    # ── Tag updates ───────────────────────────────────────────────────────────

    def _apply_all_tags(self):
        if not self._current_file:
            messagebox.showwarning('No File', 'Select a file first.')
            return
        updated = 0
        errors = []
        for row in self._tag_rows:
            new_tag = row['new_var'].get().strip()
            if not new_tag or new_tag == row['tag']:
                continue
            ok = _update_tag_in_file(self._current_file, row['tag'], new_tag)
            if ok:
                row['tag'] = new_tag
                updated += 1
            else:
                errors.append(f"Could not find tag: {row['tag'][:40]}")
        if updated:
            self._status_var.set(f'✅ Updated {updated} tag(s)')
            self._load_file(self._current_file)  # reload to show new state
            self._git_status()
        if errors:
            messagebox.showerror('Update Errors', '\n'.join(errors))
        if not updated and not errors:
            self._status_var.set('No changes — New Tag fields were empty or unchanged')

    # ── Toggle .yaml / .ignore ────────────────────────────────────────────────

    def _toggle_ignore(self):
        if not self._current_file:
            return
        try:
            new_path = _toggle_ignore(self._current_file)
            self._current_file = new_path
            self._status_var.set(
                f'{"⚫ Disabled" if new_path.suffix == ".ignore" else "✅ Enabled"}: {new_path.name}')
            self._refresh_tree()
            self._load_file(new_path)
        except Exception as e:
            messagebox.showerror('Toggle Error', str(e))

    # ── Git operations ────────────────────────────────────────────────────────

    def _git_write(self, text: str, tag: str = ''):
        self._git_output.config(state=tk.NORMAL)
        if tag:
            self._git_output.insert(tk.END, text + '\n', tag)
        else:
            self._git_output.insert(tk.END, text + '\n')
        self._git_output.see(tk.END)

    def _git_clear(self):
        self._git_output.config(state=tk.NORMAL)
        self._git_output.delete('1.0', tk.END)

    def _git_run_async(self, label: str, *args):
        self._notebook.select(2)
        self._git_clear()
        self._git_write(f'$ git {" ".join(args)}', 'head')
        repo = self._repo_path()

        def _run():
            rc, out = _git(repo, *args)
            tag = 'ok' if rc == 0 else 'err'
            self.after(0, lambda: self._git_write(out or '(no output)', tag))
            status = f'✅ {label}' if rc == 0 else f'❌ {label} failed'
            self.after(0, lambda: self._status_var.set(status))

        threading.Thread(target=_run, daemon=True).start()

    def _git_pull(self):
        """Fetch all flux repos (prod + dev/lower) without merging."""
        self._notebook.select(2)
        self._git_clear()
        repos_to_pull = {self._repos['prod'], self._repos['dev']}

        def _run():
            any_err = False
            for repo in sorted(repos_to_pull, key=lambda p: p.name):
                self.after(0, lambda r=repo: self._git_write(f'\n── {r.name} ──', 'head'))
                self.after(0, lambda: self._git_write('$ git fetch --no-write-fetch-head', 'head'))
                rc, out = _git_fetch_no_merge(repo)
                self.after(0, lambda o=out, t=('ok' if rc == 0 else 'err'): self._git_write(o or '(up to date)', t))
                if rc != 0:
                    any_err = True
                    if 'Permission denied' in (out or ''):
                        hint = (
                            '⚠️  Fetch failed because some repo refs/logs are not writable by the current user. '
                            'No merge was attempted.'
                        )
                        self.after(0, lambda h=hint: self._git_write(h, 'err'))
                else:
                    self.after(0, lambda: self._git_write('ℹ️  Fetch only complete — no merge performed', 'ok'))
            status = '❌ Fetch errors — check log' if any_err else '✅ Fetch complete (no merge performed)'
            self.after(0, lambda: self._status_var.set(status))
            self.after(500, self._refresh_tree)

        threading.Thread(target=_run, daemon=True).start()

    def _git_status(self):
        self._git_run_async('Status', 'status', '--short')

    def _git_diff(self):
        self._git_run_async('Diff', 'diff', '--stat', 'HEAD')

    def _git_commit(self):
        msg = self._commit_msg.get().strip()
        if not msg:
            messagebox.showwarning('Commit', 'Enter a commit message.')
            return
        self._notebook.select(2)
        self._git_clear()
        repo = self._repo_path()

        def _run():
            self.after(0, lambda: self._git_write('$ git add -u', 'head'))
            rc, out = _git(repo, 'add', '-u')
            self.after(0, lambda: self._git_write(out or '(staged)', 'ok' if rc == 0 else 'err'))

            self.after(0, lambda: self._git_write(f'$ git commit -m "{msg}"', 'head'))
            rc2, out2 = _git(repo, 'commit', '-m', msg)
            tag = 'ok' if rc2 == 0 else 'err'
            self.after(0, lambda: self._git_write(out2, tag))
            status = '✅ Committed' if rc2 == 0 else '❌ Commit failed'
            self.after(0, lambda: self._status_var.set(status))

        threading.Thread(target=_run, daemon=True).start()

    def _git_commit_push(self):
        msg = self._commit_msg.get().strip()
        if not msg:
            messagebox.showwarning('Commit', 'Enter a commit message.')
            return
        self._notebook.select(2)
        self._git_clear()
        repo = self._repo_path()

        def _run():
            for label, *args in [
                ('git add -u',        'add', '-u'),
                (f'git commit "{msg}"', 'commit', '-m', msg),
                ('git push',          'push'),
            ]:
                self.after(0, lambda l=label: self._git_write(f'$ {l}', 'head'))
                rc, out = _git(repo, *args[1:] if isinstance(args[0], str) else args)
                # args are already the git sub-args
                self.after(0, lambda o=out, r=rc: self._git_write(o or '(ok)', 'ok' if r == 0 else 'err'))
                if rc != 0:
                    self.after(0, lambda: self._status_var.set('❌ Push failed'))
                    return
            self.after(0, lambda: self._status_var.set('✅ Committed and pushed'))

        threading.Thread(target=_run, daemon=True).start()


# ── Standalone test ───────────────────────────────────────────────────────────
if __name__ == '__main__':
    root = tk.Tk()
    root.title('Flux Config Widget - Test')
    root.geometry('1400x900')
    root.configure(bg=BG)
    w = FluxConfigWidget(root)
    w.pack(fill=tk.BOTH, expand=True)
    root.mainloop()
