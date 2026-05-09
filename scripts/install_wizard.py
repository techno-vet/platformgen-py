#!/usr/bin/env python3
"""
PlatformGen — Install Wizard

Standalone Tk GUI for first-time setup. Runs on the host (no Docker required).

Usage:
    python3 scripts/install_wizard.py

Requirements (host): Python 3.8+, tkinter (Docker optional)
No pip installs needed — stdlib only.
"""
# -- GTK font env cleanup (prevents blank labels on some Ubuntu desktops) ------
import os
for _var in ("GTK_PATH", "GTK_DATA_PREFIX", "GTK_EXE_PREFIX", "GTK_MODULES"):
    os.environ.pop(_var, None)

import sys
import subprocess
import threading
import queue
import re
import urllib.request
import urllib.error
import urllib.parse
import shutil
from pathlib import Path

# -- Paths ---------------------------------------------------------------------
SCRIPT_DIR   = Path(__file__).resolve().parent
REPO_DIR     = SCRIPT_DIR.parent
APP_NAME     = os.environ.get("PLATFORMGEN_APP_NAME") or os.environ.get("AUGER_APP_NAME", "PlatformGen")
ASSISTANT_NAME = os.environ.get("PLATFORMGEN_ASSISTANT_NAME") or os.environ.get("AUGER_ASSISTANT_NAME", "Genny")
AUGER_DIR    = Path(
    os.environ.get("PLATFORMGEN_HOME")
    or os.environ.get("AUGER_HOME")
    or str(Path.home() / ".platformgen")
).expanduser()
DAEMON_PORT  = int(os.environ.get("PLATFORMGEN_DAEMON_PORT") or os.environ.get("AUGER_DAEMON_PORT") or "7438")
ENV_FILE     = AUGER_DIR / ".env"
ENV_TEMPLATE = REPO_DIR / ".env.example"
LAUNCH_SH    = SCRIPT_DIR / "platformgen-launch.sh"
ART_REGISTRY = "artifactory.helix.gsa.gov"
RUNTIME_IMAGE = (
    os.environ.get("PLATFORMGEN_IMAGE")
    or os.environ.get("AUGER_IMAGE")
    or f"{ART_REGISTRY}/gs-assist-docker-repo/auger-platform:20260311"
)
GHE_HOST = "github.helix.gsa.gov"
GHE_URL = f"https://{GHE_HOST}"
GHE_API_USER = f"{GHE_URL}/api/v3/user"

# Candidate locations for astutl config (checked in priority order)
ASTUTL_CANDIDATES = [
    Path.home() / ".astutl" / "astutl_secure_config.env",                              # installed AU Gold
    Path.home() / "repos" / "devtools-scripts" / "au-silver" / "config" / ".astutl" / "astutl_secure_config.env",
    Path.home() / "repos" / "devtools-scripts" / "astutl"   / "config" / ".astutl" / "astutl_secure_config.env",
    Path.home() / "repos" / "devtool-scripts-orig" / "au-silver" / "config" / ".astutl" / "astutl_secure_config.env",
    Path.home() / "repos" / "devtools-scripts-6.1" / "au-silver" / "config" / ".astutl" / "astutl_secure_config.env",
]

# Maps astutl key name -> runtime .env key name (+ optional display label for logging)
# "~" means "copy only if destination is not already set"
ASTUTL_KEY_MAP = {
    # Artifactory
    "ARTIFACTORY_IDENTITY_TOKEN": "ARTIFACTORY_IDENTITY_TOKEN",
    "ARTIFACTORY_USER":           "ARTIFACTORY_USERNAME",       # astutl uses _USER, runtime uses _USERNAME
    "ARTIFACTORY_PASSWORD":       "ARTIFACTORY_PASSWORD",
    # GitHub / Copilot (github.com)
    "GH_TOKEN":                   "GH_TOKEN",
    "GH_CLI_PAT":                 "GH_TOKEN",                   # fallback source; won't overwrite GH_TOKEN
    # GitHub Enterprise (github.helix.gsa.gov)
    "GH_ENTERPRISE_TOKEN":        "GHE_TOKEN",
    "GSA_EMAIL":                  "GHE_USERNAME",
    # Jira
    "JIRA_PAT":                   "JIRA_API_TOKEN",
    # Jenkins
    "JENKINS_API_KEY":            "JENKINS_API_TOKEN",
    # DataDog  (astutl uses DD_*, runtime uses DATADOG_*)
    "DD_API_KEY":                 "DATADOG_API_KEY",
    "DD_APP_KEY":                 "DATADOG_APP_KEY",
    # Rancher
    "RANCHER_BEARER_TOKEN":       "RANCHER_BEARER_TOKEN",
    # AWS per-env buckets -> runtime stores as AWS_1/2/3/4 slots
    # DEV / TEST / STAGING / PROD → slots 1-4
    "DEV_S3_AWS_ACCESS_KEY_ID":       "AWS_1_ACCESS_KEY_ID",
    "DEV_S3_AWS_SECRET_ACCESS_KEY":   "AWS_1_SECRET_ACCESS_KEY",
    "TEST_S3_AWS_ACCESS_KEY_ID":      "AWS_2_ACCESS_KEY_ID",
    "TEST_S3_AWS_SECRET_ACCESS_KEY":  "AWS_2_SECRET_ACCESS_KEY",
    "STAGING_S3_AWS_ACCESS_KEY_ID":   "AWS_3_ACCESS_KEY_ID",
    "STAGING_S3_AWS_SECRET_ACCESS_KEY": "AWS_3_SECRET_ACCESS_KEY",
    "PROD_S3_AWS_ACCESS_KEY_ID":      "AWS_4_ACCESS_KEY_ID",
    "PROD_S3_AWS_SECRET_ACCESS_KEY":  "AWS_4_SECRET_ACCESS_KEY",
    # Cryptkeeper per-env keys
    "DEV_CRYPTKEEPER_KEY":      "DEV_CRYPTKEEPER_KEY",
    "TEST_CRYPTKEEPER_KEY":     "TEST_CRYPTKEEPER_KEY",
    "STAGING_CRYPTKEEPER_KEY":  "STAGING_CRYPTKEEPER_KEY",
    "PROD_CRYPTKEEPER_KEY":     "PROD_CRYPTKEEPER_KEY",
    "LOCAL_CRYPTKEEPER_KEY":    "LOCAL_CRYPTKEEPER_KEY",
}

