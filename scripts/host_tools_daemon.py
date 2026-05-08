#!/usr/bin/env python3
"""
PlatformGen Host Tools HTTP Daemon
Runs on the host machine, accepts JSON commands from the Docker container.

Since the container uses --network host, both host and container share
localhost, so the daemon is reachable at http://localhost:7437 from anywhere.

Usage:
    nohup python3 scripts/host_tools_daemon.py > ~/.platformgen/daemon.log 2>&1 &

Endpoints:
    GET  /health      -> {"status":"ok","port":7437}
    POST /cmd         -> {"action": "...", ...}  -> JSON response or NDJSON stream
    POST /listen      -> {"action": "start"|"stop"} -> voice capture + transcription
"""

import http.server
import socketserver
import json
import os
import sys
import subprocess
import glob as glob_mod
import re
import shlex
import threading
import time
import traceback
import signal
import urllib.error
import urllib.request
from pathlib import Path

from auger.ai.provider_sessions import (
    append_local_turn,
    clear_copilot_pinned_session_id,
    clear_local_pinned_session,
    copilot_pin_path,
    ensure_local_session,
    read_copilot_pinned_session_id,
    read_local_pinned_session_id,
    session_messages,
    write_copilot_pinned_session_id,
)
from auger.ai.providers import (
    PROVIDER_COPILOT,
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    available_models,
    default_model,
    load_runtime_env,
    normalize_model,
    normalize_provider,
    ollama_base_url,
    openai_base_url,
    provider_supports_copilot_sessions,
)

PORT = int(os.environ.get('AUGER_DAEMON_PORT', '7437'))
AUGER_DIR = Path(
    os.environ.get('PLATFORMGEN_HOME')
    or os.environ.get('AUGER_HOME')
    or str(Path.home() / '.platformgen')
).expanduser()
HOST_TOOLS_FILE = AUGER_DIR / 'host_tools.json'
REPO_DIR = Path(__file__).parent.parent  # scripts/../ = repo root
KEEPALIVE_STATE_FILE = AUGER_DIR / 'keepalive_state.json'
APP_NAME = os.environ.get('AUGER_APP_NAME', 'PlatformGen')
KEEPALIVE_REASON = f'Keep Workspace Awake from {APP_NAME} tray'
KEEPALIVE_APP_ID = os.environ.get('AUGER_CLI_NAME', 'genny')
KEEPALIVE_INHIBIT_FLAGS = 'idle:suspend'
KEEPALIVE_LOCK = threading.Lock()
ACTIVE_COPILOT_LOCK = threading.Lock()
ACTIVE_COPILOT: dict[str, object] = {}
STATE_DIR_LABEL = str(AUGER_DIR)
SELENIUM_VENV_DIR = AUGER_DIR / 'sn_venv'


# ── Utility ───────────────────────────────────────────────────────────────────

