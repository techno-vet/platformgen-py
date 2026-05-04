"""
Google Chat Widget — Post messages to Google Chat spaces via webhooks.

Two webhook scopes:
  PERSONAL — stored in ~/.auger/.env as GCHAT_WEBHOOK_<NAME>
             Private to each user, never committed to git. Shown with 👤
  SYSTEM   — stored in auger/data/gchat_webhooks.yaml
             Shared with all users via git. Shown with 🌐

Two tabs:
    📨 Send      — compose & send to any webhook
    ⚙️  Webhooks  — inline CRUD with Personal / System toggle
"""
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import re
import subprocess
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

try:
    import yaml
except ImportError:
    yaml = None

try:
    from dotenv import set_key, unset_key
except ImportError:
    set_key = unset_key = None

try:
    from auger.ui.utils import make_text_copyable, auger_home as _auger_home
except ImportError:
    def make_text_copyable(w): pass
    def _auger_home(): return Path.home()

try:
    from PIL import Image as _PILImage, ImageDraw as _PILImageDraw, ImageTk as _PILImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


def _make_gc_send_icon(size=14, color='#5db0d7'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    d.rectangle([m*2, m*3, s2-m*2, s2-m*3], outline=color, width=m)
    d.line([(m*2, m*3), (s2//2, s2//2), (s2-m*2, m*3)], fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_gc_hooks_icon(size=14, color='#4ec9b0'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    r = m * 4
    d.arc([m*2, m*2, m*2+r*2, m*2+r*2], 180, 360, fill=color, width=m)
    d.line([(m*2+r, m*2+r*2), (m*2+r, s2-m*2)], fill=color, width=m)
    d.ellipse([m*2+r-m*2, s2-m*2-m*4, m*2+r+m*2, s2-m*2], outline=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


def _make_gc_users_icon(size=14, color='#dcdcaa'):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    s2 = size * 2
    img = Image.new('RGBA', (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = max(1, s2 // 14)
    r = m * 3
    d.ellipse([s2//4-r, m, s2//4+r, m+r*2], outline=color, width=m)
    d.arc([m, s2//2, s2//2+m*2, s2-m], 180, 360, fill=color, width=m)
    d.ellipse([s2//2+r-m, m, s2//2+r-m+r*2, m+r*2], outline=color, width=m)
    d.arc([s2//2-m*2, s2//2, s2-m, s2-m], 180, 360, fill=color, width=m)
    return img.resize((size, size), Image.LANCZOS)


# ── Theme ─────────────────────────────────────────────────────────────────────
BG      = '#1e1e1e'
BG2     = '#252526'
BG3     = '#2d2d2d'
BG4     = '#3c3c3c'
FG      = '#e0e0e0'
FG2     = '#888888'
FG3     = '#444444'
ACCENT  = '#007acc'
SUCCESS = '#4ec9b0'
ERROR   = '#f44747'
WARN    = '#f0c040'

_ENV_FILE    = _auger_home() / '.auger' / '.env'
_KEY_PREFIX  = 'GCHAT_WEBHOOK_'
_KEY_RE      = re.compile(r'^GCHAT_WEBHOOK_([A-Za-z0-9_]+)$')

# System webhooks YAML (in the repo — shared via git)
_SYS_YAML    = Path(__file__).resolve().parents[2] / 'data' / 'gchat_webhooks.yaml'
_SYS_YAML_CF = Path(__file__).resolve().parents[3] / 'config' / 'gchat_webhooks.yaml'


# ── Storage helpers ───────────────────────────────────────────────────────────

def _load_personal() -> dict:
    """Return {name: url} from ~/.auger/.env."""
    if not _ENV_FILE.exists():
        return {}
    try:
        lines = _ENV_FILE.read_text().splitlines()
    except PermissionError:
        print(f'[GChat] Warning: cannot read {_ENV_FILE} (permission denied)')
        return {}
    hooks = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, _, v = line.partition('=')
        m = _KEY_RE.match(k.strip())
        if m:
            hooks[m.group(1)] = v.strip().strip('"').strip("'")
    return hooks


def _save_personal(name: str, url: str):
    if set_key:
        try:
            _ENV_FILE.touch(exist_ok=True)
            set_key(str(_ENV_FILE), f'{_KEY_PREFIX}{name.upper()}', url)
        except PermissionError:
            raise PermissionError(
                f"Cannot write to {_ENV_FILE}\n\n"
                "The container is running as a different user than the .env owner.\n"
                "Fix: relaunch Auger from terminal:\n"
                "  docker rm -f auger-platform && bash ~/repos/auger-ai-sre-platform/scripts/auger-launch.sh"
            )


def _delete_personal(name: str):
    if unset_key:
        try:
            unset_key(str(_ENV_FILE), f'{_KEY_PREFIX}{name.upper()}')
        except PermissionError:
            pass


def _sys_yaml_path() -> Path:
    repo = _find_git_root()
    if repo is not None:
        repo_data = repo / 'auger' / 'data' / 'gchat_webhooks.yaml'
        repo_cfg = repo / 'config' / 'gchat_webhooks.yaml'
        if repo_data.exists():
            return repo_data
        if repo_cfg.exists():
            return repo_cfg
    return _SYS_YAML if _SYS_YAML.exists() else _SYS_YAML_CF


def _paired_sys_yaml_path(selected: Path) -> Path | None:
    repo = _find_git_root()
    if repo is not None:
        repo_data = repo / 'auger' / 'data' / 'gchat_webhooks.yaml'
        repo_cfg = repo / 'config' / 'gchat_webhooks.yaml'
        if selected == repo_data and repo_cfg.exists():
            return repo_cfg
        if selected == repo_cfg and repo_data.exists():
            return repo_data
    if selected == _SYS_YAML and _SYS_YAML_CF.exists():
        return _SYS_YAML_CF
    if selected == _SYS_YAML_CF and _SYS_YAML.exists():
        return _SYS_YAML
    return None


def _load_system() -> dict:
    """Return {name: {'url': ..., 'description': ...}} from YAML."""
    p = _sys_yaml_path()
    if not p.exists() or yaml is None:
        return {}
    try:
        data = yaml.safe_load(p.read_text()) or {}
        hooks = {}
        for entry in data.get('webhooks', []):
            if entry.get('name') and entry.get('url'):
                hooks[entry['name'].upper()] = {
                    'url': entry['url'],
                    'description': entry.get('description', ''),
                }
        return hooks
    except Exception:
        return {}


def _save_system(name: str, url: str, description: str = ''):
    p = _sys_yaml_path()
    if yaml is None:
        raise RuntimeError('yaml library not available')
    try:
        data = yaml.safe_load(p.read_text()) or {} if p.exists() else {}
        webhooks = data.get('webhooks', [])
        # Update existing or append
        for entry in webhooks:
            if entry.get('name', '').upper() == name.upper():
                entry['url'] = url
                entry['description'] = description
                break
        else:
            webhooks.append({'name': name.upper(), 'url': url, 'description': description})
        data['webhooks'] = webhooks
        rendered = yaml.dump(data, default_flow_style=False, sort_keys=False)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(rendered)
        target = _paired_sys_yaml_path(p)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered)
    except Exception as e:
        raise RuntimeError(f'Could not save system webhook YAML: {e}') from e


def _delete_system(name: str):
    p = _sys_yaml_path()
    if yaml is None or not p.exists():
        return
    try:
        data = yaml.safe_load(p.read_text()) or {}
        data['webhooks'] = [e for e in data.get('webhooks', [])
                            if e.get('name', '').upper() != name.upper()]
        rendered = yaml.dump(data, default_flow_style=False, sort_keys=False)
        p.write_text(rendered)
        target = _paired_sys_yaml_path(p)
        if target is not None:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(rendered)
    except Exception as e:
        print(f'[GChat] delete_system error: {e}')


def _find_git_root() -> Path | None:
    """Walk up from __file__ looking for a .git dir; also check ~/repos path."""
    # Walk up from the widget file
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / '.git').is_dir():
            return parent
    # Fallback: well-known repo location
    candidate = _auger_home() / 'repos' / 'auger-ai-sre-platform'
    if (candidate / '.git').is_dir():
        return candidate
    return None


def _get_current_branch(repo: Path) -> str:
    """Return current git branch name, or empty string on error."""
    try:
        r = subprocess.run(['git', '-C', str(repo), 'branch', '--show-current'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception:
        return ''


def _is_feature_branch(branch: str) -> bool:
    return bool(branch) and branch.startswith('feature/')


def _git_commit_push(repo: Path, branch: str, callback) -> None:
    """Commit changed YAML and push via GHE API (bypasses local git object permissions)."""
    def _do():
        try:
            import base64 as _b64, os
            from dotenv import dotenv_values
            env      = dotenv_values(str(_auger_home() / '.auger' / '.env'))
            ghe_url   = env.get('GHE_URL', 'https://github.helix.gsa.gov')
            ghe_token = env.get('GHE_TOKEN', '')
            if not ghe_token:
                callback(False, '❌ GHE_TOKEN not set in ~/.auger/.env')
                return

            headers = {'Authorization': f'token {ghe_token}',
                       'Content-Type': 'application/json'}
            api = f'{ghe_url}/api/v3/repos/assist/auger-ai-sre-platform'

            # Files to commit — data yaml (canonical) + config yaml (symlink target)
            files_to_commit = []
            for rel_path in ('auger/data/gchat_webhooks.yaml',
                             'config/gchat_webhooks.yaml'):
                local = repo / rel_path
                if not local.exists():
                    continue
                content_b64 = _b64.b64encode(local.read_bytes()).decode()
                # Upload blob
                r = requests.post(f'{api}/git/blobs', headers=headers,
                                  json={'content': content_b64, 'encoding': 'base64'},
                                  verify=False, timeout=20)
                if r.status_code not in (200, 201):
                    callback(False, f'❌ Blob upload failed for {rel_path}: {r.text[:120]}')
                    return
                files_to_commit.append({'path': rel_path, 'mode': '100644',
                                        'type': 'blob', 'sha': r.json()['sha']})

            if not files_to_commit:
                callback(True, 'No files to commit')
                return

            target_branch = branch or 'main'

            # Get current HEAD SHA for the target branch
            r = requests.get(f'{api}/git/ref/heads/{target_branch}', headers=headers,
                             verify=False, timeout=15)
            if r.status_code != 200:
                callback(False, f'❌ Could not get branch ref for "{target_branch}": {r.text[:160]}')
                return
            head_sha = r.json()['object']['sha']

            # Get base tree
            r = requests.get(f'{api}/git/commits/{head_sha}', headers=headers,
                             verify=False, timeout=15)
            base_tree = r.json()['tree']['sha']

            # Create new tree
            r = requests.post(f'{api}/git/trees', headers=headers,
                              json={'base_tree': base_tree, 'tree': files_to_commit},
                              verify=False, timeout=20)
            new_tree = r.json()['sha']

            # Create commit
            r = requests.post(f'{api}/git/commits', headers=headers,
                              json={
                                  'message': 'chore(gchat): update system webhooks\n\nCo-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>',
                                  'tree': new_tree,
                                  'parents': [head_sha],
                                  'author': {'name': env.get('GHE_USERNAME', 'auger'),
                                             'email': f'{env.get("GHE_USERNAME","auger")}@users.noreply.github.com'},
                              }, verify=False, timeout=20)
            commit_sha = r.json()['sha']

            # Update branch ref
            r = requests.patch(f'{api}/git/refs/heads/{target_branch}', headers=headers,
                               json={'sha': commit_sha}, verify=False, timeout=15)
            if r.status_code not in (200, 201):
                callback(False, f'❌ Ref update failed: {r.text[:120]}')
                return

            callback(True, f'✅ Committed & pushed {commit_sha[:8]} → {target_branch}')

        except Exception as e:
            callback(False, f'❌ {e}')
    threading.Thread(target=_do, daemon=True).start()


def _get_sender_name() -> str:
    """Return the display name for the current user from GHE_USERNAME in ~/.auger/.env."""
    import os
    # Check environment first (already loaded by the shell / container)
    username = os.environ.get('GHE_USERNAME', '').strip()
    if not username and _ENV_FILE.exists():
        try:
            for line in _ENV_FILE.read_text().splitlines():
                line = line.strip()
                if line.startswith('GHE_USERNAME='):
                    username = line.partition('=')[2].strip().strip('"').strip("'")
                    break
        except Exception:
            pass
    return username or 'Auger'


def _post_message(url: str, text: str):
    if requests is None:
        return False, 'requests library not available'
    sender = _get_sender_name()
    full_text = f"{text}\n\n— sent via Auger by {sender}"
    try:
        r = requests.post(url, json={'text': full_text},
                          headers={'Content-Type': 'application/json'}, timeout=10)
        return (True,  f'Sent {r.status_code} OK') if r.status_code == 200 \
               else (False, f'HTTP {r.status_code}: {r.text[:100]}')
    except Exception as e:
        return False, str(e)


# Users YAML (extracted from space member list HTML)
_USERS_YAML    = Path(__file__).resolve().parents[2] / 'data' / 'gchat_users.yaml'
_USERS_YAML_CF = Path(__file__).resolve().parents[3] / 'config' / 'gchat_users.yaml'


def _users_yaml_path() -> Path:
    return _USERS_YAML if _USERS_YAML.exists() else _USERS_YAML_CF


def _load_users() -> list:
    """Return list of {name, email, user_id} dicts from YAML."""
    p = _users_yaml_path()
    if not p.exists() or yaml is None:
        return []
    try:
        data = yaml.safe_load(p.read_text()) or {}
        return data.get('users', [])
    except Exception:
        return []


def _save_users(users: list):
    """Write users list back to YAML (both data/ and config/)."""
    p = _users_yaml_path()
    if yaml is None:
        return
    try:
        existing = yaml.safe_load(p.read_text()) or {} if p.exists() else {}
        existing['users'] = users
        content = ('# Google Chat space members\n'
                   '# user_id is the Google Chat numeric ID used for @mentions\n\n'
                   + yaml.dump(existing, default_flow_style=False, sort_keys=False))
        p.write_text(content)
        if _USERS_YAML.exists() and _USERS_YAML_CF.exists():
            _USERS_YAML_CF.write_text(content)
    except Exception as e:
        print(f'[GChat] save_users error: {e}')


# ── Widget ────────────────────────────────────────────────────────────────────

class GChatWidget(tk.Frame):
    WIDGET_NAME      = 'gchat'
    WIDGET_ICON_NAME = 'rocket'

    def __init__(self, master, **kw):
        super().__init__(master, bg=BG, **kw)
        self._personal: dict = {}   # name -> url
        self._system:   dict = {}   # name -> {url, description}
        self._editing:  tuple | None = None  # (scope, name) or None
        self._users:    list = []            # list of {name, email, user_id}
        self._user_editing: dict | None = None
        self._tab_icons = {}
        self._nb = None
        self._build_ui()
        self._reload()

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG2, pady=6)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text='  Google Chat', font=('Segoe UI', 11, 'bold'),
                 fg=FG, bg=BG2).pack(side=tk.LEFT)

        style = ttk.Style()
        style.configure('GC.TNotebook',     background=BG2, borderwidth=0)
        style.configure('GC.TNotebook.Tab', background=BG3, foreground=FG2,
                        padding=[10, 4], font=('Segoe UI', 9))
        style.map('GC.TNotebook.Tab',
                  background=[('selected', BG)],
                  foreground=[('selected', FG)])

        nb = ttk.Notebook(self, style='GC.TNotebook')
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._nb = nb
        self._send_tab  = tk.Frame(nb, bg=BG)
        self._hooks_tab = tk.Frame(nb, bg=BG)
        self._users_tab = tk.Frame(nb, bg=BG)
        nb.add(self._send_tab,  text='  Send  ')
        nb.add(self._hooks_tab, text='  Webhooks  ')
        nb.add(self._users_tab, text='  Users  ')
        self.after(0, self._apply_gc_tab_icons)
        self._build_send_tab()
        self._build_hooks_tab()
        self._build_users_tab()

    # ── Send tab ───────────────────────────────────────────────────────────────

    def _apply_gc_tab_icons(self):
        """Apply emoji labels to GChat sub-tabs via safe nb.tab() calls.
        nb.tab() does not trigger SIGSEGV — only nb.add(text=...) with emoji is unsafe."""
        if self._nb is None:
            return
        tabs_config = [
            (self._send_tab,  '📨 Send'),
            (self._hooks_tab, '⚙️ Webhooks'),
            (self._users_tab, '👥 Users'),
        ]
        for frame, label in tabs_config:
            try:
                self._nb.tab(frame, text=f'  {label}  ')
            except Exception:
                pass

    def _build_send_tab(self):
        p = self._send_tab
        r1 = tk.Frame(p, bg=BG)
        r1.pack(fill=tk.X, padx=12, pady=(12, 4))
        tk.Label(r1, text='To:', width=6, anchor='w',
                 font=('Segoe UI', 9), fg=FG2, bg=BG).pack(side=tk.LEFT)
        self._target_var = tk.StringVar()
        self._target_cb  = ttk.Combobox(r1, textvariable=self._target_var,
                                         state='readonly', font=('Segoe UI', 9))
        self._target_cb.pack(side=tk.LEFT, fill=tk.X, expand=True)

        tk.Label(p, text='Message:', font=('Segoe UI', 9), fg=FG2, bg=BG,
                 anchor='w').pack(fill=tk.X, padx=12)
        tf = tk.Frame(p, bg=BG3, bd=1)
        tf.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 6))
        self._msg = tk.Text(tf, height=6, bg=BG3, fg=FG, insertbackground=FG,
                            font=('Consolas', 10), wrap=tk.WORD, relief='flat',
                            padx=6, pady=6, undo=True)
        sc = ttk.Scrollbar(tf, command=self._msg.yview)
        self._msg.configure(yscrollcommand=sc.set)
        sc.pack(side=tk.RIGHT, fill=tk.Y)
        self._msg.pack(fill=tk.BOTH, expand=True)
        make_text_copyable(self._msg)

        qr = tk.Frame(p, bg=BG)
        qr.pack(fill=tk.X, padx=12, pady=(0, 4))
        tk.Label(qr, text='Quick fill:', font=('Segoe UI', 8),
                 fg=FG3, bg=BG).pack(side=tk.LEFT, padx=(0, 6))
        for lbl, fn in [('Active PR', self._fill_pr),
                         ('Current Task', self._fill_task),
                         ('Auger Invite', self._fill_invite)]:
            b = tk.Label(qr, text=lbl, font=('Segoe UI', 8), fg=ACCENT,
                         bg=BG4, cursor='hand2', padx=6, pady=2)
            b.pack(side=tk.LEFT, padx=2)
            b.bind('<Button-1>', lambda e, f=fn: f())

        bot = tk.Frame(p, bg=BG)
        bot.pack(fill=tk.X, padx=12, pady=(0, 10))
        sb = tk.Frame(bot, bg=ACCENT, cursor='hand2')
        sb.pack(side=tk.RIGHT)
        sl = tk.Label(sb, text=' Send → ', font=('Segoe UI', 9, 'bold'),
                      fg='white', bg=ACCENT, cursor='hand2', padx=8, pady=4)
        sl.pack()
        sb.bind('<Button-1>', lambda e: self._send())
        sl.bind('<Button-1>', lambda e: self._send())
        self._status = tk.Label(bot, text='', font=('Segoe UI', 9),
                                fg=FG2, bg=BG, anchor='w')
        self._status.pack(side=tk.LEFT, fill=tk.X, expand=True)

    # ── Webhooks tab ───────────────────────────────────────────────────────────

    def _build_hooks_tab(self):
        p = self._hooks_tab

        # ── Inline form ───────────────────────────────────────────────────
        form_outer = tk.Frame(p, bg=BG2, pady=6)
        form_outer.pack(fill=tk.X, padx=6, pady=(6, 0))

        self._form_title = tk.Label(form_outer, text='Add / Edit Webhook',
                                    font=('Segoe UI', 9, 'bold'), fg=FG, bg=BG2)
        self._form_title.pack(anchor='w', padx=8, pady=(0, 4))

        fields = tk.Frame(form_outer, bg=BG2)
        fields.pack(fill=tk.X, padx=8)
        fields.columnconfigure(1, weight=1)

        # Scope toggle
        tk.Label(fields, text='Scope:', font=('Segoe UI', 9, 'bold'), fg=FG,
                 bg=BG2, width=8, anchor='e').grid(row=0, column=0, padx=(0,6), pady=2, sticky='e')
        self._scope_var = tk.StringVar(value='personal')
        scope_frame = tk.Frame(fields, bg=BG2)
        scope_frame.grid(row=0, column=1, sticky='w', pady=2)
        for val, lbl, tip in [('personal', '👤 Personal', 'Saved to ~/.auger/.env — private to you'),
                               ('system',   '🌐 System',   'Saved to repo YAML — shared with all users via git')]:
            rb = tk.Radiobutton(scope_frame, text=lbl, variable=self._scope_var,
                                value=val, font=('Segoe UI', 9),
                                fg=FG, bg=BG2, selectcolor=BG3, activebackground=BG2,
                                activeforeground=FG, cursor='hand2',
                                command=self._on_scope_change)
            rb.pack(side=tk.LEFT, padx=(0, 16))
        self._scope_tip = tk.Label(fields, text='Saved to ~/.auger/.env — private to you',
                                    font=('Segoe UI', 8), fg=FG3, bg=BG2)
        self._scope_tip.grid(row=0, column=2, padx=6, sticky='w')

        # Name
        tk.Label(fields, text='Name:', font=('Segoe UI', 9), fg=FG2,
                 bg=BG2, width=8, anchor='e').grid(row=1, column=0, padx=(0,6), pady=2, sticky='e')
        self._fname_var = tk.StringVar()
        self._fname_ent = tk.Entry(fields, textvariable=self._fname_var,
                                    font=('Consolas', 9), bg=BG3, fg=FG,
                                    insertbackground=FG, relief='flat', width=20)
        self._fname_ent.grid(row=1, column=1, sticky='ew', pady=2)
        tk.Label(fields, text='e.g. ME or PR_REVIEWS',
                 font=('Segoe UI', 8), fg=FG3, bg=BG2).grid(row=1, column=2, padx=6, sticky='w')

        # URL
        tk.Label(fields, text='URL:', font=('Segoe UI', 9), fg=FG2,
                 bg=BG2, width=8, anchor='e').grid(row=2, column=0, padx=(0,6), pady=2, sticky='e')
        self._furl_var = tk.StringVar()
        self._furl_ent = tk.Entry(fields, textvariable=self._furl_var,
                                   font=('Consolas', 9), bg=BG3, fg=FG,
                                   insertbackground=FG, relief='flat')
        self._furl_ent.grid(row=2, column=1, columnspan=2, sticky='ew', pady=2)

        # Description (system only)
        self._fdesc_row = tk.Frame(fields, bg=BG2)
        self._fdesc_row.grid(row=3, column=0, columnspan=3, sticky='ew', pady=2)
        tk.Label(self._fdesc_row, text='Desc:', font=('Segoe UI', 9), fg=FG2,
                 bg=BG2, width=8, anchor='e').pack(side=tk.LEFT, padx=(0,6))
        self._fdesc_var = tk.StringVar()
        tk.Entry(self._fdesc_row, textvariable=self._fdesc_var,
                 font=('Consolas', 9), bg=BG3, fg=FG,
                 insertbackground=FG, relief='flat').pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._fdesc_row.grid_remove()  # hidden for personal

        # Error / status
        self._form_err = tk.Label(form_outer, text='', font=('Segoe UI', 8),
                                   fg=ERROR, bg=BG2)
        self._form_err.pack(anchor='w', padx=8)

        # Buttons
        btn_row = tk.Frame(form_outer, bg=BG2)
        btn_row.pack(anchor='w', padx=8, pady=(2, 4))
        for lbl, color, cmd in [
            (' Save ',  ACCENT,    self._form_save),
            (' Clear ', BG4,       self._form_clear),
            (' Test ',  '#1a5276', self._form_test),
        ]:
            b = tk.Label(btn_row, text=lbl, font=('Segoe UI', 9,
                         'bold' if lbl.strip() == 'Save' else 'normal'),
                         fg='white', bg=color, cursor='hand2', padx=8, pady=3)
            b.pack(side=tk.LEFT, padx=(0, 6))
            b.bind('<Button-1>', lambda e, f=cmd: f())

        # Git status label (hidden until a system webhook is saved/deleted)
        self._git_note = tk.Label(form_outer, text='',
            font=('Segoe UI', 8), fg=WARN, bg=BG2, wraplength=500, justify='left')

        # ── Divider ───────────────────────────────────────────────────────
        tk.Frame(p, bg=BG3, height=1).pack(fill=tk.X, padx=6, pady=4)

        # ── List ──────────────────────────────────────────────────────────
        lh = tk.Frame(p, bg=BG)
        lh.pack(fill=tk.X, padx=8)
        tk.Label(lh, text='Configured Webhooks',
                 font=('Segoe UI', 9, 'bold'), fg=FG, bg=BG).pack(side=tk.LEFT)
        self._count_lbl = tk.Label(lh, text='', font=('Segoe UI', 8), fg=FG2, bg=BG)
        self._count_lbl.pack(side=tk.LEFT, padx=8)
        rb = tk.Label(lh, text=' Refresh ', font=('Segoe UI', 8),
                      fg=FG2, bg=BG4, cursor='hand2', padx=4, pady=1)
        rb.pack(side=tk.RIGHT, padx=4)
        rb.bind('<Button-1>', lambda e: self._reload())

        outer = tk.Frame(p, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._list_frame = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=self._list_frame, anchor='nw')
        def _resize(e):
            canvas.itemconfig(win, width=e.width)
            canvas.configure(scrollregion=canvas.bbox('all'))
        canvas.bind('<Configure>', _resize)
        self._list_frame.bind('<Configure>',
                              lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

    # ── Users tab ─────────────────────────────────────────────────────────────

    def _build_users_tab(self):
        p = self._users_tab

        # Form
        form = tk.Frame(p, bg=BG2, pady=6)
        form.pack(fill=tk.X, padx=6, pady=(6, 0))
        self._user_form_title = tk.Label(form, text='Add / Edit User',
                                          font=('Segoe UI', 9, 'bold'), fg=FG, bg=BG2)
        self._user_form_title.pack(anchor='w', padx=8, pady=(0, 4))

        fields = tk.Frame(form, bg=BG2)
        fields.pack(fill=tk.X, padx=8)
        fields.columnconfigure(1, weight=1)

        labels = ['Name:', 'Email:', 'User ID:']
        self._uname_var  = tk.StringVar()
        self._uemail_var = tk.StringVar()
        self._ueid_var   = tk.StringVar()
        vars_  = [self._uname_var, self._uemail_var, self._ueid_var]
        hints  = ['Display name', 'user@gsa.gov', 'Google numeric ID (for @mention)']
        for i, (lbl, var, hint) in enumerate(zip(labels, vars_, hints)):
            tk.Label(fields, text=lbl, font=('Segoe UI', 9), fg=FG2,
                     bg=BG2, width=8, anchor='e').grid(row=i, column=0, padx=(0,6), pady=2, sticky='e')
            tk.Entry(fields, textvariable=var, font=('Consolas', 9),
                     bg=BG3, fg=FG, insertbackground=FG, relief='flat').grid(
                     row=i, column=1, sticky='ew', pady=2)
            tk.Label(fields, text=hint, font=('Segoe UI', 8), fg=FG3,
                     bg=BG2).grid(row=i, column=2, padx=6, sticky='w')

        self._user_form_err = tk.Label(form, text='', font=('Segoe UI', 8), fg=ERROR, bg=BG2)
        self._user_form_err.pack(anchor='w', padx=8)

        btn_row = tk.Frame(form, bg=BG2)
        btn_row.pack(anchor='w', padx=8, pady=(2, 6))
        for lbl, color, cmd in [
            (' Save ',       ACCENT,    self._user_save),
            (' Clear ',      BG4,       self._user_clear),
            (' Copy @mention ', '#1a5276', self._user_copy_mention),
        ]:
            b = tk.Label(btn_row, text=lbl, font=('Segoe UI', 9),
                         fg='white', bg=color, cursor='hand2', padx=8, pady=3)
            b.pack(side=tk.LEFT, padx=(0, 6))
            b.bind('<Button-1>', lambda e, f=cmd: f())

        tk.Frame(p, bg=BG3, height=1).pack(fill=tk.X, padx=6, pady=4)

        # Search + list header
        sh = tk.Frame(p, bg=BG)
        sh.pack(fill=tk.X, padx=8, pady=(0, 4))
        tk.Label(sh, text='Members', font=('Segoe UI', 9, 'bold'),
                 fg=FG, bg=BG).pack(side=tk.LEFT)
        self._user_count = tk.Label(sh, text='', font=('Segoe UI', 8), fg=FG2, bg=BG)
        self._user_count.pack(side=tk.LEFT, padx=8)
        rb = tk.Label(sh, text=' Refresh ', font=('Segoe UI', 9), fg=FG2,
                      bg=BG4, cursor='hand2', padx=4)
        rb.pack(side=tk.RIGHT, padx=4)
        rb.bind('<Button-1>', lambda e: self._reload_users())

        # Search box
        sf = tk.Frame(p, bg=BG3)
        sf.pack(fill=tk.X, padx=6, pady=(0, 4))
        tk.Label(sf, text='Search:', font=('Segoe UI', 9), bg=BG3, fg=FG2).pack(side=tk.LEFT, padx=4)
        self._user_search = tk.StringVar()
        self._user_search.trace_add('write', lambda *_: self._rebuild_users())
        tk.Entry(sf, textvariable=self._user_search, font=('Consolas', 9),
                 bg=BG3, fg=FG, insertbackground=FG, relief='flat').pack(
                 side=tk.LEFT, fill=tk.X, expand=True, pady=3, padx=(0,4))

        # Scrollable list
        outer = tk.Frame(p, bg=BG)
        outer.pack(fill=tk.BOTH, expand=True, padx=6, pady=4)
        canvas = tk.Canvas(outer, bg=BG, highlightthickness=0)
        vsb = ttk.Scrollbar(outer, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._users_frame = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=self._users_frame, anchor='nw')
        def _resize(e):
            canvas.itemconfig(win, width=e.width)
            canvas.configure(scrollregion=canvas.bbox('all'))
        canvas.bind('<Configure>', _resize)
        self._users_frame.bind('<Configure>',
                               lambda e: canvas.configure(scrollregion=canvas.bbox('all')))

    def _reload_users(self):
        self._users = _load_users()
        self._rebuild_users()

    def _rebuild_users(self):
        for w in self._users_frame.winfo_children():
            w.destroy()
        q = self._user_search.get().strip().lower()
        filtered = [u for u in self._users
                    if not q or q in u.get('name','').lower()
                    or q in u.get('email','').lower()]
        self._user_count.config(text=f'({len(self._users)} total, {len(filtered)} shown)')
        if not filtered:
            tk.Label(self._users_frame,
                     text='No members. Add one above or re-import from HTML.',
                     font=('Segoe UI', 9), fg=FG2, bg=BG).pack(padx=12, pady=16)
            return
        for u in sorted(filtered, key=lambda x: x.get('name','')):
            self._user_row(u)

    def _user_row(self, u: dict):
        row = tk.Frame(self._users_frame, bg=BG2, pady=4)
        row.pack(fill=tk.X, pady=1, padx=2)
        info = tk.Frame(row, bg=BG2)
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        tk.Label(info, text=u.get('name',''), font=('Segoe UI', 9, 'bold'),
                 fg=FG, bg=BG2).pack(anchor='w')
        tk.Label(info, text=u.get('email',''), font=('Consolas', 8),
                 fg=FG2, bg=BG2).pack(anchor='w')
        uid = u.get('user_id','')
        if uid:
            tk.Label(info, text=f'ID: {uid}', font=('Consolas', 8),
                     fg=FG3, bg=BG2).pack(anchor='w')
        btns = tk.Frame(row, bg=BG2)
        btns.pack(side=tk.RIGHT, padx=6)
        for lbl, color, cmd in [
            ('@',      ACCENT,    lambda uu=u: self._mention_to_clipboard(uu)),
            ('Edit',   BG4,       lambda uu=u: self._user_load(uu)),
            ('Delete', '#6e2020', lambda uu=u: self._user_delete(uu)),
        ]:
            b = tk.Label(btns, text=f' {lbl} ', font=('Segoe UI', 8),
                         fg='white', bg=color, cursor='hand2', padx=4, pady=2)
            b.pack(side=tk.LEFT, padx=2)
            b.bind('<Button-1>', lambda e, f=cmd: f())

    def _mention_to_clipboard(self, u: dict):
        uid  = u.get('user_id','')
        name = u.get('name','')
        mention = f'<users/{uid}>' if uid else f'@{name}'
        try:
            self.clipboard_clear()
            self.clipboard_append(mention)
            self._user_form_err.config(text=f'✅ Copied: {mention}', fg=SUCCESS)
        except Exception as e:
            self._user_form_err.config(text=f'❌ {e}', fg=ERROR)

    def _user_load(self, u: dict):
        self._user_editing = u
        self._uname_var.set(u.get('name',''))
        self._uemail_var.set(u.get('email',''))
        self._ueid_var.set(u.get('user_id',''))
        self._user_form_title.config(text=f'Edit: {u.get("name","")}')
        self._user_form_err.config(text='', fg=ERROR)

    def _user_clear(self):
        self._user_editing = None
        self._uname_var.set('')
        self._uemail_var.set('')
        self._ueid_var.set('')
        self._user_form_title.config(text='Add / Edit User')
        self._user_form_err.config(text='', fg=ERROR)

    def _user_save(self):
        name  = self._uname_var.get().strip()
        email = self._uemail_var.get().strip()
        uid   = self._ueid_var.get().strip()
        if not name:
            self._user_form_err.config(text='Name is required', fg=ERROR); return
        users = list(self._users)
        if self._user_editing:
            old_email = self._user_editing.get('email','')
            users = [u for u in users if u.get('email','') != old_email]
        users.append({'name': name, 'email': email, 'user_id': uid})
        _save_users(sorted(users, key=lambda x: x.get('name','')))
        self._user_form_err.config(text=f'✅ Saved {name}', fg=SUCCESS)
        self._reload_users()
        self._user_clear()

    def _user_delete(self, u: dict):
        from tkinter import messagebox
        if not messagebox.askyesno('Delete', f'Remove {u.get("name","")} from members list?', parent=self):
            return
        users = [x for x in self._users if x.get('email','') != u.get('email','')]
        _save_users(users)
        self._reload_users()

    def _user_copy_mention(self):
        uid  = self._ueid_var.get().strip()
        name = self._uname_var.get().strip()
        if not uid and not name:
            self._user_form_err.config(text='Enter a name or user ID first', fg=ERROR); return
        mention = f'<users/{uid}>' if uid else f'@{name}'
        try:
            self.clipboard_clear()
            self.clipboard_append(mention)
            self._user_form_err.config(text=f'✅ Copied: {mention}', fg=SUCCESS)
        except Exception as e:
            self._user_form_err.config(text=f'❌ {e}', fg=ERROR)

    def _on_scope_change(self):
        is_sys = self._scope_var.get() == 'system'
        if is_sys:
            self._fdesc_row.grid()
            self._scope_tip.config(text='Saved to repo YAML — shared with all users via git')
        else:
            self._fdesc_row.grid_remove()
            self._scope_tip.config(text='Saved to ~/.auger/.env — private to you')

    # ── List ───────────────────────────────────────────────────────────────────

    def _rebuild_list(self):
        for w in self._list_frame.winfo_children():
            w.destroy()
        total = len(self._personal) + len(self._system)
        self._count_lbl.config(text=f'({total} total — {len(self._personal)} personal, {len(self._system)} system)')

        if not total:
            tk.Label(self._list_frame,
                     text='No webhooks configured. Fill in the form above and click Save.',
                     font=('Segoe UI', 9), fg=FG2, bg=BG).pack(padx=12, pady=16)
            return

        # Personal section
        if self._personal:
            self._section_header('👤 Personal  (stored in ~/.auger/.env)')
            for name in sorted(self._personal):
                self._list_row(name, self._personal[name], 'personal', '#2a3a2a')

        # System section
        if self._system:
            self._section_header('🌐 System  (shared via git · auger/data/gchat_webhooks.yaml)')
            for name in sorted(self._system):
                info = self._system[name]
                url  = info['url'] if isinstance(info, dict) else info
                desc = info.get('description','') if isinstance(info, dict) else ''
                self._list_row(name, url, 'system', '#1a2a3a', desc)

    def _section_header(self, text: str):
        f = tk.Frame(self._list_frame, bg=BG2)
        f.pack(fill=tk.X, pady=(6, 2))
        tk.Label(f, text=f'  {text}', font=('Segoe UI', 8, 'bold'),
                 fg=FG2, bg=BG2).pack(anchor='w', pady=2)

    def _list_row(self, name: str, url: str, scope: str, row_bg: str, desc: str = ''):
        row = tk.Frame(self._list_frame, bg=row_bg, pady=5)
        row.pack(fill=tk.X, pady=1, padx=2)
        info = tk.Frame(row, bg=row_bg)
        info.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        tk.Label(info, text=name, font=('Segoe UI', 9, 'bold'),
                 fg=FG, bg=row_bg).pack(anchor='w')
        if desc:
            tk.Label(info, text=desc, font=('Segoe UI', 8),
                     fg=FG2, bg=row_bg).pack(anchor='w')
        masked = (url[:50] + '…') if len(url) > 50 else url
        tk.Label(info, text=masked, font=('Consolas', 8),
                 fg=FG3, bg=row_bg).pack(anchor='w')
        btns = tk.Frame(row, bg=row_bg)
        btns.pack(side=tk.RIGHT, padx=6)
        for lbl, color, cmd in [
            ('Test',   ACCENT,    lambda n=name, u=url: self._test(n, u)),
            ('Edit',   BG4,       lambda n=name, u=url, s=scope, d=desc: self._form_load(n, u, s, d)),
            ('Delete', '#6e2020', lambda n=name, s=scope: self._delete(n, s)),
        ]:
            b = tk.Label(btns, text=f' {lbl} ', font=('Segoe UI', 8),
                         fg='white', bg=color, cursor='hand2', padx=4, pady=2)
            b.pack(side=tk.LEFT, padx=2)
            b.bind('<Button-1>', lambda e, f=cmd: f())

    # ── Form actions ───────────────────────────────────────────────────────────

    def _form_clear(self):
        self._editing = None
        self._fname_var.set('')
        self._furl_var.set('')
        self._fdesc_var.set('')
        self._form_err.config(text='', fg=ERROR)
        self._form_title.config(text='Add Webhook')
        self._fname_ent.config(state='normal')
        self._git_note.pack_forget()

    def _form_load(self, name: str, url: str, scope: str, desc: str = ''):
        self._editing = (scope, name)
        self._scope_var.set(scope)
        self._on_scope_change()
        self._fname_var.set(name)
        self._furl_var.set(url)
        self._fdesc_var.set(desc)
        self._form_err.config(text='', fg=ERROR)
        self._form_title.config(text=f'Edit: {name}')
        self._fname_ent.config(state='disabled')
        self._git_note.pack_forget()

    def _form_save(self):
        name  = self._fname_var.get().strip().upper().replace(' ', '_')
        url   = self._furl_var.get().strip()
        scope = self._scope_var.get()
        desc  = self._fdesc_var.get().strip()
        if not name:
            self._form_err.config(text='Name is required', fg=ERROR); return
        if not re.match(r'^[A-Z][A-Z0-9_]*$', name):
            self._form_err.config(text='Name: letters, digits, underscores only', fg=ERROR); return
        if not url.startswith('https://chat.googleapis.com'):
            self._form_err.config(text='URL must start with https://chat.googleapis.com/...', fg=ERROR); return

        # If editing and scope changed, delete from old scope first
        if self._editing:
            old_scope, old_name = self._editing
            if old_scope != scope:
                if old_scope == 'personal':
                    _delete_personal(old_name)
                else:
                    _delete_system(old_name)

        if scope == 'personal':
            try:
                _save_personal(name, url)
            except PermissionError as e:
                self._form_err.config(text=str(e).split('\n')[0], fg=ERROR)
                from tkinter import messagebox
                messagebox.showerror('Permission Denied', str(e), parent=self)
                return
            self._form_err.config(text=f'Saved {name} (personal)', fg=SUCCESS)
            self._git_note.pack_forget()
            self._reload()
            self._form_clear()
        else:
            _save_system(name, url, desc)
            self._form_err.config(text=f'Saving {name}...', fg=FG2)
            self._reload()
            self._form_clear()
            self._auto_git_commit()

    def _form_test(self):
        url  = self._furl_var.get().strip()
        name = self._fname_var.get().strip() or 'form'
        if not url:
            self._form_err.config(text='Enter a URL to test', fg=ERROR); return
        if not url.startswith('https://chat.googleapis.com'):
            self._form_err.config(text='URL must start with https://chat.googleapis.com/...', fg=ERROR); return
        self._form_err.config(text='Sending test...', fg=FG2)
        def _do():
            ok, msg = _post_message(url, 'Auger webhook test: ' + name)
            self.after(0, lambda: self._form_err.config(
                text=('✅ ' if ok else '❌ ') + msg, fg=SUCCESS if ok else ERROR))
        threading.Thread(target=_do, daemon=True).start()

    def _delete(self, name: str, scope: str):
        if not messagebox.askyesno('Delete', f'Delete {scope} webhook "{name}"?', parent=self):
            return
        if scope == 'personal':
            _delete_personal(name)
            self._reload()
        else:
            _delete_system(name)
            self._reload()
            self._auto_git_commit()
        if self._editing and self._editing == (scope, name):
            self._form_clear()

    # ── Git helpers ────────────────────────────────────────────────────────────

    def _auto_git_commit(self):
        """If on a feature branch: commit + push system webhooks YAML automatically.
        Otherwise: show a manual reminder."""
        repo   = _find_git_root()
        if repo is None:
            self._git_note.config(
                text='  [!] Could not find git repo. Run: git add auger/data/gchat_webhooks.yaml && git commit',
                fg=WARN)
            self._git_note.pack(anchor='w', padx=8, pady=(2, 4))
            return
        branch = _get_current_branch(repo)
        if _is_feature_branch(branch):
            self._git_note.config(text=f'Committing & pushing to {branch}...', fg=FG2)
            self._git_note.pack(anchor='w', padx=8, pady=(2, 4))
            def _cb(ok, msg):
                self.after(0, lambda: self._git_note.config(
                    text=msg, fg=SUCCESS if ok else ERROR))
            _git_commit_push(repo, branch, _cb)
        elif branch:
            self._git_note.config(
                text=f'  [i] On branch "{branch}" (not a feature branch). '
                     f'Run: git add auger/data/gchat_webhooks.yaml && git commit && git push',
                fg=WARN)
            self._git_note.pack(anchor='w', padx=8, pady=(2, 4))
        else:
            self._git_note.config(
                text='  [i] Could not detect branch. Run: git add auger/data/gchat_webhooks.yaml && git commit',
                fg=WARN)
            self._git_note.pack(anchor='w', padx=8, pady=(2, 4))

    # ── Data ───────────────────────────────────────────────────────────────────

    def _reload(self):
        self._personal = _load_personal()
        self._system   = _load_system()
        self._reload_users()
        # Build dropdown: personal first then system, with scope prefix
        names = []
        for n in sorted(self._personal):
            names.append(f'👤 {n}')
        for n in sorted(self._system):
            names.append(f'🌐 {n}')
        self._target_cb['values'] = names
        if names and self._target_var.get() not in names:
            self._target_var.set(names[0])
        self._rebuild_list()

    def _url_for_target(self, display: str) -> str | None:
        name = display.lstrip('👤🌐 ').strip()
        if display.startswith('👤'):
            return self._personal.get(name)
        info = self._system.get(name)
        return (info['url'] if isinstance(info, dict) else info) if info else None

    def _test(self, name: str, url: str):
        self._set_status(f'Testing {name}…', FG2)
        def _do():
            ok, msg = _post_message(url, 'Auger webhook test: ' + name)
            self.after(0, lambda: self._set_status(
                ('✅ ' if ok else '❌ ') + name + ': ' + msg, SUCCESS if ok else ERROR))
        threading.Thread(target=_do, daemon=True).start()

    def _send(self):
        target = self._target_var.get().strip()
        text   = self._msg.get('1.0', 'end').strip()
        if not target:
            self._set_status('❌ Select a webhook', ERROR); return
        if not text:
            self._set_status('❌ Message is empty', ERROR); return
        url = self._url_for_target(target)
        if not url:
            self._set_status(f'❌ Webhook not found: {target}', ERROR); return
        self._set_status('Sending…', FG2)
        def _do():
            ok, msg = _post_message(url, text)
            self.after(0, lambda: self._set_status(
                ('✅ ' if ok else '❌ ') + msg, SUCCESS if ok else ERROR))
        threading.Thread(target=_do, daemon=True).start()

    def _set_status(self, msg: str, color: str = FG2):
        self._status.config(text=msg, fg=color)

    # ── Quick fill ─────────────────────────────────────────────────────────────

    def _fill_pr(self):
        try:
            import subprocess
            repo   = str(_auger_home() / 'repos' / 'auger-ai-sre-platform')
            branch = subprocess.run(['git','-C',repo,'branch','--show-current'],
                                    capture_output=True,text=True,timeout=5).stdout.strip()
            commit = subprocess.run(['git','-C',repo,'log','--oneline','-1'],
                                    capture_output=True,text=True,timeout=5).stdout.strip()
            text = (f'PR Review Request\nBranch: {branch}\nLast commit: {commit}\n'
                    f'https://github.helix.gsa.gov/assist/auger-ai-sre-platform/compare/{branch}\n'
                    f'Please review and approve')
        except Exception:
            text = 'PR Review Request\nBranch: \nPlease review and approve'
        self._set_text(text)

    def _fill_task(self):
        try:
            import sqlite3
            from auger.runtime import state_dir

            conn = sqlite3.connect(str(state_dir() / 'tasks.db'))
            row  = conn.execute("SELECT id,title,status FROM tasks WHERE status='in_progress' "
                                "ORDER BY updated_at DESC LIMIT 1").fetchone()
            conn.close()
            text = (f'Task #{row[0]}: {row[1]}\nStatus: {row[2]}' if row
                    else 'No task currently in_progress')
        except Exception:
            text = 'Current task: '
        self._set_text(text)

    def _fill_invite(self):
        self._set_text('Auger SRE Platform - Alpha\n'
                       'Get started: https://github.helix.gsa.gov/assist/auger-ai-sre-platform\n'
                       'Run bash auger-launch.sh to install.\nQuestions? Ask in this space')

    def _set_text(self, text: str):
        self._msg.delete('1.0', 'end')
        self._msg.insert('1.0', text)
