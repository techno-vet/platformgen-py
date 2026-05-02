"""
auger.tools.git_workflow
~~~~~~~~~~~~~~~~~~~~~~~~
Auto-managed feature branches for widget changes.

When a user creates or modifies a widget (via Ask Auger or directly), the
platform calls these helpers to:
  1. Locate the canonical ~/repos/auger-ai-sre-platform clone
  2. Create a feature branch  feature/widget-<name>-YYYYMMDD
  3. Commit the widget file with a meaningful message
  4. Push the branch to origin
  5. Return a PR URL for the user to open

Works from both host terminal and inside the container (~/repos is mounted
into the container at /home/auger/repos).
"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional


# ── Repo discovery ─────────────────────────────────────────────────────────────

def get_auger_repo() -> Optional[Path]:
    """Return the path to the auger-ai-sre-platform git repo.

    Search order:
      1. ~/repos/auger-ai-sre-platform  (canonical developer location)
      2. /home/auger/repos/auger-ai-sre-platform  (container path)
      3. The directory containing this file (dev/work-folder fallback)
    """
    candidates = [
        Path.home() / "repos" / "auger-ai-sre-platform",
        Path("/home/auger/repos/auger-ai-sre-platform"),
        Path(__file__).parent.parent.parent,  # auger/tools/git_workflow.py → repo root
    ]
    for path in candidates:
        if (path / ".git").exists():
            return path
    return None


# ── Low-level git helpers ──────────────────────────────────────────────────────

def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo)] + list(args),
        capture_output=True, text=True, check=check
    )


def current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def branch_exists(repo: Path, branch: str) -> bool:
    result = _git(repo, "branch", "--list", branch, check=False)
    return bool(result.stdout.strip())


def remote_exists(repo: Path) -> bool:
    result = _git(repo, "remote", check=False)
    return bool(result.stdout.strip())


def get_remote_url(repo: Path) -> str:
    result = _git(repo, "remote", "get-url", "origin", check=False)
    return result.stdout.strip()


# ── Feature branch workflow ───────────────────────────────────────────────────

def make_branch_name(widget_name: str) -> str:
    """Generate a branch name like feature/widget-my-widget-20260302."""
    slug = re.sub(r"[^a-z0-9]+", "-", widget_name.lower().replace(".py", "")).strip("-")
    date = datetime.now().strftime("%Y%m%d")
    return f"feature/widget-{slug}-{date}"


def ensure_feature_branch(repo: Path, widget_name: str) -> str:
    """Switch to (or create) the feature branch for a widget.

    If already on a feature/widget-* branch for this widget, stays there.
    Returns the branch name.
    """
    branch = make_branch_name(widget_name)
    existing = current_branch(repo)

    if existing == branch:
        return branch

    if branch_exists(repo, branch):
        _git(repo, "checkout", branch)
    else:
        _git(repo, "checkout", "-b", branch)

    return branch


def commit_widget(repo: Path, widget_file: Path, message: str | None = None) -> str:
    """Stage and commit a widget file. Returns the short commit SHA."""
    rel = widget_file.relative_to(repo) if widget_file.is_absolute() else widget_file
    widget_name = widget_file.stem
    if not message:
        message = (
            f"feat: add/update widget {widget_name}\n\n"
            f"Auto-committed by Auger platform via git_workflow.\n\n"
            f"Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
        )
    _git(repo, "add", str(rel))
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "--short", "HEAD").stdout.strip()


def _https_env(repo: Path) -> dict:
    """Build env vars for HTTPS push: GHE credentials + Zscaler cert."""
    env = os.environ.copy()
    # Zscaler cert — look in repo zscaler_certs/ dir
    cert = repo / "zscaler_certs" / "ZscalerRootCertificate-2048-SHA256.crt"
    if cert.exists():
        env["GIT_SSL_CAINFO"] = str(cert)
    return env


def push_to_origin(repo: Path, branch: str, upstream: bool = False) -> "subprocess.CompletedProcess":
    """Push branch to origin using HTTPS+GHE_TOKEN+Zscaler cert.

    Sets a temporary HTTPS remote with credentials, pushes, then restores
    the original remote URL (usually SSH).
    """
    ghe_token = os.environ.get("GHE_TOKEN", "")
    ghe_user = os.environ.get("GHE_USERNAME", "")
    ghe_url = os.environ.get("GHE_URL", "")

    original_url = get_remote_url(repo)

    if ghe_token and ghe_user and ghe_url:
        # Build HTTPS URL with credentials
        https_url = f"{ghe_url.rstrip('/')}/{_remote_path(original_url)}"
        cred_url = https_url.replace("https://", f"https://{ghe_user}:{ghe_token}@")
        _git(repo, "remote", "set-url", "origin", cred_url)

    push_args = ["push", "-u", "origin", branch] if upstream else ["push", "origin", branch]
    env = _https_env(repo)
    result = subprocess.run(
        ["git", "-C", str(repo)] + push_args,
        capture_output=True, text=True, check=False, env=env,
    )

    # Restore original remote URL
    if original_url:
        _git(repo, "remote", "set-url", "origin", original_url, check=False)

    return result


def _remote_path(remote_url: str) -> str:
    """Extract org/repo.git from any remote URL form."""
    # git@host:org/repo.git  →  org/repo.git
    m = re.match(r"git@[^:]+:(.+)", remote_url)
    if m:
        return m.group(1)
    # https://host/org/repo.git  →  org/repo.git
    m = re.match(r"https?://[^/]+/(.+)", remote_url)
    if m:
        return m.group(1)
    return remote_url


def push_branch(repo: Path, branch: str) -> bool:
    """Push the branch to origin. Returns True on success."""
    result = push_to_origin(repo, branch, upstream=True)
    return result.returncode == 0


def get_pr_url(repo: Path, branch: str) -> str:
    """Build a 'compare & open PR' URL for the branch on GHE/GitHub."""
    remote = get_remote_url(repo)
    if not remote:
        return ""
    # Normalise SSH → HTTPS
    # git@github.helix.gsa.gov:org/repo.git  →  https://github.helix.gsa.gov/org/repo
    ssh_match = re.match(r"git@([^:]+):(.+?)(?:\.git)?$", remote)
    if ssh_match:
        host, path = ssh_match.groups()
        base = f"https://{host}/{path}"
    else:
        base = re.sub(r"\.git$", "", remote)
    return f"{base}/compare/{branch}?expand=1"


# ── High-level entry point ────────────────────────────────────────────────────

def handle_widget_change(widget_path: str | Path) -> dict:
    """Full workflow: branch → commit → push → return result dict.

    Returns a dict with keys:
      success (bool), branch (str), sha (str), pr_url (str), message (str)
    """
    widget_path = Path(widget_path).expanduser()
    repo = get_auger_repo()
    if not repo:
        return {"success": False, "message": "Could not find auger-ai-sre-platform repo"}

    # If path is relative or tilde-expanded but still missing, try resolving
    # against the repo widgets directory
    if not widget_path.exists() and not widget_path.is_absolute():
        widget_path = repo / "auger" / "ui" / "widgets" / widget_path.name

    if not widget_path.exists():
        return {"success": False, "message": f"Widget file not found: {widget_path}"}

    try:
        branch = ensure_feature_branch(repo, widget_path.stem)
        sha = commit_widget(repo, widget_path)
        pushed = push_branch(repo, branch)
        pr_url = get_pr_url(repo, branch) if pushed else ""
        return {
            "success": True,
            "branch": branch,
            "sha": sha,
            "pushed": pushed,
            "pr_url": pr_url,
            "message": (
                f"Committed to branch `{branch}` ({sha})"
                + (f" — [Open PR]({pr_url})" if pr_url else " (push failed)")
            ),
        }
    except subprocess.CalledProcessError as e:
        return {"success": False, "message": f"Git error: {e.stderr or e}"}
    except Exception as e:
        return {"success": False, "message": str(e)}
