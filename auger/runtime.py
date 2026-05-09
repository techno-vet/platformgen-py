from __future__ import annotations

import os
from pathlib import Path


def _env(*keys: str, default: str = "") -> str:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    return default


def state_dir() -> Path:
    configured = _env("PLATFORMGEN_HOME", "AUGER_HOME")
    return Path(configured).expanduser() if configured else Path.home() / ".platformgen"


def app_name() -> str:
    return _env("PLATFORMGEN_APP_NAME", "AUGER_APP_NAME", default="PlatformGen")


def product_name() -> str:
    return _env("PLATFORMGEN_PRODUCT_NAME", "AUGER_PRODUCT_NAME", default=app_name())


def assistant_name() -> str:
    return _env("PLATFORMGEN_ASSISTANT_NAME", "AUGER_ASSISTANT_NAME", default="Genny")


def cli_name() -> str:
    return _env("PLATFORMGEN_CLI_NAME", "AUGER_CLI_NAME", default="genny")


def daemon_port() -> int:
    try:
        return int(_env("PLATFORMGEN_DAEMON_PORT", "AUGER_DAEMON_PORT", default="7438"))
    except ValueError:
        return 7438


def daemon_url() -> str:
    return f"http://localhost:{daemon_port()}"


def host_home() -> Path:
    for key in ("PLATFORMGEN_HOST_HOME", "AUGER_HOST_HOME", "HOME"):
        value = os.environ.get(key)
        if value and value != "/home/auger":
            return Path(value).expanduser()
    return Path.home()


def window_class() -> str:
    return _env("PLATFORMGEN_WM_CLASS", "AUGER_WM_CLASS", default="platformgen-platform")


def repo_dir() -> Path | None:
    configured = _env("PLATFORMGEN_REPO_DIR", "AUGER_REPO_DIR")
    if configured:
        path = Path(configured).expanduser()
        if (path / ".git").exists():
            return path
    for candidate in [
        Path(__file__).resolve().parents[1],
        Path.cwd(),
        Path.home() / "projects" / "platformgen-py",
        Path.home() / "repos" / "platformgen-py",
        Path.home() / "repos" / "auger-ai-sre-platform",
    ]:
        if (candidate / ".git").exists():
            return candidate
    return None
