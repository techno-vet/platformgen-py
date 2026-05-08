from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from dotenv import dotenv_values

from auger.runtime import state_dir

PROVIDER_COPILOT = "copilot"
PROVIDER_OPENAI = "openai"
PROVIDER_OLLAMA = "ollama"

PROVIDER_ORDER = (
    PROVIDER_COPILOT,
    PROVIDER_OPENAI,
    PROVIDER_OLLAMA,
)

PROVIDER_LABELS = {
    PROVIDER_COPILOT: "GitHub Copilot",
    PROVIDER_OPENAI: "OpenAI",
    PROVIDER_OLLAMA: "Ollama",
}

COPILOT_MODEL_OPTIONS = (
    "auto",
    "claude-sonnet-4.6",
    "claude-sonnet-4.5",
    "claude-haiku-4.5",
    "claude-opus-4.7",
    "claude-opus-4.6",
    "claude-opus-4.6-fast",
    "claude-opus-4.5",
    "claude-sonnet-4",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5.4-mini",
    "gpt-5-mini",
    "gpt-4.1",
)

OPENAI_MODEL_OPTIONS = (
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "o4-mini",
    "o3",
)

OLLAMA_FALLBACK_MODELS = (
    "qwen2.5-coder:7b",
    "llama3.2",
)


def load_runtime_env(base: dict | None = None) -> dict:
    env = dict(base or os.environ)
    env_file = state_dir() / ".env"
    if env_file.exists():
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                env.setdefault(key, value)
    return env


def normalize_provider(provider: str | None) -> str:
    candidate = str(provider or PROVIDER_COPILOT).strip().lower()
    return candidate if candidate in PROVIDER_ORDER else PROVIDER_COPILOT


def provider_label(provider: str | None) -> str:
    provider = normalize_provider(provider)
    return PROVIDER_LABELS.get(provider, provider.title())


def provider_supports_copilot_sessions(provider: str | None) -> bool:
    return normalize_provider(provider) == PROVIDER_COPILOT


def default_model(provider: str | None, env: dict | None = None) -> str:
    provider = normalize_provider(provider)
    env = load_runtime_env(env)
    if provider == PROVIDER_COPILOT:
        return "auto"
    if provider == PROVIDER_OPENAI:
        configured = str(env.get("OPENAI_DEFAULT_MODEL") or "").strip()
        return configured or OPENAI_MODEL_OPTIONS[0]
    configured = str(env.get("OLLAMA_MODEL") or "").strip()
    return configured or OLLAMA_FALLBACK_MODELS[0]


def openai_base_url(env: dict | None = None) -> str:
    env = load_runtime_env(env)
    return (
        str(
            env.get("OPENAI_BASE_URL")
            or env.get("OPENAI_API_BASE")
            or "https://api.openai.com"
        ).rstrip("/")
    )


def ollama_base_url(env: dict | None = None) -> str:
    env = load_runtime_env(env)
    return str(env.get("OLLAMA_BASE_URL") or env.get("OLLAMA_BASE") or "http://localhost:11434").rstrip("/")


def _http_json(url: str, *, headers: dict | None = None, timeout: int = 5) -> dict:
    req = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _openai_live_models(env: dict | None = None) -> list[str]:
    env = load_runtime_env(env)
    api_key = str(env.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return []
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        payload = _http_json(f"{openai_base_url(env)}/v1/models", headers=headers, timeout=6)
    except Exception:
        return []
    models = []
    for entry in payload.get("data", []):
        model_id = str(entry.get("id") or "").strip()
        if not model_id:
            continue
        if model_id.startswith(("gpt-", "o1", "o3", "o4")):
            models.append(model_id)
    return sorted(set(models))


def _ollama_live_models(env: dict | None = None) -> list[str]:
    env = load_runtime_env(env)
    try:
        payload = _http_json(f"{ollama_base_url(env)}/api/tags", timeout=5)
    except Exception:
        return []
    models = []
    for entry in payload.get("models", []):
        model_name = str(entry.get("name") or "").strip()
        if model_name:
            models.append(model_name)
    return models


def available_models(provider: str | None, env: dict | None = None) -> list[str]:
    provider = normalize_provider(provider)
    env = load_runtime_env(env)
    if provider == PROVIDER_COPILOT:
        return list(COPILOT_MODEL_OPTIONS)
    if provider == PROVIDER_OPENAI:
        live = _openai_live_models(env)
        ordered = list(OPENAI_MODEL_OPTIONS)
        for model in live:
            if model not in ordered:
                ordered.append(model)
        configured = str(env.get("OPENAI_DEFAULT_MODEL") or "").strip()
        if configured and configured not in ordered:
            ordered.insert(0, configured)
        return ordered
    live = _ollama_live_models(env)
    if live:
        return live
    configured = str(env.get("OLLAMA_MODEL") or "").strip()
    ordered = [configured] if configured else []
    for model in OLLAMA_FALLBACK_MODELS:
        if model not in ordered:
            ordered.append(model)
    return ordered


def seeded_models(provider: str | None, env: dict | None = None) -> list[str]:
    provider = normalize_provider(provider)
    env = load_runtime_env(env)
    if provider == PROVIDER_COPILOT:
        return list(COPILOT_MODEL_OPTIONS)
    if provider == PROVIDER_OPENAI:
        ordered = list(OPENAI_MODEL_OPTIONS)
        configured = str(env.get("OPENAI_DEFAULT_MODEL") or "").strip()
        if configured and configured not in ordered:
            ordered.insert(0, configured)
        return ordered
    configured = str(env.get("OLLAMA_MODEL") or "").strip()
    ordered = [configured] if configured else []
    for model in OLLAMA_FALLBACK_MODELS:
        if model not in ordered:
            ordered.append(model)
    return ordered


def normalize_model(provider: str | None, model: str | None, env: dict | None = None) -> str:
    provider = normalize_provider(provider)
    candidate = str(model or "").strip()
    options = available_models(provider, env)
    if candidate and candidate in options:
        return candidate
    if candidate and provider != PROVIDER_COPILOT:
        return candidate
    return default_model(provider, env)
