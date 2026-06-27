"""Gab.ai widget slice 1: Ask Gabby panel + model/session header + tool settings."""

from __future__ import annotations

import json
import queue
import re
import threading
import tkinter as tk
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from tkinter import ttk, messagebox

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
GREEN = "#4ec9b0"
RED = "#f44747"

ENV_FILE = state_dir() / ".env"
SESSIONS_FILE = state_dir() / "logs" / "gab_sessions.json"
TOOLS_FILE = state_dir() / "gab_tools.json"
STATE_FILE = state_dir() / "gab_widget_state.json"


def make_icon(size: int = 18, color: str = "#9cdcfe"):
    """Simple G icon badge for tab use."""
    if Image is None or ImageDraw is None:
        return None
    s2 = size * 2
    img = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([1, 1, s2 - 2, s2 - 2], radius=max(3, s2 // 6), outline=color, width=max(1, s2 // 10))
    d.text((s2 * 0.30, s2 * 0.16), "G", fill=color)
    return img.resize((size, size), Image.LANCZOS)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(part for part in parts if part.strip())
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        if isinstance(value.get("content"), str):
            return value["content"]
    return str(value)


class GabWidget(tk.Frame):
    """Gab.ai integration widget with Ask Gabby prompt panel."""

    WIDGET_TITLE = "Gab.ai"
    WIDGET_ICON_FUNC = staticmethod(make_icon)
    WIDGET_DEMO_DATA = {
        "base_url": "https://gab.ai/v1",
        "model": "arya",
        "prompt": "Summarize modernization options for this service.",
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._q: queue.Queue[tuple] = queue.Queue()
        self._session_label_to_id: dict[str, str] = {}

        self._base_url = tk.StringVar(value=self.WIDGET_DEMO_DATA["base_url"])
        self._api_key = tk.StringVar(value="")
        self._model = tk.StringVar(value=self.WIDGET_DEMO_DATA["model"])
        self._session_var = tk.StringVar(value="")
        self._models: list[str] = [self.WIDGET_DEMO_DATA["model"]]
        self._sessions: list[dict] = []
        self._active_session_id = ""
        self._tools: list[dict] = []
        self._settings_win = None

        self._build_ui()
        self._load_env()
        self._load_tools()
        self._load_sessions()
        self._load_state()
        self._refresh_session_options()
        self._render_session()
        self.after(80, self._poll_queue)
        self.after(180, self._refresh_models)

    def _build_ui(self):
        header = tk.Frame(self, bg=BG3)
        header.pack(fill=tk.X)
        tk.Label(header, text="Gab.ai", fg=ACCENT, bg=BG3, font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT, padx=10, pady=6)
        tk.Label(header, text="Ask Gabby", fg=MUTED, bg=BG3, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=6)

        tk.Label(header, text="Model:", fg=FG, bg=BG3, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(18, 4))
        self._model_combo = ttk.Combobox(header, textvariable=self._model, values=self._models, state="normal", width=34, font=("Consolas", 10))
        self._model_combo.pack(side=tk.LEFT, pady=4)
        self._model_combo.bind("<<ComboboxSelected>>", lambda _e: self._save_state())

        tk.Label(header, text="Session:", fg=FG, bg=BG3, font=("Segoe UI", 9)).pack(side=tk.LEFT, padx=(10, 4))
        self._session_combo = ttk.Combobox(header, textvariable=self._session_var, values=[], state="readonly", width=24, font=("Segoe UI", 10))
        self._session_combo.pack(side=tk.LEFT, pady=4)
        self._session_combo.bind("<<ComboboxSelected>>", self._on_session_change)

        tk.Button(header, text="New", bg=BG2, fg=FG, relief=tk.FLAT, command=self._new_session).pack(side=tk.LEFT, padx=(6, 0), pady=4)
        tk.Button(header, text="Delete", bg=BG2, fg=FG, relief=tk.FLAT, command=self._delete_session).pack(side=tk.LEFT, padx=(4, 0), pady=4)
        tk.Button(header, text="Settings", bg=BG2, fg=FG, relief=tk.FLAT, command=self._open_settings).pack(side=tk.RIGHT, padx=(0, 8), pady=4)
        tk.Button(header, text="Refresh Models", bg=BG2, fg=FG, relief=tk.FLAT, command=self._refresh_models).pack(side=tk.RIGHT, padx=(0, 6), pady=4)

        output_wrap = tk.Frame(self, bg=BG)
        output_wrap.pack(fill=tk.BOTH, expand=True, padx=10, pady=(8, 0))
        self._output = tk.Text(output_wrap, bg=BG2, fg=FG, wrap=tk.WORD, relief=tk.FLAT, font=("Consolas", 10), height=14)
        scroll = tk.Scrollbar(output_wrap, command=self._output.yview)
        self._output.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self._output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        prompt_wrap = tk.Frame(self, bg=BG)
        prompt_wrap.pack(fill=tk.X, padx=10, pady=(8, 10))
        tk.Label(prompt_wrap, text="Ask Gabby", fg=FG, bg=BG, font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        row = tk.Frame(prompt_wrap, bg=BG)
        row.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self._prompt = tk.Text(row, bg=BG2, fg=FG, height=5, relief=tk.FLAT, font=("Segoe UI", 10), insertbackground=FG)
        self._prompt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._prompt.insert("1.0", self.WIDGET_DEMO_DATA["prompt"])
        btn_col = tk.Frame(row, bg=BG)
        btn_col.pack(side=tk.LEFT, padx=(8, 0))
        tk.Button(btn_col, text="Ask", bg=BLUE, fg="white", relief=tk.FLAT, width=12, command=self._ask_gabby).pack(pady=(0, 6))
        tk.Button(btn_col, text="Clear", bg=BG3, fg=FG, relief=tk.FLAT, width=12, command=self._clear_output).pack()

    def _poll_queue(self):
        try:
            while True:
                item = self._q.get_nowait()
                kind = item[0]
                if kind == "models":
                    models = item[1]
                    if models:
                        self._models = models
                        self._model_combo["values"] = models
                        if self._model.get().strip() not in models:
                            self._model.set(models[0])
                        self._append_line("ok", f"Gab.ai: loaded {len(models)} model(s)")
                    else:
                        self._append_line("err", "Gab.ai: no models returned")
                    self._save_state()
                elif kind == "assistant":
                    assistant_msg = item[1]
                    self._append_assistant_message(assistant_msg)
                elif kind == "log":
                    self._append_line(item[1], item[2])
        except queue.Empty:
            pass
        self.after(120, self._poll_queue)

    def _append_line(self, level: str, text: str):
        color = GREEN if level == "ok" else RED if level == "err" else FG
        tag = f"line_{level}"
        self._output.tag_config(tag, foreground=color)
        self._output.insert(tk.END, text + "\n", (tag,))
        self._output.see(tk.END)

    def _append_assistant_message(self, assistant_msg: dict):
        session = self._current_session()
        if session is None:
            return
        session["messages"].append(assistant_msg)
        session["updated_at"] = _utc_now()
        self._save_sessions()
        self._render_session()

    def _normalize_base_url(self) -> str:
        base = self._base_url.get().strip().rstrip("/")
        if not base:
            base = "https://gab.ai/v1"
        if not base.endswith("/v1"):
            base = f"{base}/v1"
        return base

    def _models_url(self) -> str:
        return f"{self._normalize_base_url()}/models"

    def _chat_url(self) -> str:
        return f"{self._normalize_base_url()}/chat/completions"

    def _load_env(self):
        env = dotenv_values(ENV_FILE) if ENV_FILE.exists() else {}
        self._base_url.set((env.get("GAB_BASE_URL") or self._base_url.get() or "").strip())
        self._api_key.set((env.get("GAB_API_KEY") or "").strip())
        self._model.set((env.get("GAB_MODEL") or self._model.get() or "").strip())

    def _load_state(self):
        if not STATE_FILE.exists():
            return
        try:
            payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        model = str(payload.get("selected_model") or "").strip()
        if model:
            self._model.set(model)
        active = str(payload.get("active_session_id") or "").strip()
        if active and any(s.get("id") == active for s in self._sessions):
            self._active_session_id = active

    def _save_state(self):
        payload = {
            "selected_model": self._model.get().strip(),
            "active_session_id": self._active_session_id,
        }
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _request_json_or_text(self, url: str, api_key: str, method: str = "GET", payload: dict | None = None):
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body

    def _refresh_models(self):
        api_key = self._api_key.get().strip()
        if not api_key:
            self._append_line("err", "Gab.ai: API key required in API Keys+ (GAB_API_KEY)")
            return

        def work():
            try:
                status, body = self._request_json_or_text(self._models_url(), api_key, method="GET")
                if status < 200 or status >= 300:
                    self._q.put(("log", "err", f"Gab.ai: model fetch failed (HTTP {status})"))
                    return
                payload = json.loads(body) if body.strip() else {}
                names = [str(item.get("id")).strip() for item in payload.get("data", []) if str(item.get("id") or "").strip()]
                self._q.put(("models", names[:120]))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:200]
                except Exception:
                    detail = ""
                self._q.put(("log", "err", f"Gab.ai: model fetch failed (HTTP {e.code}) {detail}".strip()))
            except Exception as e:
                self._q.put(("log", "err", f"Gab.ai: model fetch failed ({str(e)[:120]})"))

        threading.Thread(target=work, daemon=True).start()

    def _load_sessions(self):
        SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        if SESSIONS_FILE.exists():
            try:
                payload = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
                self._sessions = list(payload.get("sessions") or [])
                self._active_session_id = str(payload.get("active_session_id") or "").strip()
            except Exception:
                self._sessions = []
                self._active_session_id = ""
        if not self._sessions:
            self._sessions = [self._new_session_obj("Session 1")]
            self._active_session_id = self._sessions[0]["id"]
            self._save_sessions()
        if not self._active_session_id or not any(s.get("id") == self._active_session_id for s in self._sessions):
            self._active_session_id = self._sessions[0]["id"]
        self._save_state()

    def _save_sessions(self):
        payload = {
            "active_session_id": self._active_session_id,
            "sessions": self._sessions,
        }
        SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SESSIONS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _new_session_obj(self, name: str) -> dict:
        now = _utc_now()
        return {
            "id": str(uuid.uuid4()),
            "name": name,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }

    def _refresh_session_options(self):
        self._session_label_to_id = {}
        values = []
        for idx, sess in enumerate(self._sessions, start=1):
            label = f"{sess.get('name') or f'Session {idx}'}"
            sid = str(sess.get("id") or "")
            if sid:
                label = f"{label} ({sid[:8]})"
                self._session_label_to_id[label] = sid
                values.append(label)
        self._session_combo["values"] = values
        current = next((label for label, sid in self._session_label_to_id.items() if sid == self._active_session_id), "")
        self._session_var.set(current)
        self._save_state()

    def _current_session(self) -> dict | None:
        return next((sess for sess in self._sessions if sess.get("id") == self._active_session_id), None)

    def _on_session_change(self, _event=None):
        label = self._session_var.get()
        sid = self._session_label_to_id.get(label, "")
        if sid:
            self._active_session_id = sid
            self._save_sessions()
            self._save_state()
            self._render_session()

    def _new_session(self):
        name = f"Session {len(self._sessions) + 1}"
        sess = self._new_session_obj(name)
        self._sessions.append(sess)
        self._active_session_id = sess["id"]
        self._save_sessions()
        self._refresh_session_options()
        self._render_session()
        self._append_line("ok", f"Gab.ai: started {name}")

    def _delete_session(self):
        if len(self._sessions) <= 1:
            self._append_line("err", "Gab.ai: cannot delete the last session")
            return
        current = self._current_session()
        if not current:
            return
        if not messagebox.askyesno("Delete Session", "Delete current Gab.ai session?"):
            return
        self._sessions = [sess for sess in self._sessions if sess.get("id") != current.get("id")]
        self._active_session_id = self._sessions[0]["id"]
        self._save_sessions()
        self._refresh_session_options()
        self._render_session()

    def _render_session(self):
        self._output.delete("1.0", tk.END)
        session = self._current_session()
        if not session:
            return
        for msg in session.get("messages", []):
            role = str(msg.get("role") or "").strip().lower()
            if role == "user":
                self._append_line("info", f"You: {_safe_text(msg.get('content')).strip()}")
            elif role == "assistant":
                text = _safe_text(msg.get("content")).strip()
                if text:
                    self._append_line("ok", f"Gabby: {text}")
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    names = ", ".join(
                        str((tc.get("function") or {}).get("name") or "tool")
                        for tc in tool_calls
                    )
                    self._append_line("info", f"Gabby requested tool calls: {names}")
            elif role == "tool":
                self._append_line("info", f"Tool: {_safe_text(msg.get('content')).strip()}")

    def _enabled_tools_payload(self) -> list[dict]:
        payload = []
        for tool in self._tools:
            if not tool.get("enabled"):
                continue
            name = str(tool.get("name") or "").strip()
            description = str(tool.get("description") or "").strip()
            parameters = tool.get("parameters")
            if not name or not isinstance(parameters, dict):
                continue
            payload.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description,
                        "parameters": parameters,
                    },
                }
            )
        return payload

    def _ask_gabby(self):
        prompt = self._prompt.get("1.0", tk.END).strip()
        api_key = self._api_key.get().strip()
        model = self._model.get().strip()
        session = self._current_session()
        if not session:
            self._append_line("err", "Gab.ai: no active session")
            return
        if not prompt:
            self._append_line("err", "Gab.ai: prompt required")
            return
        if not api_key:
            self._append_line("err", "Gab.ai: API key required in API Keys+ (GAB_API_KEY)")
            return
        if not model:
            self._append_line("err", "Gab.ai: model required")
            return

        user_msg = {"role": "user", "content": prompt}
        session["messages"].append(user_msg)
        session["updated_at"] = _utc_now()
        self._save_sessions()
        self._render_session()
        self._append_line("info", "Gabby: thinking...")
        self._save_state()

        def work(messages_snapshot: list[dict]):
            payload = {
                "model": model,
                "messages": messages_snapshot,
                "temperature": 0.2,
            }
            tools = self._enabled_tools_payload()
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"
            try:
                status, body = self._request_json_or_text(self._chat_url(), api_key, method="POST", payload=payload)
                if status < 200 or status >= 300:
                    self._q.put(("log", "err", f"Gab.ai: request failed (HTTP {status})"))
                    return
                data = json.loads(body) if body.strip() else {}
                choice = ((data.get("choices") or [{}])[0] or {})
                message = choice.get("message") or {}
                assistant_msg = {
                    "role": "assistant",
                    "content": _safe_text(message.get("content")),
                }
                tool_calls = message.get("tool_calls") or []
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                    if not assistant_msg["content"]:
                        assistant_msg["content"] = "Tool calls requested. Tool execution loop will be added in a follow-up slice."
                self._q.put(("assistant", assistant_msg))
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", errors="replace")[:220]
                except Exception:
                    detail = ""
                self._q.put(("log", "err", f"Gab.ai: request failed (HTTP {e.code}) {detail}".strip()))
            except Exception as e:
                self._q.put(("log", "err", f"Gab.ai: request failed ({str(e)[:120]})"))

        snapshot = list(session["messages"][-30:])
        threading.Thread(target=work, args=(snapshot,), daemon=True).start()

    def _clear_output(self):
        self._output.delete("1.0", tk.END)

    def _load_tools(self):
        if TOOLS_FILE.exists():
            try:
                payload = json.loads(TOOLS_FILE.read_text(encoding="utf-8"))
                tools = payload.get("tools") or []
                if isinstance(tools, list):
                    self._tools = tools
                    return
            except Exception:
                pass
        self._tools = []

    def _save_tools(self):
        payload = {"tools": self._tools}
        TOOLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TOOLS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _open_settings(self):
        if self._settings_win and self._settings_win.winfo_exists():
            self._settings_win.focus_set()
            return

        win = tk.Toplevel(self)
        win.title("Gab.ai Settings")
        win.configure(bg=BG)
        win.geometry("860x520")
        self._settings_win = win

        tk.Label(
            win,
            text="Define and enable tool schemas for Ask Gabby. Execution loop comes in a follow-up slice.",
            bg=BG,
            fg=MUTED,
            anchor="w",
            justify="left",
            font=("Segoe UI", 9),
        ).pack(fill=tk.X, padx=10, pady=(10, 6))

        root = tk.Frame(win, bg=BG)
        root.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        left = tk.Frame(root, bg=BG)
        left.pack(side=tk.LEFT, fill=tk.Y)
        tk.Label(left, text="Tools", bg=BG, fg=FG, font=("Segoe UI", 9, "bold")).pack(anchor=tk.W)
        tool_list = tk.Listbox(left, bg=BG2, fg=FG, selectbackground=BLUE, width=34, height=20, relief=tk.FLAT)
        tool_list.pack(fill=tk.Y, expand=False, pady=(4, 0))

        right = tk.Frame(root, bg=BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10, 0))

        name_var = tk.StringVar()
        desc_var = tk.StringVar()
        enabled_var = tk.BooleanVar(value=True)
        editing_index = {"idx": None}

        def refresh_list():
            tool_list.delete(0, tk.END)
            for tool in self._tools:
                mark = "[x]" if tool.get("enabled") else "[ ]"
                tool_list.insert(tk.END, f"{mark} {tool.get('name', 'unnamed')}")

        def clear_form():
            editing_index["idx"] = None
            name_var.set("")
            desc_var.set("")
            enabled_var.set(True)
            params_text.delete("1.0", tk.END)
            params_text.insert("1.0", json.dumps({"type": "object", "properties": {}}, indent=2))

        def load_selected(_event=None):
            sel = tool_list.curselection()
            if not sel:
                return
            idx = sel[0]
            tool = self._tools[idx]
            editing_index["idx"] = idx
            name_var.set(str(tool.get("name") or ""))
            desc_var.set(str(tool.get("description") or ""))
            enabled_var.set(bool(tool.get("enabled")))
            params = tool.get("parameters") if isinstance(tool.get("parameters"), dict) else {"type": "object", "properties": {}}
            params_text.delete("1.0", tk.END)
            params_text.insert("1.0", json.dumps(params, indent=2))

        def upsert_tool():
            name = name_var.get().strip()
            description = desc_var.get().strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name):
                messagebox.showerror("Invalid Tool Name", "Tool name must match [A-Za-z0-9_-]{1,64}")
                return
            try:
                params = json.loads(params_text.get("1.0", tk.END).strip() or "{}")
            except Exception as exc:
                messagebox.showerror("Invalid JSON", f"Parameters must be valid JSON: {exc}")
                return
            if not isinstance(params, dict):
                messagebox.showerror("Invalid JSON", "Tool parameters JSON must be an object.")
                return
            tool_obj = {
                "name": name,
                "description": description,
                "enabled": bool(enabled_var.get()),
                "parameters": params,
            }
            idx = editing_index["idx"]
            if idx is None:
                self._tools.append(tool_obj)
            else:
                self._tools[idx] = tool_obj
            self._save_tools()
            refresh_list()

        def remove_tool():
            sel = tool_list.curselection()
            if not sel:
                return
            idx = sel[0]
            if not messagebox.askyesno("Remove Tool", "Remove selected tool?"):
                return
            self._tools.pop(idx)
            self._save_tools()
            refresh_list()
            clear_form()

        def toggle_enabled():
            sel = tool_list.curselection()
            if not sel:
                return
            idx = sel[0]
            self._tools[idx]["enabled"] = not bool(self._tools[idx].get("enabled"))
            self._save_tools()
            refresh_list()
            load_selected()

        row = tk.Frame(right, bg=BG)
        row.pack(fill=tk.X)
        tk.Label(row, text="Name:", bg=BG, fg=FG, width=12, anchor="w").pack(side=tk.LEFT)
        tk.Entry(row, textvariable=name_var, bg=BG2, fg=FG, relief=tk.FLAT, insertbackground=FG).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row2 = tk.Frame(right, bg=BG)
        row2.pack(fill=tk.X, pady=(6, 0))
        tk.Label(row2, text="Description:", bg=BG, fg=FG, width=12, anchor="w").pack(side=tk.LEFT)
        tk.Entry(row2, textvariable=desc_var, bg=BG2, fg=FG, relief=tk.FLAT, insertbackground=FG).pack(side=tk.LEFT, fill=tk.X, expand=True)

        row3 = tk.Frame(right, bg=BG)
        row3.pack(fill=tk.X, pady=(6, 0))
        tk.Checkbutton(
            row3,
            text="Enabled",
            variable=enabled_var,
            bg=BG,
            fg=FG,
            selectcolor=BG2,
            activebackground=BG,
            activeforeground=FG,
        ).pack(side=tk.LEFT)

        tk.Label(right, text="Parameters JSON Schema:", bg=BG, fg=FG).pack(anchor=tk.W, pady=(8, 4))
        params_text = tk.Text(right, bg=BG2, fg=FG, relief=tk.FLAT, height=14, font=("Consolas", 10), insertbackground=FG)
        params_text.pack(fill=tk.BOTH, expand=True)

        btns = tk.Frame(right, bg=BG)
        btns.pack(fill=tk.X, pady=(8, 0))
        tk.Button(btns, text="New", bg=BG3, fg=FG, relief=tk.FLAT, command=clear_form).pack(side=tk.LEFT)
        tk.Button(btns, text="Save / Update", bg=BLUE, fg="white", relief=tk.FLAT, command=upsert_tool).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(btns, text="Remove", bg=BG3, fg=FG, relief=tk.FLAT, command=remove_tool).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(btns, text="Toggle Enabled", bg=BG3, fg=FG, relief=tk.FLAT, command=toggle_enabled).pack(side=tk.LEFT, padx=(6, 0))
        tk.Button(btns, text="Close", bg=BG3, fg=FG, relief=tk.FLAT, command=win.destroy).pack(side=tk.RIGHT)

        tool_list.bind("<<ListboxSelect>>", load_selected)
        refresh_list()
        clear_form()

