#!/usr/bin/env python3
"""
PlatformGen system tray applet
Runs on the HOST machine (not inside the Docker container).

Provides a GNOME status-area icon with:
  - Green/red indicator based on daemon health (:7437/health)
  - Open PlatformGen (bring window to front)
  - Quick Ask Genny... (floating prompt -> streams response)
  - Restart PlatformGen
  - Stop PlatformGen
  - Quit Tray (removes icon, leaves the runtime running)

Requirements (host):
  pip3 install --user pystray pillow
  sudo apt install gir1.2-gtk-3.0 gir1.2-ayatana-appindicator3-0.1

Usage (called from docker-run.sh automatically):
  python3 scripts/auger_tray.py &


  - Check for Update (compares local vs Artifactory :latest, pull + restart on demand)
"""

import os
import sys
import json
import time
import threading
import subprocess
import shutil
import urllib.request
import urllib.error

# Build a no-proxy opener for all localhost daemon calls.
# http_proxy=http://127.0.0.1:9000 is set in the environment; without this
# every tray→daemon request is silently routed through the corporate proxy.
_NO_PROXY_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({})
)
from pathlib import Path

# ── VS Code / Snap GTK-GIO override fix ───────────────────────────────────────
# GUI launches inherited from snap-based terminals can pull in an older snap
# GTK/GIO runtime. That causes AppIndicator startup failures like:
#   GLIBCXX_3.4.29 not found ... libproxy.so.1
# Strip those overrides before importing any GUI stack so the host system GTK/GIO
# libraries are used consistently.
for _snap_gtk_var in (
    "GTK_EXE_PREFIX",
    "GTK_PATH",
    "GTK_DATA_PREFIX",
    "GTK_IM_MODULE_FILE",
    "GIO_MODULE_DIR",
    "GIO_EXTRA_MODULES",
    "GI_TYPELIB_PATH",
    "GDK_PIXBUF_MODULEDIR",
    "GDK_PIXBUF_MODULE_FILE",
    "GTK_MODULES",
    "LD_LIBRARY_PATH",
    "PYTHONHOME",
):
    os.environ.pop(_snap_gtk_var, None)

for _snap_env in tuple(os.environ):
    if _snap_env.startswith("SNAP"):
        os.environ.pop(_snap_env, None)

# ── Optional Tk for Quick Ask popup ──────────────────────────────────────────
try:
    import tkinter as tk
    from tkinter import scrolledtext
    _HAS_TK = True
except ImportError:
    _HAS_TK = False

# ── pystray + PIL ─────────────────────────────────────────────────────────────
try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    print("[platformgen_tray] ERROR: pystray or pillow not installed.")
    print("  pip3 install --user pystray pillow")
    sys.exit(1)

APP_NAME = os.environ.get("AUGER_APP_NAME", "PlatformGen")
PRODUCT_NAME = os.environ.get("AUGER_PRODUCT_NAME", APP_NAME)
ASSISTANT_NAME = os.environ.get("AUGER_ASSISTANT_NAME", "Genny")
CLI_NAME = os.environ.get("AUGER_CLI_NAME", "genny")
DAEMON_URL = f"http://localhost:{os.environ.get('AUGER_DAEMON_PORT', '7437')}"
POLL_INTERVAL = 10   # seconds between health checks
CONTAINER_NAME = os.environ.get("AUGER_CONTAINER_NAME", "platformgen-platform")
STATE_DIR = Path(
    os.environ.get("PLATFORMGEN_HOME")
    or os.environ.get("AUGER_HOME")
    or str(Path.home() / ".platformgen")
).expanduser()
HOST_VENV_PID_FILE = STATE_DIR / "venv-platform.pid"
HOST_PROCESS_PATTERNS = (
    "python3 -m auger start",
    "python -m auger start",
    f"{CLI_NAME} start",
)

