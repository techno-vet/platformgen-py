"""ComfyUI widget for text-to-image generation from PlatformGen."""

from __future__ import annotations

import io
import json
import os
import threading
import time
import tkinter as tk
from tkinter import ttk
from urllib.parse import urlencode

import requests
from dotenv import load_dotenv

from platformgen.runtime import state_dir

try:
    from PIL import Image, ImageDraw, ImageTk

    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


BG = "#1e1e1e"
BG2 = "#252526"
BG3 = "#2d2d2d"
FG = "#e0e0e0"
FG2 = "#888888"
ACC = "#007acc"
GREEN = "#4ec9b0"
YELLOW = "#f0c040"
RED = "#f44747"
FONT = ("Helvetica", 10, "normal")
MONO = ("Courier New", 9, "normal")

DEFAULT_SAMPLER = "dpmpp_2m_sde"
DEFAULT_SCHEDULER = "karras"
MIN_IMAGE_DIMENSION = 512

IMAGE_PRESETS = {
    "PlatformGen Launcher Icon": {
        "prompt_prefix": (
            "launcher icon, app icon, single centered symbol, clean vector mark, geometric platform layers, "
            "subtle PG monogram, dark background, neon blue accent, crisp edges, high contrast, minimal brand system"
        ),
        "prompt_suffix": "simple silhouette, readable at small size, polished product branding, no scene background",
        "negative_prompt": (
            "photorealistic, painterly, abstract art, busy composition, multiple objects, scenery, 3d render, "
            "text, letters, watermark, blur, soft edges, gradients, clutter"
        ),
        "width": "1024",
        "height": "1024",
        "steps": "34",
        "cfg": "7.0",
        "sampler": DEFAULT_SAMPLER,
        "scheduler": DEFAULT_SCHEDULER,
        "demo_prompt": "PlatformGen launcher icon for a desktop AI developer tool",
        "hint": "Best for brand-style icon ideas. Keep the prompt to one symbol or monogram, not a full scene.",
    },
    "Logo / Icon": {
        "prompt_prefix": "clean vector logo, centered composition, crisp edges, high contrast, minimal brand mark, professional graphic design",
        "negative_prompt": "photorealistic, painterly, cluttered composition, blur, noisy background, watermark, text artifacts",
        "width": "1024",
        "height": "1024",
        "steps": "28",
        "cfg": "6.5",
        "sampler": DEFAULT_SAMPLER,
        "scheduler": DEFAULT_SCHEDULER,
        "demo_prompt": "PlatformGen launcher icon, dark developer UI, neon blue accent, clean vector look",
        "hint": "General icon preset. Use the dedicated launcher preset if you want tighter app-icon shaping.",
    },
    "UI Mockup": {
        "prompt_prefix": "product UI mockup, polished dashboard screenshot, clean layout, readable panels, modern desktop app design",
        "negative_prompt": "abstract art, painterly style, distorted controls, extra windows, blurry text, watermark",
        "width": "1344",
        "height": "768",
        "steps": "30",
        "cfg": "6.0",
        "sampler": DEFAULT_SAMPLER,
        "scheduler": DEFAULT_SCHEDULER,
        "demo_prompt": "developer platform dashboard for AI tools, dark theme, cards, side navigation, premium desktop UX",
        "hint": "Use for desktop screenshots and dashboards, not icons or logos.",
    },
    "Concept Art": {
        "prompt_prefix": "detailed concept art, cinematic lighting, cohesive composition, clear focal subject, rich atmosphere",
        "negative_prompt": "low detail, muddy colors, overexposed, extra limbs, distorted anatomy, watermark, text artifacts",
        "width": "1024",
        "height": "1024",
        "steps": "32",
        "cfg": "7.0",
        "sampler": DEFAULT_SAMPLER,
        "scheduler": DEFAULT_SCHEDULER,
        "demo_prompt": "futuristic AI workspace on a cliff at dusk, holographic terminals, cinematic sky",
        "hint": "Use for mood and direction, not branding-ready icon work.",
    },
    "Product Shot": {
        "prompt_prefix": "studio product shot, clean backdrop, professional lighting, sharp focus, premium materials",
        "negative_prompt": "abstract shapes, cluttered background, low detail, motion blur, watermark, text artifacts",
        "width": "1024",
        "height": "1024",
        "steps": "28",
        "cfg": "6.0",
        "sampler": DEFAULT_SAMPLER,
        "scheduler": DEFAULT_SCHEDULER,
        "demo_prompt": "sleek desktop hardware device for AI creators, matte black, blue glow, studio photography",
        "hint": "Use for objects and devices, not logos or interface mockups.",
    },
}


