"""
Rules / Conventions / Standards panels for the Prompts widget notebook.

Each panel provides a two-pane editor:
  - Left  (220 px): scrollable list with colored badges + Add/Delete buttons
  - Right         : form fields for the selected item + Save/Discard buttons
  - Bottom        : status bar

Load order: repo YAML first, then ~/.auger/<type>.yaml overlaid (same id → user wins).
Saves always go to the user file only.
"""
import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path

import yaml

from auger.ui.utils import make_text_copyable, add_listbox_menu

# ── Shared colour constants ───────────────────────────────────────────────────
BG     = "#1e1e1e"
BG2    = "#252526"
BG3    = "#2d2d2d"
ACCENT = "#37373d"
FG     = "#cccccc"
FG2    = "#858585"
GREEN  = "#4ec9b0"
BLUE   = "#4fc1ff"
YELLOW = "#dcdcaa"
RED    = "#f44747"
ORANGE = "#ce9178"

_BTN_KW = dict(font=("Segoe UI", 9), bd=0, padx=8, pady=3,
               activebackground=BG2, activeforeground=FG, cursor="hand2")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_yaml_list(path: Path, key: str) -> list:
    """Load a YAML file and return the list under *key*, or [] on any error."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return list(data.get(key) or [])
    except Exception:
        return []


def _save_yaml(path: Path, key: str, items: list) -> None:
    """Write *items* to *path* under *key*, creating parent dirs if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({key: items}, default_flow_style=False,
                               allow_unicode=True, sort_keys=False),
                    encoding="utf-8")


def _badge_label(parent, text: str, color: str) -> tk.Label:
    return tk.Label(parent, text=text, font=("Segoe UI", 7, "bold"),
                    bg=color, fg=BG, padx=4, pady=1)


def _scrolled_listbox(parent) -> tuple:
    """Return (frame, listbox) with a vertical scrollbar."""
    frame = tk.Frame(parent, bg=BG2)
    sb = tk.Scrollbar(frame, orient=tk.VERTICAL, bg=BG3, troughcolor=BG2,
                      highlightthickness=0)
    lb = tk.Listbox(frame, bg=BG2, fg=FG, selectbackground=ACCENT,
                    selectforeground=FG, bd=0, highlightthickness=0,
                    activestyle="none", yscrollcommand=sb.set,
                    font=("Segoe UI", 9))
    sb.config(command=lb.yview)
    sb.pack(side=tk.RIGHT, fill=tk.Y)
    lb.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    add_listbox_menu(lb)
    return frame, lb


def _text_widget(parent, height: int, editable: bool = True) -> tk.Text:
    t = tk.Text(parent, height=height, bg=BG3, fg=FG, insertbackground=FG,
                bd=0, highlightthickness=1, highlightcolor=ACCENT,
                highlightbackground=BG3, font=("Segoe UI", 9), wrap=tk.WORD,
                relief=tk.FLAT)
    make_text_copyable(t)
    if not editable:
        t.config(state=tk.DISABLED)
    return t


def _entry(parent, **kw) -> tk.Entry:
    return tk.Entry(parent, bg=BG3, fg=FG, insertbackground=FG,
                    bd=0, highlightthickness=1, highlightcolor=ACCENT,
                    highlightbackground=BG3, font=("Segoe UI", 9), **kw)


def _combo(parent, values, **kw) -> ttk.Combobox:
    style = ttk.Style()
    style.configure("RCS.TCombobox", fieldbackground=BG3, background=BG3,
                    foreground=FG, selectbackground=ACCENT,
                    selectforeground=FG, arrowcolor=FG)
    style.map("RCS.TCombobox", fieldbackground=[("readonly", BG3)])
    cb = ttk.Combobox(parent, values=values, style="RCS.TCombobox",
                      font=("Segoe UI", 9), **kw)
    return cb


def _field_row(parent, label_text: str, widget) -> None:
    row = tk.Frame(parent, bg=BG2)
    row.pack(fill=tk.X, padx=8, pady=(4, 0))
    tk.Label(row, text=label_text, font=("Segoe UI", 9), bg=BG2,
             fg=FG2, width=12, anchor="w").pack(side=tk.LEFT)
    widget_frame = tk.Frame(row, bg=BG2)
    widget_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
    widget.pack(in_=widget_frame, fill=tk.X, expand=True)


