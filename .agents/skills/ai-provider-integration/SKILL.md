---
name: ai-provider-integration
description: >-
  Procedures for adding or updating AI models and providers in Simba Intel.
  Use when adding new LLMs, implementing provider adapters, configuring streaming completions,
  setting up fallback chains, or adjusting token cost calculations.
---

# AI Provider Integration Runbook

Follow this step-by-step guide when integrating a new model or AI provider into Simba Intel.

## 1. Implement Provider Adapter

Create or modify an adapter class in `chat/providers/` subclassing `BaseProvider`:

```python
import os
from typing import Generator, Dict, Any, Optional
from chat.providers.base import BaseProvider

class CustomProvider(BaseProvider):
    provider_name = "custom"
    supported_models = ["custom-model-id"]

    def _initialize_client(self):
        self.api_key = os.getenv("CUSTOM_API_KEY", "")
        # Initialize client here

    def chat(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        # Non-streaming implementation
        pass

    def chat_stream(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> Generator[str, None, None]:
        # Yield string tokens
        on_usage = kwargs.get("on_usage")
        # If usage data is returned by provider, call on_usage(prompt_tokens, completion_tokens)
        yield "token"

    def vision(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        raise NotImplementedError("Vision not supported")

    def generate_image(self, prompt: str, model: str, **kwargs) -> str:
        raise NotImplementedError("Image generation not supported")
```

## 2. Register in Provider Manager

In `chat/services/provider_manager.py`:
```python
PROVIDER_REGISTRY = {
    "groq": GroqProvider,
    "mistral": MistralProvider,
    "custom": CustomProvider,
}
```

## 3. Register Model & Fallbacks

In `chat/services/model_registry.py`:

1. **Add `ModelConfig`**:
   ```python
   "custom-model": ModelConfig(
       display_name="Custom Model",
       provider="custom",
       actual_model="custom-model-id",
       supports_vision=False,
       context_window=128000,
       min_role="user",
   ),
   ```
2. **Configure Fallback Chain**:
   ```python
   FALLBACK_CHAINS["custom-model"] = ["nova-mind", "sky-net-mini"]
   ```
3. **Map Display Name**:
   ```python
   PROVIDER_DISPLAY_NAMES["custom"] = "Custom Cloud"
   ```

## 4. Register Cost in Cost Table

In `chat/services/cost_table.py`:
```python
MODEL_RATES = {
    # Rates per 1,000 tokens (prompt, completion)
    "custom-model": (Decimal("0.00015"), Decimal("0.00060")),
}
```

## 5. Verification

1. Verify registry lookup:
   ```bash
   python manage.py shell -c "from chat.services.model_registry import get_model_config; print(get_model_config('custom-model'))"
   ```
2. Write unit tests with mocked responses in `chat/tests.py`.
3. Run tests:
   ```bash
   python manage.py test chat.tests.ModelRegistryTests
   ```
