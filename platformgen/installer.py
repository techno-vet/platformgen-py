from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path


APP_NAME = os.environ.get("PLATFORMGEN_APP_NAME") or os.environ.get("AUGER_APP_NAME", "PlatformGen")
ASSISTANT_NAME = os.environ.get("PLATFORMGEN_ASSISTANT_NAME") or os.environ.get("AUGER_ASSISTANT_NAME", "Genny")
DEFAULT_STATE_DIR = Path(
    os.environ.get("PLATFORMGEN_HOME")
    or os.environ.get("AUGER_HOME")
    or str(Path.home() / ".platformgen")
).expanduser()
DEFAULT_REPO_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DAEMON_PORT = int(os.environ.get("PLATFORMGEN_DAEMON_PORT") or os.environ.get("AUGER_DAEMON_PORT") or "7438")
ENV_TEMPLATE_NAME = ".env.example"
INSTALL_METADATA = "install-metadata.json"
COPILOT_INSTALL_URL = "https://gh.io/copilot-install"
GHE_DEFAULT_URL = "https://github.helix.gsa.gov"

ASTUTL_CANDIDATES = [
    Path.home() / ".astutl" / "astutl_secure_config.env",
    Path.home() / "repos" / "devtools-scripts" / "au-silver" / "config" / ".astutl" / "astutl_secure_config.env",
    Path.home() / "repos" / "devtools-scripts" / "astutl" / "config" / ".astutl" / "astutl_secure_config.env",
    Path.home() / "repos" / "devtool-scripts-orig" / "au-silver" / "config" / ".astutl" / "astutl_secure_config.env",
    Path.home() / "repos" / "devtools-scripts-6.1" / "au-silver" / "config" / ".astutl" / "astutl_secure_config.env",
]

ASTUTL_KEY_MAP = {
    "ARTIFACTORY_IDENTITY_TOKEN": "ARTIFACTORY_IDENTITY_TOKEN",
    "ARTIFACTORY_USER": "ARTIFACTORY_USERNAME",
    "ARTIFACTORY_PASSWORD": "ARTIFACTORY_PASSWORD",
    "GH_TOKEN": "GH_TOKEN",
    "GH_CLI_PAT": "GH_TOKEN",
    "GH_ENTERPRISE_TOKEN": "GHE_TOKEN",
    "GSA_EMAIL": "GHE_USERNAME",
    "JIRA_PAT": "JIRA_API_TOKEN",
    "JENKINS_API_KEY": "JENKINS_API_TOKEN",
    "DD_API_KEY": "DATADOG_API_KEY",
    "DD_APP_KEY": "DATADOG_APP_KEY",
    "RANCHER_BEARER_TOKEN": "RANCHER_BEARER_TOKEN",
    "DEV_S3_AWS_ACCESS_KEY_ID": "AWS_1_ACCESS_KEY_ID",
    "DEV_S3_AWS_SECRET_ACCESS_KEY": "AWS_1_SECRET_ACCESS_KEY",
    "TEST_S3_AWS_ACCESS_KEY_ID": "AWS_2_ACCESS_KEY_ID",
    "TEST_S3_AWS_SECRET_ACCESS_KEY": "AWS_2_SECRET_ACCESS_KEY",
    "STAGING_S3_AWS_ACCESS_KEY_ID": "AWS_3_ACCESS_KEY_ID",
    "STAGING_S3_AWS_SECRET_ACCESS_KEY": "AWS_3_SECRET_ACCESS_KEY",
    "PROD_S3_AWS_ACCESS_KEY_ID": "AWS_4_ACCESS_KEY_ID",
    "PROD_S3_AWS_SECRET_ACCESS_KEY": "AWS_4_SECRET_ACCESS_KEY",
    "DEV_CRYPTKEEPER_KEY": "DEV_CRYPTKEEPER_KEY",
    "TEST_CRYPTKEEPER_KEY": "TEST_CRYPTKEEPER_KEY",
    "STAGING_CRYPTKEEPER_KEY": "STAGING_CRYPTKEEPER_KEY",
    "PROD_CRYPTKEEPER_KEY": "PROD_CRYPTKEEPER_KEY",
    "LOCAL_CRYPTKEEPER_KEY": "LOCAL_CRYPTKEEPER_KEY",
}


