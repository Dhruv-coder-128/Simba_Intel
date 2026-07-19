
from typing import Callable, Generator, Dict, Any, Optional
from groq import Groq
from .base import BaseProvider


class GroqProvider(BaseProvider):
    provider_name = "groq"
    supported_models = [
        "meta-llama/llama-4-scout-17b-16e-instruct",
        "groq/compound-mini"
    ]

    # Neither SDK client had an explicit timeout before this - an unbounded
    # default meant one hung upstream connection could pin a gunicorn thread
    # indefinitely, and this app has only 8 total request-handling threads
    # (--workers 2 --threads 4, see Dockerfile). A handful of stalled calls
    # would have been enough to make the whole server stop responding to
    # every other concurrent user. httpx (which both the groq and openai
    # SDKs are built on) applies a bare float to connect/read/write/pool
    # uniformly, and - critically for a streaming response - a read timeout
    # is measured between successive chunks, not over the whole response, so
    # a long but steadily-streaming reply is never cut off by this.
    REQUEST_TIMEOUT_SECONDS = 30.0

    def _initialize_client(self):
        self.client = Groq(api_key=self.api_key, timeout=self.REQUEST_TIMEOUT_SECONDS)

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
            # chunk.choices can legitimately be empty (e.g. a trailing
            # keep-alive/usage-only chunk - see MistralProvider.chat_stream,
            # which hits this for real via stream_options) - indexing [0]
            # unconditionally would raise IndexError and surface as a raw
            # error mid-stream instead of just skipping the empty chunk.
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def vision(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        on_usage: Optional[Callable[[dict], None]] = None,
        **kwargs,
    ) -> str:
        # `on_usage` is accepted for interface parity with every other
        # provider's vision() (chat/views.py's ask_ai always passes it) but
        # deliberately NOT forwarded to **kwargs - it isn't a real
        # chat.completions.create() parameter, and passing it through
        # crashes the SDK call with "unexpected keyword argument" before
        # any HTTP request is even sent.
        response = self.client.chat.completions.create(
            model=model,
            messages=messages,
            **kwargs
        )
        return response.choices[0].message.content

    def generate_image(self, prompt: str, model: str, **kwargs) -> str:
        raise NotImplementedError("Image generation not supported by Groq")
