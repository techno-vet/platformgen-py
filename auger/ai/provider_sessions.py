from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

from auger.runtime import state_dir

_ROOT = state_dir() / "provider_sessions"
_SESSION_DIR = _ROOT / "sessions"
_PINNED_FILE = _ROOT / "pinned.json"
_COPILOT_PIN_DIR = _ROOT / "copilot_pins"
_LEGACY_COPILOT_PIN = state_dir() / ".session_id"


def _ensure_dirs():
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    _COPILOT_PIN_DIR.mkdir(parents=True, exist_ok=True)


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return cleaned or "auto"


def scope_key(provider: str, model: str) -> str:
    return f"{provider}:{model}"


def _session_path(session_id: str) -> Path:
    _ensure_dirs()
    return _SESSION_DIR / f"{session_id}.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _pinned_map() -> dict[str, str]:
    _ensure_dirs()
    data = _read_json(_PINNED_FILE, {})
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(v).strip()}


def _write_pinned_map(payload: dict[str, str]):
    _write_json(_PINNED_FILE, dict(sorted(payload.items())))


def copilot_pin_path(model: str) -> Path:
    _ensure_dirs()
    return _COPILOT_PIN_DIR / f"{_slug(model)}.txt"


def read_copilot_pinned_session_id(model: str) -> str:
    path = copilot_pin_path(model)
    if path.exists():
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    if _slug(model) == "auto" and _LEGACY_COPILOT_PIN.exists():
        try:
            return _LEGACY_COPILOT_PIN.read_text(encoding="utf-8").strip()
        except Exception:
            return ""
    return ""


def write_copilot_pinned_session_id(model: str, session_id: str):
    session_id = str(session_id or "").strip()
    path = copilot_pin_path(model)
    if session_id:
        path.write_text(session_id, encoding="utf-8")
        if _slug(model) == "auto":
            _LEGACY_COPILOT_PIN.write_text(session_id, encoding="utf-8")
    else:
        clear_copilot_pinned_session_id(model)


def clear_copilot_pinned_session_id(model: str):
    for path in (copilot_pin_path(model), _LEGACY_COPILOT_PIN if _slug(model) == "auto" else None):
        if path is None:
            continue
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def get_local_session(session_id: str) -> dict:
    path = _session_path(session_id)
    payload = _read_json(path, {})
    if not isinstance(payload, dict):
        return {}
    return payload


def create_local_session(provider: str, model: str, alias: str = "") -> dict:
    _ensure_dirs()
    session_id = str(uuid.uuid4())
    now = time.time()
    payload = {
        "session_id": session_id,
        "provider": provider,
        "model": model,
        "alias": str(alias or "").strip(),
        "created_at": now,
        "updated_at": now,
        "messages": [],
    }
    _write_json(_session_path(session_id), payload)
    return payload


def ensure_local_session(provider: str, model: str, session_target: dict | None) -> dict:
    target = dict(session_target or {})
    mode = str(target.get("mode") or "pinned").strip().lower()
    requested_id = str(target.get("session_id") or "").strip()
    requested_name = str(target.get("name") or "").strip()

    if mode == "session" and requested_id:
        payload = get_local_session(requested_id)
        if payload.get("provider") == provider and payload.get("model") == model:
            return payload

    if mode == "new":
        return create_local_session(provider, model, requested_name)

    pins = _pinned_map()
    key = scope_key(provider, model)
    pinned_id = pins.get(key, "")
    payload = get_local_session(pinned_id) if pinned_id else {}
    if payload.get("provider") == provider and payload.get("model") == model:
        return payload

    payload = create_local_session(provider, model)
    pins[key] = payload["session_id"]
    _write_pinned_map(pins)
    return payload


def read_local_pinned_session_id(provider: str, model: str) -> str:
    return _pinned_map().get(scope_key(provider, model), "")


def clear_local_pinned_session(provider: str, model: str):
    pins = _pinned_map()
    key = scope_key(provider, model)
    if key in pins:
        pins.pop(key, None)
        _write_pinned_map(pins)


def rename_local_session(session_id: str, alias: str):
    payload = get_local_session(session_id)
    if not payload:
        return
    payload["alias"] = str(alias or "").strip()
    payload["updated_at"] = time.time()
    _write_json(_session_path(session_id), payload)


def append_local_turn(session_id: str, user_prompt: str, assistant_response: str):
    payload = get_local_session(session_id)
    if not payload:
        return
    messages = payload.setdefault("messages", [])
    messages.extend(
        [
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": assistant_response},
        ]
    )
    payload["updated_at"] = time.time()
    _write_json(_session_path(session_id), payload)


def session_messages(session_id: str, limit: int = 24) -> list[dict[str, str]]:
    payload = get_local_session(session_id)
    messages = payload.get("messages", [])
    if not isinstance(messages, list):
        return []
    trimmed = messages[-limit:]
    result = []
    for item in trimmed:
        role = str(item.get("role") or "").strip()
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant", "system"} and content:
            result.append({"role": role, "content": content})
    return result


def list_local_sessions(provider: str, model: str, limit: int = 30) -> list[dict]:
    _ensure_dirs()
    sessions = []
    for path in _SESSION_DIR.glob("*.json"):
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        if payload.get("provider") != provider or payload.get("model") != model:
            continue
        sessions.append(
            {
                "id": str(payload.get("session_id") or path.stem),
                "alias": str(payload.get("alias") or "").strip(),
                "updated_at": float(payload.get("updated_at") or 0),
                "created_at": float(payload.get("created_at") or 0),
            }
        )
    sessions.sort(key=lambda item: item.get("updated_at", 0), reverse=True)
    return sessions[:limit]
