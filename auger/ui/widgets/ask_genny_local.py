"""Local Ollama-backed Ask Genny widget for PlatformGen."""

from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
import urllib.request
import urllib.error
from tkinter import ttk

BG = "#1e1e1e"
BG2 = "#252526"
BG3 = "#2d2d2d"
FG = "#e0e0e0"
FG2 = "#888888"
ACC = "#007acc"
GREEN = "#4ec9b0"
YELLOW = "#f0c040"
RED = "#f44747"
PURPLE = "#c586c0"
FONT = ("Helvetica", 10, "normal")
MONO = ("Courier New", 10, "normal")

OLLAMA_BASE = os.environ.get("OLLAMA_BASE_URL", os.environ.get("OLLAMA_BASE", "http://localhost:11434"))


def _list_models() -> list[str]:
    try:
        req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags", headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        return [model["name"] for model in data.get("models", [])]
    except Exception:
        return []


class AskGennyLocalWidget(tk.Frame):
    WIDGET_TITLE = "Ask Genny (Local LLM)"

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._model_var = tk.StringVar(value="")
        self._runner = None
        self._busy = False
        self._agent_available = self._can_use_agent_mode()
        self._agent_mode = tk.BooleanVar(value=self._agent_available)
        self._ui_queue: queue.Queue[tuple] = queue.Queue()
        self._build_ui()
        self.after(50, self._drain_ui_queue)
        self.after(100, self._refresh_models)

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG3, pady=4)
        hdr.pack(fill=tk.X)

        tk.Label(hdr, text="Ask Genny (Local LLM)", bg=BG3, fg=ACC, font=("Helvetica", 11, "bold")).pack(side=tk.LEFT, padx=10)
        tk.Label(hdr, text="Model:", bg=BG3, fg=FG2, font=FONT).pack(side=tk.LEFT, padx=(20, 4))

        self._model_combo = ttk.Combobox(hdr, textvariable=self._model_var, state="readonly", width=28, font=FONT)
        self._model_combo.pack(side=tk.LEFT)
        self._model_combo.bind("<<ComboboxSelected>>", self._on_model_change)

        self._status = tk.Label(hdr, text="offline", bg=BG3, fg=RED, font=FONT)
        self._status.pack(side=tk.LEFT, padx=10)

        self._agent_check = tk.Checkbutton(
            hdr,
            text="Agent mode",
            variable=self._agent_mode,
            bg=BG3,
            fg=FG,
            selectcolor=BG2,
            activebackground=BG3,
            activeforeground=FG,
            font=FONT,
            cursor="hand2",
            state=tk.NORMAL if self._agent_available else tk.DISABLED,
        )
        self._agent_check.pack(side=tk.LEFT, padx=10)

        tk.Button(hdr, text="Refresh", bg=BG3, fg=FG2, relief=tk.FLAT, font=FONT, cursor="hand2",
                  command=self._refresh_models).pack(side=tk.RIGHT, padx=2)
        tk.Button(hdr, text="Clear", bg=BG3, fg=FG2, relief=tk.FLAT, font=FONT, cursor="hand2",
                  command=self._clear_chat).pack(side=tk.RIGHT, padx=4)

        if not self._agent_available:
            tk.Label(hdr, text="agent deps optional", bg=BG3, fg=YELLOW, font=("Helvetica", 8)).pack(side=tk.RIGHT, padx=8)

        chat_frame = tk.Frame(self, bg=BG)
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=(6, 0))

        self._chat = tk.Text(chat_frame, bg=BG2, fg=FG, font=MONO, wrap=tk.WORD, state=tk.DISABLED,
                             relief=tk.FLAT, bd=0, spacing1=2, spacing3=4, cursor="arrow", height=10)
        sb = tk.Scrollbar(chat_frame, orient=tk.VERTICAL, command=self._chat.yview, bg=BG3, troughcolor=BG3)
        self._chat.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._chat.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._chat.tag_config("user_label", foreground=ACC, font=("Helvetica", 9, "bold"))
        self._chat.tag_config("user_text", foreground=FG)
        self._chat.tag_config("genny_label", foreground=GREEN, font=("Helvetica", 9, "bold"))
        self._chat.tag_config("genny_text", foreground=FG)
        self._chat.tag_config("step_label", foreground=PURPLE, font=("Helvetica", 9, "bold"))
        self._chat.tag_config("step_text", foreground=YELLOW, font=("Courier New", 9))
        self._chat.tag_config("thinking", foreground=FG2, font=("Helvetica", 9, "italic"))
        self._chat.tag_config("error_text", foreground=RED)

        inp_frame = tk.Frame(self, bg=BG3)
        inp_frame.pack(fill=tk.X, padx=6, pady=(4, 6))

        btn_col = tk.Frame(inp_frame, bg=BG3)
        btn_col.pack(side=tk.RIGHT, padx=4, pady=4)

        self._send_btn = tk.Button(btn_col, text="Ask", bg=ACC, fg="#ffffff", relief=tk.FLAT,
                                   font=("Helvetica", 10, "bold"), cursor="hand2", padx=14, pady=8, command=self._send)
        self._send_btn.pack()
        self._stop_btn = tk.Button(btn_col, text="Stop", bg="#555555", fg="#ffffff", relief=tk.FLAT,
                                   font=("Helvetica", 10, "bold"), cursor="hand2", padx=14, pady=8,
                                   command=self._stop, state=tk.DISABLED)
        self._stop_btn.pack(pady=(6, 0))

        input_border = tk.Frame(inp_frame, bg=ACC, bd=1)
        input_border.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, pady=4)
        self._input = tk.Text(input_border, bg=BG2, fg=FG, font=FONT, wrap=tk.WORD, relief=tk.FLAT,
                              bd=6, height=5, insertbackground=FG)
        self._input.pack(fill=tk.BOTH, expand=True)
        self._input.bind("<Return>", self._on_enter)
        self._input.bind("<Shift-Return>", lambda _e: None)

        tk.Label(self, text="Shift+Enter for newline  •  Enter to send", bg=BG, fg=FG2, font=("Helvetica", 8)).pack(pady=(0, 2))

    def _can_use_agent_mode(self) -> bool:
        try:
            from auger.ui.agents.genny_agent import GennyRunner  # noqa: F401
            return True
        except Exception:
            return False

    def _refresh_models(self):
        threading.Thread(target=lambda: self._ui_call(self._on_models, _list_models()), daemon=True).start()

    def _on_models(self, models: list[str]):
        if models:
            self._model_combo["values"] = models
            preferred = next((m for m in models if "qwen2.5-coder" in m.lower() or "qweb-2.5-coder" in m.lower()), models[0])
            if not self._model_var.get():
                self._model_var.set(preferred)
            self._status.config(text="online", fg=GREEN)
        else:
            self._model_combo["values"] = []
            self._status.config(text="offline", fg=RED)

    def _on_model_change(self, _event=None):
        self._runner = None

    def _get_runner(self):
        from auger.ui.agents.genny_agent import GennyRunner

        if self._runner is None:
            self._runner = GennyRunner(model_name=self._model_var.get())
        return self._runner

    def _on_enter(self, event):
        if event.state & 0x1:
            return None
        self._send()
        return "break"

    def _send(self):
        if self._busy:
            return
        prompt = self._input.get("1.0", tk.END).strip()
        if not prompt:
            return
        if not self._model_var.get():
            self._append("error_text", "No Ollama model selected. Click Refresh.\n\n")
            return

        self._input.delete("1.0", tk.END)
        self._append_user(prompt)
        self._busy = True
        self._send_btn.config(state=tk.DISABLED)
        self._stop_btn.config(state=tk.NORMAL)

        if self._agent_mode.get():
            if not self._agent_available:
                self._emit_error("Agent mode requires optional local dependencies; use plain mode for normal chat.")
                return
            self._run_agent(prompt)
        else:
            self._run_plain(prompt)

    def _run_agent(self, prompt: str):
        self._append("thinking", "Genny is thinking and may use tools...\n")
        runner = self._get_runner()
        runner.run(
            prompt,
            on_step=lambda text: self._ui_call(self._emit_step, text),
            on_done=lambda text: self._ui_call(self._emit_answer, text),
            on_error=lambda text: self._ui_call(self._emit_error, text),
        )

    def _emit_step(self, text: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, "  step › ", "step_label")
        self._chat.insert(tk.END, text + "\n", "step_text")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _emit_answer(self, text: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, "\nGenny: ", "genny_label")
        self._chat.insert(tk.END, text.strip() + "\n\n", "genny_text")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)
        self._end_busy()

    def _emit_error(self, text: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, f"[error] {text}\n\n", "error_text")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)
        self._end_busy()

    def _run_plain(self, prompt: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, "Genny: ", "genny_label")
        self._plain_start = self._chat.index(tk.END)
        self._chat.insert(tk.END, "...\n", "thinking")
        self._chat.config(state=tk.DISABLED)
        self._first_plain_token = True

        def _work():
            try:
                payload = json.dumps({
                    "model": self._model_var.get(),
                    "messages": self._plain_messages(prompt),
                    "stream": True,
                }).encode()
                req = urllib.request.Request(
                    f"{OLLAMA_BASE}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    for raw in resp:
                        if not self._busy:
                            break
                        chunk = json.loads(raw.decode().strip() or "{}")
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            self._ui_call(self._plain_token, token)
                        if chunk.get("done"):
                            break
            except Exception as exc:
                self._ui_call(self._emit_error, str(exc))
                return
            self._ui_call(self._plain_done)

        threading.Thread(target=_work, daemon=True).start()

    def _plain_messages(self, prompt: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are Genny inside PlatformGen. "
                    "Do not identify yourself as Qwen, Alibaba Cloud, or a generic model name. "
                    "Answer as Genny, the local PlatformGen assistant. "
                    "If the user asks whether you are there, reply briefly and directly as Genny."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def _agent_messages(self, prompt: str) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "You are Genny inside PlatformGen. "
                    "Respond as Genny, not as Qwen, Alibaba Cloud, or a generic model. "
                    "Keep answers direct and helpful. "
                    "If the user asks whether you are there, answer briefly as Genny."
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def _complete_once(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({
            "model": self._model_var.get(),
            "messages": messages,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_BASE}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = json.loads(resp.read().decode())
        return body.get("message", {}).get("content", "").strip()

    def _plain_token(self, token: str):
        self._chat.config(state=tk.NORMAL)
        if self._first_plain_token:
            self._chat.delete(self._plain_start, tk.END)
            self._first_plain_token = False
        self._chat.insert(tk.END, token, "genny_text")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _plain_done(self):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, "\n\n")
        self._chat.config(state=tk.DISABLED)
        self._end_busy()

    def _stop(self):
        if self._runner:
            self._runner.stop()
        self._busy = False
        self._end_busy()

    def _end_busy(self):
        self._busy = False
        self._send_btn.config(state=tk.NORMAL)
        self._stop_btn.config(state=tk.DISABLED)

    def _append_user(self, text: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, "You: ", "user_label")
        self._chat.insert(tk.END, text + "\n\n", "user_text")
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _append(self, tag: str, text: str):
        self._chat.config(state=tk.NORMAL)
        self._chat.insert(tk.END, text, tag)
        self._chat.config(state=tk.DISABLED)
        self._chat.see(tk.END)

    def _clear_chat(self):
        self._runner = None
        self._chat.config(state=tk.NORMAL)
        self._chat.delete("1.0", tk.END)
        self._chat.config(state=tk.DISABLED)

    def _ui_call(self, func, *args):
        self._ui_queue.put((func, args))

    def _drain_ui_queue(self):
        try:
            while True:
                func, args = self._ui_queue.get_nowait()
                func(*args)
        except queue.Empty:
            pass
        try:
            self.after(50, self._drain_ui_queue)
        except tk.TclError:
            pass
