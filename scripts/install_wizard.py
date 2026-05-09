#!/usr/bin/env python3
"""PlatformGen desktop installer wrapper over the Python-first installer core."""

from __future__ import annotations

import argparse
import queue
import sys
import threading
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[1]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from platformgen.installer import APP_NAME, CLIInstallUI, DEFAULT_DAEMON_PORT, DEFAULT_REPO_DIR, DEFAULT_STATE_DIR, InstallOptions, InstallUI, run_install


def _build_options(args: argparse.Namespace) -> InstallOptions:
    return InstallOptions(
        state_dir=Path(args.state_dir),
        repo_dir=Path(args.repo_dir),
        daemon_port=args.daemon_port,
        launch=not args.no_launch,
        create_launchers=not args.no_launchers,
        interactive=not args.non_interactive,
        install_copilot=args.install_copilot,
        copy_legacy_state=not args.skip_legacy_migration,
    )


class TkInstallUI(InstallUI):
    interactive = True

    def __init__(self):
        import tkinter as tk
        from tkinter import scrolledtext

        self._tk = tk
        self._queue: queue.Queue = queue.Queue()
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} Installer")
        self.root.geometry("760x580")
        self.root.configure(bg="#1e1e1e")
        self.root.protocol("WM_DELETE_WINDOW", self.root.destroy)
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(500, lambda: self.root.attributes("-topmost", False))

        header = tk.Frame(self.root, bg="#007acc", pady=10)
        header.pack(fill=tk.X)
        tk.Label(
            header,
            text=f"{APP_NAME} Installer",
            bg="#007acc",
            fg="white",
            font=("Segoe UI", 13, "bold"),
        ).pack(side=tk.LEFT, padx=16)

        self.log_widget = scrolledtext.ScrolledText(
            self.root,
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="#d4d4d4",
            relief=tk.FLAT,
            wrap=tk.WORD,
            font=("Consolas", 10),
            state=tk.DISABLED,
            padx=12,
            pady=10,
        )
        self.log_widget.pack(fill=tk.BOTH, expand=True)
        for name, color in {
            "ok": "#4ec9b0",
            "warn": "#f0c040",
            "err": "#f44747",
            "info": "#569cd6",
            "dim": "#888888",
        }.items():
            self.log_widget.tag_configure(name, foreground=color)

        bottom = tk.Frame(self.root, bg="#252526", pady=6)
        bottom.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar(value="Initializing installer…")
        tk.Label(bottom, textvariable=self.status_var, bg="#252526", fg="#888888").pack(side=tk.LEFT, padx=12)
        self.close_btn = tk.Button(bottom, text="Close", state=tk.DISABLED, command=self.root.destroy)
        self.close_btn.pack(side=tk.RIGHT, padx=12)

        self.root.after(50, self._drain_queue)

    def _enqueue(self, fn):
        self._queue.put(fn)

    def _drain_queue(self):
        while True:
            try:
                fn = self._queue.get_nowait()
            except queue.Empty:
                break
            fn()
        if self.root.winfo_exists():
            self.root.after(50, self._drain_queue)

    def log(self, message: str, level: str = "info") -> None:
        tag = {
            "ok": "ok",
            "warn": "warn",
            "error": "err",
            "err": "err",
            "dim": "dim",
            "info": "info",
        }.get(level, None)

        def _write():
            self.log_widget.configure(state="normal")
            self.log_widget.insert("end", message + "\n", tag)
            self.log_widget.configure(state="disabled")
            self.log_widget.see("end")

        self._enqueue(_write)

    def status(self, message: str) -> None:
        self._enqueue(lambda: self.status_var.set(message))

    def ask_text(self, prompt: str, default: str = "", secret: bool = False) -> str:
        from tkinter import simpledialog

        result = [default]
        event = threading.Event()

        def _ask():
            result[0] = simpledialog.askstring(
                f"{APP_NAME} Installer",
                prompt,
                show="*" if secret else None,
                initialvalue=default,
                parent=self.root,
            ) or default
            event.set()

        self._enqueue(_ask)
        event.wait()
        return str(result[0]).strip()

    def confirm(self, prompt: str, default: bool = True) -> bool:
        from tkinter import messagebox

        result = [default]
        event = threading.Event()

        def _ask():
            if default:
                result[0] = messagebox.askyesno(f"{APP_NAME} Installer", prompt, parent=self.root)
            else:
                result[0] = messagebox.askyesno(f"{APP_NAME} Installer", prompt, parent=self.root, default="no")
            event.set()

        self._enqueue(_ask)
        event.wait()
        return bool(result[0])

    def mark_done(self, success: bool) -> None:
        def _done():
            self.status_var.set("Installation complete" if success else "Installation failed")
            self.close_btn.configure(state="normal")

        self._enqueue(_done)

    def run(self, options: InstallOptions) -> int:
        result = {"code": 1}

        def _worker():
            try:
                run_install(options, self)
                result["code"] = 0
                self.mark_done(True)
            except Exception as exc:
                self.log(f"[ERROR] {exc}", "err")
                self.mark_done(False)

        threading.Thread(target=_worker, daemon=True).start()
        self.root.mainloop()
        return int(result["code"])


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} desktop installer")
    parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    parser.add_argument("--repo-dir", default=str(DEFAULT_REPO_DIR))
    parser.add_argument("--daemon-port", type=int, default=DEFAULT_DAEMON_PORT)
    parser.add_argument("--no-launch", action="store_true")
    parser.add_argument("--no-launchers", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--install-copilot", choices=("auto", "skip", "always"), default="auto")
    parser.add_argument("--skip-legacy-migration", action="store_true")
    parser.add_argument("--cli", action="store_true", help="Run in terminal mode instead of Tk UI")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    options = _build_options(args)
    if args.cli:
        try:
            run_install(options, CLIInstallUI(interactive=options.interactive))
            return 0
        except Exception as exc:
            print(f"[ERROR] {exc}")
            return 1

    try:
        import tkinter  # noqa: F401
    except ImportError:
        print("tkinter is not installed; falling back to terminal mode.")
        try:
            run_install(options, CLIInstallUI(interactive=options.interactive))
            return 0
        except Exception as exc:
            print(f"[ERROR] {exc}")
            return 1

    return TkInstallUI().run(options)


if __name__ == "__main__":
    raise SystemExit(main())
