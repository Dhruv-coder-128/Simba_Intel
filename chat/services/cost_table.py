"""Static per-model USD cost table for usage estimation/analytics.

Rates are approximate public list prices at the time this table was written
and are NOT wired to any live pricing API - they exist to give the analytics
dashboard a directionally-useful cost figure, not to produce a billing-grade
number. Update the numbers here if a provider changes pricing.
"""
from typing import Dict

# USD per 1,000 tokens.
MODEL_COSTS: Dict[str, Dict[str, float]] = {
    "cyber-max": {"input_per_1k": 0.00011, "output_per_1k": 0.00034},    # groq llama-4-scout
    "nova-mind": {"input_per_1k": 0.0, "output_per_1k": 0.0},            # groq compound-mini (free tier)
    "sky-net": {"input_per_1k": 0.002, "output_per_1k": 0.006},          # mistral-large
    "sky-net-pro": {"input_per_1k": 0.002, "output_per_1k": 0.006},      # mistral-large
    "sky-net-mini": {"input_per_1k": 0.0004, "output_per_1k": 0.002},    # mistral-medium
    "image-studio": {"flat_cost": 0.0},                                  # pollinations (free)
}

DEFAULT_COST = {"input_per_1k": 0.0, "output_per_1k": 0.0}


def estimate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float:
    costs = MODEL_COSTS.get(model_id, DEFAULT_COST)
    if "flat_cost" in costs:
        return costs["flat_cost"]
    cost = (prompt_tokens / 1000) * costs["input_per_1k"] + (completion_tokens / 1000) * costs["output_per_1k"]
    return round(cost, 6)