def _platform_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _state_env_file(state_dir: Path) -> Path:
    return state_dir / ".env"


def _config_file(state_dir: Path) -> Path:
    return state_dir / "config.yaml"


def _metadata_file(state_dir: Path) -> Path:
    return state_dir / INSTALL_METADATA


def _legacy_state_dir() -> Path:
    return Path.home() / ".auger"


def _venv_dir(state_dir: Path) -> Path:
    return state_dir / "venv"


def _venv_python(state_dir: Path) -> Path:
    if os.name == "nt":
        return _venv_dir(state_dir) / "Scripts" / "python.exe"
    return _venv_dir(state_dir) / "bin" / "python3"


def _venv_pythonw(state_dir: Path) -> Path:
    if os.name == "nt":
        return _venv_dir(state_dir) / "Scripts" / "pythonw.exe"
    return _venv_python(state_dir)


def _launcher_bin_dir(state_dir: Path) -> Path:
    return state_dir / "bin"


def _launcher_script_path(state_dir: Path) -> Path:
    suffix = ".pyw" if os.name == "nt" else ".py"
    return _launcher_bin_dir(state_dir) / f"platformgen-open{suffix}"


def _launcher_cmd_path(state_dir: Path) -> Path:
    return _launcher_bin_dir(state_dir) / "platformgen-open.cmd"


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_env_key(path: Path, key: str) -> str:
    if not path.exists():
        return ""
    prefix = f"{key}="
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if raw.startswith(prefix):
            return raw[len(prefix):].strip().strip("'\"")
    return ""


def _set_env_key(path: Path, key: str, value: str) -> None:
    _ensure_parent(path)
    if not path.exists():
        path.touch(mode=0o600)
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    prefix = f"{key}="
    updated = False
    new_lines: list[str] = []
    for line in lines:
        if line.startswith(prefix):
            new_lines.append(f"{key}={value}")
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines).rstrip() + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _seed_env_template(state_dir: Path, repo_dir: Path) -> bool:
    env_file = _state_env_file(state_dir)
    template = repo_dir / ENV_TEMPLATE_NAME
    state_dir.mkdir(parents=True, exist_ok=True)
    if env_file.exists() and env_file.read_text(encoding="utf-8", errors="replace").strip():
        return False
    if template.exists():
        env_file.write_text(template.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    else:
        env_file.touch()
    try:
        env_file.chmod(0o600)
    except OSError:
        pass
    return True


def _copy_legacy_state(state_dir: Path) -> bool:
    source_dir = _legacy_state_dir()
    if not source_dir.exists() or source_dir == state_dir:
        return False
    state_dir.mkdir(parents=True, exist_ok=True)
    copied = False
    ignore_names = {
        "venv",
        ".copilot.lock",
        ".session_id",
        ".session_snapshot.json",
        "daemon.log",
        "tray.log",
        "startup-progress.log",
        "icons",
    }
    def _ignore_transient(_src: str, names: list[str]) -> set[str]:
        ignored = set(ignore_names)
        for name in names:
            try:
                if Path(_src, name).is_symlink():
                    ignored.add(name)
            except OSError:
                ignored.add(name)
        return ignored

    for item in source_dir.iterdir():
        if item.name in ignore_names:
            continue
        if item.is_symlink():
            continue
        target = state_dir / item.name
        if target.exists():
            continue
        try:
            if item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True, ignore=_ignore_transient)
            else:
                shutil.copy2(item, target)
        except OSError:
            continue
        copied = True
    return copied


def _find_astutl_file() -> Path | None:
    for candidate in ASTUTL_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _import_astutl(path: Path, env_file: Path) -> list[tuple[str, str]]:
    imported: list[tuple[str, str]] = []
    for source_key, dest_key in ASTUTL_KEY_MAP.items():
        value = _read_env_key(path, source_key)
        if not value or _read_env_key(env_file, dest_key):
            continue
        _set_env_key(env_file, dest_key, value)
        imported.append((dest_key, source_key))
    return imported


def _read_gh_hosts_token(hostname: str) -> str:
    gh_cfg = Path.home() / ".config" / "gh" / "hosts.yml"
    if not gh_cfg.exists():
        return ""
    current_host = ""
    for raw in gh_cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not raw.startswith((" ", "\t")) and line.endswith(":"):
            current_host = line[:-1].strip()
            continue
        if current_host == hostname:
            stripped = line.strip()
            if stripped.startswith(("oauth_token:", "token:")):
                return stripped.split(":", 1)[1].strip().strip("'\"")
    return ""


