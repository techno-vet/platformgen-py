#!/bin/bash
# PlatformGen - Docker Run
# Starts the PlatformGen UI from any Docker-capable host.
#
# Tokens and API keys are read from $HOME/.platformgen/.env (shared with local pip install).
# Copy .env.example to ~/.platformgen/.env and fill in your values before first run.
#
# Usage:
#   ./scripts/docker-run.sh                    # use local image
#   ./scripts/docker-run.sh artifactory.example.com/auger-platform:latest

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -eq 0 ]; then
    exec bash "$SCRIPT_DIR/platformgen-launch.sh"
fi

LOCAL_BASE_IMAGE="${PLATFORMGEN_LOCAL_BASE_IMAGE:-${AUGER_LOCAL_BASE_IMAGE:-platformgen-platform:latest}}"
LEGACY_LOCAL_BASE_IMAGE="${AUGER_LOCAL_BASE_IMAGE_LEGACY:-auger-platform:latest}"
IMAGE="${1:-$LOCAL_BASE_IMAGE}"
CONTAINER_NAME="${PLATFORMGEN_CONTAINER_NAME:-${AUGER_CONTAINER_NAME:-platformgen-platform}}"
AUGER_DIR="${PLATFORMGEN_HOME:-${AUGER_HOME:-$HOME/.platformgen}}"
DAEMON_PORT="${PLATFORMGEN_DAEMON_PORT:-${AUGER_DAEMON_PORT:-7438}}"

# Canonical repo location: prefer current PlatformGen checkout locations, fall back to script's own directory
if [ -d "$HOME/repos/platformgen-py" ]; then
    CANON_REPO="$HOME/repos/platformgen-py"
elif [ -d "$HOME/projects/platformgen-py" ]; then
    CANON_REPO="$HOME/projects/platformgen-py"
elif [ -d "$HOME/repos/auger-ai-sre-platform" ]; then
    CANON_REPO="$HOME/repos/auger-ai-sre-platform"
else
    CANON_REPO="$(cd "$(dirname "$0")/.." && pwd)"
fi

# If using the local image and a Dockerfile is present, rebuild only when
# build-affecting files change (Dockerfile, requirements, etc.) — NOT on every git commit.
# All Python/widget code is live via volume mount and never needs a rebuild.
if { [ "$IMAGE" = "$LOCAL_BASE_IMAGE" ] || [ "$IMAGE" = "$LEGACY_LOCAL_BASE_IMAGE" ]; } && [ -f "$CANON_REPO/Dockerfile" ]; then
    REPO_DIR="$CANON_REPO"

    # Hash only the files that actually affect the Docker image
    BUILD_HASH=$(cat \
        "$REPO_DIR/Dockerfile" \
        "$REPO_DIR/requirements.txt" 2>/dev/null \
        "$REPO_DIR/pyproject.toml" 2>/dev/null \
        "$REPO_DIR/setup.cfg" 2>/dev/null \
        "$REPO_DIR/install.sh" 2>/dev/null \
        | md5sum | cut -d' ' -f1)

    # Label stored in image at build time
    IMAGE_HASH=$(docker inspect --format='{{index .Config.Labels "build-hash"}}' "$IMAGE" 2>/dev/null || echo "")

    if [ -z "$IMAGE_HASH" ] || [ "$IMAGE_HASH" != "$BUILD_HASH" ]; then
        echo "🔨 Build files changed (hash: ${IMAGE_HASH:-none} → ${BUILD_HASH}) — rebuilding image..."
        CURRENT_COMMIT=$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")

        # Detect Zscaler/proxy and pass to build args so apt-get can reach internet
        BUILD_PROXY_ARGS=""
        for port in 9000 10800 3128 8080; do
            if ss -tlnp 2>/dev/null | grep -q ":${port} " || netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
                PROXY_URL="http://127.0.0.1:${port}"
                BUILD_PROXY_ARGS="--build-arg http_proxy=${PROXY_URL} --build-arg https_proxy=${PROXY_URL} --build-arg HTTP_PROXY=${PROXY_URL} --build-arg HTTPS_PROXY=${PROXY_URL}"
                echo "[SECURE] Passing proxy ${PROXY_URL} to docker build"
                break
            fi
        done

        BUILD_HASH="$BUILD_HASH" GIT_COMMIT="$CURRENT_COMMIT" \
            docker compose -f "$REPO_DIR/docker-compose.yml" build $BUILD_PROXY_ARGS
    else
        echo "[OK] Image up to date (build hash: ${BUILD_HASH}) — skipping rebuild"
    fi
    if [ "$IMAGE" = "$LEGACY_LOCAL_BASE_IMAGE" ] && docker image inspect "$LOCAL_BASE_IMAGE" >/dev/null 2>&1; then
        IMAGE="$LOCAL_BASE_IMAGE"
    fi
