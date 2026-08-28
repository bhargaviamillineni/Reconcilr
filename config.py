"""
Centralized configuration for the reconciliation pipeline.
All tunable constants live here and can be overridden via environment variables.
"""

import os


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


AMOUNT_TOLERANCE = _float_env("AMOUNT_TOLERANCE", 5.00)
DATE_WINDOW_DAYS = _int_env("DATE_WINDOW_DAYS", 6)
DETERMINISTIC_CONFIDENCE_THRESHOLD = _float_env("DETERMINISTIC_CONFIDENCE_THRESHOLD", 80)

LLM_CONFIDENCE_THRESHOLD = _float_env("LLM_CONFIDENCE_THRESHOLD", 70)
LLM_BATCH_SIZE = _int_env("LLM_BATCH_SIZE", 8)
LLM_MAX_CANDIDATES_PER_BATCH = _int_env("LLM_MAX_CANDIDATES_PER_BATCH", 30)
LLM_MAX_CALLS_PER_RUN = _int_env("LLM_MAX_CALLS_PER_RUN", 50)

LLM_COST_PER_CALL = {
    "openai": 0.0005,
    "gemini": 0.0001,
    "groq": 0.00001,
}

WEBSITE_ORDERS_PATH = os.getenv("WEBSITE_ORDERS_PATH", "data/website_orders.csv")
GATEWAY_SETTLEMENT_PATH = os.getenv("GATEWAY_SETTLEMENT_PATH", "data/gateway_settlement.csv")
GROUND_TRUTH_PATH = os.getenv("GROUND_TRUTH_PATH", "data/ground_truth.csv")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
