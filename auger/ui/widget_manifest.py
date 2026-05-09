"""
widget_manifest.py — PlatformGen Widget AI Manifest Loader

Two-tier knowledge architecture:
  1. Static tier  — auger/data/widget_manifests.yaml  (git-committed, describes all widgets)
  2. Learned tier — ~/.platformgen/widget_knowledge/{widget_name}.yaml  (runtime discoveries by Genny)

Usage:
    from platformgen.ui.widget_manifest import build_manifest_context, save_learned
    context = build_manifest_context()   # compact [WIDGET KNOWLEDGE] block for prompt injection
    save_learned("gchat", "AUGER channel is paused — use AUGER_POC")
"""

from __future__ import annotations
import yaml
from pathlib import Path
from platformgen.runtime import repo_dir, state_dir

# Static manifest file (shipped with platform)
_STATIC_CANDIDATES = [
    Path(__file__).parent.parent / "data" / "widget_manifests.yaml",
    Path(__file__).resolve().parents[2] / "auger" / "data" / "widget_manifests.yaml",
    Path(__file__).resolve().parents[2] / "platformgen" / "data" / "widget_manifests.yaml",
]

# Learned knowledge directory (runtime-owned, persists across sessions)
LEARNED_DIR = state_dir() / "widget_knowledge"

_repo = repo_dir()
if _repo:
    _STATIC_CANDIDATES.extend([
        _repo / "auger" / "data" / "widget_manifests.yaml",
        _repo / "platformgen" / "data" / "widget_manifests.yaml",
    ])


def _load_static() -> dict:
    seen: set[Path] = set()
    for candidate in _STATIC_CANDIDATES:
        candidate = Path(candidate)
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            try:
                data = yaml.safe_load(candidate.read_text()) or {}
                return data.get("widgets", {})
            except Exception:
                pass
    return {}


def _load_learned(widget_name: str) -> dict:
    path = LEARNED_DIR / f"{widget_name}.yaml"
    if path.exists():
        try:
            return yaml.safe_load(path.read_text()) or {}
        except Exception:
            pass
    return {}


def save_learned(widget_name: str, discovery: str) -> None:
    """Persist a new discovery about a widget to the learned tier.
    
    Call this when Genny discovers something about a widget through actual use
    that should be remembered across sessions.
    
    Example:
        save_learned("gchat", "AUGER channel is paused — route to AUGER_POC")
        save_learned("jira", "JSESSIONID expires ~24h after MFA login")
    """
    LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    path = LEARNED_DIR / f"{widget_name}.yaml"
    data = _load_learned(widget_name)
    discoveries = data.get("discoveries", [])
    if discovery not in discoveries:
        discoveries.append(discovery)
    data["discoveries"] = discoveries
    from datetime import datetime
    data["last_updated"] = datetime.now().isoformat(timespec="seconds")
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def build_manifest_context(max_widgets: int = 20) -> str:
    """Build compact [WIDGET KNOWLEDGE] block for injection into every prompt.

    Returns a string like:
        [WIDGET KNOWLEDGE]
        - gchat (Google Chat): Posts messages to GChat via webhooks.
          depends_on: api_config | used_by: story_to_prod, tasks
          ⚑ Always read webhook URL from gchat_webhooks.yaml
          💡 AUGER channel paused — use AUGER_POC
        ...
    """
    statics = _load_static()
    if not statics:
        return ""

    lines = ["[WIDGET KNOWLEDGE]"]
    for widget_name, manifest in list(statics.items())[:max_widgets]:
        title   = manifest.get("title", widget_name)
        purpose = manifest.get("purpose", "")
        depends = ", ".join(manifest.get("depends_on", [])) or "none"
        used_by = ", ".join(manifest.get("used_by", [])) or "none"
        rules   = manifest.get("auger_rules", [])
        files   = manifest.get("key_data_files", [])

        lines.append(f"- {widget_name} ({title}): {purpose}")
        if depends != "none" or used_by != "none":
            lines.append(f"  depends_on: {depends} | used_by: {used_by}")
        for rule in rules:
            lines.append(f"  ⚑ {rule}")
        for f in files:
            lines.append(f"  📄 {f}")
        hint = manifest.get("session_resume_hint", "")
        if hint:
            lines.append(f"  ↩ {hint}")

        # Learned tier — runtime discoveries
        learned = _load_learned(widget_name)
        for disc in learned.get("discoveries", []):
            lines.append(f"  💡 {disc}")

    lines.append("")
    return "\n".join(lines)
