from __future__ import annotations

import os
from pathlib import Path


def state_dir() -> Path:
    configured = os.environ.get("AUGER_HOME") or os.environ.get("PLATFORMGEN_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".auger"


def app_name() -> str:
    return os.environ.get("AUGER_APP_NAME", "Auger")


def product_name() -> str:
    return os.environ.get("AUGER_PRODUCT_NAME", f"{app_name()} Platform")


def assistant_name() -> str:
    return os.environ.get("AUGER_ASSISTANT_NAME", app_name())


def cli_name() -> str:
    return os.environ.get("AUGER_CLI_NAME", "auger")


def daemon_port() -> int:
    try:
        return int(os.environ.get("AUGER_DAEMON_PORT", "7437"))
    except ValueError:
        return 7437


def daemon_url() -> str:
    return f"http://localhost:{daemon_port()}"


def window_class() -> str:
    return os.environ.get("AUGER_WM_CLASS", "auger-platform")


def repo_dir() -> Path | None:
    configured = os.environ.get("AUGER_REPO_DIR")
    if configured:
        path = Path(configured).expanduser()
        if (path / ".git").exists():
            return path
    for candidate in [
        Path(__file__).resolve().parents[1],
        Path.cwd(),
        Path.home() / "projects" / "platformgen-py",
        Path.home() / "repos" / "auger-ai-sre-platform",
    ]:
        if (candidate / ".git").exists():
            return candidate
    return None
