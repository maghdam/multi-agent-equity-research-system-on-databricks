"""Offline tests for controlled structured-data tool boundaries."""

import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.config import Equity  # noqa: E402
from equity_research.gold_fundamental_metrics import (  # noqa: E402
    GoldFundamentalMetric,
)
from equity_research.gold_market_metrics import (  # noqa: E402
    GoldMarketMetric,
)
from equity_research.structured_data_tools import (  # noqa: E402
    ControlledToolDataError,
    prepare_fundamental_metrics_results,
    prepare_market_metrics_results,
)
from equity_research.tool_scope import (  # noqa: E402
    ControlledToolRequestError,
    resolve_requested_equities,
)


NOW_UTC = datetime(
    2026,
    9,
    6,
    12,
    0,
    tzinfo=timezone.utc,
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


def _market_metric(
    symbol: str,
    *,
    as_of_date: date = date(2026, 9, 4),
    source_system: str = "alpaca",
    feed: str = "sip",
    observations_available: int = 169,
) -> GoldMarketMetric:
    return GoldMarketMetric(
        source_system=source_system,
        symbol=symbol,
        as_of_date=as_of_date,
        as_of_bar_timestamp=datetime(
            as_of_date.year,
            as_of_date.month,
            as_of_date.day,
            4,
            0,
            tzinfo=timezone.utc,
        ),
        close=Decimal("200.00000000"),
        window_start_date_60d=date(2026, 6, 9),
        observations_available=observations_available,
        return_1d=Decimal("0.0100000000"),
        return_5d=Decimal("0.0200000000"),
        return_20d=Decimal("0.0300000000"),
        return_60d=Decimal("0.0400000000"),
        annualized_volatility_20d=Decimal("0.2000000000"),
        annualized_volatility_60d=Decimal("0.2500000000"),
        current_drawdown_60d=Decimal("-0.0500000000"),
        max_drawdown_60d=Decimal("-0.1000000000"),
        sma_20=Decimal("195.0000000000"),
        sma_60=Decimal("190.0000000000"),
        close_vs_sma_20=Decimal("0.0250000000"),
        close_vs_sma_60=Decimal("0.0500000000"),
        sma_20_vs_sma_60=Decimal("0.0263157895"),
        feed=feed,
        adjustment="split",
        timeframe="1Day",
        currency="USD",
        latest_source_response_id=f"{symbol}-price-response",
        latest_source_fetched_at=datetime(
            2026,
            9,
            5,
            6,
            0,
            tzinfo=timezone.utc,
        ),
        latest_source_ingestion_run_id=f"{symbol}-price-run",
    )


def _fundamental_metric(
    symbol: str,
    *,
    as_of_date: date,
    cik: str | None = None,
    source_system: str = "sec",
    ttm_derivation_method: str = "annual",
) -> GoldFundamentalMetric:
    configured_cik = (
        cik
        if cik is not None
        else EQUITIES[symbol].sec_cik
    )

    return GoldFundamentalMetric(
        source_system=source_system,
        symbol=symbol,
        cik=configured_cik,
        as_of_date=as_of_date,
        fundamental_period_end=as_of_date,
        latest_filing_form="10-K",
        latest_accession_number="0000000000-26-000001",
        revenue_ttm=Decimal("1000000000.00000000"),
        net_income_ttm=Decimal("200000000.00000000"),
        net_margin_ttm=Decimal("0.2000000000"),
        assets_latest=Decimal("1500000000.00000000"),
        revenue_growth_latest_fy=Decimal("0.1000000000"),
        net_income_change_latest_fy=Decimal("10000000.00000000"),
        latest_fy_end=date(2026, 6, 30),
        prior_fy_end=date(2025, 6, 30),
        ttm_derivation_method=ttm_derivation_method,
        latest_source_response_id=f"{symbol}-facts-response",
        latest_source_fetched_at=datetime(
            2026,
            9,
            5,
            7,
            0,
            tzinfo=timezone.utc,
        ),
        latest_source_ingestion_run_id=f"{symbol}-facts-run",
    )


class ControlledToolScopeTests(unittest.TestCase):
    def test_resolves_requested_symbols_case_insensitively_in_order(self) -> None:
        resolved = resolve_requested_equities(
            (" msft ", "aapl"),
            equities=EQUITIES,
        )

        self.assertEqual(
            tuple(equity.symbol for equity in resolved),
            ("MSFT", "AAPL"),
        )

    def test_rejects_unsupported_symbol_with_supported_universe(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolRequestError,
            r"Unsupported symbol\(s\): NVDA.*Supported symbols: AAPL, MSFT",
        ):
            resolve_requested_equities(
                ("AAPL", "NVDA"),
                equities=EQUITIES,
            )

    def test_rejects_duplicate_requested_symbols_after_normalization(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolRequestError,
            "must be unique",
        ):
            resolve_requested_equities(
                ("AAPL", " aapl "),
                equities=EQUITIES,
            )


class ControlledStructuredDataToolTests(unittest.TestCase):
    def test_market_tool_accepts_full_snapshot_for_requested_subset(self) -> None:
        results = prepare_market_metrics_results(
            metrics=(
                _market_metric("AAPL"),
                _market_metric("MSFT"),
            ),
            requested_symbols=("AAPL",),
            now_utc=NOW_UTC,
            equities=EQUITIES,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].symbol, "AAPL")
        self.assertEqual(results[0].status, "ready")
        self.assertIsNone(results[0].limitation)
        self.assertIsNotNone(results[0].metric)

    def test_market_tool_returns_explicit_missing_result(self) -> None:
        results = prepare_market_metrics_results(
            metrics=(_market_metric("AAPL"),),
            requested_symbols=("AAPL", "MSFT"),
            now_utc=NOW_UTC,
            equities=EQUITIES,
        )

        self.assertEqual(results[0].status, "ready")
        self.assertEqual(results[1].status, "unavailable")
        self.assertEqual(results[1].reason_code, "missing")
        self.assertIsNone(results[1].metric)

    def test_market_tool_returns_explicit_stale_result(self) -> None:
        result = prepare_market_metrics_results(
            metrics=(
                _market_metric(
                    "AAPL",
                    as_of_date=date(2026, 8, 20),
                ),
            ),
            requested_symbols=("AAPL",),
            now_utc=NOW_UTC,
            equities=EQUITIES,
        )[0]

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, "stale")
        self.assertIsNotNone(result.metric)
        self.assertIn("readiness window", result.limitation or "")

    def test_market_tool_rejects_future_business_date(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolDataError,
            "in the future",
        ):
            prepare_market_metrics_results(
                metrics=(
                    _market_metric(
                        "AAPL",
                        as_of_date=date(2026, 9, 7),
                    ),
                ),
                requested_symbols=("AAPL",),
                now_utc=NOW_UTC,
                equities=EQUITIES,
            )

    def test_market_tool_rejects_noncomparable_ready_dates(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolDataError,
            "common as_of_date",
        ):
            prepare_market_metrics_results(
                metrics=(
                    _market_metric(
                        "AAPL",
                        as_of_date=date(2026, 9, 4),
                    ),
                    _market_metric(
                        "MSFT",
                        as_of_date=date(2026, 9, 3),
                    ),
                ),
                requested_symbols=("AAPL", "MSFT"),
                now_utc=NOW_UTC,
                equities=EQUITIES,
            )

    def test_market_tool_rejects_invalid_source_contract(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolDataError,
            "feed is not sip",
        ):
            prepare_market_metrics_results(
                metrics=(
                    _market_metric(
                        "AAPL",
                        feed="iex",
                    ),
                ),
                requested_symbols=("AAPL",),
                now_utc=NOW_UTC,
                equities=EQUITIES,
            )

    def test_fundamental_tool_allows_distinct_fresh_filing_dates(self) -> None:
        results = prepare_fundamental_metrics_results(
            metrics=(
                _fundamental_metric(
                    "AAPL",
                    as_of_date=date(2026, 7, 31),
                    ttm_derivation_method=(
                        "annual_plus_ytd_minus_prior_ytd"
                    ),
                ),
                _fundamental_metric(
                    "MSFT",
                    as_of_date=date(2026, 7, 29),
                ),
            ),
            requested_symbols=("AAPL", "MSFT"),
            now_utc=NOW_UTC,
            equities=EQUITIES,
        )

        self.assertEqual(
            tuple(result.status for result in results),
            ("ready", "ready"),
        )
        self.assertNotEqual(
            results[0].metric.as_of_date,  # type: ignore[union-attr]
            results[1].metric.as_of_date,  # type: ignore[union-attr]
        )

    def test_fundamental_tool_returns_explicit_stale_result(self) -> None:
        result = prepare_fundamental_metrics_results(
            metrics=(
                _fundamental_metric(
                    "AAPL",
                    as_of_date=date(2026, 2, 1),
                ),
            ),
            requested_symbols=("AAPL",),
            now_utc=NOW_UTC,
            equities=EQUITIES,
        )[0]

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason_code, "stale")
        self.assertIsNotNone(result.metric)

    def test_fundamental_tool_rejects_cik_mismatch(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolDataError,
            "CIK does not match configuration",
        ):
            prepare_fundamental_metrics_results(
                metrics=(
                    _fundamental_metric(
                        "AAPL",
                        as_of_date=date(2026, 7, 31),
                        cik="0000000001",
                    ),
                ),
                requested_symbols=("AAPL",),
                now_utc=NOW_UTC,
                equities=EQUITIES,
            )

    def test_fundamental_tool_rejects_duplicate_current_rows(self) -> None:
        metric = _fundamental_metric(
            "AAPL",
            as_of_date=date(2026, 7, 31),
        )

        with self.assertRaisesRegex(
            ControlledToolDataError,
            "more than one current row",
        ):
            prepare_fundamental_metrics_results(
                metrics=(metric, metric),
                requested_symbols=("AAPL",),
                now_utc=NOW_UTC,
                equities=EQUITIES,
            )


if __name__ == "__main__":
    unittest.main()
