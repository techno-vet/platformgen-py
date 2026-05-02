#!/usr/bin/env python3
"""
status_bar.py - Auger platform status bar.

Thin (~26 px) bar pinned to the bottom of the main window.
Shows (left to right):
    [Auger vX.Y.Z]  [branch @ sha]  [green up to date]  [whale tag]  [daemon green]  [EDT HH:MM]

Thread-safety: all Tk mutations are queued via self._safe() and drained on the
main thread by _poll_q(). Worker threads never call Tk directly.
Proxy safety:  daemon health check bypasses corporate proxy (127.0.0.1:9000)
               that intercepts all localhost traffic.
"""

import json
import queue
import subprocess
import threading
import urllib.request
from datetime import datetime
from pathlib import Path
import tkinter as tk

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except ImportError:
    _ET = None

BG      = "#1e1e1e"
BG_PILL = "#2a2a2a"
FG_DIM  = "#888888"
ACCENT  = "#4fc1ff"
GREEN   = "#4ec9b0"
RED     = "#f44747"
YELLOW  = "#f0c040"

DAEMON_URL = "http://localhost:7437"

_REPO_CANDIDATES = [
    Path("/home/auger/repos/auger-ai-sre-platform"),
    Path.home() / "repos" / "auger-ai-sre-platform",
]


def _find_repo():
    for c in _REPO_CANDIDATES:
        if (c / ".git").exists():
            return c
    return None


