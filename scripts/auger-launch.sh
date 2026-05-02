#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Auger SRE Platform — One-Shot Launcher
# Pull the latest image from Artifactory and start Auger.
# The first-run wizard will guide you through Copilot token setup.
#
# Usage:
#   bash auger-launch.sh               # Docker mode (default)
#   bash auger-launch.sh --venv        # Native venv mode (no Docker required)
#   bash auger-launch.sh --venv --background   # Native venv mode detached
#   bash auger-launch.sh --docker      # Explicit Docker/SRE mode
#   bash auger-launch.sh --venv --install-only   # Install deps only, don't start
# ─────────────────────────────────────────────────────────────────────────────
set -e
set -o pipefail

IMAGE="${AUGER_IMAGE:-artifactory.helix.gsa.gov/gs-assist-docker-repo/auger-platform:20260311}"
LOCAL_BASE_IMAGE="${AUGER_LOCAL_BASE_IMAGE:-auger-platform:latest}"
CONTAINER="${AUGER_CONTAINER_NAME:-auger-platform}"
AUGER_DIR="${AUGER_HOME:-$HOME/.auger}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROGRESS_LOG="$AUGER_DIR/startup-progress.log"
APP_TITLE="${AUGER_LAUNCHER_TITLE:-Auger}"
DESKTOP_SLUG="${AUGER_DESKTOP_SLUG:-auger}"
WM_CLASS="${AUGER_WM_CLASS:-auger-platform}"
TRAY_START_SCRIPT="${AUGER_TRAY_START_SCRIPT:-$SCRIPT_DIR/start-auger-tray.sh}"
LAUNCHER_SCRIPT="${AUGER_LAUNCHER_SCRIPT:-$SCRIPT_DIR/auger-launch.sh}"
DAEMON_PORT="${AUGER_DAEMON_PORT:-7437}"

start_progress_dialog() {
    mkdir -p "$AUGER_DIR"
    : > "$PROGRESS_LOG"
    if [ "${AUGER_WIZARD:-0}" = "1" ] || [ "${AUGER_SUPPRESS_STARTUP_DIALOG:-0}" = "1" ]; then
        return
    fi
    if [ -n "${DISPLAY:-}" ] && [ -f "$SCRIPT_DIR/startup_progress.py" ]; then
        nohup python3 "$SCRIPT_DIR/startup_progress.py" \
            --log-file "$PROGRESS_LOG" \
            --title "${APP_TITLE} Startup" >/dev/null 2>&1 &
    fi
}

progress_msg() {
    local message="$1"
    echo "$message"
    printf '%s\n' "$message" >> "$PROGRESS_LOG"
}

progress_done() {
    printf 'STATE:done\n' >> "$PROGRESS_LOG"
}

progress_error() {
    local message="$1"
    echo "$message"
    printf '%s\nSTATE:error\n' "$message" >> "$PROGRESS_LOG"
}

detect_display() {
    if [ -n "${DISPLAY:-}" ]; then
        printf '%s\n' "$DISPLAY"
        return 0
    fi
    if [ -S /tmp/.X11-unix/X1 ]; then
        printf ':1\n'
        return 0
    fi
    if [ -S /tmp/.X11-unix/X0 ]; then
        printf ':0\n'
        return 0
    fi
    printf ':0\n'
}

docker_usable() {
    command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1
}

