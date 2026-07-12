
import logging
import os
from datetime import datetime


class SimbaLogger:
    def __init__(self, name: str = "simba_intel"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

    def log_request(
        self,
        provider: str,
        latency: float,
        prompt_length: int,
        response_length: int,
        token_usage: dict = None,
        error: str = None,
    ):
        self.logger.info(
            f"Request: provider=%s, latency=%.2fs, prompt_len=%d, resp_len=%d, token_usage=%s, error=%s",
            provider, latency, prompt_length, response_length, token_usage, error
        )
