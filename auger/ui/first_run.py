"""
First-run setup wizard for the runtime-configured platform.

Shown once when GHE_TOKEN is not configured in the runtime .env.
Guides user through GitHub token entry, validation, and Copilot test.
"""

import os
import sys
import threading
import subprocess
import tkinter as tk
from tkinter import ttk
from pathlib import Path

from auger.ui import icons as _icons
from auger.runtime import app_name, assistant_name, cli_name, product_name, state_dir

ENV_FILE = state_dir() / ".env"

# UI colours (match platform theme)
BG      = "#1e1e1e"
BG2     = "#252526"
BG3     = "#2d2d2d"
FG      = "#e0e0e0"
ACCENT  = "#007acc"
GREEN   = "#4ec9b0"
RED     = "#f44747"
YELLOW  = "#ce9178"
SUBTLE  = "#808080"


# ─── Detection ────────────────────────────────────────────────────────────────

def is_first_run() -> bool:
    """Return True if GHE_TOKEN is not yet configured."""
    # Check environment first (passed via docker-run.sh -e GH_TOKEN)
    for key in ("GH_TOKEN", "GHE_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"):
        if os.environ.get(key, "").strip():
            return False
    # Check .env file
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip() in ("GH_TOKEN", "GHE_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"):
                if v.strip():
                    return False
    return True


def _write_ghe_token(token: str):
    """Write or update GHE_TOKEN in the runtime env file."""
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    found = False
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                lines.append(line)
                continue
            k = stripped.split("=", 1)[0].strip()
            if k in ("GH_TOKEN", "GHE_TOKEN"):
                if not found:
                    lines.append(f"GHE_TOKEN={token}")
                    found = True
                # drop duplicate GHE_TOKEN lines
            else:
                lines.append(line)
    if not found:
        lines.append(f"GHE_TOKEN={token}")
    ENV_FILE.write_text("\n".join(lines) + "\n")