install_desktop_launchers() {
    local icon_dir desktop_dir autostart_dir icon_path
    local host_desktop_file sre_desktop_file autostart_file

    icon_dir="$HOME/.local/share/icons"
    desktop_dir="$HOME/.local/share/applications"
    autostart_dir="$HOME/.config/autostart"
    icon_path="$icon_dir/${DESKTOP_SLUG}-platform.png"
    host_desktop_file="$desktop_dir/${DESKTOP_SLUG}.desktop"
    sre_desktop_file="$desktop_dir/${DESKTOP_SLUG}-platform.desktop"
    autostart_file="$autostart_dir/${DESKTOP_SLUG}-task-tray.desktop"

    mkdir -p "$icon_dir" "$desktop_dir" "$autostart_dir"
    rm -f "$autostart_dir/${DESKTOP_SLUG}-platform.desktop"

    python3 -c "
import sys
sys.path.insert(0, '${SCRIPT_DIR}/..')
try:
    from auger.ui.icons import install_app_icon
    path = install_app_icon('${icon_path}')
    print('[OK]  App icon saved:', path)
except Exception as e:
    print('[WARN]   Could not render app icon:', e)
" 2>/dev/null || true

    cat > "$host_desktop_file" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=${APP_TITLE}
GenericName=Host Platform
Comment=Launch ${APP_TITLE} on this host without Docker
Exec=bash ${LAUNCHER_SCRIPT} --venv --background
Icon=${icon_path}
Terminal=false
Categories=Development;System;
StartupWMClass=${WM_CLASS}
Keywords=${DESKTOP_SLUG};host;venv;widgets;
DESKTOP

    if docker_usable; then
        cat > "$sre_desktop_file" <<DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=${APP_TITLE} SRE
GenericName=SRE Platform
Comment=Launch the Docker-based ${APP_TITLE} platform
Exec=bash ${LAUNCHER_SCRIPT} --docker
Icon=${icon_path}
Terminal=false
Categories=Development;System;
StartupWMClass=${WM_CLASS}
Keywords=${DESKTOP_SLUG};sre;docker;devops;kubernetes;
DESKTOP
        chmod +x "$sre_desktop_file"
    else
        rm -f "$sre_desktop_file"
    fi

    chmod +x "$host_desktop_file"
    update-desktop-database "$desktop_dir" 2>/dev/null || true

    cat > "$autostart_file" <<AUTOSTART
[Desktop Entry]
Type=Application
Name=${AUGER_TASK_TRAY_TITLE:-Auger Task Tray}
Comment=Start ${APP_TITLE} task tray on login
Exec=bash ${TRAY_START_SCRIPT}
Icon=${icon_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
AUTOSTART
}

trap 'rc=$?; if [ "$rc" -ne 0 ] && [ -f "$PROGRESS_LOG" ]; then progress_error "Auger startup failed."; fi' EXIT

echo ""
echo "=================================================="
echo "    Auger SRE Platform - Launcher"
echo "=================================================="
echo ""

# ── Mode detection ────────────────────────────────────────────────────────────
VENV_MODE=0
DOCKER_MODE=0
INSTALL_ONLY=0
BACKGROUND_MODE=0
for arg in "$@"; do
    case "$arg" in
        --venv|--lite)         VENV_MODE=1; DOCKER_MODE=0 ;;
        --docker|--sre)        DOCKER_MODE=1; VENV_MODE=0 ;;
        --install-only)        INSTALL_ONLY=1 ;;
        --background|--detach) BACKGROUND_MODE=1 ;;
    esac
done

# Ensure ~/.local/bin is in PATH (for copilot, auger CLI, etc.)
if [ -z "$PATH" ]; then
    export PATH="$HOME/.local/bin"
elif ! echo "$PATH" | grep -q "$HOME/.local/bin"; then
    export PATH="$HOME/.local/bin:$PATH"
fi

# Auto-detect venv mode if Docker is not available or not usable
if [ "$DOCKER_MODE" -eq 0 ] && [ "$VENV_MODE" -eq 0 ] && ! docker_usable; then
    echo "[INFO]   Docker is not available/usable — switching to native venv mode automatically."
    VENV_MODE=1
fi

if [ "$DOCKER_MODE" -eq 1 ] && ! docker_usable; then
    echo "[ERROR]  Docker/SRE mode was requested, but Docker is not available or you do not have access to it."
    echo "   Try: bash $SCRIPT_DIR/auger-launch.sh --venv"
    exit 1
fi

