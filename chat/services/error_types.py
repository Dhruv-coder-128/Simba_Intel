"""Standardized AI error types and normalization for SIMBA_INTEL.

Maps provider-specific exceptions (Groq, Mistral, Nvidia, OpenRouter, Pollinations)
and internal quota/rate checks into clean, consistent error structures.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional
import re


class AIErrorType(str, Enum):
    RATE_LIMITED = "rate_limited"                   # Upstream provider HTTP 429
    DAILY_LIMIT_REACHED = "daily_limit_reached"     # Internal SIMBA user account quota
    BURST_LIMITED = "burst_limited"                 # Rapid user submission limiter (30/min)
    AUTH_ERROR = "auth_error"                       # Upstream 401/403 or invalid API key
    MODEL_NOT_FOUND = "model_not_found"             # Invalid or retired model ID
    PROVIDER_OVERLOADED = "provider_overloaded"     # Upstream capacity / temporarily overloaded
    PROVIDER_UNAVAILABLE = "provider_unavailable"   # Upstream 502/503/504 or network outage
    TIMEOUT = "timeout"                             # Request exceeded maximum timeout
    INVALID_REQUEST = "invalid_request"             # 400 Bad request / context window exceeded
    UNKNOWN_PROVIDER_ERROR = "unknown_provider_error"


@dataclass
class NormalizedAIError:
    error_type: AIErrorType
    message: str
    provider: str = ""
    model_id: str = ""
    retry_after: Optional[int] = None
    status_code: int = 500
    is_user_quota: bool = False

    def to_dict(self) -> dict:
        data = {
            "type": "error",
            "error_type": self.error_type.value,
            "message": self.message,
            "provider": self.provider,
            "model_id": self.model_id,
            "is_user_quota": self.is_user_quota,
        }
        if self.retry_after is not None:
            data["retry_after"] = self.retry_after
        return data


def normalize_provider_error(
    exc: Exception,
    provider: str = "",
    model_id: str = "",
) -> NormalizedAIError:
    """Classifies any exception into a normalized AI error with user-friendly guidance."""
    if not exc:
        return NormalizedAIError(
            error_type=AIErrorType.UNKNOWN_PROVIDER_ERROR,
            message="An unexpected error occurred while communicating with the AI service.",
            provider=provider,
            model_id=model_id,
            status_code=500,
        )

    exc_str = str(exc)
    exc_lower = exc_str.lower()
    exc_type = type(exc).__name__

    # Extract status code if available on exception
    extracted_status = getattr(exc, "status_code", None)
    if extracted_status is None:
        extracted_status = getattr(exc, "raw_status_code", None)
    if extracted_status is None:
        resp = getattr(exc, "response", None)
        if resp and hasattr(resp, "status_code"):
            extracted_status = resp.status_code
    if extracted_status is None:
        # Check for numeric status patterns like "Error code: 403" or "code=502"
        match = re.search(r"(?:status[_\s]*code|error\s+code|code)[:=\s]+([0-9]{3})", exc_str, re.IGNORECASE)
        if match:
            try:
                extracted_status = int(match.group(1))
            except (ValueError, TypeError):
                pass

    # 1. Check for rate limit / 429
    from chat.services.ai_router import is_rate_limit_error, extract_retry_after
    if extracted_status == 429 or is_rate_limit_error(exc):
        retry_after = extract_retry_after(exc)
        retry_suffix = f" Please try again in about {retry_after}s." if retry_after else " Please wait a moment or select another model."
        return NormalizedAIError(
            error_type=AIErrorType.RATE_LIMITED,
            message=f"The selected provider is temporarily rate-limited.{retry_suffix}",
            provider=provider,
            model_id=model_id,
            retry_after=retry_after,
            status_code=429,
            is_user_quota=False,
        )

    # 2. Check for authentication / permission errors (401 / 403)
    if extracted_status in (401, 403) or any(kw in exc_lower for kw in ("unauthorized", "401", "forbidden", "403", "invalid api key", "authentication", "bad credentials", "tier_not_allowed", "permission_denied")) or exc_type in ("AuthenticationError", "PermissionDeniedError"):
        return NormalizedAIError(
            error_type=AIErrorType.AUTH_ERROR,
            message="The selected AI provider is not configured correctly.",
            provider=provider,
            model_id=model_id,
            status_code=401 if extracted_status != 403 else 403,
        )

    # 3. Check for model not found (404)
    if extracted_status == 404 or any(kw in exc_lower for kw in ("404", "model not found", "does not exist", "decommissioned", "invalid model", "invalid_model", "model_not_found")) or exc_type == "NotFoundError":
        return NormalizedAIError(
            error_type=AIErrorType.MODEL_NOT_FOUND,
            message="This model is currently unavailable.",
            provider=provider,
            model_id=model_id,
            status_code=404,
        )

    # 4. Check for provider overload / capacity limits
    if any(kw in exc_lower for kw in (
        "service temporarily overloaded", "temporarily overloaded", "provider overload",
        "server is temporarily overloaded", "overloaded", "capacity", "provider request failure"
    )):
        return NormalizedAIError(
            error_type=AIErrorType.PROVIDER_OVERLOADED,
            message="The selected provider is temporarily overloaded. Please retry shortly.",
            provider=provider,
            model_id=model_id,
            status_code=503,
        )

    # 5. Check for timeout (408 / 504 / APITimeoutError)
    if extracted_status in (408, 504) or any(kw in exc_lower for kw in ("timeout", "timed out", "deadline exceeded", "request timed out")) or "timeout" in exc_type.lower():
        return NormalizedAIError(
            error_type=AIErrorType.TIMEOUT,
            message="Request to the AI provider timed out. Please try again.",
            provider=provider,
            model_id=model_id,
            status_code=504,
        )

    # 6. Check for invalid request / context length (400)
    if extracted_status == 400 or any(kw in exc_lower for kw in ("context_length_exceeded", "context window", "maximum context length", "too long", "invalid_request_error", "bad request")) or exc_type == "BadRequestError":
        return NormalizedAIError(
            error_type=AIErrorType.INVALID_REQUEST,
            message="The request was invalid or exceeded the model's context limit. Please shorten your message or start a new chat.",
            provider=provider,
            model_id=model_id,
            status_code=400,
        )

    # 7. Check for provider outage / server errors (500 / 502 / 503 / connection errors)
    if extracted_status in (500, 502, 503) or any(kw in exc_lower for kw in ("502", "503", "504", "500", "service unavailable", "bad gateway", "internal server error", "connection refused", "connection error", "failed to connect", "network error", "upstream error")) or exc_type in ("APIConnectionError", "InternalServerError", "BadGatewayError", "ServiceUnavailableError"):
        return NormalizedAIError(
            error_type=AIErrorType.PROVIDER_UNAVAILABLE,
            message="The selected provider is currently unreachable. Please try again.",
            provider=provider,
            model_id=model_id,
            status_code=503,
        )

    # 8. Generic clean fallback - never expose raw python tracebacks
    return NormalizedAIError(
        error_type=AIErrorType.UNKNOWN_PROVIDER_ERROR,
        message="An unexpected provider error occurred. Please try again or select another model.",
        provider=provider,
        model_id=model_id,
        status_code=500,
    )

