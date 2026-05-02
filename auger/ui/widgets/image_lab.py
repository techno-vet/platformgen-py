"""Image Lab Widget — PIL image preview and AI-driven iteration."""

import tkinter as tk
from tkinter import ttk, filedialog
import threading
import json
import re
import os
import urllib.request
import urllib.error
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

SEED_CODE = '''def make_image(size=256, color="#2ea043"):
    """SRE health gauge — dark background, glowing ring, needle, tick marks."""
    import math
    from PIL import Image, ImageDraw, ImageFilter
    R = size * 2
    img = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def px(v): return max(1, int(v * R / 512.0))

    # Background — layered dark concentric rounded rects
    for i in range(40, 0, -1):
        t = i / 40.0
        c = int(10 + 22 * (1 - t))
        pad = px(8 + i * 6)
        d.rounded_rectangle([pad, pad, R - pad, R - pad],
                             radius=px(40), fill=(c, c + 4, c + 14))

    cx = cy = R // 2
    outer_r = R // 2 - px(36)
    inner_r = outer_r - px(28)

    # Outer status ring
    margin = px(36)
    d.ellipse([margin, margin, R - margin, R - margin],
              outline=color, width=px(20))

    # 12 tick marks
    for i in range(12):
        angle = math.radians(i * 30 - 90)
        is_major = (i % 3 == 0)
        ir = inner_r if is_major else inner_r + px(14)
        x1 = int(cx + outer_r * math.cos(angle))
        y1 = int(cy + outer_r * math.sin(angle))
        x2 = int(cx + ir * math.cos(angle))
        y2 = int(cy + ir * math.sin(angle))
        d.line([(x1, y1), (x2, y2)],
               fill=(color if is_major else "#4a7a5a"),
               width=(px(10) if is_major else px(6)))

    # Sweep arc — 75% of 270 deg starting at -135
    arc_r = outer_r - px(40)
    bb = [cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r]
    d.arc(bb, start=-135, end=-135 + 270 * 0.75, fill=color, width=px(16))

    # Needle
    needle_angle = math.radians(-135 + 270 * 0.75)
    nl = arc_r - px(16)
    nx = int(cx + nl * math.cos(needle_angle))
    ny = int(cy + nl * math.sin(needle_angle))
    d.line([(cx, cy), (nx, ny)], fill="#ffffff", width=px(8))

    # Center hub
    dot_r = px(36)
    d.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=color)
    d.ellipse([cx - px(16), cy - px(16), cx + px(16), cy + px(16)], fill="#ffffff")

    # Labels
    try:
        from PIL import ImageFont
        fnt_big   = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", px(40))
        fnt_small = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", px(28))
        d.text((cx, cy + px(100)), "75%",    font=fnt_big,   fill="#ffffff", anchor="mm")
        d.text((cx, cy + px(136)), "HEALTH", font=fnt_small, fill="#888888", anchor="mm")
    except Exception:
        pass

    # Glow overlay
    glow = Image.new("RGBA", (R, R), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([margin + px(4), margin + px(4), R - margin - px(4), R - margin - px(4)],
               outline=color, width=px(12))
    glow = glow.filter(ImageFilter.GaussianBlur(px(16)))
    img = Image.alpha_composite(img, glow)

    return img.resize((size, size), Image.LANCZOS)
'''