# ─────────────────────────────────────────────────────────────────────────────
# VENV MODE  (no Docker required — works on Windows, macOS, Linux)
# ─────────────────────────────────────────────────────────────────────────────
if [ "$VENV_MODE" -eq 1 ]; then
    echo "[PY]  Auger native venv mode"
    echo ""

    # Require Python 3.8+
    if ! command -v python3 &>/dev/null; then
        echo "[ERROR]  python3 not found. Please install Python 3.8 or newer."
        exit 1
    fi

    VENV_DIR="$AUGER_DIR/venv"
    VENV_PID_FILE="$AUGER_DIR/venv-platform.pid"
    VENV_LOG_FILE="$AUGER_DIR/venv-platform.log"
    mkdir -p "$AUGER_DIR"

    # Create venv if it doesn't exist
    if [ ! -d "$VENV_DIR" ]; then
        echo "[PKG]  Creating Python virtual environment at $VENV_DIR ..."
        python3 -m venv "$VENV_DIR"
    fi

    # Activate venv
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    export PATH="$VENV_DIR/bin:$PATH"
    export AUGER_VENV_BIN="$VENV_DIR/bin"

    # Detect proxy (same logic as Docker mode)
    PROXY_URL=""
    for port in 9000 10800 3128 8080; do
        if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
           netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
            PROXY_URL="http://127.0.0.1:${port}"
            echo "[SECURE]  Proxy detected on port ${port}"
            break
        fi
    done

    PIP_PROXY_ARGS=""
    if [ -n "$PROXY_URL" ]; then
        PIP_PROXY_ARGS="--proxy $PROXY_URL"
        export http_proxy="$PROXY_URL"
        export https_proxy="$PROXY_URL"
        export HTTP_PROXY="$PROXY_URL"
        export HTTPS_PROXY="$PROXY_URL"
    fi

    # Install/update the package if dependencies or console scripts are missing.
    if [ "$INSTALL_ONLY" -eq 1 ] || \
       ! "$VENV_DIR/bin/python3" -c "import click, auger" 2>/dev/null || \
       [ ! -x "$VENV_DIR/bin/${AUGER_CLI_NAME:-auger}" ]; then
        echo "[PKG]  Installing platform package and dependencies..."
        "$VENV_DIR/bin/pip" install --quiet $PIP_PROXY_ARGS --upgrade pip
        "$VENV_DIR/bin/pip" install --quiet $PIP_PROXY_ARGS "$REPO_DIR"
        echo "[OK]  Package installed in venv"
    fi

    if [ "$INSTALL_ONLY" -eq 1 ]; then
        install_desktop_launchers
        echo ""
        echo "[OK]  Venv install complete: $VENV_DIR"
        echo "   To start Auger:  bash $SCRIPT_DIR/auger-launch.sh --venv"
        exit 0
    fi

    # Load .env tokens into environment
    if [ -f "$AUGER_DIR/.env" ]; then
        set -a
        # shellcheck disable=SC1090
        source "$AUGER_DIR/.env" 2>/dev/null || true
        set +a
    fi

    # Auto-init if config.yaml doesn't exist
    CONFIG_FILE="$AUGER_DIR/config.yaml"
    if [ ! -f "$CONFIG_FILE" ]; then
        echo "[SETUP]  First run — initializing Auger config..."
        # Try to find a GitHub token from environment
        _INIT_TOKEN="${GH_TOKEN:-${GHE_TOKEN:-${GITHUB_TOKEN:-}}}"
        if [ -z "$_INIT_TOKEN" ]; then
            read -rp "   GitHub Copilot token (github.com): " _INIT_TOKEN
        else
            echo "   Using token from ~/.auger/.env"
        fi
        "$VENV_DIR/bin/python3" -m auger init --token "$_INIT_TOKEN" || true
    fi

    # Start host tools daemon if not already running
    if ! curl -sf "http://localhost:${DAEMON_PORT}/health" >/dev/null 2>&1; then
        echo "[SETUP]  Starting host tools daemon..."
        nohup "$VENV_DIR/bin/python3" "$SCRIPT_DIR/host_tools_daemon.py" \
            > "$AUGER_DIR/daemon.log" 2>&1 &
        DAEMON_PID=$!
        echo "$DAEMON_PID" > "$AUGER_DIR/daemon.pid"
        sleep 1
        if curl -sf "http://localhost:${DAEMON_PORT}/health" >/dev/null 2>&1; then
            echo "[OK]  Host tools daemon running (PID $DAEMON_PID)"
        else
            echo "[WARN]   Daemon may still be starting — continuing anyway"
        fi
    else
        echo "[OK]  Host tools daemon already running"
    fi

    # Export venv mode so widgets can detect it
    export AUGER_MODE=venv
    DISPLAY_VAL="$(detect_display)"
    install_desktop_launchers
    DISPLAY="$DISPLAY_VAL" bash "$TRAY_START_SCRIPT" >/dev/null 2>&1 || true

    if [ "$BACKGROUND_MODE" -eq 1 ]; then
        if [ -f "$VENV_PID_FILE" ]; then
            _old_pid="$(cat "$VENV_PID_FILE" 2>/dev/null || true)"
            if [ -n "$_old_pid" ] && kill -0 "$_old_pid" 2>/dev/null; then
                echo "[OK]  Auger host mode is already running (PID $_old_pid)"
                exit 0
            fi
            rm -f "$VENV_PID_FILE"
        fi

        echo "[START]  Starting Auger (venv mode) in the background..."
        nohup env AUGER_MODE=venv DISPLAY="$DISPLAY_VAL" PATH="$PATH" AUGER_VENV_BIN="$AUGER_VENV_BIN" "$VENV_DIR/bin/python3" -m auger start \
            >> "$VENV_LOG_FILE" 2>&1 &
        _venv_pid=$!
        echo "$_venv_pid" > "$VENV_PID_FILE"
        sleep 2
        if kill -0 "$_venv_pid" 2>/dev/null; then
            echo "[OK]  Auger host mode running (PID $_venv_pid)"
            echo "   Log: $VENV_LOG_FILE"
            exit 0
        fi
        echo "[ERROR]  Auger host mode failed to stay running."
        echo "   Check: $VENV_LOG_FILE"
        exit 1
    fi

    echo "[START]  Starting Auger (venv mode)..."
    echo ""
    echo "   Auger window will appear on your display."
    echo "   To stop: Ctrl+C or close the window."
    echo ""

    exec env AUGER_MODE=venv DISPLAY="$DISPLAY_VAL" PATH="$PATH" AUGER_VENV_BIN="$AUGER_VENV_BIN" "$VENV_DIR/bin/python3" -m auger start
