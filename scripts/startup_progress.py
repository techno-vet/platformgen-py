#!/usr/bin/env python3
"""Simple startup progress window for Auger host-side launches."""

from __future__ import annotations

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk


class StartupProgressWindow:
    def __init__(self, log_file: Path, title: str):
        self.log_file = log_file
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("760x420")
        self.root.configure(bg="#1e1e1e")
        self.root.attributes("-topmost", True)
        self.root.resizable(True, True)

        self.status_var = tk.StringVar(value="Starting Auger...")
        self._last_text = ""
        self._done_seen = False
        self._error_seen = False

        self._build_ui()
        self.root.after(250, self._poll)

    def _build_ui(self) -> None:
        bg = "#1e1e1e"
        bg2 = "#252526"
        fg = "#d4d4d4"
        accent = "#4ec9b0"

        tk.Label(
            self.root,
            text="Auger startup",
            bg=bg,
            fg=accent,
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 6))

        ttk.Progressbar(self.root, mode="indeterminate", length=720).pack(
            fill="x", padx=14, pady=(0, 10)
        )
        for child in self.root.winfo_children():
            if isinstance(child, ttk.Progressbar):
                child.start(12)

        tk.Label(
            self.root,
            textvariable=self.status_var,
            bg=bg,
            fg=fg,
            anchor="w",
            justify="left",
            wraplength=720,
            font=("Segoe UI", 10),
        ).pack(fill="x", padx=14, pady=(0, 10))

        frame = tk.Frame(self.root, bg=bg2, highlightbackground="#3c3c3c", highlightthickness=1)
        frame.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        self.text = tk.Text(
            frame,
            bg=bg2,
            fg=fg,
            insertbackground=fg,
            relief="flat",
            wrap="word",
            font=("Consolas", 9),
            state="disabled",
        )
        scrollbar = tk.Scrollbar(frame, command=self.text.yview)
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        scrollbar.pack(side="right", fill="y", pady=8, padx=(0, 8))

    def _read_log(self) -> tuple[str, str, bool, bool]:
        if not self.log_file.exists():
            return "", "Starting Auger...", False, False

        raw = self.log_file.read_text(errors="replace")
        status = "Starting Auger..."
        visible_lines: list[str] = []
        done_seen = False
        error_seen = False

        for line in raw.splitlines():
            if line == "STATE:done":
                done_seen = True
                continue
            if line == "STATE:error":
                error_seen = True
                continue
            if not line.strip():
                continue
            visible_lines.append(line)
            status = line

        return "\n".join(visible_lines), status, done_seen, error_seen

    def _poll(self) -> None:
        text, status, done_seen, error_seen = self._read_log()
        if text != self._last_text:
            self.text.configure(state="normal")
            self.text.delete("1.0", tk.END)
            if text:
                self.text.insert("1.0", text)
            self.text.configure(state="disabled")
            self.text.see(tk.END)
            self._last_text = text

        self.status_var.set(status)

        if error_seen and not self._error_seen:
            self.root.bell()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self._error_seen = True

        if done_seen and not self._done_seen:
            self._done_seen = True
            self.root.after(1500, self.root.destroy)
            return

        self.root.after(400, self._poll)

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Auger startup progress")
    parser.add_argument("--log-file", required=True, help="Path to startup progress log")
    parser.add_argument("--title", default="Auger Startup", help="Window title")
    args = parser.parse_args()

    StartupProgressWindow(Path(args.log_file), args.title).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
