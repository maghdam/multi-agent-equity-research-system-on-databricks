"""Offline tests for reusable Alpaca daily-price request logic."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.alpaca_prices import (  # noqa: E402
    MAX_PAGE_LIMIT,
    PricePageCursor,
    advance_price_page,
    build_price_request_parameters,
    parse_price_response_page,
    resolve_price_request_window,
)
from equity_research.config import load_equities  # noqa: E402


START = "2026-08-27T00:00:00-04:00"
END = "2026-08-27T23:59:59-04:00"


class AlpacaPriceRequestTests(unittest.TestCase):
    """Verify contract parameters, pagination, and input validation."""

    def test_builds_contract_parameters_for_project_symbols(self) -> None:
        """Build the exact daily-price contract for configured equities."""

        equities = load_equities()
        symbols = [
            equity.alpaca_symbol for equity in equities.values()
        ]

        parameters = build_price_request_parameters(
            symbols,
            START,
            END,
        )

        self.assertEqual(
            parameters,
            {
                "symbols": "AAPL,MSFT",
                "timeframe": "1Day",
                "start": START,
                "end": END,
                "feed": "sip",
                "adjustment": "split",
                "currency": "USD",
                "limit": MAX_PAGE_LIMIT,
                "sort": "asc",
            },
        )

    def test_adds_normalized_page_token(self) -> None:
        """Add a continuation token without changing contract settings."""

        parameters = build_price_request_parameters(
            ["AAPL", "MSFT"],
            START,
            END,
            page_token=" next-page ",
        )

        self.assertEqual(parameters["page_token"], "next-page")
        self.assertEqual(parameters["symbols"], "AAPL,MSFT")
        self.assertEqual(parameters["timeframe"], "1Day")

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
                    build_price_request_parameters(
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
                    build_price_request_parameters(
                        ["AAPL"],
                        start,
                        end,
                    )

    def test_rejects_invalid_page_limits(self) -> None:
        """Keep Alpaca page limits inside the supported range."""

        for limit in (0, MAX_PAGE_LIMIT + 1, True):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(
                    ValueError,
                    "limit must be",
                ):
                    build_price_request_parameters(
                        ["AAPL"],
                        START,
                        END,
                        limit=limit,
                    )

    def test_rejects_blank_page_token(self) -> None:
        """Reject an unusable pagination continuation token."""

        with self.assertRaisesRegex(
            ValueError,
            "page_token must be nonblank",
        ):
            build_price_request_parameters(
                ["AAPL"],
                START,
                END,
                page_token="  ",
            )


class AlpacaPriceResponseTests(unittest.TestCase):
    """Verify validation of decoded Alpaca price-response pages."""

    def test_parses_valid_response_page(self) -> None:
        """Return normalized bars, record count, and continuation token."""

        result = parse_price_response_page(
            {
                "bars": {
                    "AAPL": [{"c": 100.0}],
                    "MSFT": [{"c": 200.0}],
                },
                "next_page_token": " next-page ",
            }
        )

        self.assertEqual(result.record_count, 2)
        self.assertEqual(result.next_page_token, "next-page")
        self.assertEqual(result.bars["AAPL"][0]["c"], 100.0)

    def test_accepts_terminal_empty_page(self) -> None:
        """Accept an empty final page without a continuation token."""

        result = parse_price_response_page(
            {
                "bars": {},
                "next_page_token": None,
            }
        )

        self.assertEqual(result.bars, {})
        self.assertEqual(result.record_count, 0)
        self.assertIsNone(result.next_page_token)

    def test_rejects_invalid_bar_structures(self) -> None:
        """Reject missing bars, invalid collections, and invalid records."""

        invalid_payloads = (
            None,
            [],
            {},
            {"bars": []},
            {"bars": {"AAPL": {}}},
            {"bars": {"AAPL": [42]}},
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    parse_price_response_page(payload)

    def test_rejects_invalid_next_page_tokens(self) -> None:
        """Reject blank or non-string continuation tokens."""

        for token in ("  ", 42):
            with self.subTest(token=token):
                with self.assertRaisesRegex(
                    ValueError,
                    "next_page_token",
                ):
                    parse_price_response_page(
                        {
                            "bars": {},
                            "next_page_token": token,
                        }
                    )


class AlpacaPricePaginationTests(unittest.TestCase):
    """Verify bounded and cycle-safe response pagination."""

    def test_advances_to_next_page(self) -> None:
        """Create page two using the first continuation token."""

        first_cursor = PricePageCursor()

        second_cursor = advance_price_page(
            first_cursor,
            " next-page ",
        )

        self.assertIsNotNone(second_cursor)
        assert second_cursor is not None

        self.assertEqual(second_cursor.page_number, 2)
        self.assertEqual(second_cursor.page_token, "next-page")
        self.assertEqual(
            second_cursor.seen_page_tokens,
            frozenset({"next-page"}),
        )

    def test_stops_when_page_token_is_absent(self) -> None:
        """Return None when the current response is the final page."""

        next_cursor = advance_price_page(
            PricePageCursor(),
            None,
        )

        self.assertIsNone(next_cursor)

    def test_rejects_repeated_page_token(self) -> None:
        """Prevent an API token cycle from creating an infinite loop."""

        second_cursor = advance_price_page(
            PricePageCursor(),
            "page-two",
        )

        assert second_cursor is not None

        with self.assertRaisesRegex(RuntimeError, "repeated"):
            advance_price_page(
                second_cursor,
                "page-two",
            )

    def test_enforces_maximum_page_count(self) -> None:
        """Stop pagination before requesting more than the safety limit."""

        with self.assertRaisesRegex(RuntimeError, "page limit"):
            advance_price_page(
                PricePageCursor(),
                "page-two",
                max_pages=1,
            )




class AlpacaPriceRequestWindowTests(unittest.TestCase):
    """Verify explicit backfill and rolling incremental request intervals."""

    def test_resolves_explicit_backfill_window(self) -> None:
        """Keep a valid caller-supplied historical interval deterministic."""

        window = resolve_price_request_window(
            " BACKFILL ",
            START,
            END,
        )

        self.assertEqual(window.load_mode, "backfill")
        self.assertEqual(window.start, START)
        self.assertEqual(window.end, END)

    def test_rejects_invalid_backfill_window(self) -> None:
        """Require complete, ordered, timezone-aware backfill boundaries."""

        invalid_windows = (
            ("", END),
            (START, ""),
            (END, START),
            ("2026-08-27T00:00:00", END),
        )

        for start, end in invalid_windows:
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    resolve_price_request_window(
                        "backfill",
                        start,
                        end,
                    )

    def test_resolves_completed_incremental_window(self) -> None:
        """Build a seven-day overlap ending on the prior New York day."""

        window = resolve_price_request_window(
            "incremental",
            now=datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(window.load_mode, "incremental")
        self.assertEqual(window.start, "2026-08-26T00:00:00-04:00")
        self.assertEqual(window.end, "2026-09-01T23:59:59-04:00")

    def test_rejects_ambiguous_incremental_settings(self) -> None:
        """Reject explicit dates, invalid lookbacks, and naive current time."""

        with self.assertRaises(ValueError):
            resolve_price_request_window(
                "incremental",
                START,
                END,
            )

        for lookback_days in (0, 32, True):
            with self.subTest(lookback_days=lookback_days):
                with self.assertRaises(ValueError):
                    resolve_price_request_window(
                        "incremental",
                        lookback_days=lookback_days,
                    )

        with self.assertRaises(ValueError):
            resolve_price_request_window(
                "incremental",
                now=datetime(2026, 9, 2, 12, 0),
            )


if __name__ == "__main__":
    unittest.main()