fi

# ─────────────────────────────────────────────────────────────────────────────
# DOCKER MODE  (original flow)
# ─────────────────────────────────────────────────────────────────────────────

# ── 1. Docker check ───────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    echo "[ERROR]  Docker not found. Please install Docker Desktop or Docker Engine first."
    exit 1
fi

if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    DISPLAY_VAL="$(detect_display)"
    echo "[OK]  Auger container already running — opening the existing platform window..."
    if docker exec -d -e DISPLAY="$DISPLAY_VAL" "$CONTAINER" auger start >/dev/null 2>&1; then
        exit 0
    fi
    echo "[WARN]   Could not activate the existing Auger UI — continuing with full startup path."
fi

start_progress_dialog
progress_msg "Starting Auger launcher..."

# ── 2. Base image selection ───────────────────────────────────────────────────
# Default behavior prefers the local base image built from the current checkout
# so launcher, tray, and install_wizard all share the same early-adopter path.
# Set AUGER_PREFER_REMOTE_BASE=1 to opt back into the Artifactory base image.
_art_registry="artifactory.helix.gsa.gov"
BASE_IMAGE="$IMAGE"
read_env_key() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    grep -E "^${key}=" "$file" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "'\"" || true
}

run_low_priority() {
    if [ "${AUGER_LOW_PRIORITY_BUILD:-1}" != "1" ]; then
        "$@"
        return $?
    fi
    if command -v ionice >/dev/null 2>&1; then
        ionice -c3 nice -n 19 "$@"
        return $?
    fi
    if command -v nice >/dev/null 2>&1; then
        nice -n 19 "$@"
        return $?
    fi
    "$@"
}

find_proxy_url() {
    local port
    for port in 9000 10800 3128 8080; do
        if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
           netstat -tlnp 2>/dev/null | grep -q ":${port} "; then
            printf 'http://127.0.0.1:%s\n' "$port"
            return 0
        fi
    done
    return 1
}

compute_local_base_build_hash() {
    local git_head dirty_hash
    if git_head="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null)"; then
        if git -C "$REPO_DIR" diff --quiet --ignore-submodules HEAD -- 2>/dev/null && \
           git -C "$REPO_DIR" diff --cached --quiet --ignore-submodules HEAD -- 2>/dev/null; then
            printf '%s\n' "$git_head"
            return 0
        fi
        dirty_hash="$(git -C "$REPO_DIR" status --porcelain --untracked-files=no 2>/dev/null | md5sum | cut -d' ' -f1)"
        printf '%s-%s\n' "$git_head" "$dirty_hash"
        return 0
    fi

    cat \
        "$REPO_DIR/Dockerfile" \
        "$REPO_DIR/Dockerfile.user" \
        "$REPO_DIR/scripts/entrypoint.sh" \
        "$REPO_DIR/requirements.txt" \
        "$REPO_DIR/pyproject.toml" \
        "$REPO_DIR/setup.cfg" \
        "$REPO_DIR/install.sh" \
        2>/dev/null | md5sum | cut -d' ' -f1
}

