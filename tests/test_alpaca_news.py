import pytest

from equity_research.alpaca_news import (
    NewsPageCursor,
    advance_news_page,
    build_news_request_parameters,
    parse_news_response_page,
)


def test_build_news_request_parameters_uses_configured_symbols_and_content():
    params = build_news_request_parameters(
        ["AAPL", "MSFT"],
        "2026-08-24T00:00:00Z",
        "2026-08-28T23:59:59Z",
        limit=3,
    )

    assert params == {
        "symbols": "AAPL,MSFT",
        "start": "2026-08-24T00:00:00Z",
        "end": "2026-08-28T23:59:59Z",
        "sort": "asc",
        "limit": 3,
        "include_content": "true",
        "exclude_contentless": "false",
    }


def test_build_news_request_parameters_includes_page_token():
    params = build_news_request_parameters(
        ["AAPL"],
        "2026-08-24T00:00:00Z",
        "2026-08-28T23:59:59Z",
        page_token=" next ",
    )
    assert params["page_token"] == "next"


@pytest.mark.parametrize("limit", [0, 51, True, 1.5])
def test_build_news_request_parameters_rejects_invalid_limit(limit):
    with pytest.raises(ValueError):
        build_news_request_parameters(
            ["AAPL"],
            "2026-08-24T00:00:00Z",
            "2026-08-28T23:59:59Z",
            limit=limit,
        )


def test_parse_news_response_page_preserves_articles():
    payload = {
        "news": [
            {"id": 1, "symbols": ["AAPL"], "headline": "Synthetic headline"},
            {"id": 2, "symbols": ["MSFT"], "headline": "Another synthetic headline"},
        ],
        "next_page_token": "token-2",
    }

    page = parse_news_response_page(payload)

    assert page.record_count == 2
    assert page.next_page_token == "token-2"
    assert page.articles == payload["news"]


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {},
        {"news": {}},
        {"news": [1]},
        {"news": [], "next_page_token": ""},
    ],
)
def test_parse_news_response_page_rejects_invalid_structure(payload):
    with pytest.raises(ValueError):
        parse_news_response_page(payload)


def test_advance_news_page_finishes_without_token():
    assert advance_news_page(NewsPageCursor(), None) is None


def test_advance_news_page_tracks_token_history():
    cursor = advance_news_page(NewsPageCursor(), "token-2")
    assert cursor == NewsPageCursor(
        page_number=2,
        page_token="token-2",
        seen_page_tokens=frozenset({"token-2"}),
    )


def test_advance_news_page_rejects_repeated_token():
    cursor = NewsPageCursor(
        page_number=2,
        page_token="token-2",
        seen_page_tokens=frozenset({"token-2"}),
    )
    with pytest.raises(RuntimeError, match="repeated page token"):
        advance_news_page(cursor, "token-2")


def test_advance_news_page_enforces_page_bound():
    cursor = NewsPageCursor(page_number=2)
    with pytest.raises(RuntimeError, match="2-page limit"):
        advance_news_page(cursor, "token-3", max_pages=2)
