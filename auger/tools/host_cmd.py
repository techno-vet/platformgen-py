"""
host_cmd.py - Send commands to the Auger Host Tools HTTP Daemon.

The daemon (scripts/host_tools_daemon.py) runs on the host as an HTTP server
on localhost:7437. Since the container uses --network host, both container
and host share localhost, so no special routing is needed.

Usage:
    from auger.tools.host_cmd import open_url, launch_tool, find_tool
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

DAEMON_URL = 'http://localhost:7437'
TIMEOUT = 10.0          # seconds for normal commands
STREAM_TIMEOUT = 660.0  # 11 min for long-running (ServiceNow MFA)

AUGER_DIR = Path.home() / '.auger'
HOST_TOOLS_FILE = AUGER_DIR / 'host_tools.json'


# ── Core HTTP helpers ─────────────────────────────────────────────────────────

def _post(action: str, timeout: float = TIMEOUT, **kwargs) -> dict:
    """POST a command to the daemon and return the JSON response."""
    payload = json.dumps({'action': action, **kwargs}).encode()
    req = urllib.request.Request(
        f'{DAEMON_URL}/cmd',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {'status': 'error', 'message': f'Daemon unreachable at {DAEMON_URL}: {e.reason}'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


def _post_stream(action: str, timeout: float = STREAM_TIMEOUT, **kwargs):
    """POST a streaming command; yields dicts from NDJSON response line by line."""
    payload = json.dumps({'action': action, **kwargs}).encode()
    req = urllib.request.Request(
        f'{DAEMON_URL}/cmd',
        data=payload,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            buf = b''
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except json.JSONDecodeError:
                            pass
    except Exception as e:
        yield {'type': 'error', 'message': str(e)}


def daemon_health() -> dict:
    """Check if the daemon is alive. Returns health dict or error."""
    try:
        with urllib.request.urlopen(f'{DAEMON_URL}/health', timeout=2.0) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {'status': 'error', 'message': str(e)}


# ── Public API ────────────────────────────────────────────────────────────────

def find_tool(name: str) -> str:
    """Ask daemon to find a binary (has access to /snap/bin, ~/.local/bin on host)."""
    result = _post('find_tool', tool=name)
    return result.get('binary', '')


def list_tools() -> list:
    """Return list of registered host tools."""
    result = _post('list_tools')
    return result.get('tools', [])


def auto_detect_tools() -> list:
    """Trigger daemon auto-detection of well-known host tools, return updated list."""
    result = _post('auto_detect_tools', timeout=15.0)
    return result.get('tools', [])


def get_tool_icon(key: str, icon_name: str = '') -> bytes | None:
    """Fetch raw PNG icon bytes for a tool from the host. Returns None if not found."""
    import base64
    result = _post('get_tool_icon', key=key, icon_name=icon_name, timeout=8.0)
    if result.get('status') == 'ok' and result.get('data'):
        return base64.b64decode(result['data'])
    return None


def register_tool(key: str, name: str, binary: str = '',
                  args_template: list = None, exec_cmd: str = '') -> dict:
    """Register or update a host tool."""
    kwargs = {'key': key, 'name': name, 'binary': binary,
              'args_template': args_template or []}
    if exec_cmd:
        kwargs['exec_cmd'] = exec_cmd
    return _post('register_tool', **kwargs)


def remove_tool(key: str) -> dict:
    """Remove a tool from the registry."""
    return _post('remove_tool', key=key)


def open_url(url: str) -> dict:
    """Open a URL in the host browser."""
    return _post('open_url', args=[url])


def launch_tool(key: str, args: list = None) -> dict:
    """Launch a registered host tool."""
    return _post('launch_tool', tool=key, args=args or [])


def open_path(tool_key: str, path: str) -> dict:
    """Open a file or folder on the host with a registered tool.

    Automatically strips /host prefix so the host binary receives
    the real host path (/host/home/user/x -> /home/user/x).
    """
    return _post('open_path', tool=tool_key, path=path)


def list_desktop_apps() -> list:
    """Scan host .desktop files and return all launcher apps."""
    result = _post('list_desktop_apps', timeout=20.0)
    return result.get('apps', [])


def servicenow_login_stream():
    """Stream ServiceNow MFA login progress. Yields dicts with type/message fields."""
    yield from _post_stream('servicenow_login')


def jira_login_stream():
    """Stream Jira MFA login progress. Yields dicts with type/message fields."""
    yield from _post_stream('jira_login')


def open_url(url: str) -> dict:
    """Open a URL in Chrome on the host via the daemon."""
    return _post('open_url', url=url, timeout=10.0)


def docker_open_terminal(image: str) -> dict:
    """Open a host terminal running docker run -it --rm image /bin/bash."""
    return _post('docker_open_terminal', image=image, timeout=30.0)


def docker_pull_stream(image: str):
    """Pull a Docker image on the host, streaming progress dicts."""
    yield from _post_stream('docker_pull', image=image)


def docker_push_stream(image: str):
    """Push a Docker image to Artifactory, streaming progress dicts."""
    yield from _post_stream('docker_push', image=image)


def docker_run_bash_stream(image: str):
    """Run a container from an image with /bin/bash, streaming output dicts."""
    yield from _post_stream('docker_run_bash', image=image)


def send_host_cmd(action: str, timeout: float = TIMEOUT, **kwargs) -> dict:
    """Generic command sender."""
    return _post(action, timeout=timeout, **kwargs)