build_local_base_image() {
    local reason="$1"
    local force_rebuild="${AUGER_FORCE_REBUILD_BASE:-0}"
    local build_hash
    local existing_hash
    local current_commit
    local proxy_url
    local build_args=()

    progress_msg "$reason"

    build_hash="$(compute_local_base_build_hash)"
    existing_hash="$(docker inspect --format='{{index .Config.Labels "build-hash"}}' "$LOCAL_BASE_IMAGE" 2>/dev/null || true)"

    if [ "$force_rebuild" != "1" ] && [ -n "$existing_hash" ] && [ "$existing_hash" = "$build_hash" ]; then
        BASE_IMAGE="$LOCAL_BASE_IMAGE"
        progress_msg "Local Auger base image already up to date: ${BASE_IMAGE}"
        return 0
    fi

    current_commit="$(git -C "$REPO_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    if proxy_url="$(find_proxy_url)"; then
        build_args+=(
            --build-arg "http_proxy=${proxy_url}"
            --build-arg "https_proxy=${proxy_url}"
            --build-arg "HTTP_PROXY=${proxy_url}"
            --build-arg "HTTPS_PROXY=${proxy_url}"
        )
        progress_msg "Passing proxy ${proxy_url} to local base image build..."
    fi

    progress_msg "Building local Auger base image from this checkout..."
    progress_msg "Running local base-image build at reduced CPU/I/O priority to keep your workspace responsive..."
    if run_low_priority env BUILD_HASH="$build_hash" GIT_COMMIT="$current_commit" DOCKER_BUILDKIT=0 docker build \
        --network host \
        "${build_args[@]}" \
        --build-arg "GIT_COMMIT=${current_commit}" \
        --build-arg "BUILD_HASH=${build_hash}" \
        -f "$REPO_DIR/Dockerfile" \
        -t "$LOCAL_BASE_IMAGE" \
        "$REPO_DIR" 2>&1 | tee -a "$PROGRESS_LOG"; then
        BASE_IMAGE="$LOCAL_BASE_IMAGE"
        progress_msg "Local Auger base image ready: ${BASE_IMAGE}"
        return 0
    fi

    progress_error "Local Auger base image build failed."
    exit 1
}

art_image_access_ok() {
    local image="$1"
    [ -n "$image" ] || return 1
    docker manifest inspect "$image" >/dev/null 2>&1
}

_art_last_error=""
art_login_with_key() {
    local user="$1" key="$2" image="$3"
    [ -n "$user" ] && [ -n "$key" ] || {
        _art_last_error="missing"
        return 1
    }
    if ! printf '%s' "$key" | docker login "$_art_registry" -u "$user" --password-stdin >/dev/null 2>&1; then
        _art_last_error="login"
        return 1
    fi
    if ! art_image_access_ok "$image"; then
        _art_last_error="access"
        return 1
    fi
    _art_last_error=""
    return 0
}

_art_user="${ARTIFACTORY_USERNAME:-${ARTIFACTORY_USER:-}}"
_art_identity="${ARTIFACTORY_IDENTITY_TOKEN:-}"
PREFER_REMOTE_BASE="${AUGER_PREFER_REMOTE_BASE:-0}"
if [ -z "$_art_user" ]; then
    _art_user=$(read_env_key "$AUGER_DIR/.env" "ARTIFACTORY_USERNAME")
fi
if [ -z "$_art_user" ]; then
    _art_user=$(read_env_key "$AUGER_DIR/.env" "ARTIFACTORY_USER")
fi
[ -z "$_art_identity" ] && _art_identity=$(read_env_key "$AUGER_DIR/.env" "ARTIFACTORY_IDENTITY_TOKEN")

_art_authenticated=false
if [ "${AUGER_FORCE_LOCAL_BASE:-0}" = "1" ] || [ "$PREFER_REMOTE_BASE" != "1" ]; then
    if [ "${AUGER_FORCE_LOCAL_BASE:-0}" = "1" ]; then
        build_local_base_image "Install Wizard requested a local Auger base image build from this checkout."
    else
        build_local_base_image "Using the local Auger base image strategy for this checkout."
    fi
else
    if art_login_with_key "$_art_user" "$_art_identity" "$BASE_IMAGE"; then
        echo "🔐  Logged in to Artifactory with saved Identity Token."
        _art_authenticated=true
    else
        if [ -n "$_art_identity" ] && [ "$_art_last_error" = "access" ]; then
            echo "[WARN]   Saved Identity Token logged in but cannot read ${BASE_IMAGE}."
        fi
    fi

    if [ "$_art_authenticated" = false ]; then
        if [ "${AUGER_WIZARD:-0}" != "1" ] && [ -t 0 ]; then
            progress_msg "Logging in to Artifactory..."
            if docker login "$_art_registry" && art_image_access_ok "$BASE_IMAGE"; then
                _art_authenticated=true
            else
                progress_msg "Artifactory Docker pull access is unavailable for this account."
            fi
        else
            progress_msg "No working Artifactory Docker pull access detected non-interactively."
        fi
    fi

    if [ "$_art_authenticated" = false ]; then
        build_local_base_image "Falling back to a local Auger base image build because the Artifactory Docker repo is not accessible."
    else
        progress_msg "Using Artifactory base image: ${BASE_IMAGE}"
    fi