STANDARD_ICON_CODE = '''def make_image(size=256, color="#2ea043"):
    """Auger standard app icon — A letterform with auger tip on dark tile."""
    from PIL import Image, ImageDraw
    RENDER = size * 2
    img = Image.new("RGBA", (RENDER, RENDER), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sc = RENDER / 64.0

    def p(x, y): return (int(x * sc), int(y * sc))
    def s(v): return max(1, int(v * sc))

    d.rounded_rectangle([s(2), s(2), RENDER - s(2), RENDER - s(2)],
                        radius=s(10), fill="#1a2332")

    cx = RENDER // 2
    apex = p(32, 10)
    bl = p(10, 53)
    br = p(54, 53)
    stroke = s(7)

    d.line([apex, bl], fill=color, width=stroke)
    d.line([apex, br], fill=color, width=stroke)

    t = 0.50
    lx = int(apex[0] + (bl[0] - apex[0]) * t)
    ly = int(apex[1] + (bl[1] - apex[1]) * t)
    rx = int(apex[0] + (br[0] - apex[0]) * t)
    ry = int(apex[1] + (br[1] - apex[1]) * t)
    d.line([(lx, ly), (rx, ry)], fill=color, width=s(5))

    base_y = p(32, 53)[1]
    shft_y = p(32, 58)[1]
    tip_y = RENDER - s(3)
    d.line([(cx, base_y), (cx, shft_y)], fill=color, width=s(5))
    d.polygon([
        (cx - s(5), shft_y),
        (cx + s(5), shft_y),
        (cx, tip_y),
    ], fill="#ffffff")

    return img.resize((size, size), Image.LANCZOS)
'''



