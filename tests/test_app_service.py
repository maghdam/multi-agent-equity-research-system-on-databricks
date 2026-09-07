from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.app_contracts import (  # noqa: E402
    build_app_research_selection,
)
from equity_research.app_service import (  # noqa: E402
    AppResearchSession,
    AppStructuredSnapshot,
    run_app_research,
)
from equity_research.config import Equity  # noqa: E402
from equity_research.structured_data_tools import (  # noqa: E402
    FundamentalMetricsToolResult,
    MarketMetricsToolResult,
)
from equity_research.supervisor_research_graph import (  # noqa: E402
    SupervisorResearchResult,
)


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


def _market_result(symbol: str) -> MarketMetricsToolResult:
    return MarketMetricsToolResult(
        symbol=symbol,
        display_name=EQUITIES[symbol].display_name,
        status="unavailable",
        reason_code="missing",
        limitation="Synthetic test limitation.",
        metric=None,
    )


def _fundamental_result(
    symbol: str,
) -> FundamentalMetricsToolResult:
    return FundamentalMetricsToolResult(
        symbol=symbol,
        display_name=EQUITIES[symbol].display_name,
        status="unavailable",
        reason_code="missing",
        limitation="Synthetic test limitation.",
        metric=None,
    )


class FakeRuntime:
    def __init__(
        self,
        *,
        structured: AppStructuredSnapshot,
        report_symbols: tuple[str, ...],
        report_mode: str,
    ) -> None:
        self.structured = structured
        self.report_symbols = report_symbols
        self.report_mode = report_mode
        self.calls: list[tuple[object, str]] = []

    def run_research(
        self,
        *,
        selection,
        request_text: str,
    ) -> tuple[AppStructuredSnapshot, SupervisorResearchResult]:
        self.calls.append(
            (
                selection,
                request_text,
            )
        )
        return (
            self.structured,
            SupervisorResearchResult(
                state=object(),
                report=SimpleNamespace(
                    symbols=self.report_symbols,
                    mode=self.report_mode,
                ),
            ),
        )


class AppServiceTests(unittest.TestCase):
    def test_run_app_research_uses_validated_selection(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol="MSFT",
            market_window_sessions=60,
            equities=EQUITIES,
        )
        runtime = FakeRuntime(
            structured=AppStructuredSnapshot(
                market_results=(
                    _market_result("AAPL"),
                    _market_result("MSFT"),
                ),
                fundamental_results=(
                    _fundamental_result("AAPL"),
                    _fundamental_result("MSFT"),
                ),
            ),
            report_symbols=("AAPL", "MSFT"),
            report_mode="comparison",
        )

        session = run_app_research(
            selection=selection,
            runtime=runtime,
            equities=EQUITIES,
        )

        self.assertIsInstance(
            session,
            AppResearchSession,
        )
        self.assertEqual(
            session.selection,
            selection,
        )
        self.assertIn(
            "60-trading-session",
            session.request_text,
        )
        self.assertEqual(
            len(runtime.calls),
            1,
        )
        runtime_selection, runtime_request = runtime.calls[0]
        self.assertEqual(
            runtime_selection,
            selection,
        )
        self.assertIn(
            "Compare Apple Inc. (AAPL) and Microsoft Corporation (MSFT).",
            runtime_request,
        )

    def test_structured_symbols_must_match_selection(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol="MSFT",
            market_window_sessions=20,
            equities=EQUITIES,
        )
        runtime = FakeRuntime(
            structured=AppStructuredSnapshot(
                market_results=(
                    _market_result("MSFT"),
                    _market_result("AAPL"),
                ),
                fundamental_results=(
                    _fundamental_result("AAPL"),
                    _fundamental_result("MSFT"),
                ),
            ),
            report_symbols=("AAPL", "MSFT"),
            report_mode="comparison",
        )

        with self.assertRaisesRegex(
            ValueError,
            "market_results symbols",
        ):
            run_app_research(
                selection=selection,
                runtime=runtime,
                equities=EQUITIES,
            )

        self.assertEqual(
            len(runtime.calls),
            1,
        )

    def test_report_symbols_must_match_selection(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol=None,
            market_window_sessions=5,
            equities=EQUITIES,
        )
        runtime = FakeRuntime(
            structured=AppStructuredSnapshot(
                market_results=(
                    _market_result("AAPL"),
                ),
                fundamental_results=(
                    _fundamental_result("AAPL"),
                ),
            ),
            report_symbols=("MSFT",),
            report_mode="single_company",
        )

        with self.assertRaisesRegex(
            ValueError,
            "report symbols",
        ):
            run_app_research(
                selection=selection,
                runtime=runtime,
                equities=EQUITIES,
            )

    def test_report_mode_must_match_selection(self) -> None:
        selection = build_app_research_selection(
            primary_symbol="AAPL",
            comparison_symbol="MSFT",
            market_window_sessions=1,
            equities=EQUITIES,
        )
        runtime = FakeRuntime(
            structured=AppStructuredSnapshot(
                market_results=(
                    _market_result("AAPL"),
                    _market_result("MSFT"),
                ),
                fundamental_results=(
                    _fundamental_result("AAPL"),
                    _fundamental_result("MSFT"),
                ),
            ),
            report_symbols=("AAPL", "MSFT"),
            report_mode="single_company",
        )

        with self.assertRaisesRegex(
            ValueError,
            "report mode",
        ):
            run_app_research(
                selection=selection,
                runtime=runtime,
                equities=EQUITIES,
            )


if __name__ == "__main__":
    unittest.main()