fi

# ── 3. Pull base image + build personalized image ────────────────────────────
# Sanitize username for use as a Docker image tag:
# Domain usernames like bobbygblair@gtd.gsa.gov are invalid in tags.
# Strip domain suffix and replace any remaining non-alphanumeric chars with -.
_SAFE_USER="$(echo "${USER}" | sed 's/@.*//' | tr -cs 'a-zA-Z0-9' '-' | sed 's/-$//' | tr 'A-Z' 'a-z')"
PERSONALIZED_IMAGE="auger-platform-${_SAFE_USER}:latest"
FORCE_REBUILD_PERSONALIZED="${AUGER_FORCE_REBUILD_PERSONALIZED:-0}"

if [ "$FORCE_REBUILD_PERSONALIZED" = "1" ]; then
    progress_msg "Forcing personalized image rebuild to pick up latest local code..."
elif docker image inspect "$PERSONALIZED_IMAGE" >/dev/null 2>&1; then
    progress_msg "Personalized image already present: ${PERSONALIZED_IMAGE}"
fi

if [ "$FORCE_REBUILD_PERSONALIZED" = "1" ] || ! docker image inspect "$PERSONALIZED_IMAGE" >/dev/null 2>&1; then
    if [ "$BASE_IMAGE" = "$IMAGE" ]; then
        progress_msg "Pulling Auger base image..."
        docker pull "$BASE_IMAGE" 2>&1 | tee -a "$PROGRESS_LOG"
    else
        progress_msg "Using local Auger base image: ${BASE_IMAGE}"
    fi

    progress_msg "Building personalized image for ${USER} (this can take a few minutes)..."
    progress_msg "Running personalized-image build at reduced CPU/I/O priority to keep your workspace responsive..."
    # Force legacy builder (DOCKER_BUILDKIT=0) — docker buildx hangs on layer export
    # for large images on this platform. Legacy builder completes reliably.
    # NOTE: no --network=host here — Dockerfile.user only does useradd+mkdir+chown,
    # needs no network. --network=host caused useradd to hang querying domain AD/LDAP
    # with large domain UIDs on domain-joined WorkSpaces.
    if run_low_priority env DOCKER_BUILDKIT=0 docker build --no-cache \
        -f "$REPO_DIR/Dockerfile.user" \
        --build-arg "BASE_IMAGE=${BASE_IMAGE}" \
        --build-arg "HOST_USER=${_SAFE_USER}" \
        --build-arg "HOST_UID=$(id -u)" \
        --build-arg "HOST_GID=$(id -g)" \
        -t "$PERSONALIZED_IMAGE" \
        "$REPO_DIR" 2>&1 | tee -a "$PROGRESS_LOG"; then
        progress_msg "Personalized image ready: ${PERSONALIZED_IMAGE}"
    else
        progress_error "Personalized image build failed."
        exit 1
    fi
fi

# ── 4. Stop any existing container ───────────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    progress_msg "Stopping existing Auger container..."
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
fi

# ── 5. Ensure ~/.auger exists ─────────────────────────────────────────────────
mkdir -p "$AUGER_DIR"
touch "$AUGER_DIR/.env"

# ── 6. Detect display ────────────────────────────────────────────────────────
DISPLAY_VAL="$(detect_display)"

# ── 7. Detect Zscaler proxy ──────────────────────────────────────────────────
PROXY_ARGS=""
for port in 9000 10800 3128 8080; do
    if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
        PROXY_URL="http://127.0.0.1:${port}"
        PROXY_ARGS="-e http_proxy=$PROXY_URL -e https_proxy=$PROXY_URL -e HTTP_PROXY=$PROXY_URL -e HTTPS_PROXY=$PROXY_URL"
        echo "[SECURE]  Proxy detected on port ${port}"
        break
    fi
done

