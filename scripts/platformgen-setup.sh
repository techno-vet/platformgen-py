#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# PlatformGen — First-Time Setup Script
#
# Detects credentials automatically (gh CLI, astutl/AU Gold, env vars, .env).
# Silently uses what it finds — only prompts if a credential fails validation.
# Detects Docker vs native Python venv mode automatically.
#
# Usage:  bash scripts/platformgen-setup.sh
#         bash scripts/platformgen-setup.sh --venv    # force venv mode
# ─────────────────────────────────────────────────────────────────────────────
set -e

STATE_DIR="${PLATFORMGEN_HOME:-${AUGER_HOME:-$HOME/.platformgen}}"
ENV_FILE="$STATE_DIR/.env"
export PLATFORMGEN_HOME="$STATE_DIR"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ASTUTL_ENV="$HOME/.astutl/astutl_secure_config.env"
ART_REGISTRY="artifactory.helix.gsa.gov"
APP_NAME="${PLATFORMGEN_APP_NAME:-${AUGER_APP_NAME:-PlatformGen}}"
ASSISTANT_NAME="${PLATFORMGEN_ASSISTANT_NAME:-${AUGER_ASSISTANT_NAME:-Genny}}"

# Parse --venv flag
FORCE_VENV=0
for arg in "$@"; do
    [ "$arg" = "--venv" ] && FORCE_VENV=1
done

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║         ${APP_NAME} — First-Time Setup                ║"
echo "╚══════════════════════════════════════════════════════╝"
echo ""

mkdir -p "$STATE_DIR"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

# ── Helper: write/update a key=value in .env ─────────────────────────────────
set_env_key() {
    local key="$1" val="$2"
    if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
    else
        echo "${key}=${val}" >> "$ENV_FILE"
    fi
}

# ── Helper: test a GH token against api.github.com ───────────────────────────
gh_token_valid() {
    local tok="$1"
    local http_code
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${tok}" \
        https://api.github.com/user 2>/dev/null || echo "000")
    [ "$http_code" = "200" ]
}

# ── Helper: test Artifactory docker login ────────────────────────────────────
art_login_valid() {
    local user="$1" key="$2"
    printf '%s' "$key" | docker login "$ART_REGISTRY" -u "$user" --password-stdin >/dev/null 2>&1
}

read_env_key() {
    local file="$1" key="$2"
    [ -f "$file" ] || return 0
    grep -E "^${key}=" "$file" 2>/dev/null | head -1 | cut -d= -f2- | tr -d "'\""
}

