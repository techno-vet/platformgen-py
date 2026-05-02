#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export AUGER_HOME="${AUGER_HOME:-$HOME/.platformgen}"
export AUGER_DAEMON_PORT="${AUGER_DAEMON_PORT:-7537}"
export AUGER_APP_NAME="${AUGER_APP_NAME:-PlatformGen}"
export AUGER_PRODUCT_NAME="${AUGER_PRODUCT_NAME:-PlatformGen}"
export AUGER_ASSISTANT_NAME="${AUGER_ASSISTANT_NAME:-Genny}"
export AUGER_CLI_NAME="${AUGER_CLI_NAME:-genny}"
export AUGER_WM_CLASS="${AUGER_WM_CLASS:-platformgen-platform}"
export AUGER_CONTAINER_NAME="${AUGER_CONTAINER_NAME:-platformgen-platform}"
export AUGER_LAUNCHER_TITLE="${AUGER_LAUNCHER_TITLE:-PlatformGen}"
export AUGER_TASK_TRAY_TITLE="${AUGER_TASK_TRAY_TITLE:-PlatformGen Task Tray}"
export AUGER_DESKTOP_SLUG="${AUGER_DESKTOP_SLUG:-platformgen}"
export AUGER_LAUNCHER_SCRIPT="${AUGER_LAUNCHER_SCRIPT:-$SCRIPT_DIR/platformgen-launch.sh}"
export AUGER_TRAY_START_SCRIPT="${AUGER_TRAY_START_SCRIPT:-$SCRIPT_DIR/start-platformgen-tray.sh}"
export AUGER_REPO_DIR="${AUGER_REPO_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"

"$SCRIPT_DIR/bootstrap-platformgen-state.sh"
exec bash "$SCRIPT_DIR/auger-launch.sh" "$@"
