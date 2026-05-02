"""Local Genny agent backed by Ollama with a lightweight native tool loop."""

from __future__ import annotations

import json
import subprocess
import threading
import traceback
import urllib.request
from pathlib import Path
from typing import Callable

from auger.runtime import repo_dir

OLLAMA_BASE = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:14b"
WORK_DIR = str(repo_dir() or Path.cwd())
MAX_OUTPUT_CHARS = 4000
MAX_STEPS = 6


def run_bash(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
            cwd=WORK_DIR,
        )
        output = result.stdout
        if result.stderr:
            output += "\n[stderr]\n" + result.stderr
        return _truncate_output(output.strip() or "(no output)")
    except subprocess.TimeoutExpired:
        return "[error] Command timed out after 60s"
    except Exception as exc:
        return f"[error] {exc}"


def read_file(path: str) -> str:
    try:
        target = Path(path)
        if not target.is_absolute():
            target = Path(WORK_DIR) / target
        return _truncate_output(target.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        return f"[error] {exc}"


def write_file(path: str, content: str) -> str:
    try:
        target = Path(path)
        if not target.is_absolute():
            target = Path(WORK_DIR) / target
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Written {target} ({len(content)} chars)"
    except Exception as exc:
        return f"[error] {exc}"


def list_directory(path: str) -> str:
    try:
        target = Path(path)
        if not target.is_absolute():
            target = Path(WORK_DIR) / target
        entries = sorted(target.iterdir(), key=lambda entry: (entry.is_file(), entry.name))
        return _truncate_output("\n".join(f"{'📁' if entry.is_dir() else '📄'} {entry.name}" for entry in entries) or "(empty)")
    except Exception as exc:
        return f"[error] {exc}"


TOOLS = {
    "run_bash": run_bash,
    "read_file": read_file,
    "write_file": write_file,
    "list_directory": list_directory,
}


class GennyRunner:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        self._model_name = model_name
        self._stop = False

    def reset_model(self, model_name: str):
        self._model_name = model_name

    def run(
        self,
        prompt: str,
        on_step: Callable[[str], None],
        on_done: Callable[[str], None],
        on_error: Callable[[str], None],
    ):
        self._stop = False

        def _work():
            try:
                answer = self._run_loop(prompt, on_step)
                if self._stop:
                    on_done("(stopped)")
                else:
                    on_done(answer)
            except InterruptedError:
                on_done("(stopped)")
            except Exception as exc:
                on_error(f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}")

        threading.Thread(target=_work, daemon=True).start()

    def stop(self):
        self._stop = True

    def _run_loop(self, prompt: str, on_step: Callable[[str], None]) -> str:
        messages: list[dict[str, str]] = [
            {"role": "system", "content": _system_prompt()},
            {"role": "user", "content": prompt},
        ]

        for _ in range(MAX_STEPS):
            if self._stop:
                raise InterruptedError("stopped")

            action = self._chat_json(messages)
            kind = str(action.get("action", "")).strip().lower()

            if kind == "final":
                answer = str(action.get("answer", "")).strip()
                return answer or "I couldn't produce a final answer."

            if kind != "tool":
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Invalid response. Return JSON only with either "
                            '{"action":"tool",...} or {"action":"final","answer":"..."}'
                        ),
                    }
                )
                continue

            tool_name = str(action.get("tool", "")).strip()
            args = action.get("args", {})
            if tool_name not in TOOLS:
                messages.append(
                    {
                        "role": "user",
                        "content": f"Unknown tool '{tool_name}'. Valid tools: {', '.join(sorted(TOOLS))}.",
                    }
                )
                continue

            if not isinstance(args, dict):
                messages.append({"role": "user", "content": f"Tool args for {tool_name} must be an object."})
                continue

            result = self._execute_tool(tool_name, args)
            on_step(_format_step(tool_name, args, result))
            messages.append({"role": "assistant", "content": json.dumps(action)})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Tool result for {tool_name}:\n```text\n{result}\n```\n"
                        "Now either use another tool or return the final answer."
                    ),
                }
            )

        return "I ran out of tool steps before reaching a final answer."

    def _chat_json(self, messages: list[dict[str, str]]) -> dict:
        payload = json.dumps(
            {
                "model": self._model_name,
                "messages": messages,
                "stream": False,
                "format": "json",
            }
        ).encode()
        request = urllib.request.Request(
            f"{OLLAMA_BASE}/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=180) as response:
            body = json.loads(response.read().decode())
        content = body.get("message", {}).get("content", "").strip()
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError(f"Expected JSON object from model, got: {type(parsed).__name__}")

    def _execute_tool(self, tool_name: str, args: dict) -> str:
        tool = TOOLS[tool_name]
        if tool_name == "run_bash":
            return tool(str(args.get("command", "")))
        if tool_name == "read_file":
            return tool(str(args.get("path", "")))
        if tool_name == "write_file":
            return tool(str(args.get("path", "")), str(args.get("content", "")))
        if tool_name == "list_directory":
            return tool(str(args.get("path", "")))
        raise ValueError(f"Unsupported tool: {tool_name}")


def _system_prompt() -> str:
    return (
        "You are Genny inside PlatformGen with access to live tools.\n"
        f"Your working directory is: {WORK_DIR}\n"
        "When the answer depends on the current repo, branch, commit, files, CLI state, or shell output, "
        "you must use a tool instead of guessing.\n"
        "Do not say you lack real-time access when tools can answer the question.\n"
        "Available tools:\n"
        "1. run_bash(command): run shell commands in the repo working directory.\n"
        "2. read_file(path): read a file.\n"
        "3. write_file(path, content): write a file.\n"
        "4. list_directory(path): list a directory.\n"
        "Return JSON only, no markdown fences.\n"
        'Tool call format: {"action":"tool","tool":"run_bash","args":{"command":"git branch --show-current && git rev-parse HEAD"}}\n'
        'Final format: {"action":"final","answer":"..."}\n'
        "Prefer concise, direct final answers."
    )


def _format_step(tool_name: str, args: dict, result: str) -> str:
    return f"🔧 **{tool_name}**(`{_truncate_inline(json.dumps(args, ensure_ascii=True), 180)}`)\n```\n{_truncate_output(result, 600)}\n```"


def _truncate_inline(text: str, max_len: int) -> str:
    return text if len(text) <= max_len else text[:max_len] + "…"


def _truncate_output(text: str, max_len: int = MAX_OUTPUT_CHARS) -> str:
    return text if len(text) <= max_len else text[:max_len] + "\n…[truncated]"
