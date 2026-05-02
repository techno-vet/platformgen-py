"""Tabbed content area with wrapping multi-row tab bar."""

import json
import tkinter as tk
from tkinter import ttk, messagebox
import re
from pathlib import Path
from auger.ui import icons as _icons

BG     = "#1e1e1e"
BG2    = "#252526"
BG3    = "#2d2d2d"
ACCENT = "#37373d"
FG     = "#cccccc"
FG2    = "#858585"
GREEN  = "#4ec9b0"
RED    = "#f44747"

_STATE_FILE = Path.home() / '.auger' / 'tab_state.json'

def _tab_icon_for_class(widget_class, size=18):
    """Return a PhotoImage for the tab, preferring WIDGET_ICON_FUNC over WIDGET_ICON_NAME.
    Returns None if neither is available or PIL is missing."""
    # Try WIDGET_ICON_FUNC first (programmatic PIL icon)
    icon_func = getattr(widget_class, 'WIDGET_ICON_FUNC', None)
    if icon_func:
        try:
            from PIL import ImageTk
            pil_img = icon_func(size=size)
            return ImageTk.PhotoImage(pil_img)
        except Exception:
            pass
    # Fall back to static icon registry
    icon_name = getattr(widget_class, 'WIDGET_ICON_NAME', None)
    if icon_name:
        try:
            return _icons.get(icon_name, size)
        except Exception:
            pass
    return None



class _WrappingTabBar(tk.Frame):
    """Tab bar that wraps buttons to new rows when width is exceeded."""

    TAB_H = 28  # nominal tab height px

    def __init__(self, parent, **kw):
        super().__init__(parent, bg=BG2, **kw)
        self._entries = []   # list of {'frame', 'btn', 'text', 'image', 'right_click_cb'}
        self._current_frame = None
        self.bind('<Configure>', lambda e: self._relayout())

    # ── Public API ────────────────────────────────────────────────────────────

    def add(self, frame, text='', image=None, select_cb=None, right_click_cb=None):
        btn = tk.Button(
            self,
            text=text, image=image,
            compound=tk.LEFT if image else tk.NONE,
            bg=BG2, fg=FG2, bd=0,
            padx=8, pady=3,
            font=('Segoe UI', 9),
            activebackground=ACCENT, activeforeground=FG,
            cursor='hand2', relief=tk.FLAT,
            anchor='w',
        )
        if select_cb:
            btn.configure(command=select_cb)
        entry = {
            'frame': frame, 'btn': btn,
            'text': text, 'image': image,
            'right_click_cb': right_click_cb,
        }
        self._entries.append(entry)
        if right_click_cb:
            btn.bind('<Button-3>', lambda e, en=entry: self._show_tab_menu(e, en))
        self._relayout()
        return btn

    def _show_tab_menu(self, event, entry):
        """Show right-click context menu for a tab."""
        menu = tk.Menu(self, tearoff=0, bg=BG2, fg=FG,
                       activebackground=ACCENT, activeforeground='white')
        text = entry['text'].strip()
        is_home = text.lower() == 'home'
        # Pop out
        if not is_home and entry.get('right_click_cb'):
            menu.add_command(label='⬡  Pop Out to Window',
                             command=lambda: entry['right_click_cb'](action='popout'))
            menu.add_separator()
        if not is_home:
            menu.add_command(label='✕  Close Tab',
                             command=lambda: entry['right_click_cb'](action='close'))
        else:
            menu.add_command(label='Home tab cannot be closed', state='disabled')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def remove(self, frame):
        entry = self._entry(frame)
        if entry:
            entry['btn'].place_forget()
            entry['btn'].destroy()
            self._entries = [e for e in self._entries if e['frame'] is not frame]
        if self._current_frame is frame:
            self._current_frame = None
        self._relayout()

    def select(self, frame):
        self._current_frame = frame
        for e in self._entries:
            active = e['frame'] is frame
            e['btn'].config(
                bg=ACCENT if active else BG2,
                fg=FG    if active else FG2,
                relief=tk.SUNKEN if active else tk.FLAT,
            )

    def update_tab(self, frame, text=None, image=None, compound=None):
        entry = self._entry(frame)
        if not entry:
            return
        if text is not None:
            entry['text'] = text
            entry['btn'].config(text=text)
        if image is not None:
            entry['image'] = image
            entry['btn'].config(image=image,
                                compound=compound if compound else tk.LEFT)
        elif compound is not None and entry['image']:
            entry['btn'].config(compound=compound)
        self._relayout()

    def get_text(self, frame):
        entry = self._entry(frame)
        return entry['text'] if entry else ''

    def index_of(self, frame):
        for i, e in enumerate(self._entries):
            if e['frame'] is frame:
                return i
        raise tk.TclError('frame not in tab bar')

    def frame_at(self, idx):
        return self._entries[idx]['frame']

    # ── Internal ──────────────────────────────────────────────────────────────

    def _entry(self, frame):
        for e in self._entries:
            if e['frame'] is frame:
                return e
        return None

    def _relayout(self):
        w = self.winfo_width()
        if w <= 1:
            self.after(30, self._relayout)
            return
        x, y, row_h = 2, 2, 0
        for e in self._entries:
            btn = e['btn']
            btn.update_idletasks()
            bw = btn.winfo_reqwidth() + 2
            bh = btn.winfo_reqheight() + 2
            if x + bw > w - 2 and x > 2:
                x = 2
                y += row_h + 2
                row_h = 0
            btn.place(x=x, y=y, height=bh)
            x += bw
            row_h = max(row_h, bh)
        total = y + row_h + 4
        self.configure(height=max(self.TAB_H, total))