fi

# ─── Host: ensure PlatformGen CLI is available ───────────────────────────────
_host_cli=""
for _candidate in platformgen auger; do
    if command -v "$_candidate" &>/dev/null; then
        _host_cli="$_candidate"
        break
    fi
done
if [ -z "$_host_cli" ]; then
    if [ -f "$HOME/.local/bin/platformgen" ] || [ -f "$HOME/.local/bin/auger" ]; then
        export PATH="$HOME/.local/bin:$PATH"
    fi
    for _candidate in platformgen auger; do
        if command -v "$_candidate" &>/dev/null; then
            _host_cli="$_candidate"
            break
        fi
    done
fi
if [ -z "$_host_cli" ]; then
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  PlatformGen CLI not found on this host."
    echo "  The shared Copilot session (host ↔ container) requires"
    echo "  platformgen (or legacy auger) to be installed on the host."
    echo ""
    echo "  Install it now?"
    echo "  pip3 install --user -e \"$CANON_REPO\""
    echo "  (or install package name: pip3 install --user platformgen-py)"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    read -r -p "  Auto-install with pip3? [y/N] " _ans
    if [[ "${_ans,,}" == "y" ]]; then
        pip3 install --user -e "$CANON_REPO" && echo "[OK] PlatformGen CLI installed" || echo "[WARN]  Install failed — continuing without host CLI"
    else
        echo "[WARN]  Skipping host CLI install — Ask Genny host session won't be shared"
    fi
    echo ""
fi

# ─── Ensure config dir exists ─────────────────────────────────────────────────
# Ensure ~/.platformgen exists (even with no .env — first-run wizard handles it)
mkdir -p "$AUGER_DIR"
if [ ! -f "$AUGER_DIR/.env" ]; then
    echo "[INFO]  No $AUGER_DIR/.env found — first-run setup wizard will appear on launch."
    touch "$AUGER_DIR/.env"
fi

# Allow X11 connections from local Docker containers
xhost +local:docker 2>/dev/null || true

HOST_UID=$(id -u)
HOST_GID=$(id -g)

echo "[START] Starting PlatformGen..."
echo "   Image  : $IMAGE"
echo "   Display: $DISPLAY"
echo "   Config : $AUGER_DIR"

# Detect Zscaler proxy (Amazon WorkSpace: Zscaler runs on 127.0.0.1:9000)
PROXY_ARGS=""
for port in 9000 10800 3128 8080; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} " || netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
        echo "[SECURE] Detected Zscaler/proxy on port ${port} - passing proxy to container"
        PROXY_ARGS="-e http_proxy=http://127.0.0.1:${port} -e https_proxy=http://127.0.0.1:${port} -e HTTP_PROXY=http://127.0.0.1:${port} -e HTTPS_PROXY=http://127.0.0.1:${port}"
        break
    fi
done

# Detect real upstream DNS (resolvectl for systemd-resolved, fallback to resolv.conf)
DNS_ARGS=""
if command -v resolvectl &>/dev/null; then
    # Get upstream DNS from systemd-resolved (skips 127.0.0.53 stub)
    while read -r ns; do
        [ -n "$ns" ] && DNS_ARGS="$DNS_ARGS --dns $ns"
    done < <(resolvectl status 2>/dev/null | awk '/DNS Servers:/{for(i=3;i<=NF;i++) print $i}' | sort -u | head -4)
