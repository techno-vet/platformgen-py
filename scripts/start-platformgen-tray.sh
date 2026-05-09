#!/bin/bash
# Start the PlatformGen host tools daemon (if needed) and the host task tray.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${PLATFORMGEN_HOME:-${AUGER_HOME:-${AUGER_DIR:-$HOME/.platformgen}}}"
TRAY_SCRIPT="${PLATFORMGEN_TRAY_SCRIPT:-${AUGER_TRAY_SCRIPT:-$SCRIPT_DIR/platformgen_tray.py}}"
DAEMON_SCRIPT="$SCRIPT_DIR/host_tools_daemon.py"
HOST_PYTHON="/usr/bin/python3"
HOST_PIP="/usr/bin/pip3"
DAEMON_PORT="${PLATFORMGEN_DAEMON_PORT:-${AUGER_DAEMON_PORT:-7438}}"

[ -x "$HOST_PYTHON" ] || HOST_PYTHON="$(command -v python3)"
[ -x "$HOST_PIP" ] || HOST_PIP="$(command -v pip3)"

mkdir -p "$STATE_DIR"

DISPLAY_VAL="${DISPLAY:-}"
if [ -z "$DISPLAY_VAL" ]; then
    if [ -S /tmp/.X11-unix/X1 ]; then
        DISPLAY_VAL=":1"
    elif [ -S /tmp/.X11-unix/X0 ]; then
        DISPLAY_VAL=":0"
    else
        DISPLAY_VAL=":0"
    fi
fi

if [ -f "$DAEMON_SCRIPT" ] && ! curl -sf --noproxy localhost "http://localhost:${DAEMON_PORT}/health" >/dev/null 2>&1; then
    OLD_DAEMON=$(lsof -ti "tcp:${DAEMON_PORT}" 2>/dev/null | head -1 || true)
    if [ -n "$OLD_DAEMON" ]; then
        kill "$OLD_DAEMON" 2>/dev/null || true
        sleep 1
    fi

    echo "[NET]  Starting Host Tools daemon on port ${DAEMON_PORT}..."
    nohup "$HOST_PYTHON" "$DAEMON_SCRIPT" >> "$STATE_DIR/daemon.log" 2>&1 &
    DAEMON_PID=$!
    disown "$DAEMON_PID"

    for _i in $(seq 1 20); do
        if curl -sf --noproxy localhost "http://localhost:${DAEMON_PORT}/health" >/dev/null 2>&1; then
            echo "$DAEMON_PID" > "$STATE_DIR/daemon.pid"
            echo "[OK]  Daemon ready (PID $DAEMON_PID)"
            break
        fi
        sleep 0.5
    done
fi

if [ ! -f "$TRAY_SCRIPT" ]; then
    echo "[INFO]  tray script not found — skipping system tray icon"
    exit 0
fi

# Skip tray in headless environments
if [ -z "$DISPLAY_VAL" ] || [ "$DISPLAY_VAL" = ":0" ]; then
    if [ ! -S /tmp/.X11-unix/X0 ] && [ ! -S /tmp/.X11-unix/X1 ]; then
        echo "[INFO]  No X11 display detected — skipping system tray icon"
        exit 0
    fi
fi

# Install pystray if needed (with fallback for PEP 668)
if ! "$HOST_PYTHON" -c "import pystray" 2>/dev/null; then
    echo "[PKG]  Installing pystray for system tray support..."
    "$HOST_PIP" install --user --quiet pystray pillow 2>/dev/null \
        || "$HOST_PIP" install --user --quiet --break-system-packages pystray pillow 2>/dev/null \
        && echo "[OK]  pystray installed" \
        || echo "[WARN]  pystray install failed — tray icon disabled"
fi

if ! "$HOST_PYTHON" -c "import pystray" 2>/dev/null; then
    echo "[WARN]  pystray not available — skipping system tray icon"
    exit 0
fi

"$HOST_PYTHON" -c "
import os, signal, subprocess, time
self_pid = os.getpid()
r = subprocess.run(['pgrep', '-f', 'platformgen_tray.py|auger_tray.py'], capture_output=True, text=True)
pids = [int(p) for p in r.stdout.split() if p.strip() and int(p) != self_pid]
for pid in pids:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
if pids:
    time.sleep(1)
"

echo "[ALERT]  Starting system tray applet..."
DISPLAY="$DISPLAY_VAL" XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}" \
gnome-extensions enable ubuntu-appindicators@ubuntu.com 2>/dev/null || true

DISPLAY="$DISPLAY_VAL" XAUTHORITY="${XAUTHORITY:-/run/user/$(id -u)/gdm/Xauthority}" \
setsid env -u GTK_EXE_PREFIX -u GTK_PATH -u GTK_DATA_PREFIX -u GTK_IM_MODULE_FILE \
    -u GIO_MODULE_DIR -u GIO_EXTRA_MODULES -u GI_TYPELIB_PATH \
    -u GDK_PIXBUF_MODULEDIR -u GDK_PIXBUF_MODULE_FILE -u GTK_MODULES \
    -u LD_LIBRARY_PATH -u PYTHONHOME \
    "$HOST_PYTHON" "$TRAY_SCRIPT" >> "$STATE_DIR/tray.log" 2>&1 &
TRAY_PID=$!
disown "$TRAY_PID"

sleep 2
if "$HOST_PYTHON" -c "import subprocess; r=subprocess.run(['pgrep','-f','platformgen_tray.py|auger_tray.py'],capture_output=True); exit(0 if r.stdout.strip() else 1)" 2>/dev/null; then
    echo "[OK]  Tray applet running (PID $TRAY_PID)"
else
    echo "[WARN]  Tray applet failed to start — check $STATE_DIR/tray.log"
    tail -5 "$STATE_DIR/tray.log" 2>/dev/null | sed 's/^/   /'
fi