def _find_bin(*names):
    """Find first available binary, searching /snap/bin and ~/.local/bin too."""
    env_path = f"/snap/bin:{Path.home()}/.local/bin:{os.environ.get('PATH', '')}"
    for name in names:
        if os.path.isfile(name) and os.access(name, os.X_OK):
            return name
        r = subprocess.run(['bash', '-c', f'PATH="{env_path}" command -v "{name}"'],
                           capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    return ''


BROWSER_BIN = _find_bin('google-chrome', 'google-chrome-stable', 'chromium-browser', 'chromium')


def _load_tools() -> dict:
    AUGER_DIR.mkdir(parents=True, exist_ok=True)
    if HOST_TOOLS_FILE.exists():
        try:
            return json.loads(HOST_TOOLS_FILE.read_text())
        except Exception:
            pass
    return {'tools': []}


def _save_tools(data: dict):
    HOST_TOOLS_FILE.write_text(json.dumps(data, indent=2))


def _read_keepalive_state() -> dict:
    AUGER_DIR.mkdir(parents=True, exist_ok=True)
    if KEEPALIVE_STATE_FILE.exists():
        try:
            return json.loads(KEEPALIVE_STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _write_keepalive_state(data: dict):
    AUGER_DIR.mkdir(parents=True, exist_ok=True)
    KEEPALIVE_STATE_FILE.write_text(json.dumps(data, indent=2))


def _clear_keepalive_state():
    try:
        KEEPALIVE_STATE_FILE.unlink()
    except FileNotFoundError:
        pass


def _lock_meta_path(lock_path: Path) -> Path:
    return lock_path.with_suffix(lock_path.suffix + '.json')


def _write_lock_metadata(lock_path: Path, *, pid: int | None = None):
    payload = {
        'acquired_at': time.time(),
        'pid': pid or os.getpid(),
    }
    try:
        meta_path = _lock_meta_path(lock_path)
        meta_path.write_text(json.dumps(payload))
        os.chmod(meta_path, 0o666)
    except Exception:
        pass


def _clear_lock_metadata(lock_path: Path):
    try:
        _lock_meta_path(lock_path).unlink()
    except FileNotFoundError:
        pass
    except Exception:
        pass


def _register_active_copilot(
    process: subprocess.Popen | None,
    *,
    request_id: str,
    prompt: str,
    session_mode: str,
    session_id: str | None,
    model: str,
    provider: str,
) -> dict[str, object]:
    state: dict[str, object] = {
        'request_id': request_id,
        'process': process,
        'pid': process.pid if process else 0,
        'prompt': prompt[:200],
        'session_mode': session_mode,
        'session_id': session_id or '',
        'model': model,
        'provider': provider,
        'started_at': time.time(),
        'cancel_requested': False,
    }
    with ACTIVE_COPILOT_LOCK:
        ACTIVE_COPILOT.clear()
        ACTIVE_COPILOT.update(state)
        return ACTIVE_COPILOT


def _active_copilot_snapshot() -> dict[str, object]:
    with ACTIVE_COPILOT_LOCK:
        if not ACTIVE_COPILOT:
            return {}
        proc = ACTIVE_COPILOT.get('process')
        if proc is None:
            active = True
        else:
            active = bool(getattr(proc, 'poll', lambda: 0)() is None)
        return {
            key: value
            for key, value in ACTIVE_COPILOT.items()
            if key != 'process'
        } | {'active': active}


def _clear_active_copilot(request_id: str | None = None):
    with ACTIVE_COPILOT_LOCK:
        if request_id and ACTIVE_COPILOT.get('request_id') != request_id:
            return
        ACTIVE_COPILOT.clear()


def _interrupt_process_gracefully(proc: subprocess.Popen) -> str:
    steps = (
        (signal.SIGINT, 3),
        (signal.SIGTERM, 2),
        (signal.SIGKILL, 1),
    )
    last_signal = 'SIGINT'
    for sig, timeout in steps:
        last_signal = sig.name
        if proc.poll() is not None:
            return last_signal
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            return last_signal
        except Exception:
            try:
                os.kill(proc.pid, sig)
            except ProcessLookupError:
                return last_signal
        try:
            proc.wait(timeout=timeout)
            return last_signal
        except subprocess.TimeoutExpired:
            continue
    return last_signal


def handle_cancel_ask(cmd: dict) -> dict:
    with ACTIVE_COPILOT_LOCK:
        proc = ACTIVE_COPILOT.get('process')
        if not ACTIVE_COPILOT:
            return {'status': 'ok', 'message': 'No active Ask Genny request'}
        if proc is not None and getattr(proc, 'poll', lambda: 0)() is not None:
            ACTIVE_COPILOT.clear()
            return {'status': 'ok', 'message': 'No active Ask Genny request'}
        if ACTIVE_COPILOT.get('cancel_requested'):
            return {
                'status': 'ok',
                'message': 'Cancel already in progress',
                'pid': proc.pid,
                'request_id': ACTIVE_COPILOT.get('request_id', ''),
            }
        ACTIVE_COPILOT['cancel_requested'] = True
        ACTIVE_COPILOT['cancel_requested_at'] = time.time()
        request_id = str(ACTIVE_COPILOT.get('request_id') or '')
        pid = proc.pid if proc else 0
        provider = str(ACTIVE_COPILOT.get('provider') or PROVIDER_COPILOT)

    signal_used = _interrupt_process_gracefully(proc) if proc else 'local-cancel'
    return {
        'status': 'ok',
        'message': 'Cancel requested',
        'pid': pid,
        'request_id': request_id,
        'signal': signal_used,
        'provider': provider,
    }


def _pid_cmdline(pid: int) -> str:
    if pid <= 0:
        return ''
    try:
        raw = Path(f'/proc/{pid}/cmdline').read_bytes()
        return raw.replace(b'\x00', b' ').decode('utf-8', errors='ignore').strip()
    except Exception:
        return ''


def _keepalive_matches(state: dict, cmdline: str) -> bool:
    method = state.get('method', '')
    if method == 'gnome-session-inhibit':
        return 'gnome-session-inhibit' in cmdline and KEEPALIVE_REASON in cmdline
    if method == 'systemd-inhibit':
        return 'systemd-inhibit' in cmdline and KEEPALIVE_REASON in cmdline
    return False


def _keepalive_state() -> dict:
    state = _read_keepalive_state()
    pid = int(state.get('pid') or 0)
    cmdline = _pid_cmdline(pid)
    if not pid or not cmdline or not _keepalive_matches(state, cmdline):
        if state:
            _clear_keepalive_state()
        return {
            'enabled': False,
            'method': '',
            'pid': 0,
            'started_at': None,
            'reason': KEEPALIVE_REASON,
        }
    return {
        'enabled': True,
        'method': state.get('method', ''),
        'pid': pid,
        'started_at': state.get('started_at'),
        'reason': state.get('reason', KEEPALIVE_REASON),
        'cmdline': cmdline,
    }


def _keepalive_candidates() -> list[tuple[str, list[str]]]:
    candidates = []
    gnome_inhibit = _find_bin('gnome-session-inhibit')
    if gnome_inhibit:
        candidates.append((
            'gnome-session-inhibit',
            [
                gnome_inhibit,
                '--app-id', KEEPALIVE_APP_ID,
                '--reason', KEEPALIVE_REASON,
                '--inhibit', KEEPALIVE_INHIBIT_FLAGS,
                '--inhibit-only',
            ],
        ))
    systemd_inhibit = _find_bin('systemd-inhibit')
    if systemd_inhibit:
        candidates.append((
            'systemd-inhibit',
            [
                systemd_inhibit,
                '--what=idle:sleep',
                '--why', KEEPALIVE_REASON,
                'sleep', 'infinity',
            ],
        ))
    return candidates


def _start_keepalive() -> dict:
    state = _keepalive_state()
    if state['enabled']:
        return {
            'status': 'ok',
            'enabled': True,
            'message': 'Keepalive already enabled',
            **state,
        }

    errors = []
    for method, cmd in _keepalive_candidates():
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            time.sleep(0.4)
            if proc.poll() is None:
                state = {
                    'pid': proc.pid,
                    'method': method,
                    'started_at': int(time.time()),
                    'reason': KEEPALIVE_REASON,
                }
                _write_keepalive_state(state)
                return {
                    'status': 'ok',
                    'enabled': True,
                    'message': 'Keepalive enabled',
                    **state,
                }
            errors.append(f'{method} exited with code {proc.returncode}')
        except Exception as exc:
            errors.append(f'{method}: {exc}')

    return {
        'status': 'error',
        'enabled': False,
        'message': 'Could not start a desktop inhibitor',
        'errors': errors,
    }


def _stop_keepalive() -> dict:
    state = _keepalive_state()
    if not state['enabled']:
        return {
            'status': 'ok',
            'enabled': False,
            'message': 'Keepalive already disabled',
            **state,
        }

    pid = state['pid']
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        pass

    for _ in range(20):
        if not _pid_cmdline(pid):
            break
        time.sleep(0.1)
    else:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    _clear_keepalive_state()
    return {
        'status': 'ok',
        'enabled': False,
        'message': 'Keepalive disabled',
        'method': state.get('method', ''),
        'pid': 0,
        'started_at': None,
        'reason': KEEPALIVE_REASON,
    }


def _resolve_desktop_icon(icon_field: str, snap_name: str = '') -> str:
    """Resolve an Icon= field from a .desktop file to an absolute path."""
    if not icon_field:
        return ''
    # Replace ${SNAP} or $SNAP with actual snap path
    if '${SNAP}' in icon_field or '$SNAP' in icon_field:
        snap_root = f'/snap/{snap_name}/current' if snap_name else ''
        icon_field = icon_field.replace('${SNAP}', snap_root).replace('$SNAP', snap_root)
    if os.path.isabs(icon_field) and os.path.isfile(icon_field):
        return icon_field
    return icon_field  # return as-is (theme icon name)


def _icon_for_snap(snap_name: str) -> str:
    """Find best icon for a snap app."""
    # 1. Check varlib desktop file for Icon= path
    for d in ['/var/lib/snapd/desktop/applications', str(Path.home() / '.local/share/applications')]:
        for f in glob_mod.glob(os.path.join(d, f'{snap_name}_*.desktop')):
            try:
                with open(f, errors='ignore') as fh:
                    for line in fh:
                        line = line.rstrip()
                        if line.startswith('Icon='):
                            icon = line[5:].strip()
                            resolved = _resolve_desktop_icon(icon, snap_name)
                            if os.path.isfile(resolved):
                                return resolved
            except Exception:
                pass
    # 2. meta/gui directory
    meta_gui = f'/snap/{snap_name}/current/meta/gui'
    for ext in ('png', 'svg'):
        for f in glob_mod.glob(f'{meta_gui}/*.{ext}'):
            return f
    return ''


def _auto_detect():
    """Register well-known tools found on host at startup."""
    data = _load_tools()
    registered = {t['key'] for t in data.get('tools', [])}
    # (key, name, binaries, snap_name)
    KNOWN = [
        ('vscode',               'VS Code',            ['/snap/bin/code', 'code'],                 'code'),
        ('chrome',               'Chrome',             ['/usr/bin/google-chrome', 'google-chrome'], ''),
        ('terminal',             'Terminal',           ['/usr/bin/gnome-terminal', 'gnome-terminal', 'kgx', 'x-terminal-emulator', 'xterm'], ''),
        ('nautilus',             'Files (Nautilus)',   ['/usr/bin/nautilus', 'nautilus'],           ''),
        ('intellij-community',   'IntelliJ Community',['/snap/bin/intellij-idea-community'],       'intellij-idea-community'),
        ('intellij-ultimate',    'IntelliJ Ultimate', ['/snap/bin/intellij-idea-ultimate'],        'intellij-idea-ultimate'),
        ('pycharm',              'PyCharm',            ['/snap/bin/pycharm'],                       'pycharm-community'),
        ('postman',              'Postman',            ['/snap/bin/postman'],                       'postman'),
        ('datagrip',             'DataGrip',           ['/snap/bin/datagrip'],                      'datagrip'),
        ('eclipse',              'Eclipse',            ['/snap/bin/eclipse'],                       'eclipse'),
    ]
    added = []
    icons_updated = False
    for key, name, binaries, snap_name in KNOWN:
        if key in registered:
            # Update icon if missing from existing entry
            existing = next((t for t in data['tools'] if t['key'] == key), None)
            if existing and not existing.get('icon') and snap_name:
                icon_path = _icon_for_snap(snap_name)
                if icon_path:
                    existing['icon'] = icon_path
                    icons_updated = True
            continue
        binary = _find_bin(*binaries)
        if binary:
            icon_path = _icon_for_snap(snap_name) if snap_name else ''
            entry = {'key': key, 'name': name, 'binary': binary,
                     'args_template': ['--new-window'] if key == 'vscode' else []}
            if icon_path:
                entry['icon'] = icon_path
            data['tools'].append(entry)
            added.append(f"{name} ({binary})")
    if added or icons_updated:
        _save_tools(data)
    if added:
        print(f"  Auto-detected: {', '.join(added)}")


# ── Action handlers (sync) ────────────────────────────────────────────────────

def handle_open_url(cmd: dict) -> dict:
    args = cmd.get('args', [])
    url = args[0] if args else cmd.get('url', '')
    if not url:
        return {'status': 'error', 'message': 'No URL provided'}
    if not BROWSER_BIN:
        return {'status': 'error', 'message': 'No browser found on host'}
    subprocess.Popen([BROWSER_BIN, url], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {'status': 'ok'}


def handle_launch_tool(cmd: dict) -> dict:
    key = cmd.get('tool', '')
    data = _load_tools()
    tool = next((t for t in data.get('tools', []) if t['key'] == key), None)
    if not tool:
        return {'status': 'error', 'message': f"Tool '{key}' not registered"}
    exec_cmd = tool.get('exec_cmd', '')
    binary = tool.get('binary', '')
    args = tool.get('args_template', [])
    try:
        if key == 'terminal':
            # Terminal entries from .desktop files can point at distro-specific
            # launchers; prefer a known-good host terminal when available.
            terminal_bin = _find_bin('gnome-terminal', 'kgx', 'x-terminal-emulator', 'xterm', 'konsole', 'xfce4-terminal')
            if terminal_bin:
                subprocess.Popen([terminal_bin], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return {'status': 'ok'}
        if exec_cmd:
            subprocess.Popen(['bash', '-c', exec_cmd], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif binary:
            subprocess.Popen([binary] + args, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            return {'status': 'error', 'message': 'No binary or exec_cmd configured for this tool'}
        return {'status': 'ok'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def handle_find_tool(cmd: dict) -> dict:
    name = cmd.get('tool', '')
    if not name:
        return {'status': 'ok', 'binary': ''}
    binary = _find_bin(name)
    return {'status': 'ok', 'binary': binary}


def handle_register_tool(cmd: dict) -> dict:
    try:
        data = _load_tools()
        key = cmd.get('key', '')
        if not key:
            return {'status': 'error', 'message': 'key is required'}
        data['tools'] = [t for t in data.get('tools', []) if t.get('key') != key]
        entry = {
            'key': key,
            'name': cmd.get('name', key),
            'binary': cmd.get('binary', ''),
            'args_template': cmd.get('args_template', []),
        }
        if cmd.get('exec_cmd'):
            entry['exec_cmd'] = cmd['exec_cmd']
        data['tools'].append(entry)
        _save_tools(data)
        return {'status': 'ok'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def handle_remove_tool(cmd: dict) -> dict:
    try:
        key = cmd.get('key', '')
        data = _load_tools()
        data['tools'] = [t for t in data.get('tools', []) if t.get('key') != key]
        _save_tools(data)
        return {'status': 'ok'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def handle_list_tools(_cmd: dict) -> dict:
    return _load_tools()


def handle_auto_detect_tools(_cmd: dict) -> dict:
    """Trigger auto-detection of well-known tools on demand and return updated list."""
    _auto_detect()
    return _load_tools()


def handle_get_tool_icon(cmd: dict) -> dict:
    """Find the icon file for a tool key and return it as base64-encoded PNG data."""
    import base64, subprocess as _sp
    key = cmd.get('key', '')
    icon_name = cmd.get('icon_name', '') or key  # icon_name from .desktop Icon= field

    def _read_file(fpath):
        if not os.path.isfile(fpath):
            return None
        if fpath.endswith('.svg'):
            for converter in ['rsvg-convert', 'inkscape', 'convert']:
                try:
                    result = _sp.run([converter, '-w', '64', '-h', '64', fpath],
                                     capture_output=True, timeout=5)
                    if result.returncode == 0 and result.stdout:
                        return result.stdout
                except Exception:
                    pass
            return None  # skip SVG if no converter
        with open(fpath, 'rb') as f:
            return f.read()

    # 0. Check stored icon path in host_tools.json (highest priority)
    data = _load_tools()
    tool = next((t for t in data.get('tools', []) if t['key'] == key), None)
    if tool and tool.get('icon'):
        stored = tool['icon']
        if os.path.isabs(stored):
            raw = _read_file(stored)
            if raw:
                return {'status': 'ok', 'data': base64.b64encode(raw).decode(), 'fmt': 'png', 'path': stored}
        icon_name = stored  # use as theme icon name fallback

    # 1. Snap meta/gui
    snap_icon = _icon_for_snap(key)
    if snap_icon:
        raw = _read_file(snap_icon)
        if raw:
            return {'status': 'ok', 'data': base64.b64encode(raw).decode(), 'fmt': 'png', 'path': snap_icon}

    # 2. Theme icon search by name
    icon_names = list(dict.fromkeys([icon_name, key]))
    candidates = []
    for iname in icon_names:
        for size in ('256x256', '128x128', '64x64', '48x48', '32x32'):
            candidates.append(f'/usr/share/icons/hicolor/{size}/apps/{iname}.png')
        candidates.append(f'/usr/share/icons/**/{iname}.png')
        candidates.append(f'/usr/share/pixmaps/{iname}.png')
        candidates.append(f'/usr/share/pixmaps/{iname}.xpm')

    for pattern in candidates:
        try:
            for fpath in sorted(glob_mod.glob(pattern, recursive=True), key=len, reverse=True):
                raw = _read_file(fpath)
                if raw:
                    return {'status': 'ok', 'data': base64.b64encode(raw).decode(), 'fmt': 'png', 'path': fpath}
        except Exception:
            pass

    return {'status': 'not_found'}


def handle_list_desktop_apps(_cmd: dict) -> dict:
    dirs = [
        str(Path.home() / '.local/share/applications'),
        '/usr/share/applications',
        '/var/lib/snapd/desktop/applications',
    ]
    apps, seen = [], set()
    for d in dirs:
        for path in glob_mod.glob(os.path.join(d, '*.desktop')):
            try:
                name = exec_str = icon = ''
                no_display = hidden = False
                in_entry = False
                with open(path, errors='ignore') as f:
                    for line in f:
                        line = line.rstrip()
                        if line == '[Desktop Entry]':
                            in_entry = True
                        elif line.startswith('[') and line != '[Desktop Entry]':
                            in_entry = False
                        if not in_entry:
                            continue
                        if line.startswith('Name=') and not name:
                            name = line[5:]
                        elif line.startswith('Exec=') and not exec_str:
                            exec_str = re.sub(r' ?%[fFuUdDnNickvm]', '', line[5:]).strip()
                        elif line.startswith('Icon=') and not icon:
                            icon = line[5:]
                        elif line == 'NoDisplay=true':
                            no_display = True
                        elif line == 'Hidden=true':
                            hidden = True
                if name and exec_str and not no_display and not hidden and name not in seen:
                    seen.add(name)
                    key = re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')
                    apps.append({'key': key, 'name': name, 'exec_cmd': exec_str, 'icon': icon})
            except Exception:
                pass
    apps.sort(key=lambda x: x['name'].lower())
    return {'status': 'ok', 'apps': apps}


# ── Streaming action: ServiceNow MFA Login ────────────────────────────────────

def stream_servicenow_login(cmd: dict, write_line):
    """Launch servicenow_auto_login.py on host, stream stdout back to caller."""
    script = REPO_DIR / 'auger' / 'tools' / 'servicenow_auto_login.py'
    if not script.exists():
        write_line({'type': 'error', 'message': f'Login script not found: {script}'})
        return

    venv_python = _find_selenium_python()
    if not venv_python:
        write_line({
                'type': 'error',
                'message': (
                    'No Python with selenium found.\n'
                    f'Fix: pip install selenium webdriver-manager in {SELENIUM_VENV_DIR}\n'
                    f'Run: python3 -m venv {SELENIUM_VENV_DIR} && '
                    f'{SELENIUM_VENV_DIR}/bin/pip install selenium webdriver-manager'
                )
            })
        return

    write_line({'type': 'progress', 'message': '[NET] Opening Chrome on host for ServiceNow login...'})
    write_line({'type': 'progress', 'message': f'   Script: {script}'})
    write_line({'type': 'progress', 'message': f'   Python: {venv_python}'})

    try:
        proc = subprocess.Popen(
            [venv_python, str(script), '--no-prompt'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                write_line({'type': 'progress', 'message': line})
        proc.wait(timeout=660)
        if proc.returncode == 0:
            write_line({'type': 'done', 'status': 'ok',
                        'message': f'[OK] Login complete — cookies saved to {AUGER_DIR / ".env"}'})
        else:
            write_line({'type': 'error',
                        'message': f'Login script exited with code {proc.returncode}'})
    except subprocess.TimeoutExpired:
        proc.kill()
        write_line({'type': 'error', 'message': 'Login timed out after 11 minutes'})
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


def stream_jira_login(cmd: dict, write_line):
    """Launch jira_auto_login.py on host, stream stdout back to caller."""
    script = REPO_DIR / 'auger' / 'tools' / 'jira_auto_login.py'
    if not script.exists():
        write_line({'type': 'error', 'message': f'Login script not found: {script}'})
        return

    venv_python = _find_selenium_python()
    if not venv_python:
        write_line({
                'type': 'error',
                'message': (
                    'No Python with selenium found.\n'
                    f'Fix: pip install selenium webdriver-manager in {SELENIUM_VENV_DIR}\n'
                    f'Run: python3 -m venv {SELENIUM_VENV_DIR} && '
                    f'{SELENIUM_VENV_DIR}/bin/pip install selenium webdriver-manager'
                )
            })
        return

    write_line({'type': 'progress', 'message': '[NET] Opening Chrome on host for Jira login...'})
    write_line({'type': 'progress', 'message': f'   Script: {script}'})

    try:
        proc = subprocess.Popen(
            [venv_python, str(script), '--no-prompt'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, start_new_session=True
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                write_line({'type': 'progress', 'message': line})
        proc.wait(timeout=660)
        if proc.returncode == 0:
            write_line({'type': 'done', 'status': 'ok',
                        'message': f'[OK] Jira login complete — cookies saved to {AUGER_DIR / ".env"}'})
        else:
            write_line({'type': 'error',
                        'message': f'Login script exited with code {proc.returncode}'})
    except subprocess.TimeoutExpired:
        proc.kill()
        write_line({'type': 'error', 'message': 'Login timed out after 11 minutes'})
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


def _find_selenium_python() -> str:
    """Find a Python with selenium installed, or create a venv if needed."""
    candidates = [
        str(AUGER_DIR / 'sn_venv' / 'bin' / 'python'),
        # au_sre standalone venv (common location)
        str(Path.home() / 'repos/devtools-scripts/au-silver/astutl_python/au_sre/venv/bin/python'),
        sys.executable,
    ]
    for py in candidates:
        if not os.path.isfile(py):
            continue
        r = subprocess.run([py, '-c', 'import selenium'], capture_output=True)
        if r.returncode == 0:
            return py

    # Auto-create venv with selenium
    venv_dir = AUGER_DIR / 'sn_venv'
    print(f'  Creating selenium venv at {venv_dir}...')
    r = subprocess.run([sys.executable, '-m', 'venv', str(venv_dir)], capture_output=True)
    if r.returncode != 0:
        return ''
    pip = str(venv_dir / 'bin' / 'pip')
    subprocess.run([pip, 'install', '--quiet', 'selenium', 'webdriver-manager'],
                   capture_output=True)
    py = str(venv_dir / 'bin' / 'python')
    return py if os.path.isfile(py) else ''


# ── Host-scope actions: restart / rebuild Docker runtime ──────────────────────

def stream_restart_platform(cmd: dict, write_line):
    """Restart the PlatformGen UI. Delegates to stream_restart_auger since the
    daemon runs on the host and is unaffected by container restarts.
    docker restart is NOT used — it triggers a Tk segfault (exit 139) on
    some platforms because the graceful SIGTERM path isn't crash-safe."""
    stream_restart_auger(cmd, write_line)


def stream_restart_auger(cmd: dict, write_line):
    """Stop and restart the Docker runtime container (full restart).
    The daemon stays running — platformgen-launch.sh is NOT used here because it
    would try to start a second daemon on port 7437 while this one is live.
    Uses the personalized image when available and keeps host UID/GID mapping."""
    docker_bin = _find_bin('docker')
    if not docker_bin:
        write_line({'type': 'error', 'message': 'docker not found on host'})
        return

    import os, time, re as _re
    display = os.environ.get('DISPLAY', ':0')
    container = os.environ.get('AUGER_CONTAINER_NAME', 'platformgen-platform')

    # Derive safe username (strip domain, replace non-alphanumeric with -)
    _raw_user = os.environ.get('USER', 'auger')
    _safe_user = _re.sub(r'[^a-zA-Z0-9]+', '-', _raw_user.split('@')[0]).rstrip('-')
    _host_home = str(Path.home())
    _auger_dir = str(AUGER_DIR)
    _container_home = f'/home/{_safe_user}'

    # Pick personalized image if it exists, else fall back to base image
    _personalized_image = f'auger-platform-{_safe_user}:latest'
    _base_image = 'auger-platform:latest'
    _check = subprocess.run(
        [docker_bin, 'image', 'inspect', _personalized_image],
        capture_output=True
    )
    if _check.returncode == 0:
        _image = _personalized_image
        _user_arg = f'{os.getuid()}:{os.getgid()}'
    else:
        write_line({'type': 'progress',
                    'message': f'  [WARN]  Personalized image not found — falling back to {_base_image}'})
        _image = _base_image
        _user_arg = 'auger'
        _container_home = '/home/auger'

    write_line({'type': 'progress', 'message': f'🔄 Restarting {APP_NAME} Docker runtime ({_image})...'})
    try:
        # Stop existing container
        subprocess.run([docker_bin, 'rm', '-f', container], capture_output=True)
        write_line({'type': 'progress', 'message': '  ✓ Old container stopped'})
        time.sleep(1)

        volume_args = [
            '-v', f'{_auger_dir}:{_container_home}/.auger',
            '-v', f'{_host_home}/.ssh:{_container_home}/.ssh:ro',
            '-v', f'{_host_home}/.gitconfig:{_container_home}/.gitconfig:ro',
            '-v', '/:/host:ro',
        ]
        if (Path.home() / 'repos').exists():
            volume_args += ['-v', f'{_host_home}/repos:{_container_home}/repos']
        if (Path.home() / '.kube').exists():
            volume_args += ['-v', f'{_host_home}/.kube:{_container_home}/.kube:ro']
        if (Path.home() / '.copilot').exists():
            volume_args += ['-v', f'{_host_home}/.copilot:{_container_home}/.copilot']
        if os.path.exists('/var/run/docker.sock'):
            volume_args += ['-v', '/var/run/docker.sock:/var/run/docker.sock']

        # Build a patched resolv.conf: strip loopback/APIPA nameservers and add 8.8.8.8
        # as fallback so private hostnames (RDS, dev09, etc.) resolve inside the container.
        auger_resolv = '/tmp/auger-resolv.conf'
        try:
            with open('/etc/resolv.conf') as _rf:
                orig = _rf.read()
            patched = _re.sub(r'^nameserver\s+(127\.|169\.254\.).*\n?', '', orig, flags=_re.M)
            if 'nameserver' not in patched:
                patched += '\nnameserver 8.8.8.8\nnameserver 8.8.4.4\n'
            with open(auger_resolv, 'w') as _wf:
                _wf.write(patched)
            resolv_args = ['-v', f'{auger_resolv}:/etc/resolv.conf:ro']
        except Exception:
            resolv_args = []

        # Collect real upstream DNS servers via resolvectl (WorkSpace systemd-resolved)
        dns_args: list[str] = []
        try:
            rc = subprocess.run(['resolvectl', 'status'], capture_output=True, text=True)
            for ns in set(_m.group(1) for _m in
                           __import__('re').finditer(r'DNS Servers:\s+([\d.]+)', rc.stdout)):
                if not (ns.startswith('127.') or ns.startswith('169.254.')):
                    dns_args += ['--dns', ns]
        except Exception:
            pass
        if not dns_args:
            for _line in open('/etc/resolv.conf'):
                _line = _line.strip()
                if _line.startswith('nameserver'):
                    ns = _line.split()[1]
                    if not (ns.startswith('127.') or ns.startswith('169.254.')):
                        dns_args += ['--dns', ns]
        if not dns_args:
            dns_args = ['--dns', '8.8.8.8', '--dns', '8.8.4.4']

        proxy = 'http://127.0.0.1:9000'
        run_cmd = [
            docker_bin, 'run', '-d',
            '--name', container,
            '--network', 'host',
            '--security-opt', 'seccomp:unconfined',
            '--user', _user_arg,
            '-e', f'DISPLAY={display}',
            '-e', f'HOME={_container_home}',
            '-v', '/tmp/.X11-unix:/tmp/.X11-unix',
        ] + volume_args + resolv_args + dns_args + [
            '-e', f'http_proxy={proxy}',
            '-e', f'https_proxy={proxy}',
            '-e', f'HTTP_PROXY={proxy}',
            '-e', f'HTTPS_PROXY={proxy}',
            _image,
            'auger', 'start',
        ]

        result = subprocess.run(run_cmd, capture_output=True, text=True)
        if result.returncode != 0:
            write_line({'type': 'error', 'message': f'docker run failed: {result.stderr.strip()}'})
            return

        write_line({'type': 'progress', 'message': '  ✓ Container started'})
        write_line({'type': 'done', 'status': 'ok',
                    'message': f'[OK] {APP_NAME} Docker runtime restarted (daemon still running)'})
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


def stream_rebuild_auger(cmd: dict, write_line):
    """Rebuild the Docker image then restart the runtime."""
    write_line({'type': 'progress', 'message': f'🔨 Rebuilding {APP_NAME} image (this takes a few minutes)...'})
    try:
        import os as _os
        env = _os.environ.copy()
        result = subprocess.run(
            ['git', '-C', str(REPO_DIR), 'rev-parse', 'HEAD'],
            capture_output=True, text=True
        )
        env['GIT_COMMIT'] = result.stdout.strip()

        proc = subprocess.Popen(
            ['docker', 'compose', '-f', str(REPO_DIR / 'docker-compose.yml'), 'build'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env, cwd=str(REPO_DIR)
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                write_line({'type': 'progress', 'message': line})
        proc.wait(timeout=600)
        if proc.returncode != 0:
            write_line({'type': 'error',
                        'message': f'Build failed (exit {proc.returncode}) — check daemon.log'})
            return
        write_line({'type': 'progress', 'message': '[OK] Build complete — restarting...'})
        # Chain into restart
        stream_restart_auger(cmd, write_line)
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


# ── Session Snapshot helpers (Layer 1 + 2) ────────────────────────────────────

def _write_session_snapshot(user_prompt: str, response_lines: list) -> None:
    """Write the session snapshot after every Copilot call."""
    import sqlite3 as _sq3
    snap: dict = {'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    try:
        for candidate in [
            Path('/home/auger/repos/auger-ai-sre-platform'),
            Path.home() / 'repos' / 'auger-ai-sre-platform',
        ]:
            if candidate.exists():
                branch = subprocess.check_output(
                    ['git', '-C', str(candidate), 'branch', '--show-current'],
                    stderr=subprocess.DEVNULL, text=True).strip()
                head = subprocess.check_output(
                    ['git', '-C', str(candidate), 'log', '--oneline', '-1'],
                    stderr=subprocess.DEVNULL, text=True).strip()
                snap['git_branch'] = branch
                snap['git_head'] = head
                break
    except Exception:
        pass
    try:
        db = AUGER_DIR / 'tasks.db'
        if db.exists():
            conn = _sq3.connect(str(db))
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
    try:
        hist = AUGER_DIR / 'chat_history.jsonl'
        if hist.exists():
            turns = []
            for raw in hist.read_text().splitlines()[-20:]:
                try:
                    obj = json.loads(raw)
                    turns.append({'ts': obj.get('ts', ''), 'role': obj.get('role', ''),
                                  'content': obj.get('content', '')[:300]})
                except Exception:
                    pass
            snap['last_turns'] = turns[-10:]
    except Exception:
        pass
    snap['last_user_prompt'] = user_prompt[:300]
    try:
        (AUGER_DIR / '.session_snapshot.json').write_text(json.dumps(snap, indent=2))
    except Exception:
        pass


def _load_behavior_doc() -> str:
    """Return AUGER_BEHAVIOR.md persona doc — searched in package data and repo."""
    candidates = [
        Path('/home/auger/repos/auger-ai-sre-platform/auger/data/origin/AUGER_BEHAVIOR.md'),
        Path.home() / 'repos' / 'auger-ai-sre-platform' / 'auger' / 'data' / 'origin' / 'AUGER_BEHAVIOR.md',
    ]
    for p in candidates:
        if p.exists():
            try:
                return p.read_text().strip()
            except Exception:
                pass
    return ''


def _build_context_preamble() -> str:
    """Return context preamble to inject before every copilot prompt.

    Warm start (snapshot < 48h): compact snapshot (branch, tasks, last turns).
    Cold start (no snapshot / stale): AUGER_BEHAVIOR.md orientation so Genny
    is self-aware from day one on a fresh PlatformGen install.
    """
    snap_path = AUGER_DIR / '.session_snapshot.json'
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
                    snap = None
        except Exception:
            snap = None

    # Cold-start: inject persona doc
    if snap is None:
        behavior = _load_behavior_doc()
        if behavior:
            return (
                '[AUGER COLD-START ORIENTATION — injected on first run / long idle]\n'
                + behavior
                + '\n[END ORIENTATION — respond to the user message below]\n\n'
            )
        return ''

    # Warm start: compact snapshot preamble
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



# ── Ask Copilot streaming action ──────────────────────────────────────────────

def stream_ask_copilot(cmd: dict, write_line):
    """Run copilot on the host with session locking + pinned session ID.
    Serializes all requests so concurrent calls never corrupt events.jsonl.
    Streams output back as NDJSON and appends to the shared chat history."""
    import fcntl, time
    import uuid

    prompt = cmd.get('prompt', '').strip()
    if not prompt:
        write_line({'type': 'error', 'message': 'No prompt provided'})
        return

    # Build env, loading the runtime .env file
    env = os.environ.copy()
    env_file = AUGER_DIR / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if v and k not in env:
                    env[k] = v
    token = (env.get('COPILOT_GITHUB_TOKEN') or env.get('GH_TOKEN') or
             env.get('GITHUB_TOKEN') or env.get('GITHUB_COPILOT_TOKEN'))
    if token:
        env['COPILOT_GITHUB_TOKEN'] = token
        env['GH_TOKEN'] = token
        env['GITHUB_TOKEN'] = token

    selected_model = str(cmd.get('model') or 'auto').strip() or 'auto'
    session_id_file = copilot_pin_path(selected_model)
    pinned_session_id = read_copilot_pinned_session_id(selected_model) or None
    model_args = ['--model', selected_model] if selected_model.lower() != 'auto' else []

    session_target = cmd.get('session_target', {})
    if not isinstance(session_target, dict):
        session_target = {}
    session_mode = str(session_target.get('mode') or 'pinned').strip().lower()
    requested_session_id = str(session_target.get('session_id') or '').strip()
    requested_session_name = str(session_target.get('name') or '').strip()
    name_args = ['--name', requested_session_name] if requested_session_name else []

    def _session_is_corrupt(candidate_id: str) -> bool:
        if not candidate_id:
            return False
        try:
            import json as _json_health

            events_path = Path.home() / '.copilot' / 'session-state' / candidate_id / 'events.jsonl'
            if not events_path.exists():
                return False
            try:
                lines = events_path.read_text().splitlines()
                for raw_line in lines[-30:]:
                    try:
                        evt = _json_health.loads(raw_line)
                        etype = evt.get('type', '')
                        edata = evt.get('data', {}) or {}
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
                return False
        except Exception:
            return False
        return False

    if session_mode == 'session' and requested_session_id:
        session_id = requested_session_id
        session_args = ['--resume', session_id]
    elif session_mode == 'new':
        session_id = requested_session_id or str(uuid.uuid4())
        session_args = ['--resume', session_id]
    else:
        session_mode = 'pinned'
        session_id = pinned_session_id
        session_args = ['--resume', session_id] if session_id else ['--continue']

    if session_mode == 'pinned' and session_id and _session_is_corrupt(session_id):
        try:
            clear_copilot_pinned_session_id(selected_model)
        except Exception:
            pass
        session_id = None
        session_args = ['--continue']
        write_line({'type': 'progress', 'message': '[WARN] Corrupt pinned session detected — starting fresh session'})
    elif session_mode == 'session' and session_id and _session_is_corrupt(session_id):
        session_mode = 'new'
        session_id = str(uuid.uuid4())
        session_args = ['--resume', session_id]
        write_line({'type': 'progress', 'message': '[WARN] Selected session is unhealthy — switching this request to a fresh session'})

    copilot_bin = _find_bin('copilot')
    if not copilot_bin:
        write_line({'type': 'error', 'message': 'copilot not found on host PATH'})
        return

    lock_path = AUGER_DIR / '.copilot.lock'
    chat_history = AUGER_DIR / 'chat_history.jsonl'
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    source = cmd.get('source', 'daemon')  # caller can tag origin: 'container', 'host', etc.

    # Layer 2: inject session snapshot preamble before every copilot call
    _preamble = _build_context_preamble()
    _enriched_prompt = _preamble + prompt if _preamble else prompt

    write_line({'type': 'progress', 'message': '⏳ Acquiring session lock...'})
    # Ensure lock file is world-writable (0o666) so both host user and container
    # auger user (different UIDs) can acquire it without PermissionError.
    if not lock_path.exists():
        import os as _os_lock
        fd = _os_lock.open(str(lock_path), _os_lock.O_CREAT | _os_lock.O_WRONLY, 0o666)
        _os_lock.close(fd)
    try:
        lock_path.chmod(0o666)
    except Exception:
        pass

    # Acquire lock with timeout (30s) so a stuck/abandoned call never blocks forever.
    _lock_deadline = time.time() + 30
    with open(lock_path, 'r+') as lock_fh:
        while True:
            try:
                fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _write_lock_metadata(lock_path)
                break
            except BlockingIOError:
                if time.time() > _lock_deadline:
                    write_line({'type': 'error',
                                'message': 'Timed out waiting for session lock (another call may be stuck). '
                                           'If this persists, restart the host daemon.'})
                    return
                time.sleep(0.5)
        try:
            write_line({'type': 'progress', 'message': '🤖 Asking Copilot...'})

            # Record prompt in shared chat history (original, not enriched)
            AUGER_DIR.mkdir(parents=True, exist_ok=True)
            with open(chat_history, 'a') as hf:
                hf.write(json.dumps({
                    'ts': timestamp, 'role': 'user',
                    'content': prompt, 'source': source
                }) + '\n')

            request_id = str(uuid.uuid4())

            def _run_copilot(s_args, enriched):
                """Run copilot subprocess and return (response_lines, returncode, cancelled)."""
                lines_out = []
                run_name_args = [] if '--resume' in s_args else name_args
                p = subprocess.Popen(
                    [copilot_bin] + model_args + run_name_args + ['-p', enriched, '--allow-all'] + s_args,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, bufsize=1, env=env
                )
                active_state = _register_active_copilot(
                    p,
                    request_id=request_id,
                    prompt=prompt,
                    session_mode=session_mode,
                    session_id=session_id,
                    model=selected_model,
                    provider=PROVIDER_COPILOT,
                )
                _stats_prefixes = (
                    'Total usage est:', 'API time spent:', 'Total session time:',
                    'Total code changes:', 'Breakdown by AI model:',
                )
                import re as _re_stats
                try:
                    for ln in p.stdout:
                        ln = ln.rstrip()
                        if not ln:
                            continue
                        clean = _re_stats.sub(r'\x1b\[[0-9;]*[mK]', '', ln)
                        stripped = clean.strip()
                        is_stats = (any(stripped.startswith(s) for s in _stats_prefixes)
                                    or bool(_re_stats.match(r' +claude-| +gpt-', clean)))
                        lines_out.append(clean)
                        if not is_stats:
                            write_line({'type': 'output', 'message': ln})
                    p.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
                except Exception:
                    # Client disconnected or exception — kill copilot so lock is released
                    try:
                        p.kill()
                        p.wait(timeout=5)
                    except Exception:
                        pass
                    raise
                finally:
                    was_cancelled = bool(active_state.get('cancel_requested'))
                    _clear_active_copilot(request_id)
                return lines_out, p.returncode, was_cancelled

            response_lines, rc, was_cancelled = _run_copilot(session_args, _enriched_prompt)

            # Auto-detect CAPIError / 400 Bad Request in output — corrupt session.
            # Clear the pinned session and retry once with a fresh --continue session.
            _caperror_markers = (
                'capierror',
                '400 bad request',
                '400 bad_request',
                'bad request',
                'failed to get response',
                'tool_use ids were found without tool_result',
                'each tool_use block must have a corresponding tool_result block',
                'invalid_request_error',
            )
            _output_lower = ' '.join(response_lines).lower()
            if not was_cancelled and (rc != 0 or any(m in _output_lower for m in _caperror_markers)):
                if session_mode == 'pinned':
                    try:
                        clear_copilot_pinned_session_id(selected_model)
                    except Exception:
                        pass
                    write_line({'type': 'progress',
                                'message': '[WARN] Session error detected — clearing pinned session and retrying with fresh session…'})
                    response_lines, rc, was_cancelled = _run_copilot(['--continue'], _enriched_prompt)
                    session_id = None
                else:
                    session_mode = 'new'
                    session_id = str(uuid.uuid4())
                    write_line({'type': 'progress',
                                'message': '[WARN] Session error detected — retrying with a fresh non-pinned session…'})
                    response_lines, rc, was_cancelled = _run_copilot(['--resume', session_id], _enriched_prompt)

            if was_cancelled:
                write_line({
                    'type': 'cancelled',
                    'message': 'Request cancelled — lock released normally',
                })
                return

            # Pin session ID after every successful call so next invocation uses
            # --resume instead of --continue (preserves full conversation context).
            actual_session_id = session_id
            if rc == 0:
                try:
                    session_state_dir = Path.home() / '.copilot' / 'session-state'
                    if session_state_dir.exists():
                        dirs = sorted(
                            (e for e in session_state_dir.iterdir() if e.is_dir()),
                            key=lambda p: p.stat().st_mtime,
                            reverse=True,
                        )
                        if dirs:
                            actual_session_id = dirs[0].name
                            if session_mode == 'pinned':
                                write_copilot_pinned_session_id(selected_model, dirs[0].name)
                except Exception:
                    pass

            # Layer 1: write session snapshot for context recovery
            _write_session_snapshot(prompt, response_lines)

            # Record response in shared chat history
            with open(chat_history, 'a') as hf:
                hf.write(json.dumps({
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                    'role': 'assistant',
                    'content': '\n'.join(response_lines),
                    'source': source
                }) + '\n')

            if rc == 0:
                write_line({
                    'type': 'done',
                    'status': 'ok',
                    'session_id': actual_session_id,
                    'session_mode': session_mode,
                    'model': selected_model,
                    'provider': PROVIDER_COPILOT,
                })
            else:
                write_line({'type': 'error',
                            'message': f'copilot exited with code {rc}'})
        except subprocess.TimeoutExpired:
            write_line({'type': 'error', 'message': 'Copilot timed out after 5 minutes'})
        except Exception as e:
            write_line({'type': 'error', 'message': str(e)})
        finally:
            _clear_lock_metadata(lock_path)
            fcntl.flock(lock_fh, fcntl.LOCK_UN)


def _ask_genny_system_prompt() -> str:
    return (
        f"You are the AI agent embedded in {APP_NAME}. "
        "Respond as the in-product assistant, not as a generic provider or model name. "
        "Preserve the user's platform context and answer directly."
    )


def _stream_openai_chat(
    env: dict,
    *,
    model: str,
    messages: list[dict[str, str]],
    active_state: dict[str, object],
    on_chunk,
):
    api_key = str(env.get('OPENAI_API_KEY') or '').strip()
    if not api_key:
        raise ValueError('OpenAI API key is not configured in API Keys+')
    payload = json.dumps({
        'model': model,
        'messages': messages,
        'stream': True,
    }).encode()
    req = urllib.request.Request(
        f'{openai_base_url(env)}/v1/chat/completions',
        data=payload,
        headers={
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
            'Accept': 'text/event-stream',
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            if active_state.get('cancel_requested'):
                return True
            line = raw.decode('utf-8', errors='replace').strip()
            if not line or not line.startswith('data:'):
                continue
            data = line[5:].strip()
            if data == '[DONE]':
                break
            event = json.loads(data)
            delta = (
                event.get('choices', [{}])[0]
                .get('delta', {})
                .get('content', '')
            )
            if delta:
                on_chunk(delta)
    return bool(active_state.get('cancel_requested'))


def _stream_ollama_chat(
    env: dict,
    *,
    model: str,
    messages: list[dict[str, str]],
    active_state: dict[str, object],
    on_chunk,
):
    payload = json.dumps({
        'model': model,
        'messages': messages,
        'stream': True,
    }).encode()
    req = urllib.request.Request(
        f'{ollama_base_url(env)}/api/chat',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            if active_state.get('cancel_requested'):
                return True
            chunk = json.loads(raw.decode('utf-8', errors='replace').strip() or '{}')
            delta = chunk.get('message', {}).get('content', '')
            if delta:
                on_chunk(delta)
            if chunk.get('done'):
                break
    return bool(active_state.get('cancel_requested'))


def stream_ask_local_provider(cmd: dict, write_line, *, provider: str):
    import uuid

    prompt = cmd.get('prompt', '').strip()
    if not prompt:
        write_line({'type': 'error', 'message': 'No prompt provided'})
        return

    provider = normalize_provider(provider)
    env = load_runtime_env(os.environ.copy())
    selected_model = normalize_model(provider, cmd.get('model'), env)
    session_target = cmd.get('session_target', {})
    if not isinstance(session_target, dict):
        session_target = {}
    requested_mode = str(session_target.get('mode') or 'pinned').strip().lower()
    source = cmd.get('source', 'daemon')
    chat_history = AUGER_DIR / 'chat_history.jsonl'
    timestamp = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

    session_payload = ensure_local_session(provider, selected_model, session_target)
    session_id = str(session_payload.get('session_id') or '')
    session_mode = requested_mode if requested_mode in {'pinned', 'session', 'new'} else 'pinned'
    request_id = str(uuid.uuid4())

    history = session_messages(session_id)
    context_preamble = _build_context_preamble()
    enriched_prompt = context_preamble + prompt if context_preamble else prompt
    messages = [
        {'role': 'system', 'content': _ask_genny_system_prompt()},
        *history,
        {'role': 'user', 'content': enriched_prompt},
    ]

    AUGER_DIR.mkdir(parents=True, exist_ok=True)
    with open(chat_history, 'a') as hf:
        hf.write(json.dumps({
            'ts': timestamp,
            'role': 'user',
            'content': prompt,
            'source': source,
        }) + '\n')

    response_chunks: list[str] = []

    def _emit(delta: str):
        response_chunks.append(delta)
        write_line({'type': 'chunk', 'message': delta})

    active_state = _register_active_copilot(
        None,
        request_id=request_id,
        prompt=prompt,
        session_mode=session_mode,
        session_id=session_id,
        model=selected_model,
        provider=provider,
    )
    try:
        if provider == PROVIDER_OPENAI:
            was_cancelled = _stream_openai_chat(
                env,
                model=selected_model,
                messages=messages,
                active_state=active_state,
                on_chunk=_emit,
            )
        elif provider == PROVIDER_OLLAMA:
            was_cancelled = _stream_ollama_chat(
                env,
                model=selected_model,
                messages=messages,
                active_state=active_state,
                on_chunk=_emit,
            )
        else:
            write_line({'type': 'error', 'message': f'Unsupported provider: {provider}'})
            return

        if was_cancelled:
            write_line({
                'type': 'cancelled',
                'message': 'Request cancelled — session preserved',
            })
            return

        full_response = ''.join(response_chunks).strip()
        if not full_response:
            write_line({'type': 'error', 'message': f'{provider} returned an empty response'})
            return

        append_local_turn(session_id, prompt, full_response)
        _write_session_snapshot(prompt, [full_response])
        with open(chat_history, 'a') as hf:
            hf.write(json.dumps({
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'role': 'assistant',
                'content': full_response,
                'source': source,
            }) + '\n')
        write_line({
            'type': 'done',
            'status': 'ok',
            'session_id': session_id,
            'session_mode': session_mode,
            'model': selected_model,
            'provider': provider,
        })
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode('utf-8', errors='replace').strip()
        message = detail or f'{provider} HTTP error {exc.code}'
        write_line({'type': 'error', 'message': message[:1000]})
    except Exception as exc:
        write_line({'type': 'error', 'message': str(exc)})
    finally:
        _clear_active_copilot(request_id)


def stream_ask(cmd: dict, write_line):
    provider = normalize_provider(cmd.get('provider'))
    if provider_supports_copilot_sessions(provider):
        stream_ask_copilot(cmd, write_line)
        return
    stream_ask_local_provider(cmd, write_line, provider=provider)


# ── Docker / Artifactory streaming actions ────────────────────────────────────

def _docker_login_artifactory() -> tuple:
    """Login to Artifactory Docker registry. Returns (ok, message)."""
    env_file = AUGER_DIR / '.env'
    env_vars = {}
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, _, v = line.partition('=')
                env_vars[k.strip()] = v.strip().strip('"').strip("'")
    registry_url = env_vars.get('ARTIFACTORY_URL', os.environ.get('ARTIFACTORY_URL', ''))
    registry = registry_url.replace('https://', '').replace('http://', '').rstrip('/')
    username  = env_vars.get('ARTIFACTORY_USERNAME', os.environ.get('ARTIFACTORY_USERNAME', ''))
    password  = (env_vars.get('ARTIFACTORY_IDENTITY_TOKEN') or
                 env_vars.get('ARTIFACTORY_API_KEY') or
                 env_vars.get('ARTIFACTORY_PASSWORD') or
                 os.environ.get('ARTIFACTORY_IDENTITY_TOKEN', ''))
    if not registry or not username or not password:
        return False, f'Missing ARTIFACTORY_URL/USERNAME/IDENTITY_TOKEN in {AUGER_DIR / ".env"}'
    docker_bin = _find_bin('docker')
    if not docker_bin:
        return False, 'docker not found on host PATH'
    env = os.environ.copy()
    r = subprocess.run(
        [docker_bin, 'login', registry, '-u', username, '--password-stdin'],
        input=password.encode(), capture_output=True, env=env
    )
    if r.returncode == 0:
        return True, f'Logged in to {registry}'
    return False, r.stderr.decode().strip() or r.stdout.decode().strip()


def stream_docker_pull(cmd: dict, write_line):
    """Pull a Docker image on the host, streaming progress."""
    image = cmd.get('image', '').strip()
    if not image:
        write_line({'type': 'error', 'message': 'No image specified'})
        return
    docker_bin = _find_bin('docker')
    if not docker_bin:
        write_line({'type': 'error', 'message': 'docker not found on host'})
        return
    write_line({'type': 'progress', 'message': f'Logging in to Artifactory...'})
    ok, msg = _docker_login_artifactory()
    write_line({'type': 'progress', 'message': msg})
    if not ok:
        write_line({'type': 'error', 'message': f'Login failed: {msg}'})
        return
    write_line({'type': 'progress', 'message': f'Pulling {image}...'})
    try:
        proc = subprocess.Popen(
            [docker_bin, 'pull', image],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                write_line({'type': 'progress', 'message': line})
        proc.wait(timeout=600)
        if proc.returncode == 0:
            write_line({'type': 'done', 'status': 'ok', 'message': f'Pulled {image}'})
        else:
            write_line({'type': 'error', 'message': f'docker pull exited with {proc.returncode}'})
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


def stream_docker_push(cmd: dict, write_line):
    """Push a Docker image to Artifactory, streaming progress."""
    image = cmd.get('image', '').strip()
    if not image:
        write_line({'type': 'error', 'message': 'No image specified'})
        return
    docker_bin = _find_bin('docker')
    if not docker_bin:
        write_line({'type': 'error', 'message': 'docker not found on host'})
        return
    write_line({'type': 'progress', 'message': 'Logging in to Artifactory...'})
    ok, msg = _docker_login_artifactory()
    write_line({'type': 'progress', 'message': msg})
    if not ok:
        write_line({'type': 'error', 'message': f'Login failed: {msg}'})
        return
    write_line({'type': 'progress', 'message': f'Pushing {image}...'})
    try:
        proc = subprocess.Popen(
            [docker_bin, 'push', image],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                write_line({'type': 'progress', 'message': line})
        proc.wait(timeout=600)
        if proc.returncode == 0:
            write_line({'type': 'done', 'status': 'ok', 'message': f'Pushed {image}'})
        else:
            write_line({'type': 'error', 'message': f'docker push exited with {proc.returncode}'})
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


def handle_docker_open_terminal(cmd: dict) -> dict:
    """Open a gnome-terminal on the host running 'docker run -it --rm image /bin/bash'.
    First does docker login, then optionally pulls, then launches the terminal."""
    image = cmd.get('image', '').strip()
    if not image:
        return {'status': 'error', 'message': 'No image specified'}
    docker_bin = _find_bin('docker')
    if not docker_bin:
        return {'status': 'error', 'message': 'docker not found on host'}
    terminal_bin = _find_bin('gnome-terminal', 'xterm', 'konsole', 'xfce4-terminal')
    if not terminal_bin:
        return {'status': 'error', 'message': 'No terminal emulator found on host'}

    # Login silently (ignore failures — image may already be cached)
    _docker_login_artifactory()

    docker_cmd = f'{docker_bin} run -it --rm {image} /bin/bash'
    if 'gnome-terminal' in terminal_bin:
        args = [terminal_bin, '--', 'bash', '-c', f'{docker_cmd}; exec bash']
    elif 'xterm' in terminal_bin:
        args = [terminal_bin, '-e', docker_cmd]
    else:
        args = [terminal_bin, '-e', docker_cmd]

    subprocess.Popen(args, start_new_session=True)
    return {'status': 'ok', 'message': f'Opened terminal: {docker_cmd}'}



    """Run docker exec /bin/bash in an existing container, streaming I/O."""
    container = cmd.get('container', '').strip()
    if not container:
        write_line({'type': 'error', 'message': 'No container name specified'})
        return
    docker_bin = _find_bin('docker')
    if not docker_bin:
        write_line({'type': 'error', 'message': 'docker not found on host'})
        return
    write_line({'type': 'progress', 'message': f'Attaching to {container}...'})
    try:
        proc = subprocess.Popen(
            [docker_bin, 'exec', '-it', container, '/bin/bash'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1
        )
        for line in proc.stdout:
            write_line({'type': 'output', 'message': line.rstrip()})
        proc.wait(timeout=3600)
        write_line({'type': 'done', 'status': 'ok', 'message': 'Session ended'})
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


def stream_docker_run_bash(cmd: dict, write_line):
    """Run a fresh container from an image with /bin/bash, streaming output."""
    image = cmd.get('image', '').strip()
    if not image:
        write_line({'type': 'error', 'message': 'No image specified'})
        return
    docker_bin = _find_bin('docker')
    if not docker_bin:
        write_line({'type': 'error', 'message': 'docker not found on host'})
        return
    write_line({'type': 'progress', 'message': f'Starting container from {image}...'})
    try:
        proc = subprocess.Popen(
            [docker_bin, 'run', '-i', '--rm', '--entrypoint', '/bin/bash', image],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            bufsize=0
        )
        write_line({'type': 'started', 'status': 'ok', 'message': 'Container ready'})
        os.set_blocking(proc.stdout.fileno(), False)
        import time
        time.sleep(1)
        proc.stdin.write(b"export PS1='container# '\necho '=== READY ==='\n")
        proc.stdin.flush()
        while proc.poll() is None:
            try:
                data = proc.stdout.read(4096)
                if data:
                    write_line({'type': 'output', 'message': data.decode('utf-8', errors='replace')})
            except BlockingIOError:
                time.sleep(0.05)
        write_line({'type': 'done', 'status': 'ok', 'message': 'Container exited'})
    except Exception as e:
        write_line({'type': 'error', 'message': str(e)})


# ── HTTP Handler ──────────────────────────────────────────────────────────────


def handle_open_path(cmd: dict) -> dict:
    """Open a file or folder with a registered tool on the host.

    Strips /host prefix so host binaries receive real host paths.
    cmd: {tool: key, path: /absolute/path}
    """
    tool_key = cmd.get('tool', '')
    path = cmd.get('path', '').strip()
    if not tool_key:
        return {'status': 'error', 'message': 'No tool specified'}
    if not path:
        return {'status': 'error', 'message': 'No path specified'}

    # ── Container → host path translation ────────────────────────────────────
    # The container mounts host paths at well-known locations. Translate so
    # host binaries (VS Code, etc.) receive real filesystem paths.
    host_home = str(Path.home())  # e.g. /home/bobbygblair
    # Volume mounts: container_prefix → host_prefix
    CONTAINER_MOUNTS = [
        ('/host/', '/'),                               # full host root
        ('/home/auger/repos/', f'{host_home}/repos/'), # ~/repos mount
        ('/home/auger/.auger/', f'{host_home}/.auger/'),
        ('/home/auger/.ssh/', f'{host_home}/.ssh/'),
        ('/home/auger/.kube/', f'{host_home}/.kube/'),
        ('/home/auger/', f'{host_home}/'),             # catch-all for /home/auger
    ]
    for container_prefix, host_prefix in CONTAINER_MOUNTS:
        if path.startswith(container_prefix):
            path = host_prefix + path[len(container_prefix):]
            break
    if path == '/host':
        path = '/'

    data = _load_tools()
    tool = next((t for t in data.get('tools', []) if t['key'] == tool_key), None)
    if not tool:
        return {'status': 'error', 'message': f"Tool '{tool_key}' not registered"}

    binary = tool.get('binary', '')
    exec_cmd = tool.get('exec_cmd', '')
    if not binary and not exec_cmd:
        return {'status': 'error', 'message': f"Tool '{tool_key}' has no binary configured"}

    try:
        env = os.environ.copy()
        # Prevent VS Code from routing through an existing window via IPC
        env.pop('VSCODE_IPC_HOOK_CLI', None)
        if exec_cmd:
            subprocess.Popen(['bash', '-c', f'{exec_cmd} {shlex.quote(path)}'],
                             start_new_session=True, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            args = tool.get('args_template', [])
            subprocess.Popen([binary] + args + [path], start_new_session=True, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'status': 'ok', 'message': f"Opened {path} with {tool['name']}"}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def handle_launch_wizard(cmd: dict) -> dict:
    """Launch the PlatformGen install wizard (install_wizard.py) on the host desktop.

    The wizard is a standalone Tk window — it must run on the host (not inside
    the container) so it can reach the host X11 display directly.
    Called from inside the container via the host daemon on localhost:7437.
    """
    wizard_path = REPO_DIR / 'scripts' / 'install_wizard.py'
    if not wizard_path.exists():
        return {'status': 'error', 'message': f'install_wizard.py not found at {wizard_path}'}
    try:
        env = os.environ.copy()
        # Ensure DISPLAY is set — fall back to :0 / :1 if not inherited
        if 'DISPLAY' not in env or not env['DISPLAY']:
            for d in (':1', ':0'):
                env['DISPLAY'] = d
                break
        subprocess.Popen(
            [sys.executable, str(wizard_path)],
            start_new_session=True, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {'status': 'ok', 'message': 'Install wizard launched on host desktop'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


# ── Voice capture state ──────────────────────────────────────────────────────
_voice_proc: 'subprocess.Popen | None' = None
_voice_wav  = Path('/tmp/auger_voice.wav')
_voice_lock = threading.Lock()
_PULSE_MIC  = 'AWS-Virtual-Microphone'   # PCoIP virtual mic source name

# ── Voice hotwords ────────────────────────────────────────────────────────────
_STATIC_HOTWORDS = [
    # Environments
    'dev09', 'staging10', 'mcaas', 'ASSIST',
    # Tools / services
    'Auger', 'Artifactory', 'Kubernetes', 'kubectl', 'Helm', 'Flux',
    'Rancher', 'Gotenberg', 'Cryptkeeper', 'Prospector', 'ServiceNow',
    'DataDog', 'Jira', 'Confluence', 'GitHub', 'Docker',
    # GSA / program
    'GSA', 'FCS', 'SRE', 'FPDS',
]

# Common Whisper mishearings → correct term
_VOICE_CORRECTIONS = {
    'crypto keeper': 'Cryptkeeper',
    'crypto-keeper': 'Cryptkeeper',
    'prospector': 'Prospector',
    'gotenberg': 'Gotenberg',
    'service now': 'ServiceNow',
    'data dog': 'DataDog',
    'cube ectl': 'kubectl',
    'cube cuddle': 'kubectl',
    'dev 09': 'dev09',
    'staging 10': 'staging10',
    'mc as': 'mcaas',
}


def _build_hotwords() -> str:
    """Combine static hotwords + widget titles + user config hotwords."""
    words = list(_STATIC_HOTWORDS)

    # Widget titles from manifests
    try:
        import yaml as _yaml
        manifests = Path(__file__).parent.parent / 'auger' / 'data' / 'widget_manifests.yaml'
        if not manifests.exists():
            manifests = Path(__file__).parent.parent / 'auger/data/widget_manifests.yaml'
        if manifests.exists():
            data = _yaml.safe_load(manifests.read_text())
            widgets = data.get('widgets', {})
            if isinstance(widgets, dict):
                for v in widgets.values():
                    if isinstance(v, dict) and v.get('title'):
                        words.append(v['title'])
    except Exception:
        pass

    # User-defined hotwords from the runtime config.yaml
    try:
        import yaml as _yaml
        user_cfg = AUGER_DIR / 'config.yaml'
        if user_cfg.exists():
            cfg = _yaml.safe_load(user_cfg.read_text()) or {}
            for w in cfg.get('voice_hotwords', []):
                words.append(str(w))
    except Exception:
        pass

    # Deduplicate preserving order
    seen = set()
    unique = []
    for w in words:
        if w.lower() not in seen:
            seen.add(w.lower())
            unique.append(w)
    return ' '.join(unique)


def _apply_voice_corrections(text: str) -> str:
    """Fix common Whisper mishearings of product-specific terms."""
    result = text
    for wrong, right in _VOICE_CORRECTIONS.items():
        import re as _re
        result = _re.sub(wrong, right, result, flags=_re.IGNORECASE)
    return result


def handle_listen(cmd: dict) -> dict:
    """Start or stop voice recording via arecord + PulseAudio.

    POST /listen  {"action": "start"}  -> {"status": "recording", "source": "..."}
    POST /listen  {"action": "stop"}   -> {"status": "ok", "transcript": "..."}
    """
    global _voice_proc
    action = cmd.get('action', 'start')

    if action == 'start':
        with _voice_lock:
            if _voice_proc and _voice_proc.poll() is None:
                return {'status': 'already_recording'}
            _voice_wav.unlink(missing_ok=True)
            source = _pulse_mic_source()
            _voice_proc = subprocess.Popen([
                'arecord',
                '-D', f'pulse:{source}' if source != 'default' else 'pulse',
                '-f', 'S16_LE',
                '-r', '16000',
                '-c', '1',
                str(_voice_wav),
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'status': 'recording', 'source': source}

    elif action == 'stop':
        with _voice_lock:
            proc = _voice_proc
            _voice_proc = None
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        # Transcribe
        if not _voice_wav.exists() or _voice_wav.stat().st_size < 1000:
            return {'status': 'error', 'message': 'No audio captured — check microphone'}
        try:
            from faster_whisper import WhisperModel
            hotwords = _build_hotwords()
            model = WhisperModel('tiny.en', device='cpu', compute_type='int8')
            segments, _ = model.transcribe(
                str(_voice_wav),
                beam_size=5,
                hotwords=hotwords,
                initial_prompt=f"{APP_NAME} platform. {hotwords[:200]}",
            )
            transcript = ' '.join(s.text.strip() for s in segments).strip()
            transcript = _apply_voice_corrections(transcript)
            _voice_wav.unlink(missing_ok=True)
            return {'status': 'ok', 'transcript': transcript}
        except Exception as exc:
            return {'status': 'error', 'message': f'Transcription failed: {exc}'}

    return {'status': 'error', 'message': f'Unknown action: {action}'}


def _pulse_mic_source() -> str:
    """Return best available PulseAudio microphone source name."""
    try:
        out = subprocess.check_output(['pactl', 'list', 'short', 'sources'],
                                      text=True, timeout=3)
        for line in out.splitlines():
            if _PULSE_MIC in line:
                return _PULSE_MIC
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and '.monitor' not in parts[1]:
                return parts[1]
    except Exception:
        pass
    return 'default'


def handle_unlock_session(cmd: dict) -> dict:
    """Force-clear the Copilot session lock file so a stuck lock can be released."""
    lock_path = AUGER_DIR / '.copilot.lock'
    try:
        _clear_lock_metadata(lock_path)
        # Advisory flock locks attach to the inode, not the file path contents.
        # Replacing the file ensures future open() calls target a fresh inode,
        # even if a dead/stuck process still holds a lock on the old one.
        if lock_path.exists():
            lock_path.unlink()
        fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY, 0o666)
        os.close(fd)
        os.chmod(lock_path, 0o666)
        return {'status': 'ok', 'message': 'Session lock replaced'}
    except Exception as exc:
        return {'status': 'error', 'message': str(exc)}


SYNC_ACTIONS = {
    'open_url':               handle_open_url,
    'launch_tool':            handle_launch_tool,
    'find_tool':              handle_find_tool,
    'register_tool':          handle_register_tool,
    'remove_tool':            handle_remove_tool,
    'list_tools':             handle_list_tools,
    'auto_detect_tools':      handle_auto_detect_tools,
    'get_tool_icon':          handle_get_tool_icon,
    'list_desktop_apps':      handle_list_desktop_apps,
    'docker_open_terminal':   handle_docker_open_terminal,
    'open_path':              handle_open_path,
    'launch_wizard':          handle_launch_wizard,
    'unlock_session':         handle_unlock_session,
    'cancel_ask':             handle_cancel_ask,
}


def stream_reinit_session(cmd: dict, write_line):
    """Clear the pinned session for the active provider/model scope."""
    import fcntl as _fcntl
    provider = normalize_provider(cmd.get('provider'))
    model = normalize_model(provider, cmd.get('model'))
    lock_path = AUGER_DIR / '.copilot.lock'
    write_line({'type': 'progress', 'message': f'🔄 Reinitializing {provider} session…'})
    with open(lock_path, 'w') as _lf:
        _fcntl.flock(_lf, _fcntl.LOCK_EX)
        try:
            if provider_supports_copilot_sessions(provider):
                old_id = read_copilot_pinned_session_id(model)
                clear_copilot_pinned_session_id(model)
            else:
                old_id = read_local_pinned_session_id(provider, model)
                clear_local_pinned_session(provider, model)
            if old_id:
                write_line({'type': 'progress',
                            'message': f'🗑️  Cleared pinned session: {old_id[:12]}…'})
            else:
                write_line({'type': 'progress',
                            'message': '[INFO]  No pinned session found (already fresh)'})
            write_line({'type': 'progress',
                        'message': '[OK] Session cleared — next message will start a fresh scoped session with full context snapshot.'})
            write_line({'type': 'done', 'status': 'ok', 'provider': provider, 'model': model})
        finally:
            _fcntl.flock(_lf, _fcntl.LOCK_UN)


STREAM_ACTIONS = {
    'ask_copilot':         stream_ask,
    'reinit_session':      stream_reinit_session,
    'restart_auger':       stream_restart_auger,
    'rebuild_auger':       stream_rebuild_auger,
    'servicenow_login':    stream_servicenow_login,
    'jira_login':          stream_jira_login,
    'docker_pull':         stream_docker_pull,
    'docker_push':         stream_docker_push,
    'docker_run_bash':     stream_docker_run_bash,
}


class DaemonHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Suppress routine GET /health noise; log everything else
        try:
            rendered = fmt % args if args else fmt
        except Exception:
            rendered = f'{fmt} {" ".join(str(arg) for arg in args)}'.strip()
        if '/health' not in rendered:
            print(f'[daemon] {rendered}')

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _restart_daemon_self(self):
        """Spawn a fresh detached daemon child, then exit this process."""
        self._send_json({'status': 'ok', 'message': 'Daemon restarting...'})

        def _do_restart():
            import time
            time.sleep(0.3)
            try:
                self.server.socket.close()
            except Exception:
                pass
            subprocess.Popen(
                [sys.executable] + sys.argv,
                start_new_session=True,
                close_fds=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
            os._exit(0)

        threading.Thread(target=_do_restart, daemon=True).start()

    def do_GET(self):
        if self.path == '/health':
            keepalive = _keepalive_state()
            daemon_name = f"{APP_NAME.lower().replace(' ', '-')}-host-tools"
            self._send_json({'status': 'ok', 'daemon': daemon_name, 'port': PORT,
                             'browser': BROWSER_BIN or None, 'keepalive': keepalive})
        elif self.path == '/keepalive_status':
            state = _keepalive_state()
            self._send_json({'status': 'ok', **state})
        elif self.path == '/session_status':
            # Report Copilot session lock state and last response time.
            lock_path = AUGER_DIR / '.copilot.lock'
            chat_history = AUGER_DIR / 'chat_history.jsonl'
            locked = False
            locked_secs = 0
            last_response_ts = None
            try:
                import fcntl as _fcntl
                if lock_path.exists():
                    with open(lock_path, 'r+') as _lf:
                        try:
                            _fcntl.flock(_lf, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
                            _fcntl.flock(_lf, _fcntl.LOCK_UN)
                            locked = False
                            _clear_lock_metadata(lock_path)
                        except BlockingIOError:
                            locked = True
                            try:
                                meta = json.loads(_lock_meta_path(lock_path).read_text())
                                acquired_at = float(meta.get('acquired_at') or 0)
                                if acquired_at > 0:
                                    locked_secs = max(0, int(time.time() - acquired_at))
                                else:
                                    locked_secs = int(time.time() - lock_path.stat().st_mtime)
                            except Exception:
                                locked_secs = int(time.time() - lock_path.stat().st_mtime)
            except Exception:
                pass
            active_ask = _active_copilot_snapshot()
            try:
                if chat_history.exists():
                    import json as _jh
                    last_line = None
                    with open(chat_history, 'rb') as _f:
                        # Efficient: read last 2KB to find last assistant line
                        _f.seek(0, 2)
                        size = _f.tell()
                        _f.seek(max(0, size - 2048))
                        tail = _f.read().decode('utf-8', errors='ignore')
                    for raw in tail.strip().splitlines():
                        try:
                            obj = _jh.loads(raw)
                            if obj.get('role') == 'assistant':
                                last_line = obj
                        except Exception:
                            pass
                    if last_line:
                        last_response_ts = last_line.get('ts')
            except Exception:
                pass
            self._send_json({
                'status': 'ok',
                'locked': locked,
                'locked_secs': locked_secs,
                'last_response_ts': last_response_ts,
                'lock_path': str(lock_path),
                'active_request': bool(active_ask.get('active')),
                'cancel_requested': bool(active_ask.get('cancel_requested')),
                'active_provider': str(active_ask.get('provider') or ''),
                'active_model': str(active_ask.get('model') or ''),
            })
        elif self.path == '/restart_daemon':
            self._restart_daemon_self()
        else:
            self._send_json({'error': 'Not found'}, 404)

    def _stream_action(self, action_fn, cmd: dict):
        """Shared NDJSON streaming helper over a normal response body.

        We intentionally avoid manual chunked transfer encoding here. Some host
        Python/http client combinations used by Ask Genny receive an empty reply
        when this daemon hand-rolls `Transfer-Encoding: chunked`. Plain NDJSON
        lines flushed over a standard response are sufficient for both the panel
        and curl, with EOF delimiting the stream.
        """
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-ndjson')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True

        def write_line(obj: dict):
            data = (json.dumps(obj) + '\n').encode()
            try:
                self.wfile.write(data)
                self.wfile.flush()
            except Exception:
                pass

        try:
            action_fn(cmd, write_line)
        except Exception as exc:
            try:
                write_line({'type': 'error', 'message': str(exc)})
            except Exception:
                pass

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length)
            try:
                cmd = json.loads(body)
            except Exception:
                self._send_json({'status': 'error', 'message': 'Invalid JSON'}, 400)
                return

            # Dedicated /ask endpoint — shortcut for stream_ask_copilot
            if self.path == '/ask':
                cmd.setdefault('source', 'host')
                self._stream_action(stream_ask, cmd)
                return

            # Dedicated /restart_platform endpoint — restarts UI only, daemon stays up
            if self.path == '/restart_platform':
                self._stream_action(stream_restart_platform, cmd)
                return

            # /schedule_restart — responds immediately, then restarts after `delay` seconds.
            # Safe to call from inside Ask Genny: response is delivered before restart fires.
            # Body: {"delay": 5, "message": "optional user-facing message"}
            if self.path == '/schedule_restart':
                delay = int(cmd.get('delay', 5))
                msg = cmd.get('message', f'Restarting {APP_NAME} in {delay}s…')
                import threading as _threading
                def _delayed():
                    import time as _time
                    _time.sleep(delay)
                    stream_restart_platform({}, lambda x: None)
                _threading.Thread(target=_delayed, daemon=True).start()
                resp = {'status': 'ok', 'message': msg, 'delay': delay}
                body = __import__('json').dumps(resp).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            # Dedicated /restart endpoint (full restart via docker-run.sh)
            if self.path == '/restart':
                self._stream_action(stream_restart_auger, cmd)
                return

            # Dedicated /restart_daemon endpoint — POST supported for tray/client helpers
            if self.path == '/restart_daemon':
                self._restart_daemon_self()
                return

            if self.path == '/keepalive':
                action = str(cmd.get('action', 'toggle')).strip().lower()
                with KEEPALIVE_LOCK:
                    if action in ('enable', 'start', 'on'):
                        self._send_json(_start_keepalive())
                    elif action in ('disable', 'stop', 'off'):
                        self._send_json(_stop_keepalive())
                    elif action == 'toggle':
                        current = _keepalive_state()
                        self._send_json(_stop_keepalive() if current['enabled'] else _start_keepalive())
                    else:
                        self._send_json({
                            'status': 'error',
                            'message': f'Unknown keepalive action: {action}',
                        }, 400)
                return

            # Dedicated /rebuild endpoint
            if self.path == '/rebuild':
                self._stream_action(stream_rebuild_auger, cmd)
                return

            # Dedicated /reinit_session endpoint — clears pinned session for fresh start
            if self.path == '/reinit_session':
                self._stream_action(stream_reinit_session, cmd)
                return

            # Dedicated /launch_wizard endpoint — opens install wizard on host desktop
            if self.path == '/launch_wizard':
                self._send_json(handle_launch_wizard(cmd))
                return

            # Voice capture endpoint — start/stop arecord + transcribe with faster-whisper
            if self.path == '/listen':
                self._send_json(handle_listen(cmd))
                return

            action = cmd.get('action', '')

            if action in SYNC_ACTIONS:
                result = SYNC_ACTIONS[action](cmd)
                self._send_json(result)

            elif action in STREAM_ACTIONS:
                self._stream_action(STREAM_ACTIONS[action], cmd)

            else:
                self._send_json({'status': 'error', 'message': f"Unknown action: '{action}'"}, 400)
        except Exception:
            traceback.print_exc()
            try:
                self._send_json({'status': 'error', 'message': 'Daemon request failed'}, 500)
            except Exception:
                pass


class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """Handle each request in a new thread so long-running streams don't block."""
    daemon_threads = True
    allow_reuse_address = True


def main():
    AUGER_DIR.mkdir(parents=True, exist_ok=True)
    print(f'[NET] {APP_NAME} Host Tools Daemon v2 (HTTP)')
    print(f'   Port:    {PORT}')
    print(f'   Browser: {BROWSER_BIN or "not found"}')
    print(f'   Tools:   {HOST_TOOLS_FILE}')
    print(f'   Repo:    {REPO_DIR}')
    print(f'   Ask:     POST http://localhost:{PORT}/ask  {{\"prompt\": \"...\"}}')
    print()
    print('[SETUP] Scanning for host tools...')
    _auto_detect()
    server = ThreadedHTTPServer(('0.0.0.0', PORT), DaemonHandler)
    print(f'[OK] Daemon ready at http://localhost:{PORT}')
    print('   Health check: curl http://localhost:7437/health')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nDaemon stopped.')


if __name__ == '__main__':
    main()
