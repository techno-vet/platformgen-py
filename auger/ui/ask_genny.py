"""Assistant panel - AI agent interface running the configured CLI."""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import subprocess
import threading
import queue
import shutil
import re
import json
import os
import signal
from pathlib import Path
import sys
from datetime import datetime, timedelta
from dotenv import dotenv_values

from auger.ai.provider_sessions import (
    list_local_sessions,
    read_copilot_pinned_session_id,
    read_local_pinned_session_id,
    rename_local_session,
)
from auger.ai.providers import (
    COPILOT_MODEL_OPTIONS,
    PROVIDER_COPILOT,
    PROVIDER_LABELS,
    PROVIDER_OPENAI,
    available_models,
    default_model,
    normalize_model,
    normalize_provider,
    provider_supports_copilot_sessions,
    seeded_models,
)
from .markdown_widget import MarkdownWidget
from auger.runtime import assistant_name, cli_name, daemon_url, product_name, state_dir

try:
    from auger.tools.git_workflow import handle_widget_change, get_auger_repo, make_branch_name
    _GIT_WORKFLOW_AVAILABLE = True
except ImportError:
    _GIT_WORKFLOW_AVAILABLE = False


ASK_HEADER_BG = '#24292f'
ASK_HEADER_BG_ACTIVE = '#2f363d'
ASK_HEADER_ACCENT = '#22b8b2'
ASK_HEADER_ACCENT_ACTIVE = '#45d6d0'
ASK_HEADER_TEXT = '#f0f6fc'
ASK_HEADER_TEXT_MUTED = '#c9d1d9'
ASK_HEADER_TEXT_DIM = '#8b949e'
ASK_HEADER_COMBO_BG = '#2d333b'
ASK_HEADER_COMBO_BG_ACTIVE = '#3a424c'
ASK_HEADER_COMBO_TEXT = '#f0f6fc'
ASK_HEADER_COMBO_FONT = ('Segoe UI', 10)
ASK_HEADER_COMBO_LIST_FONT = ('Segoe UI', 11)

SESSION_HEALTH_POLL_MS = 5000
SESSION_LOCK_STALE_SECS = 15