def _read_git_credential_token(hostname: str) -> str:
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        result = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost={hostname}\n".encode(),
            capture_output=True,
            env=env,
            timeout=5,
        )
        for line in result.stdout.decode(errors="replace").splitlines():
            if line.startswith("password="):
                return line[9:].strip()
    except Exception:
        pass
    return ""


def _gh_token_valid(token: str) -> bool:
    if not token:
        return False
    try:
        req = urllib.request.Request(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "platformgen-installer/1.0",
            },
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(req, timeout=8) as response:
            return response.status == 200
    except Exception:
        return False


def _ghe_token_valid(token: str, ghe_api_user: str) -> bool:
    if not token:
        return False
    try:
        req = urllib.request.Request(
            ghe_api_user,
            headers={
                "Authorization": f"token {token}",
                "User-Agent": "platformgen-installer/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            return response.status == 200
    except Exception:
        return False


def _detect_ghe_context(env_file: Path) -> tuple[str, str, str]:
    ghe_url = _read_env_key(env_file, "GHE_URL") or GHE_DEFAULT_URL
    parsed = urllib.parse.urlparse(ghe_url.rstrip("/"))
    host = parsed.netloc or parsed.path.split("/")[0] or "github.helix.gsa.gov"
    api_user = "https://api.github.com/user" if host == "github.com" else f"{ghe_url.rstrip('/')}/api/v3/user"
    return host, ghe_url.rstrip("/"), api_user


def _detect_gh_token(env_file: Path) -> tuple[str, str]:
    token = _read_env_key(env_file, "GH_TOKEN")
    if token:
        return token, "~/.platformgen/.env"

    for var in ("GH_TOKEN", "GITHUB_TOKEN", "COPILOT_GITHUB_TOKEN"):
        value = os.environ.get(var, "")
        if value:
            return value, f"${var}"

    try:
        result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), "gh CLI"
    except Exception:
        pass

    token = _read_gh_hosts_token("github.com")
    if token:
        return token, "~/.config/gh/hosts.yml"

    token = _read_git_credential_token("github.com")
    if token and token.startswith(("ghp_", "github_pat_")):
        return token, "git credential store"

    astutl_path = _find_astutl_file()
    if astutl_path:
        for key in ("GH_TOKEN", "GH_CLI_PAT"):
            value = _read_env_key(astutl_path, key)
            if value:
                return value, f"astutl ({key})"
    return "", ""


def _detect_ghe_token(env_file: Path, host: str) -> tuple[str, str]:
    token = _read_env_key(env_file, "GHE_TOKEN")
    if token:
        return token, "~/.platformgen/.env"

    for var in ("GHE_TOKEN", "GH_ENTERPRISE_TOKEN"):
        value = os.environ.get(var, "")
        if value:
            return value, f"${var}"

    try:
        result = subprocess.run(
            ["gh", "auth", "token", "--hostname", host],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), f"gh CLI ({host})"
    except Exception:
        pass

    token = _read_gh_hosts_token(host)
    if token:
        return token, "~/.config/gh/hosts.yml"

    token = _read_git_credential_token(host)
    if token:
        return token, "git credential store"

    astutl_path = _find_astutl_file()
    if astutl_path:
        token = _read_env_key(astutl_path, "GH_ENTERPRISE_TOKEN")
        if token:
            return token, "astutl (GH_ENTERPRISE_TOKEN)"
    return "", ""


class InstallUI:
    interactive = True

    def log(self, message: str, level: str = "info") -> None:
        raise NotImplementedError

    def status(self, message: str) -> None:
        self.log(message, "dim")

    def ask_text(self, prompt: str, default: str = "", secret: bool = False) -> str:
        raise NotImplementedError

    def confirm(self, prompt: str, default: bool = True) -> bool:
        raise NotImplementedError


class CLIInstallUI(InstallUI):
    def __init__(self, interactive: bool = True):
        self.interactive = interactive

    def log(self, message: str, level: str = "info") -> None:
        print(message)

    def ask_text(self, prompt: str, default: str = "", secret: bool = False) -> str:
        if not self.interactive:
            return default
        suffix = f" [{default}]" if default else ""
        if secret:
            value = getpass.getpass(f"{prompt}{suffix}: ")
        else:
            value = input(f"{prompt}{suffix}: ")
        return value.strip() or default

    def confirm(self, prompt: str, default: bool = True) -> bool:
        if not self.interactive:
            return default
        default_label = "Y/n" if default else "y/N"
        answer = input(f"{prompt} [{default_label}]: ").strip().lower()
        if not answer:
            return default
        return answer in {"y", "yes", "1", "true"}


@dataclass
class InstallOptions:
    state_dir: Path
    repo_dir: Path
    daemon_port: int
    launch: bool = True
    create_launchers: bool = True
    interactive: bool = True
    install_copilot: str = "auto"  # auto|skip|always
    copy_legacy_state: bool = True


def _run(cmd: list[str], *, env: dict | None = None, timeout: int | None = None, check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=timeout, check=check)


def _ensure_python_version(ui: InstallUI) -> None:
    if sys.version_info < (3, 10):
        raise RuntimeError("Python 3.10 or newer is required.")
    ui.log(f"[OK] Using Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")


def _create_venv(state_dir: Path, ui: InstallUI) -> Path:
    venv_dir = _venv_dir(state_dir)
    python_path = _venv_python(state_dir)
    if not python_path.exists():
        ui.log(f"[PKG] Creating virtual environment at {venv_dir}")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    else:
        ui.log(f"[OK] Reusing virtual environment at {venv_dir}")
    return python_path


def _install_editable_repo(state_dir: Path, repo_dir: Path, ui: InstallUI) -> None:
    python_path = _venv_python(state_dir)
    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    ui.log("[PKG] Installing PlatformGen into the virtual environment")
    subprocess.run([str(python_path), "-m", "pip", "install", "--upgrade", "pip"], check=True, env=env)
    subprocess.run([str(python_path), "-m", "pip", "install", "--editable", str(repo_dir)], check=True, env=env)


def _init_config(state_dir: Path, token: str, ui: InstallUI) -> None:
    config_file = _config_file(state_dir)
    if config_file.exists():
        ui.log(f"[OK] Existing config found at {config_file}")
        return
    ui.log("[SETUP] Initializing PlatformGen runtime state")
    python_path = _venv_python(state_dir)
    snippet = textwrap.dedent(
        """
        from pathlib import Path
        from auger.config_manager import AugerConfigManager

        config_dir = Path(sys.argv[1])
        token = sys.argv[2]
        manager = AugerConfigManager(config_dir)
        manager.init(github_token=token)
        """
    )
    subprocess.run([str(python_path), "-c", f"import sys\n{snippet}", str(state_dir), token], check=True)


def _copilot_available() -> bool:
    candidates = [
        shutil.which("copilot"),
        str(Path.home() / ".local" / "bin" / "copilot"),
    ]
    if os.name == "nt":
        local_app = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates.extend([
            shutil.which("copilot.exe"),
            str(local_app / "Microsoft" / "WindowsApps" / "copilot.exe"),
            str(local_app / "Programs" / "GitHub Copilot" / "copilot.exe"),
        ])
    return any(candidate and Path(candidate).exists() for candidate in candidates)


def _install_copilot_cli(options: InstallOptions, ui: InstallUI) -> None:
    if _copilot_available():
        ui.log("[OK] GitHub Copilot CLI already available")
        return
    if options.install_copilot == "skip":
        ui.log(f"[WARN] GitHub Copilot CLI not found. Install it later so Ask {ASSISTANT_NAME} works.")
        return

    should_install = options.install_copilot == "always" or ui.confirm(
        f"Install the GitHub Copilot CLI for Ask {ASSISTANT_NAME}?",
        default=True,
    )
    if not should_install:
        ui.log(f"[WARN] Skipping Copilot CLI install. Ask {ASSISTANT_NAME} will stay limited until it is installed.")
        return

    if os.name == "nt":
        winget = shutil.which("winget")
        if winget:
            ui.log("[PKG] Installing GitHub Copilot CLI via winget")
            subprocess.run(
                [winget, "install", "--accept-package-agreements", "--accept-source-agreements", "GitHub.Copilot"],
                check=False,
            )
        else:
            ui.log("[WARN] winget not found. Install GitHub Copilot CLI later with: winget install GitHub.Copilot")
    else:
        if not shutil.which("curl") or not shutil.which("bash"):
            ui.log(f"[WARN] curl/bash not found. Install GitHub Copilot CLI later from {COPILOT_INSTALL_URL}")
            return
        ui.log("[PKG] Installing GitHub Copilot CLI")
        subprocess.run(
            ["bash", "-lc", f"curl -fsSL {COPILOT_INSTALL_URL} | bash"],
            check=False,
        )

    if _copilot_available():
        ui.log("[OK] GitHub Copilot CLI installed")
    else:
        ui.log(f"[WARN] GitHub Copilot CLI install did not complete. Ask {ASSISTANT_NAME} may require a manual install step.")


def _write_metadata(options: InstallOptions) -> None:
    payload = {
        "installed_at": time.time(),
        "platform": _platform_name(),
        "state_dir": str(options.state_dir),
        "repo_dir": str(options.repo_dir),
        "daemon_port": options.daemon_port,
        "venv_python": str(_venv_python(options.state_dir)),
        "launcher_script": str(_launcher_script_path(options.state_dir)),
    }
    path = _metadata_file(options.state_dir)
    _ensure_parent(path)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _launcher_script_content(state_dir: Path, repo_dir: Path, daemon_port: int, detach: bool = True) -> str:
    return textwrap.dedent(
        f"""\
        #!/usr/bin/env python3
        from pathlib import Path
        import sys

        REPO_DIR = Path({str(repo_dir)!r})
        if str(REPO_DIR) not in sys.path:
            sys.path.insert(0, str(REPO_DIR))

        from platformgen.installer import launch_installed

        raise SystemExit(
            launch_installed(
                state_dir=Path({str(state_dir)!r}),
                repo_dir=REPO_DIR,
                daemon_port={int(daemon_port)},
                detach={bool(detach)!r},
            )
        )
        """
    )


def _write_runtime_launcher(options: InstallOptions, ui: InstallUI) -> Path:
    launcher_path = _launcher_script_path(options.state_dir)
    launcher_path.parent.mkdir(parents=True, exist_ok=True)
    launcher_path.write_text(
        _launcher_script_content(options.state_dir, options.repo_dir, options.daemon_port),
        encoding="utf-8",
    )
    try:
        launcher_path.chmod(launcher_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass

    if os.name == "nt":
        cmd_path = _launcher_cmd_path(options.state_dir)
        pythonw = _venv_pythonw(options.state_dir)
        cmd_path.write_text(
            "@echo off\r\n"
            f"start \"\" \"{pythonw}\" \"{launcher_path}\"\r\n",
            encoding="utf-8",
        )
        ui.log(f"[OK] Created Windows launcher wrapper at {cmd_path}")
    else:
        ui.log(f"[OK] Created launcher script at {launcher_path}")

    return launcher_path


def _render_icon_with_venv(state_dir: Path, repo_dir: Path, destination: Path, image_format: str) -> None:
    python_path = _venv_python(state_dir)
    code = textwrap.dedent(
        f"""
        import sys
        from pathlib import Path
        sys.path.insert(0, {str(repo_dir)!r})
        from platformgen.ui.icons import load_app_icon
        dest = Path({str(destination)!r})
        dest.parent.mkdir(parents=True, exist_ok=True)
        img = load_app_icon(256)
        img.save(dest, format={image_format!r})
        """
    )
    subprocess.run([str(python_path), "-c", code], check=True)


def _install_linux_launcher(options: InstallOptions, launcher_script: Path, ui: InstallUI) -> Path:
    icon_path = Path.home() / ".local" / "share" / "icons" / "platformgen-platform.png"
    desktop_path = Path.home() / ".local" / "share" / "applications" / "platformgen.desktop"
    _render_icon_with_venv(options.state_dir, options.repo_dir, icon_path, "PNG")
    desktop_path.parent.mkdir(parents=True, exist_ok=True)
    desktop_path.write_text(
        textwrap.dedent(
            f"""\
            [Desktop Entry]
            Version=1.0
            Type=Application
            Name={APP_NAME}
            GenericName=Host Platform
            Comment=Launch {APP_NAME} on this host
            Exec={launcher_script}
            Icon={icon_path}
            Terminal=false
            Categories=Development;System;
            StartupWMClass=platformgen-platform
            Keywords=platformgen;host;venv;widgets;
            """
        ),
        encoding="utf-8",
    )
    try:
        desktop_path.chmod(desktop_path.stat().st_mode | stat.S_IXUSR)
    except OSError:
        pass
    subprocess.run(["update-desktop-database", str(desktop_path.parent)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ui.log(f"[OK] Installed Linux launcher at {desktop_path}")
    return desktop_path


def _ps_escape(value: str) -> str:
    return value.replace("`", "``").replace('"', '`"')


def _create_windows_shortcut(shortcut_path: Path, target: str, arguments: str, icon_path: str, working_directory: str) -> bool:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if not powershell:
        return False
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    script = textwrap.dedent(
        f'''
        $WshShell = New-Object -ComObject WScript.Shell
        $Shortcut = $WshShell.CreateShortcut("{_ps_escape(str(shortcut_path))}")
        $Shortcut.TargetPath = "{_ps_escape(target)}"
        $Shortcut.Arguments = "{_ps_escape(arguments)}"
        $Shortcut.IconLocation = "{_ps_escape(icon_path)}"
        $Shortcut.WorkingDirectory = "{_ps_escape(working_directory)}"
        $Shortcut.Save()
        '''
    )
    result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True)
    return result.returncode == 0


def _install_windows_launcher(options: InstallOptions, launcher_script: Path, ui: InstallUI) -> Path:
    local_appdata = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    icon_path = local_appdata / "PlatformGen" / "icons" / "platformgen.ico"
    _render_icon_with_venv(options.state_dir, options.repo_dir, icon_path, "ICO")

    pythonw = _venv_pythonw(options.state_dir)
    desktop_shortcut = Path.home() / "Desktop" / f"{APP_NAME}.lnk"
    start_menu_shortcut = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "PlatformGen" / f"{APP_NAME}.lnk"

    created_any = False
    args = str(launcher_script)
    for shortcut in (desktop_shortcut, start_menu_shortcut):
        created_any = _create_windows_shortcut(shortcut, str(pythonw), args, str(icon_path), str(options.repo_dir)) or created_any

    if created_any:
        ui.log(f"[OK] Installed Windows shortcuts for {APP_NAME}")
    else:
        ui.log(f"[WARN] Could not create Windows shortcuts automatically. Launcher script is at {launcher_script}")
    return start_menu_shortcut


def install_launchers(options: InstallOptions, ui: InstallUI) -> list[Path]:
    launcher_script = _write_runtime_launcher(options, ui)
    if not options.create_launchers:
        return [launcher_script]
    if os.name == "nt":
        return [launcher_script, _install_windows_launcher(options, launcher_script, ui)]
    if sys.platform == "darwin":
        ui.log("[INFO] macOS launcher generation is intentionally deferred, but the installer core is adapter-ready.")
        return [launcher_script]
    return [launcher_script, _install_linux_launcher(options, launcher_script, ui)]


def _detect_display() -> str:
    display = os.environ.get("DISPLAY", "").strip()
    if display:
        return display
    for candidate in (":1", ":0"):
        socket_path = Path("/tmp/.X11-unix") / f"X{candidate[1:]}"
        if socket_path.exists():
            return candidate
    return ":0"


def _daemon_health(daemon_port: int) -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://localhost:{daemon_port}/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def _spawn_detached(cmd: list[str], *, env: dict, stdout, stderr):
    kwargs = {"env": env, "stdout": stdout, "stderr": stderr}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs)


def launch_installed(state_dir: Path, repo_dir: Path, daemon_port: int, detach: bool = True, ui: InstallUI | None = None) -> int:
    state_dir = Path(state_dir).expanduser()
    repo_dir = Path(repo_dir).expanduser()
    python_path = _venv_python(state_dir)
    if not python_path.exists():
        if ui:
            ui.log(f"[ERROR] Venv python not found at {python_path}")
        return 1

    env = os.environ.copy()
    env["PLATFORMGEN_HOME"] = str(state_dir)
    env["AUGER_HOME"] = str(state_dir)
    env["PLATFORMGEN_DAEMON_PORT"] = str(daemon_port)
    env["AUGER_DAEMON_PORT"] = str(daemon_port)
    env["AUGER_MODE"] = "venv"
    if os.name != "nt":
        env["DISPLAY"] = _detect_display()

    daemon_script = repo_dir / "scripts" / "host_tools_daemon.py"
    if daemon_script.exists() and not _daemon_health(daemon_port):
        daemon_log = state_dir / "daemon.log"
        daemon_log.parent.mkdir(parents=True, exist_ok=True)
        with daemon_log.open("a", encoding="utf-8") as handle:
            _spawn_detached([str(python_path), str(daemon_script)], env=env, stdout=handle, stderr=handle)
        if ui:
            ui.log(f"[OK] Started host tools daemon on port {daemon_port}")

    cmd = [str(python_path), "-m", "platformgen", "start", "--config-dir", str(state_dir)]
    if detach:
        log_path = state_dir / "venv-platform.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            proc = _spawn_detached(cmd, env=env, stdout=handle, stderr=handle)
        time.sleep(1.5)
        running = proc.poll() is None
        if ui:
            if running:
                ui.log(f"[OK] {APP_NAME} started in the background")
            else:
                ui.log(f"[ERROR] {APP_NAME} exited before startup completed")
        return 0 if running else 1

    result = subprocess.run(cmd, env=env)
    return result.returncode


def _write_detected_tokens(state_dir: Path, ui: InstallUI, interactive: bool) -> tuple[str, str]:
    env_file = _state_env_file(state_dir)
    host, ghe_url, ghe_api_user = _detect_ghe_context(env_file)
    gh_token, gh_source = _detect_gh_token(env_file)
    ghe_token, ghe_source = _detect_ghe_token(env_file, host)

    if gh_token:
        ui.log(f"[INFO] Found GitHub token via {gh_source}")
        if _gh_token_valid(gh_token):
            _set_env_key(env_file, "GH_TOKEN", gh_token)
            ui.log("[OK] Saved GitHub token for Ask Genny")
        else:
            ui.log("[WARN] Saved GitHub token candidate was rejected by github.com")
            gh_token = ""

    if not gh_token and interactive:
        gh_token = ui.ask_text(
            "GitHub Fine-Grained PAT for Copilot (blank to skip)",
            default="",
            secret=True,
        ).strip()
        if gh_token:
            if _gh_token_valid(gh_token):
                _set_env_key(env_file, "GH_TOKEN", gh_token)
                ui.log("[OK] Stored GitHub token")
            else:
                ui.log("[WARN] github.com rejected that token; continuing without GH_TOKEN")
                gh_token = ""

    if ghe_token:
        ui.log(f"[INFO] Found Enterprise GitHub token via {ghe_source}")
        if _ghe_token_valid(ghe_token, ghe_api_user):
            _set_env_key(env_file, "GHE_URL", ghe_url)
            _set_env_key(env_file, "GHE_TOKEN", ghe_token)
            ui.log("[OK] Saved Enterprise GitHub token")
        else:
            ui.log(f"[WARN] Saved {host} token candidate was rejected")
            ghe_token = ""

    if not ghe_token and interactive:
        ghe_token = ui.ask_text(
            f"{host} token for the GitHub widget (blank to skip)",
            default="",
            secret=True,
        ).strip()
        if ghe_token:
            if _ghe_token_valid(ghe_token, ghe_api_user):
                _set_env_key(env_file, "GHE_URL", ghe_url)
                _set_env_key(env_file, "GHE_TOKEN", ghe_token)
                ui.log("[OK] Stored Enterprise GitHub token")
            else:
                ui.log(f"[WARN] {host} rejected that token; continuing without GHE_TOKEN")
                ghe_token = ""

    return gh_token, ghe_token


def run_install(options: InstallOptions, ui: InstallUI) -> dict[str, object]:
    options.state_dir = options.state_dir.expanduser()
    options.repo_dir = options.repo_dir.expanduser().resolve()
    env_file = _state_env_file(options.state_dir)

    ui.log("")
    ui.log(f"{APP_NAME} installer — host mode")
    ui.log("")
    _ensure_python_version(ui)

    seeded = _seed_env_template(options.state_dir, options.repo_dir)
    if seeded:
        ui.log(f"[OK] Seeded {env_file} from {ENV_TEMPLATE_NAME}")

    if options.copy_legacy_state:
        if _copy_legacy_state(options.state_dir):
            ui.log("[OK] Imported compatible state from ~/.auger")
        else:
            ui.log("[INFO] No compatible legacy state needed from ~/.auger")

    astutl_path = _find_astutl_file()
    if astutl_path:
        imported = _import_astutl(astutl_path, env_file)
        if imported:
            ui.log(f"[OK] Imported {len(imported)} credential key(s) from {astutl_path}")

    gh_token, ghe_token = _write_detected_tokens(options.state_dir, ui, options.interactive)

    _create_venv(options.state_dir, ui)
    _install_editable_repo(options.state_dir, options.repo_dir, ui)
    _init_config(options.state_dir, gh_token or "", ui)
    _write_metadata(options)

    if gh_token:
        _install_copilot_cli(options, ui)
    else:
        ui.log(f"[WARN] No GH_TOKEN configured yet. Ask {ASSISTANT_NAME} will stay limited until it is added.")

    launcher_paths = install_launchers(options, ui)
    report = {
        "state_dir": str(options.state_dir),
        "repo_dir": str(options.repo_dir),
        "launcher_paths": [str(path) for path in launcher_paths if path],
        "launched": False,
    }

    if options.launch:
        result = launch_installed(options.state_dir, options.repo_dir, options.daemon_port, detach=True, ui=ui)
        report["launched"] = result == 0
        if result != 0:
            raise RuntimeError(f"{APP_NAME} failed to launch after install.")

    ui.log("")
    ui.log(f"[OK] {APP_NAME} installation complete")
    ui.log(f"[INFO] State directory: {options.state_dir}")
    for path in report["launcher_paths"]:
        ui.log(f"[INFO] Launcher: {path}")
    return report


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} Python-first installer")
    sub = parser.add_subparsers(dest="command")

    install_parser = sub.add_parser("install", help="Install or upgrade PlatformGen")
    install_parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    install_parser.add_argument("--repo-dir", default=str(DEFAULT_REPO_DIR))
    install_parser.add_argument("--daemon-port", type=int, default=DEFAULT_DAEMON_PORT)
    install_parser.add_argument("--no-launch", action="store_true")
    install_parser.add_argument("--no-launchers", action="store_true")
    install_parser.add_argument("--non-interactive", action="store_true")
    install_parser.add_argument("--install-copilot", choices=("auto", "skip", "always"), default="auto")
    install_parser.add_argument("--skip-legacy-migration", action="store_true")

    launch_parser = sub.add_parser("launch", help="Launch an installed PlatformGen host runtime")
    launch_parser.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    launch_parser.add_argument("--repo-dir", default=str(DEFAULT_REPO_DIR))
    launch_parser.add_argument("--daemon-port", type=int, default=DEFAULT_DAEMON_PORT)
    launch_parser.add_argument("--foreground", action="store_true")

    args = parser.parse_args(argv)
    if not args.command:
        args.command = "install"
        if not hasattr(args, "state_dir"):
            defaults = parser.parse_args(["install"])
            for key, value in vars(defaults).items():
                setattr(args, key, value)
    return args


def main(argv: list[str] | None = None, ui: InstallUI | None = None) -> int:
    args = _parse_args(argv)
    if args.command == "launch":
        return launch_installed(
            state_dir=Path(args.state_dir),
            repo_dir=Path(args.repo_dir),
            daemon_port=args.daemon_port,
            detach=not args.foreground,
            ui=ui,
        )

    options = InstallOptions(
        state_dir=Path(args.state_dir),
        repo_dir=Path(args.repo_dir),
        daemon_port=args.daemon_port,
        launch=not args.no_launch,
        create_launchers=not args.no_launchers,
        interactive=not args.non_interactive,
        install_copilot=args.install_copilot,
        copy_legacy_state=not args.skip_legacy_migration,
    )
    runtime_ui = ui or CLIInstallUI(interactive=options.interactive)
    try:
        run_install(options, runtime_ui)
        return 0
    except subprocess.CalledProcessError as exc:
        runtime_ui.log(f"[ERROR] Command failed: {' '.join(str(part) for part in exc.cmd)}")
        if exc.stdout:
            runtime_ui.log(exc.stdout.strip())
        if exc.stderr:
            runtime_ui.log(exc.stderr.strip())
        return exc.returncode or 1
    except Exception as exc:
        runtime_ui.log(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