fi
if [ -z "$DNS_ARGS" ] && [ -f /etc/resolv.conf ]; then
    while IFS= read -r line; do
        case "$line" in
            nameserver\ *)
                ns="${line#nameserver }"
                case "$ns" in 127.*) ;; *) DNS_ARGS="$DNS_ARGS --dns $ns" ;; esac ;;
        esac
    done < /etc/resolv.conf
fi
[ -z "$DNS_ARGS" ] && DNS_ARGS="--dns 8.8.8.8 --dns 8.8.4.4"

# ─── Host Tools HTTP Daemon (start FIRST — platform needs it on boot) ────────
# Must be running before the container starts so /schedule_restart, browser
# launch, and Jira MFA auth are available the moment the UI opens.
DAEMON_SCRIPT="$SCRIPT_DIR/host_tools_daemon.py"
if [ -f "$DAEMON_SCRIPT" ]; then
    OLD_DAEMON=$(lsof -ti "tcp:${DAEMON_PORT}" 2>/dev/null | head -1)
    [ -n "$OLD_DAEMON" ] && kill "$OLD_DAEMON" 2>/dev/null && sleep 1
    echo "[NET] Starting Host Tools daemon on port ${DAEMON_PORT}..."
    nohup python3 "$DAEMON_SCRIPT" > "$AUGER_DIR/daemon.log" 2>&1 &
    DAEMON_PID=$!
    disown $DAEMON_PID
    for i in $(seq 1 20); do
        if curl -sf --noproxy localhost "http://localhost:${DAEMON_PORT}/health" >/dev/null 2>&1; then
            echo "[OK] Daemon ready (PID $DAEMON_PID)"
            echo "$DAEMON_PID" > "$AUGER_DIR/daemon.pid"
            break
        fi
        sleep 0.5
    done
else
    echo "[WARN]  Daemon script not found at $DAEMON_SCRIPT — skipping"
fi

# Stop any existing container with same name
docker rm -f "$CONTAINER_NAME" 2>/dev/null || true

# Start container detached (keeps running after exec exits).
# Load token from .env — propagate under all three names copilot CLI checks.
if [ -z "$GH_TOKEN" ] && [ -f "$AUGER_DIR/.env" ]; then
    _env_token=$(grep -E '^(GHE_TOKEN|GH_TOKEN)=' "$AUGER_DIR/.env" | head -1 | cut -d= -f2- | tr -d "'\"\r")
    [ -n "$_env_token" ] && GH_TOKEN="$_env_token"
fi
# Always propagate under all names so auger CLI + copilot CLI both find the token
_COPILOT_TOKEN="${COPILOT_GITHUB_TOKEN:-${GITHUB_TOKEN:-$GH_TOKEN}}"
COPILOT_BIN_MOUNT=""
[ -x "$HOME/.local/bin/copilot" ] && COPILOT_BIN_MOUNT="-v $HOME/.local/bin/copilot:/usr/local/bin/copilot:ro"
docker run -d \
  --name "$CONTAINER_NAME" \
  --hostname platformgen-platform \
  --user root \
  --network host \
  ${DNS_ARGS} \
  # Base images still use the legacy in-container home layout for compatibility.
  -e HOME=/home/auger \
  -e PATH=/home/auger/.local/bin:/usr/local/bin:/usr/bin:/bin \
  -e HOST_UID="$HOST_UID" \
  -e HOST_GID="$HOST_GID" \
  -e HOST_USER="$(id -un 2>/dev/null || echo hostuser)" \
  -e PLATFORMGEN_USE_LIVE_REPO=1 \
  -e AUGER_USE_LIVE_REPO=1 \
  ${_COPILOT_TOKEN:+-e GH_TOKEN="$_COPILOT_TOKEN"} \
  ${_COPILOT_TOKEN:+-e GITHUB_TOKEN="$_COPILOT_TOKEN"} \
  ${_COPILOT_TOKEN:+-e COPILOT_GITHUB_TOKEN="$_COPILOT_TOKEN"} \
  -v /tmp/.X11-unix:/tmp/.X11-unix:rw \
  -v "$AUGER_DIR:/home/auger/.auger" \
  -v "$HOME/.copilot:/home/auger/.copilot" \
  ${COPILOT_BIN_MOUNT} \
  -v "$HOME/.kube:/home/auger/.kube:ro" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /opt/google/chrome:/opt/google/chrome:ro \
  $([ -f "$HOME/.gitconfig" ] && echo "-v $HOME/.gitconfig:/home/auger/.gitconfig:ro") \
  $([ -d "$HOME/.ssh" ] && echo "-v $HOME/.ssh:/home/auger/.ssh:ro") \
  $([ -d "$HOME/repos" ] && echo "-v $HOME/repos:/home/auger/repos") \
  -v /:/host:ro \
  -e AUGER_HOST_ROOT=/host \
  --group-add "$(stat -c '%g' /var/run/docker.sock)" \
  ${PROXY_ARGS} \
  --security-opt seccomp:unconfined \
  "$IMAGE" \
  sleep infinity

