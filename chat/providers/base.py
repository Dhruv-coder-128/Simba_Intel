
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Generator, Dict, Any, Optional


class BaseProvider(ABC):
    """Abstract base class for all AI providers."""

    provider_name: str
    supported_models: list[str]
    api_key: Optional[str] = None
    api_base: Optional[str] = None

    def __init__(self, api_key: Optional[str] = None, api_base: Optional[str] = None, **kwargs):
        self.api_key = api_key
        self.api_base = api_base
        self.kwargs = kwargs
        self._initialize_client()

    @abstractmethod
    def _initialize_client(self):
        """Initialize the provider-specific client."""
        pass

    @abstractmethod
    def chat(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        """Non-streaming chat completion."""
        pass

    @abstractmethod
    def chat_stream(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> Generator[str, None, None]:
        """Streaming chat completion."""
        pass

    @abstractmethod
    def vision(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        """Vision/image understanding."""
        pass

    @abstractmethod
    def generate_image(self, prompt: str, model: str, **kwargs) -> str:
        """Image generation."""
        pass

    def is_model_supported(self, model: str) -> bool:
        """Check if a model is supported by this provider."""
        return model in self.supported_models

    def get_provider_name(self) -> str:
        """Return the provider name."""
        return self.provider_name