# ─────────────────────────────────────────────────────────────────────────────
# Base panel
# ─────────────────────────────────────────────────────────────────────────────

class _BasePanel(tk.Frame):
    """Shared scaffold: left list pane + right form pane + status bar."""

    _DATA_KEY = ""   # subclasses set to "rules", "conventions", "standards"
    _FILE     = ""   # subclasses set to "rules.yaml" etc.
    WIDGET_SKIP_AUTO_OPEN = True   # never auto-open as standalone widget

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG, **kwargs)
        self._items: list = []          # list of dicts (merged repo+user)
        self._selected_idx: int = -1    # currently selected list index
        self._dirty: bool = False       # unsaved form changes

        self._load()
        self._build_scaffold()
        self._post_build()
        self._refresh_list()

    # ── Paths ─────────────────────────────────────────────────────────────────

    def _repo_path(self) -> Path:
        return (Path(__file__).resolve().parents[3]
                / "auger" / "data" / "origin" / self._FILE)

    def _user_path(self) -> Path:
        return Path.home() / ".auger" / self._FILE

    # ── Load / Save ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        merged: dict = {}
        order: list = []
        for path in (self._repo_path(), self._user_path()):
            for item in _load_yaml_list(path, self._DATA_KEY):
                iid = item.get("id")
                if iid is None:
                    continue
                if iid not in merged:
                    order.append(iid)
                merged[iid] = item
        self._items = [merged[k] for k in order]

    def _save(self) -> bool:
        """Write current items to the user YAML file. Returns True on success."""
        try:
            _save_yaml(self._user_path(), self._DATA_KEY, self._items)
            return True
        except Exception as exc:
            self._set_status(f"Save failed: {exc}", RED)
            return False

    # ── Scaffold ──────────────────────────────────────────────────────────────

    def _build_scaffold(self) -> None:
        # Main horizontal panes
        panes = tk.Frame(self, bg=BG)
        panes.pack(fill=tk.BOTH, expand=True)

        # ── Left pane ─────────────────────────────────────────────────────────
        left = tk.Frame(panes, bg=BG2, width=220)
        left.pack(side=tk.LEFT, fill=tk.Y)
        left.pack_propagate(False)

        tk.Label(left, text=self._DATA_KEY.capitalize(), font=("Segoe UI", 10, "bold"),
                 bg=BG2, fg=FG, anchor="w").pack(fill=tk.X, padx=10, pady=(8, 4))

        list_frame, self._listbox = _scrolled_listbox(left)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self._listbox.bind("<<ListboxSelect>>", self._on_select)

        btn_row = tk.Frame(left, bg=BG2)
        btn_row.pack(fill=tk.X, padx=4, pady=(0, 6))
        tk.Button(btn_row, text="Add", bg=ACCENT, fg=FG,
                  command=self._add_item, **_BTN_KW).pack(side=tk.LEFT, padx=(0, 4))
        self._del_btn = tk.Button(btn_row, text="Delete", bg=ACCENT, fg=FG2,
                                  command=self._delete_item, **_BTN_KW)
        self._del_btn.pack(side=tk.LEFT)

        # ── Right pane ────────────────────────────────────────────────────────
        right = tk.Frame(panes, bg=BG2)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._form_frame = tk.Frame(right, bg=BG2)
        self._form_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        self._build_form(self._form_frame)

        # Save / Discard row
        save_row = tk.Frame(right, bg=BG2)
        save_row.pack(fill=tk.X, padx=8, pady=(4, 6))
        tk.Button(save_row, text="Save", bg=GREEN, fg=BG,
                  command=self._on_save, **_BTN_KW).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(save_row, text="Discard", bg=ACCENT, fg=FG2,
                  command=self._on_discard, **_BTN_KW).pack(side=tk.LEFT)

        # ── Status bar ────────────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="")
        self._status_bar = tk.Label(self, textvariable=self._status_var,
                                    font=("Segoe UI", 8), bg=BG, fg=FG2,
                                    anchor="w")
        self._status_bar.pack(fill=tk.X, padx=8, pady=(0, 4))

    def _set_status(self, msg: str, color: str = FG2) -> None:
        self._status_var.set(msg)
        self._status_bar.config(fg=color)

    # ── Abstract interface (subclasses implement) ─────────────────────────────

    def _build_form(self, parent: tk.Frame) -> None:
        """Build form widgets inside *parent*. Called once during scaffold."""
        raise NotImplementedError

    def _post_build(self) -> None:
        """Optional hook called after scaffold is built."""

    def _list_label(self, item: dict) -> str:
        """Return the string shown in the listbox for *item*."""
        return item.get("name", item.get("id", "?"))

    def _populate_form(self, item: dict) -> None:
        """Fill form fields from *item*. Called when user selects a row."""
        raise NotImplementedError

    def _collect_form(self) -> dict:
        """Read form fields and return a dict. Called on Save."""
        raise NotImplementedError

    # ── List management ───────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._listbox.delete(0, tk.END)
        for item in self._items:
            self._listbox.insert(tk.END, self._list_label(item))

    def _on_select(self, event=None) -> None:
        sel = self._listbox.curselection()
        if not sel:
            return
        self._selected_idx = sel[0]
        self._populate_form(self._items[self._selected_idx])

    def _add_item(self) -> None:
        new_item = self._new_item_template()
        self._items.append(new_item)
        self._refresh_list()
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(tk.END)
        self._listbox.see(tk.END)
        self._selected_idx = len(self._items) - 1
        self._populate_form(new_item)
        self._set_status("New item added — fill in fields and Save.", BLUE)

    def _delete_item(self) -> None:
        if self._selected_idx < 0 or self._selected_idx >= len(self._items):
            return
        self._items.pop(self._selected_idx)
        self._selected_idx = -1
        self._refresh_list()
        self._clear_form()
        if self._save():
            self._set_status("Item deleted.", FG2)

    def _new_item_template(self) -> dict:
        """Return a blank item dict. Subclasses may override."""
        return {"id": f"new-item-{len(self._items)}", "name": "New Item"}

    def _clear_form(self) -> None:
        """Reset form to empty state."""
        self._populate_form(self._new_item_template())

    # ── Save / Discard ────────────────────────────────────────────────────────

    def _on_save(self) -> None:
        if self._selected_idx < 0:
            self._set_status("No item selected.", FG2)
            return
        item = self._collect_form()
        self._items[self._selected_idx] = item
        self._refresh_list()
        self._listbox.selection_set(self._selected_idx)
        if self._save():
            self._set_status("Saved.", GREEN)

    def _on_discard(self) -> None:
        if self._selected_idx >= 0:
            self._populate_form(self._items[self._selected_idx])
        self._set_status("Changes discarded.", FG2)