select_art_key() {
    local user="$1" identity_token="$2"
    if [ -n "$identity_token" ] && art_login_valid "$user" "$identity_token"; then
        echo "$identity_token"
        return 0
    fi
    return 1
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — GitHub Copilot token
# ─────────────────────────────────────────────────────────────────────────────
echo "[SEARCH]  Checking GitHub Copilot token..."
GH_TOKEN_VAL=""
GH_TOKEN_SOURCE=""

# Priority order: .env → gh CLI → GH_TOKEN env → GITHUB_TOKEN env → gh config file → git credential store
_tok=$(grep -E '^GH_TOKEN=' "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-)
[ -n "$_tok" ] && GH_TOKEN_VAL="$_tok" && GH_TOKEN_SOURCE="~/.platformgen/.env"

if [ -z "$GH_TOKEN_VAL" ] && command -v gh &>/dev/null; then
    _tok=$(gh auth token 2>/dev/null || true)
    [ -n "$_tok" ] && GH_TOKEN_VAL="$_tok" && GH_TOKEN_SOURCE="gh CLI"
fi

if [ -z "$GH_TOKEN_VAL" ] && [ -n "${GH_TOKEN:-}" ]; then
    GH_TOKEN_VAL="$GH_TOKEN"
    GH_TOKEN_SOURCE="GH_TOKEN env var"
fi

if [ -z "$GH_TOKEN_VAL" ] && [ -n "${GITHUB_TOKEN:-}" ]; then
    GH_TOKEN_VAL="$GITHUB_TOKEN"
    GH_TOKEN_SOURCE="GITHUB_TOKEN env var"
fi

if [ -z "$GH_TOKEN_VAL" ] && [ -f "$HOME/.config/gh/hosts.yml" ]; then
    _tok=$(grep -A2 'github.com' "$HOME/.config/gh/hosts.yml" 2>/dev/null | grep 'oauth_token\|token:' | head -1 | awk '{print $2}')
    [ -n "$_tok" ] && GH_TOKEN_VAL="$_tok" && GH_TOKEN_SOURCE="~/.config/gh/hosts.yml"
fi

if [ -z "$GH_TOKEN_VAL" ]; then
    _tok=$(git credential fill <<< $'protocol=https\nhost=github.com' 2>/dev/null | grep '^password=' | cut -d= -f2- || true)
    if [[ "$_tok" == ghp_* ]] || [[ "$_tok" == github_pat_* ]]; then
        GH_TOKEN_VAL="$_tok"
        GH_TOKEN_SOURCE="git credential store"
    fi
fi

if [ -n "$GH_TOKEN_VAL" ]; then
    echo -n "   Found token via ${GH_TOKEN_SOURCE} — verifying... "
    if gh_token_valid "$GH_TOKEN_VAL"; then
        echo "[OK] valid"
        set_env_key "GH_TOKEN" "$GH_TOKEN_VAL"
    else
        echo "[ERROR] token rejected by github.com"
        GH_TOKEN_VAL=""
    fi
fi

# Only prompt if no valid token was found
while [ -z "$GH_TOKEN_VAL" ]; do
    echo ""
    echo "   No valid GitHub Copilot token found."
    echo "   Get one at: https://github.com/settings/tokens → Generate new token (classic)"
    echo "   Required scopes: repo  read:user  (copilot if available)"
    echo ""
    read -rp "   Paste your token (github.com): " user_token
    if [ -z "$user_token" ]; then
        echo "   [WARN]  Skipping — Ask ${ASSISTANT_NAME} will not work. Add GH_TOKEN to ~/.platformgen/.env later."
        break
    fi
    echo -n "   Verifying... "
    if gh_token_valid "$user_token"; then
        echo "[OK] valid"
        set_env_key "GH_TOKEN" "$user_token"
        GH_TOKEN_VAL="$user_token"
    else
        echo "[ERROR] github.com rejected that token — please try again"
    fi
done

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Choose launch mode (Docker vs native venv)
# ─────────────────────────────────────────────────────────────────────────────
echo ""
LAUNCH_FLAGS=""

if [ "$FORCE_VENV" -eq 1 ]; then
    echo "   Venv mode requested (--venv flag)."
    LAUNCH_FLAGS="--venv"
elif ! command -v docker &>/dev/null; then
    echo "   Docker not found — switching to native Python venv mode automatically."
    echo "   (Works on Windows, macOS, and Linux without Docker.)"
    LAUNCH_FLAGS="--venv"
else
    echo "   How would you like to run ${APP_NAME}?"
    echo "   [1] Docker (containerized, recommended)"
    echo "   [2] Native Python venv (lighter, no Docker admin rights needed)"
    echo ""
    read -rp "   Choose [1/2] (default: 1): " launch_choice
    launch_choice="${launch_choice:-1}"
    [ "$launch_choice" = "2" ] && LAUNCH_FLAGS="--venv"
fi

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Artifactory credentials (Docker mode only)
# ─────────────────────────────────────────────────────────────────────────────
if [ -z "$LAUNCH_FLAGS" ]; then
    echo ""
    echo "   Checking Artifactory credentials..."
    ART_USER=""
    ART_KEY=""
    ART_SOURCE=""

    # Priority: .env → astutl/AU Gold
    _u=$(read_env_key "$ENV_FILE" "ARTIFACTORY_USERNAME")
    [ -z "$_u" ] && _u=$(read_env_key "$ENV_FILE" "ARTIFACTORY_USER")
    _it=$(read_env_key "$ENV_FILE" "ARTIFACTORY_IDENTITY_TOKEN")
    if [ -n "$_u" ] && [ -n "$_it" ]; then
        ART_USER="$_u"; ART_IT="$_it"; ART_SOURCE="~/.platformgen/.env"
    fi

    if [ -z "$ART_USER" ] && [ -f "$ASTUTL_ENV" ]; then
        _u=$(read_env_key "$ASTUTL_ENV" "ARTIFACTORY_USERNAME")
        [ -z "$_u" ] && _u=$(read_env_key "$ASTUTL_ENV" "ARTIFACTORY_USER")
        _it=$(read_env_key "$ASTUTL_ENV" "ARTIFACTORY_IDENTITY_TOKEN")
        if [ -n "$_u" ] && [ -n "$_it" ]; then
            ART_USER="$_u"; ART_IT="$_it"; ART_SOURCE="~/.astutl (AU Gold)"
            [ -n "$_it" ] && set_env_key "ARTIFACTORY_IDENTITY_TOKEN" "$_it"
            set_env_key "ARTIFACTORY_USERNAME" "$_u"
        fi
    fi

    if [ -n "$ART_USER" ] && [ -n "${ART_IT:-}" ]; then
        echo -n "   Found identity token via ${ART_SOURCE} — testing Docker login... "
        if ART_KEY=$(select_art_key "$ART_USER" "${ART_IT:-}"); then
            echo "ok"
            set_env_key "ARTIFACTORY_USERNAME" "$ART_USER"
            [ -n "${ART_IT:-}" ] && set_env_key "ARTIFACTORY_IDENTITY_TOKEN" "$ART_IT"
        else
            echo "login failed"
            ART_USER=""; ART_KEY=""
        fi
    fi

    # Only prompt if login failed or no creds found
    while [ -z "$ART_USER" ] || [ -z "$ART_KEY" ]; do
        echo ""
        echo "   Artifactory credentials needed to pull the ${APP_NAME} Docker image."
        echo "   Get your Identity Token: https://artifactory.helix.gsa.gov → Profile → Identity Token"
        echo ""
        if [ -z "$ART_USER" ]; then
            read -rp "   Artifactory username (FCS username): " ART_USER
            [ -z "$ART_USER" ] && echo "   Cannot pull image without username." && break
        fi
        read -rsp "   Artifactory Identity Token: " ART_KEY
        echo ""
        [ -z "$ART_KEY" ] && echo "   Cannot pull image without token." && break
        echo -n "   Testing Docker login... "
        if art_login_valid "$ART_USER" "$ART_KEY"; then
            echo "ok"
            set_env_key "ARTIFACTORY_USERNAME" "$ART_USER"
            set_env_key "ARTIFACTORY_IDENTITY_TOKEN" "$ART_KEY"
            break
        else
            echo "login failed — check your username and token and try again"
            ART_USER=""; ART_KEY=""
        fi
    done
fi

# ── Step 4: Launch PlatformGen ────────────────────────────────────────────────
echo ""
echo "[OK]  Setup complete! Launching ${APP_NAME}..."
echo ""

bash "$SCRIPT_DIR/platformgen-launch.sh" $LAUNCH_FLAGS
