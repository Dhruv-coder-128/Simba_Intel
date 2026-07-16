
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
    ):
        self.logger.info(
            f"Request: provider=%s, latency=%.2fs, prompt_len=%d, resp_len=%d, token_usage=%s, error=%s",
            provider, latency, prompt_length, response_length, token_usage, error
        )
        if error:
            # Every AI provider call already funnels here on failure - this
            # is the single choke point chat/models.py's ErrorLog (Error
            # Center) is fed from, rather than adding a try/except at every
            # call site individually.
            from chat.models import ErrorLog
            try:
                ErrorLog.record(category=category, message=error, detail=f"provider={provider}")
            except Exception:
                # Recording the error must never itself become a new,
                # unhandled error inside the AI request path.
                self.logger.exception("Failed to record ErrorLog entry")
