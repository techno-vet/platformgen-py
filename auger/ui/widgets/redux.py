"""ReDuX widget: settings + Ask ReDuX panel (slice 1/2)."""

from __future__ import annotations

import json
import queue
import re
import threading
import tkinter as tk
import urllib.error
import urllib.request

from dotenv import dotenv_values

from platformgen.runtime import state_dir

try:
    from PIL import Image, ImageDraw
except Exception:  # pragma: no cover
    Image = None
    ImageDraw = None

BG = "#1e1e1e"
BG2 = "#252526"
BG3 = "#2d2d2d"
FG = "#e0e0e0"
MUTED = "#8b949e"
ACCENT = "#4ec9b0"
BLUE = "#007acc"
RED = "#f44747"
GREEN = "#4ec9b0"

ENV_FILE = state_dir() / ".env"


def make_icon(size: int = 18, color: str = "#c586c0"):
    """Simple R icon badge for tab use."""
    if Image is None or ImageDraw is None:
        return None
    s2 = size * 2
    img = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, s2 - 2, s2 - 2], radius=max(3, s2 // 6), outline=color, width=max(1, s2 // 10))
    d.text((s2 * 0.33, s2 * 0.18), "R", fill=color)
    return img.resize((size, size), Image.LANCZOS)


class ReduxWidget(tk.Frame):
    """ReDuX integration widget (slice 1 + 2)."""

    WIDGET_TITLE = "ReDuX"
    WIDGET_ICON_FUNC = staticmethod(make_icon)
    WIDGET_DEMO_DATA = {
        "api_url": "http://localhost:4200",
        "model": "redux-default",
        "prompt": "Summarize modernization options for this service.",
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._q: queue.Queue[tuple[str, str]] = queue.Queue()

        self._api_url = tk.StringVar(value=self.WIDGET_DEMO_DATA["api_url"])
        self._api_key = tk.StringVar(value="")
        self._model = tk.StringVar(value=self.WIDGET_DEMO_DATA["model"])

        self._build_ui()
        self._load_env()
        self.after(80, self._poll_queue)

    def _build_ui(self):
        header = tk.Frame(self, bg=BG3)
        header.pack(fill=tk.X)
        tk.Label(header, text="ReDuX", fg=ACCENT, bg=BG3, font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT, padx=10, pady=6)
        tk.Label(header, text="Settings + Ask ReDuX", fg=MUTED, bg=BG3, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=6)

        settings = tk.Frame(self, bg=BG)
        settings.pack(fill=tk.X, padx=10, pady=(10, 6))

        self._add_labeled_entry(settings, "API URL", self._api_url)
        self._add_labeled_entry(settings, "API Key", self._api_key, masked=True)
        self._add_labeled_entry(settings, "Model", self._model)

        btns = tk.Frame(settings, bg=BG)
        btns.pack(fill=tk.X, pady=(8, 0))
        tk.Button(btns, text="Save Settings", bg=BLUE, fg="white", relief=tk.FLAT, command=self._save_env).pack(side=tk.LEFT)
        tk.Button(btns, text="Test API", bg=GREEN, fg="#111111", relief=tk.FLAT, command=self._test_api).pack(side=tk.LEFT, padx=8)

        chat_frame = tk.Frame(self, bg=BG)
        chat_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 10))

        tk.Label(chat_frame, text="Ask ReDuX", fg=FG, bg=BG, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)

        output_wrap = tk.Frame(chat_frame, bg=BG)
        output_wrap.pack(fill=tk.BOTH, expand=True)
        self._output = tk.Text(output_wrap, bg=BG2, fg=FG, wrap=tk.WORD, relief=tk.FLAT, font=("Consolas", 10), height=15)
        scroll = tk.Scrollbar(output_wrap, command=self._output.yview)
        self._output.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        prompt_row = tk.Frame(chat_frame, bg=BG)
        prompt_row.pack(fill=tk.X, pady=(8, 0))
        self._prompt = tk.Text(prompt_row, bg=BG2, fg=FG, height=4, relief=tk.FLAT, font=("Segoe UI", 10), insertbackground=FG)
        self._prompt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._prompt.insert("1.0", self.WIDGET_DEMO_DATA["prompt"])
        btn_col = tk.Frame(prompt_row, bg=BG)
        btn_col.pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(btn_col, text="Ask", bg=BLUE, fg="white", relief=tk.FLAT, width=12, command=self._ask_redux).pack(pady=(0, 6))
        tk.Button(btn_col, text="Clear", bg=BG3, fg=FG, relief=tk.FLAT, width=12, command=self._clear_output).pack()

    def _add_labeled_entry(self, parent, label, var, masked: bool = False):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill=tk.X, pady=2)
        tk.Label(row, text=f"{label}:", width=10, anchor=tk.W, fg=FG, bg=BG, font=("Segoe UI", 10)).pack(side=tk.LEFT)
        show = "*" if masked else ""
        tk.Entry(row, textvariable=var, show=show, bg=BG2, fg=FG, relief=tk.FLAT, insertbackground=FG, font=("Consolas", 10)).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _poll_queue(self):
        try:
            while True:
                kind, msg = self._q.get_nowait()
                color = GREEN if kind == "ok" else RED if kind == "err" else FG
                self._output.insert(tk.END, msg + "\n", (kind,))
                self._output.tag_config(kind, foreground=color)
                self._output.see(tk.END)
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _load_env(self):
        env = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
        self._api_url.set((env.get("REDUX_API_URL") or self._api_url.get() or "").strip())
        self._api_key.set((env.get("REDUX_API_KEY") or "").strip())
        self._model.set((env.get("REDUX_MODEL") or self._model.get() or "").strip())
        self._q.put(("info", f"Loaded settings from {ENV_FILE}"))

    def _write_env_key(self, key: str, value: str):
        ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not ENV_FILE.exists():
            ENV_FILE.write_text("", encoding="utf-8")
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
        pat = re.compile(rf"^{re.escape(key)}=")
        new_line = f"{key}={value}"
        replaced = False
        for i, line in enumerate(lines):
            if pat.match(line):
                lines[i] = new_line
                replaced = True
                break
        if not replaced:
            lines.append(new_line)
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _save_env(self):
        self._write_env_key("REDUX_API_URL", self._api_url.get().strip())
        self._write_env_key("REDUX_API_KEY", self._api_key.get().strip())
        self._write_env_key("REDUX_MODEL", self._model.get().strip())
        self._q.put(("ok", "ReDuX: saved settings to .env"))

    def _models_url(self) -> str:
        base = self._api_url.get().strip().rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/models"
        if base.endswith("/models"):
            return base
        return f"{base}/v1/models"

    def _chat_url(self) -> str:
        base = self._api_url.get().strip().rstrip("/")
        if base.endswith("/v1"):
            return f"{base}/chat/completions"
        if base.endswith("/chat/completions"):
            return base
        return f"{base}/v1/chat/completions"

    def _test_api(self):
        api_key = self._api_key.get().strip()
        if not api_key:
            self._q.put(("err", "ReDuX: API key required"))
            return

        def work():
            try:
                req = urllib.request.Request(
                    self._models_url(),
                    headers={
                        "Accept": "application/json",
                        "Authorization": f"Bearer {api_key}",
                    },
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                names = [m.get("id") for m in payload.get("data", []) if m.get("id")][:3]
                if names:
                    self._q.put(("ok", f"ReDuX: API test passed (models: {', '.join(names)})"))
                else:
                    self._q.put(("ok", "ReDuX: API test passed"))
            except urllib.error.HTTPError as e:
                self._q.put(("err", f"ReDuX: API test failed (HTTP {e.code})"))
            except Exception as e:
                self._q.put(("err", f"ReDuX: API test failed ({str(e)[:120]})"))

        threading.Thread(target=work, daemon=True).start()

    def _ask_redux(self):
        prompt = self._prompt.get("1.0", tk.END).strip()
        api_key = self._api_key.get().strip()
        model = self._model.get().strip()
        if not prompt:
            self._q.put(("err", "ReDuX: prompt required"))
            return
        if not api_key:
            self._q.put(("err", "ReDuX: API key required"))
            return
        if not model:
            self._q.put(("err", "ReDuX: model required"))
            return

        self._q.put(("info", f"You: {prompt}"))
        self._q.put(("info", "ReDuX: thinking..."))

        def work():
            body = json.dumps(
                {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.2,
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                self._chat_url(),
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                answer = ""
                choices = payload.get("choices") or []
                if choices:
                    answer = (choices[0].get("message") or {}).get("content") or ""
                if not answer:
                    answer = payload.get("output_text") or ""
                if not answer:
                    answer = json.dumps(payload)[:500]
                self._q.put(("ok", f"ReDuX: {answer.strip()}"))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8")[:220]
                except Exception:
                    detail = ""
                self._q.put(("err", f"ReDuX: request failed (HTTP {e.code}) {detail}"))
            except Exception as e:
                self._q.put(("err", f"ReDuX: request failed ({str(e)[:120]})"))

        threading.Thread(target=work, daemon=True).start()

    def _clear_output(self):
        self._output.delete("1.0", tk.END)