# ── 8. Load token if already configured ──────────────────────────────────────
GH_TOKEN_ARG=""
if [ -f "$AUGER_DIR/.env" ]; then
    _tok=$(grep -E '^(GHE_TOKEN|GH_TOKEN)=' "$AUGER_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "'\"" || true)
    [ -n "$_tok" ] && GH_TOKEN_ARG="-e GH_TOKEN=$_tok"
fi

# ── 9. Allow X11 connections ─────────────────────────────────────────────────
xhost +local: >/dev/null 2>&1 || true

# ── Ensure .env readable ──────────────────────────────────────────────────────
# Container runs as the host user (same uid) — .env is already readable.
# chmod is a no-op but kept as a safety net for first-run edge cases.
chmod 644 "$AUGER_DIR/.env" 2>/dev/null || true

# ── 10. Start Host Tools Daemon (BEFORE container) ───────────────────────────
# Must be running before the UI starts so /schedule_restart, browser launch,
# and Jira MFA auth are all available the moment the platform opens.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DAEMON_SCRIPT="$SCRIPT_DIR/host_tools_daemon.py"
if [ -f "$DAEMON_SCRIPT" ]; then
    OLD_DAEMON=$(lsof -ti "tcp:${DAEMON_PORT}" 2>/dev/null | head -1 || true)
    [ -n "$OLD_DAEMON" ] && kill "$OLD_DAEMON" 2>/dev/null && sleep 1
    progress_msg "Starting host tools daemon..."
    nohup python3 "$DAEMON_SCRIPT" >> "$AUGER_DIR/daemon.log" 2>&1 &
    DAEMON_PID=$!
    disown $DAEMON_PID
    for i in $(seq 1 20); do
        if curl -sf --noproxy localhost "http://localhost:${DAEMON_PORT}/health" >/dev/null 2>&1; then
            echo "[OK]  Daemon ready (PID $DAEMON_PID)"
            echo "$DAEMON_PID" > "$AUGER_DIR/daemon.pid"
            break
        fi
        sleep 0.5
    done
else
    echo "[WARN]   Daemon script not found at $DAEMON_SCRIPT — skipping"
fi

# ── 11. Start container ───────────────────────────────────────────────────────
progress_msg "Starting Auger on personalized image..."
CONTAINER_HOME="/home/${_SAFE_USER}"
CONTAINER_USER="$(id -u):$(id -g)"
REPOS_MOUNT=""
[ -d "$HOME/repos" ] && REPOS_MOUNT="-v $HOME/repos:${CONTAINER_HOME}/repos"

KUBE_MOUNT=""
[ -d "$HOME/.kube" ] && KUBE_MOUNT="-v $HOME/.kube:${CONTAINER_HOME}/.kube:ro"

SSH_MOUNT=""
[ -d "$HOME/.ssh" ] && SSH_MOUNT="-v $HOME/.ssh:${CONTAINER_HOME}/.ssh:ro"

GITCONFIG_MOUNT=""
[ -f "$HOME/.gitconfig" ] && GITCONFIG_MOUNT="-v $HOME/.gitconfig:${CONTAINER_HOME}/.gitconfig:ro"

# Ask Auger session state (copilot events.jsonl lives here)
COPILOT_MOUNT=""
[ -d "$HOME/.copilot" ] && COPILOT_MOUNT="-v $HOME/.copilot:${CONTAINER_HOME}/.copilot"

# Host Copilot CLI binary for in-container Ask Auger fallback
COPILOT_BIN_MOUNT=""
[ -x "$HOME/.local/bin/copilot" ] && COPILOT_BIN_MOUNT="-v $HOME/.local/bin/copilot:/usr/local/bin/copilot:ro"

# Docker socket for Cryptkeeper/Prospector widgets
# Also pass --group-add so the auger user inside the container can connect to the daemon.
# On Amazon WorkSpaces the socket is owned by root:video (GID 44) -- not root:docker.
DOCKER_SOCK_MOUNT=""
DOCKER_SOCK_GROUP=""
if [ -S /var/run/docker.sock ]; then
    DOCKER_SOCK_MOUNT="-v /var/run/docker.sock:/var/run/docker.sock"
    _sock_gid=$(stat -c '%g' /var/run/docker.sock 2>/dev/null || true)
    [ -n "$_sock_gid" ] && DOCKER_SOCK_GROUP="--group-add $_sock_gid"
fi

# Chrome binary for Host Tools browser launch
CHROME_MOUNT=""
[ -d /opt/google/chrome ] && CHROME_MOUNT="-v /opt/google/chrome:/opt/google/chrome:ro"

# DNS fix: 169.254.169.253 (AWS VPC DNS) is unreachable from inside the container
# even with --network host. Build a patched resolv.conf mounting 8.8.8.8 as the
# primary nameserver so RDS/private hostnames (*.rds.amazonaws.com) resolve.
AUGER_RESOLV="/tmp/auger-resolv.conf"
{
    grep -v '^nameserver' /etc/resolv.conf 2>/dev/null || true
    echo "nameserver 8.8.8.8"
    echo "nameserver 1.1.1.1"
    grep '^nameserver' /etc/resolv.conf 2>/dev/null | grep -v '169\.254\.' || true
} > "$AUGER_RESOLV"
RESOLV_MOUNT="-v $AUGER_RESOLV:/etc/resolv.conf:ro"

# ── DNS detection ─────────────────────────────────────────────────────────────
# Amazon WorkSpaces use systemd-resolved with a 127.0.0.53 stub resolver that
# is unreachable from inside Docker containers. Detect the real upstream DNS
# servers and pass them via --dns so internal hostnames (RDS, Artifactory, etc.)
# resolve correctly inside the container.
DNS_ARGS=""
if command -v resolvectl &>/dev/null; then
    while read -r ns; do
        [ -n "$ns" ] && DNS_ARGS="$DNS_ARGS --dns $ns"
    done < <(resolvectl status 2>/dev/null | awk '/DNS Servers:/{for(i=3;i<=NF;i++) print $i}' | sort -u | head -4)
fi
if [ -z "$DNS_ARGS" ] && [ -f /etc/resolv.conf ]; then
    while IFS= read -r line; do
        case "$line" in
            nameserver\ *)
                ns="${line#nameserver }"
                # Skip loopback (127.x.x.x) and link-local (169.254.x.x) — unreachable inside containers
                case "$ns" in 127.*|169.254.*) ;; *) DNS_ARGS="$DNS_ARGS --dns $ns" ;; esac ;;
        esac
    done < /etc/resolv.conf