class AskGennyPanel(tk.Frame):
    """Bottom panel for interacting with the Genny AI agent."""
    
    def __init__(self, parent, content_area, popped_out=False):
        super().__init__(parent, bg='#1e1e1e')
        
        self._is_popped_out = popped_out
        self.content_area = content_area
        self._queue = queue.Queue()
        self._process = None
        self._active_request_mode = None
        self._cancel_supported = False
        self._cancel_requested = False
        self._last_prompt = ''  # original user prompt, stored for post-response footer
        
        self._auger = self._resolve_cli_path()
        
        # History persistence
        self._history_dir = state_dir() / "logs" / "chat_history"
        self._history_dir.mkdir(parents=True, exist_ok=True)
        self._history_file = self._history_dir / "conversations.jsonl"
        self._status_file = self._history_dir / "work_status.jsonl"
        self._pending_response_file = self._history_dir / "pending_response.json"
        self._draft_file = self._history_dir / "draft.json"
        self._legacy_draft_file = self._history_dir / "draft.txt"
        self._auto_save_id = None
        self._draft_cache_text = ""
        self._draft_saved_at = None
        self._live_response_chunks = []
        self._live_response_prompt = ""
        self._panel_state_file = state_dir() / "ask_genny_panel.json"
        self._provider_var = tk.StringVar(value=PROVIDER_LABELS[PROVIDER_COPILOT])
        self._model_var = tk.StringVar(value="auto")
        self._session_var = tk.StringVar(value="Pinned Session")
        self._selected_session_target = {'mode': 'pinned'}
        self._session_aliases = {}
        self._session_targets_by_label = {}
        self._provider_labels = {label: provider for provider, label in PROVIDER_LABELS.items()}
        self._provider_values = [PROVIDER_LABELS[provider] for provider in PROVIDER_LABELS]
        self._model_options_cache = {provider: seeded_models(provider) for provider in PROVIDER_LABELS}
        self._load_panel_state()

        # Shared chat history watcher (cross-source: terminal, host, container)
        self._chat_history_file = state_dir() / "chat_history.jsonl"
        self._chat_history_offset = 0  # byte offset — only show lines added after startup

        self._build_ui()
        # Defer history restore until after mainloop starts — avoids a Tk
        # thread-safety race with status_bar worker threads that call after()
        # from background threads during startup.
        self.after(50, self._restore_history)
        self._show_welcome()
        self._restore_draft()
        self._start_queue_poll()
        self._start_auto_save()
        self._start_chat_history_watcher()
        self._start_session_health_poll()
        # Self-initialize from origin docs if this is a fresh install
        self.after(2000, self._maybe_self_initialize)

    def _resolve_cli_path(self) -> str:
        cli = cli_name()
        candidates = [
            shutil.which(cli),
            os.environ.get("AUGER_CLI_PATH"),
            os.path.join(os.environ.get("AUGER_VENV_BIN", ""), cli) if os.environ.get("AUGER_VENV_BIN") else None,
            str(Path(sys.executable).resolve().parent / cli),
            str(state_dir() / "venv" / "bin" / cli),
            str(Path.home() / f".local/bin/{cli}"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return str(Path(candidate))
        return str(Path.home() / f".local/bin/{cli}")

    def _load_header_brand_image(self):
        asset_path = Path(__file__).resolve().parent / "assets" / "ask_genny_header.png"
        if not asset_path.exists():
            return None
        try:
            image = tk.PhotoImage(file=str(asset_path))
            max_width = 28
            max_height = 24
            scale = max(
                1,
                (image.width() + max_width - 1) // max_width,
                (image.height() + max_height - 1) // max_height,
            )
            if scale > 1:
                image = image.subsample(scale, scale)
            return image
        except Exception:
            return None

    def _configure_header_combo_style(self):
        style = ttk.Style()
        style_name = 'AskHeader.TCombobox'
        try:
            style.theme_use(style.theme_use())
        except Exception:
            pass
        style.configure(
            style_name,
            foreground=ASK_HEADER_COMBO_TEXT,
            fieldbackground=ASK_HEADER_COMBO_BG,
            background=ASK_HEADER_COMBO_BG,
            arrowcolor=ASK_HEADER_ACCENT,
            bordercolor=ASK_HEADER_BG_ACTIVE,
            darkcolor=ASK_HEADER_COMBO_BG,
            lightcolor=ASK_HEADER_COMBO_BG,
            insertcolor=ASK_HEADER_COMBO_TEXT,
            padding=(6, 2, 6, 2),
            font=ASK_HEADER_COMBO_FONT,
            relief='flat',
            borderwidth=1,
            arrowsize=14,
        )
        style.map(
            style_name,
            fieldbackground=[
                ('readonly', ASK_HEADER_COMBO_BG),
                ('disabled', ASK_HEADER_BG_ACTIVE),
                ('focus', ASK_HEADER_COMBO_BG_ACTIVE),
            ],
            background=[
                ('readonly', ASK_HEADER_COMBO_BG),
                ('disabled', ASK_HEADER_BG_ACTIVE),
                ('focus', ASK_HEADER_COMBO_BG_ACTIVE),
            ],
            bordercolor=[
                ('readonly', ASK_HEADER_BG_ACTIVE),
                ('disabled', ASK_HEADER_BG_ACTIVE),
                ('focus', ASK_HEADER_ACCENT),
            ],
            lightcolor=[
                ('readonly', ASK_HEADER_COMBO_BG),
                ('disabled', ASK_HEADER_BG_ACTIVE),
                ('focus', ASK_HEADER_COMBO_BG_ACTIVE),
            ],
            darkcolor=[
                ('readonly', ASK_HEADER_COMBO_BG),
                ('disabled', ASK_HEADER_BG_ACTIVE),
                ('focus', ASK_HEADER_COMBO_BG_ACTIVE),
            ],
            foreground=[
                ('readonly', ASK_HEADER_COMBO_TEXT),
                ('disabled', ASK_HEADER_TEXT_DIM),
            ],
            arrowcolor=[
                ('disabled', ASK_HEADER_TEXT_DIM),
                ('focus', ASK_HEADER_ACCENT_ACTIVE),
                ('readonly', ASK_HEADER_ACCENT),
            ],
            selectbackground=[('readonly', ASK_HEADER_ACCENT)],
            selectforeground=[('readonly', ASK_HEADER_BG)],
        )
        option_db = {
            '*TCombobox*Listbox.background': ASK_HEADER_COMBO_BG,
            '*TCombobox*Listbox.foreground': ASK_HEADER_COMBO_TEXT,
            '*TCombobox*Listbox.selectBackground': ASK_HEADER_ACCENT,
            '*TCombobox*Listbox.selectForeground': ASK_HEADER_BG,
            '*TCombobox*Listbox.font': ASK_HEADER_COMBO_LIST_FONT,
        }
        for pattern, value in option_db.items():
            try:
                self.option_add(pattern, value)
            except Exception:
                pass

    def _load_panel_state(self):
        data = {}
        if self._panel_state_file.exists():
            try:
                data = json.loads(self._panel_state_file.read_text(encoding='utf-8'))
            except Exception:
                data = {}

        provider = normalize_provider(data.get('selected_provider'))
        self._provider_var.set(PROVIDER_LABELS[provider])
        model = normalize_model(provider, data.get('selected_model'))
        self._model_var.set(model)

        aliases = data.get('session_aliases', {})
        if isinstance(aliases, dict):
            self._session_aliases = {
                str(session_id): str(alias).strip()
                for session_id, alias in aliases.items()
                if str(alias).strip()
            }
        else:
            self._session_aliases = {}

        session_target = data.get('session_target', {})
        if not isinstance(session_target, dict):
            session_target = {}
        mode = str(session_target.get('mode') or 'pinned').strip().lower()
        if mode == 'session' and str(session_target.get('session_id') or '').strip():
            self._selected_session_target = {
                'mode': 'session',
                'session_id': str(session_target.get('session_id')).strip(),
            }
        elif mode == 'new':
            self._selected_session_target = {
                'mode': 'new',
                'name': self._clean_session_name(session_target.get('name', '')),
            }
        else:
            self._selected_session_target = {'mode': 'pinned'}

    def _save_panel_state(self):
        payload = {
            'selected_provider': self._effective_provider(),
            'selected_model': self._effective_model(),
            'session_target': dict(self._selected_session_target),
            'session_aliases': dict(sorted(self._session_aliases.items())),
        }
        try:
            self._panel_state_file.parent.mkdir(parents=True, exist_ok=True)
            self._panel_state_file.write_text(json.dumps(payload, indent=2), encoding='utf-8')
        except Exception:
            pass

    def _effective_provider(self) -> str:
        selected = self._provider_var.get()
        return normalize_provider(self._provider_labels.get(selected, selected))

    def _effective_model(self) -> str:
        return normalize_model(self._effective_provider(), self._model_var.get())

    def _copilot_session_state_dir(self) -> Path:
        return Path.home() / '.copilot' / 'session-state'

    def _read_pinned_session_id(self) -> str:
        provider = self._effective_provider()
        model = self._effective_model()
        if provider_supports_copilot_sessions(provider):
            return read_copilot_pinned_session_id(model)
        return read_local_pinned_session_id(provider, model)

    def _clean_session_name(self, name: str) -> str:
        return ' '.join(str(name or '').strip().split())

    def _session_timestamp_label(self, timestamp: float | None) -> str:
        if not timestamp:
            return ''
        try:
            return datetime.fromtimestamp(timestamp).strftime('%m/%d %H:%M')
        except Exception:
            return ''

    def _list_copilot_sessions(self, limit: int = 30) -> list[dict]:
        session_root = self._copilot_session_state_dir()
        if not session_root.exists():
            return []
        entries = []
        try:
            dirs = sorted(
                (entry for entry in session_root.iterdir() if entry.is_dir()),
                key=lambda entry: entry.stat().st_mtime,
                reverse=True,
            )
        except Exception:
            return []

        for entry in dirs[:limit]:
            try:
                stat = entry.stat()
                entries.append(
                    {
                        'id': entry.name,
                        'updated_at': stat.st_mtime,
                        'updated_label': self._session_timestamp_label(stat.st_mtime),
                        'alias': self._session_aliases.get(entry.name, '').strip(),
                    }
                )
            except Exception:
                continue
        return entries

    def _list_sessions_for_scope(self, limit: int = 30) -> list[dict]:
        provider = self._effective_provider()
        if provider_supports_copilot_sessions(provider):
            return self._list_copilot_sessions(limit=limit)
        return [
            {
                'id': entry['id'],
                'updated_at': entry.get('updated_at', 0),
                'updated_label': self._session_timestamp_label(entry.get('updated_at')),
                'alias': entry.get('alias', ''),
            }
            for entry in list_local_sessions(provider, self._effective_model(), limit=limit)
        ]

    def _session_display_label(self, session_id: str, alias: str = '', updated_label: str = '', pinned: bool = False) -> str:
        base = alias or ('Pinned Session' if pinned else f'Session {session_id[:8]}')
        parts = [base]
        if not pinned:
            parts.append(session_id[:8])
        if updated_label:
            parts.append(updated_label)
        return ' - '.join(parts)

    def _session_target_matches(self, target: dict, expected: dict) -> bool:
        if target.get('mode') != expected.get('mode'):
            return False
        if target.get('mode') == 'session':
            return str(target.get('session_id') or '') == str(expected.get('session_id') or '')
        if target.get('mode') == 'new':
            return self._clean_session_name(target.get('name', '')) == self._clean_session_name(expected.get('name', ''))
        return True

    def _set_session_target(self, target: dict, refresh: bool = True):
        mode = str(target.get('mode') or 'pinned').strip().lower()
        if mode == 'session' and str(target.get('session_id') or '').strip():
            self._selected_session_target = {
                'mode': 'session',
                'session_id': str(target.get('session_id')).strip(),
            }
        elif mode == 'new':
            self._selected_session_target = {
                'mode': 'new',
                'name': self._clean_session_name(target.get('name', '')),
            }
        else:
            self._selected_session_target = {'mode': 'pinned'}
        self._save_panel_state()
        if refresh and hasattr(self, '_session_combo'):
            self._refresh_session_selector()

    def _refresh_provider_selector(self):
        self._provider_combo['values'] = self._provider_values
        self._provider_var.set(PROVIDER_LABELS[self._effective_provider()])

    def _refresh_model_options(self):
        provider = self._effective_provider()
        options = self._model_options_cache.get(provider) or available_models(provider)
        self._model_options_cache[provider] = options
        self._model_combo['values'] = options
        self._model_var.set(normalize_model(provider, self._model_var.get()))

    def _refresh_provider_models_async(self):
        provider = self._effective_provider()
        model_before = self._model_var.get()

        def _work():
            options = available_models(provider)

            def _apply():
                if self._effective_provider() != provider:
                    return
                self._model_options_cache[provider] = options
                self._model_combo['values'] = options
                self._model_var.set(normalize_model(provider, model_before))
                self._save_panel_state()
                self._refresh_session_selector()

            self.after(0, _apply)

        threading.Thread(target=_work, daemon=True).start()

    def _refresh_model_selector(self):
        self._refresh_model_options()

    def _refresh_session_selector(self):
        pinned_session_id = self._read_pinned_session_id()
        values = []
        mapping = {}

        pinned_alias = self._session_aliases.get(pinned_session_id, '').strip() if pinned_session_id else ''
        pinned_label = self._session_display_label(
            pinned_session_id or 'pinned',
            alias=pinned_alias,
            updated_label='',
            pinned=True,
        )
        values.append(pinned_label)
        mapping[pinned_label] = {'mode': 'pinned'}

        if self._selected_session_target.get('mode') == 'new':
            new_name = self._clean_session_name(self._selected_session_target.get('name', ''))
            new_label = f"New Session - {new_name or 'unnamed'}"
            values.append(new_label)
            mapping[new_label] = dict(self._selected_session_target)

        for entry in self._list_sessions_for_scope():
            if entry['id'] == pinned_session_id:
                continue
            label = self._session_display_label(
                entry['id'],
                alias=entry.get('alias', ''),
                updated_label=entry.get('updated_label', ''),
            )
            if label in mapping:
                label = f"{label} ({entry['id'][:8]})"
            values.append(label)
            mapping[label] = {'mode': 'session', 'session_id': entry['id']}

        self._session_targets_by_label = mapping
        self._session_combo['values'] = values

        selected_label = None
        for label, target in mapping.items():
            if self._session_target_matches(target, self._selected_session_target):
                selected_label = label
                break
        if selected_label is None:
            self._set_session_target({'mode': 'pinned'}, refresh=False)
            selected_label = pinned_label
        self._session_var.set(selected_label)

        rename_state = tk.NORMAL if (
            self._selected_session_target.get('mode') == 'new'
            or self._selected_session_target.get('mode') == 'session'
            or bool(pinned_session_id)
        ) else tk.DISABLED
        self._rename_session_btn.config(state=rename_state)

    def _selected_session_id(self) -> str:
        mode = self._selected_session_target.get('mode')
        if mode == 'session':
            return str(self._selected_session_target.get('session_id') or '').strip()
        if mode == 'pinned':
            return self._read_pinned_session_id()
        return ''

    def _on_provider_selected(self, _event=None):
        current_label = self._provider_var.get()
        provider = self._provider_labels.get(current_label, current_label)
        self._provider_var.set(PROVIDER_LABELS[normalize_provider(provider)])
        self._model_var.set(default_model(self._effective_provider()))
        self._set_session_target({'mode': 'pinned'}, refresh=False)
        self._refresh_model_selector()
        self._refresh_session_selector()
        self._refresh_provider_health_ui()
        self._save_panel_state()
        self._refresh_provider_models_async()

    def _on_model_selected(self, _event=None):
        self._model_var.set(self._effective_model())
        self._set_session_target({'mode': 'pinned'}, refresh=False)
        self._refresh_session_selector()
        self._save_panel_state()

    def _on_session_selected(self, _event=None):
        target = self._session_targets_by_label.get(self._session_var.get())
        if target:
            self._set_session_target(target, refresh=False)

    def _new_session(self):
        suggested = datetime.now().strftime('Session %m/%d %H:%M')
        provider = PROVIDER_LABELS[self._effective_provider()]
        name = simpledialog.askstring(
            f'New {provider} Session',
            f'Optional session name for the next {provider} Ask Genny conversation:',
            parent=self,
            initialvalue=suggested,
        )
        if name is None:
            return
        self._set_session_target({'mode': 'new', 'name': name})

    def _rename_session(self):
        provider = PROVIDER_LABELS[self._effective_provider()]
        mode = self._selected_session_target.get('mode')
        if mode == 'new':
            initial = self._clean_session_name(self._selected_session_target.get('name', ''))
            renamed = simpledialog.askstring(
                'Rename Pending Session',
                f'Name for the next new {provider} session:',
                parent=self,
                initialvalue=initial,
            )
            if renamed is None:
                return
            self._set_session_target({'mode': 'new', 'name': renamed})
            return

        session_id = self._selected_session_id()
        if not session_id:
            messagebox.showinfo(
                'No Session Available',
                f'There is no {provider} session to rename yet. Send a prompt first or choose an existing session.',
                parent=self,
            )
            return

        if provider_supports_copilot_sessions(self._effective_provider()):
            current_name = self._session_aliases.get(session_id, '')
        else:
            current_name = list_local_sessions(self._effective_provider(), self._effective_model(), limit=100)
            current_name = next((entry.get('alias', '') for entry in current_name if entry.get('id') == session_id), '')
        renamed = simpledialog.askstring(
            f'Rename {provider} Session',
            f'Friendly name for this {provider} session:',
            parent=self,
            initialvalue=current_name,
        )
        if renamed is None:
            return
        cleaned = self._clean_session_name(renamed)
        if provider_supports_copilot_sessions(self._effective_provider()):
            if cleaned:
                self._session_aliases[session_id] = cleaned
            else:
                self._session_aliases.pop(session_id, None)
        else:
            rename_local_session(session_id, cleaned)
        self._save_panel_state()
        self._refresh_session_selector()
        self._refresh_provider_health_ui()

    def _apply_session_result(self, metadata: dict | None):
        if not metadata:
            return

        actual_session_id = str(metadata.get('session_id') or '').strip()
        mode = self._selected_session_target.get('mode')

        if mode == 'new' and actual_session_id:
            planned_name = self._clean_session_name(self._selected_session_target.get('name', ''))
            if planned_name and provider_supports_copilot_sessions(self._effective_provider()) and actual_session_id not in self._session_aliases:
                self._session_aliases[actual_session_id] = planned_name
            elif planned_name:
                rename_local_session(actual_session_id, planned_name)
            self._selected_session_target = {'mode': 'session', 'session_id': actual_session_id}
        elif mode == 'session' and actual_session_id:
            self._selected_session_target = {'mode': 'session', 'session_id': actual_session_id}
        else:
            self._selected_session_target = {'mode': 'pinned'}

        self._save_panel_state()
        self._refresh_session_selector()

    def _post_local_session_result(self):
        target_mode = self._selected_session_target.get('mode')
        if target_mode == 'new':
            sessions = self._list_copilot_sessions(limit=1)
            session_id = sessions[0]['id'] if sessions else ''
        else:
            session_id = self._selected_session_id()
        self._apply_session_result({'session_id': session_id, 'model': self._effective_model()})

    def _open_provider_manager(self):
        try:
            module = __import__("auger.ui.widgets.api_config", fromlist=["APIConfigWidget"])
            self.content_area.add_widget_tab("API Keys+", module.APIConfigWidget)
        except Exception as exc:
            messagebox.showerror(
                "Provider Manager",
                f"Could not open API Keys+ provider configuration.\n\n{exc}",
                parent=self,
            )

    def _refresh_provider_health_ui(self):
        supports_copilot = provider_supports_copilot_sessions(self._effective_provider())
        session_state = 'readonly'
        new_session_state = tk.NORMAL
        rename_state = tk.NORMAL if self._selected_session_target.get('mode') == 'new' or self._selected_session_id() else tk.DISABLED
        if not supports_copilot:
            self._unlock_btn.pack_forget()
            self._session_age_label.config(text="")
            self._lock_dot.config(fg=ASK_HEADER_ACCENT_ACTIVE)
        self._session_combo.config(state=session_state)
        self._new_session_btn.config(state=new_session_state)
        self._rename_session_btn.config(state=rename_state)
    
    def _build_ui(self):
        """Build the panel UI."""
        self._configure_header_combo_style()
        # Header
        header = tk.Frame(self, bg=ASK_HEADER_BG, height=34)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)
        self._header = header

        brand = tk.Frame(header, bg=ASK_HEADER_BG)
        brand.pack(side=tk.LEFT, padx=(10, 10))

        self._header_brand_image = self._load_header_brand_image()
        if self._header_brand_image is not None:
            tk.Label(
                brand,
                image=self._header_brand_image,
                bg=ASK_HEADER_BG,
            ).pack(side=tk.LEFT, padx=(0, 6))

        tk.Label(
            brand,
            text=f"Ask {assistant_name()}",
            font=('Segoe UI', 11, 'bold'),
            fg=ASK_HEADER_ACCENT,
            bg=ASK_HEADER_BG
        ).pack(side=tk.LEFT)

        tk.Label(
            header,
            text="Provider",
            font=('Segoe UI', 9),
            fg=ASK_HEADER_TEXT_MUTED,
            bg=ASK_HEADER_BG
        ).pack(side=tk.LEFT, padx=(4, 4))

        self._provider_combo = ttk.Combobox(
            header,
            textvariable=self._provider_var,
            state='readonly',
            width=16,
            style='AskHeader.TCombobox',
            font=ASK_HEADER_COMBO_FONT,
        )
        self._provider_combo.pack(side=tk.LEFT, padx=(0, 8), pady=2)
        self._provider_combo.bind('<<ComboboxSelected>>', self._on_provider_selected)

        self._providers_btn = tk.Button(
            header,
            text="Providers...",
            command=self._open_provider_manager,
            bg=ASK_HEADER_BG,
            fg=ASK_HEADER_TEXT,
            font=('Segoe UI', 9),
            relief=tk.FLAT,
            cursor='hand2',
            activebackground=ASK_HEADER_BG_ACTIVE,
            activeforeground=ASK_HEADER_TEXT,
            padx=6,
            pady=0,
        )
        self._providers_btn.pack(side=tk.LEFT, padx=(0, 8))

        tk.Label(
            header,
            text="Model",
            font=('Segoe UI', 9),
            fg=ASK_HEADER_TEXT_MUTED,
            bg=ASK_HEADER_BG
        ).pack(side=tk.LEFT, padx=(0, 4))

        self._model_combo = ttk.Combobox(
            header,
            textvariable=self._model_var,
            state='readonly',
            width=18,
            style='AskHeader.TCombobox',
            font=ASK_HEADER_COMBO_FONT,
        )
        self._model_combo.pack(side=tk.LEFT, padx=(0, 8), pady=2)
        self._model_combo.bind('<<ComboboxSelected>>', self._on_model_selected)

        tk.Label(
            header,
            text="Session",
            font=('Segoe UI', 9),
            fg=ASK_HEADER_TEXT_MUTED,
            bg=ASK_HEADER_BG
        ).pack(side=tk.LEFT, padx=(0, 4))

        self._session_combo = ttk.Combobox(
            header,
            textvariable=self._session_var,
            state='readonly',
            width=28,
            style='AskHeader.TCombobox',
            font=ASK_HEADER_COMBO_FONT,
        )
        self._session_combo.pack(side=tk.LEFT, padx=(0, 4), pady=2)
        self._session_combo.bind('<<ComboboxSelected>>', self._on_session_selected)

        self._new_session_btn = tk.Button(
            header,
            text="+",
            command=self._new_session,
            bg=ASK_HEADER_BG,
            fg=ASK_HEADER_ACCENT,
            font=('Segoe UI', 9, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            activebackground=ASK_HEADER_BG_ACTIVE,
            activeforeground=ASK_HEADER_ACCENT_ACTIVE,
            padx=6,
            pady=0,
        )
        self._new_session_btn.pack(side=tk.LEFT, padx=(0, 4))

        self._rename_session_btn = tk.Button(
            header,
            text="Rename",
            command=self._rename_session,
            bg=ASK_HEADER_BG,
            fg=ASK_HEADER_TEXT,
            font=('Segoe UI', 9),
            relief=tk.FLAT,
            cursor='hand2',
            activebackground=ASK_HEADER_BG_ACTIVE,
            activeforeground=ASK_HEADER_TEXT,
            padx=6,
            pady=0,
        )
        self._rename_session_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        self.status_label = tk.Label(
            header,
            text="",
            font=('Segoe UI', 9, 'italic'),
            fg=ASK_HEADER_TEXT_DIM,
            bg=ASK_HEADER_BG
        )
        self.status_label.pack(side=tk.RIGHT, padx=10)

        # ── Session health indicator (right side of header) ──────────────────
        # Unlock button — shown only when lock is stuck
        self._unlock_btn = tk.Button(
            header,
            text="Unlock",
            command=self._force_unlock_session,
            bg='#c0392b', fg='white',
            font=('Segoe UI', 8, 'bold'),
            relief=tk.FLAT, cursor='hand2',
            activebackground='#922b21', activeforeground='white',
            padx=6, pady=0,
        )
        # Don't pack yet — shown dynamically when locked

        self._cancel_btn = tk.Button(
            header,
            text="Stop",
            command=self._cancel_request,
            bg=ASK_HEADER_BG,
            fg=ASK_HEADER_ACCENT,
            font=('Segoe UI', 8, 'bold'),
            relief=tk.FLAT,
            cursor='hand2',
            activebackground=ASK_HEADER_BG_ACTIVE,
            activeforeground=ASK_HEADER_ACCENT_ACTIVE,
            padx=6,
            pady=0,
        )
        # Don't pack yet — shown only while a cancellable request is running

        # Last-response age label
        self._session_age_label = tk.Label(
            header, text="",
            font=('Segoe UI', 8), fg=ASK_HEADER_ACCENT_ACTIVE, bg=ASK_HEADER_BG
        )
        self._session_age_label.pack(side=tk.RIGHT, padx=(0, 4))

        # Lock status dot label: green=ok, yellow=warn, red=stuck
        self._lock_dot = tk.Label(
            header, text="●",
            font=('Segoe UI', 11), fg=ASK_HEADER_ACCENT, bg=ASK_HEADER_BG
        )
        self._lock_dot.pack(side=tk.RIGHT, padx=(0, 2))

        # Internal state for health polling
        self._session_locked = False
        self._session_locked_secs = 0
        self._session_last_ts = None
        self._is_processing = False

        # Pop-out button (hidden when already in a popped-out window)
        if not self._is_popped_out:
            self._popout_btn = tk.Button(
                header,
                text="Pop Out",
                command=self._popout,
                bg=ASK_HEADER_BG,
                fg=ASK_HEADER_TEXT,
                font=('Segoe UI', 9),
                relief=tk.FLAT,
                cursor='hand2',
                activebackground=ASK_HEADER_BG_ACTIVE,
                activeforeground=ASK_HEADER_TEXT,
                padx=8, pady=0,
            )
            self._popout_btn.pack(side=tk.RIGHT, padx=(0, 4))

        self._refresh_provider_selector()
        self._refresh_model_selector()
        self._refresh_session_selector()
        self._refresh_provider_health_ui()
        
        # Input bar at BOTTOM (pack before response so it stays visible)
        input_frame = tk.Frame(self, bg='#252526')
        input_frame.pack(fill=tk.X, side=tk.BOTTOM, padx=5, pady=5)
        
        # Input text
        input_text_frame = tk.Frame(input_frame, bg='#252526')
        input_text_frame.pack(fill=tk.BOTH, expand=True, side=tk.LEFT, padx=(0, 5))
        
        self.input_text = tk.Text(
            input_text_frame,
            height=2,
            bg='#2d2d2d',
            fg='#e0e0e0',
            insertbackground='#e0e0e0',
            font=('Consolas', 10),
            wrap=tk.WORD,
            relief=tk.FLAT
        )
        self.input_text.pack(fill=tk.BOTH, expand=True)
        self.input_text.bind('<Return>', self._on_enter)
        self.input_text.bind('<Shift-Return>', lambda e: None)  # Allow newline
        self.input_text.bind('<<Paste>>', self._on_paste)  # Clean emojis on paste
        
        # Buttons
        btn_frame = tk.Frame(input_frame, bg='#252526')
        btn_frame.pack(side=tk.RIGHT)
        
        self.ask_btn = tk.Button(
            btn_frame,
            text="Ask  ➤",
            command=self._on_ask,
            bg='#007acc',
            fg='white',
            font=('Segoe UI', 10),
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=5
        )
        self.ask_btn.pack(pady=(0, 3))
        
        clear_btn = tk.Button(
            btn_frame,
            text="Clear Chat",
            command=self._on_clear,
            bg='#3c3c3c',
            fg='#e0e0e0',
            font=('Segoe UI', 9),
            relief=tk.FLAT,
            cursor='hand2',
            padx=15,
            pady=3
        )
        clear_btn.pack()

        attach_btn = tk.Button(
            btn_frame,
            text="Attach",
            command=self._attach_file,
            bg='#3c3c3c',
            fg='#e0e0e0',
            font=('Segoe UI', 9),
            relief=tk.FLAT,
            cursor='hand2',
            padx=10,
            pady=3
        )
        attach_btn.pack(pady=(2, 0))

        # Mic button — push-to-talk voice input
        self._mic_btn = tk.Button(
            btn_frame,
            text="[MIC]",
            bg='#3c3c3c',
            fg='#a0a0a0',
            font=('Segoe UI', 9),
            relief=tk.FLAT,
            cursor='hand2',
            padx=10,
            pady=3
        )
        self._mic_btn.pack(pady=(2, 0))
        self._mic_btn.bind('<ButtonPress-1>', self._on_mic_press)
        self._mic_btn.bind('<ButtonRelease-1>', self._on_mic_release)
        self._mic_recording = False
        
        # Response area (scrollable markdown widget)
        response_frame = tk.Frame(self, bg='#1e1e1e')
        response_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        scrollbar = ttk.Scrollbar(response_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.response = MarkdownWidget(response_frame, yscrollcommand=scrollbar.set)
        self.response.pack(fill=tk.BOTH, expand=True)
        scrollbar.config(command=self.response.yview)
        self._refresh_model_selector()
        self._refresh_session_selector()
    
    def _popout(self):
        """Pop Ask Genny out into its own floating window."""
        if getattr(self, '_popout_window', None) and self._popout_window.winfo_exists():
            self._popout_window.lift()
            return

        paned = self.master if isinstance(self.master, ttk.PanedWindow) else None

        top = tk.Toplevel()
        top.title(f"Ask {assistant_name()} — {product_name()}")
        top.geometry("960x700")
        top.configure(bg='#1e1e1e')
        top.protocol("WM_DELETE_WINDOW", lambda: self._dock_back(top, paned))

        # Create a fresh Ask Genny panel inside the Toplevel (popped_out=True hides Pop Out btn)
        panel = AskGennyPanel(top, self.content_area, popped_out=True)
        panel.pack(fill=tk.BOTH, expand=True)

        # Add a Dock Back button to the panel's header
        tk.Button(
            panel.winfo_children()[0],  # header frame (first child)
            text="⬒ Dock Back",
            command=lambda: self._dock_back(top, paned),
            bg=ASK_HEADER_BG, fg=ASK_HEADER_TEXT, font=('Segoe UI', 9),
            relief=tk.FLAT, cursor='hand2',
            activebackground=ASK_HEADER_BG_ACTIVE, activeforeground=ASK_HEADER_TEXT,
            padx=8, pady=0,
        ).pack(side=tk.LEFT, padx=(0, 4))

        # Collapse bottom pane in main window
        if paned:
            try:
                paned.forget(self)
            except Exception:
                pass

        self._popout_window = top
        self._popout_panel = panel
        self._popout_paned = paned

    def _dock_back(self, top, paned):
        """Dock the assistant panel back into the main window."""
        # Grab any draft text from the popped-out panel BEFORE destroying it
        if self._popout_panel:
            try:
                popped_draft = self._popout_panel.input_text.get('1.0', tk.END).strip()
                if popped_draft:
                    # Write immediately so the docked panel can recover the current draft.
                    self._write_draft_snapshot(popped_draft)
                    # Also inject directly into the docked panel input
                    self.input_text.delete('1.0', tk.END)
                    self.input_text.insert('1.0', popped_draft)
            except Exception:
                pass

        try:
            top.destroy()
        except Exception:
            pass

        # Re-add self to PanedWindow
        if paned:
            try:
                paned.add(self, weight=2)
            except Exception:
                pass

        self._popout_window = None
        self._popout_panel = None
        self._popout_paned = None
        # Return focus to input so user can keep typing immediately
        try:
            self.input_text.focus_set()
            self.input_text.mark_set(tk.INSERT, tk.END)
        except Exception:
            pass

    def _show_welcome(self):
        """Show welcome message (only if no history restored)."""
        welcome = f"""## [*] {assistant_name()} AI Agent

I'm your AI SRE assistant. Ask me anything, or build your platform:

- `create a widget to configure and test API keys for PagerDuty, Datadog, and AWS`
- `create a service health monitor widget`
- `create an alert manager widget`
- `create a Kubernetes pod status widget`
- `create a log tail widget`

Generated widgets will appear as tabs above. **Shift+Enter** for newline, **Enter** to send.
"""
        self.response.append_markdown(welcome)
    
    def _on_enter(self, event):
        """Handle Enter key — send only when not processing."""
        if not event.state & 0x1:  # No Shift modifier
            if self.ask_btn['state'] == tk.DISABLED:
                return 'break'  # absorb Enter, allow typing but not sending
            self._on_ask()
            return 'break'
    
    def _on_ask(self):
        """Send prompt to the configured CLI."""
        prompt = self.input_text.get('1.0', tk.END).strip()
        if not prompt:
            return

        # Guard: never start a new request while one is already processing.
        # Unlocking the copilot session mid-stream corrupts events.jsonl.
        if self._process is not None and self._process.poll() is None:
            self.response.append_markdown(
                "**⏳ Still processing previous request — please wait.**\n"
            )
            return
        
        # Save prompt to history immediately
        self._save_to_history('user', prompt)
        # Tag in shared chat_history.jsonl so watcher knows this came from the panel
        self._write_chat_history('user', prompt, source='panel')
        self._begin_live_response(prompt)
        
        # Clear input and draft
        self._last_prompt = prompt  # save for post-response footer
        self.input_text.delete('1.0', tk.END)
        self._clear_draft()
        
        # Show user prompt
        self.response.append_raw('\n')
        self.response.append_markdown(f"### 💬 You\n{prompt}\n")
        self.response.append_raw('\n')
        
        # Check if auger exists
        if not Path(self._auger).exists():
            self.response.append_markdown(
                f"**⚠️  {cli_name()} CLI not found at:** `{self._auger}`\n\n"
                "Install it or update the path in `ui/ask_genny.py`.\n"
            )
            return
        
        # Handle /help inline — no daemon or copilot call needed
        if prompt.strip().lower().startswith('/help'):
            self.response.append_markdown(self._SLASH_HELP)
            return

        # Check for slash command — route to daemon
        daemon_action = self._detect_host_intent(prompt)
        self._cancel_requested = False
        self._active_request_mode = None
        self._cancel_supported = False
        self.status_label.config(text="Processing...")
        if daemon_action:
            self._set_processing()
            if daemon_action in ('restart_auger', 'rebuild_auger'):
                note = f"[{product_name()} lifecycle] Requested {daemon_action.replace('_', ' ')}"
                self._save_to_history('system', note)
                self._append_status_note(note, kind='lifecycle')
                self._write_chat_history('system', note, source='panel')
            thread = threading.Thread(
                target=self._run_via_daemon, args=(prompt, daemon_action), daemon=True)
            thread.start()
            return

        # Route through host daemon so copilot runs as the host user (who owns
        # ~/.copilot/session-state/). Falls back to local auger CLI if daemon is down.
        self._active_request_mode = 'daemon'
        self._cancel_supported = True
        self._set_processing()
        thread = threading.Thread(target=self._run_via_ask_daemon, args=(prompt,), daemon=True)
        thread.start()
    
    def _auger_env(self):
        """Build subprocess env: current env + tokens loaded from the runtime env file."""
        env = os.environ.copy()
        env_file = state_dir() / ".env"
        if env_file.exists():
            for key, val in dotenv_values(env_file).items():
                if val is not None:
                    env.setdefault(key, val)  # don't override vars already in env
        # Ensure the token is exposed under the name auger CLI recognises
        for token_key in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "GHE_TOKEN"):
            if token_key in env and env[token_key]:
                # Propagate under all names auger CLI checks
                for alias in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
                    env.setdefault(alias, env[token_key])
                break
        # Tell cli.py this subprocess was spawned by the panel — so it tags
        # chat_history entries as 'panel' and the watcher skips them (no duplicate).
        env['AUGER_CHAT_SOURCE'] = 'panel'
        env['AUGER_ASK_PROVIDER'] = self._effective_provider()
        env['AUGER_COPILOT_MODEL'] = self._effective_model()
        env['AUGER_COPILOT_SESSION_MODE'] = str(self._selected_session_target.get('mode') or 'pinned')
        env.pop('AUGER_COPILOT_SESSION_ID', None)
        env.pop('AUGER_COPILOT_SESSION_NAME', None)
        if self._selected_session_target.get('mode') == 'session':
            session_id = str(self._selected_session_target.get('session_id') or '').strip()
            if session_id:
                env['AUGER_COPILOT_SESSION_ID'] = session_id
        elif self._selected_session_target.get('mode') == 'new':
            session_name = self._clean_session_name(self._selected_session_target.get('name', ''))
            if session_name:
                env['AUGER_COPILOT_SESSION_NAME'] = session_name
        return env

    def _run_via_ask_daemon(self, prompt: str):
        """Send prompt to host daemon /ask endpoint (runs copilot as host user).

        The host user owns ~/.copilot/session-state/ so --resume and session
        pinning work correctly. Falls back to local auger CLI if daemon is down.
        """
        import urllib.request, urllib.error, json as _json

        daemon_endpoint = f'{daemon_url()}/ask'
        response_lines = []
        try:
            req = urllib.request.Request(
                daemon_endpoint,
                data=_json.dumps({
                    'prompt': prompt,
                    'source': 'container',
                    'provider': self._effective_provider(),
                    'model': self._effective_model(),
                    'session_target': dict(self._selected_session_target),
                }).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            # Bypass corporate proxy for localhost (http_proxy=127.0.0.1:9000 is set)
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=300) as resp:
                for raw_line in resp:
                    try:
                        line_str = raw_line.decode('utf-8', errors='replace').strip()
                        if not line_str:
                            continue
                        entry = _json.loads(line_str)
                        msg_type = entry.get('type', '')
                        msg = entry.get('message', '')
                        if msg_type == 'output' and msg:
                            response_lines.append(msg)
                            self._queue.put(('line', msg + '\n'))
                        elif msg_type == 'chunk' and msg:
                            response_lines.append(msg)
                            self._queue.put(('chunk', msg))
                        elif msg_type == 'progress':
                            pass  # suppress internal progress messages from panel
                        elif msg_type == 'done':
                            self._queue.put(('session_meta', entry))
                            full = '\n'.join(response_lines)
                            self._save_to_history('assistant', full)
                            self._check_for_widget_code(full)
                            self._clear_pending_response()
                            self._queue.put(('done', None))
                            return
                        elif msg_type == 'cancelled':
                            self._queue.put(('cancelled', msg or 'Request cancelled'))
                            return
                        elif msg_type == 'error':
                            self._queue.put(('error', msg or 'Daemon returned error'))
                            return
                    except Exception:
                        pass
        except urllib.error.URLError:
            # Daemon not reachable — fall back to local auger CLI
            if self._effective_provider() != PROVIDER_COPILOT:
                self._queue.put(('error', 'Host daemon is unavailable. Start PlatformGen host tools to use OpenAI or Ollama providers.'))
                return
            augmented_prompt = self._behavior_preamble() + prompt
            self._active_request_mode = 'local'
            self._cancel_supported = True
            self._run_auger(augmented_prompt, on_complete=self._post_local_session_result)
            return
        except Exception as e:
            self._queue.put(('error', str(e)))
        self._queue.put(('done', None))

    def _run_auger(self, prompt, on_complete=None):
        try:
            # Start process with token env vars from the runtime .env
            self._process = subprocess.Popen(
                [self._auger, prompt],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=self._auger_env(),
            )
            
            response_lines = []
            
            # Stream output
            for line in self._process.stdout:
                # Strip ANSI codes
                clean_line = re.sub(r'\x1b\[[0-9;]*[mK]', '', line)
                response_lines.append(clean_line)
                
                # Queue for UI update
                self._queue.put(('line', clean_line))
            
            self._process.wait()
            rc = self._process.returncode
            
            # Check for widget code in response
            full_response = ''.join(response_lines)
            if self._cancel_requested:
                self._queue.put(('cancelled', 'Request cancelled — lock released normally'))
            elif rc == 0 or full_response:
                self._check_for_widget_code(full_response)
                
                # Save response to history
                self._save_to_history('assistant', full_response)
                self._clear_pending_response()
                
                # Done — pass optional callback so caller can react
                self._queue.put(('done', on_complete))
            else:
                self._queue.put(('error', 'Ask Genny request exited without a response'))
        
        except Exception as e:
            if self._cancel_requested:
                self._queue.put(('cancelled', 'Request cancelled — lock released normally'))
            else:
                self._queue.put(('error', str(e)))
        finally:
            self._process = None
    
    def _check_for_widget_code(self, response):
        """Check if response contains a widget class definition, file path, or SQL."""
        # Look for Python code blocks with tk.Frame
        pattern = r'```python\s*(.*?)```'
        matches = re.findall(pattern, response, re.DOTALL)

        for code in matches:
            if 'tk.Frame' in code and 'class ' in code:
                # Extract class/widget name for branch naming
                name_match = re.search(r'class\s+(\w+)', code)
                widget_name = name_match.group(1) if name_match else 'new_widget'
                self._queue.put(('widget', (code, widget_name)))
                break

        # Detect SQL code blocks — route only the SQL to the database widget
        sql_pat = r'```(?:sql|postgresql|pgsql|mysql|sqlite)\s*(.*?)```'
        sql_matches = re.findall(sql_pat, response, re.DOTALL | re.IGNORECASE)
        if sql_matches:
            self._queue.put(('sql', sql_matches[-1].strip()))

        # Also detect explicit "created file" / "saved to" messages referencing widgets dir
        file_pat = re.search(
            r'(?:created?|saved?|wrote?|written)\s+(?:to\s+)?'
            r'[`"\']?([^\s`"\']+/widgets/[^\s`"\']+\.py)[`"\']?',
            response, re.IGNORECASE
        )
        if file_pat:
            self._queue.put(('widget_file', file_pat.group(1)))
    
    def _start_queue_poll(self):
        """Start polling the queue for updates."""
        self._poll_queue()
    
    def _poll_queue(self):
        """Poll queue for messages from background thread."""
        try:
            while True:
                msg_type, data = self._queue.get_nowait()
                
                if msg_type == 'line':
                    self.response.append_markdown(data)
                    self._track_live_response_chunk(data)

                elif msg_type == 'chunk':
                    self.response.append_raw(data)
                    self._track_live_response_chunk(data)
                
                elif msg_type == 'error':
                    self.response.append_markdown(f"**❌ Error:** {data}\n")
                    self._save_pending_response_note(f"[Error before completion]\n{data}")
                    self.status_label.config(text="Error")
                    self._set_ready(check_lock=True)

                elif msg_type == 'cancel_error':
                    self.response.append_markdown(f"**⚠️ Cancel failed:** {data}\n")
                    self.status_label.config(text="Processing...")
                    self._cancel_requested = False
                    if self._cancel_supported:
                        self._cancel_btn.config(state=tk.NORMAL, text='Stop')

                elif msg_type == 'cancelled':
                    self.response.append_markdown(f"*{data}*\n")
                    self._clear_pending_response()
                    self._set_ready(check_lock=True)
                    self.status_label.config(text="Cancelled")
                
                elif msg_type == 'done':
                    self.status_label.config(text="Ready")
                    self._set_ready(check_lock=True)
                    self._append_prompt_footer()
                    self._clear_pending_response()
                    if data:  # on_complete callback
                        data()

                elif msg_type == 'session_meta':
                    self._apply_session_result(data)
                
                elif msg_type == 'widget':
                    code, widget_name = data if isinstance(data, tuple) else (data, 'new_widget')
                    self._offer_load_widget(code, widget_name)

                elif msg_type == 'widget_file':
                    self._offer_commit_widget(Path(data))

                elif msg_type == 'sql':
                    self._send_sql_to_database(data)
        
        except queue.Empty:
            pass
        
        # Poll again in 80ms
        self.after(80, self._poll_queue)

    def _append_prompt_footer(self):
        """After response completes, show original prompt (scrolls off screen otherwise)."""
        if not self._last_prompt:
            return
        original = self._last_prompt.strip()
        self.response.append_raw('\n')
        self.response.append_markdown(
            f"---\n"
            f"📝 **Your prompt:** {original}\n"
        )
        self._last_prompt = ''

    def _offer_to_load_widget(self, code, widget_name):
        """Offer to load generated widget code and commit it to a feature branch."""
        response = messagebox.askyesno(
            "Widget Generated",
            "Genny generated a widget. Load it now?",
            icon=messagebox.QUESTION
        )

        if response:
            self.content_area.load_widget_from_code(code)

        # Also offer to save + commit to a feature branch
        if _GIT_WORKFLOW_AVAILABLE and get_auger_repo():
            branch = make_branch_name(widget_name)
            commit = messagebox.askyesno(
                "Commit Widget",
                f"Commit this widget to a feature branch?\n\n"
                f"Branch: {branch}\n\n"
                f"(You can open a PR from there when ready)",
                icon=messagebox.QUESTION
            )
            if commit:
                self._commit_widget_code(code, widget_name)

    def _commit_widget_code(self, code: str, widget_name: str):
        """Save widget code to file and run handle_widget_change in background."""
        repo = get_auger_repo()
        if not repo:
            return
        widget_file = repo / "auger" / "ui" / "widgets" / f"{widget_name.lower()}.py"
        try:
            widget_file.write_text(code)
        except Exception as e:
            self.response.append_markdown(f"\n**⚠️  Could not save widget:** {e}\n")
            return

        def _do_commit():
            result = handle_widget_change(widget_file)
            msg = result.get("message", "Unknown result")
            self._queue.put(('line', f"\n**🌿 Git:** {msg}\n"))
            self._queue.put(('done', None))

        threading.Thread(target=_do_commit, daemon=True).start()

    def _offer_commit_widget(self, widget_path: Path):
        """Offer to commit an existing widget file that Copilot wrote to disk."""
        if not _GIT_WORKFLOW_AVAILABLE or not get_auger_repo():
            return
        widget_path = widget_path.expanduser()
        # If path doesn't exist as-is, try resolving against repo widgets dir
        if not widget_path.exists():
            repo = get_auger_repo()
            if repo:
                widget_path = repo / "auger" / "ui" / "widgets" / widget_path.name
        if not widget_path.exists():
            return  # silently skip — file doesn't exist, nothing to commit
        # Skip if file is already clean in git (already committed by us)
        try:
            repo = get_auger_repo()
            if repo:
                import subprocess as _sp
                result = _sp.run(
                    ["git", "-C", str(repo), "status", "--porcelain", str(widget_path)],
                    capture_output=True, text=True
                )
                if not result.stdout.strip():
                    return  # already committed, nothing to offer
        except Exception:
            pass
        branch = make_branch_name(widget_path.stem)
        commit = messagebox.askyesno(
            "Commit Widget",
            f"Copilot created:\n  {widget_path.name}\n\n"
            f"Commit to feature branch?\n  {branch}",
            icon=messagebox.QUESTION
        )
        if commit:
            def _do_commit():
                result = handle_widget_change(widget_path)
                msg = result.get("message", "Unknown result")
                self._queue.put(('line', f"\n**🌿 Git:** {msg}\n"))
                self._queue.put(('done', None))
            threading.Thread(target=_do_commit, daemon=True).start()

    def _send_sql_to_database(self, sql: str):
        """Push extracted SQL into the Database widget query editor."""
        db_widget = None
        for key, info in self.content_area._tabs.items():
            w = info.get('widget')
            if w and hasattr(w, 'set_query'):
                db_widget = w
                try:
                    self.content_area.select(info['frame'])
                except Exception:
                    pass
                break
        if db_widget:
            db_widget.set_query(sql)
        else:
            self.response.append_markdown(
                "\n> 💡 *Open the **Database** widget and paste the SQL above.*\n"
            )

    def _on_clear(self):
        """Clear the response area."""
        if messagebox.askyesno("Clear", "Clear entire conversation history?"):
            self.response.clear()
            self._show_welcome()

    # ------------------------------------------------------------------ #
    #  Self-initialization — runs once on first launch after install      #
    # ------------------------------------------------------------------ #

    _PURPOSE_FLAG = state_dir() / ".purpose_initialized"
    _BEHAVIOR_FLAG = state_dir() / ".behavior_initialized"

    def _maybe_self_initialize(self):
        """Check if auger has already been initialized with its origin context."""
        if self._PURPOSE_FLAG.exists():
            # Still run behavior init if not done yet (e.g. upgrading from older install)
            if not self._BEHAVIOR_FLAG.exists():
                self.after(500, self._behavior_initialize)
            return
        bootstrap = self._find_bootstrap_prompt()
        if not bootstrap:
            return
        self._self_initialize(bootstrap)

    def _find_bootstrap_prompt(self):
        """Locate BOOTSTRAP_PROMPT.md — works for pip install and Docker."""
        candidates = [
            # Installed as package data: auger/data/origin/
            Path(__file__).parent.parent / "data" / "origin" / "BOOTSTRAP_PROMPT.md",
            # Docker / dev: repo root docs/origin/
            Path(__file__).parent.parent.parent / "docs" / "origin" / "BOOTSTRAP_PROMPT.md",
        ]
        for p in candidates:
            if p.exists():
                return p.read_text(encoding="utf-8")
        return None

    def _find_behavior_doc(self):
        """Locate AUGER_BEHAVIOR.md — works for pip install and Docker."""
        candidates = [
            Path(__file__).parent.parent / "data" / "origin" / "AUGER_BEHAVIOR.md",
            Path(__file__).parent.parent.parent / "docs" / "origin" / "AUGER_BEHAVIOR.md",
        ]
        for p in candidates:
            if p.exists():
                return p.read_text(encoding="utf-8")
        return None

    def _load_rcs_context(self) -> str:
        """Load rules, conventions, and widget manifests into a compact context string."""
        import yaml
        lines = []
        for fname, label in [("rules.yaml", "RULES"), ("conventions.yaml", "CONVENTIONS")]:
            for base in [
                Path(__file__).parent.parent / "data" / "origin" / fname,
                state_dir() / fname,
            ]:
                if base.exists():
                    try:
                        data = yaml.safe_load(base.read_text()) or {}
                        key = fname.replace(".yaml", "")
                        items = data.get(key, [])
                        if items:
                            lines.append(f"[{label}]")
                            for item in items:
                                enforcement = item.get("enforcement", "")
                                enf_str = f" [{enforcement.upper()}]" if enforcement else ""
                                rule_text = (item.get("rule") or item.get("pattern") or item.get("description") or "").strip()[:200]
                                lines.append(f"- {item.get('name','')}{enf_str}: {rule_text}")
                            lines.append("")
                    except Exception:
                        pass

        # Widget AI Manifests — inject compact widget knowledge block
        try:
            from auger.ui.widget_manifest import build_manifest_context
            manifest_block = build_manifest_context()
            if manifest_block:
                lines.append(manifest_block)
        except Exception:
            pass

        return "\n".join(lines)

    def _behavior_preamble(self):
        """Return compact preamble injected before every user prompt."""
        base_preamble = (
            "[PLATFORM CONTEXT — always active]\n"
            f"You are the {assistant_name()} AI Agent embedded in {product_name()}.\n"
            f"Tasks DB: {state_dir() / 'tasks.db'} (table: tasks, cols: id,title,description,status,priority,category,created_at,updated_at). "
            "Status: pending/in_progress/done/blocked. Priority: low/medium/high/critical.\n"
            "BEHAVIOR: When ideas, action items, or planned work come up, proactively offer to add them as tasks. "
            "Insert via Python sqlite3. Tasks widget auto-refreshes every 5s.\n"
            "Deployment = Flux config PR merge (never kubectl for FCS/prod). "
            "Widget changes use hot-reload (no restart). Git push uses HTTPS not SSH from container.\n"
            "[END CONTEXT]\n\n"
        )
        rcs = self._load_rcs_context()
        if rcs:
            base_preamble += f"\n{rcs}"
        return base_preamble

    def _self_initialize(self, bootstrap_text):
        """Fire a self-training prompt so the assistant internalizes its purpose."""
        behavior = self._find_behavior_doc() or ""
        prompt = (
            "[PLATFORM SELF-INITIALIZATION — READ CAREFULLY]\n\n"
            f"You are the {assistant_name()} AI Agent, the embedded AI assistant inside "
            f"{product_name()}. This is your first run on this installation. "
            "Below is the complete architectural specification and origin story "
            "of the platform you are embedded in, followed by your behavioral guidelines. "
            "Please read both, internalize your purpose and the key design decisions, "
            "then respond with a brief acknowledgment (3-5 sentences) confirming:\n"
            f"1. What {product_name()} is and who it is for\n"
            "2. Your role as the embedded AI agent\n"
            "3. The most important architectural constraint you must always respect\n"
            "4. How you will proactively help users capture tasks\n\n"
            "--- ORIGIN DOCUMENTATION ---\n\n"
            + bootstrap_text
            + "\n\n--- END ORIGIN DOCUMENTATION ---\n\n"
            "--- BEHAVIORAL GUIDELINES ---\n\n"
            + behavior
            + "\n\n--- END BEHAVIORAL GUIDELINES ---"
        )

        # Show a subtle notice in the response area
        self.response.append_raw("\n")
        self.response.append_markdown(
            "---\n"
            "### [INIT] First-Run Initialization\n"
            f"*{assistant_name()} is reading its origin documentation and behavioral guidelines...*\n"
        )
        self.response.append_raw("\n")

        # Save a compact note to history (not the full bootstrap text)
        self._save_to_history("system", "[Self-initialization: reading BOOTSTRAP_PROMPT.md + AUGER_BEHAVIOR.md]")

        self.status_label.config(text="Initializing...")
        self._active_request_mode = 'local'
        self._cancel_supported = True
        self._cancel_requested = False
        self._set_processing()
        thread = threading.Thread(
            target=self._run_auger,
            args=(prompt, self._on_init_complete),
            daemon=True,
        )
        thread.start()

    def _behavior_initialize(self):
        """Run behavior-only init for users who already have the bootstrap flag."""
        behavior = self._find_behavior_doc()
        if not behavior:
            return
        prompt = (
            "[AUGER BEHAVIOR UPDATE — READ CAREFULLY]\n\n"
            f"The {product_name()} platform has been updated with new behavioral guidelines. "
            "Please read the following and confirm you understand your new proactive behaviors:\n\n"
            "--- BEHAVIORAL GUIDELINES ---\n\n"
            + behavior
            + "\n\n--- END BEHAVIORAL GUIDELINES ---\n\n"
            "Respond with a 2-3 sentence acknowledgment confirming you understand: "
            "(1) how to proactively capture tasks, and (2) the key platform constraints."
        )
        self.response.append_raw("\n")
        self.response.append_markdown(
            "---\n"
            "### [UPDATE] Behavior Guidelines Update\n"
            f"*{assistant_name()} is loading updated behavioral guidelines...*\n"
        )
        self.response.append_raw("\n")
        self._save_to_history("system", "[Behavior update: reading AUGER_BEHAVIOR.md]")
        self.status_label.config(text="Updating behavior...")
        self._active_request_mode = 'local'
        self._cancel_supported = True
        self._cancel_requested = False
        self._set_processing()
        thread = threading.Thread(
            target=self._run_auger,
            args=(prompt, self._on_behavior_init_complete),
            daemon=True,
        )
        thread.start()

    def _on_init_complete(self):
        """Called after the self-init auger response completes."""
        self._PURPOSE_FLAG.parent.mkdir(parents=True, exist_ok=True)
        self._PURPOSE_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
        self._BEHAVIOR_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
        self.response.append_markdown(
            f"\n[OK] *{assistant_name()} has been initialized. This will not run again on this installation.*\n---\n"
        )

    def _on_behavior_init_complete(self):
        """Called after behavior-only init completes."""
        self._BEHAVIOR_FLAG.parent.mkdir(parents=True, exist_ok=True)
        self._BEHAVIOR_FLAG.write_text(datetime.now().isoformat(), encoding="utf-8")
        self.response.append_markdown(
            "\n[OK] *Behavioral guidelines loaded.*\n---\n"
        )
    
    def set_prompt(self, text):
        """Set the input prompt (used by menu items)."""
        self.input_text.delete('1.0', tk.END)
        self.input_text.insert('1.0', text)
        self.input_text.focus_set()
    
    def _save_to_history(self, role, content):
        """Save message to persistent history file (JSONL format)."""
        try:
            entry = {
                'timestamp': datetime.now().isoformat(),
                'role': role,
                'content': content
            }
            with open(self._history_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            print(f"Failed to save history: {e}")

    def _append_status_note(self, note, kind='info'):
        """Persist a restart-safe work-status note shown on the next launch."""
        try:
            entry = {
                'timestamp': datetime.now().isoformat(),
                'kind': kind,
                'content': note,
            }
            with open(self._status_file, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
        except Exception as e:
            print(f"Failed to save status note: {e}")

    def _restore_status_notes(self):
        """Restore recent restart-safe work-status notes."""
        try:
            if not self._status_file.exists():
                return
            cutoff = datetime.now() - timedelta(days=2)
            notes = []
            with open(self._status_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        ts = datetime.fromisoformat(entry['timestamp'])
                        if ts >= cutoff:
                            notes.append(entry)
                    except Exception:
                        continue
            if not notes:
                return
            self.response.append_markdown("### [STATUS] Recent Work Notes\n\n", scroll=False)
            for note in notes[-12:]:
                ts = note.get('timestamp', '')
                content = (note.get('content') or '').strip()
                if not content:
                    continue
                self.response.append_markdown(f"- `{ts}` {content}\n", scroll=False)
            self.response.append_markdown("\n---\n\n", scroll=False)
        except Exception as e:
            print(f"Failed to restore status notes: {e}")

    def _begin_live_response(self, prompt):
        self._live_response_chunks = []
        self._live_response_prompt = prompt
        self._save_pending_response()

    def _track_live_response_chunk(self, chunk):
        if not self._live_response_prompt:
            return
        self._live_response_chunks.append(chunk)
        self._save_pending_response()

    def _save_pending_response_note(self, note):
        if not self._live_response_prompt:
            return
        self._live_response_chunks.append(f"\n{note}\n")
        self._save_pending_response()

    def _save_pending_response(self):
        try:
            payload = {
                'timestamp': datetime.now().isoformat(),
                'product': product_name(),
                'assistant': assistant_name(),
                'prompt': self._live_response_prompt,
                'content': ''.join(self._live_response_chunks).strip(),
            }
            self._pending_response_file.write_text(json.dumps(payload), encoding='utf-8')
        except Exception as e:
            print(f"Failed to save pending response: {e}")

    def _clear_pending_response(self):
        self._live_response_chunks = []
        self._live_response_prompt = ""
        try:
            if self._pending_response_file.exists():
                self._pending_response_file.unlink()
        except Exception as e:
            print(f"Failed to clear pending response: {e}")

    def _restore_pending_response(self):
        try:
            if not self._pending_response_file.exists():
                return
            payload = json.loads(self._pending_response_file.read_text(encoding='utf-8'))
            prompt = (payload.get('prompt') or '').strip()
            content = (payload.get('content') or '').strip()
            timestamp = (payload.get('timestamp') or '').strip()
            if not prompt and not content:
                return
            self.response.append_markdown("### [RECOVERED] In-Progress Reply From Before Restart\n\n", scroll=False)
            if prompt:
                self.response.append_raw('\n', scroll=False)
                self.response.append_markdown(f"### [YOU]\n{prompt}\n", scroll=False)
                self.response.append_raw('\n', scroll=False)
            if content:
                self.response.append_markdown(content + "\n", scroll=False)
                self.response.append_raw('\n', scroll=False)
            if timestamp:
                self.response.append_markdown(f"*Recovered from pending response saved at {timestamp}*\n\n", scroll=False)
            self.response.append_markdown("---\n\n", scroll=False)
            self.response.see(tk.END)
        except Exception as e:
            print(f"Failed to restore pending response: {e}")
    
    def _restore_history(self):
        """Restore last 2 days of chat history on startup.
        
        Note: Only displays recent history for performance, but the complete
        history is preserved in the JSONL file and never deleted.
        """
        try:
            if not self._history_file.exists():
                self._restore_status_notes()
                self._restore_pending_response()
                return
            cutoff = datetime.now() - timedelta(days=2)
            restored_messages = []
            
            with open(self._history_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        msg_time = datetime.fromisoformat(entry['timestamp'])
                        
                        if msg_time >= cutoff:
                            restored_messages.append(entry)
                    except:
                        continue
            
            if restored_messages:
                self.response.append_markdown("### [RESTORED] Chat History (Last 2 Days)\n\n", scroll=False)

                for msg in restored_messages[-60:]:
                    content = msg['content']

                    if msg['role'] == 'user':
                        self.response.append_raw('\n', scroll=False)
                        self.response.append_markdown(f"### [YOU]\n{content}\n", scroll=False)
                        self.response.append_raw('\n', scroll=False)
                    else:
                        self.response.append_markdown(f"### [{assistant_name().upper()}]\n{content}\n", scroll=False)
                        self.response.append_raw('\n', scroll=False)

                self.response.append_markdown("\n---\n\n", scroll=False)
                # Scroll to bottom once after all history is loaded
                self.response.see(tk.END)
            self._restore_status_notes()
            self._restore_pending_response()
                
        except Exception as e:
            print(f"Failed to restore history: {e}")
    
    def _strip_emoji(self, text):
        """Remove emoji characters that cause segfaults."""
        import re
        # Remove emoji and other special Unicode characters
        emoji_pattern = re.compile("["
            u"\U0001F600-\U0001F64F"  # emoticons
            u"\U0001F300-\U0001F5FF"  # symbols & pictographs
            u"\U0001F680-\U0001F6FF"  # transport & map symbols
            u"\U0001F1E0-\U0001F1FF"  # flags (iOS)
            u"\U00002702-\U000027B0"
            u"\U000024C2-\U0001F251"
            "]+", flags=re.UNICODE)
        return emoji_pattern.sub('', text)
    
    def _start_auto_save(self):
        """Start auto-saving draft text."""
        self._save_draft()
    
    def _write_draft_snapshot(self, draft: str, saved_at: str | None = None):
        draft = (draft or '').strip()
        if not draft:
            self._clear_draft()
            return
        timestamp = saved_at or datetime.now().isoformat()
        payload = {
            'text': draft,
            'saved_at': timestamp,
        }
        self._draft_file.write_text(json.dumps(payload), encoding='utf-8')
        self._draft_cache_text = draft
        self._draft_saved_at = timestamp
        try:
            if self._legacy_draft_file.exists():
                self._legacy_draft_file.unlink()
        except Exception:
            pass

    def _read_saved_draft(self):
        if self._draft_file.exists():
            try:
                payload = json.loads(self._draft_file.read_text(encoding='utf-8'))
                if isinstance(payload, dict):
                    draft = str(payload.get('text') or '').strip()
                    saved_at = str(payload.get('saved_at') or '').strip()
                    if draft:
                        return draft, saved_at
            except Exception:
                pass

        if self._legacy_draft_file.exists():
            try:
                draft = self._legacy_draft_file.read_text(encoding='utf-8').strip()
            except Exception:
                draft = ''
            if draft:
                return draft, ''
        return '', ''

    def _should_restore_draft(self, saved_at: str) -> bool:
        if not saved_at:
            return False
        try:
            age = datetime.now() - datetime.fromisoformat(saved_at)
        except Exception:
            return False
        return age <= timedelta(hours=8)

    def _save_draft(self):
        """Save current input text as draft (auto-save every 3 seconds)."""
        try:
            draft = self.input_text.get('1.0', tk.END).strip()
            if draft:
                if draft != self._draft_cache_text:
                    self._write_draft_snapshot(draft)
            else:
                self._clear_draft()
        except Exception as e:
            print(f"Failed to save draft: {e}")
        
        # Schedule next auto-save
        self._auto_save_id = self.after(3000, self._save_draft)
    
    def _restore_draft(self):
        """Restore draft text on startup."""
        try:
            draft, saved_at = self._read_saved_draft()
            if not draft:
                return
            if not self._should_restore_draft(saved_at):
                self._clear_draft()
                return
            self.input_text.insert('1.0', draft)
            self._draft_cache_text = draft
            self._draft_saved_at = saved_at
            self.status_label.config(text="Draft restored")
            self.after(3000, lambda: self.status_label.config(text=""))
        except Exception as e:
            print(f"Failed to restore draft: {e}")
    
    def _clear_draft(self):
        """Clear saved draft file."""
        try:
            if self._draft_file.exists():
                self._draft_file.unlink()
            if self._legacy_draft_file.exists():
                self._legacy_draft_file.unlink()
            self._draft_cache_text = ""
            self._draft_saved_at = None
        except Exception as e:
            print(f"Failed to clear draft: {e}")

    # ------------------------------------------------------------------ #
    #  Shared chat history watcher (Option 5.2)                          #
    #  Polls the runtime chat_history.jsonl for entries from other sources #
    #  (terminal, host daemon, container) and mirrors them in the panel  #
    # ------------------------------------------------------------------ #

    _SOURCE_LABELS = {
        'terminal': '💻 Host Terminal',
        'host':     '🖥️  Host',
        'daemon':   '🖥️  Host Daemon',
        'container':'📦 Container',
    }

    def _write_chat_history(self, role: str, content: str, source: str = 'panel'):
        """Append an entry to the shared runtime chat_history.jsonl."""
        import time as _time
        try:
            self._chat_history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._chat_history_file, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps({
                    'ts': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
                    'role': role, 'content': content, 'source': source
                }) + '\n')
        except Exception as e:
            print(f"Failed to write chat history: {e}")

    def _start_chat_history_watcher(self):
        """Initialise offset to current EOF so we only show NEW entries."""
        try:
            if self._chat_history_file.exists():
                self._chat_history_offset = self._chat_history_file.stat().st_size
            else:
                self._chat_history_offset = 0
        except Exception:
            self._chat_history_offset = 0
        self._poll_chat_history()

    def _poll_chat_history(self):
        """Poll shared chat_history.jsonl every 1s for external entries."""
        try:
            if self._chat_history_file.exists():
                size = self._chat_history_file.stat().st_size
                if size > self._chat_history_offset:
                    with open(self._chat_history_file, 'r', encoding='utf-8', errors='replace') as fh:
                        fh.seek(self._chat_history_offset)
                        new_text = fh.read()
                        self._chat_history_offset = fh.tell()
                    for raw in new_text.splitlines():
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            entry = json.loads(raw)
                        except Exception:
                            continue
                        source = entry.get('source', '')
                        # Skip our own panel entries — already shown directly
                        if source in ('panel', 'container'):
                            continue
                        role = entry.get('role', 'user')
                        content = entry.get('content', '').strip()
                        if not content:
                            continue
                        label = self._SOURCE_LABELS.get(source, f'🔗 {source}')
                        if role == 'user':
                            self.response.append_raw('\n')
                            self.response.append_markdown(
                                f"### {label}\n{content}\n"
                            )
                            self.response.append_raw('\n')
                        else:
                            self.response.append_raw('\n')
                            self.response.append_markdown(
                                f"*— {label} response —*\n\n{content}\n"
                            )
                            self.response.append_raw('\n')
                        self.response.see(tk.END)
        except Exception as e:
            print(f"Chat history watcher error: {e}")
        self.after(1000, self._poll_chat_history)

    # ── Session health monitor ────────────────────────────────────────────────

    def _start_session_health_poll(self):
        """Start polling daemon /session_status for lock and freshness state."""
        self._poll_session_health()

    def _poll_session_health(self):
        """Check lock status + last response age via daemon, update header indicator."""
        import urllib.request, json as _json
        def _fetch():
            try:
                with urllib.request.urlopen(
                    'http://localhost:7437/session_status', timeout=3
                ) as r:
                    return _json.loads(r.read())
            except Exception:
                return None

        def _run():
            data = _fetch()
            # Use after(0) to schedule UI update on main thread — NOT self._queue
            # (which expects (msg_type, data) tuples and would break on a lambda)
            try:
                self.after(0, lambda: self._apply_session_health(data))
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()
        self.after(SESSION_HEALTH_POLL_MS, self._poll_session_health)

    def _apply_session_health(self, data):
        """Update header age label and remote lock state from session_status."""
        if data is None:
            return

        if not provider_supports_copilot_sessions(self._effective_provider()):
            self._session_locked = False
            self._session_locked_secs = 0
            self._session_last_ts = data.get('last_response_ts')
            self._session_age_label.config(text='')
            if not self._is_processing:
                self._apply_lock_state(False, locked_secs=0)
            return

        self._session_locked = bool(data.get('locked', False))
        self._session_locked_secs = int(data.get('locked_secs') or 0)
        self._session_last_ts = data.get('last_response_ts')

        if self._session_locked:
            lock_age = self._format_lock_age(self._session_locked_secs)
            age_str = f'lock {lock_age}' if lock_age else 'locked'
        else:
            age_str = ''
        self._session_age_label.config(text=age_str)

        if not self._is_processing:
            self._apply_lock_state(self._session_locked, locked_secs=self._session_locked_secs)

    def _format_lock_age(self, seconds: int) -> str:
        try:
            secs = max(0, int(seconds))
        except Exception:
            return ''
        if secs < 60:
            return f'{secs}s'
        if secs < 3600:
            return f'{secs // 60}m'
        return f'{secs // 3600}h'

    def _force_unlock_session(self):
        """Force-clear the Copilot session lock after user confirmation."""
        if not provider_supports_copilot_sessions(self._effective_provider()):
            return
        from tkinter import messagebox
        if not messagebox.askyesno(
            'Unlock Session',
            'Force-clear the Copilot session lock?\n\n'
            'Use this only for a stale or orphaned lock.\n'
            'For a live request, use Stop instead so the process can exit cleanly.',
            icon='warning'
        ):
            return
        import urllib.request, json as _json
        def _do():
            try:
                data = _json.dumps({'action': 'unlock_session'}).encode()
                req = urllib.request.Request(
                    'http://localhost:7437/cmd',
                    data=data,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=5):
                    pass
            except Exception:
                pass
            try:
                self.after(0, self._poll_session_health)
            except Exception:
                pass
        threading.Thread(target=_do, daemon=True).start()
        self.status_label.config(text='Unlocking session...')
        self._lock_dot.config(fg=ASK_HEADER_ACCENT)
        try:
            self._unlock_btn.pack_forget()
        except Exception:
            pass

    def _cancel_request(self):
        if not self._cancel_supported or self._cancel_requested:
            return
        self._cancel_requested = True
        self.status_label.config(text='Cancelling...')
        try:
            self._cancel_btn.config(state=tk.DISABLED, text='Stopping...')
        except Exception:
            pass

        if self._active_request_mode == 'daemon':
            threading.Thread(target=self._cancel_daemon_request, daemon=True).start()
        elif self._active_request_mode == 'local':
            threading.Thread(target=self._cancel_local_request, daemon=True).start()

    def _cancel_daemon_request(self):
        import urllib.request, json as _json
        try:
            req = urllib.request.Request(
                'http://localhost:7437/cmd',
                data=_json.dumps({'action': 'cancel_ask'}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=10) as resp:
                result = _json.loads(resp.read().decode('utf-8', errors='replace'))
        except Exception as exc:
            self._queue.put(('cancel_error', str(exc)))
            return

        if result.get('status') != 'ok':
            self._queue.put(('cancel_error', result.get('message') or 'Daemon cancel failed'))

    def _cancel_local_request(self):
        proc = self._process
        if not proc or proc.poll() is not None:
            return
        try:
            proc.send_signal(signal.SIGINT)
            proc.wait(timeout=3)
            return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            self._queue.put(('cancel_error', 'Could not send SIGINT to local Ask Genny process'))
            return

        try:
            proc.terminate()
            proc.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass
        except Exception:
            self._queue.put(('cancel_error', 'Could not send SIGTERM to local Ask Genny process'))
            return

        try:
            proc.kill()
            proc.wait(timeout=1)
        except Exception as exc:
            self._queue.put(('cancel_error', f'Could not stop local Ask Genny process: {exc}'))

    # ── Processing state helpers ──────────────────────────────────────────────

    def _set_processing(self):
        """Disable send button, start pulsating dot, and show Stop when supported."""
        self.ask_btn.config(state=tk.DISABLED)
        self._provider_combo.config(state='disabled')
        self._model_combo.config(state='disabled')
        self._session_combo.config(state='disabled')
        self._new_session_btn.config(state=tk.DISABLED)
        self._rename_session_btn.config(state=tk.DISABLED)
        self._is_processing = True
        try:
            self._unlock_btn.pack_forget()
        except Exception:
            pass
        try:
            if self._cancel_supported:
                self._cancel_btn.config(state=tk.NORMAL, text='Stop')
                self._cancel_btn.pack(side=tk.RIGHT, padx=(0, 4))
            else:
                self._cancel_btn.pack_forget()
        except Exception:
            pass
        self._pulse_dot()

    def _set_ready(self, check_lock: bool = False):
        """Re-enable send button and stop pulsating dot.
        If check_lock=True, verify daemon lock is cleared — go red if stuck."""
        self.ask_btn.config(state=tk.NORMAL)
        self._provider_combo.config(state='readonly')
        self._model_combo.config(state='readonly')
        self._session_combo.config(state='readonly')
        self._new_session_btn.config(state=tk.NORMAL)
        self._rename_session_btn.config(state=tk.NORMAL)
        self._refresh_session_selector()
        self._is_processing = False
        self._cancel_requested = False
        self._cancel_supported = False
        self._active_request_mode = None
        self._process = None
        try:
            self._cancel_btn.pack_forget()
        except Exception:
            pass
        if check_lock:
            def _verify():
                import urllib.request, json as _j
                try:
                    with urllib.request.urlopen(
                        'http://localhost:7437/session_status', timeout=3
                    ) as r:
                        data = _j.loads(r.read())
                    locked = data.get('locked', False)
                    locked_secs = int(data.get('locked_secs') or 0)
                except Exception:
                    locked = False
                    locked_secs = 0
                self.after(
                    0,
                    lambda: self._apply_lock_state(
                        locked,
                        locked_secs=locked_secs,
                        force_unlock=locked,
                    ),
                )
            threading.Thread(target=_verify, daemon=True).start()
        else:
            self._lock_dot.config(fg=ASK_HEADER_ACCENT)
        self._refresh_provider_health_ui()

    def _apply_lock_state(self, locked: bool, locked_secs: int = 0, force_unlock: bool = False):
        """Apply final lock state after processing completes or on restart."""
        if not provider_supports_copilot_sessions(self._effective_provider()):
            self._lock_dot.config(fg=ASK_HEADER_ACCENT_ACTIVE)
            try:
                self._unlock_btn.pack_forget()
            except Exception:
                pass
            if self.status_label.cget('text') in ('Session locked — click Unlock', 'Session busy...', 'Unlocking session...'):
                self.status_label.config(text='Ready')
            return
        if locked and (force_unlock or locked_secs >= SESSION_LOCK_STALE_SECS):
            self._lock_dot.config(fg='#f85149')   # red — stale/stuck
            try:
                self._unlock_btn.pack(side=tk.RIGHT, padx=(0, 4))
            except Exception:
                pass
            self.status_label.config(text='Session locked — click Unlock')
        elif locked:
            self._lock_dot.config(fg='#d29922')   # yellow — active elsewhere
            try:
                self._unlock_btn.pack_forget()
            except Exception:
                pass
            self.status_label.config(text='Session busy...')
        else:
            self._lock_dot.config(fg=ASK_HEADER_ACCENT)   # green — healthy
            try:
                self._unlock_btn.pack_forget()
            except Exception:
                pass
            if self.status_label.cget('text') in ('Session locked — click Unlock', 'Session busy...', 'Unlocking session...'):
                self.status_label.config(text='Ready')

    def _pulse_dot(self):
        """Animate dot between two greens while processing."""
        if not getattr(self, '_is_processing', False):
            self._lock_dot.config(fg=ASK_HEADER_ACCENT)   # settle to solid green
            return
        current = self._lock_dot.cget('fg')
        next_color = ASK_HEADER_ACCENT_ACTIVE if current == ASK_HEADER_ACCENT else ASK_HEADER_ACCENT
        self._lock_dot.config(fg=next_color)
        self.after(600, self._pulse_dot)
    # Slash commands — must start at position 0 of the prompt.
    # Natural language phrases no longer trigger daemon actions to prevent
    # accidental routing (e.g. "restart platform" in a normal sentence).
    _SLASH_COMMANDS = {
        '/reinit':   'reinit_session',
        '/restart':  'restart_auger',
        '/rebuild':  'rebuild_auger',
    }

    _SLASH_HELP = """*Ask Genny Slash Commands* (must be the first character of your message)

`/reinit`   — Clear the pinned session for the current provider/model lane
`/restart`  — Restart the PlatformGen container (same as relaunch)
`/rebuild`  — Rebuild the personalized Docker image and restart
`/help`     — Show this command reference

All other messages are sent directly to the selected provider as normal prompts.
"""

    def _detect_host_intent(self, prompt: str) -> str:
        """Return daemon action name only if prompt starts with a known slash command."""
        stripped = prompt.strip()
        first_word = stripped.split()[0].lower() if stripped else ''
        return self._SLASH_COMMANDS.get(first_word, '')

    def _run_via_daemon(self, prompt: str, action: str):
        """Forward a host-scope request to the daemon and stream response."""
        import urllib.request, urllib.error
        daemon_url = f'http://localhost:7437/{action.replace("_auger", "")}'
        self._queue.put(('line', f'*Routing to host daemon: `{action}`*\n'))
        try:
            req = urllib.request.Request(
                daemon_url,
                data=__import__('json').dumps({
                    'prompt': prompt,
                    'source': 'container',
                    'provider': self._effective_provider(),
                    'model': self._effective_model(),
                }).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            # Bypass corporate proxy for localhost (http_proxy=127.0.0.1:9000 is set)
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            with opener.open(req, timeout=300) as resp:
                for raw_line in resp:
                    try:
                        entry = __import__('json').loads(raw_line.decode('utf-8', errors='replace').strip())
                        msg = entry.get('message', '')
                        if msg:
                            self._queue.put(('line', msg + '\n'))
                        if entry.get('type') == 'done':
                            self._queue.put(('done', None))
                            return
                        if entry.get('type') == 'error':
                            self._queue.put(('error', msg))
                            return
                    except Exception:
                        pass
        except urllib.error.URLError as e:
            self._queue.put(('error',
                f'Daemon not reachable at {daemon_url}: {e}\n'
                'Is the host daemon running? (check localhost:7437/health)'))
        except Exception as e:
            # For restart/rebuild, a dropped connection IS success — the container
            # was killed before it could send the final "done" response.
            err_str = str(e).lower()
            if action in ('restart_auger', 'rebuild_auger') and (
                    'remote end closed' in err_str or 'connection' in err_str):
                self._queue.put(('line', f'✅ {product_name()} restarted — reconnecting…\n'))
            else:
                self._queue.put(('error', str(e)))
        self._queue.put(('done', None))

    # ── Voice input (push-to-talk) ────────────────────────────────────────────

    def _on_mic_press(self, event=None):
        """Start recording when mic button is pressed."""
        if self._mic_recording:
            return
        self._mic_recording = True
        self._mic_btn.config(bg='#c0392b', fg='white', text='REC ')
        self.status_label.config(text='Listening...')
        threading.Thread(target=self._mic_start, daemon=True).start()

    def _on_mic_release(self, event=None):
        """Stop recording and transcribe when mic button is released."""
        if not self._mic_recording:
            return
        self._mic_recording = False
        self._mic_btn.config(bg='#3c3c3c', fg='#a0a0a0', text='[MIC]')
        self.status_label.config(text='Transcribing...')
        threading.Thread(target=self._mic_stop, daemon=True).start()

    def _mic_start(self):
        import urllib.request, urllib.error, json as _json
        try:
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            req = urllib.request.Request(
                'http://localhost:7437/listen',
                data=_json.dumps({'action': 'start'}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            opener.open(req, timeout=5)
        except Exception as e:
            self.after(0, lambda: self.status_label.config(text=f'Mic error: {e}'))
            self.after(0, lambda: self._mic_btn.config(
                bg='#3c3c3c', fg='#a0a0a0', text='[MIC]'))
            self._mic_recording = False

    def _mic_stop(self):
        import urllib.request, urllib.error, json as _json
        try:
            proxy_handler = urllib.request.ProxyHandler({})
            opener = urllib.request.build_opener(proxy_handler)
            req = urllib.request.Request(
                'http://localhost:7437/listen',
                data=_json.dumps({'action': 'stop'}).encode(),
                headers={'Content-Type': 'application/json'},
                method='POST'
            )
            with opener.open(req, timeout=30) as resp:
                result = _json.loads(resp.read().decode())
            transcript = result.get('transcript', '').strip()
            err = result.get('message', '')
            if transcript:
                self.after(0, lambda t=transcript: self._insert_transcript(t))
                self.after(0, lambda: self.status_label.config(text=''))
            else:
                msg = err or 'No speech detected'
                self.after(0, lambda m=msg: self.status_label.config(text=m))
                self.after(3000, lambda: self.status_label.config(text=''))
        except Exception as e:
            self.after(0, lambda: self.status_label.config(text=f'Transcription error: {e}'))
            self.after(4000, lambda: self.status_label.config(text=''))

    def _insert_transcript(self, text: str):
        """Insert transcribed text into the prompt input field."""
        current = self.input_text.get('1.0', tk.END).strip()
        if current:
            self.input_text.insert(tk.END, ' ' + text)
        else:
            self.input_text.insert('1.0', text)
        self.input_text.see(tk.END)
        self.input_text.focus_set()

    def _attach_file(self):
        import datetime
        path = filedialog.askopenfilename(
            title='Attach file to Ask Genny',
            filetypes=[
                ('Text / data files', '*.txt *.log *.json *.yaml *.yml *.csv *.md *.py *.sh'),
                ('All files', '*.*'),
            ]
        )
        if not path:
            return
        p = Path(path)
        try:
            content = p.read_text(errors='replace')
        except Exception as e:
            self.input_text.insert('insert', f'[Could not read file: {e}]')
            return
        if len(content) > 4000:
            paste_dir = state_dir() / 'pastes'
            paste_dir.mkdir(exist_ok=True)
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            dest = paste_dir / f'{p.stem}_{ts}{p.suffix}'
            dest.write_text(content)
            self.input_text.insert('insert', f'@file:{dest}\n')
        else:
            self.input_text.insert('insert', f'--- {p.name} ---\n{content}\n---\n')
        self.input_text.focus_set()

    def _on_paste(self, event=None):
        """Handle paste event. Large pastes go to the runtime pastes dir to avoid
        locking up the Tk Text widget — inserts @file: reference instead."""
        import datetime
        try:
            from auger import IN_DOCKER
            clipboard = self.clipboard_get()
        except Exception:
            return None
        if len(clipboard) > 4000:
            paste_dir = state_dir() / 'pastes'
            paste_dir.mkdir(exist_ok=True)
            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            dest = paste_dir / f'paste_{ts}.txt'
            dest.write_text(clipboard)
            self.input_text.insert('insert', f'@file:{dest}\n')
            return 'break'
        self.input_text.insert('insert', clipboard)
        return 'break'


AskAugerPanel = AskGennyPanel

__all__ = ["AskGennyPanel", "AskAugerPanel"]