def _validate_token(token: str) -> tuple[bool, str]:
    """Validate a GitHub.com token by hitting the API. Returns (ok, message)."""
    try:
        import urllib.request, json as _json
        # Wizard always sets up github.com tokens for Copilot
        api_url = "https://api.github.com/user"
        req = urllib.request.Request(api_url, headers={
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "auger-platform/1.0",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read())
            login = data.get("login", "unknown")
            return True, f"Authenticated as {login}"
    except Exception as e:
        msg = str(e)
        if "401" in msg or "Unauthorized" in msg:
            return False, "Invalid token (401 Unauthorized)"
        if "403" in msg or "Forbidden" in msg:
            return False, "Access forbidden (403) — check token scopes"
        if "404" in msg:
            return False, "GHE host not reachable — check network/proxy"
        return False, f"Connection error: {msg[:80]}"


def _test_copilot(token: str) -> tuple[bool, str]:
    """Test that the configured CLI works with the token. Returns (ok, message)."""
    auger_bin = _find_auger()
    if not auger_bin:
        return False, f"{cli_name()} CLI not found — ensure it is installed"
    env = dict(os.environ)
    env["GH_TOKEN"] = token
    env["GHE_TOKEN"] = token
    env["GITHUB_TOKEN"] = token
    env["COPILOT_GITHUB_TOKEN"] = token
    try:
        result = subprocess.run(
            [auger_bin, "ping"],
            capture_output=True, text=True, timeout=20, env=env
        )
        combined = (result.stdout + result.stderr).strip()
        if result.returncode == 0:
            return True, "Copilot session established"
        # Non-zero but might still have a response
        if any(w in combined.lower() for w in ("hello", "hi", "copilot", "assist")):
            return True, "Copilot responding"
        return False, f"{cli_name()} returned exit code {result.returncode}: {combined[:120]}"
    except subprocess.TimeoutExpired:
        return False, "Copilot test timed out (>20s)"
    except Exception as e:
        return False, f"Error running auger: {e}"


def _find_auger() -> str | None:
    import shutil
    return shutil.which(cli_name()) or (
        str(Path.home() / f".local/bin/{cli_name()}")
        if (Path.home() / f".local/bin/{cli_name()}").exists() else None
    )


# ─── Wizard Dialog ────────────────────────────────────────────────────────────

class FirstRunWizard(tk.Toplevel):
    """Modal first-run setup wizard."""

    STEPS = ["welcome", "token", "validate", "copilot", "done"]

    def __init__(self, parent: tk.Tk):
        super().__init__(parent)
        self.parent = parent
        self.title(f"{product_name()} — First-Time Setup")
        self.geometry("620x500")
        self.resizable(False, False)
        self.configure(bg=BG)

        # Centre on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() - 620) // 2
        y = (self.winfo_screenheight() - 500) // 2
        self.geometry(f"620x500+{x}+{y}")

        # Block parent window
        self.transient(parent)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_close_attempt)

        self._token_var   = tk.StringVar()
        self._status_var  = tk.StringVar()
        self._completed   = False

        # Load icons
        try:
            self._ico_key     = _icons.get("key",     32)
            self._ico_check   = _icons.get("check",   32)
            self._ico_error   = _icons.get("error",   32)
            self._ico_connect = _icons.get("connect", 32)
            self._ico_home    = _icons.get("home",    32)
        except Exception:
            self._ico_key = self._ico_check = self._ico_error = \
                self._ico_connect = self._ico_home = None

        self._build_ui()
        self._show_step("welcome")

    # ── Layout ──────────────────────────────────────────────────────────────

    def _build_ui(self):
        # Header bar
        hdr = tk.Frame(self, bg=ACCENT, height=52)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"  {product_name()} — First-Time Setup",
                 font=("Segoe UI", 13, "bold"), fg="white", bg=ACCENT
                 ).pack(side=tk.LEFT, padx=16, pady=12)

        # Progress bar (step indicator)
        self._prog_frame = tk.Frame(self, bg=BG2, height=6)
        self._prog_frame.pack(fill=tk.X)
        self._prog_canvas = tk.Canvas(self._prog_frame, bg=BG2,
                                      height=6, highlightthickness=0)
        self._prog_canvas.pack(fill=tk.X)

        # Body (swapped per step)
        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)

        # Footer
        ftr = tk.Frame(self, bg=BG2, height=56)
        ftr.pack(fill=tk.X, side=tk.BOTTOM)
        ftr.pack_propagate(False)
        self._btn_back = tk.Button(
            ftr, text=" Back", font=("Segoe UI", 10),
            bg=BG3, fg=FG, relief=tk.FLAT, padx=20, pady=6,
            command=self._go_back)
        self._btn_back.pack(side=tk.LEFT, padx=16, pady=12)
        self._btn_next = tk.Button(
            ftr, text="Next ", font=("Segoe UI", 10, "bold"),
            bg=ACCENT, fg="white", relief=tk.FLAT, padx=20, pady=6,
            command=self._go_next)
        self._btn_next.pack(side=tk.RIGHT, padx=16, pady=12)
        self._status_lbl = tk.Label(ftr, textvariable=self._status_var,
                                    font=("Segoe UI", 9), fg=SUBTLE, bg=BG2,
                                    anchor=tk.W)
        self._status_lbl.pack(side=tk.LEFT, padx=8, fill=tk.X, expand=True)

    def _update_progress(self, step_name: str):
        step_idx = self.STEPS.index(step_name)
        total    = len(self.STEPS) - 1  # exclude 'done' visually
        frac     = min(step_idx / total, 1.0)
        self._prog_canvas.update_idletasks()
        w = self._prog_canvas.winfo_width() or 620
        self._prog_canvas.delete("all")
        self._prog_canvas.create_rectangle(0, 0, int(w * frac), 6, fill=GREEN, outline="")

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()

    # ── Step rendering ───────────────────────────────────────────────────────

    def _show_step(self, step: str):
        self._current_step = step
        self._clear_body()
        self._update_progress(step)
        getattr(self, f"_step_{step}")()

    def _step_welcome(self):
        self._btn_back.config(state=tk.DISABLED)
        self._btn_next.config(text="Get Started  ", state=tk.NORMAL)
        self._status_var.set("")

        if self._ico_home:
            tk.Label(self._body, image=self._ico_home, bg=BG).pack(pady=(10, 0))

        tk.Label(self._body, text="Welcome to Auger SRE Platform",
                 font=("Segoe UI", 16, "bold"), fg=GREEN, bg=BG).pack(pady=(8, 4))

        tk.Label(self._body,
                 text="Auger uses GitHub Copilot as its AI backbone.\n"
                      "This wizard will configure your GitHub token so\n"
                      "Ask Auger can help you set up everything else.",
                 font=("Segoe UI", 11), fg=FG, bg=BG, justify=tk.CENTER
                 ).pack(pady=(0, 16))

        info = tk.Frame(self._body, bg=BG3, pady=10, padx=14)
        info.pack(fill=tk.X)
        tk.Label(info, text="What you need:", font=("Segoe UI", 10, "bold"),
                 fg=YELLOW, bg=BG3).pack(anchor=tk.W)
        for bullet in (
            "A GitHub Personal Access Token (classic) with read:org and copilot scopes",
            "Network access to your GitHub instance",
        ):
            tk.Label(info, text=f"  •  {bullet}", font=("Segoe UI", 10),
                     fg=FG, bg=BG3, justify=tk.LEFT).pack(anchor=tk.W, pady=1)

    def _step_token(self):
        self._btn_back.config(state=tk.NORMAL)
        self._btn_next.config(text="Validate Token  ", state=tk.NORMAL)
        self._status_var.set("")

        if self._ico_key:
            tk.Label(self._body, image=self._ico_key, bg=BG).pack(pady=(0, 4))

        tk.Label(self._body, text="Enter your GitHub Token",
                 font=("Segoe UI", 14, "bold"), fg=GREEN, bg=BG).pack(pady=(0, 6))

        tk.Label(self._body,
                 text="Paste your GitHub Personal Access Token below.\n"
                       f"It will be saved to {ENV_FILE} on your host.",
                 font=("Segoe UI", 10), fg=FG, bg=BG, justify=tk.CENTER
                 ).pack(pady=(0, 14))

        entry_frame = tk.Frame(self._body, bg=BG3, pady=8, padx=12)
        entry_frame.pack(fill=tk.X)
        tk.Label(entry_frame, text="GHE_TOKEN", font=("Segoe UI", 9),
                 fg=SUBTLE, bg=BG3).pack(anchor=tk.W)
        self._token_entry = tk.Entry(
            entry_frame, textvariable=self._token_var,
            font=("Consolas", 11), bg="#1a1a2e", fg=GREEN,
            insertbackground=GREEN, relief=tk.FLAT,
            show="*", width=52
        )
        self._token_entry.pack(fill=tk.X, pady=(2, 0))
        self._token_entry.bind("<Return>", lambda e: self._go_next())

        # Show/hide toggle
        self._show_token = tk.BooleanVar(value=False)
        tk.Checkbutton(
            entry_frame, text="Show token",
            variable=self._show_token,
            command=lambda: self._token_entry.config(
                show="" if self._show_token.get() else "*"),
            bg=BG3, fg=SUBTLE, selectcolor=BG3,
            activebackground=BG3, font=("Segoe UI", 9)
        ).pack(anchor=tk.W, pady=(4, 0))

        # Token help link (text only)
        tk.Label(self._body,
                 text="github.com → Settings → Developer settings → Personal access tokens → Fine-grained",
                 font=("Segoe UI", 9), fg=SUBTLE, bg=BG).pack(pady=(6, 0))
        tk.Label(self._body,
                 text="Required scope:  Copilot Editor → Read-only  (no repo access needed)",
                 font=("Segoe UI", 9), fg=SUBTLE, bg=BG).pack(pady=(2, 0))

        self._token_entry.focus_set()

    def _step_validate(self):
        """Validation in-progress step (auto-advances)."""
        self._btn_back.config(state=tk.DISABLED)
        self._btn_next.config(state=tk.DISABLED)
        self._status_var.set("Validating token...")

        if self._ico_connect:
            tk.Label(self._body, image=self._ico_connect, bg=BG).pack(pady=(10, 4))

        tk.Label(self._body, text="Validating GitHub Token",
                 font=("Segoe UI", 14, "bold"), fg=GREEN, bg=BG).pack(pady=(0, 8))

        self._validate_msg = tk.StringVar(value="Contacting GitHub API...")
        self._validate_lbl = tk.Label(
            self._body, textvariable=self._validate_msg,
            font=("Segoe UI", 11), fg=YELLOW, bg=BG)
        self._validate_lbl.pack()

        token = self._token_var.get().strip()
        threading.Thread(target=self._do_validate, args=(token,), daemon=True).start()

    def _do_validate(self, token: str):
        ok, msg = _validate_token(token)
        self.after(0, lambda: self._on_validate_done(ok, msg, token))

    def _on_validate_done(self, ok: bool, msg: str, token: str):
        if ok:
            _write_ghe_token(token)
            self._validate_msg.set(f"Token valid — {msg}")
            self._validate_lbl.config(fg=GREEN)
            self._status_var.set(f"Token saved to {ENV_FILE}")
            self.after(1200, lambda: self._show_step("copilot"))
        else:
            self._validate_msg.set(f"Validation failed: {msg}")
            self._validate_lbl.config(fg=RED)
            self._status_var.set("Check token and try again")
            self._btn_back.config(state=tk.NORMAL)
            self._btn_next.config(text="Retry  ", state=tk.NORMAL,
                                  command=lambda: self._show_step("token"))

    def _step_copilot(self):
        """Test Copilot integration."""
        self._btn_back.config(state=tk.DISABLED)
        self._btn_next.config(state=tk.DISABLED)
        self._status_var.set("Testing Copilot...")

        if self._ico_check:
            tk.Label(self._body, image=self._ico_check, bg=BG).pack(pady=(10, 4))

        tk.Label(self._body, text=f"Testing Ask {assistant_name()}",
                 font=("Segoe UI", 14, "bold"), fg=GREEN, bg=BG).pack(pady=(0, 8))

        self._copilot_msg = tk.StringVar(value=f"Launching {cli_name()} CLI test...")
        self._copilot_lbl = tk.Label(
            self._body, textvariable=self._copilot_msg,
            font=("Segoe UI", 11), fg=YELLOW, bg=BG)
        self._copilot_lbl.pack()

        # Output box
        self._copilot_out = tk.Text(
            self._body, height=6, font=("Consolas", 9),
            bg=BG3, fg=FG, relief=tk.FLAT, state=tk.DISABLED)
        self._copilot_out.pack(fill=tk.X, pady=(12, 0))

        token = self._token_var.get().strip()
        threading.Thread(target=self._do_copilot_test, args=(token,), daemon=True).start()

    def _copilot_append(self, text: str):
        self._copilot_out.config(state=tk.NORMAL)
        self._copilot_out.insert(tk.END, text)
        self._copilot_out.see(tk.END)
        self._copilot_out.config(state=tk.DISABLED)

    def _do_copilot_test(self, token: str):
        self.after(0, lambda: self._copilot_append(f"$ {cli_name()} ping\n"))
        ok, msg = _test_copilot(token)
        self.after(0, lambda: self._copilot_append(f"{msg}\n"))
        self.after(0, lambda: self._on_copilot_done(ok, msg))

    def _on_copilot_done(self, ok: bool, msg: str):
        if ok:
            self._copilot_msg.set("Copilot is working!")
            self._copilot_lbl.config(fg=GREEN)
            self._status_var.set(f"Ready to use Ask {assistant_name()}")
            self.after(1200, lambda: self._show_step("done"))
        else:
            self._copilot_msg.set("Copilot test did not succeed")
            self._copilot_lbl.config(fg=YELLOW)
            self._status_var.set(f"You can still proceed — Ask {assistant_name()} may work once network is ready")
            self._btn_next.config(text="Continue anyway  ", state=tk.NORMAL,
                                  command=lambda: self._show_step("done"))

    def _step_done(self):
        self._completed = True
        self._btn_back.config(state=tk.DISABLED)
        self._btn_next.config(text=f"Open {app_name()}  ", state=tk.NORMAL,
                              command=self._finish)
        self._status_var.set("")

        if self._ico_check:
            tk.Label(self._body, image=self._ico_check, bg=BG).pack(pady=(10, 4))

        tk.Label(self._body, text="You're all set!",
                 font=("Segoe UI", 16, "bold"), fg=GREEN, bg=BG).pack(pady=(0, 6))

        tk.Label(self._body,
                 text="GitHub Copilot is configured.\n"
                       f"Ask {assistant_name()} can now help you configure everything else\n"
                       "— ServiceNow, Jenkins, Artifactory, Datadog, and more.",
                 font=("Segoe UI", 11), fg=FG, bg=BG, justify=tk.CENTER
                 ).pack(pady=(0, 16))

        tips = tk.Frame(self._body, bg=BG3, pady=10, padx=14)
        tips.pack(fill=tk.X)
        tk.Label(tips, text=f"Try asking {assistant_name()}:", font=("Segoe UI", 10, "bold"),
                 fg=YELLOW, bg=BG3).pack(anchor=tk.W)
        for prompt in (
            '"Help me configure my ServiceNow credentials"',
            '"Set up my Artifactory access token"',
            '"What can you help me with?"',
        ):
            tk.Label(tips, text=f"  •  {prompt}", font=("Consolas", 9),
                     fg=GREEN, bg=BG3, justify=tk.LEFT).pack(anchor=tk.W, pady=1)

    # ── Navigation ───────────────────────────────────────────────────────────

    _STEP_ORDER = ["welcome", "token", "validate", "copilot", "done"]

    def _go_next(self):
        step = self._current_step
        if step == "welcome":
            self._show_step("token")
        elif step == "token":
            token = self._token_var.get().strip()
            if not token:
                self._status_var.set("Please enter a token first")
                return
            self._show_step("validate")
        elif step == "done":
            self._finish()

    def _go_back(self):
        step = self._current_step
        if step == "token":
            self._show_step("welcome")

    def _finish(self):
        self._completed = True
        self.grab_release()
        self.destroy()

    def _on_close_attempt(self):
        """Allow closing only from done step."""
        if self._completed or self._current_step == "done":
            self._finish()
        else:
            # Allow skip with confirmation
            import tkinter.messagebox as mb
            if mb.askyesno(
                "Skip Setup?",
                f"Setup is not complete. You can still use {app_name()} but Ask {assistant_name()}\n"
                f"won't work until GHE_TOKEN is configured in {ENV_FILE}.\n\n"
                "Skip setup?",
                parent=self
            ):
                self.grab_release()
                self.destroy()


# ─── Entry Point ──────────────────────────────────────────────────────────────

def maybe_show_wizard(root: tk.Tk) -> bool:
    """Show first-run wizard if needed. Returns True if wizard was shown."""
    if not is_first_run():
        return False
    wizard = FirstRunWizard(root)
    root.wait_window(wizard)
    return True