fi
# Hard fallback: if no non-loopback DNS found, use GSA-reachable public resolvers
[ -z "$DNS_ARGS" ] && DNS_ARGS="--dns 8.8.8.8 --dns 8.8.4.4"
progress_msg "Preparing container DNS and mounts..."

if ! docker run -d \
    --name "$CONTAINER" \
    --network host \
    --security-opt seccomp:unconfined \
    --user "$CONTAINER_USER" \
    -e DISPLAY="$DISPLAY_VAL" \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v "$AUGER_DIR:${CONTAINER_HOME}/.auger" \
    -v /:/host:ro \
    ${REPOS_MOUNT} \
    ${KUBE_MOUNT} \
    ${SSH_MOUNT} \
    ${GITCONFIG_MOUNT} \
    ${COPILOT_MOUNT} \
    ${COPILOT_BIN_MOUNT} \
    ${DOCKER_SOCK_MOUNT} \
    ${DOCKER_SOCK_GROUP} \
    ${CHROME_MOUNT} \
    ${RESOLV_MOUNT} \
    ${GH_TOKEN_ARG} \
    ${PROXY_ARGS} \
    ${DNS_ARGS} \
    "$PERSONALIZED_IMAGE" \
    auger start 2>&1 | tee -a "$PROGRESS_LOG"; then
    progress_error "Failed to launch Auger container."
    exit 1
fi

# ── 12. Wait for UI ───────────────────────────────────────────────────────────
progress_msg "Waiting for Auger UI to start..."
sleep 5

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    progress_msg "Auger container exited during startup. Recent container logs:"
    docker logs --tail 120 "$CONTAINER" 2>&1 | tee -a "$PROGRESS_LOG" || true
    progress_error "Auger container failed to start. Check docker logs auger-platform."
    exit 1
fi

# ── 12b. Host pip dependencies (no sudo needed) ──────────────────────────────
if ! python3 -c "import faster_whisper" 2>/dev/null; then
    echo "[PKG]  Installing faster-whisper for voice transcription..."
    pip3 install --user --quiet faster-whisper 2>/dev/null \
        && echo "[OK]  faster-whisper installed" \
        || echo "[WARN]  faster-whisper install failed — voice transcription disabled (run: pip3 install --user faster-whisper)"
fi

install_desktop_launchers
progress_msg "GNOME launchers installed."
progress_msg "Tray autostart registered."
progress_msg "Auger startup complete."
progress_done

# ── 14. Start System Tray Applet ─────────────────────────────────────────────
DISPLAY="${DISPLAY_VAL}" bash "$SCRIPT_DIR/start-auger-tray.sh"

echo ""
echo "[OK]  Auger is running!"
echo ""
echo "   The Auger window should appear on your screen."
echo "   The system tray icon (🤖) gives you Open / Ask / Restart / Stop controls."
echo ""
echo "   To stop Auger:  docker rm -f auger-platform"
echo ""