# ─────────────────────────────────────────────────────────────────────────────
class ContentArea(tk.Frame):
    """Content area with wrapping multi-row tab bar."""

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self._tabs = {}        # tab_key -> {'frame': f, 'widget': w, 'cls': cls}
        self._tab_icons = {}   # tab_key -> PhotoImage (GC guard)
        self._view_menu_refresh = None   # set by app.py to rebuild View > Tabs section
        self._popouts = {}     # tab_key -> Toplevel
        self._ask_auger_cb = None  # set by app.py: fn(widget_name, traceback_str, source_path)

        # Load saved tab state for restore (None = no saved state, open all)
        self._restore_state = self.load_tab_state()

        # Wrapping tab bar at top
        self._tabbar = _WrappingTabBar(self)
        self._tabbar.pack(fill=tk.X, side=tk.TOP)

        # Separator line
        tk.Frame(self, bg='#3c3c3c', height=1).pack(fill=tk.X)

        # Content stacking area
        self._stack = tk.Frame(self, bg=BG)
        self._stack.pack(fill=tk.BOTH, expand=True)

        self._current_frame = None

        self._add_home_tab()

    # ── Notebook-compatible API ───────────────────────────────────────────────

    def add(self, frame, text='', image=None, compound=tk.LEFT):
        """Add a frame as a new tab."""
        frame.pack_forget()
        self._tabbar.add(
            frame, text=text, image=image,
            select_cb=lambda f=frame: self.select(f),
            right_click_cb=lambda f=frame, **kw: self._tab_action(f, **kw),
        )

    def _frame_exists(self, frame):
        if frame is None:
            return False
        try:
            return bool(frame.winfo_exists())
        except tk.TclError:
            return False

    def _prune_dead_tab_entries(self):
        alive = []
        for entry in self._tabbar._entries:
            frame = entry.get('frame')
            btn = entry.get('btn')
            frame_alive = self._frame_exists(frame)
            btn_alive = False
            if btn is not None:
                try:
                    btn_alive = bool(btn.winfo_exists())
                except tk.TclError:
                    btn_alive = False
            if frame_alive and btn_alive:
                alive.append(entry)
                continue
            if btn is not None and btn_alive:
                try:
                    btn.destroy()
                except tk.TclError:
                    pass
        self._tabbar._entries = alive
        if not self._frame_exists(self._current_frame):
            self._current_frame = None
        if not self._frame_exists(self._tabbar._current_frame):
            self._tabbar._current_frame = None

    def select(self, frame):
        """Bring frame to front."""
        self._prune_dead_tab_entries()
        if not self._frame_exists(frame):
            if self._tabbar._entries:
                frame = self._tabbar._entries[-1]['frame']
            else:
                self._current_frame = None
                return
        try:
            if self._frame_exists(self._current_frame) and self._current_frame is not frame:
                self._current_frame.pack_forget()
            frame.pack(fill=tk.BOTH, expand=True)
        except tk.TclError:
            return
        self._current_frame = frame
        self._tabbar.select(frame)
        self._save_tab_state()
        if self._view_menu_refresh:
            self._view_menu_refresh()

    def tab(self, frame, option=None, **kw):
        """Get/set tab options (text, image, compound)."""
        if option is not None and not kw:
            # getter
            if option == 'text':
                return self._tabbar.get_text(frame)
            return ''
        # setter
        self._tabbar.update_tab(frame, **kw)

    def index(self, what):
        """Return integer index of a frame, or raise TclError."""
        if isinstance(what, str) and what.startswith('@'):
            # Hit-test not needed with custom tab bar — return -1
            return -1
        return self._tabbar.index_of(what)

    def forget(self, tab_id):
        """Remove a tab by index."""
        try:
            frame = self._tabbar.frame_at(tab_id)
        except (IndexError, TypeError):
            return
        self._close_tab(frame)

    def after(self, ms, func=None, *args):
        return super().after(ms, func, *args)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _tab_action(self, frame, action='close'):
        if action == 'popout':
            self._popout_tab(frame)
        else:
            self._close_tab(frame)

    def _close_tab(self, frame):
        self._prune_dead_tab_entries()
        if not self._frame_exists(frame):
            return
        # Don't close Home
        text = self._tabbar.get_text(frame).strip()
        if text.lower() == 'home':
            return
        # Remove from tracking
        key = text.lower().replace(' ', '_')
        self._tabs.pop(key, None)
        self._tab_icons.pop(key, None)
        # Hide frame
        try:
            frame.pack_forget()
        except tk.TclError:
            pass
        self._tabbar.remove(frame)
        if self._current_frame is frame:
            self._current_frame = None
        try:
            frame.destroy()
        except tk.TclError:
            pass
        self._prune_dead_tab_entries()
        # Select another tab
        if self._tabbar._entries:
            self.select(self._tabbar._entries[-1]['frame'])
        self._save_tab_state()
        if self._view_menu_refresh:
            self._view_menu_refresh()

    # ── Pop-out & tab state ───────────────────────────────────────────────────

    def _popout_tab(self, frame):
        """Detach a widget tab into its own Toplevel window."""
        text = self._tabbar.get_text(frame).strip()
        key = text.lower().replace(' ', '_')
        tab_info = self._tabs.get(key)
        if not tab_info or not tab_info.get('cls'):
            messagebox.showinfo("Pop Out", "This widget cannot be popped out (no class reference).")
            return

        # Close the tab first
        self._close_tab(frame)

        # Create toplevel
        top = tk.Toplevel(self)
        top.title(f"Auger — {text}")
        top.geometry("900x650")
        top.configure(bg=BG)
        self._popouts[key] = top

        # Dock-back bar
        bar = tk.Frame(top, bg=BG2, height=28)
        bar.pack(fill=tk.X, side=tk.TOP)
        tk.Label(bar, text=f"  ⬡ {text}", bg=BG2, fg=FG,
                 font=('Segoe UI', 9)).pack(side=tk.LEFT)
        tk.Button(bar, text="⬒ Dock Back", bg=BG2, fg=FG2,
                  relief=tk.FLAT, bd=0, cursor='hand2',
                  font=('Segoe UI', 9), activebackground=ACCENT,
                  command=lambda k=key, cls=tab_info['cls'], t=top: self._dock_back(k, cls, t)
                  ).pack(side=tk.RIGHT, padx=6, pady=2)
        tk.Frame(top, bg='#3c3c3c', height=1).pack(fill=tk.X)

        # Widget inside toplevel
        try:
            container = tk.Frame(top, bg=BG)
            container.pack(fill=tk.BOTH, expand=True)
            w = tab_info['cls'](container)
            w.pack(fill=tk.BOTH, expand=True)
        except Exception as e:
            tk.Label(top, text=f"Error loading widget:\n{e}",
                     fg=RED, bg=BG).pack(expand=True)

        def on_top_close():
            self._popouts.pop(key, None)
            top.destroy()
        top.protocol("WM_DELETE_WINDOW", on_top_close)

    def _dock_back(self, key, cls, top):
        """Close pop-out window and re-open widget as a tab."""
        self._popouts.pop(key, None)
        top.destroy()
        display = key.replace('_', ' ').title()
        self.add_widget_tab(display, cls)

    # ── Tab state persistence ─────────────────────────────────────────────────

    def _save_tab_state(self):
        """Write open tab keys + active tab to ~/.auger/tab_state.json."""
        try:
            active_key = None
            if self._current_frame:
                active_text = self._tabbar.get_text(self._current_frame).strip()
                active_key = active_text.lower().replace(' ', '_')
            ordered = [e['text'].strip().lower().replace(' ', '_')
                       for e in self._tabbar._entries]
            state = {'open': ordered, 'active': active_key}
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps(state, indent=2))
        except Exception:
            pass

    def load_tab_state(self):
        """Return saved state dict or None."""
        try:
            state = json.loads(_STATE_FILE.read_text())
            alias_map = {'gchat': 'google_chat'}
            open_tabs = []
            seen = set()
            for key in state.get('open', []):
                normalized = alias_map.get(key, key)
                if normalized in seen:
                    continue
                seen.add(normalized)
                open_tabs.append(normalized)
            active = alias_map.get(state.get('active'), state.get('active'))
            normalized_state = {'open': open_tabs, 'active': active}
            if normalized_state != state:
                try:
                    _STATE_FILE.write_text(json.dumps(normalized_state, indent=2))
                except Exception:
                    pass
            return normalized_state
        except Exception:
            return None

    def restore_active_tab(self):
        """Called once after hot-reload first scan: select the previously active tab."""
        if not self._restore_state:
            return
        active_key = self._restore_state.get('active')
        if not active_key:
            return
        # Find the frame matching the saved active key
        tab_info = self._tabs.get(active_key)
        if tab_info and tab_info.get('frame'):
            try:
                self.select(tab_info['frame'])
                print(f"[✓] Restored active tab: {active_key}")
            except Exception as e:
                print(f"[!] Could not restore active tab {active_key}: {e}")
        # Clear restore state so subsequent auto-opens aren't filtered
        self._restore_state = None

    def get_open_tabs(self):
        """Return list of (tab_key, display_text) for all open tabs, active last."""
        result = []
        active_key = None
        if self._current_frame:
            at = self._tabbar.get_text(self._current_frame).strip()
            active_key = at.lower().replace(' ', '_')
        for e in self._tabbar._entries:
            text = e['text'].strip()
            key = text.lower().replace(' ', '_')
            result.append((key, text, key == active_key))
        return result

    # ── Home tab ──────────────────────────────────────────────────────────────

    def _add_home_tab(self):
        home_frame = tk.Frame(self._stack, bg='#1e1e1e')
        content = tk.Frame(home_frame, bg='#1e1e1e')
        content.place(relx=0.5, rely=0.4, anchor=tk.CENTER)
        tk.Label(content, text="[*] Auger SRE Platform",
                 font=('Segoe UI', 32, 'bold'), fg='#4ec9b0', bg='#1e1e1e'
                 ).pack(pady=(0, 10))
        tk.Label(content, text="Ask Auger below to build your platform",
                 font=('Segoe UI', 14), fg='#e0e0e0', bg='#1e1e1e'
                 ).pack(pady=(0, 20))
        tk.Label(content, text='Try: "create a service health monitor widget"',
                 font=('Consolas', 11, 'italic'), fg='#808080', bg='#1e1e1e'
                 ).pack()
        try:
            home_img = _icons.get('home', 18)
            self._tab_icons['home'] = home_img
            self.add(home_frame, image=home_img, text=" Home ", compound=tk.LEFT)
        except Exception:
            self.add(home_frame, text="  Home  ")
        self.select(home_frame)
        self._tabs['home'] = {'frame': home_frame, 'widget': None}

    # ── Widget tab management ─────────────────────────────────────────────────


    def _get_tab_icon(self, widget_class, size: int = 18):
        """Return a PhotoImage for a widget tab.

        Tries WIDGET_ICON_FUNC (PIL make_icon callable) first, then falls back
        to WIDGET_ICON_NAME (pre-built icon from icons.py). Returns None if
        neither is available or PIL is not installed.
        """
        try:
            from PIL import ImageTk as _itk
            icon_func = getattr(widget_class, 'WIDGET_ICON_FUNC', None)
            if icon_func is not None:
                img = icon_func(size=size)
                return _itk.PhotoImage(img)
        except Exception:
            pass
        icon_name = getattr(widget_class, 'WIDGET_ICON_NAME', None)
        if icon_name:
            try:
                return _icons.get(icon_name, size)
            except Exception:
                pass
        return None

    def add_widget_tab(self, name, widget_class, **kwargs):
        tab_key = name.lower().replace(' ', '_')
        if tab_key in self._tabs:
            frame = self._tabs[tab_key]['frame']
            try:
                self._tabbar.index_of(frame)
                self.select(frame)
                return
            except tk.TclError:
                del self._tabs[tab_key]

        try:
            frame = tk.Frame(self._stack, bg='#1e1e1e')
            widget = widget_class(frame, **kwargs)
            widget.pack(fill=tk.BOTH, expand=True)

            tab_img = self._get_tab_icon(widget_class)
            if tab_img:
                self._tab_icons[tab_key] = tab_img
                self.add(frame, image=tab_img, text=f" {name} ", compound=tk.LEFT)
            else:
                self.add(frame, text=f"  {name}  ")
            self.select(frame)
            self._tabs[tab_key] = {'frame': frame, 'widget': widget, 'cls': widget_class}
            print(f"✅ Opened widget: {name}")

        except Exception as e:
            import traceback as _tb
            import inspect as _inspect
            tb_str = _tb.format_exc()
            frame = tk.Frame(self._stack, bg='#1e1e1e')
            self._build_crash_overlay(frame, name, widget_class, str(e), tb_str)
            self.add(frame, text=f"  ⚠ {name}  ")
            self.select(frame)
            self._tabs[tab_key] = {'frame': frame, 'widget': None, 'cls': widget_class}
            print(f"❌ Error loading widget {name}: {e}")

    def _build_crash_overlay(self, frame, widget_name, widget_class, error_msg, tb_str):
        """Replace widget content with a crash banner + 'Ask Auger to fix' button."""
        import inspect as _inspect

        # Resolve source file path for this widget class
        source_path = None
        try:
            source_path = _inspect.getfile(widget_class)
        except (TypeError, OSError):
            pass

        outer = tk.Frame(frame, bg='#1e1e1e')
        outer.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)

        # ── Error header ──────────────────────────────────────────────────────
        tk.Label(outer, text=f"⚠  {widget_name} crashed on load",
                 font=('Segoe UI', 14, 'bold'), fg='#f44747', bg='#1e1e1e'
                 ).pack(pady=(0, 6))

        tk.Label(outer, text=error_msg,
                 font=('Consolas', 10), fg='#ce9178', bg='#1e1e1e',
                 wraplength=620, justify=tk.LEFT
                 ).pack(pady=(0, 12))

        # ── Traceback (scrollable, collapsed by default) ───────────────────
        tb_frame = tk.Frame(outer, bg='#1e1e1e')
        tb_frame.pack(fill=tk.X, pady=(0, 12))
        tb_text = tk.Text(tb_frame, font=('Consolas', 9), fg='#808080', bg='#252526',
                          relief=tk.FLAT, wrap=tk.NONE, height=6, width=90)
        tb_scroll = tk.Scrollbar(tb_frame, orient=tk.VERTICAL, command=tb_text.yview)
        tb_text.configure(yscrollcommand=tb_scroll.set)
        tb_text.insert('1.0', tb_str)
        tb_text.config(state=tk.DISABLED)
        tb_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tb_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # ── Action buttons ────────────────────────────────────────────────────
        btn_row = tk.Frame(outer, bg='#1e1e1e')
        btn_row.pack()

        def _ask_auger_to_fix():
            if not self._ask_auger_cb:
                return
            # Read first 120 lines of widget source as context
            source_snippet = ''
            if source_path:
                try:
                    with open(source_path, 'r', encoding='utf-8') as f:
                        lines = f.readlines()[:120]
                    source_snippet = ''.join(lines)
                except Exception:
                    pass
            self._ask_auger_cb(widget_name, tb_str, source_path or '', source_snippet)

        def _retry():
            # Destroy overlay content and try reloading the widget
            for child in frame.winfo_children():
                child.destroy()
            try:
                w = widget_class(frame)
                w.pack(fill=tk.BOTH, expand=True)
                tab_key = widget_name.lower().replace(' ', '_')
                if tab_key in self._tabs:
                    self._tabs[tab_key]['widget'] = w
                # Remove error indicator from tab label
                self._tabbar.update_tab(frame, text=f" {widget_name} ")
            except Exception as retry_exc:
                import traceback as _tb2
                self._build_crash_overlay(frame, widget_name, widget_class,
                                          str(retry_exc), _tb2.format_exc())

        tk.Button(btn_row, text='🤖  Ask Auger to Fix',
                  font=('Segoe UI', 10, 'bold'), fg='#ffffff', bg='#0e639c',
                  activebackground='#1177bb', relief=tk.FLAT, padx=12, pady=6,
                  cursor='hand2',
                  command=_ask_auger_to_fix
                  ).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(btn_row, text='↺  Retry',
                  font=('Segoe UI', 10), fg='#cccccc', bg='#3c3c3c',
                  activebackground='#505050', relief=tk.FLAT, padx=12, pady=6,
                  cursor='hand2',
                  command=_retry
                  ).pack(side=tk.LEFT, padx=(0, 8))

        def _schedule_restart():
            import subprocess
            try:
                subprocess.Popen(
                    ['curl', '-sf', '--noproxy', 'localhost',
                     '-X', 'POST', 'http://localhost:7437/schedule_restart',
                     '-H', 'Content-Type: application/json',
                     '-d', '{"delay": 3, "message": "Restarting platform..."}'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            except Exception:
                pass

        tk.Button(btn_row, text='🔄  Restart Platform',
                  font=('Segoe UI', 10), fg='#cccccc', bg='#3c3c3c',
                  activebackground='#505050', relief=tk.FLAT, padx=12, pady=6,
                  cursor='hand2',
                  command=_schedule_restart
                  ).pack(side=tk.LEFT)

        if source_path:
            tk.Label(outer, text=f"📄 {source_path}",
                     font=('Consolas', 9), fg='#555555', bg='#1e1e1e'
                     ).pack(pady=(10, 0))

    def open_help_doc(self, path: str, title: str):
        from auger.ui.widgets.help_viewer import HelpViewerWidget
        tab_key = 'help'
        if tab_key in self._tabs:
            frame = self._tabs[tab_key]['frame']
            try:
                self.select(frame)
            except Exception:
                pass
        else:
            self.add_widget_tab("Help", HelpViewerWidget)
        if tab_key in self._tabs:
            _, widget = self._tabs[tab_key].get('frame'), self._tabs[tab_key].get('widget')
            widget = self._tabs[tab_key]['widget']
            if widget:
                widget.open_doc(path, title)

    def load_widget_from_code(self, code, name=None):
        try:
            match = re.search(r'class\s+(\w+)\s*\(', code)
            if not match:
                messagebox.showerror("Error", "No class definition found in code")
                return
            class_name = match.group(1)
            if not name:
                name = class_name.lower()
            if not name.endswith('.py'):
                name = f"{name}.py"
            widgets_dir = Path('ui/widgets')
            widgets_dir.mkdir(parents=True, exist_ok=True)
            (widgets_dir / name).write_text(code)
            messagebox.showinfo("Widget Saved",
                f"Widget saved to {widgets_dir / name}\n\n"
                "The hot reloader will load it automatically in ~1 second.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save widget:\n{e}")

    def hot_reload_update(self, path, module):
        try:
            widget_class = None
            for attr in dir(module):
                obj = getattr(module, attr)
                if (isinstance(obj, type) and
                        (issubclass(obj, tk.Frame) or issubclass(obj, ttk.Frame)) and
                        obj not in (tk.Frame, ttk.Frame)):
                    widget_class = obj
                    break
            if not widget_class:
                print(f"⚠️  No Frame subclass found in {path.name}")
                return

            if hasattr(widget_class, 'WIDGET_TITLE'):
                display_name = widget_class.WIDGET_TITLE
            else:
                display_name = widget_class.__name__.replace('Widget', '').replace('_', ' ').title()
            tab_key = display_name.lower().replace(' ', '_')

            if tab_key in self._tabs:
                frame = self._tabs[tab_key]['frame']
                old_widget = self._tabs[tab_key]['widget']

                # Flash
                old_text = self._tabbar.get_text(frame)
                clean_text = old_text.replace('[RELOAD]', '').strip()
                self._tabbar.update_tab(frame, text=f"  [RELOAD] {clean_text}  ")

                if old_widget:
                    old_widget.destroy()
                new_widget = widget_class(frame)
                new_widget.pack(fill=tk.BOTH, expand=True)
                self._tabs[tab_key]['widget'] = new_widget
                self._tabs[tab_key]['cls'] = widget_class

                # Also update the Widgets menu lambda so reopening the tab
                # uses the new class (the menu captures class at creation time)
                app = self.master
                while app and not isinstance(app, tk.Tk):
                    app = app.master
                if app and hasattr(app, 'widgets_menu'):
                    menu = app.widgets_menu
                    try:
                        for i in range(menu.index('end') + 1):
                            if (menu.type(i) == 'command' and
                                    menu.entrycget(i, 'label') == display_name):
                                menu.entryconfigure(
                                    i,
                                    command=lambda dn=display_name, wc=widget_class:
                                        self.add_widget_tab(dn, wc))
                                break
                    except Exception:
                        pass

                tab_img = self._get_tab_icon(widget_class)
                if tab_img:
                    self._tab_icons[tab_key] = tab_img
                    self.after(1200, lambda f=frame, img=tab_img, t=clean_text:
                               self._tabbar.update_tab(f, text=f" {t} ", image=img, compound=tk.LEFT))
                else:
                    self.after(1200, lambda f=frame, t=clean_text:
                               self._tabbar.update_tab(f, text=f"  {t}  "))

                print(f"[RELOAD] Hot reloaded: {widget_class.__name__}")

            else:
                skip = getattr(widget_class, 'WIDGET_SKIP_AUTO_OPEN', False)
                app = self.master
                while app and not isinstance(app, tk.Tk):
                    app = app.master
                if app and hasattr(app, 'widgets_menu') and not skip:
                    menu = app.widgets_menu
                    existing = [menu.entrycget(i, 'label')
                                for i in range(menu.index('end') + 1)
                                if menu.type(i) == 'command']
                    if display_name not in existing:
                        menu.add_command(
                            label=display_name,
                            command=lambda dn=display_name, wc=widget_class:
                                self.add_widget_tab(dn, wc))
                        print(f"[✓] Added '{display_name}' to Widgets menu")
                    else:
                        # Tab was closed but menu entry exists — update its lambda
                        # to point at the new (reloaded) class so next open gets
                        # the updated widget instead of the stale cached class.
                        try:
                            for i in range(menu.index('end') + 1):
                                if (menu.type(i) == 'command' and
                                        menu.entrycget(i, 'label') == display_name):
                                    menu.entryconfigure(
                                        i,
                                        command=lambda dn=display_name, wc=widget_class:
                                            self.add_widget_tab(dn, wc))
                                    print(f"[✓] Updated menu command for closed tab: {display_name}")
                                    break
                        except Exception:
                            pass
                if not skip:
                    # If restore state is active, only open tabs in the saved list
                    rs = self._restore_state
                    if rs is not None:
                        saved_open = rs.get('open', [])
                        if tab_key in saved_open:
                            self.add_widget_tab(display_name, widget_class)
                            print(f"[✓] Restored widget: {display_name}")
                        else:
                            print(f"[~] Skipped (not in last session): {display_name}")
                    else:
                        self.add_widget_tab(display_name, widget_class)
                        print(f"[✓] Auto-opened widget: {display_name}")

        except Exception as e:
            print(f"❌ Hot reload error for {path.name}: {e}")
