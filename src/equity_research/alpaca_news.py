"""Reusable Alpaca company-news request logic."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

MAX_NEWS_PAGE_LIMIT = 50
MAX_NEWS_RESPONSE_PAGES = 100


@dataclass(frozen=True)
class NewsResponsePage:
    """Validated contents and metadata from one Alpaca news response page."""

    articles: list[dict[str, object]]
    next_page_token: str | None
    record_count: int


@dataclass(frozen=True)
class NewsPageCursor:
    """Position and safety history for an Alpaca news pagination sequence."""

    page_number: int = 1
    page_token: str | None = None
    seen_page_tokens: frozenset[str] = frozenset()


def build_news_request_parameters(
    symbols: Sequence[str],
    start: str,
    end: str,
    *,
    page_token: str | None = None,
    limit: int = MAX_NEWS_PAGE_LIMIT,
) -> dict[str, str | int]:
    """Build one credential-free Alpaca historical-news request."""

    if isinstance(symbols, str):
        raise ValueError("symbols must be a sequence, not one string.")

    normalized_symbols = tuple(symbol.strip() for symbol in symbols)

    if not normalized_symbols or any(not symbol for symbol in normalized_symbols):
        raise ValueError("symbols must contain at least one nonblank symbol.")

    if len(set(normalized_symbols)) != len(normalized_symbols):
        raise ValueError("symbols must not contain duplicates.")

    normalized_start = start.strip()
    normalized_end = end.strip()

    if not normalized_start or not normalized_end:
        raise ValueError("start and end must be nonblank.")

    if (
        isinstance(limit, bool)
        or not isinstance(limit, int)
        or not 1 <= limit <= MAX_NEWS_PAGE_LIMIT
    ):
        raise ValueError(
            f"limit must be an integer from 1 to {MAX_NEWS_PAGE_LIMIT}."
        )

    parameters: dict[str, str | int] = {
        "symbols": ",".join(normalized_symbols),
        "start": normalized_start,
        "end": normalized_end,
        "sort": "asc",
        "limit": limit,
        "include_content": "true",
        "exclude_contentless": "false",
    }

    if page_token is not None:
        normalized_page_token = page_token.strip()
        if not normalized_page_token:
            raise ValueError("page_token must be nonblank when provided.")
        parameters["page_token"] = normalized_page_token

    return parameters


def parse_news_response_page(payload: object) -> NewsResponsePage:
    """Validate and normalize one decoded Alpaca news response page."""

    if not isinstance(payload, Mapping):
        raise ValueError("response payload must be a JSON object.")

    raw_articles = payload.get("news")
    if not isinstance(raw_articles, list):
        raise ValueError("response payload must contain a news list.")

    articles: list[dict[str, object]] = []
    for article in raw_articles:
        if not isinstance(article, Mapping):
            raise ValueError("each news article must be a JSON object.")
        articles.append(dict(article))

    raw_next_page_token = payload.get("next_page_token")
    if raw_next_page_token is None:
        next_page_token = None
    elif isinstance(raw_next_page_token, str) and raw_next_page_token.strip():
        next_page_token = raw_next_page_token.strip()
    else:
        raise ValueError("next_page_token must be null or a nonblank string.")

    return NewsResponsePage(
        articles=articles,
        next_page_token=next_page_token,
        record_count=len(articles),
    )


def advance_news_page(
    cursor: NewsPageCursor,
    next_page_token: str | None,
    *,
    max_pages: int = MAX_NEWS_RESPONSE_PAGES,
) -> NewsPageCursor | None:
    """Return the next news cursor, or None when pagination is complete."""

    if (
        isinstance(max_pages, bool)
        or not isinstance(max_pages, int)
        or max_pages < 1
    ):
        raise ValueError("max_pages must be a positive integer.")

    if next_page_token is None:
        return None

    if not isinstance(next_page_token, str) or not next_page_token.strip():
        raise ValueError("next_page_token must be null or a nonblank string.")

    normalized_token = next_page_token.strip()

    if normalized_token in cursor.seen_page_tokens:
        raise RuntimeError("Alpaca pagination returned a repeated page token.")

    if cursor.page_number >= max_pages:
        raise RuntimeError(
            f"Alpaca pagination exceeded the {max_pages}-page limit."
        )

    return NewsPageCursor(
        page_number=cursor.page_number + 1,
        page_token=normalized_token,
        seen_page_tokens=(
            cursor.seen_page_tokens | frozenset({normalized_token})
        ),
    )
