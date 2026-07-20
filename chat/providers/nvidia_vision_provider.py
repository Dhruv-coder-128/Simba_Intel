"""Quantum Core's VISION router - image understanding, OCR, screenshot and
document-image reading, all through NVIDIA vision models. No Tesseract, no
OCR library: every text-from-image extraction in the app goes through this
exact same fallback chain (see extract_text_from_image(), used by
chat/file_analyzer.py).

No discovery, no health cache, no blacklist, no retry: a real request just
walks VISION_MODELS top to bottom, and the first one that answers wins. A
model that fails (404/429/500/503/timeout/connection/streaming error - any
exception at all) is skipped immediately and never retried within that
same request; nothing about that failure is remembered afterward, so the
very next request tries every model fresh, in the same fixed order.
"""
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

logger = logging.getLogger("simba_intel")

NVIDIA_API_BASE_URL = "https://integrate.api.nvidia.com/v1"
# "Maximum timeout 15 seconds. If timeout, immediately switch. Never let
# users wait 30+ seconds."
REQUEST_TIMEOUT_SECONDS = 15.0

# Fixed priority order. Do not add, remove, or reorder without an explicit
# product decision - this list IS the routing policy.
VISION_MODELS: List[str] = [
    "meta/llama-3.2-11b-vision-instruct",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "nvidia/nemotron-nano-12b-v2-vl",
    "stepfun-ai/step-3.7-flash",
]

_OCR_PROMPT = (
    "Extract every piece of readable text from this image, exactly as it "
    "appears, preserving line breaks. Do not describe the image, summarize "
    "it, or add commentary - output only the extracted text. If the image "
    "contains no readable text, respond with exactly: NO_TEXT_FOUND"
)


def _make_client(api_key: Optional[str]) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=NVIDIA_API_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)


def ask_vision(
    api_key: Optional[str],
    messages: List[Dict[str, Any]],
    on_usage: Optional[Callable[[dict], None]] = None,
    on_model_resolved: Optional[Callable[[dict], None]] = None,
    **kwargs,
) -> str:
    """Tries each VISION_MODELS candidate in priority order, immediate
    failover on any error - image understanding, OCR, and document/
    screenshot reading all share this one path. Raises only once every
    candidate has failed; never exposes the underlying provider error to
    the caller.

    `on_usage` is accepted for interface parity with every other
    provider's vision()/chat_stream() (chat/views.py's ask_ai always
    passes it) but deliberately NOT forwarded to `**kwargs` - it is not a
    real `chat.completions.create()` parameter, and NVIDIA's API Catalog
    fronts independently-hosted models with no guarantee any of them
    accept usage-reporting kwargs identically. Passing it through crashes
    the SDK call with "unexpected keyword argument" before any HTTP
    request is even sent - callers fall back to the character-count token
    estimate instead, same as the text provider."""
    client = _make_client(api_key)
    last_error: Optional[Exception] = None
    fallback_count = 0
    for candidate in VISION_MODELS:
        start = time.time()
        try:
            response = client.chat.completions.create(model=candidate, messages=messages, **kwargs)
        except Exception as e:
            last_error = e
            fallback_count += 1
            logger.warning(
                "Quantum Core (vision): model=%s failed (%.2fs): %s", candidate, time.time() - start, e,
            )
            continue
        logger.info("Quantum Core (vision): selected_model=%s latency=%.2fs", candidate, time.time() - start)
        if on_model_resolved:
            on_model_resolved({"model": candidate, "fallback_count": fallback_count})
        return response.choices[0].message.content
    logger.warning("Quantum Core (vision): every model failed")
    raise last_error or RuntimeError("Quantum Core vision is temporarily unavailable.")


def extract_text_from_image(api_key: Optional[str], image_bytes: bytes, mime_type: str = "image/png") -> str:
    """"No Tesseract. No OCR library. Everything must use NVIDIA Vision" -
    reuses ask_vision()'s exact same fallback chain with an extraction-only
    prompt, so OCR gets the identical priority order and failover behavior
    as any other vision request. Returns an empty string (never raises) on
    failure or when the image has no readable text - OCR is best-effort
    context for a chat turn, not a hard requirement."""
    import base64

    encoded = base64.b64encode(image_bytes).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": _OCR_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
            ],
        }
    ]
    try:
        result = ask_vision(api_key, messages)
    except Exception as e:
        logger.warning("Quantum Core OCR: extraction failed - %s: %s", type(e).__name__, e)
        return ""

    text = (result or "").strip()
    return "" if text == "NO_TEXT_FOUND" else text