# Launch the UI in the running container (detached so it survives terminal close)
echo "[OK] Container started, launching UI..."
docker exec -d -u "$HOST_UID:$HOST_GID" \
    -e DISPLAY="${DISPLAY:-:1}" \
    -e PYTHONPATH="/home/auger/.auger/pypackages" \
    "$CONTAINER_NAME" sh -lc 'python3 -m platformgen start || python3 -m auger start || auger start'

echo "🖥️  PlatformGen UI is running. Close this terminal freely."
echo "   Daemon log: $AUGER_DIR/daemon.log"
echo "   To stop:    docker rm -f $CONTAINER_NAME"

# ─── System Tray Applet ───────────────────────────────────────────────────────
# Launches the host task tray for Open/Ask/Restart/Stop.
DISPLAY="${DISPLAY:-:1}" bash "$SCRIPT_DIR/start-platformgen-tray.sh"

# ─── GNOME .desktop launcher + dock icon ─────────────────────────────────────
ICON_DIR="$HOME/.local/share/icons"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_PATH="$ICON_DIR/platformgen-platform.png"
DESKTOP_FILE="$DESKTOP_DIR/platformgen-platform.desktop"
mkdir -p "$ICON_DIR" "$DESKTOP_DIR"
rm -f "$DESKTOP_DIR/auger-platform.desktop"

python3 -c "
import sys
sys.path.insert(0, '${REPO_DIR}')
try:
    try:
        from platformgen.ui.icons import install_app_icon
    except ImportError:
        from auger.ui.icons import install_app_icon
    path = install_app_icon('${ICON_PATH}')
    print('[OK] App icon saved:', path)
except Exception as e:
    print('[WARN]  Could not render app icon:', e)
"

cat > "$DESKTOP_FILE" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=PlatformGen
GenericName=SRE Platform
Comment=Drill Down With Genny [INSTALL]
Exec=bash ${SCRIPT_DIR}/platformgen-launch.sh
Icon=${ICON_PATH}
Terminal=false
Categories=Development;System;
StartupWMClass=platformgen-platform
Keywords=platformgen;genny;sre;devops;kubernetes;
DESKTOP

chmod +x "$DESKTOP_FILE"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
echo "[OK] GNOME launcher installed: $DESKTOP_FILE"

# ─── GNOME tray autostart — survive workspace reboot ──────────────────────────
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/platformgen-task-tray.desktop"
mkdir -p "$AUTOSTART_DIR"
rm -f "$AUTOSTART_DIR/auger-platform.desktop"
rm -f "$AUTOSTART_DIR/auger-task-tray.desktop"
cat > "$AUTOSTART_FILE" <<AUTOSTART
[Desktop Entry]
Type=Application
Name=PlatformGen Task Tray
Comment=Start PlatformGen task tray on login
Exec=bash ${SCRIPT_DIR}/start-platformgen-tray.sh
Icon=${ICON_PATH}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
AUTOSTART
echo "[OK] Tray autostart registered — PlatformGen task tray will start after workspace reboot"