# ─────────────────────────────────────────────────────────────────────────────
# RulesPanel
# ─────────────────────────────────────────────────────────────────────────────

_ENFORCEMENT_COLORS = {
    "warn":  ORANGE,
    "block": RED,
    "info":  BLUE,
}

_SCOPE_OPTIONS = [
    "global",
    "repo:assist-prod-flux-config",
    "repo:auger-ai-sre-platform",
    "team:SRE",
    "team:Dev",
]

_ENFORCEMENT_OPTIONS = ["warn", "block", "info"]


class RulesPanel(_BasePanel):
    _DATA_KEY = "rules"
    _FILE     = "rules.yaml"

    def _post_build(self) -> None:
        self._conflict_strip = tk.Label(
            self, text="", font=("Segoe UI", 8), bg="#3a3000", fg=YELLOW,
            anchor="w", padx=8)
        # inserted dynamically when conflicts exist
        self._check_conflicts()

    def _list_label(self, item: dict) -> str:
        scope = item.get("scope", "global")
        enf   = item.get("enforcement", "info")
        badge = f"[{enf}]"
        name  = item.get("name", item.get("id", "?"))
        return f"{badge}  {name}  ({scope})"

    def _build_form(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="Edit Rule", font=("Segoe UI", 10, "bold"),
                 bg=BG2, fg=FG, anchor="w").pack(fill=tk.X, padx=8, pady=(6, 4))

        # name
        self._f_name = _entry(parent)
        _field_row(parent, "Name:", self._f_name)

        # scope (combobox + freeform)
        self._f_scope = _combo(parent, _SCOPE_OPTIONS)
        self._f_scope.set("global")
        _field_row(parent, "Scope:", self._f_scope)

        # enforcement
        self._f_enforcement = _combo(parent, _ENFORCEMENT_OPTIONS, state="readonly")
        self._f_enforcement.set("info")
        _field_row(parent, "Enforcement:", self._f_enforcement)

        # rule text
        tk.Label(parent, text="Rule text:", font=("Segoe UI", 9),
                 bg=BG2, fg=FG2).pack(anchor="w", padx=8, pady=(6, 2))
        self._f_rule = _text_widget(parent, height=6)
        self._f_rule.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

    def _populate_form(self, item: dict) -> None:
        self._f_name.delete(0, tk.END)
        self._f_name.insert(0, item.get("name", ""))
        self._f_scope.set(item.get("scope", "global"))
        self._f_enforcement.set(item.get("enforcement", "info"))
        self._f_rule.delete("1.0", tk.END)
        self._f_rule.insert("1.0", (item.get("rule") or "").strip())

    def _collect_form(self) -> dict:
        base = self._items[self._selected_idx].copy()
        base["name"]        = self._f_name.get().strip()
        base["scope"]       = self._f_scope.get().strip()
        base["enforcement"] = self._f_enforcement.get().strip()
        base["rule"]        = self._f_rule.get("1.0", tk.END).strip()
        return base

    def _new_item_template(self) -> dict:
        return {
            "id": f"new-rule-{len(self._items)}",
            "name": "New Rule",
            "scope": "global",
            "enforcement": "info",
            "rule": "",
        }

    def _on_save(self) -> None:
        super()._on_save()
        self._check_conflicts()

    def _load(self) -> None:
        super()._load()

    def _check_conflicts(self) -> None:
        """Detect scope conflicts; mark earlier duplicates with ⚠️ in listbox."""
        scope_seen: dict = {}  # scope -> last index
        conflicts: set = set()
        for idx, item in enumerate(self._items):
            scope = item.get("scope", "global")
            if scope in scope_seen:
                conflicts.add(scope_seen[scope])
            scope_seen[scope] = idx

        # Re-render listbox with ⚠️ markers
        sel = self._listbox.curselection()
        self._listbox.delete(0, tk.END)
        for idx, item in enumerate(self._items):
            label = self._list_label(item)
            if idx in conflicts:
                label = "⚠️ " + label
            self._listbox.insert(tk.END, label)
        if sel:
            self._listbox.selection_set(sel[0])

        # Show/hide conflict strip
        n = len(conflicts)
        if n > 0:
            msg = f"⚠️ {n} conflicting rule{'s' if n > 1 else ''} detected — last rule wins per scope"
            self._conflict_strip.config(text=msg)
            self._conflict_strip.pack(fill=tk.X, before=self._status_bar)
        else:
            self._conflict_strip.pack_forget()

    def _refresh_list(self) -> None:
        self._check_conflicts()


