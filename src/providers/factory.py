'''
Descripttion: 
version: 
Author: WorkPartner Contributors
Date: 2026-05-04 21:50:38
'''
import os
import yaml
from pathlib import Path

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# Load .env at import time so env vars are available when _resolve_env_vars runs
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_dotenv_path = _PROJECT_ROOT / ".env"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path)


def load_config() -> dict:
    config_path = _PROJECT_ROOT / "config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    # Resolve env vars in values like "${VAR_NAME}"
    return _resolve_env_vars(config)


def _resolve_env_vars(obj):
    if isinstance(obj, str) and obj.startswith("${") and obj.endswith("}"):
        return os.environ.get(obj[2:-1], obj)
    if isinstance(obj, dict):
        return {k: _resolve_env_vars(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_env_vars(v) for v in obj]
    return obj


def create_model(provider_name: str | None = None) -> ChatOpenAI:
    """Create a LangGraph-compatible chat model from config."""
    config = load_config()
    provider_name = provider_name or config["providers"]["default"]
    provider_cfg = config["providers"].get(provider_name)

    if provider_cfg is None:
        raise ValueError(
            f"Provider '{provider_name}' not found in config.yaml. "
            f"Available: {list(config['providers'].keys())}"
        )

    if provider_name == "openai" or "base_url" in provider_cfg:
        return ChatOpenAI(
            model=provider_cfg.get("model", "gpt-4o"),
            api_key=provider_cfg["api_key"],
            base_url=provider_cfg.get("base_url"),
            max_tokens=provider_cfg.get("max_tokens", 8192),
            temperature=provider_cfg.get("temperature", 0.7),
            streaming=True,
        )

    raise ValueError(f"Unknown provider type: {provider_name}")
