"""ModelRouter — purpose-based model selection.

Manages multiple model instances categorized by route:
  - chat: main conversation (expensive, high reasoning)
  - utility: lightweight tasks (cheap, fast)
  - utility_large: summaries, memory compilation
  - vision: image understanding (desktop control)

Falls back to `chat` route for unknown names.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# Valid route names
VALID_ROUTES = frozenset({"chat", "utility", "utility_large", "vision"})

# Default route when unknown one is requested
DEFAULT_ROUTE = "chat"


class ModelRouter:
    """Routes model requests by purpose based on config.

    Usage:
        router = ModelRouter(config)
        chat_model = router.get_model("chat")
        utility_model = router.get_model("utility")
    """

    def __init__(self, config: dict):
        self._config = config
        self._models: dict[str, ChatOpenAI] = {}
        self._initialized = False

    def _ensure_initialized(self):
        if not self._initialized:
            self._initialize_models()
            self._initialized = True

    def _initialize_models(self):
        """Create model instances for configured routes."""
        models_cfg = self._config.get("models", {})
        if not models_cfg:
            logger.info("No models section in config, using providers.default")
            from src.providers.factory import create_model
            default_model = create_model()
            for route in VALID_ROUTES:
                self._models[route] = default_model
            return

        for route in VALID_ROUTES:
            route_cfg = models_cfg.get(route)
            if route_cfg is None:
                logger.info("No config for route '%s', using default provider", route)
                from src.providers.factory import create_model
                self._models[route] = create_model()
                continue

            provider_name = route_cfg.get("provider")
            model_instance = _create_model_from_cfg(route_cfg, provider_name)
            self._models[route] = model_instance
            logger.info("ModelRouter: %s -> %s (%s)",
                        route, route_cfg.get("model", "?"),
                        provider_name or "default")

    def get_model(self, route: str = DEFAULT_ROUTE) -> ChatOpenAI:
        """Get a model instance for the given route.

        Args:
            route: Model purpose — "chat", "utility", "utility_large", or "vision".

        Returns:
            ChatOpenAI model instance for the route (falls back to chat if unknown).
        """
        self._ensure_initialized()
        if route not in VALID_ROUTES:
            logger.warning("Unknown model route '%s', falling back to '%s'",
                           route, DEFAULT_ROUTE)
            route = DEFAULT_ROUTE
        return self._models[route]


def _create_model_from_cfg(route_cfg: dict, provider_name: str | None = None) -> ChatOpenAI:
    """Create a single model instance from route config.

    Reuses the factory's create_model if provider matches the default,
    otherwise constructs directly.
    """
    from src.providers.factory import create_model, load_config

    config = load_config()
    default_provider = config["providers"].get("default")

    # If this route uses the default provider, reuse factory
    if provider_name == default_provider or provider_name is None:
        return create_model(provider_name)

    # Build from route-specific config
    provider_cfg = config["providers"].get(provider_name, {})
    if not provider_cfg:
        # If provider key not in providers section, use route_cfg directly
        # (route_cfg may contain all needed fields)
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=route_cfg.get("model", "gpt-4o"),
            api_key=route_cfg.get("api_key", ""),
            base_url=route_cfg.get("base_url"),
            max_tokens=route_cfg.get("max_tokens", 8192),
            temperature=route_cfg.get("temperature", 0.7),
            streaming=True,
        )

    # Merge route config overrides on top of provider config
    merged = {**provider_cfg, **{k: v for k, v in route_cfg.items()
                                  if k not in ("provider",)}}

    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=merged.get("model", "gpt-4o"),
        api_key=merged["api_key"],
        base_url=merged.get("base_url"),
        max_tokens=merged.get("max_tokens", 8192),
        temperature=merged.get("temperature", 0.7),
        streaming=True,
    )