# ─────────────────────────────────────────────────────────────────────────────
# ConventionsPanel
# ─────────────────────────────────────────────────────────────────────────────

_CATEGORY_COLORS = {
    "branch": GREEN,
    "commit": BLUE,
    "pr":     YELLOW,
}

_CATEGORY_OPTIONS = ["branch", "commit", "pr", "other"]


class ConventionsPanel(_BasePanel):
    _DATA_KEY = "conventions"
    _FILE     = "conventions.yaml"

    def _list_label(self, item: dict) -> str:
        cat  = item.get("category", "other")
        name = item.get("name", item.get("id", "?"))
        return f"[{cat}]  {name}"

    def _build_form(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="Edit Convention", font=("Segoe UI", 10, "bold"),
                 bg=BG2, fg=FG, anchor="w").pack(fill=tk.X, padx=8, pady=(6, 4))

        self._f_name = _entry(parent)
        _field_row(parent, "Name:", self._f_name)

        self._f_category = _combo(parent, _CATEGORY_OPTIONS, state="readonly")
        self._f_category.set("branch")
        _field_row(parent, "Category:", self._f_category)

        self._f_pattern = _entry(parent)
        _field_row(parent, "Pattern:", self._f_pattern)

        tk.Label(parent, text="Description:", font=("Segoe UI", 9),
                 bg=BG2, fg=FG2).pack(anchor="w", padx=8, pady=(6, 2))
        self._f_desc = _text_widget(parent, height=4)
        self._f_desc.pack(fill=tk.X, padx=8, pady=(0, 2))

        tk.Label(parent, text="Examples (one per line):", font=("Segoe UI", 9),
                 bg=BG2, fg=FG2).pack(anchor="w", padx=8, pady=(4, 2))
        self._f_examples = _text_widget(parent, height=3)
        self._f_examples.pack(fill=tk.X, padx=8, pady=(0, 4))

    def _populate_form(self, item: dict) -> None:
        self._f_name.delete(0, tk.END)
        self._f_name.insert(0, item.get("name", ""))
        self._f_category.set(item.get("category", "branch"))
        self._f_pattern.delete(0, tk.END)
        self._f_pattern.insert(0, item.get("pattern", ""))
        self._f_desc.delete("1.0", tk.END)
        self._f_desc.insert("1.0", (item.get("description") or "").strip())
        self._f_examples.delete("1.0", tk.END)
        examples = item.get("examples") or []
        self._f_examples.insert("1.0", "\n".join(examples))

    def _collect_form(self) -> dict:
        base = self._items[self._selected_idx].copy()
        base["name"]        = self._f_name.get().strip()
        base["category"]    = self._f_category.get().strip()
        base["pattern"]     = self._f_pattern.get().strip()
        base["description"] = self._f_desc.get("1.0", tk.END).strip()
        raw_ex = self._f_examples.get("1.0", tk.END).strip()
        base["examples"]    = [e.strip() for e in raw_ex.splitlines() if e.strip()]
        return base

    def _new_item_template(self) -> dict:
        return {
            "id": f"new-convention-{len(self._items)}",
            "name": "New Convention",
            "category": "branch",
            "pattern": "",
            "description": "",
            "examples": [],
        }


