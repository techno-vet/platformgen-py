#!/usr/bin/env python3
"""
Runtime-configurable platform CLI.

Dual-mode behavior:
- With subcommands: platformgen init, platformgen start, etc.
- Without subcommands: platformgen "question" (quick ask mode)
"""

import os
import sys
import click
from pathlib import Path
from auger.ai.provider_sessions import (
    clear_copilot_pinned_session_id,
    copilot_pin_path,
    read_copilot_pinned_session_id,
    write_copilot_pinned_session_id,
)
from auger.utils.file_lock import acquire_file_lock, ensure_lock_file, release_file_lock
from platformgen.runtime import app_name, assistant_name, cli_name, product_name, repo_dir, state_dir

WINDOWS_HIDDEN_PROCESS = 0x08000000 if os.name == "nt" else 0


# ── Session Snapshot (Layer 1 + 2) ────────────────────────────────────────────

def _write_session_snapshot(user_prompt: str, response_lines: list) -> None:
    """Write the runtime session snapshot after every copilot call.

    Captures: git state, top active tasks, last 10 chat turns.
    Used by _build_context_preamble() to inject context into the next call.
    """
    import json, time, subprocess, sqlite3
    snap: dict = {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}

    # Git state
    try:
        for candidate in [repo_dir(), Path.cwd()]:
            if not candidate:
                continue
            candidate = Path(candidate)
            if (candidate / '.git').exists():
                branch = subprocess.check_output(
                    ['git', '-C', str(candidate), 'branch', '--show-current'],
                    stderr=subprocess.DEVNULL, text=True).strip()
                head = subprocess.check_output(
                    ['git', '-C', str(candidate), 'log', '--oneline', '-1'],
                    stderr=subprocess.DEVNULL, text=True).strip()
                snap['git_branch'] = branch
                snap['git_head'] = head
                snap['git_repo'] = str(candidate)
                break
    except Exception:
        pass

    # Top 10 active tasks from tasks.db
    try:
        db = state_dir() / 'tasks.db'
        if db.exists():
            conn = sqlite3.connect(str(db))
            rows = conn.execute(
                "SELECT id,title,status,priority FROM tasks "
                "WHERE status NOT IN ('done','Done','blocked') "
                "ORDER BY CASE priority "
                "  WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'High' THEN 1 "
                "  WHEN 'medium' THEN 2 WHEN 'Medium' THEN 2 ELSE 3 END, "
                "updated_at DESC LIMIT 10"
            ).fetchall()
            conn.close()
            snap['active_tasks'] = [
                {'id': r[0], 'title': r[1], 'status': r[2], 'priority': r[3]}
                for r in rows
            ]
    except Exception:
        pass

    # Last 10 chat turns (compact: 300 chars each)
    try:
        hist = state_dir() / 'chat_history.jsonl'
        if hist.exists():
            import json as _j
            turns = []
            for raw in hist.read_text().splitlines()[-20:]:
                try:
                    obj = _j.loads(raw)
                    turns.append({
                        'ts': obj.get('ts', ''),
                        'role': obj.get('role', ''),
                        'content': obj.get('content', '')[:300],
                    })
                except Exception:
                    pass
            snap['last_turns'] = turns[-10:]
    except Exception:
        pass

    snap['last_user_prompt'] = user_prompt[:300]

    try:
        snap_path = state_dir() / '.session_snapshot.json'
        snap_path.write_text(json.dumps(snap, indent=2))
    except Exception:
        pass


def _load_behavior_doc() -> str:
    """Return the contents of AUGER_BEHAVIOR.md (persona + rules doc).

    Searched in order: installed package data, repo source tree, home repos.
    Returns empty string if not found.
    """
    candidates = [
        Path(__file__).parent / 'data' / 'origin' / 'AUGER_BEHAVIOR.md',
    ]
    repo = repo_dir()
    if repo:
        candidates.extend([
            repo / 'auger' / 'data' / 'origin' / 'AUGER_BEHAVIOR.md',
            repo / 'platformgen' / 'data' / 'origin' / 'AUGER_BEHAVIOR.md',
        ])
    for p in candidates:
        if p.exists():
            try:
                return p.read_text().strip()
            except Exception:
                pass
    return ''


