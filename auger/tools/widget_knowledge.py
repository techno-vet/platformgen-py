"""
widget_knowledge.py — WIDGET_AI_MANIFEST tools for Auger.

Two-tier knowledge architecture:
  1. Static YAML   — auger/data/widget_manifests.yaml  (all widgets; Auger-editable)
  2. Learned tier  — ~/.auger/widget_knowledge/{widget_name}.yaml  (runtime discoveries)

For NEW widgets (which Auger creates and owns, not root-owned legacy widgets):
  The widget .py file should also define a WIDGET_AI_MANIFEST dict constant.
  This module will prefer the module constant if found, else fall back to YAML.

Usage:
    from auger.tools.widget_knowledge import save_learned
    save_learned("gchat", discoveries=["SRE channel is prod-only"])
"""

from __future__ import annotations
import yaml
from pathlib import Path
from datetime import datetime

_LEARNED_DIR = Path.home() / ".auger" / "widget_knowledge"

_YAML_CANDIDATES = [
    Path(__file__).parent.parent / "data" / "widget_manifests.yaml",
    Path.home() / "repos" / "auger-ai-sre-platform" / "auger" / "data" / "widget_manifests.yaml",
]


def _load_yaml_manifests() -> dict:
    for path in _YAML_CANDIDATES:
        if path.exists():
            try:
                data = yaml.safe_load(path.read_text()) or {}
                return data.get("widgets", {})
            except Exception:
                pass
    return {}


def _load_learned(widget_name: str) -> dict:
    path = _LEARNED_DIR / f"{widget_name}.yaml"
    if path.exists():
        try:
            return yaml.safe_load(path.read_text()) or {}
        except Exception:
            pass
    return {}


def save_learned(widget_name: str,
                 discoveries: list[str] | None = None,
                 usage_patterns: list[str] | None = None) -> None:
    """
    Persist Auger-discovered knowledge to the learned tier.
    Merges with existing data — never overwrites prior discoveries.
    """
    _LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    existing = _load_learned(widget_name)

    if discoveries:
        existing_d = existing.get("discoveries", [])
        for d in discoveries:
            if d not in existing_d:
                existing_d.append(d)
        existing["discoveries"] = existing_d

    if usage_patterns:
        existing_u = existing.get("usage_patterns", [])
        for u in usage_patterns:
            if u not in existing_u:
                existing_u.append(u)
        existing["usage_patterns"] = existing_u

    existing["last_updated"] = datetime.now().strftime("%Y-%m-%d")
    path = _LEARNED_DIR / f"{widget_name}.yaml"
    path.write_text(yaml.dump(existing, default_flow_style=False, allow_unicode=True))


def get_manifest(widget_name: str) -> dict:
    """
    Return the merged manifest for a single widget.
    Priority: module WIDGET_AI_MANIFEST constant > YAML static > learned-tier annotations.
    """
    # Try module constant first (for new widgets Auger created)
    try:
        import importlib
        mod = importlib.import_module(f"auger.ui.widgets.{widget_name}")
        if hasattr(mod, "WIDGET_AI_MANIFEST"):
            manifest = dict(mod.WIDGET_AI_MANIFEST)
            manifest["_source"] = "module_constant"
            learned = _load_learned(widget_name)
            if learned.get("discoveries"):
                manifest.setdefault("auger_rules", [])
                manifest["auger_rules"] = list(manifest["auger_rules"]) + [
                    f"[learned] {d}" for d in learned["discoveries"]
                ]
            return manifest
    except Exception:
        pass

    # Fall back to YAML
    static = _load_yaml_manifests().get(widget_name, {})
    learned = _load_learned(widget_name)
    merged = dict(static)
    if learned.get("discoveries"):
        merged.setdefault("auger_rules", [])
        merged["auger_rules"] = list(merged.get("auger_rules", [])) + [
            f"[learned] {d}" for d in learned["discoveries"]
        ]
    return merged
