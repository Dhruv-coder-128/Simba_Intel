
import logging
import os
from datetime import datetime


class SimbaLogger:
    def __init__(self, name: str = "simba_intel"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        # This logger manages its own handler/formatter below - without
        # propagate=False, every record also bubbles up to Django's root
        # logger (see simba_web/settings.py's LOGGING config) and gets
        # printed a second time through its handler too.
        self.logger.propagate = False
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

            # This logger doesn't propagate to the root logger (see above),
            # so it needs its own copy of the ring-buffer handler too, for
            # the admin console's Live Monitor "Live Log Stream" panel to
            # see AI-request logs, not just Django's own.
            from chat.log_buffer import RingBufferHandler
            ring_handler = RingBufferHandler()
            ring_handler.setFormatter(formatter)
            self.logger.addHandler(ring_handler)

    def log_request(
        self,
        provider: str,
        latency: float,
        prompt_length: int,
        response_length: int,
        token_usage: dict = None,
        error: str = None,
        category: str = "chat_provider",
        model: str = "",
        routing_mode: str = "",
        status_code: int = 200,
        retry_count: int = 0,
    ):
        # Sanitize error message to ensure no API keys / auth tokens are logged
        safe_error = None
        if error:
            safe_error = str(error)
            # Mask potential bearer tokens or 32+ character hex/alphanumeric keys
            import re
            safe_error = re.sub(r'(?:bearer\s+|key[=:\s]+|gsk_|nvapi-|sk-)[a-zA-Z0-9_\-]{16,}', '[REDACTED_SECRET]', safe_error, flags=re.IGNORECASE)

        self.logger.info(
            f"[AI_GENERATION] provider=%s model=%s mode=%s latency=%.2fs status=%d retries=%d prompt_len=%d resp_len=%d token_usage=%s error=%s",
            provider, model or "unknown", routing_mode or "default", latency, status_code, retry_count, prompt_length, response_length, token_usage, safe_error
        )
        if error:
            from chat.models import ErrorLog
            try:
                ErrorLog.record(category=category, message=safe_error or "Provider error", detail=f"provider={provider} model={model} mode={routing_mode} status={status_code}")
            except Exception:
                self.logger.exception("Failed to record ErrorLog entry")