# ─────────────────────────────────────────────────────────────────────────────
# StandardsPanel
# ─────────────────────────────────────────────────────────────────────────────

class StandardsPanel(_BasePanel):
    _DATA_KEY = "standards"
    _FILE     = "standards.yaml"

    def _list_label(self, item: dict) -> str:
        return item.get("name", item.get("id", "?"))

    def _build_form(self, parent: tk.Frame) -> None:
        tk.Label(parent, text="Edit Standard", font=("Segoe UI", 10, "bold"),
                 bg=BG2, fg=FG, anchor="w").pack(fill=tk.X, padx=8, pady=(6, 4))

        self._f_name = _entry(parent)
        _field_row(parent, "Name:", self._f_name)

        tk.Label(parent, text="Description:", font=("Segoe UI", 9),
                 bg=BG2, fg=FG2).pack(anchor="w", padx=8, pady=(6, 2))
        self._f_desc = _text_widget(parent, height=3)
        self._f_desc.pack(fill=tk.X, padx=8, pady=(0, 2))

        self._f_url = _entry(parent)
        _field_row(parent, "URL (opt.):", self._f_url)

        tk.Label(parent, text="Content:", font=("Segoe UI", 9),
                 bg=BG2, fg=FG2).pack(anchor="w", padx=8, pady=(6, 2))
        self._f_content = _text_widget(parent, height=6)
        self._f_content.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))

    def _populate_form(self, item: dict) -> None:
        self._f_name.delete(0, tk.END)
        self._f_name.insert(0, item.get("name", ""))
        self._f_desc.delete("1.0", tk.END)
        self._f_desc.insert("1.0", (item.get("description") or "").strip())
        self._f_url.delete(0, tk.END)
        self._f_url.insert(0, item.get("url") or "")
        self._f_content.delete("1.0", tk.END)
        self._f_content.insert("1.0", (item.get("content") or "").strip())

    def _collect_form(self) -> dict:
        base = self._items[self._selected_idx].copy()
        base["name"]        = self._f_name.get().strip()
        base["description"] = self._f_desc.get("1.0", tk.END).strip()
        url = self._f_url.get().strip()
        if url:
            base["url"] = url
        elif "url" in base:
            del base["url"]
        base["content"] = self._f_content.get("1.0", tk.END).strip()
        return base

    def _new_item_template(self) -> dict:
        return {
            "id": f"new-standard-{len(self._items)}",
            "name": "New Standard",
            "description": "",
            "content": "",
        }
