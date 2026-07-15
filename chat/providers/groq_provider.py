
from typing import Callable, Generator, Dict, Any, Optional
from groq import Groq
from .base import BaseProvider


class GroqProvider(BaseProvider):
    provider_name = "groq"
    supported_models = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "groq/compound-mini"
    ]

    def _initialize_client(self):
        self.client = Groq(api_key=self.api_key)

    def chat(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content

    def chat_stream(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        on_usage: Optional[Callable[[dict], None]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        # Verified empirically: the installed Groq SDK raises TypeError on
        # stream_options={"include_usage": True} - it's not supported at all
        # here (unlike Mistral's OpenAI-compatible endpoint), so `on_usage`
        # is accepted for interface parity but intentionally never called;
        # callers fall back to a token-count estimate for this provider.
        stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            **kwargs
        )
        for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def vision(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content

    def generate_image(self, prompt: str, model: str, **kwargs) -> str:
        raise NotImplementedError("Image generation not supported by Groq")