# Image used for update checks.  Override via env var for local dev.
IMAGE = os.environ.get(
    "AUGER_IMAGE",
    "artifactory.helix.gsa.gov/gs-assist-docker-repo/auger-platform:latest",
)
SCRIPT_DIR = Path(__file__).resolve().parent
# Script that starts the runtime (used after an image update or when tray starts PlatformGen)
LAUNCH_SCRIPT = os.environ.get("AUGER_LAUNCHER_SCRIPT", str(SCRIPT_DIR / "platformgen-launch.sh"))
TRAY_TITLE_BASE = f"{PRODUCT_NAME} — Ask {ASSISTANT_NAME}"
HOST_RUNTIME_LABEL = PRODUCT_NAME
DOCKER_RUNTIME_LABEL = f"{PRODUCT_NAME} Docker Runtime"


def _tray_title(message: str = "") -> str:
    return f"{TRAY_TITLE_BASE} ({message})" if message else TRAY_TITLE_BASE

# ── Icon generation ───────────────────────────────────────────────────────────

def _load_standard_tray_icon(size: int = 16) -> Image.Image:
    asset = SCRIPT_DIR.parent / "auger" / "ui" / "assets" / "auger_tray_icon.png"
    fallback = SCRIPT_DIR.parent / "auger" / "ui" / "assets" / "auger_app_icon.png"
    source = asset if asset.exists() else fallback
    if source.exists():
        with Image.open(source) as img:
            return img.convert("RGBA").resize((size, size), Image.LANCZOS)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([2, 2, size - 2, size - 2], fill="#1a2332")
    d.text((size // 2, size // 2), "A", fill="#ffffff", anchor="mm")
    return img


_TRAY_BASE_ICON = _load_standard_tray_icon(16)
ICON_GREEN = _TRAY_BASE_ICON.copy()
ICON_YELLOW = _TRAY_BASE_ICON.copy()
ICON_RED = _TRAY_BASE_ICON.copy()
DRILL_GREEN = _TRAY_BASE_ICON.copy()
DRILL_YELLOW = _TRAY_BASE_ICON.copy()
DRILL_RED = _TRAY_BASE_ICON.copy()

# ── Stable icon paths (avoids pystray temp-file deletion race with AppIndicator) ─
# pystray's appindicator backend deletes+recreates /tmp/tmpXXXX on every icon.icon update.
# AyatanaAppIndicator3 reads the file path from DBUS on each render, so if the file was
# just deleted it gets a blank icon.  We override _update_fs_icon on the pystray.Icon
# instance to write to a stable runtime state path that is overwritten in-place instead.
_ICON_DIR = STATE_DIR / "icons"
_ICON_DIR.mkdir(parents=True, exist_ok=True)
_STABLE_ICON_PATH = str(_ICON_DIR / "tray_icon.png")

def _patch_stable_icon(icon: "pystray.Icon") -> None:
    """Monkey-patch icon._update_fs_icon to write to a stable path in-place."""
    import types

    def _stable_update_fs_icon(self):
        # Remove the old temp path if pystray already created one
        if self._icon_path and self._icon_path != _STABLE_ICON_PATH:
            try:
                os.unlink(self._icon_path)
            except OSError:
                pass
        self._icon_path = _STABLE_ICON_PATH
        self.icon.save(self._icon_path, "PNG")
        self._icon_valid = True

    icon._update_fs_icon = types.MethodType(_stable_update_fs_icon, icon)

# ── Daemon helpers ────────────────────────────────────────────────────────────

def _daemon_healthy() -> bool:
    try:
        with _NO_PROXY_OPENER.open(f"{DAEMON_URL}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _post(path: str, payload: dict, timeout: int = 35) -> str:
    """POST JSON to the daemon. Returns response text (may be NDJSON stream).

    Default timeout is 35s — restart_platform can take ~20s when container
    needs docker start + UI relaunch.  Callers that need a shorter timeout
    can pass timeout= explicitly.
    """
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{DAEMON_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with _NO_PROXY_OPENER.open(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return f"Error: {e}"


def _get_json(path: str, timeout: int = 5) -> dict:
    try:
        with _NO_PROXY_OPENER.open(f"{DAEMON_URL}{path}", timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _docker_exec(cmd: list) -> str:
    try:
        r = subprocess.run(
            ["docker", "exec", CONTAINER_NAME] + cmd,
            capture_output=True, text=True, timeout=10
        )
        return r.stdout + r.stderr
    except Exception as e:
        return str(e)


def _container_running() -> bool:
    try:
        r = subprocess.run(
            ["docker", "ps", "--filter", f"name={CONTAINER_NAME}", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        return CONTAINER_NAME in r.stdout.splitlines()
    except Exception:
        return False


def _personalized_image_present() -> bool:
    try:
        safe_user = "".join(ch if ch.isalnum() else "-" for ch in os.environ.get("USER", "auger").split("@")[0]).strip("-").lower()
        if not safe_user:
            return False
        image = f"auger-platform-{safe_user}:latest"
        r = subprocess.run(
            ["docker", "image", "inspect", image],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _launch_platform() -> None:
    subprocess.Popen(["bash", LAUNCH_SCRIPT, "--docker"], start_new_session=True)


def _launch_host_platform() -> None:
    subprocess.Popen(["bash", LAUNCH_SCRIPT, "--venv", "--background"], start_new_session=True)


def _docker_command_available() -> bool:
    return shutil.which("docker") is not None


def _host_platform_running() -> bool:
    try:
        if HOST_VENV_PID_FILE.exists():
            pid = int(HOST_VENV_PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True
    except Exception:
        pass
    try:
        for pattern in HOST_PROCESS_PATTERNS:
            r = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, timeout=5,
            )
            if r.stdout.strip():
                return True
        return False
    except Exception:
        return False


def _stop_host_platform_processes() -> None:
    try:
        if HOST_VENV_PID_FILE.exists():
            pid = int(HOST_VENV_PID_FILE.read_text().strip())
            subprocess.run(["kill", str(pid)], capture_output=True, timeout=5)
            HOST_VENV_PID_FILE.unlink(missing_ok=True)
            time.sleep(1)
    except Exception:
        pass
    try:
        for pattern in HOST_PROCESS_PATTERNS:
            r = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True, text=True, timeout=5,
            )
            for raw in r.stdout.splitlines():
                pid = raw.strip()
                if pid:
                    subprocess.run(["kill", pid], capture_output=True, timeout=5)
    except Exception:
        pass


def _activate_existing_platform() -> bool:
    try:
        r = subprocess.run(
            [
                "docker",
                "exec",
                "-d",
                "-e",
                f"DISPLAY={os.environ.get('DISPLAY', ':1')}",
                CONTAINER_NAME,
                "auger",
                "start",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def _keepalive_status() -> dict:
    return _get_json("/keepalive_status", timeout=3)


def _keepalive_enabled(item=None) -> bool:
    status = _keepalive_status()
    return bool(status.get("enabled"))

# ── Quick Ask popup ───────────────────────────────────────────────────────────

def _open_quick_ask():
    """Open a small floating Tk window for Quick Ask Genny."""
    if not _HAS_TK:
        print("[platformgen_tray] Tk not available — cannot open Quick Ask")
        return

    def _run_popup():
        root = tk.Tk()
        root.title(f"Ask {ASSISTANT_NAME}")
        root.geometry("520x380")
        root.configure(bg="#1e1e1e")
        root.attributes("-topmost", True)
        root.resizable(True, True)

        # Try to keep it floating without a full taskbar entry
        try:
            root.wm_attributes("-type", "dialog")
        except Exception:
            pass

        BG    = "#1e1e1e"
        BG2   = "#2d2d2d"
        FG    = "#d4d4d4"
        ACCENT = "#2ea043"
        FONT  = ("Segoe UI", 10)

        # Header
        tk.Label(root, text=f"⚡ Ask {ASSISTANT_NAME}", bg=BG, fg=ACCENT,
                 font=("Segoe UI", 13, "bold")).pack(pady=(12, 4))

        # Prompt entry
        prompt_var = tk.StringVar()
        entry = tk.Entry(root, textvariable=prompt_var, bg=BG2, fg=FG,
                         font=FONT, insertbackground=FG, relief="flat",
                         highlightbackground=ACCENT, highlightthickness=1)
        entry.pack(fill=tk.X, padx=16, pady=(4, 8))
        entry.focus_set()

        # Response area — Text widget with markdown tag formatting
        resp_frame = tk.Frame(root, bg=BG2, highlightbackground=ACCENT,
                              highlightthickness=1)
        resp_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))
        resp = tk.Text(
            resp_frame, bg=BG2, fg=FG, font=("Segoe UI", 10), relief="flat",
            wrap=tk.WORD, state="disabled", height=14,
            padx=8, pady=6, spacing1=2, spacing3=2
        )
        vsb = tk.Scrollbar(resp_frame, orient="vertical", command=resp.yview)
        resp.configure(yscrollcommand=vsb.set)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        resp.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Markdown-style tags
        resp.tag_configure("h1",     font=("Segoe UI", 13, "bold"),   foreground="#a5d6a7", spacing1=6)
        resp.tag_configure("h2",     font=("Segoe UI", 11, "bold"),   foreground="#81c784", spacing1=4)
        resp.tag_configure("h3",     font=("Segoe UI", 10, "bold"),   foreground="#66bb6a", spacing1=3)
        resp.tag_configure("bold",   font=("Segoe UI", 10, "bold"))
        resp.tag_configure("code",   font=("Consolas", 9),            foreground="#ce9178", background="#1a1a1a")
        resp.tag_configure("bullet", lmargin1=12, lmargin2=24,        foreground=FG)
        resp.tag_configure("hr",     foreground="#444444")

        status_var = tk.StringVar(value="Ready")
        tk.Label(root, textvariable=status_var, bg=BG, fg="#888888",
                 font=("Segoe UI", 8)).pack(pady=(0, 8))

        _md_buf = [""]   # buffer for assembling streamed partial lines

        def _render_line(line: str):
            """Render one complete markdown line into resp widget."""
            resp.configure(state="normal")
            if line.startswith("### "):
                resp.insert(tk.END, line[4:] + "\n", "h3")
            elif line.startswith("## "):
                resp.insert(tk.END, line[3:] + "\n", "h2")
            elif line.startswith("# "):
                resp.insert(tk.END, line[2:] + "\n", "h1")
            elif line.startswith(("- ", "* ", "+ ")):
                resp.insert(tk.END, "  • " + line[2:] + "\n", "bullet")
            elif line.startswith("```") or line == "---":
                resp.insert(tk.END, "─" * 40 + "\n", "hr")
            elif line.startswith("`") and line.endswith("`"):
                resp.insert(tk.END, line[1:-1] + "\n", "code")
            elif line == "":
                resp.insert(tk.END, "\n")
            else:
                # Inline bold **text** and `code`
                import re
                parts = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", line)
                for part in parts:
                    if part.startswith("**") and part.endswith("**"):
                        resp.insert(tk.END, part[2:-2], "bold")
                    elif part.startswith("`") and part.endswith("`"):
                        resp.insert(tk.END, part[1:-1], "code")
                    else:
                        resp.insert(tk.END, part)
                resp.insert(tk.END, "\n")
            resp.see(tk.END)
            resp.configure(state="disabled")

        def _append(text: str):
            """Buffer streamed text and render complete lines."""
            _md_buf[0] += text
            while "\n" in _md_buf[0]:
                line, _md_buf[0] = _md_buf[0].split("\n", 1)
                _render_line(line)

        def _ask():
            prompt = prompt_var.get().strip()
            if not prompt:
                return
            prompt_var.set("")
            resp.configure(state="normal")
            resp.delete("1.0", tk.END)
            resp.configure(state="disabled")
            status_var.set("⏳ Asking…")

            def _worker():
                # Stream via /ask endpoint — NDJSON lines
                data = json.dumps({"prompt": prompt}).encode()
                req = urllib.request.Request(
                    f"{DAEMON_URL}/ask",
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                try:
                    with _NO_PROXY_OPENER.open(req, timeout=60) as r:
                        for raw in r:
                            line = raw.decode("utf-8", errors="replace").rstrip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                                chunk = obj.get("chunk") or obj.get("text") or obj.get("message") or ""
                                if chunk:
                                    root.after(0, lambda c=chunk: _append(c))
                            except json.JSONDecodeError:
                                # Plain text line
                                root.after(0, lambda l=line: _append(l + "\n"))
                    root.after(0, lambda: status_var.set("✓ Done"))
                except Exception as e:
                    root.after(0, lambda err=str(e): (
                        _append(f"\n[Error: {err}]"),
                        status_var.set("✗ Error")
                    ))

            threading.Thread(target=_worker, daemon=True).start()

        ask_btn = tk.Button(
            root, text="Ask  ⏎", bg=ACCENT, fg="#ffffff",
            font=("Segoe UI", 10, "bold"), relief="flat",
            padx=12, pady=4, command=_ask, cursor="hand2"
        )
        ask_btn.pack(pady=(0, 12))

        entry.bind("<Return>", lambda e: _ask())
        entry.bind("<Escape>", lambda e: root.destroy())

        root.mainloop()

    threading.Thread(target=_run_popup, daemon=True).start()


# ── Update check ─────────────────────────────────────────────────────────────

def _get_local_image_id() -> str:
    """Return the image ID (sha256:…) of the locally-tagged IMAGE, or '' if not found."""
    try:
        r = subprocess.run(
            ["docker", "image", "inspect", IMAGE, "--format", "{{.Id}}"],
            capture_output=True, text=True, timeout=10,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _pull_image() -> tuple:
    """Run `docker pull IMAGE`.

    Returns (status, detail) where status is one of:
      'up_to_date'  — registry digest matches local
      'updated'     — new layers downloaded
      'unreachable' — could not connect (local dev / no Artifactory access)
      'error'       — unexpected failure
    """
    try:
        r = subprocess.run(
            ["docker", "pull", IMAGE],
            capture_output=True, text=True, timeout=120,
        )
        combined = (r.stdout + r.stderr).lower()
        if r.returncode != 0:
            if any(x in combined for x in ("connection refused", "no such host",
                                           "network", "timeout", "unauthorized",
                                           "denied", "not found")):
                return ("unreachable", r.stderr.strip()[:200])
            return ("error", r.stderr.strip()[:200])
        if "up to date" in combined or "already exists" in combined and "pull complete" not in combined:
            return ("up_to_date", "")
        if "pull complete" in combined or "downloaded newer" in combined:
            return ("updated", "")
        # Ambiguous output — treat as up to date
        return ("up_to_date", "")
    except subprocess.TimeoutExpired:
        return ("error", "Timed out waiting for docker pull")
    except Exception as e:
        return ("error", str(e))


def _check_for_update(icon, item):
    """Menu handler: open update dialog and check for a newer image."""
    if not _HAS_TK:
        # Headless fallback: just pull and print result
        threading.Thread(target=_headless_update_check, daemon=True).start()
        return
    threading.Thread(target=_update_dialog, args=(icon,), daemon=True).start()


def _headless_update_check():
    status, detail = _pull_image()
    msgs = {
        "up_to_date":  "[platformgen_tray] Image is up to date.",
        "updated":     f"[platformgen_tray] New image pulled — restart {PRODUCT_NAME} to apply.",
        "unreachable": f"[platformgen_tray] Artifactory unreachable: {detail}",
        "error":       f"[platformgen_tray] Update check failed: {detail}",
    }
    print(msgs.get(status, status))


def _update_dialog(icon):
    """Show a small Tk dialog that runs docker pull and reports the result."""
    root = tk.Tk()
    root.title(f"{PRODUCT_NAME} — Check for Update")
    root.geometry("440x200")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    BG    = "#1e1e1e"
    BG2   = "#2d2d2d"
    FG    = "#d4d4d4"
    GREEN = "#2ea043"
    YELLOW = "#d29922"
    RED   = "#da3633"

    root.configure(bg=BG)

    try:
        root.wm_attributes("-type", "dialog")
    except Exception:
        pass

    tk.Label(root, text=f"🔄 {PRODUCT_NAME} Update Check", bg=BG, fg=GREEN,
             font=("Segoe UI", 13, "bold")).pack(pady=(14, 2))

    img_label = tk.Label(root, text=f"Image: {IMAGE}", bg=BG, fg="#888888",
                         font=("Segoe UI", 8), wraplength=400)
    img_label.pack()

    status_var = tk.StringVar(value="⏳  Checking Artifactory for updates…")
    status_lbl = tk.Label(root, textvariable=status_var, bg=BG, fg=YELLOW,
                          font=("Segoe UI", 11), wraplength=400)
    status_lbl.pack(pady=(16, 8))

    # Buttons frame — hidden until pull completes
    btn_frame = tk.Frame(root, bg=BG)
    btn_frame.pack(pady=(0, 16))

    restart_btn = tk.Button(
        btn_frame, text="🔄  Restart Now", bg=GREEN, fg="#ffffff",
        font=("Segoe UI", 10, "bold"), relief="flat", padx=12, pady=4,
        cursor="hand2",
    )
    close_btn = tk.Button(
        btn_frame, text="Close", bg=BG2, fg=FG,
        font=("Segoe UI", 10), relief="flat", padx=12, pady=4,
        cursor="hand2", command=root.destroy,
    )

    def _apply_restart():
        root.destroy()
        threading.Thread(
            target=_restart_with_new_image, args=(icon,), daemon=True
        ).start()

    restart_btn.configure(command=_apply_restart)

    def _on_pull_done(status, detail):
        """Called from background thread via root.after."""
        if status == "up_to_date":
            status_var.set("[OK]  Already running the latest image.")
            status_lbl.configure(fg=GREEN)
            close_btn.pack(side=tk.LEFT, padx=6)
        elif status == "updated":
            status_var.set(f"🆕  New image downloaded! Restart {PRODUCT_NAME} to apply.")
            status_lbl.configure(fg=GREEN)
            restart_btn.pack(side=tk.LEFT, padx=6)
            close_btn.pack(side=tk.LEFT, padx=6)
        elif status == "unreachable":
            status_var.set("[WARN]  Artifactory unreachable — running local image.")
            status_lbl.configure(fg=YELLOW)
            close_btn.pack(side=tk.LEFT, padx=6)
        else:
            status_var.set(f"[ERROR]  Update check failed: {detail[:80]}")
            status_lbl.configure(fg=RED)
            close_btn.pack(side=tk.LEFT, padx=6)

    def _worker():
        status, detail = _pull_image()
        root.after(0, lambda: _on_pull_done(status, detail))

    threading.Thread(target=_worker, daemon=True).start()
    root.mainloop()


def _restart_with_new_image(icon):
    """Stop the container and re-launch using the freshly-pulled image."""
    icon.icon  = DRILL_YELLOW
    icon.title = _tray_title(f"Restarting {DOCKER_RUNTIME_LABEL} with new image…")
    try:
        subprocess.run(["docker", "rm", "-f", CONTAINER_NAME],
                       capture_output=True, timeout=15)
        subprocess.Popen(["bash", LAUNCH_SCRIPT])
        time.sleep(12)
    except Exception as e:
        print(f"[platformgen_tray] Restart failed: {e}")
    _refresh_status(icon)


# ── Runtime control actions ───────────────────────────────────────────────────

def _open_host_auger(icon, item):
    """Launch the host/venv PlatformGen runtime if it is not already running."""
    def _worker():
        icon.icon = DRILL_YELLOW
        if _host_platform_running():
            icon.title = _tray_title(f"{HOST_RUNTIME_LABEL} already running")
        else:
            icon.title = _tray_title(f"Starting {HOST_RUNTIME_LABEL}…")
            _launch_host_platform()
        time.sleep(3)
        _refresh_status(icon)

    threading.Thread(target=_worker, daemon=True).start()


def _open_sre_auger(icon, item):
    """Bring the Docker runtime window to front, or start it if stopped."""
    def _worker():
        if _container_running():
            icon.icon = DRILL_YELLOW
            icon.title = _tray_title(f"Opening existing {DOCKER_RUNTIME_LABEL} window…")
            if not _activate_existing_platform():
                _launch_platform()
        else:
            icon.icon = DRILL_YELLOW
            icon.title = _tray_title(f"Starting {DOCKER_RUNTIME_LABEL}…")
            _launch_platform()
        time.sleep(5)
        _refresh_status(icon)

    threading.Thread(target=_worker, daemon=True).start()


def _quick_ask(icon, item):
    _open_quick_ask()


def _toggle_keepalive(icon, item):
    icon.icon = DRILL_YELLOW
    icon.title = _tray_title("Toggling keepalive…")

    def _worker():
        current = _keepalive_status()
        if current.get("status") != "ok":
            icon.title = _tray_title("Keepalive unavailable")
            _refresh_status(icon)
            try:
                icon.update_menu()
            except Exception:
                pass
            return

        action = "stop" if current.get("enabled") else "start"
        raw = _post("/keepalive", {"action": action}, timeout=10)
        try:
            result = json.loads(raw)
        except Exception:
            result = {"status": "error", "message": raw}

        if result.get("status") == "ok":
            state = "enabled" if result.get("enabled") else "disabled"
            icon.title = _tray_title(f"Keepalive {state}")
        else:
            icon.title = _tray_title("Keepalive toggle failed")
            print(f"[platformgen_tray] Keepalive toggle failed: {result.get('message') or raw}")

        time.sleep(1)
        _refresh_status(icon)
        try:
            icon.update_menu()
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()


def _restart_host_auger(icon, item):
    """Restart the host/venv PlatformGen runtime."""
    icon.icon = DRILL_YELLOW
    icon.title = _tray_title(f"Restarting {HOST_RUNTIME_LABEL}…")

    def _worker():
        _stop_host_platform_processes()
        _launch_host_platform()
        time.sleep(4)
        _refresh_status(icon)

    threading.Thread(target=_worker, daemon=True).start()


def _restart_auger(icon, item):
    """Restart the Docker runtime UI only — daemon stays running."""
    icon.icon = DRILL_YELLOW
    icon.title = _tray_title(f"Restarting {DOCKER_RUNTIME_LABEL}…")

    def _worker():
        if not _personalized_image_present():
            icon.title = _tray_title("Rebuilding personalized image…")
            _launch_platform()
        elif _container_running():
            _post("/restart_platform", {})
        else:
            _launch_platform()
        time.sleep(10)
        _refresh_status(icon)

    threading.Thread(target=_worker, daemon=True).start()


def _restart_daemon(icon, item):
    """Restart the host daemon — works even when daemon is currently dead.

    Strategy:
      1. If the daemon is alive, use /restart_daemon endpoint — it closes its
         own socket before spawning a child, avoiding port-conflict crashes.
      2. If the daemon is already dead, kill by PID file then start fresh.
    Never do both — that races two new processes for port 7437.
    """
    icon.icon = DRILL_YELLOW
    icon.title = _tray_title("Restarting daemon…")

    def _worker():
        daemon_script = SCRIPT_DIR / "host_tools_daemon.py"
        pid_file = STATE_DIR / "daemon.pid"
        log_file = STATE_DIR / "daemon.log"

        if _daemon_healthy():
            # Daemon is alive — let it restart itself cleanly via its endpoint.
            # It closes the socket before spawning a child, so no port conflict.
            _post("/restart_daemon", {}, timeout=5)
            time.sleep(4)
        else:
            # Daemon is dead — kill stale PID (if any) then start fresh.
            try:
                old_pid = int(pid_file.read_text().strip())
                subprocess.run(["kill", str(old_pid)], capture_output=True)
                time.sleep(1)
            except Exception:
                pass

            with open(log_file, "a") as log:
                proc = subprocess.Popen(
                    ["nohup", "python3", str(daemon_script)],
                    stdout=log, stderr=log,
                    start_new_session=True,
                )
            pid_file.write_text(str(proc.pid))
            time.sleep(3)

        _refresh_status(icon)

    threading.Thread(target=_worker, daemon=True).start()


def _full_restart_auger(icon, item):
    """Full restart: Docker runtime plus host daemon."""
    icon.icon = DRILL_YELLOW
    icon.title = _tray_title(f"Full restart {DOCKER_RUNTIME_LABEL}…")

    def _worker():
        if not _personalized_image_present():
            icon.title = _tray_title("Rebuilding personalized image…")
            _launch_platform()
        elif _daemon_healthy():
            _post("/restart_daemon", {}, timeout=5)
            time.sleep(4)
            if _daemon_healthy():
                _post("/restart", {})
            else:
                _launch_platform()
        else:
            _launch_platform()
        time.sleep(10)
        _refresh_status(icon)

    threading.Thread(target=_worker, daemon=True).start()


def _stop_host_auger(icon, item):
    _stop_host_platform_processes()
    time.sleep(1)
    _refresh_status(icon)


def _stop_auger(icon, item):
    subprocess.Popen(["docker", "rm", "-f", CONTAINER_NAME])
    icon.icon = DRILL_YELLOW if _daemon_healthy() else ICON_RED
    if _daemon_healthy():
        icon.title = _tray_title(f"Tray ready — {DOCKER_RUNTIME_LABEL} stopped")
    else:
        icon.title = _tray_title("Stopped")


def _quit_tray(icon, item):
    icon.stop()


# ── Status polling ────────────────────────────────────────────────────────────

def _refresh_status(icon):
    daemon_ok = _daemon_healthy()
    host_running = _host_platform_running()
    sre_running = _container_running()
    if daemon_ok and host_running and sre_running:
        icon.icon  = DRILL_GREEN
        icon.title = _tray_title(f"{HOST_RUNTIME_LABEL} + {DOCKER_RUNTIME_LABEL} running")
    elif daemon_ok and host_running:
        icon.icon  = DRILL_GREEN
        icon.title = _tray_title(f"{HOST_RUNTIME_LABEL} running")
    elif daemon_ok and sre_running:
        icon.icon  = DRILL_GREEN
        icon.title = _tray_title(f"{DOCKER_RUNTIME_LABEL} running")
    elif daemon_ok:
        icon.icon  = DRILL_YELLOW
        icon.title = _tray_title("Tray ready — runtimes stopped")
    else:
        icon.icon  = DRILL_RED
        icon.title = _tray_title("Daemon unavailable")


def _poll_loop(icon):
    while True:
        time.sleep(POLL_INTERVAL)
        _refresh_status(icon)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    menu_items = [
        pystray.MenuItem(f"[START] Open {HOST_RUNTIME_LABEL}", _open_host_auger, default=True),
        pystray.MenuItem(f"🔄 Restart {HOST_RUNTIME_LABEL}", _restart_host_auger),
        pystray.MenuItem(f"⏹  Stop {HOST_RUNTIME_LABEL}", _stop_host_auger),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(f"💬 Quick Ask {ASSISTANT_NAME}…", _quick_ask),
        pystray.MenuItem("☕ Keep Workspace Awake",    _toggle_keepalive, checked=_keepalive_enabled),
        pystray.Menu.SEPARATOR,
    ]
    if _docker_command_available():
        menu_items.extend([
            pystray.MenuItem(f"🐳 Open {DOCKER_RUNTIME_LABEL}", _open_sre_auger),
            pystray.MenuItem(f"🔄 Restart {DOCKER_RUNTIME_LABEL}", _restart_auger),
            pystray.MenuItem("⚙️  Full Restart Docker Runtime (+ Daemon)", _full_restart_auger),
            pystray.MenuItem(f"⏹  Stop {DOCKER_RUNTIME_LABEL}", _stop_auger),
            pystray.MenuItem("🆕 Check for Update…",           _check_for_update),
            pystray.Menu.SEPARATOR,
        ])
    menu_items.extend([
        pystray.MenuItem("🔌 Restart Daemon Only",     _restart_daemon),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("[ERROR] Quit Tray",               _quit_tray),
    ])
    menu = pystray.Menu(*menu_items)

    # Start with yellow (connecting) then poll immediately
    icon = pystray.Icon(
        name="platformgen",
        icon=DRILL_YELLOW,
        title=TRAY_TITLE_BASE,
        menu=menu,
    )

    # Use stable icon path so AppIndicator always has the file available
    _patch_stable_icon(icon)

    # Kick off health poll in background
    threading.Thread(target=_poll_loop, args=(icon,), daemon=True).start()

    # Initial status check after 2s
    def _initial_check():
        time.sleep(2)
        _refresh_status(icon)

    threading.Thread(target=_initial_check, daemon=True).start()

    icon.run()


if __name__ == "__main__":
    main()
