import os
from typing import Callable, Generator, Dict, Any, Optional

from openai import OpenAI

from .base import BaseProvider


class MistralProvider(BaseProvider):

    provider_name = "mistral"

    supported_models = [
        "mistral-medium-latest",
        "mistral-large-latest",
        "ministral-8b-latest",
        "pixtral-large-latest",
    ]

    # See GroqProvider.REQUEST_TIMEOUT_SECONDS for why this exists: an
    # unbounded client timeout risks pinning one of this app's 8 total
    # gunicorn request-handling threads on a single hung upstream call. A
    # streaming read timeout is measured between chunks, not over the whole
    # response, so a long-but-steadily-streaming reply is unaffected.
    REQUEST_TIMEOUT_SECONDS = 30.0

    def _initialize_client(self):
        self.client = OpenAI(
            api_key=os.getenv("MISTRAL_API_KEY"),
            base_url="https://api.mistral.ai/v1",
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

        return response.choices[0].message.content

    def chat_stream(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        on_usage: Optional[Callable[[dict], None]] = None,
        **kwargs,
    ) -> Generator[str, None, None]:

        # Verified empirically: Mistral's OpenAI-compatible endpoint honors
        # stream_options and returns a final usage-bearing chunk with real
        # token counts (unlike the Groq SDK, which rejects this kwarg
        # outright) - so real usage capture is only attempted here.
        stream = self.client.chat.completions.create(
            model=model,
            messages=messages,
            stream=True,
            stream_options={"include_usage": True},
            **kwargs,
        )

        for chunk in stream:
            if getattr(chunk, "usage", None) and on_usage:
                on_usage({
                    "prompt_tokens": chunk.usage.prompt_tokens,
                    "completion_tokens": chunk.usage.completion_tokens,
                })

            if (
                chunk.choices
                and chunk.choices[0].delta
                and chunk.choices[0].delta.content
            ):
                yield chunk.choices[0].delta.content

    def vision(
        self,
        messages,
        model="pixtral-large-latest",
        on_usage: Optional[Callable[[dict], None]] = None,
        **kwargs,
    ):

        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,
        )

        if getattr(response, "usage", None) and on_usage:
            on_usage({
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
            })

        return response.choices[0].message.content

    def generate_image(
        self,
        prompt,
        model=None,
        **kwargs,
    ):
        raise NotImplementedError(
            "Image Generation will be added in the next update."
        )