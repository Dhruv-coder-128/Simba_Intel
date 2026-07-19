"""Quantum Core's real implementation - registered as provider "nvidia" in
chat/services/provider_manager.py, so every existing call site (chat/
services/ai_router.py, chat/views.py's ask_ai/regenerate_message/
edit_message/continue_message) needs ZERO changes: they already just
resolve `get_model_config(model_id)` to a (provider, actual_model) pair and
call `get_provider(config.provider).chat_stream(messages, config.
actual_model, **kwargs)` generically. The user only ever sees "Quantum
Core"; which real NVIDIA model answered is an internal, per-request
decision, never surfaced in an error message or log line a user could see.

Routing is the simplest thing that could possibly work:
    no attachment -> chat()/chat_stream() below, walks TEXT_MODELS in order
    attachment    -> vision(), delegates entirely to
                     chat/providers/nvidia_vision_provider.py's own
                     VISION_MODELS chain (that decision - "does this
                     request have an attachment" - is made once, by
                     chat/views.py's ask_ai, exactly the way it already
                     decides this for every other vision-capable model;
                     nothing here re-derives it)

No discovery, no health cache, no blacklist, no retry: a real request just
walks the fixed model list top to bottom, and the first one that answers
wins. A model that fails (404/429/500/503/timeout/connection/streaming
error - any exception at all) is skipped immediately and never retried
within that same request; nothing about that failure is remembered
afterward, so the very next request tries every model fresh, in the same
fixed order.
"""
import logging
import time
from typing import Any, Callable, Dict, Generator, List, Optional

from openai import OpenAI

from chat.providers.base import BaseProvider
from chat.providers.nvidia_vision_provider import ask_vision

logger = logging.getLogger("simba_intel")

NVIDIA_API_BASE_URL = "https://integrate.api.nvidia.com/v1"
# "Maximum timeout 15 seconds. If timeout, immediately switch. Never let
# users wait 30+ seconds."
REQUEST_TIMEOUT_SECONDS = 15.0

# Fixed priority order - fastest first. Do not add, remove, or reorder
# without an explicit product decision; this list IS the routing policy.
TEXT_MODELS: List[str] = [
    "nvidia/nemotron-3-super-120b-a12b",
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "mistralai/mistral-nemotron",
    "meta/llama-3.1-70b-instruct",
]


def _iter_stream(stream) -> Generator[str, None, None]:
    for chunk in stream:
        # chunk.choices can legitimately be empty (a trailing keep-alive/
        # usage-only chunk) - indexing [0] unconditionally would raise
        # IndexError and surface as a raw error mid-stream instead of just
        # skipping it.
        if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content


class NvidiaTextProvider(BaseProvider):
    provider_name = "nvidia"

    def _initialize_client(self):
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=NVIDIA_API_BASE_URL,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    def chat(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        last_error: Optional[Exception] = None
        for candidate in TEXT_MODELS:
            start = time.time()
            try:
                response = self.client.chat.completions.create(
                    model=candidate, messages=messages, stream=False, **kwargs,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "Quantum Core (text): model=%s failed (%.2fs): %s", candidate, time.time() - start, e,
                )
                continue
            logger.info("Quantum Core (text): selected_model=%s latency=%.2fs", candidate, time.time() - start)
            return response.choices[0].message.content
        logger.warning("Quantum Core (text): every model failed")
        raise last_error or RuntimeError("Quantum Core is temporarily unavailable.")

    def chat_stream(
        self,
        messages: list[Dict[str, Any]],
        model: str,
        on_usage: Optional[Callable[[dict], None]] = None,
        **kwargs,
    ) -> Generator[str, None, None]:
        # stream_options={"include_usage": True} is deliberately NOT sent -
        # NVIDIA's API Catalog fronts independently-hosted models with no
        # guarantee every one supports this parameter identically, and
        # requesting it speculatively risks turning a healthy model into a
        # spurious "failure" that burns a failover attempt for nothing -
        # `on_usage` is accepted for interface parity but never called here
        # (callers fall back to the character-count token estimate).
        last_error: Optional[Exception] = None
        fallback_count = 0
        for candidate in TEXT_MODELS:
            start = time.time()
            try:
                stream = self.client.chat.completions.create(
                    model=candidate, messages=messages, stream=True, **kwargs,
                )
                gen = _iter_stream(stream)
                first_chunk = next(gen)
            except StopIteration:
                # A real, successful call that just produced no tokens -
                # not a failure, so this must not trigger failover.
                logger.info(
                    "Quantum Core (text): selected_model=%s (empty response) fallback_count=%d latency=%.2fs",
                    candidate, fallback_count, time.time() - start,
                )
                return
            except Exception as e:
                last_error = e
                fallback_count += 1
                logger.warning(
                    "Quantum Core (text): model=%s failed (%.2fs): %s - switching immediately, no retry",
                    candidate, time.time() - start, e,
                )
                continue
            else:
                # Streaming can only fail over before the first token is
                # yielded - once real output has reached the caller,
                # switching models mid-stream would interleave/duplicate
                # text, so a failure past this point propagates as a
                # normal exception (the existing view-level try/except in
                # chat/views.py already turns that into the same generic
                # safe error message every other streaming endpoint uses).
                logger.info(
                    "Quantum Core (text): selected_model=%s fallback_count=%d latency=%.2fs",
                    candidate, fallback_count, time.time() - start,
                )
                yield first_chunk
                yield from gen
                return

        logger.warning("Quantum Core (text): every model failed")
        raise last_error or RuntimeError("Quantum Core is temporarily unavailable.")

    def vision(self, messages: list[Dict[str, Any]], model: str, **kwargs) -> str:
        """Delegates entirely to chat/providers/nvidia_vision_provider.py's
        own VISION_MODELS chain - kept in its own file so the text and
        vision routing policies can each be read, tested, and changed
        independently."""
        return ask_vision(self.api_key, messages, **kwargs)

    def generate_image(self, prompt: str, model: str, **kwargs) -> str:
        raise NotImplementedError(
            "Quantum Core does not generate images - image generation is handled by Image Studio (Pollinations)."
        )
