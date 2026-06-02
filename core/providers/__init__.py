"""
core/providers/__init__.py - Provider Factory & Registrering.
Använd get_provider(name) för att hämta en provider-instans.
"""

import logging
from typing import Optional

from .base import BaseProvider

_logger = logging.getLogger(__name__)

# Provider-register: namn -> klass
_PROVIDER_REGISTRY: dict = {}


def register_provider(name: str, provider_class: type):
    """Registrera en provider-klass.

    Args:
        name: Providernamn (t.ex. "deepseek", "gemini", "claude")
        provider_class: Klass som ärver BaseProvider
    """
    _PROVIDER_REGISTRY[name.lower()] = provider_class
    _logger.debug("Provider registrerad: %s -> %s", name, provider_class.__name__)


def get_provider(name: str, **kwargs) -> Optional[BaseProvider]:
    """Hämta en provider-instans.

    Försöker hitta providern i registret. Om den inte är registrerad,
    försök lazy-importa från core.providers.<name>_provider.

    Args:
        name: Providernamn (t.ex. "deepseek", "gemini", "claude")
        **kwargs: Skickas till provider-konstruktorn

    Returns:
        BaseProvider-instans eller None om providern inte finns
    """
    name = name.lower().strip()

    # Kolla om den redan är registrerad
    if name in _PROVIDER_REGISTRY:
        try:
            return _PROVIDER_REGISTRY[name](**kwargs)
        except Exception as e:
            _logger.error("Kunde inte instansiera provider '%s': %s", name, e)
            return None

    # Försök lazy-import
    module_name = f"core.providers.{name}_provider"
    try:
        import importlib
        module = importlib.import_module(module_name)
        # Leta efter klassen som slutar med Provider
        for attr_name in dir(module):
            if attr_name.lower() == f"{name}provider":
                cls = getattr(module, attr_name)
                if isinstance(cls, type) and issubclass(cls, BaseProvider):
                    register_provider(name, cls)
                    return cls(**kwargs)
        _logger.warning("Hittade ingen provider-klass i %s", module_name)
    except ImportError as e:
        _logger.warning("Kunde inte ladda provider '%s': %s", name, e)
    except Exception as e:
        _logger.error("Fel vid lazy-import av provider '%s': %s", name, e)

    return None


def list_providers() -> dict:
    """Lista alla registrerade providers med deras config.

    Returns:
        Dict med providernamn -> config
    """
    result = {}
    for name, cls in _PROVIDER_REGISTRY.items():
        try:
            cfg = getattr(cls, "PROVIDER_CONFIG", {})
            result[name] = {
                "name": name,
                "cost_per_1m_input": cfg.get("cost_per_1m_input", 0),
                "cost_per_1m_output": cfg.get("cost_per_1m_output", 0),
                "model": getattr(cls, "DEFAULT_MODEL", ""),
            }
        except Exception:
            result[name] = {"name": name}
    return result


# Auto-registrera tillgängliga providers vid import
try:
    from .deepseek_provider import DeepSeekProvider
    register_provider("deepseek", DeepSeekProvider)
except ImportError:
    pass

try:
    from .gemini_provider import GeminiProvider
    register_provider("gemini", GeminiProvider)
except ImportError:
    pass

try:
    from .claude_provider import ClaudeProvider
    register_provider("claude", ClaudeProvider)
except ImportError:
    pass
