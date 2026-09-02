"""Shared Alpaca HTTP retry-policy helpers."""

from __future__ import annotations


MAX_REQUEST_ATTEMPTS = 3
BASE_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 30.0
RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def is_retryable_http_status(status: int) -> bool:
    """Return whether an HTTP status represents a temporary source failure."""

    if (
        isinstance(status, bool)
        or not isinstance(status, int)
        or not 100 <= status <= 599
    ):
        raise ValueError("status must be an integer HTTP status code.")

    return status in RETRYABLE_HTTP_STATUSES


def calculate_retry_delay(
    attempt_number: int,
    retry_after_header: str | None = None,
    *,
    base_delay_seconds: float = BASE_RETRY_DELAY_SECONDS,
    max_delay_seconds: float = MAX_RETRY_DELAY_SECONDS,
) -> float:
    """Calculate bounded exponential backoff for one failed attempt."""

    if (
        isinstance(attempt_number, bool)
        or not isinstance(attempt_number, int)
        or attempt_number < 1
    ):
        raise ValueError("attempt_number must be a positive integer.")

    if (
        isinstance(base_delay_seconds, bool)
        or not isinstance(base_delay_seconds, (int, float))
        or base_delay_seconds <= 0
    ):
        raise ValueError("base_delay_seconds must be positive.")

    if (
        isinstance(max_delay_seconds, bool)
        or not isinstance(max_delay_seconds, (int, float))
        or max_delay_seconds < base_delay_seconds
    ):
        raise ValueError(
            "max_delay_seconds must be at least base_delay_seconds."
        )

    exponential_delay = min(
        float(base_delay_seconds) * (2 ** (attempt_number - 1)),
        float(max_delay_seconds),
    )

    if retry_after_header is None:
        return exponential_delay

    try:
        retry_after_delay = float(retry_after_header.strip())
    except (AttributeError, ValueError):
        return exponential_delay

    if retry_after_delay < 0:
        return exponential_delay

    return min(
        max(exponential_delay, retry_after_delay),
        float(max_delay_seconds),
    )