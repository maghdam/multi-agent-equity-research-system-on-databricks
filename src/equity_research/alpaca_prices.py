"""Reusable Alpaca daily-price request logic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


MAX_PAGE_LIMIT = 10_000
MAX_RESPONSE_PAGES = 100
MAX_REQUEST_ATTEMPTS = 3
BASE_RETRY_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 30.0
RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 500, 502, 503, 504})
DEFAULT_INCREMENTAL_LOOKBACK_DAYS = 7
MAX_INCREMENTAL_LOOKBACK_DAYS = 31
NEW_YORK_TIMEZONE = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class PriceResponsePage:
    """Validated contents and metadata from one Alpaca response page."""

    bars: dict[str, list[dict[str, object]]]
    next_page_token: str | None
    record_count: int


@dataclass(frozen=True)
class PricePageCursor:
    """Position and safety history for an Alpaca pagination sequence."""

    page_number: int = 1
    page_token: str | None = None
    seen_page_tokens: frozenset[str] = frozenset()


@dataclass(frozen=True)
class PriceRequestWindow:
    """Resolved inclusive Alpaca request interval and its load mode."""

    load_mode: str
    start: str
    end: str


def build_price_request_parameters(
    symbols: Sequence[str],
    start: str,
    end: str,
    *,
    page_token: str | None = None,
    limit: int = MAX_PAGE_LIMIT,
) -> dict[str, str | int]:
    """Build one credential-free Alpaca daily-bars request."""

    if isinstance(symbols, str):
        raise ValueError("symbols must be a sequence, not one string.")

    normalized_symbols = tuple(symbol.strip() for symbol in symbols)

    if not normalized_symbols or any(
        not symbol for symbol in normalized_symbols
    ):
        raise ValueError(
            "symbols must contain at least one nonblank symbol."
        )

    if len(set(normalized_symbols)) != len(normalized_symbols):
        raise ValueError("symbols must not contain duplicates.")

    normalized_start = start.strip()
    normalized_end = end.strip()

    if not normalized_start or not normalized_end:
        raise ValueError("start and end must be nonblank.")

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_PAGE_LIMIT
    ):
        raise ValueError(
            f"limit must be an integer from 1 to {MAX_PAGE_LIMIT}."
        )

    parameters: dict[str, str | int] = {
        "symbols": ",".join(normalized_symbols),
        "timeframe": "1Day",
        "start": normalized_start,
        "end": normalized_end,
        "feed": "sip",
        "adjustment": "split",
        "currency": "USD",
        "limit": limit,
        "sort": "asc",
    }

    if page_token is not None:
        normalized_page_token = page_token.strip()

        if not normalized_page_token:
            raise ValueError(
                "page_token must be nonblank when provided."
            )

        parameters["page_token"] = normalized_page_token

    return parameters


def parse_price_response_page(payload: object) -> PriceResponsePage:
    """Validate and normalize one decoded Alpaca price-response page."""

    if not isinstance(payload, Mapping):
        raise ValueError("response payload must be a JSON object.")

    raw_bars = payload.get("bars")

    if not isinstance(raw_bars, Mapping):
        raise ValueError(
            "response payload must contain a bars object."
        )

    normalized_bars: dict[str, list[dict[str, object]]] = {}
    record_count = 0

    for raw_symbol, raw_records in raw_bars.items():
        if not isinstance(raw_symbol, str) or not raw_symbol.strip():
            raise ValueError(
                "bar symbols must be nonblank strings."
            )

        symbol = raw_symbol.strip()

        if symbol in normalized_bars:
            raise ValueError(
                "bar symbols must be unique after normalization."
            )

        if not isinstance(raw_records, list):
            raise ValueError(
                f"bars for {symbol} must be provided as a list."
            )

        records: list[dict[str, object]] = []

        for record in raw_records:
            if not isinstance(record, Mapping):
                raise ValueError(
                    f"each bar for {symbol} must be a JSON object."
                )

            records.append(dict(record))

        normalized_bars[symbol] = records
        record_count += len(records)

    raw_next_page_token = payload.get("next_page_token")

    if raw_next_page_token is None:
        next_page_token = None
    elif (
        isinstance(raw_next_page_token, str)
        and raw_next_page_token.strip()
    ):
        next_page_token = raw_next_page_token.strip()
    else:
        raise ValueError(
            "next_page_token must be null or a nonblank string."
        )

    return PriceResponsePage(
        bars=normalized_bars,
        next_page_token=next_page_token,
        record_count=record_count,
    )


def advance_price_page(
    cursor: PricePageCursor,
    next_page_token: str | None,
    *,
    max_pages: int = MAX_RESPONSE_PAGES,
) -> PricePageCursor | None:
    """Return the next cursor, or None when pagination is complete."""

    if (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or max_pages < 1
    ):
        raise ValueError("max_pages must be a positive integer.")

    if next_page_token is None:
        return None

    if not isinstance(next_page_token, str) or not next_page_token.strip():
        raise ValueError(
            "next_page_token must be null or a nonblank string."
        )

    normalized_token = next_page_token.strip()

    if normalized_token in cursor.seen_page_tokens:
        raise RuntimeError("Alpaca pagination returned a repeated page token.")

    if cursor.page_number >= max_pages:
        raise RuntimeError(
            f"Alpaca pagination exceeded the {max_pages}-page limit."
        )

    return PricePageCursor(
        page_number=cursor.page_number + 1,
        page_token=normalized_token,
        seen_page_tokens=(
            cursor.seen_page_tokens | frozenset({normalized_token})
        ),
    )


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


def resolve_price_request_window(
    load_mode: str,
    start: str = "",
    end: str = "",
    *,
    lookback_days: int = DEFAULT_INCREMENTAL_LOOKBACK_DAYS,
    now: datetime | None = None,
) -> PriceRequestWindow:
    """Resolve an explicit backfill or completed-day incremental interval."""

    normalized_mode = load_mode.strip().lower()
    if normalized_mode not in {"backfill", "incremental"}:
        raise ValueError("load_mode must be backfill or incremental.")

    normalized_start = start.strip()
    normalized_end = end.strip()

    if normalized_mode == "backfill":
        if not normalized_start or not normalized_end:
            raise ValueError(
                "backfill mode requires nonblank start and end timestamps."
            )

        start_datetime = _parse_aware_timestamp(normalized_start, "start")
        end_datetime = _parse_aware_timestamp(normalized_end, "end")

        if start_datetime >= end_datetime:
            raise ValueError("backfill start must be earlier than end.")

        return PriceRequestWindow(
            load_mode=normalized_mode,
            start=start_datetime.isoformat(),
            end=end_datetime.isoformat(),
        )

    if normalized_start or normalized_end:
        raise ValueError(
            "incremental mode calculates start and end; leave both blank."
        )

    if (
        isinstance(lookback_days, bool)
        or not isinstance(lookback_days, int)
        or not 1 <= lookback_days <= MAX_INCREMENTAL_LOOKBACK_DAYS
    ):
        raise ValueError(
            "lookback_days must be an integer from 1 to "
            f"{MAX_INCREMENTAL_LOOKBACK_DAYS}."
        )

    reference_time = now or datetime.now(timezone.utc)
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")

    market_date = reference_time.astimezone(NEW_YORK_TIMEZONE).date()
    end_date = market_date - timedelta(days=1)
    start_date = end_date - timedelta(days=lookback_days - 1)

    start_datetime = datetime.combine(
        start_date,
        time.min,
        tzinfo=NEW_YORK_TIMEZONE,
    )
    end_datetime = datetime.combine(
        end_date,
        time(23, 59, 59),
        tzinfo=NEW_YORK_TIMEZONE,
    )

    return PriceRequestWindow(
        load_mode=normalized_mode,
        start=start_datetime.isoformat(),
        end=end_datetime.isoformat(),
    )


def _parse_aware_timestamp(value: str, parameter: str) -> datetime:
    """Parse one RFC-3339-style timestamp and require its UTC offset."""

    normalized_value = value[:-1] + "+00:00" if value.endswith("Z") else value

    try:
        parsed = datetime.fromisoformat(normalized_value)
    except ValueError as exc:
        raise ValueError(
            f"{parameter} must be a valid timezone-aware timestamp."
        ) from exc

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(
            f"{parameter} must be a valid timezone-aware timestamp."
        )

    return parsed