def make_icon(size=18, color="#2ea043"):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0,0,0,0))
    d = ImageDraw.Draw(img)
    m = max(1, size//8); cx = size//2
    d.ellipse([m, m, size-m, size-m], outline=color, width=m)
    d.ellipse([cx-m, cx-m, cx+m, cx+m], fill=color)
    d.line([(size-2*m, m), (m, size-m)], fill=color, width=m)
    return img

class ImageLabWidget(tk.Frame):
    WIDGET_TITLE = "Image Lab"
    WIDGET_ICON_FUNC = staticmethod(make_icon)

    def __init__(self, parent):
        super().__init__(parent, bg='#1e1e1e')
        self._code          = SEED_CODE  # module-level; updated on hot-reload
        self._current_image = None
        self._preview_size  = 256
        self._preview_color = "#2ea043"
        self._photo         = None
        self._show_code     = False

        if not PIL_AVAILABLE:
            tk.Label(self, text="PIL/Pillow not installed.",
                     fg='#f44747', bg='#1e1e1e', font=('Segoe UI', 12)
                     ).pack(expand=True)
            return

        self._build_ui()
        self.after(100, self._render)

    def _build_ui(self):
        hdr = tk.Frame(self, bg='#007acc', height=30)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)
        tk.Label(hdr, text="  Image Lab", font=('Segoe UI', 11, 'bold'),
                 fg='white', bg='#007acc').pack(side=tk.LEFT, padx=10)
        for lbl, cmd in [("Save", self._save), ("< > Code", self._toggle_code), ("Reset", self._reset)]:
            tk.Button(hdr, text=lbl, command=cmd, bg='#007acc', fg='white',
                      font=('Segoe UI', 9), relief=tk.FLAT, cursor='hand2', padx=8
                      ).pack(side=tk.RIGHT, padx=2)

        cf = tk.Frame(self, bg='#252526')
        cf.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self._canvas = tk.Canvas(cf, bg='#252526', highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind('<Configure>', lambda e: self.after(50, self._redisplay))

        self._code_frame = tk.Frame(self, bg='#0d1117')
        self._code_text  = tk.Text(self._code_frame, bg='#0d1117', fg='#c9d1d9',
                                   font=('Consolas', 9), height=10, wrap=tk.NONE,
                                   insertbackground='white', relief=tk.FLAT)
        sb = ttk.Scrollbar(self._code_frame, command=self._code_text.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._code_text.config(yscrollcommand=sb.set)
        self._code_text.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
        tk.Button(self._code_frame, text="Run Code", command=self._run_from_editor,
                  bg='#238636', fg='white', font=('Segoe UI', 9),
                  relief=tk.FLAT, cursor='hand2', padx=10
                  ).pack(side=tk.RIGHT, pady=3, padx=5)

        ctrl = tk.Frame(self, bg='#252526')
        ctrl.pack(fill=tk.X, padx=5, pady=(0, 3))
        tk.Label(ctrl, text="Size:", bg='#252526', fg='#888', font=('Segoe UI', 9)).pack(side=tk.LEFT)
        for sz in [16, 32, 64, 128, 256]:
            tk.Button(ctrl, text=str(sz), command=lambda s=sz: self._set_size(s),
                      bg='#3c3c3c', fg='#e0e0e0', font=('Segoe UI', 9),
                      relief=tk.FLAT, cursor='hand2', padx=6, pady=1
                      ).pack(side=tk.LEFT, padx=1)
        tk.Label(ctrl, text="  Preset:", bg='#252526', fg='#888', font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(8,0))
        for lbl, cmd in [("Health", self._load_health_preset), ("Standard Icon", self._load_standard_icon_preset)]:
            tk.Button(ctrl, text=lbl, command=cmd,
                      bg='#3c3c3c', fg='#e0e0e0', font=('Segoe UI', 9),
                      relief=tk.FLAT, cursor='hand2', padx=6, pady=1
                      ).pack(side=tk.LEFT, padx=1)
        tk.Label(ctrl, text="  Color:", bg='#252526', fg='#888', font=('Segoe UI', 9)).pack(side=tk.LEFT, padx=(8,0))
        for clr, name in [("#2ea043","green"),("#d29922","yellow"),("#da3633","red"),("#007acc","blue"),("#ffffff","white")]:
            tk.Button(ctrl, text=name, command=lambda c=clr: self._set_color(c),
                      bg=clr if clr != '#ffffff' else '#555', fg='white',
                      font=('Segoe UI', 8), relief=tk.FLAT, cursor='hand2', padx=5, pady=1
                      ).pack(side=tk.LEFT, padx=1)

        inf = tk.Frame(self, bg='#252526')
        inf.pack(fill=tk.X, padx=5, pady=(0, 5))
        self._prompt = tk.Text(inf, height=2, bg='#2d2d2d', fg='#888',
                               insertbackground='#e0e0e0', font=('Consolas', 10),
                               wrap=tk.WORD, relief=tk.FLAT)
        self._prompt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,5))
        self._prompt.insert('1.0', 'Describe changes to the image...')
        self._prompt.bind('<FocusIn>',  self._clear_hint)
        self._prompt.bind('<FocusOut>', self._restore_hint)
        self._prompt.bind('<Return>',   self._on_enter)

        btns = tk.Frame(inf, bg='#252526')
        btns.pack(side=tk.RIGHT)
        self._apply_btn = tk.Button(btns, text="Apply  ->", command=self._apply,
                                    bg='#007acc', fg='white', font=('Segoe UI', 10),
                                    relief=tk.FLAT, cursor='hand2', padx=12, pady=4)
        self._apply_btn.pack(pady=(0, 3))

        self._status = tk.Label(self, text="Ready — describe changes and press Apply",
                                bg='#1e1e1e', fg='#555', font=('Segoe UI', 9), anchor='w')
        self._status.pack(fill=tk.X, padx=8, pady=(0, 3))

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render(self):
        try:
            img = self._exec_code(self._code, self._preview_size, self._preview_color)
            self._current_image = img
            self._display_image(img)
            self._set_status(f"Rendered {img.size[0]}x{img.size[1]}px")
        except Exception as e:
            self._set_status(f"Render error: {e}", error=True)

    def _redisplay(self):
        if self._current_image:
            self._display_image(self._current_image)

    def _display_image(self, img):
        cw = max(self._canvas.winfo_width(),  10)
        ch = max(self._canvas.winfo_height(), 10)
        pad = 24
        mw, mh = cw - pad * 2, ch - pad * 2
        if mw < 4 or mh < 4:
            return
        display = img.copy()
        display.thumbnail((mw, mh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(display)
        self._canvas.delete("all")
        for row in range(0, ch, 16):
            for col in range(0, cw, 16):
                fill = '#333' if (row//16 + col//16) % 2 == 0 else '#2a2a2a'
                self._canvas.create_rectangle(col, row, col+16, row+16, fill=fill, outline='')
        self._canvas.create_image(cw//2, ch//2, image=self._photo, anchor='center')
        self._canvas.create_text(cw-4, ch-4, text=f"{img.size[0]}x{img.size[1]}",
                                 fill='#555', font=('Consolas', 8), anchor='se')

    def _exec_code(self, code, size, color):
        ns = {}
        preamble = "from PIL import Image, ImageDraw, ImageFont, ImageFilter\nimport math, random\n"
        exec(preamble + code, ns)
        fn = ns.get("make_image")
        if fn is None:
            raise ValueError("Code must define make_image(size, color)")
        result = fn(size, color)
        if not hasattr(result, 'tobytes'):
            raise ValueError("make_image() must return a PIL Image")
        return result

    # ── AI modification ───────────────────────────────────────────────────────

    def _apply(self):
        raw = self._prompt.get('1.0', 'end-1c').strip()
        if not raw or raw == 'Describe changes to the image...':
            return

        self._apply_btn.config(state=tk.DISABLED, text="...")
        self._set_status("Asking Auger...")

        prompt = (
            f"You are a PIL/Pillow Python programmer.\n"
            f"Modify the image code as requested.\n\n"
            f"Request: {raw}\n\n"
            f"Current code:\n```python\n{self._code}\n```\n\n"
            f"Return ONLY a Python function named `make_image(size=256, color=\"#2ea043\")` "
            f"that creates and returns a PIL RGBA Image. "
            f"Imports inside the function are fine. "
            f"Only PIL/Pillow, math, random. No explanation — just the code in a ```python block."
        )

        self._stream_ask(
            prompt,
            on_chunk=lambda c: None,
            on_done=lambda full: self.after(0, lambda: self._handle_response(full, raw)),
            on_error=lambda e: (
                self.after(0, lambda: self._set_status(f"Error: {e}", error=True)),
                self.after(0, lambda: self._apply_btn.config(state=tk.NORMAL, text="Apply  ->"))
            )
        )

    def _handle_response(self, full_text, original_prompt):
        self._apply_btn.config(state=tk.NORMAL, text="Apply  ->")
        code = self._extract_code(full_text)
        if not code:
            self._set_status(f"No code found in response ({len(full_text)} chars)", error=True)
            return
        try:
            img = self._exec_code(code, self._preview_size, self._preview_color)
            self._code = code
            self._current_image = img
            self._display_image(img)
            self._set_status(f"Applied: {original_prompt[:70]}")
            if self._show_code:
                self._update_code_editor()
        except Exception as e:
            self._set_status(f"Code error: {e}", error=True)

    def _extract_code(self, text):
        # Fenced block
        m = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()
        # No fences — find def make_image and grab body by indentation
        if "def make_image" in text:
            idx = text.find("def make_image")
            lines = text[idx:].splitlines()
            out, in_body = [], False
            for i, ln in enumerate(lines):
                if not in_body:
                    out.append(ln)
                    if ln.strip().startswith("def make_image"):
                        in_body = True
                    continue
                if ln.strip() == "":
                    j = i + 1
                    while j < len(lines) and not lines[j].strip():
                        j += 1
                    if j < len(lines) and lines[j] and lines[j][0] not in (" ", "\t"):
                        break
                out.append(ln)
            return "\n".join(out).strip()
        return ""

    def _stream_ask(self, prompt, on_chunk, on_done, on_error):
        """Send prompt through the host daemon Ask Auger path."""

        def _run():
            try:
                status_req = urllib.request.Request(
                    "http://localhost:7437/session_status",
                    method="GET",
                )
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(status_req, timeout=5) as status_resp:
                    status = json.loads(status_resp.read().decode("utf-8", errors="replace"))
                if status.get("locked"):
                    locked_secs = int(status.get("locked_secs") or 0)
                    if locked_secs >= 120:
                        on_error(
                            "Ask Auger appears stuck from an older request "
                            f"({locked_secs}s). Open the main Ask Auger panel and use Unlock before retrying."
                        )
                    else:
                        on_error(
                            "Another Ask Auger request is still running. "
                            "Wait for it to finish, then try Apply again."
                        )
                    return

                req = urllib.request.Request(
                    "http://localhost:7437/ask",
                    data=json.dumps({"prompt": prompt, "source": "image_lab"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                response_lines = []
                with opener.open(req, timeout=300) as resp:
                    for raw_line in resp:
                        line_str = raw_line.decode("utf-8", errors="replace").strip()
                        if not line_str:
                            continue
                        entry = json.loads(line_str)
                        msg_type = entry.get("type", "")
                        msg = entry.get("message", "")
                        if msg_type == "output" and msg:
                            response_lines.append(msg)
                            on_chunk(msg + "\n")
                        elif msg_type == "done":
                            on_done("\n".join(response_lines))
                            return
                        elif msg_type == "error":
                            on_error(msg or "Ask Auger request failed")
                            return
                on_done("\n".join(response_lines))
            except urllib.error.URLError:
                on_error("Ask Auger daemon is not reachable. Start/restart the host daemon and try again.")
            except Exception as e:
                on_error(str(e))

        threading.Thread(target=_run, daemon=True).start()

    # ── Controls ──────────────────────────────────────────────────────────────

    def _set_size(self, size):
        self._preview_size = size
        self._render()

    def _set_color(self, color):
        self._preview_color = color
        self._render()

    def _toggle_code(self):
        self._show_code = not self._show_code
        if self._show_code:
            self._update_code_editor()
            self._code_frame.pack(fill=tk.X, padx=5, pady=(0, 3), before=self._status)
        else:
            self._code_frame.pack_forget()

    def _update_code_editor(self):
        self._code_text.delete('1.0', tk.END)
        self._code_text.insert('1.0', self._code)

    def _run_from_editor(self):
        code = self._code_text.get('1.0', 'end-1c').strip()
        try:
            img = self._exec_code(code, self._preview_size, self._preview_color)
            self._code = code
            self._current_image = img
            self._display_image(img)
            self._set_status("Code applied")
        except Exception as e:
            self._set_status(f"Error: {e}", error=True)

    def _save(self):
        if not self._current_image:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("All files", "*.*")],
            initialfile="auger_icon.png")
        if path:
            self._current_image.save(path)
            self._set_status(f"Saved: {path}")

    def _reset(self):
        import sys as _sys
        _mod = _sys.modules.get(__name__)
        self._code = getattr(_mod, "SEED_CODE", SEED_CODE)
        self._render()
        if self._show_code:
            self._update_code_editor()
        self._set_status("Reset to seed image")

    def _load_health_preset(self):
        self._code = SEED_CODE
        self._render()
        if self._show_code:
            self._update_code_editor()
        self._set_status("Loaded health gauge preset")

    def _load_standard_icon_preset(self):
        self._code = STANDARD_ICON_CODE
        self._render()
        if self._show_code:
            self._update_code_editor()
        self._set_status("Loaded standard app icon preset")

    def _set_status(self, msg, error=False):
        self._status.config(text=msg, fg='#f44747' if error else '#555')

    def _clear_hint(self, _event):
        if self._prompt.get('1.0', 'end-1c') == 'Describe changes to the image...':
            self._prompt.delete('1.0', tk.END)
            self._prompt.config(fg='#e0e0e0')

    def _restore_hint(self, _event):
        if not self._prompt.get('1.0', 'end-1c').strip():
            self._prompt.config(fg='#888')
            self._prompt.insert('1.0', 'Describe changes to the image...')

    def _on_enter(self, event):
        if not (event.state & 1):
            self._apply()
            return "break"