def make_icon(size=18, color="#f0c040"):
    if not PIL_AVAILABLE:
        return None
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = max(1, size // 8)
    draw.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=max(2, size // 5),
        outline=color,
        width=max(1, size // 10),
    )
    draw.ellipse(
        [size // 4, size // 4, size - size // 4, size - size // 4],
        outline=color,
        width=max(1, size // 10),
    )
    draw.line(
        [(size // 2), size // 4, (size // 2), size - size // 4],
        fill=color,
        width=max(1, size // 12),
    )
    draw.line(
        [size // 4, size // 2, size - size // 4, size // 2],
        fill=color,
        width=max(1, size // 12),
    )
    return img


def _load_env():
    load_dotenv(state_dir() / ".env", override=True)


def _default_base() -> str:
    _load_env()
    return os.environ.get("COMFYUI_BASE_URL", "http://localhost:8188").rstrip("/")


class ComfyUIWidget(tk.Frame):
    WIDGET_TITLE = "ComfyUI"
    WIDGET_ICON_FUNC = staticmethod(make_icon)
    WIDGET_DEMO_DATA = {
        "prompt": "PlatformGen launcher icon, dark developer UI, neon blue accent, clean vector look",
        "negative_prompt": "blurry, low quality, text artifacts, watermark",
        "checkpoint": "v1-5-pruned-emaonly-fp16.safetensors",
    }

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        _load_env()
        self._busy = False
        self._photo = None
        self._ui_queue = []
        self._checkpoints: list[str] = []
        self._samplers: list[str] = []
        self._schedulers: list[str] = []
        self._base_var = tk.StringVar(value=_default_base())
        self._preset_var = tk.StringVar(value="PlatformGen Launcher Icon")
        self._preset_hint_var = tk.StringVar(value="")
        self._checkpoint_var = tk.StringVar(
            value=os.environ.get("COMFYUI_CHECKPOINT", self.WIDGET_DEMO_DATA["checkpoint"])
        )
        self._sampler_var = tk.StringVar(value=DEFAULT_SAMPLER)
        self._scheduler_var = tk.StringVar(value=DEFAULT_SCHEDULER)
        self._width_var = tk.StringVar(value="1024")
        self._height_var = tk.StringVar(value="1024")
        self._steps_var = tk.StringVar(value="24")
        self._cfg_var = tk.StringVar(value="7.0")
        self._seed_var = tk.StringVar(value="-1")
        self._status_var = tk.StringVar(value="offline")
        self._image_meta_var = tk.StringVar(value="No generated image yet.")
        self._build_ui()
        self._apply_preset_defaults(IMAGE_PRESETS.get(self._preset_var.get(), IMAGE_PRESETS["PlatformGen Launcher Icon"]), update_prompt=True)
        self.after(100, self._refresh_status)
        self.after(100, self._drain_ui)

    def _build_ui(self):
        hdr = tk.Frame(self, bg=BG3, pady=4)
        hdr.pack(fill=tk.X)

        tk.Label(hdr, text="ComfyUI", bg=BG3, fg=YELLOW, font=("Helvetica", 11, "bold")).pack(side=tk.LEFT, padx=10)
        tk.Label(hdr, text="Endpoint:", bg=BG3, fg=FG2, font=FONT).pack(side=tk.LEFT, padx=(10, 4))
        tk.Entry(hdr, textvariable=self._base_var, bg=BG2, fg=FG, insertbackground=FG, relief=tk.FLAT, width=34).pack(side=tk.LEFT)
        tk.Label(hdr, textvariable=self._status_var, bg=BG3, fg=FG, font=FONT).pack(side=tk.LEFT, padx=10)
        tk.Button(hdr, text="Refresh", command=self._refresh_status, bg=BG3, fg=FG, relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT, padx=4)
        tk.Button(hdr, text="Queue Prompt", command=self._queue_generation, bg=ACC, fg="white", relief=tk.FLAT, cursor="hand2").pack(side=tk.RIGHT, padx=4)

        main_frame = tk.Frame(self, bg=BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        canvas = tk.Canvas(main_frame, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_frame, orient=tk.VERTICAL, command=canvas.yview)
        content = tk.Frame(canvas, bg=BG)
        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=content, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        body = tk.Frame(content, bg=BG)
        body.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        body.grid_columnconfigure(0, weight=3, minsize=420)
        body.grid_columnconfigure(1, weight=2, minsize=360)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=BG)
        right = tk.Frame(body, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        right.grid(row=0, column=1, sticky="nsew")

        self._prompt = self._labeled_text(left, "Prompt", height=6)
        self._negative = self._labeled_text(left, "Negative Prompt", height=4)
        self._workflow = self._labeled_text(left, "Workflow Override (optional JSON)", height=12, mono=True)
        self._prompt.insert("1.0", self.WIDGET_DEMO_DATA["prompt"])
        self._negative.insert("1.0", self.WIDGET_DEMO_DATA["negative_prompt"])

        grid = tk.Frame(left, bg=BG)
        grid.pack(fill=tk.X, pady=(6, 0))
        self._preset_combo = self._labeled_combo(grid, "Preset", self._preset_var, tuple(IMAGE_PRESETS), 0, 0, width=24)
        self._preset_combo.bind("<<ComboboxSelected>>", self._on_preset_change)
        self._checkpoint_combo = self._labeled_combo(grid, "Checkpoint", self._checkpoint_var, (self._checkpoint_var.get(),), 0, 2, width=34)
        tk.Label(left, textvariable=self._preset_hint_var, bg=BG, fg=FG2, font=("Helvetica", 9), wraplength=520, justify=tk.LEFT).pack(anchor=tk.W, pady=(6, 0))
        self._labeled_entry(grid, "Width", self._width_var, 1, 0, width=10)
        self._labeled_entry(grid, "Height", self._height_var, 1, 2, width=10)
        self._labeled_entry(grid, "Steps", self._steps_var, 2, 0, width=10)
        self._labeled_entry(grid, "CFG", self._cfg_var, 2, 2, width=10)
        self._labeled_entry(grid, "Seed", self._seed_var, 3, 0, width=18)
        self._sampler_combo = self._labeled_combo(grid, "Sampler", self._sampler_var, (self._sampler_var.get(),), 3, 2, width=22)
        self._scheduler_combo = self._labeled_combo(grid, "Scheduler", self._scheduler_var, (self._scheduler_var.get(),), 4, 0, width=18)

        btns = tk.Frame(left, bg=BG)
        btns.pack(fill=tk.X, pady=(8, 0))
        tk.Button(btns, text="Use Demo Prompt", command=self._load_demo, bg=BG3, fg=FG, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btns, text="Clear Workflow Override", command=lambda: self._workflow.delete("1.0", tk.END), bg=BG3, fg=FG, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT)
        tk.Button(btns, text="Refresh Models", command=self._refresh_status, bg=BG3, fg=FG, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=(6, 0))

        preview_hdr = tk.Frame(right, bg=BG)
        preview_hdr.pack(fill=tk.X)
        tk.Label(preview_hdr, text="Latest Image", bg=BG, fg=FG, font=("Helvetica", 10, "bold")).pack(side=tk.LEFT)
        tk.Label(preview_hdr, textvariable=self._image_meta_var, bg=BG, fg=FG2, font=("Helvetica", 8)).pack(side=tk.RIGHT)

        self._preview = tk.Label(right, bg=BG2, fg=FG2, text="Queue a prompt to render an image.", relief=tk.FLAT)
        self._preview.pack(fill=tk.BOTH, expand=True, pady=(6, 6))

        tk.Label(right, text="Log", bg=BG, fg=FG, font=("Helvetica", 10, "bold")).pack(anchor=tk.W)
        self._log = tk.Text(right, bg=BG2, fg=FG, font=MONO, relief=tk.FLAT, height=12, wrap=tk.WORD)
        self._log.pack(fill=tk.BOTH, expand=True)
        self._log.config(state=tk.DISABLED)
        self._bind_mousewheel(canvas, content)

    def _bind_mousewheel(self, canvas: tk.Canvas, root: tk.Widget):
        def _on_mousewheel(event):
            try:
                widget_path = str(getattr(event, "widget", ""))
                root_path = str(root)
                if widget_path != root_path and not widget_path.startswith(f"{root_path}."):
                    return
                if not canvas.winfo_exists():
                    return
                delta = event.delta
                if delta == 0 and getattr(event, "num", None) == 4:
                    delta = 120
                elif delta == 0 and getattr(event, "num", None) == 5:
                    delta = -120
                if delta:
                    canvas.yview_scroll(int(-delta / 120), "units")
            except tk.TclError:
                return

        self._bind_mousewheel_recursive(root, _on_mousewheel)

    def _bind_mousewheel_recursive(self, widget: tk.Widget, callback):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, callback, add="+")
        for child in widget.winfo_children():
            self._bind_mousewheel_recursive(child, callback)

    def _labeled_text(self, parent, label: str, height: int, mono: bool = False):
        tk.Label(parent, text=label, bg=BG, fg=FG2, font=FONT).pack(anchor=tk.W, pady=(0, 2))
        text = tk.Text(
            parent,
            bg=BG2,
            fg=FG,
            insertbackground=FG,
            height=height,
            wrap=tk.WORD,
            relief=tk.FLAT,
            font=MONO if mono else FONT,
        )
        text.pack(fill=tk.X, pady=(0, 8))
        return text

    def _labeled_entry(self, parent, label: str, variable: tk.StringVar, row: int, column: int, width: int = 18):
        tk.Label(parent, text=label, bg=BG, fg=FG2, font=FONT).grid(row=row, column=column, sticky="w", pady=2)
        entry = tk.Entry(parent, textvariable=variable, bg=BG2, fg=FG, insertbackground=FG, relief=tk.FLAT, width=width)
        entry.grid(row=row, column=column + 1, sticky="w", pady=2, padx=(6, 18))
        return entry

    def _labeled_combo(self, parent, label: str, variable: tk.StringVar, values: tuple[str, ...], row: int, column: int, width: int = 18):
        tk.Label(parent, text=label, bg=BG, fg=FG2, font=FONT).grid(row=row, column=column, sticky="w", pady=2)
        combo = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=width)
        combo.grid(row=row, column=column + 1, sticky="w", pady=2, padx=(6, 18))
        return combo

    def _load_demo(self):
        preset = IMAGE_PRESETS.get(self._preset_var.get(), IMAGE_PRESETS["PlatformGen Launcher Icon"])
        self._prompt.delete("1.0", tk.END)
        self._prompt.insert("1.0", preset.get("demo_prompt", self.WIDGET_DEMO_DATA["prompt"]))
        self._negative.delete("1.0", tk.END)
        self._negative.insert("1.0", preset.get("negative_prompt", self.WIDGET_DEMO_DATA["negative_prompt"]))
        self._checkpoint_var.set(self._preferred_checkpoint())
        self._apply_preset_defaults(preset, update_prompt=False)

    def _on_preset_change(self, _event=None):
        preset = IMAGE_PRESETS.get(self._preset_var.get())
        if preset:
            self._apply_preset_defaults(preset, update_prompt=True)

    def _apply_preset_defaults(self, preset: dict, *, update_prompt: bool):
        self._preset_hint_var.set(preset.get("hint", ""))
        self._width_var.set(preset.get("width", self._width_var.get()))
        self._height_var.set(preset.get("height", self._height_var.get()))
        self._steps_var.set(preset.get("steps", self._steps_var.get()))
        self._cfg_var.set(preset.get("cfg", self._cfg_var.get()))
        self._sampler_var.set(self._pick_valid_option(self._samplers, preset.get("sampler", DEFAULT_SAMPLER)))
        self._scheduler_var.set(self._pick_valid_option(self._schedulers, preset.get("scheduler", DEFAULT_SCHEDULER)))
        if update_prompt:
            self._prompt.delete("1.0", tk.END)
            self._prompt.insert("1.0", preset.get("demo_prompt", self.WIDGET_DEMO_DATA["prompt"]))
            self._negative.delete("1.0", tk.END)
            self._negative.insert("1.0", preset.get("negative_prompt", self.WIDGET_DEMO_DATA["negative_prompt"]))

    def _pick_valid_option(self, options: list[str], desired: str) -> str:
        if desired in options:
            return desired
        return options[0] if options else desired

    def _preferred_checkpoint(self) -> str:
        current = self._checkpoint_var.get().strip()
        if current and current in self._checkpoints:
            return current
        default = os.environ.get("COMFYUI_CHECKPOINT", self.WIDGET_DEMO_DATA["checkpoint"])
        if default in self._checkpoints:
            return default
        return self._checkpoints[0] if self._checkpoints else default

    def _normalize_dimension(self, value: str, fallback: int) -> int:
        raw = int(value or str(fallback))
        return max(MIN_IMAGE_DIMENSION, ((raw + 63) // 64) * 64)

    def _normalized_dimensions(self) -> tuple[int, int]:
        width = self._normalize_dimension(self._width_var.get(), 1024)
        height = self._normalize_dimension(self._height_var.get(), 1024)
        return width, height

    def _append_log(self, text: str):
        self._log.config(state=tk.NORMAL)
        self._log.insert(tk.END, text.rstrip() + "\n")
        self._log.see(tk.END)
        self._log.config(state=tk.DISABLED)

    def _set_status(self, text: str, color: str):
        self._status_var.set(text)
        self._preview.config(highlightthickness=1, highlightbackground=color)

    def _request(self, method: str, path: str, *, json_body=None, timeout=20, stream=False):
        url = f"{self._base_url().rstrip('/')}{path}"
        return requests.request(method, url, json=json_body, timeout=timeout, stream=stream)

    def _base_url(self) -> str:
        return self._base_var.get().strip().rstrip("/")

    def _refresh_status(self):
        base_url = self._base_url()

        def _work():
            try:
                resp = requests.get(f"{base_url}/system_stats", timeout=5)
                resp.raise_for_status()
                self._ui(self._set_status, "online", GREEN)
                devices = resp.json().get("devices", [])
                if devices:
                    names = ", ".join(device.get("name", "device") for device in devices[:2])
                    self._ui(self._append_log, f"[ok] ComfyUI online: {names}")
                else:
                    self._ui(self._append_log, "[ok] ComfyUI online")
                self._refresh_runtime_metadata(base_url)
            except Exception as exc:
                self._ui(self._set_status, "offline", RED)
                self._ui(self._append_log, f"[err] ComfyUI unavailable: {exc}")

        threading.Thread(target=_work, daemon=True).start()

    def _refresh_runtime_metadata(self, base_url: str):
        try:
            checkpoint_resp = requests.get(f"{base_url}/object_info/CheckpointLoaderSimple", timeout=10)
            checkpoint_resp.raise_for_status()
            checkpoint_data = checkpoint_resp.json().get("CheckpointLoaderSimple", {})
            checkpoints = checkpoint_data.get("input", {}).get("required", {}).get("ckpt_name", [[]])[0]
        except Exception as exc:
            self._ui(self._append_log, f"[warn] Could not load checkpoints: {exc}")
            checkpoints = []

        try:
            sampler_resp = requests.get(f"{base_url}/object_info/KSampler", timeout=10)
            sampler_resp.raise_for_status()
            sampler_data = sampler_resp.json().get("KSampler", {}).get("input", {}).get("required", {})
            samplers = sampler_data.get("sampler_name", [[]])[0]
            schedulers = sampler_data.get("scheduler", [[]])[0]
        except Exception as exc:
            self._ui(self._append_log, f"[warn] Could not load samplers: {exc}")
            samplers = []
            schedulers = []

        self._ui(self._apply_runtime_metadata, list(checkpoints), list(samplers), list(schedulers))

    def _apply_runtime_metadata(self, checkpoints: list[str], samplers: list[str], schedulers: list[str]):
        if checkpoints:
            self._checkpoints = checkpoints
            self._checkpoint_combo["values"] = checkpoints
            self._checkpoint_var.set(self._preferred_checkpoint())
        if samplers:
            self._samplers = samplers
            self._sampler_combo["values"] = samplers
            self._sampler_var.set(self._pick_valid_option(samplers, self._sampler_var.get() or DEFAULT_SAMPLER))
        if schedulers:
            self._schedulers = schedulers
            self._scheduler_combo["values"] = schedulers
            self._scheduler_var.set(self._pick_valid_option(schedulers, self._scheduler_var.get() or DEFAULT_SCHEDULER))
        preset = IMAGE_PRESETS.get(self._preset_var.get())
        if preset:
            self._apply_preset_defaults(preset, update_prompt=False)

    def _queue_generation(self):
        if self._busy:
            return
        prompt = self._prompt.get("1.0", tk.END).strip()
        if not prompt:
            self._append_log("[err] Prompt is required.")
            return
        requested_width = self._width_var.get().strip() or "1024"
        requested_height = self._height_var.get().strip() or "1024"
        try:
            request_state = self._build_request_state()
        except Exception as exc:
            self._append_log(f"[err] Invalid ComfyUI request: {exc}")
            self._set_status("invalid", RED)
            return
        normalized_width = request_state["width"]
        normalized_height = request_state["height"]
        if (requested_width, requested_height) != (str(normalized_width), str(normalized_height)):
            self._append_log(
                f"[warn] Adjusted size from {requested_width}x{requested_height} to "
                f"{normalized_width}x{normalized_height}; SD1.5 needs larger dimensions."
            )
        self._busy = True
        self._set_status("queueing", YELLOW)
        self._append_log(f"[run] Queueing image for prompt: {prompt[:120]}")
        threading.Thread(target=self._generate, args=(request_state,), daemon=True).start()

    def _generate(self, request_state: dict):
        try:
            resp = requests.post(
                f"{request_state['base_url']}/prompt",
                json=request_state["payload"],
                timeout=30,
            )
            resp.raise_for_status()
            body = resp.json()
            prompt_id = body.get("prompt_id")
            if not prompt_id:
                raise ValueError(f"ComfyUI did not return prompt_id: {body}")
            self._ui(self._append_log, f"[ok] Prompt queued: {prompt_id}")
            self._ui(self._set_status, "rendering", YELLOW)
            self._poll_history(prompt_id, request_state["base_url"])
        except Exception as exc:
            self._ui(self._append_log, f"[err] Queue failed: {exc}")
            self._ui(self._set_status, "offline", RED)
            self._busy = False

    def _build_request_state(self) -> dict:
        width, height = self._normalized_dimensions()
        return {
            "base_url": self._base_url(),
            "payload": self._build_payload(),
            "width": width,
            "height": height,
        }

    def _build_payload(self) -> dict:
        override = self._workflow.get("1.0", tk.END).strip()
        if override:
            templated = self._apply_workflow_tokens(override)
            parsed = json.loads(templated)
            if "prompt" in parsed:
                return parsed
            return {"prompt": parsed, "client_id": "platformgen"}

        width, height = self._normalized_dimensions()
        steps = max(1, int(self._steps_var.get() or "24"))
        cfg = float(self._cfg_var.get() or "7.0")
        seed = int(self._seed_var.get() or "-1")
        sampler_name = self._sampler_var.get().strip() or DEFAULT_SAMPLER
        scheduler_name = self._scheduler_var.get().strip() or DEFAULT_SCHEDULER
        checkpoint_name = self._checkpoint_var.get().strip() or self.WIDGET_DEMO_DATA["checkpoint"]
        prompt_text = self._compose_prompt()
        negative_prompt = self._compose_negative_prompt()

        graph = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint_name}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt_text, "clip": ["1", 1]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative_prompt, "clip": ["1", 1]}},
            "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed if seed >= 0 else int(time.time() * 1000) % 2147483647,
                    "steps": steps,
                    "cfg": cfg,
                    "sampler_name": sampler_name,
                    "scheduler": scheduler_name,
                    "denoise": 1,
                    "model": ["1", 0],
                    "positive": ["2", 0],
                    "negative": ["3", 0],
                    "latent_image": ["4", 0],
                },
            },
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {"class_type": "SaveImage", "inputs": {"filename_prefix": "platformgen", "images": ["6", 0]}},
        }
        return {"prompt": graph, "client_id": "platformgen"}

    def _compose_prompt(self) -> str:
        prompt = self._prompt.get("1.0", tk.END).strip()
        preset = IMAGE_PRESETS.get(self._preset_var.get())
        prefix = (preset or {}).get("prompt_prefix", "").strip()
        suffix = (preset or {}).get("prompt_suffix", "").strip()
        parts = [part for part in (prefix, prompt, suffix) if part]
        return ", ".join(parts)

    def _compose_negative_prompt(self) -> str:
        prompt = self._negative.get("1.0", tk.END).strip()
        preset = IMAGE_PRESETS.get(self._preset_var.get())
        prefix = (preset or {}).get("negative_prompt", "").strip()
        if prefix and prompt:
            return f"{prefix}, {prompt}"
        return prompt or prefix

    def _apply_workflow_tokens(self, text: str) -> str:
        replacements = {
            "{{prompt}}": json.dumps(self._compose_prompt()),
            "{{negative_prompt}}": json.dumps(self._compose_negative_prompt()),
            "{{checkpoint}}": json.dumps(self._checkpoint_var.get().strip()),
            "{{width}}": str(self._normalized_dimensions()[0]),
            "{{height}}": str(self._normalized_dimensions()[1]),
            "{{steps}}": str(int(self._steps_var.get() or "24")),
            "{{cfg}}": str(float(self._cfg_var.get() or "7.0")),
            "{{seed}}": str(int(self._seed_var.get() or "-1")),
            "{{sampler}}": json.dumps(self._sampler_var.get().strip() or DEFAULT_SAMPLER),
            "{{scheduler}}": json.dumps(self._scheduler_var.get().strip() or DEFAULT_SCHEDULER),
        }
        rendered = text
        for token, value in replacements.items():
            rendered = rendered.replace(token, value)
        return rendered

    def _poll_history(self, prompt_id: str, base_url: str):
        deadline = time.time() + 180
        while time.time() < deadline:
            try:
                resp = requests.get(f"{base_url}/history/{prompt_id}", timeout=15)
                resp.raise_for_status()
                history = resp.json()
                item = history.get(prompt_id) if isinstance(history, dict) else None
                if not item and isinstance(history, dict) and len(history) == 1:
                    item = next(iter(history.values()))
                images = self._extract_images(item or {})
                if images:
                    self._ui(self._append_log, f"[ok] Render complete: {len(images)} image(s)")
                    self._show_image(images[0], base_url)
                    self._busy = False
                    self._ui(self._set_status, "online", GREEN)
                    return
            except Exception as exc:
                self._ui(self._append_log, f"[warn] Polling retry: {exc}")
            time.sleep(2)

        self._ui(self._append_log, f"[err] Timed out waiting for prompt {prompt_id}")
        self._ui(self._set_status, "timeout", RED)
        self._busy = False

    def _extract_images(self, item: dict) -> list[dict]:
        outputs = item.get("outputs", {})
        images = []
        if isinstance(outputs, dict):
            for node_output in outputs.values():
                for image_meta in node_output.get("images", []):
                    if isinstance(image_meta, dict) and image_meta.get("filename"):
                        images.append(image_meta)
        return images

    def _show_image(self, image_meta: dict, base_url: str):
        try:
            query = urlencode(
                {
                    "filename": image_meta.get("filename", ""),
                    "subfolder": image_meta.get("subfolder", ""),
                    "type": image_meta.get("type", "output"),
                }
            )
            resp = requests.get(f"{base_url}/view?{query}", timeout=60)
            resp.raise_for_status()
            if not PIL_AVAILABLE:
                self._ui(self._image_meta_var.set, image_meta.get("filename", "image ready"))
                self._ui(self._preview.config, {"text": "Image generated. Install Pillow to preview it here."})
                return
            image = Image.open(io.BytesIO(resp.content))
            image.thumbnail((640, 640))
            self._ui(self._set_preview_image, image.copy(), image_meta)
        except Exception as exc:
            self._ui(self._append_log, f"[err] Could not fetch preview: {exc}")

    def _set_preview_image(self, image, image_meta: dict):
        photo = ImageTk.PhotoImage(image)
        self._photo = photo
        self._preview.config(image=photo, text="")
        self._image_meta_var.set(image_meta.get("filename", "generated image"))

    def _ui(self, func, *args):
        self._ui_queue.append((func, args))

    def _drain_ui(self):
        try:
            while self._ui_queue:
                func, args = self._ui_queue.pop(0)
                try:
                    func(*args)
                except TypeError:
                    if len(args) == 1 and isinstance(args[0], dict):
                        func(**args[0])
                    else:
                        raise
        finally:
            try:
                self.after(80, self._drain_ui)
            except tk.TclError:
                pass


def create_widget(parent, context_builder_callback=None):
    return ComfyUIWidget(parent)
