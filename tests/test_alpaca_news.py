"""Offline tests for reusable Alpaca company-news request logic."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.alpaca_news import (  # noqa: E402
    MAX_NEWS_PAGE_LIMIT,
    NewsPageCursor,
    advance_news_page,
    build_news_request_parameters,
    parse_news_response_page,
    resolve_news_request_window,
)


START = "2026-08-24T00:00:00Z"
END = "2026-08-28T23:59:59Z"


class AlpacaNewsRequestTests(unittest.TestCase):
    """Verify news request parameters and input validation."""

    def test_builds_contract_parameters_for_project_symbols(self) -> None:
        """Build the expected historical-news request."""

        parameters = build_news_request_parameters(
            ["AAPL", "MSFT"],
            START,
            END,
        )

        self.assertEqual(
            parameters,
            {
                "symbols": "AAPL,MSFT",
                "start": START,
                "end": END,
                "sort": "asc",
                "limit": MAX_NEWS_PAGE_LIMIT,
                "include_content": "true",
                "exclude_contentless": "false",
            },
        )

    def test_adds_normalized_page_token(self) -> None:
        """Add a continuation token without changing request settings."""

        parameters = build_news_request_parameters(
            ["AAPL"],
            START,
            END,
            page_token=" next-page ",
        )

        self.assertEqual(parameters["page_token"], "next-page")
        self.assertEqual(parameters["symbols"], "AAPL")

    def test_rejects_invalid_symbol_inputs(self) -> None:
        """Reject strings, empty collections, blanks, and duplicates."""

        invalid_inputs = (
            "AAPL",
            [],
            ["AAPL", ""],
            ["AAPL", "AAPL"],
        )

        for symbols in invalid_inputs:
            with self.subTest(symbols=symbols):
                with self.assertRaises(ValueError):
                    build_news_request_parameters(
                        symbols,
                        START,
                        END,
                    )

    def test_rejects_blank_date_boundaries(self) -> None:
        """Require both request-window boundaries."""

        invalid_boundaries = (
            ("", END),
            (START, "  "),
        )

        for start, end in invalid_boundaries:
            with self.subTest(start=start, end=end):
                with self.assertRaisesRegex(
                    ValueError,
                    "start and end",
                ):
                    build_news_request_parameters(
                        ["AAPL"],
                        start,
                        end,
                    )

    def test_rejects_invalid_page_limits(self) -> None:
        """Keep news page limits inside the Alpaca-supported range."""

        for limit in (0, MAX_NEWS_PAGE_LIMIT + 1, True, 1.5):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(
                    ValueError,
                    "limit must be",
                ):
                    build_news_request_parameters(
                        ["AAPL"],
                        START,
                        END,
                        limit=limit,
                    )

    def test_rejects_blank_page_token(self) -> None:
        """Reject an unusable continuation token."""

        with self.assertRaisesRegex(
            ValueError,
            "page_token must be nonblank",
        ):
            build_news_request_parameters(
                ["AAPL"],
                START,
                END,
                page_token="  ",
            )


class AlpacaNewsResponseTests(unittest.TestCase):
    """Verify validation of decoded Alpaca news-response pages."""

    def test_parses_valid_response_page(self) -> None:
        """Preserve article payloads, count, and continuation token."""

        payload = {
            "news": [
                {
                    "id": 1,
                    "symbols": ["AAPL"],
                    "headline": "Synthetic headline",
                },
                {
                    "id": 2,
                    "symbols": ["MSFT"],
                    "headline": "Another synthetic headline",
                },
            ],
            "next_page_token": " next-page ",
        }

        result = parse_news_response_page(payload)

        self.assertEqual(result.record_count, 2)
        self.assertEqual(result.next_page_token, "next-page")
        self.assertEqual(result.articles, payload["news"])

    def test_accepts_terminal_empty_page(self) -> None:
        """Accept an empty final response page."""

        result = parse_news_response_page(
            {
                "news": [],
                "next_page_token": None,
            }
        )

        self.assertEqual(result.articles, [])
        self.assertEqual(result.record_count, 0)
        self.assertIsNone(result.next_page_token)

    def test_rejects_invalid_article_structures(self) -> None:
        """Reject missing news collections and malformed articles."""

        invalid_payloads = (
            None,
            [],
            {},
            {"news": {}},
            {"news": [42]},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_news_response_page(payload)

    def test_rejects_invalid_next_page_tokens(self) -> None:
        """Reject blank or non-string continuation tokens."""

        for token in ("  ", 42):
            with self.subTest(token=token):
                with self.assertRaisesRegex(
                    ValueError,
                    "next_page_token",
                ):
                    parse_news_response_page(
                        {
                            "news": [],
                            "next_page_token": token,
                        }
                    )


class AlpacaNewsPaginationTests(unittest.TestCase):
    """Verify bounded and cycle-safe news pagination."""

    def test_advances_to_next_page(self) -> None:
        """Create page two using the first continuation token."""

        result = advance_news_page(
            NewsPageCursor(),
            " next-page ",
        )

        self.assertIsNotNone(result)
        assert result is not None

        self.assertEqual(result.page_number, 2)
        self.assertEqual(result.page_token, "next-page")
        self.assertEqual(
            result.seen_page_tokens,
            frozenset({"next-page"}),
        )

    def test_stops_when_page_token_is_absent(self) -> None:
        """Return None when the current response is the final page."""

        self.assertIsNone(
            advance_news_page(
                NewsPageCursor(),
                None,
            )
        )

    def test_rejects_repeated_page_token(self) -> None:
        """Prevent a token cycle from creating an infinite loop."""

        second_cursor = advance_news_page(
            NewsPageCursor(),
            "page-two",
        )

        assert second_cursor is not None

        with self.assertRaisesRegex(RuntimeError, "repeated"):
            advance_news_page(
                second_cursor,
                "page-two",
            )

    def test_enforces_maximum_page_count(self) -> None:
        """Stop before requesting more than the configured safety limit."""

        with self.assertRaisesRegex(RuntimeError, "page limit"):
            advance_news_page(
                NewsPageCursor(),
                "page-two",
                max_pages=1,
            )


class AlpacaNewsRequestWindowTests(unittest.TestCase):
    """Verify explicit backfill and rolling incremental news intervals."""

    def test_resolves_explicit_backfill_window(self) -> None:
        """Keep a valid historical news interval deterministic."""

        window = resolve_news_request_window(
            " BACKFILL ",
            START,
            END,
        )

        self.assertEqual(window.load_mode, "backfill")
        self.assertEqual(window.start, "2026-08-24T00:00:00+00:00")
        self.assertEqual(window.end, "2026-08-28T23:59:59+00:00")

    def test_rejects_invalid_backfill_window(self) -> None:
        """Require complete, ordered, timezone-aware boundaries."""

        invalid_windows = (
            ("", END),
            (START, ""),
            (END, START),
            ("2026-08-24T00:00:00", END),
        )

        for start, end in invalid_windows:
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    resolve_news_request_window(
                        "backfill",
                        start,
                        end,
                    )

    def test_resolves_delayed_incremental_window(self) -> None:
        """Build a rolling overlap ending fifteen minutes behind now."""

        window = resolve_news_request_window(
            "incremental",
            now=datetime(
                2026,
                9,
                2,
                16,
                0,
                tzinfo=timezone.utc,
            ),
        )

        self.assertEqual(window.load_mode, "incremental")
        self.assertEqual(
            window.start,
            "2026-08-26T15:45:00+00:00",
        )
        self.assertEqual(
            window.end,
            "2026-09-02T15:45:00+00:00",
        )

    def test_rejects_ambiguous_incremental_settings(self) -> None:
        """Reject explicit dates, invalid lookbacks, and naive now."""

        with self.assertRaises(ValueError):
            resolve_news_request_window(
                "incremental",
                START,
                END,
            )

        for lookback_days in (0, 32, True):
            with self.subTest(lookback_days=lookback_days):
                with self.assertRaises(ValueError):
                    resolve_news_request_window(
                        "incremental",
                        lookback_days=lookback_days,
                    )

        with self.assertRaises(ValueError):
            resolve_news_request_window(
                "incremental",
                now=datetime(2026, 9, 2, 16, 0),
            )

    def test_rejects_unknown_load_mode(self) -> None:
        """Require an explicit supported ingestion mode."""

        with self.assertRaisesRegex(
            ValueError,
            "backfill or incremental",
        ):
            resolve_news_request_window("refresh")


if __name__ == "__main__":
    unittest.main()