# -- Theme (matches the PlatformGen dark theme) --------------------------------
BG     = "#1e1e1e"
BG2    = "#2d2d2d"
FG     = "#d4d4d4"
GREEN  = "#4ec9b0"
YELLOW = "#dcdcaa"
RED    = "#f44747"
BLUE   = "#569cd6"
ORANGE = "#ce9178"
DIM    = "#6a6a6a"
ACCENT = "#007acc"
FONT   = ("Segoe UI", 10)
MFONT  = ("Consolas", 10)
ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
OSC_ESCAPE_RE = re.compile(r"\x1B\][^\x07]*(?:\x07|\x1B\\)")


# -- Wizard Window -------------------------------------------------------------

class WizardWindow:
    def __init__(self):
        import tkinter as tk
        from tkinter import scrolledtext
        self._tk = tk
        self._ui_queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} - Setup")
        self.root.geometry("720x560")
        self.root.configure(bg=BG)
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Force window to front so it's not hidden behind other windows
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after(500, lambda: self.root.attributes('-topmost', False))
        self._setup_running = True
        self._build_ui()
        self.root.after(50, self._drain_ui_queue)

    def _build_ui(self):
        tk = self._tk
        from tkinter import scrolledtext

        # -- Header ---------------------------------------------------------
        hdr = tk.Frame(self.root, bg=ACCENT, pady=10)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr, text=f"{APP_NAME} - First-Time Setup",
            bg=ACCENT, fg="white", font=("Segoe UI", 13, "bold"),
        ).pack(side=tk.LEFT, padx=16)

        # -- Log / chat area ------------------------------------------------
        self.log = scrolledtext.ScrolledText(
            self.root, bg=BG, fg=FG, font=MFONT,
            relief=tk.FLAT, wrap=tk.WORD, state=tk.DISABLED,
            padx=14, pady=10, insertbackground=FG,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        for name, fg_col, extra in [
            ("ok",     GREEN,  {}),
            ("err",    RED,    {}),
            ("warn",   YELLOW, {}),
            ("info",   BLUE,   {}),
            ("dim",    DIM,    {}),
            ("orange", ORANGE, {}),
            ("h2",     BLUE,   {"font": ("Segoe UI", 11, "bold")}),
            ("bold",   FG,     {"font": ("Consolas", 10, "bold")}),
        ]:
            self.log.tag_configure(name, foreground=fg_col, **extra)

        # -- Bottom bar -----------------------------------------------------
        bottom = tk.Frame(self.root, bg=BG2, pady=6)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_var = tk.StringVar(value="Initializing...")
        tk.Label(
            bottom, textvariable=self.status_var,
            bg=BG2, fg=DIM, font=("Segoe UI", 9), anchor="w",
        ).pack(side=tk.LEFT, padx=12, fill=tk.X, expand=True)

        self.close_btn = tk.Button(
            bottom, text="Close", command=self.root.destroy,
            bg=ACCENT, fg="white", font=("Segoe UI", 10),
            relief=tk.FLAT, padx=18, pady=4,
            state=tk.DISABLED, cursor="hand2",
        )
        self.close_btn.pack(side=tk.RIGHT, padx=12)

    def _on_close(self):
        self.root.destroy()

    # -- Thread-safe UI helpers ------------------------------------------------

    @staticmethod
    def _sanitize_text(text):
        if text is None:
            return ""
        cleaned = str(text).replace("\r", "\n").replace("\b", "")
        cleaned = ANSI_ESCAPE_RE.sub("", cleaned)
        cleaned = OSC_ESCAPE_RE.sub("", cleaned)
        cleaned = cleaned.translate(str.maketrans({
            "\u2705": "[OK]",
            "\u274c": "[ERROR]",
            "\u26a0": "[WARN]",
            "\u2139": "[INFO]",
            "\U0001f4a1": "[INFO]",
            "\U0001f4e6": "[PKG]",
            "\U0001f510": "[LOCK]",
            "\U0001f916": "[TRAY]",
            "\U0001f529": "[SETUP]",
            "\U0001f40d": "[PY]",
            "\U0001f680": "[START]",
            "\ufe0f": "",
            "\u2014": "-",
            "\u2013": "-",
            "\u2026": "...",
            "\u2018": "'",
            "\u2019": "'",
            "\u201c": '"',
            "\u201d": '"',
        }))
        cleaned = cleaned.encode("ascii", "replace").decode("ascii")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned

    def _dispatch_ui(self, fn):
        self._ui_queue.put(fn)

    def _drain_ui_queue(self):
        while True:
            try:
                fn = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            fn()
        if self.root.winfo_exists():
            self.root.after(50, self._drain_ui_queue)

    def log_line(self, text, tag=None):
        """Append one line to the log."""
        text = self._sanitize_text(text)
        def _do():
            self.log.configure(state="normal")
            if tag:
                self.log.insert("end", text + "\n", tag)
            else:
                self.log.insert("end", text + "\n")
            self.log.configure(state="disabled")
            self.log.see("end")
        self._dispatch_ui(_do)

    def log_inline(self, text, tag=None):
        """Append text without a trailing newline."""
        text = self._sanitize_text(text)
        def _do():
            self.log.configure(state="normal")
            if tag:
                self.log.insert("end", text, tag)
            else:
                self.log.insert("end", text)
            self.log.configure(state="disabled")
            self.log.see("end")
        self._dispatch_ui(_do)

    def set_status(self, msg):
        msg = self._sanitize_text(msg)
        self._dispatch_ui(lambda: self.status_var.set(msg))

    def open_link(self, label: str, url: str):
        """Append a clickable hyperlink button to the log area."""
        def _add():
            import webbrowser
            tk = self._tk
            btn = tk.Label(
                self.log,
                text=f"  -> {label}: {url}",
                fg="#4ec9b0", bg="#1e1e1e",
                cursor="hand2",
                font=("Consolas", 9, "underline"),
            )
            btn.bind("<Button-1>", lambda _e: webbrowser.open(url))
            self.log.window_create(tk.END, window=btn)
            self.log.insert(tk.END, "\n")
            self.log.see(tk.END)
        self._dispatch_ui(_add)

    def ask_secret(self, prompt, title=f"{APP_NAME} Setup"):
        from tkinter import simpledialog
        result  = [None]
        ev      = threading.Event()
        def _ask():
            result[0] = simpledialog.askstring(title, prompt, show="*", parent=self.root)
            ev.set()
        self._dispatch_ui(_ask)
        ev.wait()
        return result[0] or ""

    def ask_text(self, prompt, title=f"{APP_NAME} Setup"):
        """Modal plain-text dialog — blocks the background thread."""
        from tkinter import simpledialog
        result  = [None]
        ev      = threading.Event()
        def _ask():
            result[0] = simpledialog.askstring(title, prompt, parent=self.root)
            ev.set()
        self._dispatch_ui(_ask)
        ev.wait()
        return result[0] or ""

    def mark_done(self, success=True):
        self._setup_running = False
        def _finish():
            self.close_btn.configure(state="normal")
            if success:
                self.status_var.set(f"Setup complete - {APP_NAME} is running")
                self.root.after(1500, lambda: self.root.winfo_exists() and self.root.destroy())
            else:
                self.status_var.set("Setup incomplete - see messages above")
        self._dispatch_ui(_finish)

    def run(self):
        t = threading.Thread(target=_run_setup, args=(self,), daemon=True)
        t.start()
        self.root.mainloop()


# -- Credential helpers --------------------------------------------------------

def _read_env_key(path, key):
    if not path or not path.exists():
        return ""
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith(f"{key}="):
            return line[len(key) + 1:].strip().strip("'\"")
    return ""


def _set_env_key(key, val):
    AUGER_DIR.mkdir(parents=True, exist_ok=True)
    if not ENV_FILE.exists():
        ENV_FILE.touch(mode=0o600)
    lines   = ENV_FILE.read_text(errors="replace").splitlines()
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={val}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={val}")
    ENV_FILE.write_text("\n".join(new_lines) + "\n")
    ENV_FILE.chmod(0o600)


def _seed_env_template():
    AUGER_DIR.mkdir(parents=True, exist_ok=True)
    if ENV_FILE.exists() and ENV_FILE.read_text(errors="replace").strip():
        ENV_FILE.chmod(0o600)
        return False
    if ENV_TEMPLATE.exists():
        ENV_FILE.write_text(ENV_TEMPLATE.read_text(errors="replace"))
    else:
        ENV_FILE.touch(mode=0o600)
    ENV_FILE.chmod(0o600)
    return True


def _update_bashrc_path():
    """Add ~/.local/bin to PATH in ~/.bashrc if not already present."""
    bashrc = Path.home() / ".bashrc"
    path_export = 'export PATH="$HOME/.local/bin:$PATH"'
    
    if not bashrc.exists():
        bashrc.write_text(f"# {APP_NAME}\n{path_export}\n")
        return True
    
    content = bashrc.read_text(errors="replace")
    if "$HOME/.local/bin" in content or "~/.local/bin" in content:
        return False  # Already present
    
    # Add at the end if not present
    if not content.endswith("\n"):
        content += "\n"
    content += f"\n# {APP_NAME}\n{path_export}\n"
    bashrc.write_text(content)
    return True


def _gh_token_valid(token):
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "auger-install-wizard/1.0",
            },
        )
        # Bypass corporate proxy for external calls
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=8) as resp:
            return resp.status == 200
    except Exception:
        return False


