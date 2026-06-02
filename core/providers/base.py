"""
core/providers/base.py - Abstrakt basklass för AI-providers.
Alla providers (DeepSeek, Gemini, Claude) ärver från BaseProvider.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TokenUsage:
    """Förbrukad token-statistik för ett API-anrop."""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cached_input_tokens: int = 0


@dataclass
class AiResponse:
    """Standardiserat svar från en AI-provider."""
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    provider: str = ""
    error: Optional[str] = None
    success: bool = True


class BaseProvider(ABC):
    """Abstrakt basklass som alla AI-providers måste implementera."""

    # Konfiguration per provider (pris per 1M tokens i USD)
    PROVIDER_CONFIG: dict = {
        "cost_per_1m_input": 0.0,
        "cost_per_1m_output": 0.0,
    }

    def __init__(self, api_key: str = "", model: str = "", config: dict = None):
        """Initiera providern.

        Args:
            api_key: API-nyckel. Använder config._get_secret om tom.
            model: Modellnamn. Använder config-default om tom.
            config: Extra konfiguration för providern.
        """
        self.api_key = api_key
        self.model = model
        self.config = config or {}

    @abstractmethod
    def generate(self, messages: list, **kwargs) -> AiResponse:
        """Generera text från en lista med meddelanden.

        Args:
            messages: Lista med {"role": "user"|"assistant"|"system", "content": "..."}
            **kwargs: max_tokens, temperature, etc.

        Returns:
            AiResponse med text, usage och eventuellt felmeddelande.
        """
        ...

    @abstractmethod
    def generate_structured(self, prompt: str, schema: dict) -> dict:
        """Generera strukturerad JSON enligt ett schema.

        Args:
            prompt: Prompt-texten
            schema: JSON-schema som definierar output-formatet

        Returns:
            Dict med strukturerad data
        """
        ...

    def cost_estimate(self, tokens: TokenUsage) -> float:
        """Beräkna uppskattad kostnad för ett anrop.

        Args:
            tokens: TokenUsage från ett anrop

        Returns:
            Kostnad i USD
        """
        cfg = self.PROVIDER_CONFIG
        input_cost = (tokens.input_tokens / 1_000_000) * cfg.get("cost_per_1m_input", 0)
        output_cost = (tokens.output_tokens / 1_000_000) * cfg.get("cost_per_1m_output", 0)
        return round(input_cost + output_cost, 6)

    def get_provider_name(self) -> str:
        """Returnera providerns namn (används för loggning och UI)."""
        return self.__class__.__name__.replace("Provider", "").lower()
