from __future__ import annotations

import unittest

from equity_research.app_contracts import (
    SUPPORTED_MARKET_WINDOWS,
    build_app_research_selection,
    build_research_request_text,
    company_selector_options,
)
from equity_research.config import Equity
from equity_research.tool_scope import ControlledToolRequestError


EQUITIES = {
    "AAPL": Equity(
        symbol="AAPL",
        display_name="Apple Inc.",
        alpaca_symbol="AAPL",
        sec_cik="0000320193",
    ),
    "MSFT": Equity(
        symbol="MSFT",
        display_name="Microsoft Corporation",
        alpaca_symbol="MSFT",
        sec_cik="0000789019",
    ),
}


class AppContractsTests(unittest.TestCase):
    def test_company_selector_options_are_searchable_and_stable(self) -> None:
        options = company_selector_options(
            EQUITIES
        )

        self.assertEqual(
            [option.symbol for option in options],
            ["AAPL", "MSFT"],
        )
        self.assertEqual(
            options[0].label,
            "Apple Inc. (AAPL)",
        )
        self.assertEqual(
            options[1].label,
            "Microsoft Corporation (MSFT)",
        )

    def test_single_company_selection(self) -> None:
        selection = build_app_research_selection(
            primary_symbol=" aapl ",
            comparison_symbol=None,
            market_window_sessions=60,
            equities=EQUITIES,
        )

        self.assertEqual(
            selection.requested_symbols,
            ("AAPL",),
        )
        self.assertEqual(
            selection.mode,
            "single_company",
        )

    def test_comparison_selection(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol=" msft ",
            market_window_sessions=20,
            equities=EQUITIES,
        )

        self.assertEqual(
            selection.requested_symbols,
            ("AAPL", "MSFT"),
        )
        self.assertEqual(
            selection.mode,
            "comparison",
        )

    def test_blank_comparison_symbol_means_single_company(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol="  ",
            market_window_sessions=5,
            equities=EQUITIES,
        )

        self.assertEqual(
            selection.requested_symbols,
            ("AAPL",),
        )

    def test_duplicate_symbols_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolRequestError,
            "unique",
        ):
            build_app_research_selection(
                primary_symbol="AAPL",
                comparison_symbol="aapl",
                market_window_sessions=20,
                equities=EQUITIES,
            )

    def test_unsupported_symbol_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolRequestError,
            "Unsupported symbol",
        ):
            build_app_research_selection(
                primary_symbol="NVDA",
                comparison_symbol=None,
                market_window_sessions=20,
                equities=EQUITIES,
            )

    def test_market_window_is_bounded_to_gold_windows(self) -> None:
        self.assertEqual(
            SUPPORTED_MARKET_WINDOWS,
            (1, 5, 20, 60),
        )

        with self.assertRaisesRegex(
            ValueError,
            "market_window_sessions",
        ):
            build_app_research_selection(
                primary_symbol="AAPL",
                comparison_symbol=None,
                market_window_sessions=30,
                equities=EQUITIES,
            )

    def test_request_text_uses_exact_selected_window(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol="MSFT",
            market_window_sessions=60,
            equities=EQUITIES,
        )

        request_text = build_research_request_text(
            selection,
            equities=EQUITIES,
        )

        self.assertIn(
            "Compare Apple Inc. (AAPL) and Microsoft Corporation (MSFT).",
            request_text,
        )
        self.assertIn(
            "60-trading-session",
            request_text,
        )
        self.assertIn(
            "bounded to the available controlled data and evidence",
            request_text,
        )


if __name__ == "__main__":
    unittest.main()