def _build_context_preamble() -> str:
    """Return a context preamble to inject before every copilot prompt.

    - If the runtime session snapshot exists and is < 48h old: return
      compact snapshot (branch, tasks, last turns).
    - Otherwise (first run or long idle): return AUGER_BEHAVIOR.md as a
      cold-start orientation so Genny is self-aware from day one.
    """
    import json
    snap_path = state_dir() / '.session_snapshot.json'

    snap = None
    if snap_path.exists():
        try:
            snap = json.loads(snap_path.read_text())
            ts = snap.get('ts', '')
            if ts:
                from datetime import datetime, timezone
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(ts.replace('Z', '+00:00'))
                       ).total_seconds()
                if age > 172800:
                    snap = None  # stale — fall through to cold-start
        except Exception:
            snap = None

    # Cold-start: no snapshot or stale — inject persona doc
    if snap is None:
        behavior = _load_behavior_doc()
        if behavior:
            return (
                '[AUGER COLD-START ORIENTATION — injected on first run / long idle]\n'
                + behavior
                + '\n[END ORIENTATION — respond to the user message below]\n\n'
            )
        return ''

    # Warm start: build compact snapshot preamble
    try:
        parts = ['[AUGER SESSION SNAPSHOT — auto-injected for context continuity]']
        if snap.get('git_branch'):
            head_sha = (snap.get('git_head') or '').split()[0]
            parts.append(f"Branch: {snap['git_branch']} @ {head_sha}")
        tasks = snap.get('active_tasks', [])
        if tasks:
            top = ' | '.join(
                f"#{t['id']} {t['title'][:45]} ({t['status']})"
                for t in tasks[:5]
            )
            parts.append(f"Active tasks: {top}")
        last_prompt = snap.get('last_user_prompt', '')
        if last_prompt:
            parts.append(f"Last user msg: {last_prompt[:200]}")
        turns = snap.get('last_turns', [])
        if turns:
            recent = '\n'.join(
                f"  [{t['role']}]: {t['content'][:120]}"
                for t in turns[-3:]
            )
            parts.append(f"Recent context:\n{recent}")
        parts.append('[END SNAPSHOT — respond to the user message below]')
        return '\n'.join(parts) + '\n\n'
    except Exception:
        return ''


# ── Ask functionality ──────────────────────────────────────────────────────────

