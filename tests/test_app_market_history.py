from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.app_market_history import (  # noqa: E402
    build_price_history_sql_request,
    prepare_market_history_series,
)
from equity_research.config import Equity  # noqa: E402
from equity_research.gold_market_metrics import GoldMarketMetric  # noqa: E402
from equity_research.structured_data_tools import (  # noqa: E402
    ControlledToolDataError,
    MarketMetricsToolResult,
)


NOW = datetime(
    2026,
    9,
    7,
    8,
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
) -> GoldMarketMetric:
    return GoldMarketMetric(
        source_system="alpaca",
        symbol=symbol,
        as_of_date=as_of_date,
        as_of_bar_timestamp=NOW,
        close=Decimal("100"),
        window_start_date_60d=date(2026, 6, 12),
        observations_available=61,
        return_1d=Decimal("0.01"),
        return_5d=Decimal("0.02"),
        return_20d=Decimal("0.03"),
        return_60d=Decimal("0.04"),
        annualized_volatility_20d=Decimal("0.20"),
        annualized_volatility_60d=Decimal("0.25"),
        current_drawdown_60d=Decimal("-0.02"),
        max_drawdown_60d=Decimal("-0.08"),
        sma_20=Decimal("98"),
        sma_60=Decimal("95"),
        close_vs_sma_20=Decimal("0.02"),
        close_vs_sma_60=Decimal("0.05"),
        sma_20_vs_sma_60=Decimal("0.03"),
        feed="sip",
        adjustment="split",
        timeframe="1Day",
        currency="USD",
        latest_source_response_id="response",
        latest_source_fetched_at=NOW,
        latest_source_ingestion_run_id="run",
    )


def _ready_market_result(
    symbol: str,
) -> MarketMetricsToolResult:
    return MarketMetricsToolResult(
        symbol=symbol,
        display_name=EQUITIES[symbol].display_name,
        status="ready",
        reason_code=None,
        limitation=None,
        metric=_market_metric(
            symbol
        ),
    )


def _statement_response(
    rows: list[list[str]],
) -> dict:
    return {
        "status": {
            "state": "SUCCEEDED",
        },
        "manifest": {
            "format": "JSON_ARRAY",
            "schema": {
                "columns": [
                    {"name": "symbol"},
                    {"name": "trading_date"},
                    {"name": "close"},
                    {"name": "currency"},
                ],
            },
            "total_chunk_count": 1,
            "truncated": False,
        },
        "result": {
            "data_array": rows,
            "truncated": False,
        },
    }


class AppMarketHistoryTests(unittest.TestCase):
    def test_query_is_bounded_to_selected_window_and_symbols(self) -> None:
        payload = build_price_history_sql_request(
            warehouse_id="warehouse-1",
            table_full_name="workspace.silver.daily_prices",
            requested_symbols=("AAPL", "MSFT"),
            market_window_sessions=60,
            equities=EQUITIES,
        )

        self.assertEqual(
            payload["row_limit"],
            122,
        )
        self.assertIn(
            "`workspace`.`silver`.`daily_prices`",
            payload["statement"],
        )
        self.assertIn(
            "ROW_NUMBER() OVER",
            payload["statement"],
        )
        self.assertEqual(
            payload["parameters"],
            [
                {
                    "name": "symbol_0",
                    "value": "AAPL",
                    "type": "STRING",
                },
                {
                    "name": "symbol_1",
                    "value": "MSFT",
                    "type": "STRING",
                },
                {
                    "name": "observation_count",
                    "value": "61",
                    "type": "INT",
                },
            ],
        )

    def test_ready_single_series_matches_gold_as_of_date(self) -> None:
        series = prepare_market_history_series(
            response=_statement_response(
                [
                    [
                        "AAPL",
                        "2026-09-03",
                        "100.00",
                        "USD",
                    ],
                    [
                        "AAPL",
                        "2026-09-04",
                        "104.00",
                        "USD",
                    ],
                ]
            ),
            requested_symbols=("AAPL",),
            market_window_sessions=1,
            market_results=(
                _ready_market_result("AAPL"),
            ),
            equities=EQUITIES,
        )

        self.assertEqual(
            len(series),
            1,
        )
        self.assertEqual(
            series[0].status,
            "ready",
        )
        self.assertEqual(
            tuple(
                point.trading_date.isoformat()
                for point in series[0].points
            ),
            (
                "2026-09-03",
                "2026-09-04",
            ),
        )

    def test_comparison_requires_aligned_trading_dates(self) -> None:
        with self.assertRaisesRegex(
            ControlledToolDataError,
            "aligned trading dates",
        ):
            prepare_market_history_series(
                response=_statement_response(
                    [
                        ["AAPL", "2026-09-03", "100", "USD"],
                        ["MSFT", "2026-09-02", "200", "USD"],
                        ["AAPL", "2026-09-04", "101", "USD"],
                        ["MSFT", "2026-09-04", "201", "USD"],
                    ]
                ),
                requested_symbols=("AAPL", "MSFT"),
                market_window_sessions=1,
                market_results=(
                    _ready_market_result("AAPL"),
                    _ready_market_result("MSFT"),
                ),
                equities=EQUITIES,
            )

    def test_unready_gold_suppresses_history_values(self) -> None:
        unavailable = MarketMetricsToolResult(
            symbol="AAPL",
            display_name="Apple Inc.",
            status="unavailable",
            reason_code="stale",
            limitation="Synthetic stale result.",
            metric=_market_metric("AAPL"),
        )

        series = prepare_market_history_series(
            response={},
            requested_symbols=("AAPL",),
            market_window_sessions=60,
            market_results=(unavailable,),
            equities=EQUITIES,
        )

        self.assertEqual(
            series[0].status,
            "unavailable",
        )
        self.assertEqual(
            series[0].points,
            (),
        )


if __name__ == "__main__":
    unittest.main()
