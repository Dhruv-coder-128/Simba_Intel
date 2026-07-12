
from typing import Generator, Dict, Any, Optional
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

    def chat_stream(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> Generator[str, None, None]:
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