# Helper function for ask functionality
def run_copilot_ask(prompt_text=None):
    """Run gh copilot or show GUI"""
    import subprocess
    
    def run_copilot(prompt):
        """Run standalone copilot CLI with the given prompt"""
        import os
        from pathlib import Path

        # Build env, loading the runtime .env if it exists
        env = os.environ.copy()
        env_file = state_dir() / '.env'
        if env_file.exists():
            try:
                from dotenv import dotenv_values
                for k, v in dotenv_values(env_file).items():
                    if v and k not in env:
                        env[k] = v
            except Exception:
                pass

        # Ensure ~/.local/bin is in PATH for copilot CLI and other user tools
        local_bin = str(Path.home() / '.local' / 'bin')
        current_path = env.get('PATH', '')
        if local_bin not in current_path:
            env['PATH'] = f"{local_bin}:{current_path}" if current_path else local_bin

        # Ensure all copilot token env vars point to a real token
        token = (env.get('COPILOT_GITHUB_TOKEN') or
                 env.get('GH_TOKEN') or
                 env.get('GITHUB_TOKEN') or
                 env.get('GITHUB_COPILOT_TOKEN'))
        if token:
            env['COPILOT_GITHUB_TOKEN'] = token
            env['GH_TOKEN'] = token
            env['GITHUB_TOKEN'] = token

        # Acquire exclusive lockfile so concurrent auger calls never write to
        # the same copilot session simultaneously (prevents events.jsonl corruption)
        import json as _json_health
        lock_path = state_dir() / '.copilot.lock'
        ensure_lock_file(lock_path)
        lock_meta_path = lock_path.with_suffix(lock_path.suffix + '.json')

        def _write_lock_metadata():
            payload = {'acquired_at': _time.time(), 'pid': os.getpid()}
            try:
                lock_meta_path.write_text(_json.dumps(payload))
                lock_meta_path.chmod(0o666)
            except Exception:
                pass

        def _clear_lock_metadata():
            try:
                lock_meta_path.unlink()
            except FileNotFoundError:
                pass
            except Exception:
                pass
        selected_provider = (env.get('AUGER_ASK_PROVIDER') or 'copilot').strip().lower() or 'copilot'
        selected_model = (env.get('AUGER_COPILOT_MODEL') or 'auto').strip() or 'auto'
        if selected_provider != 'copilot':
            click.echo(f'Ask {assistant_name()} local fallback only supports the Copilot provider right now.')
            import sys as _sys_provider
            _sys_provider.exit(1)
        session_id_file = copilot_pin_path(selected_model)
        pinned_session_id = read_copilot_pinned_session_id(selected_model) or None
        model_args = ['--model', selected_model] if selected_model.lower() != 'auto' else []
        requested_mode = (env.get('AUGER_COPILOT_SESSION_MODE') or 'pinned').strip().lower()
        requested_session_id = (env.get('AUGER_COPILOT_SESSION_ID') or '').strip()
        requested_session_name = (env.get('AUGER_COPILOT_SESSION_NAME') or '').strip()
        name_args = ['--name', requested_session_name] if requested_session_name else []

        def _session_is_corrupt(candidate_id: str) -> bool:
            if not candidate_id:
                return False
            events_path = Path.home() / '.copilot' / 'session-state' / candidate_id / 'events.jsonl'
            try:
                _events_exist = events_path.exists()
            except PermissionError:
                _events_exist = True
            if not _events_exist:
                return False
            try:
                lines = events_path.read_text().splitlines()
                for raw_line in lines[-30:]:
                    try:
                        evt = _json_health.loads(raw_line)
                        etype = evt.get('type', '')
                        edata = evt.get('data', {})
                        corrupt = (
                            (etype == 'session.error' and
                             ('retried 5 times' in edata.get('message', '') or
                              'Failed to get response' in edata.get('message', '')))
                            or
                            (etype == 'session.compaction_complete' and
                             not edata.get('success', True))
                        )
                        if corrupt:
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
            return False

        if requested_mode == 'session' and requested_session_id:
            session_id = requested_session_id
            session_mode = 'session'
            session_args = ['--resume', session_id]
        elif requested_mode == 'new':
            import uuid as _uuid

            session_id = str(_uuid.uuid4())
            session_mode = 'new'
            session_args = [f'--session-id={session_id}']
        else:
            session_id = pinned_session_id
            session_mode = 'pinned'
            session_args = ['--resume', session_id] if session_id else ['--continue']

        if session_mode == 'pinned' and session_id and _session_is_corrupt(session_id):
            clear_copilot_pinned_session_id(selected_model)
            session_id = None
            session_args = ['--continue']
            print(
                '[WARN] Corrupt pinned session detected - starting fresh session',
                flush=True
            )
        elif session_mode == 'session' and session_id and _session_is_corrupt(session_id):
            import uuid as _uuid

            session_id = str(_uuid.uuid4())
            session_mode = 'new'
            session_args = [f'--session-id={session_id}']
            print(
                '[WARN] Selected session is unhealthy - switching this request to a fresh session',
                flush=True
            )

        # Record prompt in shared chat history.
        # Source priority: AUGER_CHAT_SOURCE env var (set by panel subprocess) >
        # Docker detection ('container') > host terminal ('terminal').
        # Watcher skips 'panel' and 'container' — only shows 'terminal' entries.
        import time as _time, json as _json, re as _re
        _in_docker = Path('/.dockerenv').exists()
        _source = os.environ.get('AUGER_CHAT_SOURCE') or ('container' if _in_docker else 'terminal')
        chat_history = state_dir() / 'chat_history.jsonl'
        chat_history.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(chat_history, 'a') as _hf:
                _hf.write(_json.dumps({
                    'ts': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
                    'role': 'user', 'content': prompt, 'source': _source
                }) + '\n')
        except Exception:
            pass

        # Layer 2: prepend session snapshot preamble so a new/resumed session
        # immediately has context (branch, active tasks, recent conversation).
        # The original `prompt` is still what gets written to chat_history above.
        _preamble = _build_context_preamble()
        _enriched_prompt = _preamble + prompt if _preamble else prompt

        try:
            with open(lock_path, 'r+' if lock_path.exists() else 'w') as lock_fh:
                # Non-blocking: fail fast if another invocation is processing.
                # Prevents unlocking mid-stream and corrupting events.jsonl.
                try:
                    acquire_file_lock(lock_fh, blocking=False)
                    _write_lock_metadata()
                except BlockingIOError:
                    click.echo(
                        f'Another Ask {assistant_name()} request is already processing. '
                        'Wait for it to finish before sending a new prompt. '
                        f'(If this is stale, remove {state_dir() / ".copilot.lock"})'
                    )
                    import sys as _sys2; _sys2.exit(1)
                try:
                    # Stream output to terminal AND capture for chat_history.jsonl
                    run_name_args = [] if '--resume' in session_args or any(arg.startswith('--session-id=') for arg in session_args) else name_args
                    popen_kwargs = {}
                    if WINDOWS_HIDDEN_PROCESS:
                        popen_kwargs['creationflags'] = WINDOWS_HIDDEN_PROCESS
                    proc = subprocess.Popen(
                        ["copilot"] + model_args + run_name_args + ["-p", _enriched_prompt, "--allow-all"] + session_args,
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        env=env,
                        **popen_kwargs,
                    )
                    _STATS_PREFIXES = (
                        'Total usage est:', 'API time spent:', 'Total session time:',
                        'Total code changes:', 'Breakdown by AI model:',
                    )
                    def _stream_proc(p, lines_out):
                        for raw in p.stdout:
                            clean = _re.sub(rb'\x1b\[[0-9;]*[mK]', b'', raw).decode('utf-8', errors='replace')
                            stripped = clean.strip()
                            is_stats = (any(stripped.startswith(s) for s in _STATS_PREFIXES)
                                        or _re.match(r' +claude-| +gpt-', clean))
                            if not is_stats:
                                sys.stdout.buffer.write(raw)
                                sys.stdout.buffer.flush()
                            lines_out.append(clean)
                        p.wait()

                    response_lines = []
                    _stream_proc(proc, response_lines)
                    _final_rc = proc.returncode

                    # ── CAPIError/session auto-recovery ──────────────────────
                    # There are two common failure modes:
                    # 1) OAuth cache/auth drift (hosts.json) -> retry same session.
                    # 2) Corrupt pinned transcript (tool_use without tool_result)
                    #    -> clear pin once, retry with fresh --continue, then repin.
                    _full_out = ''.join(response_lines)
                    _lower_out = _full_out.lower()

                    _has_400 = bool(_re.search(r'CAPIError.*400|400.*Bad Request', _full_out, _re.IGNORECASE))
                    _session_protocol_markers = (
                        'tool_use ids were found without tool_result',
                        'each tool_use block must have a corresponding tool_result block',
                        'invalid_request_error',
                    )
                    _is_protocol_corruption = any(m in _lower_out for m in _session_protocol_markers)
                    _generic_error_markers = (
                        'failed to get response',
                        '400 bad request',
                        '400 bad_request',
                    )
                    _should_recover = _has_400 or any(m in _lower_out for m in _generic_error_markers)

                    if _should_recover:
                        if _is_protocol_corruption and session_mode == 'pinned' and session_id:
                            # Keep a forensic copy of the bad pin and start fresh once.
                            try:
                                import time as _time_recover
                                bad_pin = session_id_file.with_name(f'{session_id_file.stem}.bad-{int(_time_recover.time())}{session_id_file.suffix}')
                                session_id_file.rename(bad_pin)
                            except Exception:
                                try:
                                    clear_copilot_pinned_session_id(selected_model)
                                except Exception:
                                    pass
                            session_id = None
                            session_args = ["--continue"]
                            print(
                                '\n[WARN] Copilot session transcript mismatch detected '
                                '(tool_use/tool_result sequence error).\n'
                                '       Cleared pinned session and retrying once with a fresh session; '
                                'context is preserved via snapshot preamble.',
                                flush=True
                            )
                        elif session_mode in ('session', 'new'):
                            import uuid as _uuid

                            session_id = str(_uuid.uuid4())
                            session_mode = 'new'
                            session_args = [f'--session-id={session_id}']
                            print(
                                '\n[WARN] Ask Genny session error detected - retrying once with a fresh non-pinned session.',
                                flush=True
                            )
                        elif _has_400:
                            _hosts_json = Path.home() / '.config' / 'github-copilot' / 'hosts.json'
                            _cleared = False
                            try:
                                if _hosts_json.exists():
                                    _hosts_json.unlink()
                                    _cleared = True
                            except Exception:
                                pass
                            print(
                                '\n[WARN] CAPIError 400 - retrying Copilot call. '
                                + ('Cleared hosts.json first.' if _cleared else 'hosts.json not changed.'),
                                flush=True
                            )

                        response_lines = []
                        run_name_args = [] if '--resume' in session_args or any(arg.startswith('--session-id=') for arg in session_args) else name_args
                        proc2 = subprocess.Popen(
                            ["copilot"] + model_args + run_name_args + ["-p", _enriched_prompt, "--allow-all"] + session_args,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            env=env,
                            **popen_kwargs,
                        )
                        _stream_proc(proc2, response_lines)
                        _final_rc = proc2.returncode
                        _full_out = ''.join(response_lines)
                        _lower_out = _full_out.lower()

                        if _re.search(r'CAPIError.*400|400.*Bad Request', _full_out, _re.IGNORECASE):
                            print(
                                '\n[ERROR] Copilot still failing after auto-retry.\n'
                                '        Run this once in a terminal, then retry your prompt:\n'
                                '          copilot auth login\n'
                                f'        Session pin file: {copilot_pin_path(selected_model)}',
                                flush=True
                            )
                        elif any(m in _lower_out for m in _session_protocol_markers):
                            print(
                                '\n[ERROR] Copilot session is still returning tool protocol errors after retry.\n'
                                '        Use the recovery helper to rebuild a clean session:\n'
                                '          python3 scripts/recover_copilot_session.py',
                                flush=True
                            )

                    # Pin latest session after each successful response only when
                    # Ask Genny is using the pinned-session path.
                    if _final_rc == 0:
                        try:
                            session_state_dir = Path.home() / '.copilot' / 'session-state'
                            if session_state_dir.exists():
                                dirs = sorted(
                                    (e for e in session_state_dir.iterdir() if e.is_dir()),
                                    key=lambda p: p.stat().st_mtime,
                                    reverse=True,
                                )
                                if dirs and session_mode == 'pinned':
                                    write_copilot_pinned_session_id(selected_model, dirs[0].name)
                        except Exception:
                            pass
                    # ── end auto-recovery ────────────────────────────────────

                    # Layer 1: write session snapshot for context recovery
                    _write_session_snapshot(prompt, response_lines)
                    # Write response to shared chat history
                    try:
                        with open(chat_history, 'a') as _hf:
                            _hf.write(_json.dumps({
                                'ts': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime()),
                                'role': 'assistant',
                                'content': ''.join(response_lines).strip(),
                                'source': _source
                            }) + '\n')
                    except Exception:
                        pass
                finally:
                    _clear_lock_metadata()
                    release_file_lock(lock_fh)
        except FileNotFoundError:
            click.echo("Error: 'copilot' command not found")
            click.echo("\nPlease install standalone Copilot CLI:")
            click.echo("  curl -fsSL https://gh.io/copilot-install | bash")
            click.echo("\nOr with Homebrew:")
            click.echo("  brew install copilot-cli")
            sys.exit(1)
    
    def show_gui():
        """Show GUI prompt window"""
        import tkinter as tk
        from tkinter import scrolledtext
        
        root = tk.Tk()
        root.title(f"{assistant_name()} - Ask Copilot")
        root.geometry("600x400")
        
        frame = tk.Frame(root, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        
        tk.Label(frame, text="Enter your prompt:").pack(anchor="w")
        
        text_input = scrolledtext.ScrolledText(frame, wrap=tk.WORD, height=15)
        text_input.pack(fill=tk.BOTH, expand=True, pady=(4, 8))
        text_input.focus()
        
        def on_ask():
            prompt = text_input.get("1.0", tk.END).strip()
            if prompt:
                root.destroy()
                run_copilot(prompt)
        
        def on_enter(event):
            # Ctrl+Enter submits
            if event.state & 0x4:  # Control key
                on_ask()
        
        text_input.bind('<Control-Return>', on_enter)
        
        button_frame = tk.Frame(frame)
        button_frame.pack(anchor="e")
        
        tk.Label(button_frame, text="Tip: Ctrl+Enter to submit", 
                fg="gray", font=("Arial", 9)).pack(side=tk.LEFT, padx=(0, 10))
        tk.Button(button_frame, text="Ask", command=on_ask, width=12).pack(side=tk.RIGHT)
        
        root.mainloop()
    
    # If prompt provided, use it
    if prompt_text:
        run_copilot(prompt_text)
    else:
        # Show GUI
        try:
            show_gui()
        except Exception as e:
            click.echo(f"[ERROR] Error showing GUI: {e}")
            click.echo("\nTry providing prompt directly:")
            click.echo(f'  {cli_name()} "your question here"')
            sys.exit(1)


class PlatformGenGroup(click.Group):
    """Custom Click group that implements dual-mode behavior"""
    
    def invoke(self, ctx):
        # Check if no subcommand was invoked and we have args
        if ctx.invoked_subcommand is None and len(sys.argv) > 1:
            first_arg = sys.argv[1]
            
            # If it's a flag (starts with --) or a known command, let Click handle it
            if first_arg.startswith('--') or first_arg in self.commands:
                return super().invoke(ctx)
            
            # Otherwise, treat everything as an ask prompt
            prompt = " ".join(sys.argv[1:])
            run_copilot_ask(prompt)
            ctx.exit(0)
        
        # Default Click behavior for subcommands
        return super().invoke(ctx)


@click.command(cls=PlatformGenGroup)
@click.version_option(version="0.1.0")
@click.pass_context
def main(ctx):
    """AI-powered SRE tools.
    
    Dual-mode usage:
    
      <cli> init              # CLI mode: Initialize configuration
      <cli> start             # CLI mode: Start GUI
      <cli> "question"        # Ask mode: Quick Copilot query
      <cli>                   # Ask mode: Open GUI prompt
    
    A comprehensive SRE platform with dynamic widgets, AI chat assistant,
    and integrations with DataDog, GitHub, ServiceNow, and more.
    """
    # This gets called by Click's framework
    # The actual routing is handled in PlatformGenGroup.invoke()
    pass


# Wrapper to check for no-args case BEFORE Click processing
def platformgen_main():
    """Entry point that handles no-args case before Click"""
    # Check if ~/.local/bin is in PATH (warn only once per session)
    local_bin = Path.home() / ".local" / "bin"
    if local_bin.exists() and str(local_bin) not in os.environ.get("PATH", ""):
        click.echo("Warning: ~/.local/bin is not in your PATH", err=True)
        click.echo("   Add this to your ~/.bashrc:", err=True)
        click.echo('   export PATH="$HOME/.local/bin:$PATH"', err=True)
        click.echo("", err=True)
    
    # If no args, open GUI directly
    if len(sys.argv) == 1:
        run_copilot_ask()
        sys.exit(0)
    
    # Otherwise, let Click handle it
    main()


def genny_main():
    """Compatibility entry point for the canonical Genny CLI name."""
    platformgen_main()


def cli_main():
    """Legacy Auger CLI compatibility entry point."""
    platformgen_main()


AugerGroup = PlatformGenGroup


@main.command()
@click.option('--token', prompt='GitHub Copilot token (github.com)', 
              help=f'GitHub Copilot token for Ask {assistant_name()}')
@click.option('--config-dir', default=None, 
              help='Custom config directory (default: runtime state dir)')
@click.option('--datadog-api-key', default=None,
              help='DataDog API key (optional, can configure later)')
@click.option('--datadog-app-key', default=None,
              help='DataDog Application key (optional, can configure later)')
def init(token, config_dir, datadog_api_key, datadog_app_key):
    """Initialize platform configuration
    
    Sets up the configuration directory and stores credentials.
    
    IMPORTANT: Use your Copilot token (github.com) for the assistant.
    Enterprise GitHub and other integrations can be configured later
    via the assistant or by editing the runtime .env file.
    
    Priority: get the assistant working first, then configure everything else.
    """
    from auger.config_manager import AugerConfigManager
    
    if not config_dir:
        config_dir = state_dir()
    else:
        config_dir = Path(config_dir)
    
    click.echo(f"Initializing {app_name()} in: {config_dir}")
    
    # Create config manager
    config = AugerConfigManager(config_dir)
    
    # Initialize with GitHub token (required)
    config.init(
        github_token=token,
        datadog_api_key=datadog_api_key,
        datadog_app_key=datadog_app_key
    )
    
    click.echo(f"\n{app_name()} initialized successfully!")
    click.echo(f"Config directory: {config_dir}")
    click.echo(f"📄 Config file: {config_dir / 'config.yaml'}")
    click.echo(f"🔐 Secrets file: {config_dir / '.env'}")
    
    click.echo("\n🚀 Next steps:")
    click.echo(f"  1. Start {app_name()}: {cli_name()} start")
    click.echo(f"  2. Open Ask {assistant_name()} chat panel")
    click.echo("  3. Ask: 'Help me set up DataDog integration'")
    
    if not datadog_api_key:
        click.echo(f"\nTip: You can configure DataDog later by asking {assistant_name()}!")


@main.command()
@click.option('--port', default=6000, help='Web server port (future feature)')
@click.option('--display', default=None, help='X11 DISPLAY (default: current DISPLAY)')
@click.option('--debug', is_flag=True, help='Enable debug mode')
@click.option('--config-dir', default=None, help='Custom config directory')
def start(port, display, debug, config_dir):
    """Start the platform GUI
    
    Launches the runtime-configured platform with all enabled widgets.
    """
    # Set display if specified
    if display:
        os.environ['DISPLAY'] = display
    elif 'DISPLAY' not in os.environ:
        click.echo("[WARN] DISPLAY not set. Using :1")
        os.environ['DISPLAY'] = ':1'
    
    # Check if initialized
    if not config_dir:
        config_dir = state_dir()
    else:
        config_dir = Path(config_dir)
    
    config_file = config_dir / 'config.yaml'
    if not config_file.exists():
        click.echo(f"[ERROR] {app_name()} not initialized!")
        click.echo(f"Run: {cli_name()} init")
        sys.exit(1)
    
    click.echo(f"[INFO] Starting {product_name()}...")
    click.echo(f"[INFO] Config: {config_dir}")
    click.echo(f"[INFO] Display: {os.environ.get('DISPLAY')}")
    
    if debug:
        click.echo("[DEBUG] Debug mode enabled")
        os.environ['AUGER_DEBUG'] = '1'
    
    # Import and run app
    try:
        try:
            from platformgen.app import main as app_main
        except ImportError:
            from auger.app import main as app_main
        app_main()
    except ImportError as e:
        click.echo(f"[ERROR] Error importing app: {e}")
        click.echo("Make sure all dependencies are installed:")
        click.echo("  pip install -e .")
        sys.exit(1)
    except Exception as e:
        click.echo(f"[ERROR] Error starting {app_name()}: {e}")
        if debug:
            import traceback
            traceback.print_exc()
        sys.exit(1)


@main.command()
@click.option('--config-dir', default=None, help='Custom config directory')
def config(config_dir):
    """Show current configuration."""
    from auger.config_manager import AugerConfigManager
    
    if not config_dir:
        config_dir = state_dir()
    else:
        config_dir = Path(config_dir)
    
    config_file = config_dir / 'config.yaml'
    if not config_file.exists():
        click.echo(f"[ERROR] {app_name()} not initialized!")
        click.echo(f"Run: {cli_name()} init")
        sys.exit(1)
    
    click.echo(f"📄 Configuration from: {config_file}")
    click.echo("=" * 70)
    
    with open(config_file, 'r') as f:
        content = f.read()
        # Redact any tokens/keys in output
        import re
        content = re.sub(r'(token|key|password|secret):\s*\S+', r'\1: ****', content, flags=re.IGNORECASE)
        click.echo(content)


@main.command()
@click.argument('integration', type=click.Choice(['github', 'datadog', 'servicenow', 'all']))
@click.option('--config-dir', default=None, help='Custom config directory')
def test(integration, config_dir):
    """Test an integration
    
    Tests connectivity and authentication for the specified integration.
    """
    from auger.config_manager import AugerConfigManager
    
    if not config_dir:
        config_dir = state_dir()
    else:
        config_dir = Path(config_dir)
    
    config = AugerConfigManager(config_dir)
    
    integrations_to_test = []
    if integration == 'all':
        integrations_to_test = ['github', 'datadog', 'servicenow']
    else:
        integrations_to_test = [integration]
    
    results = {}
    
    for integ in integrations_to_test:
        click.echo(f"\n🔍 Testing {integ}...")
        
        try:
            if integ == 'github':
                from auger.integrations.github_integration import test_github
                result = test_github(config)
            elif integ == 'datadog':
                from auger.integrations.datadog_integration import test_datadog
                result = test_datadog(config)
            elif integ == 'servicenow':
                from platformgen.tools.servicenow_session import ServiceNowSession
                sn = ServiceNowSession()
                result = len(sn.scrape_incidents(limit=1)) > 0
            
            results[integ] = result
            
            if result:
                click.echo(f"{integ} integration working!")
            else:
                click.echo(f"[ERROR] {integ} integration failed")
                
        except Exception as e:
            click.echo(f"[ERROR] {integ} test error: {e}")
            results[integ] = False
    
    # Summary
    click.echo("\n" + "=" * 70)
    click.echo("Test Summary:")
    for integ, result in results.items():
        status = "PASS" if result else "FAIL"
        click.echo(f"  {integ:15} {status}")


@main.command()
@click.option('--config-dir', default=None, help='Custom config directory')
def widgets(config_dir):
    """List available widgets
    
    Shows all available widgets and their status.
    """
    from auger.config_manager import AugerConfigManager
    
    if not config_dir:
        config_dir = state_dir()
    else:
        config_dir = Path(config_dir)
    
    config = AugerConfigManager(config_dir)
    
    # Get list of widgets from ui/widgets directory
    widgets_dir = Path(__file__).parent / 'ui' / 'widgets'
    
    click.echo("📦 Available Widgets:")
    click.echo("=" * 70)
    
    widget_files = sorted(widgets_dir.glob('*.py'))
    for widget_file in widget_files:
        if widget_file.name.startswith('_'):
            continue
        
        widget_name = widget_file.stem
        enabled = config.is_widget_enabled(widget_name)
        status = "Enabled" if enabled else "Disabled"
        
        click.echo(f"  {widget_name:30} {status}")
    
    click.echo(f"\nEnable/disable widgets in: {state_dir() / 'config.yaml'}")


@main.command()
@click.option('--config-dir', default=None, help='Custom config directory')
def doctor(config_dir):
    """Run diagnostics on the current installation."""
    if not config_dir:
        config_dir = state_dir()
    else:
        config_dir = Path(config_dir)
    
    click.echo(f"🔍 Running {app_name()} diagnostics...")
    click.echo("=" * 70)
    
    issues = []
    
    # Check Python version
    import sys
    py_version = sys.version_info
    if py_version >= (3, 10):
        click.echo(f"Python version: {py_version.major}.{py_version.minor}")
    else:
        click.echo(f"[ERROR] Python version: {py_version.major}.{py_version.minor} (requires >= 3.10)")
        issues.append("Upgrade to Python 3.10 or higher")
    
    # Check config
    config_file = config_dir / 'config.yaml'
    if config_file.exists():
        click.echo(f"Config file: {config_file}")
    else:
        click.echo(f"[ERROR] Config file not found: {config_file}")
        issues.append(f"Run: {cli_name()} init")
    
    # Check DISPLAY
    if 'DISPLAY' in os.environ:
        click.echo(f"DISPLAY: {os.environ['DISPLAY']}")
    else:
        click.echo("[ERROR] DISPLAY not set")
        issues.append("Set DISPLAY environment variable (e.g., export DISPLAY=:1)")
    
    # Check tkinter
    try:
        import tkinter
        click.echo("tkinter available")
    except ImportError:
        click.echo("[ERROR] tkinter not available")
        issues.append("Install tkinter: apt install python3-tk")
    
    # Check dependencies
    try:
        import requests
        import yaml
        import dotenv
        click.echo("Core dependencies installed")
    except ImportError as e:
        click.echo(f"[ERROR] Missing dependency: {e}")
        issues.append("Install dependencies: pip install -e .")
    
    # Summary
    click.echo("\n" + "=" * 70)
    if issues:
        click.echo("[ERROR] Issues found:")
        for i, issue in enumerate(issues, 1):
            click.echo(f"  {i}. {issue}")
    else:
        click.echo(f"All checks passed. {app_name()} is ready to use.")
    click.echo(f"\nRun: {cli_name()} start")


if __name__ == '__main__':
    platformgen_main()
