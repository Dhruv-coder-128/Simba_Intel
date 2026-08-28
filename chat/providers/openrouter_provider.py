import os
from typing import Any, Callable, Dict, Generator, Optional

from openai import OpenAI

from chat.utils.env import get_env_var
from .base import BaseProvider


class OpenRouterProvider(BaseProvider):
    provider_name = "openrouter"
    supported_models = [
        "nvidia/nemotron-3-super-120b-a12b:free",
    ]

    OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"
    REQUEST_TIMEOUT_SECONDS = 30.0

    def _initialize_client(self):
        api_key = self.api_key or get_env_var("OPENROUTER_API_KEY") or "placeholder"
        base_url = self.api_base or self.OPENROUTER_API_BASE_URL
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=self.REQUEST_TIMEOUT_SECONDS,
        )

    def chat(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        **kwargs,
    ) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            **kwargs,
        )
        if response.choices and response.choices[0].message:
            return response.choices[0].message.content or ""
        return ""

    def chat_stream(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        on_usage: Optional[Callable[[dict], None]] = None,
        on_model_resolved: Optional[Callable[[dict], None]] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )

        for chunk in stream:
            usage = getattr(chunk, "usage", None)
            if usage is not None and on_usage:
                p_tokens = getattr(usage, "prompt_tokens", None)
                c_tokens = getattr(usage, "completion_tokens", None)
                if isinstance(p_tokens, int) and isinstance(c_tokens, int):
                    on_usage({
                        "prompt_tokens": p_tokens,
                        "completion_tokens": c_tokens,
                    })

            if (
                chunk.choices
                and chunk.choices[0].delta
                and chunk.choices[0].delta.content
            ):
                yield chunk.choices[0].delta.content

    def vision(
        self,
        messages: list[Dict[str, Any]],
        model: str = "nvidia/nemotron-3-super-120b-a12b:free",
        on_usage: Optional[Callable[[dict], None]] = None,
        on_model_resolved: Optional[Callable[[dict], None]] = None,
        **kwargs,
    ) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=False,
            **kwargs,
        )

        usage = getattr(response, "usage", None)
        if usage is not None and on_usage:
            p_tokens = getattr(usage, "prompt_tokens", None)
            c_tokens = getattr(usage, "completion_tokens", None)
            if isinstance(p_tokens, int) and isinstance(c_tokens, int):
                on_usage({
                    "prompt_tokens": p_tokens,
                    "completion_tokens": c_tokens,
                })

        if response.choices and response.choices[0].message:
            return response.choices[0].message.content or ""
        return ""

    def generate_image(self, prompt: str, model: str = None, **kwargs) -> str:
        raise NotImplementedError("Image generation is not supported by OpenRouter in SIMBA_INTEL.")
