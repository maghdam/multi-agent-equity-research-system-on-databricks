"""Shared SEC HTTP access-policy and retry helpers."""

from __future__ import annotations


MAX_SEC_REQUEST_ATTEMPTS = 3
MIN_SEC_REQUEST_INTERVAL_SECONDS = 0.2
BASE_SEC_RETRY_DELAY_SECONDS = 1.0
MAX_SEC_RETRY_DELAY_SECONDS = 30.0

RETRYABLE_SEC_HTTP_STATUSES = frozenset(
    {
        429,
        500,
        502,
        503,
        504,
    }
)

def build_sec_html_request_headers(
    user_agent: str,
) -> dict[str, str]:
    """Build headers for an identified SEC HTML document request."""

    normalized_user_agent = user_agent.strip()

    if not normalized_user_agent:
        raise ValueError("user_agent must be nonblank.")

    return {
        "User-Agent": normalized_user_agent,
        "Accept": "text/html, application/xhtml+xml",
        "Accept-Encoding": "identity",
    }

def build_sec_request_headers(
    user_agent: str,
) -> dict[str, str]:
    """Build headers required for an identified SEC automated request."""

    normalized_user_agent = user_agent.strip()

    if not normalized_user_agent:
        raise ValueError("user_agent must be nonblank.")

    return {
        "User-Agent": normalized_user_agent,
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }


def is_retryable_sec_http_status(status: int) -> bool:
    """Return whether an SEC HTTP failure is suitable for a bounded retry."""

    if (
        isinstance(status, bool)
        or not isinstance(status, int)
        or not 100 <= status <= 599
    ):
        raise ValueError("status must be an integer HTTP status code.")

    return status in RETRYABLE_SEC_HTTP_STATUSES


def calculate_sec_retry_delay(
    attempt_number: int,
    retry_after_header: str | None = None,
    *,
    base_delay_seconds: float = BASE_SEC_RETRY_DELAY_SECONDS,
    max_delay_seconds: float = MAX_SEC_RETRY_DELAY_SECONDS,
) -> float:
    """Calculate bounded exponential backoff for one failed SEC request."""

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


def calculate_sec_spacing_delay(
    elapsed_seconds: float,
    *,
    minimum_interval_seconds: float = MIN_SEC_REQUEST_INTERVAL_SECONDS,
) -> float:
    """Return the remaining delay before another SEC request is allowed."""

    if (
        isinstance(elapsed_seconds, bool)
        or not isinstance(elapsed_seconds, (int, float))
        or elapsed_seconds < 0
    ):
        raise ValueError("elapsed_seconds must be nonnegative.")

    if (
        isinstance(minimum_interval_seconds, bool)
        or not isinstance(minimum_interval_seconds, (int, float))
        or minimum_interval_seconds <= 0
    ):
        raise ValueError("minimum_interval_seconds must be positive.")

    return max(
        0.0,
        float(minimum_interval_seconds) - float(elapsed_seconds),
    )