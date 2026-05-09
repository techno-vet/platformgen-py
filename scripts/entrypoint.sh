#!/bin/bash
# PlatformGen - Container Entrypoint
# Auto-initializes runtime config if not already done.
#
# Option A (user-specific image): The container image is built by platformgen-launch.sh
# with the host user's uid/gid baked in via Dockerfile.user. PLATFORMGEN_HOST_HOME is
# set in the image ENV so all paths resolve correctly — no uid mismatch, no
# Permission Denied errors on shared mounts.
#
# Backward-compat fallback: if PLATFORMGEN_HOST_HOME / AUGER_HOST_HOME is not set,
# defaults to /home/auger so the old behavior is preserved.

_H="${PLATFORMGEN_HOST_HOME:-${AUGER_HOST_HOME:-/home/auger}}"

AUGER_CONFIG="${_H}/.auger/config.yaml"
AUGER_ENV="${_H}/.auger/.env"

# ── Live-code symlink resolution ──────────────────────────────────────────────
# Default (prod): symlink already points to auger_baked — no action needed.
# Dev mode: when explicitly requested, repoint the symlink to live code.
APP_HOME="/home/auger/auger-platform"
[ -d "/home/auger/platformgen-platform" ] && APP_HOME="/home/auger/platformgen-platform"
REPO_AUGER=""
for candidate in \
    "${_H}/repos/platformgen-py/auger" \
    "${_H}/projects/platformgen-py/auger" \
    "${_H}/repos/auger-ai-sre-platform/auger"
do
    if [ -d "$candidate" ]; then
        REPO_AUGER="$candidate"
        break
    fi
done
BAKED_AUGER="${APP_HOME}/auger_baked"
CURRENT_LINK="${APP_HOME}/auger"
USE_LIVE_REPO="${PLATFORMGEN_USE_LIVE_REPO:-${AUGER_USE_LIVE_REPO:-0}}"

if [ "$USE_LIVE_REPO" = "1" ] && [ -n "$REPO_AUGER" ] && [ -L "$CURRENT_LINK" ]; then
    # Dev launcher requested live code/hot-reload support.
    rm -f "$CURRENT_LINK" && ln -sfn "$REPO_AUGER" "$CURRENT_LINK" 2>/dev/null || true

    # Sync any new requirements from the live repo into a persistent user-owned package
    # directory on the runtime state volume. This survives container restarts without
    # needing a root-owned system install or a full image rebuild.
    PYPACKAGES="${_H}/.auger/pypackages"
    LIVE_REQ=""
    for candidate in \
        "${_H}/repos/platformgen-py/requirements.txt" \
        "${_H}/projects/platformgen-py/requirements.txt" \
        "${_H}/repos/auger-ai-sre-platform/requirements.txt"
    do
        if [ -f "$candidate" ]; then
            LIVE_REQ="$candidate"
            break
        fi
    done
    mkdir -p "$PYPACKAGES"
    if [ -n "$LIVE_REQ" ] && [ -f "$LIVE_REQ" ]; then
        pip install --quiet --target "$PYPACKAGES" -r "$LIVE_REQ" 2>/dev/null || true
    fi
    # Prepend to PYTHONPATH so imports find the persistent packages
    export PYTHONPATH="${PYPACKAGES}${PYTHONPATH:+:$PYTHONPATH}"
fi
# ─────────────────────────────────────────────────────────────────────────────

# ── Docker credentials symlink ────────────────────────────────────────────────
# Artifactory creds live in ~/.auger/.docker/config.json (host volume).
# Docker CLI expects ~/.docker/config.json — create symlink so widgets work.
if [ ! -e "${_H}/.docker" ] && [ -d "${_H}/.auger/.docker" ]; then
    ln -sfn "${_H}/.auger/.docker" "${_H}/.docker"
fi
# ─────────────────────────────────────────────────────────────────────────────

# Source .env for token (used only for first-time auger init)
if [ -f "$AUGER_ENV" ]; then
    set -a; source "$AUGER_ENV" 2>/dev/null || true; set +a
fi

TOKEN="${COPILOT_GITHUB_TOKEN:-${GH_TOKEN:-${GITHUB_TOKEN:-${GHE_TOKEN}}}}"

if [ ! -f "$AUGER_CONFIG" ] && [ -n "$TOKEN" ]; then
    echo "Initializing PlatformGen configuration..."
    platformgen init --token "$TOKEN" 2>/dev/null || auger init --token "$TOKEN" 2>/dev/null || true
    echo "PlatformGen initialized"
fi

# ── Ensure shared files exist and are writable ────────────────────────────────
# With a matching uid (Option A image) these are owned by the correct user and
# need no chmod. We still create them if missing for first-run scenarios.
mkdir -p "${_H}/.auger/logs/chat_history"
touch "${_H}/.auger/chat_history.jsonl"             2>/dev/null || true
touch "${_H}/.auger/logs/chat_history/conversations.jsonl" 2>/dev/null || true
touch "${_H}/.auger/.copilot.lock"                  2>/dev/null || true
touch "${_H}/.auger/logs/chat_history/draft.txt"    2>/dev/null || true

# ── Ensure copilot binary wrapper exists ──────────────────────────────────────
# The copilot CLI is a Node.js app distributed via ~/.copilot/pkg/. Create a
# wrapper script at ~/.local/bin/copilot so it's on PATH inside the container.
_COPILOT_PKG="${_H}/.copilot/pkg/linux-x64"
_COPILOT_WRAPPER="${_H}/.local/bin/copilot"
if [ ! -x "${_COPILOT_WRAPPER}" ] && ! command -v copilot >/dev/null 2>&1; then
    _COPILOT_JS="$(ls -d "${_COPILOT_PKG}"/*/index.js 2>/dev/null | sort -V | tail -1)"
    if [ -n "${_COPILOT_JS}" ]; then
        mkdir -p "${_H}/.local/bin"
        printf '#!/bin/bash\nexec node "%s" "$@"\n' "${_COPILOT_JS}" > "${_COPILOT_WRAPPER}"
        chmod +x "${_COPILOT_WRAPPER}"
    fi
fi
# ─────────────────────────────────────────────────────────────────────────────

# Run the provided command (or bash if none)
exec "${@:-/bin/bash}"