def _git(repo, *args, timeout=8):
    try:
        r = subprocess.run(
            ["git", "-C", str(repo)] + list(args),
            capture_output=True, text=True, timeout=timeout,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _get_version():
    try:
        from importlib.metadata import version as _iv
        return _iv("auger-platform")
    except Exception:
        pass
    for c in _REPO_CANDIDATES:
        try:
            for line in (c / "pyproject.toml").read_text().splitlines():
                if line.strip().startswith("version"):
                    return line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
    return "?"


def _daemon_ok():
    """Return True if daemon responds. Bypasses corporate proxy on localhost."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"{DAEMON_URL}/health", timeout=2.0) as resp:
            return json.loads(resp.read()).get("status") == "ok"
    except Exception:
        return False


def _read_image_tag():
    import os
    tag = os.environ.get("AUGER_IMAGE_TAG", "")
    if not tag:
        for p in [Path("/.docker-image-tag"), Path.home() / ".auger" / "image_tag"]:
            try:
                tag = p.read_text().strip()
                if tag:
                    break
            except Exception:
                pass
    return tag or "latest"


class AugerStatusBar(tk.Frame):
    """
    Thin status bar pinned to the bottom of the main window.

    Pack with side=tk.BOTTOM, fill=tk.X before the main PanedWindow.

    Parameters
    ----------
    parent       : parent Tk widget
    content_ref  : ContentArea reference (wire after _build_layout)
    """

    def __init__(self, parent, content_ref=None, **kwargs):
        kwargs.setdefault("height", 26)
        super().__init__(parent, bg=BG, **kwargs)
        self.pack_propagate(False)

        self._content = content_ref
        self._repo    = _find_repo()
        self._version = _get_version()

        tk.Frame(self, bg="#3c3c3c", height=1).pack(side=tk.TOP, fill=tk.X)

        inner = tk.Frame(self, bg=BG)
        inner.pack(fill=tk.BOTH, expand=True)

        # Left: version pill + branch pill
        left = tk.Frame(inner, bg=BG)
        left.pack(side=tk.LEFT, padx=(8, 0))

        self._lbl_ver = tk.Label(
            left, text=f"Auger v{self._version}",
            bg=BG_PILL, fg=FG_DIM, font=("Consolas", 8), padx=5, pady=0,
        )
        self._lbl_ver.pack(side=tk.LEFT, padx=(0, 5), pady=3)

        self._lbl_branch = tk.Label(
            left, text="...",
            bg=BG_PILL, fg=ACCENT, font=("Consolas", 8), padx=5, pady=0,
            cursor="hand2",
        )
        self._lbl_branch.pack(side=tk.LEFT, padx=(0, 5), pady=3)
        self._lbl_branch.bind("<Button-1>", self._click_branch)

        # Middle: update status + image
        mid = tk.Frame(inner, bg=BG)
        mid.pack(side=tk.LEFT, padx=6)

        self._lbl_update = tk.Label(
            mid, text="checking...", bg=BG, fg=FG_DIM, font=("Consolas", 8),
        )
        self._lbl_update.pack(side=tk.LEFT, padx=(0, 12))

        self._lbl_image = tk.Label(
            mid, text="\U0001f433 ...", bg=BG, fg=FG_DIM, font=("Consolas", 8),
            cursor="hand2",
        )
        self._lbl_image.pack(side=tk.LEFT)
        self._lbl_image.bind("<Button-1>", self._click_image)

        # Right: daemon + clock
        right = tk.Frame(inner, bg=BG)
        right.pack(side=tk.RIGHT, padx=(0, 10))

        self._lbl_time = tk.Label(
            right, text="", bg=BG, fg=FG_DIM, font=("Consolas", 8),
        )
        self._lbl_time.pack(side=tk.RIGHT, padx=(8, 0))

        self._lbl_daemon = tk.Label(
            right, text="daemon ...", bg=BG, fg=FG_DIM, font=("Consolas", 8),
        )
        self._lbl_daemon.pack(side=tk.RIGHT)

        threading.Thread(target=self._worker_git,        daemon=True).start()
        threading.Thread(target=self._worker_git_remote, daemon=True).start()
        threading.Thread(target=self._worker_daemon,     daemon=True).start()
        self._tick_clock()
        self._q: queue.Queue = queue.Queue()
        self._poll_q()

    def _poll_q(self):
        """Drain the pending-update queue on the main thread (thread-safe Tk updates)."""
        try:
            while True:
                fn = self._q.get_nowait()
                try:
                    fn()
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.after(50, self._poll_q)

    def _safe(self, fn):
        """Queue fn() for execution on the main thread. Never calls Tk from bg threads."""
        self._q.put(fn)

    def _worker_git(self):
        """Fast local poll: branch + SHA only (no network). Runs every 15s."""
        if not self._repo:
            self._safe(lambda: self._lbl_branch.config(text="no repo"))
            self._safe(lambda: self._lbl_update.config(text="\u2014"))
            self._worker_image()
            return

        branch = _git(self._repo, "branch", "--show-current") or "HEAD"
        sha    = _git(self._repo, "rev-parse", "--short", "HEAD") or "?"
        self._safe(lambda b=branch, s=sha:
                   self._lbl_branch.config(text=f"{b} @ {s}"))

        self._worker_image()
        threading.Timer(15, lambda: threading.Thread(
            target=self._worker_git, daemon=True).start()).start()

    def _worker_git_remote(self):
        """Slow remote poll: ls-remote to check ahead/behind. Runs every 5 min."""
        if not self._repo:
            return
        branch = _git(self._repo, "branch", "--show-current") or "HEAD"
        try:
            local       = _git(self._repo, "rev-parse", "HEAD")
            remote_line = _git(self._repo, "ls-remote", "origin",
                               f"refs/heads/{branch}", timeout=12)
            if not remote_line:
                raise ValueError("empty ls-remote")
            remote = remote_line.split()[0]
            if local == remote:
                self._safe(lambda: self._lbl_update.config(
                    text="\U0001f7e2 up to date", fg=GREEN))
            else:
                cnt    = _git(self._repo, "rev-list", "--count",
                              f"HEAD..origin/{branch}")
                behind = int(cnt) if cnt.isdigit() else 0
                if behind > 0:
                    self._safe(lambda n=behind: self._lbl_update.config(
                        text=f"\U0001f7e1 {n} behind", fg=YELLOW))
                else:
                    self._safe(lambda: self._lbl_update.config(
                        text="\U0001f7e1 ahead/diverged", fg=YELLOW))
        except Exception:
            self._safe(lambda: self._lbl_update.config(
                text="\U0001f535 local", fg=FG_DIM))

        threading.Timer(5 * 60, lambda: threading.Thread(
            target=self._worker_git_remote, daemon=True).start()).start()

    def _worker_image(self):
        tag = _read_image_tag()
        self._safe(lambda t=tag:
                   self._lbl_image.config(text=f"\U0001f433 {t}"))

    def _worker_daemon(self):
        ok  = _daemon_ok()
        dot = "\U0001f7e2" if ok else "\U0001f534"
        fg  = GREEN if ok else RED
        self._safe(lambda d=dot, c=fg:
                   self._lbl_daemon.config(text=f"daemon {d}", fg=c))
        threading.Timer(30, lambda: threading.Thread(
            target=self._worker_daemon, daemon=True).start()).start()

    def _tick_clock(self):
        if _ET:
            now     = datetime.now(_ET)
            is_dst  = bool(now.dst() and now.dst().total_seconds() > 0)
            tz_abbr = "EDT" if is_dst else "EST"
        else:
            now     = datetime.utcnow()
            tz_abbr = "UTC"
        self._lbl_time.config(text=f"{tz_abbr} {now.strftime('%H:%M')}")
        self.after(10_000, self._tick_clock)

    def _click_branch(self, _event=None):
        if not self._content:
            return
        try:
            from auger.ui.widgets.github import GitHubWidget
            self._content.add_widget_tab("GitHub", GitHubWidget)
        except Exception as e:
            print(f"[status_bar] branch click: {e}")

    def _click_image(self, _event=None):
        if not self._content:
            return
        try:
            from auger.ui.widgets.artifactory import ArtifactoryWidget
            self._content.add_widget_tab("Artifactory", ArtifactoryWidget)
        except Exception as e:
            print(f"[status_bar] image click: {e}")