def _ghe_token_valid(token):
    try:
        req = urllib.request.Request(
            GHE_API_USER,
            headers={
                "Authorization": f"token {token}",
                "User-Agent": "auger-install-wizard/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception:
        return False


def _art_login_valid(user, key):
    try:
        login = subprocess.run(
            ["docker", "login", ART_REGISTRY, "-u", user, "--password-stdin"],
            input=key.encode(),
            capture_output=True,
            timeout=25,
        )
        if login.returncode != 0:
            return False
        inspect = subprocess.run(
            ["docker", "manifest", "inspect", RUNTIME_IMAGE],
            capture_output=True,
            timeout=30,
        )
        return inspect.returncode == 0
    except Exception:
        return False


def _docker_runtime_state():
    docker_bin = shutil.which("docker")
    if not docker_bin:
        return "missing", "docker not installed"
    try:
        result = subprocess.run(
            ["docker", "ps"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return "ok", ""
        detail = (result.stderr or result.stdout or "").strip()
        detail = detail.splitlines()[-1] if detail else "docker ps failed"
        return "unusable", detail
    except Exception as exc:
        return "unusable", str(exc)


def _find_host_auger_bin():
    candidates = [
        shutil.which("auger"),
        shutil.which("genny"),
        shutil.which("platformgen"),
        str(Path.home() / ".local" / "bin" / "auger"),
        str(Path.home() / ".local" / "bin" / "genny"),
        str(Path.home() / ".local" / "bin" / "platformgen"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def _find_host_copilot_bin():
    candidates = [
        shutil.which("copilot"),
        str(Path.home() / ".local" / "bin" / "copilot"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return ""


def _install_host_auger():
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    user_bin = str(Path.home() / ".local" / "bin")
    env["PATH"] = f"{user_bin}:{env.get('PATH', '')}" if env.get("PATH") else user_bin
    cmd = [sys.executable, "-m", "pip", "install", "--user", "--upgrade", str(REPO_DIR)]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
    except Exception as exc:
        return exc


def _install_host_copilot():
    env = os.environ.copy()
    user_bin = str(Path.home() / ".local" / "bin")
    env["PATH"] = f"{user_bin}:{env.get('PATH', '')}" if env.get("PATH") else user_bin
    cmd = [
        "bash",
        "-lc",
        "curl -fsSL https://gh.io/copilot-install | bash",
    ]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )
    except Exception as exc:
        return exc


def _choose_valid_art_secret(user, identity_token=""):
    """Return the identity token if it can read the runtime image."""
    if identity_token and _art_login_valid(user, identity_token):
        return identity_token, "Identity Token"
    return "", ""


def _read_gh_hosts_token(hostname):
    gh_cfg = Path.home() / ".config" / "gh" / "hosts.yml"
    if not gh_cfg.exists():
        return ""
    current_host = ""
    for raw in gh_cfg.read_text(errors="replace").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")) and line.endswith(":"):
            current_host = line[:-1].strip()
            continue
        if current_host == hostname:
            stripped = line.strip()
            if stripped.startswith(("oauth_token:", "token:")):
                return stripped.split(":", 1)[1].strip().strip("'\"")
    return ""


def _read_git_credential_token(hostname):
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost={hostname}\n".encode(),
            capture_output=True,
            timeout=5,
            env=env,
        )
        for line in r.stdout.decode(errors="replace").splitlines():
            if line.startswith("password="):
                return line[9:].strip()
    except Exception:
        pass
    return ""


def _detect_gh_token():
    """Returns (token, source) — empty strings if nothing found."""
    # 1. Already saved
    tok = _read_env_key(ENV_FILE, "GH_TOKEN")
    if tok:
        return tok, "~/.platformgen/.env"

    # 2. gh CLI
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip(), "gh CLI"
    except Exception:
        pass

    # 3. Environment variables
    for var in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"):
        val = os.environ.get(var, "")
        if val:
            return val, f"${var}"

    # 4. gh config file
    tok = _read_gh_hosts_token("github.com")
    if tok:
        return tok, "~/.config/gh/hosts.yml"

    # 5. git credential store (only classic/fine-grained PATs)
    tok = _read_git_credential_token("github.com")
    if tok and tok.startswith(("ghp_", "github_pat_", "github_pat_")):
        return tok, "git credential store"

    # 6. astutl devtools config (GH_TOKEN or GH_CLI_PAT)
    astutl = _find_astutl_file()
    if astutl:
        for key in ("GH_TOKEN", "GH_CLI_PAT"):
            val = _read_env_key(astutl, key)
            if val:
                short = str(astutl).replace(str(Path.home()), "~")
                return val, f"astutl ({key})"

    return "", ""


def _detect_ghe_token():
    """Returns (token, source) — empty strings if nothing found."""
    tok = _read_env_key(ENV_FILE, "GHE_TOKEN")
    if tok:
        return tok, "~/.platformgen/.env"

    for var in ("GHE_TOKEN", "GH_ENTERPRISE_TOKEN"):
        val = os.environ.get(var, "")
        if val:
            return val, f"${var}"

    try:
        r = subprocess.run(
            ["gh", "auth", "token", "--hostname", GHE_HOST],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip(), f"gh CLI ({GHE_HOST})"
    except Exception:
        pass

    tok = _read_gh_hosts_token(GHE_HOST)
    if tok:
        return tok, "~/.config/gh/hosts.yml"

    tok = _read_git_credential_token(GHE_HOST)
    if tok:
        return tok, "git credential store"

    astutl = _find_astutl_file()
    if astutl:
        tok = _read_env_key(astutl, "GH_ENTERPRISE_TOKEN")
        if tok:
            return tok, "astutl (GH_ENTERPRISE_TOKEN)"

    return "", ""


def _find_astutl_file():
    """Return the first existing astutl_secure_config.env path, or None."""
    for p in ASTUTL_CANDIDATES:
        if p.exists():
            return p
    return None


def _import_from_astutl(astutl_path):
    """
    Read astutl_secure_config.env and copy known keys to ~/.platformgen/.env.
    Only writes a key if the destination is not already set.
    Returns list of (auger_key, astutl_key) pairs that were imported.
    """
    imported = []
    for astutl_key, auger_key in ASTUTL_KEY_MAP.items():
        val = _read_env_key(astutl_path, astutl_key)
        if not val:
            continue
        existing = _read_env_key(ENV_FILE, auger_key)
        if existing:
            continue  # already set — don't overwrite
        _set_env_key(auger_key, val)
        imported.append((auger_key, astutl_key))
    return imported


def _detect_art_creds():
    """Returns (username, identity_token, source) — empty strings if nothing found."""
    user = (
        _read_env_key(ENV_FILE, "ARTIFACTORY_USERNAME")
        or _read_env_key(ENV_FILE, "ARTIFACTORY_USER")
        or os.environ.get("ARTIFACTORY_USERNAME", "")
        or os.environ.get("ARTIFACTORY_USER", "")
    )
    it = _read_env_key(ENV_FILE, "ARTIFACTORY_IDENTITY_TOKEN") or os.environ.get("ARTIFACTORY_IDENTITY_TOKEN", "")
    if user and it:
        return user, it, "~/.platformgen/.env / environment"

    astutl = _find_astutl_file()
    if astutl:
        # astutl uses ARTIFACTORY_USER (not _USERNAME)
        u  = _read_env_key(astutl, "ARTIFACTORY_USER") or _read_env_key(astutl, "ARTIFACTORY_USERNAME")
        it = _read_env_key(astutl, "ARTIFACTORY_IDENTITY_TOKEN")
        if u and it:
            return u, it, f"astutl ({astutl.parent.parent.name})"

    return "", "", ""


# -- Main setup flow -----------------------------------------------------------

def _run_setup(wiz):
    w = wiz

    w.log_line("")
    w.log_line(f"  {APP_NAME} — Setting up your environment", "bold")
    w.log_line("")

    seeded_template = _seed_env_template()
    if seeded_template:
        w.log_line("  Seeded ~/.platformgen/.env from .env.example so it can be pre-filled before onboarding.", "dim")
        w.log_line("")

    # Load GHE_URL from .env if set, otherwise use default
    global GHE_HOST, GHE_URL, GHE_API_USER
    env_ghe_url = _read_env_key(ENV_FILE, "GHE_URL")
    if env_ghe_url:
        GHE_URL = env_ghe_url.rstrip("/")
        # Extract hostname from URL (e.g., https://github.com -> github.com)
        try:
            parsed = urllib.parse.urlparse(GHE_URL)
            GHE_HOST = parsed.netloc or parsed.path.split("/")[0]
        except Exception:
            GHE_HOST = "github.com"  # fallback
    # API endpoint: github.com uses api.github.com, GHE uses ghe.host/api/v3
    if GHE_HOST == "github.com":
        GHE_API_USER = "https://api.github.com/user"
    else:
        GHE_API_USER = f"{GHE_URL}/api/v3/user"

    # =======================================================================
    # STEP 0 — Bulk import from astutl (AU Gold devtools)
    # =======================================================================
    astutl_path = _find_astutl_file()
    if astutl_path:
        w.log_line("  -- Step 0: AU Gold Credential Import ------------------", "h2")
        short = str(astutl_path).replace(str(Path.home()), "~")
        w.log_inline(f"  Found {short} — importing credentials… ")
        imported = _import_from_astutl(astutl_path)
        if imported:
            w.log_line(f"[OK]  {len(imported)} key(s) imported", "ok")
            # Group by service for readable output
            service_groups = {}
            for auger_key, astutl_key in imported:
                svc = auger_key.split("_")[0]
                service_groups.setdefault(svc, []).append(auger_key)
            for svc, keys in sorted(service_groups.items()):
                w.log_line(f"    {svc}: {', '.join(keys)}", "dim")
        else:
            w.log_line("(all keys already set — nothing new to import)", "dim")
        w.log_line("")

    # =======================================================================
    # STEP 1 — GitHub Copilot token
    # =======================================================================
    w.log_line("  -- Step 1: GitHub Copilot Token ----------------------", "h2")
    w.set_status("Checking GitHub Copilot token…")

    gh_tok, gh_src = _detect_gh_token()
    gh_ok = False

    if gh_tok:
        w.log_inline(f"  Found token via {gh_src} — verifying… ")
        if _gh_token_valid(gh_tok):
            w.log_line("[OK]  valid", "ok")
            _set_env_key("GH_TOKEN", gh_tok)
            gh_ok = True
        else:
            w.log_line("[ERROR]  rejected by github.com", "err")
            gh_tok = ""
    else:
        w.log_line("  No GitHub token found automatically.", "warn")

    while not gh_ok:
        w.log_line("")
        w.log_line(f"  A github.com Fine-Grained Personal Access Token is required for Ask {ASSISTANT_NAME}.", "dim")
        w.log_line("  1. Go to: https://github.com/settings/personal-access-tokens/new", "dim")
        w.log_line("  2. Click 'Generate new token (fine-grained)'", "dim")
        w.log_line("  3. Permission required: [OK] Copilot > Copilot requests (read-only)", "dim")
        w.log_line(f"     (No other scopes needed for Ask {ASSISTANT_NAME}; classic PATs/ghp_ tokens will fail)", "dim")
        w.open_link("Open Fine-Grained GitHub token page", "https://github.com/settings/personal-access-tokens/new")
        w.log_line("")
        tok = w.ask_secret(
            "Paste your github.com Fine-Grained Personal Access Token\n\n"
            "Create one at:\n"
            "https://github.com/settings/personal-access-tokens/new\n\n"
            "Required permission: Copilot > Copilot requests (read-only)\n\n"
            "Classic Personal Access Tokens (ghp_) are not supported by Copilot.\n\n"
            f"Leave blank to skip — Ask {ASSISTANT_NAME} won't work until GH_TOKEN is set.",
            title="GitHub Copilot Token",
        )
        if not tok:
            w.log_line(f"  [WARN]  Skipped — Ask {ASSISTANT_NAME} will not function until GH_TOKEN is added.", "warn")
            w.log_line("      Edit ~/.platformgen/.env to add it later.", "dim")
            break
        w.log_inline("  Verifying… ")
        if _gh_token_valid(tok):
            w.log_line("[OK]  valid", "ok")
            _set_env_key("GH_TOKEN", tok)
            gh_ok = True
        else:
            w.log_line("[ERROR]  github.com rejected that token — check scopes and try again", "err")

    w.log_line("")

    # =======================================================================
    # STEP 1b — Enterprise GitHub token
    # =======================================================================
    w.log_line("  -- Step 1b: Enterprise GitHub Token ------------------", "h2")
    w.set_status("Checking Enterprise GitHub token…")

    ghe_tok, ghe_src = _detect_ghe_token()
    ghe_ok = False

    if ghe_tok:
        w.log_inline(f"  Found token via {ghe_src} — verifying against {GHE_HOST}… ")
        if _ghe_token_valid(ghe_tok):
            w.log_line("[OK]  valid", "ok")
            _set_env_key("GHE_URL", GHE_URL)
            _set_env_key("GHE_TOKEN", ghe_tok)
            ghe_ok = True
        else:
            w.log_line("[ERROR]  rejected by github.helix.gsa.gov", "err")
            ghe_tok = ""
    else:
        w.log_line("  No Enterprise GitHub token found automatically.", "warn")

    while not ghe_ok:
        w.log_line("")
        w.log_line(f"  A {GHE_HOST} token powers the GitHub widget, Prospector, and HTTPS git flows inside {APP_NAME}.", "dim")
        w.log_line(f"  If you cloned with VS Code or browser auth, {APP_NAME} still needs a separate GHE token in ~/.platformgen/.env.", "dim")
        w.log_line(f"  Get it at: {GHE_URL}/settings/tokens", "dim")
        w.log_line("  Recommended scopes: repo  read:user", "dim")
        w.open_link("Open Enterprise GitHub token page", f"{GHE_URL}/settings/tokens")
        w.log_line("")
        tok = w.ask_secret(
            f"Paste your {GHE_HOST} Personal Access Token\n\n"
            "Create one at:\n"
            f"{GHE_URL}/settings/tokens\n\n"
            "Recommended scopes: repo, read:user\n\n"
            "Leave blank to skip — GitHub/Prospector features will stay limited until GHE_TOKEN is set.",
            title="Enterprise GitHub Token",
        )
        if not tok:
            w.log_line("  [WARN]  Skipped — GitHub Enterprise features will remain limited until GHE_TOKEN is added.", "warn")
            w.log_line("      Edit ~/.platformgen/.env to add it later.", "dim")
            break
        w.log_inline(f"  Verifying against {GHE_HOST}… ")
        if _ghe_token_valid(tok):
            w.log_line("[OK]  valid", "ok")
            _set_env_key("GHE_URL", GHE_URL)
            _set_env_key("GHE_TOKEN", tok)
            ghe_ok = True
        else:
            w.log_line(f"[ERROR]  {GHE_HOST} rejected that token — check scopes and try again", "err")

    w.log_line("")

    # =======================================================================
    # STEP 1c — Host auger CLI
    # =======================================================================
    w.log_line(f"  -- Step 1c: Host {APP_NAME} CLI ---------------------------", "h2")
    w.set_status(f"Checking host {APP_NAME} CLI…")

    host_auger = _find_host_auger_bin()
    host_copilot = _find_host_copilot_bin()
    if host_auger:
        w.log_line(f"  [OK]  Host {APP_NAME} CLI already available at {host_auger}", "ok")
    elif gh_ok:
        w.log_line(f"  [PKG]  Installing host {APP_NAME} CLI so Ask {ASSISTANT_NAME} works from any terminal…", "dim")
        install_result = _install_host_auger()
        if isinstance(install_result, Exception):
            w.log_line(f"  [WARN]  Host auger install error: {install_result}", "warn")
            w.log_line("      You can retry later with: python3 -m pip install --user --upgrade .", "dim")
        elif install_result.returncode == 0:
            host_auger = _find_host_auger_bin()
            if host_auger:
                w.log_line(f"  [OK]  Host {APP_NAME} CLI installed at {host_auger}", "ok")
            else:
                w.log_line(f"  [WARN]  pip reported success but ~/.local/bin/{ASSISTANT_NAME.lower()} or platformgen was not found", "warn")
                w.log_line("      Retry later with: python3 -m pip install --user --upgrade .", "dim")
        else:
            err = (install_result.stderr or install_result.stdout or "").strip()
            w.log_line(f"  [WARN]  Host {APP_NAME} install failed — continuing with platform setup", "warn")
            if err:
                w.log_line(f"      {err.splitlines()[-1]}", "dim")
            w.log_line("      Retry later with: python3 -m pip install --user --upgrade .", "dim")
    else:
        w.log_line(f"  [WARN]  Skipping host {APP_NAME} install because no valid GitHub token is configured yet.", "warn")

    host_auger = _find_host_auger_bin()
    if host_copilot:
        w.log_line(f"  [OK]  Host copilot CLI already available at {host_copilot}", "ok")
    elif host_auger:
        w.log_line(f"  [PKG]  Installing standalone Copilot CLI required by terminal {APP_NAME.lower()}…", "dim")
        copilot_result = _install_host_copilot()
        if isinstance(copilot_result, Exception):
            w.log_line(f"  [WARN]  Host copilot install error: {copilot_result}", "warn")
            w.log_line("      Retry later with: curl -fsSL https://gh.io/copilot-install | bash", "dim")
        elif copilot_result.returncode == 0:
            host_copilot = _find_host_copilot_bin()
            if host_copilot:
                w.log_line(f"  [OK]  Host copilot CLI installed at {host_copilot}", "ok")
            else:
                w.log_line("  [WARN]  Copilot installer reported success but ~/.local/bin/copilot was not found", "warn")
                w.log_line("      Retry later with: curl -fsSL https://gh.io/copilot-install | bash", "dim")
        else:
            err = (copilot_result.stderr or copilot_result.stdout or "").strip()
            w.log_line(f"  [WARN]  Host copilot CLI install failed — terminal Ask {ASSISTANT_NAME} may not work yet", "warn")
            if err:
                w.log_line(f"      {err.splitlines()[-1]}", "dim")
            w.log_line("      Retry later with: curl -fsSL https://gh.io/copilot-install | bash", "dim")
    else:
        w.log_line(f"  [WARN]  Skipping host copilot install until host {APP_NAME} CLI is available.", "warn")

    w.log_line("")

    # =======================================================================
    # STEP 2 — Runtime mode
    # =======================================================================
    w.log_line("  -- Step 2: Runtime Mode ------------------------------", "h2")
    w.set_status(f"Selecting {APP_NAME} runtime...")

    docker_state, docker_detail = _docker_runtime_state()
    launch_mode = "venv"
    if docker_state == "ok":
        w.log_line("  Two launch modes are available on this system:", "dim")
        w.log_line(f"    1. {APP_NAME}      - host/venv mode, fast startup, recommended for most users", "dim")
        w.log_line(f"    2. {APP_NAME} SRE  - Docker mode, full SRE/container sandbox", "dim")
        choice = (w.ask_text(
            "Choose launch mode:\n\n"
            f"1. {APP_NAME} (host/venv, recommended for most users)\n"
            f"2. {APP_NAME} SRE (Docker / full SRE sandbox)\n\n"
            "Press Enter for 1.",
            title=f"Choose {APP_NAME} Runtime",
        ) or "").strip().lower()
        if choice in {"2", "docker", "sre", "auger sre"}:
            launch_mode = "docker"
            w.log_line(f"  [OK] Selected {APP_NAME} SRE (Docker mode).", "ok")
        else:
            launch_mode = "venv"
            w.log_line(f"  [OK] Selected {APP_NAME} host mode (venv).", "ok")
    elif docker_state == "unusable":
        w.log_line("  Docker is installed but not usable from this account/session.", "warn")
        w.log_line(f"      {docker_detail}", "dim")
        w.log_line(f"  [OK] Continuing with {APP_NAME} host mode (venv) so Docker access is not required.", "ok")
    else:
        w.log_line("  Docker not found on this system.", "dim")
        w.log_line(f"  [OK] Continuing with {APP_NAME} host mode (venv).", "ok")

    if launch_mode == "docker":
        w.log_line("")
        w.log_line("  -- Step 2b: SRE Base Image Strategy -----------------", "h2")
        w.set_status(f"Preparing local {APP_NAME} base image build...")

        art_user, art_it, art_src = _detect_art_creds()
        if art_user and art_it and "astutl" in art_src:
            _set_env_key("ARTIFACTORY_USERNAME", art_user)
            _set_env_key("ARTIFACTORY_IDENTITY_TOKEN", art_it)
            w.log_line(f"  Found saved Artifactory credentials via {art_src}.", "dim")
            w.log_line("  Credentials were copied into ~/.platformgen/.env for later non-installer launches.", "dim")
        elif art_user and art_it:
            w.log_line(f"  Found saved Artifactory credentials via {art_src}.", "dim")
            w.log_line("  Keeping them available for later non-installer launches.", "dim")
        else:
            w.log_line("  No saved Artifactory Docker pull credentials detected.", "dim")

        w.log_line(f"  [OK] Install Wizard will always build the {APP_NAME} base image locally from this checkout.", "ok")
        w.log_line("      This keeps your local test path aligned with what early adopters should validate from main.", "dim")
        w.log_line("      If the local base image is already current for this checkout, platformgen-launch.sh will reuse it.", "dim")
        w.log_line("      Otherwise it will rebuild locally at reduced CPU/I/O priority.", "dim")
    else:
        w.log_line(f"  Host mode uses {AUGER_DIR}/venv and launches {APP_NAME} directly on this machine.", "dim")
        w.log_line(f"  If Docker is installed later, Ask {ASSISTANT_NAME} and widgets can still call host Docker tools from host mode.", "dim")

    w.log_line("")

    # =======================================================================
    # STEP 2b — Host pip dependencies (no sudo needed)
    # =======================================================================
    w.log_line("  -- Step 2b: Host voice dependencies ------------------", "h2")
    w.set_status("Checking host pip dependencies…")

    _HOST_PIP_DEPS = [
        ("faster_whisper", "faster-whisper", f"voice transcription (Ask {ASSISTANT_NAME} mic input)"),
    ]
    for _import_name, _pip_name, _desc in _HOST_PIP_DEPS:
        try:
            __import__(_import_name)
            w.log_line(f"  [OK]  {_pip_name} already installed ({_desc})", "ok")
        except ImportError:
            w.log_line(f"  [PKG]  Installing {_pip_name} — {_desc}…", "dim")
            try:
                _r = subprocess.run(
                    ["pip3", "install", "--user", "--quiet", _pip_name],
                    capture_output=True, text=True, timeout=120,
                )
                if _r.returncode == 0:
                    w.log_line(f"  [OK]  {_pip_name} installed", "ok")
                else:
                    w.log_line(f"  [WARN]  {_pip_name} install failed — {_desc} disabled", "warn")
                    w.log_line(f"      pip3 install --user {_pip_name}", "dim")
            except Exception as _pip_exc:
                w.log_line(f"  [WARN]  {_pip_name} install error: {_pip_exc}", "warn")

    w.log_line("")

    # =======================================================================
    # STEP 3 — Launch the platform
    # =======================================================================
    w.log_line(f"  -- Step 3: Launching {APP_NAME} ------------------", "h2")
    w.set_status(f"Launching {APP_NAME}...")

    if not LAUNCH_SH.exists():
        w.log_line(f"  [ERROR]  Launch script not found: {LAUNCH_SH}", "err")
        w.log_line("  Make sure you're running from the platformgen-py repo.", "dim")
        w.mark_done(success=False)
        return

    launch_args = ["bash", str(LAUNCH_SH)]
    launch_env = {**os.environ, "AUGER_WIZARD": "1"}
    if launch_mode == "docker":
        w.log_line("  Running platformgen-launch.sh --docker...", "dim")
        w.log_line("  (Install Wizard forces a local base image from this repo, then builds your personalized image.)", "dim")
        launch_args.append("--docker")
        launch_env.update({
            "AUGER_FORCE_LOCAL_BASE": "1",
            "AUGER_FORCE_REBUILD_PERSONALIZED": "1",
        })
    else:
        w.log_line("  Running platformgen-launch.sh --venv --background...", "dim")
        w.log_line(f"  (Install Wizard will create/update {AUGER_DIR}/venv, start the host daemon/tray, and launch {APP_NAME} directly on this host.)", "dim")
        launch_args.extend(["--venv", "--background"])
    w.log_line("")

    try:
        proc = subprocess.Popen(
            launch_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=launch_env,
        )
        for raw in proc.stdout:
            line = w._sanitize_text(raw).rstrip()
            if not line:
                continue
            lo = line.lower()
            if any(x in lo for x in ("[ok]", "success", "started", "running", "complete")):
                w.log_line("  " + line, "ok")
            elif any(x in lo for x in ("[error]", "error", "failed", "denied")):
                w.log_line("  " + line, "err")
            elif any(x in lo for x in ("[warn]", "warn", "skip")):
                w.log_line("  " + line, "warn")
            elif any(x in lo for x in ("[info]", "pulling", "pulled", "already", "digest", "status:")):
                w.log_line("  " + line, "info")
            else:
                w.log_line("  " + line, "dim")
        proc.wait()

        container_up = False
        host_up = False
        try:
            if launch_mode == "docker":
                r = subprocess.run(
                    ["docker", "ps", "--filter", "name=platformgen-platform",
                     "--format", "{{.Names}}"],
                    capture_output=True, text=True, timeout=5)
                container_up = "platformgen-platform" in r.stdout
            else:
                pid_file = AUGER_DIR / "venv-platform.pid"
                if pid_file.exists():
                    pid = int(pid_file.read_text().strip())
                    os.kill(pid, 0)
                    host_up = True
        except Exception:
            pass

        if launch_mode == "venv" and not host_up:
            try:
                r = subprocess.run(
                    ["pgrep", "-f", "python3 -m platformgen start|python -m platformgen start|python3 -m auger start|python -m auger start"],
                    capture_output=True, text=True, timeout=5)
                host_up = bool(r.stdout.strip())
            except Exception:
                pass

        success = False
        if launch_mode == "docker":
            # Exit 143 = SIGTERM (128+15): bash received SIGTERM during cleanup.
            success = proc.returncode == 0 or (proc.returncode == 143 and container_up)
        else:
            success = proc.returncode == 0 and host_up

        if success:
            w.log_line("")
            if launch_mode == "docker":
                w.log_line(f"  [OK]  {APP_NAME} SRE is running!", "ok")
                w.log_line("  The platform window should now appear on your desktop.", "dim")
            else:
                w.log_line(f"  [OK]  {APP_NAME} host mode is running!", "ok")
                w.log_line("  The host-mode window should now appear on your desktop.", "dim")

            # Verify daemon health
            try:
                import urllib.request, urllib.error
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                resp = opener.open(f"http://localhost:{DAEMON_PORT}/health", timeout=3)
                w.log_line(f"  [OK]  Host Tools daemon is healthy (port {DAEMON_PORT})", "ok")
            except Exception:
                w.log_line("  [WARN]  Host Tools daemon not responding — it may still be starting", "warn")

            # Verify tray applet
            try:
                r2 = subprocess.run(["pgrep", "-f", "platformgen_tray.py|auger_tray.py"],
                                    capture_output=True, text=True, timeout=3)
                if r2.stdout.strip():
                    w.log_line("  [OK]  System tray icon is running", "ok")
                else:
                    w.log_line("  [WARN]  Tray icon not detected — check ~/.platformgen/tray.log", "warn")
            except Exception:
                pass

            w.log_line("")
            w.log_line("  [TIP] Ask Genny is ready — type any question into the Ask Genny panel.", "info")
            w.log_line("  [TIP] Open the API Keys+ tab to configure additional integrations.", "info")
            w.log_line("  [TIP] Need help? Type: what can you do?", "info")
            
            # Update ~/.bashrc with PATH if needed
            if _update_bashrc_path():
                w.log_line("", "dim")
                w.log_line("  [OK]  Added ~/.local/bin to PATH in ~/.bashrc", "ok")
                w.log_line("  [TIP] Reload your shell with:  source ~/.bashrc", "dim")
            
            w.mark_done(success=True)
        else:
            w.log_line(f"  [ERROR]  Launch script exited with code {proc.returncode}", "err")
            if launch_mode == "docker":
                w.log_line("  Run:  docker logs platformgen-platform  for details.", "dim")
            else:
                w.log_line("  Run:  tail -100 ~/.platformgen/venv-platform.log  for details.", "dim")
            w.mark_done(success=False)

    except FileNotFoundError:
        w.log_line("  [ERROR]  'bash' not found — cannot run launch script", "err")
        w.mark_done(success=False)
    except Exception as exc:
        w.log_line(f"  [ERROR]  Unexpected error: {exc}", "err")
        w.mark_done(success=False)


# -- Entry point ---------------------------------------------------------------

def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("ERROR: tkinter is not installed.")
        print("")
        print("Install it with:  sudo apt-get install -y python3-tk")
        print("")
        print("Falling back to the bash installer…")
        bash_setup = SCRIPT_DIR / "platformgen-setup.sh"
        if bash_setup.exists():
            os.execv("/bin/bash", ["/bin/bash", str(bash_setup)])
        sys.exit(1)

    wiz = WizardWindow()
    wiz.run()


if __name__ == "__main__":
    main()
