"""Offline tests for Gold market-metric calculation."""

import sys
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.gold_market_metrics import (  # noqa: E402
    MarketPriceObservation,
    build_market_metrics_snapshot,
)


START_DATE = date(2026, 1, 2)


def _observation(
    symbol: str,
    index: int,
    *,
    close: Decimal | None = None,
    trading_date: date | None = None,
    source_system: str = "alpaca",
    feed: str = "sip",
) -> MarketPriceObservation:
    current_date = (
        trading_date
        if trading_date is not None
        else START_DATE + timedelta(days=index)
    )

    current_close = (
        close
        if close is not None
        else Decimal("100") + Decimal(index)
    )

    return MarketPriceObservation(
        symbol=symbol,
        bar_timestamp=datetime(
            current_date.year,
            current_date.month,
            current_date.day,
            4,
            0,
            tzinfo=timezone.utc,
        ),
        trading_date=current_date,
        close=current_close,
        source_system=source_system,
        feed=feed,
        adjustment="split",
        timeframe="1Day",
        currency="USD",
        source_response_id=f"{symbol}-response-{index}",
        fetched_at=datetime(
            2026,
            9,
            4,
            10,
            0,
            tzinfo=timezone.utc,
        ),
        ingestion_run_id=f"{symbol}-run-{index}",
    )


def _history(
    symbol: str,
    count: int = 70,
    *,
    base: Decimal = Decimal("100"),
) -> list[MarketPriceObservation]:
    return [
        _observation(
            symbol,
            index,
            close=base + Decimal(index),
        )
        for index in range(count)
    ]


class GoldMarketMetricsTests(unittest.TestCase):
    def test_builds_one_current_metric_per_configured_symbol(self) -> None:
        observations = (
            _history("MSFT", base=Decimal("200"))
            + _history("AAPL")
        )

        metrics = build_market_metrics_snapshot(
            observations=observations,
            configured_symbols=("AAPL", "MSFT"),
        )

        self.assertEqual(
            [metric.symbol for metric in metrics],
            ["AAPL", "MSFT"],
        )
        self.assertEqual(len(metrics), 2)
        self.assertEqual(
            metrics[0].as_of_date,
            metrics[1].as_of_date,
        )

        aapl = metrics[0]

        self.assertEqual(
            aapl.close,
            Decimal("169"),
        )
        self.assertEqual(
            aapl.window_start_date_60d,
            START_DATE + timedelta(days=9),
        )
        self.assertEqual(
            aapl.observations_available,
            70,
        )
        self.assertEqual(
            aapl.return_1d,
            (
                Decimal("169") / Decimal("168")
                - Decimal("1")
            ).quantize(
                Decimal("0.0000000001"),
                rounding=ROUND_HALF_EVEN,
            ),
        )
        self.assertEqual(
            aapl.return_60d,
            (
                Decimal("169") / Decimal("109")
                - Decimal("1")
            ).quantize(
                Decimal("0.0000000001"),
                rounding=ROUND_HALF_EVEN,
            ),
        )
        self.assertEqual(
            aapl.sma_20,
            Decimal("159.5000000000"),
        )
        self.assertEqual(
            aapl.sma_60,
            Decimal("139.5000000000"),
        )
        self.assertEqual(
            aapl.current_drawdown_60d,
            Decimal("0E-10"),
        )
        self.assertEqual(
            aapl.max_drawdown_60d,
            Decimal("0E-10"),
        )
        self.assertEqual(
            aapl.latest_source_response_id,
            "AAPL-response-69",
        )

    def test_requires_at_least_61_closes(self) -> None:
        observations = (
            _history("AAPL", 60)
            + _history(
                "MSFT",
                60,
                base=Decimal("200"),
            )
        )

        with self.assertRaisesRegex(
            ValueError,
            "61 are required",
        ):
            build_market_metrics_snapshot(
                observations=observations,
                configured_symbols=("AAPL", "MSFT"),
            )

    def test_latest_trading_dates_must_match(self) -> None:
        aapl = _history("AAPL", 61)
        msft = _history(
            "MSFT",
            61,
            base=Decimal("200"),
        )

        msft[-1] = _observation(
            "MSFT",
            61,
            close=Decimal("261"),
        )

        with self.assertRaisesRegex(
            ValueError,
            "latest trading date",
        ):
            build_market_metrics_snapshot(
                observations=aapl + msft,
                configured_symbols=("AAPL", "MSFT"),
            )

    def test_final_61_trading_dates_must_be_identical(self) -> None:
        aapl = _history("AAPL", 62)
        msft = _history(
            "MSFT",
            62,
            base=Decimal("200"),
        )

        del msft[30]
        msft.insert(
            0,
            _observation(
                "MSFT",
                -1,
                close=Decimal("199"),
                trading_date=START_DATE - timedelta(days=1),
            ),
        )

        with self.assertRaisesRegex(
            ValueError,
            "61-session",
        ):
            build_market_metrics_snapshot(
                observations=aapl + msft,
                configured_symbols=("AAPL", "MSFT"),
            )

    def test_duplicate_symbol_trading_date_fails(self) -> None:
        aapl = _history("AAPL", 61)
        duplicate = _observation(
            "AAPL",
            60,
            close=Decimal("999"),
        )

        with self.assertRaisesRegex(
            ValueError,
            "duplicate Silver trading date",
        ):
            build_market_metrics_snapshot(
                observations=aapl + [duplicate],
                configured_symbols=("AAPL",),
            )

    def test_wrong_source_settings_fail(self) -> None:
        history = _history("AAPL", 61)

        history[0] = _observation(
            "AAPL",
            0,
            feed="iex",
        )

        with self.assertRaisesRegex(
            ValueError,
            "feed=sip",
        ):
            build_market_metrics_snapshot(
                observations=history,
                configured_symbols=("AAPL",),
            )

    def test_max_drawdown_detects_peak_to_later_trough(self) -> None:
        closes = [
            Decimal("100")
            for _ in range(61)
        ]

        closes[30] = Decimal("200")
        closes[31] = Decimal("150")

        for index in range(32, 60):
            closes[index] = Decimal("160")

        closes[-1] = Decimal("180")

        observations = [
            _observation(
                "AAPL",
                index,
                close=close,
            )
            for index, close in enumerate(closes)
        ]

        metric = build_market_metrics_snapshot(
            observations=observations,
            configured_symbols=("AAPL",),
        )[0]

        self.assertEqual(
            metric.max_drawdown_60d,
            Decimal("-0.2500000000"),
        )
        self.assertEqual(
            metric.current_drawdown_60d,
            Decimal("-0.1000000000"),
        )

    def test_input_order_does_not_change_output(self) -> None:
        observations = (
            _history("AAPL", 70)
            + _history(
                "MSFT",
                70,
                base=Decimal("200"),
            )
        )

        forward = build_market_metrics_snapshot(
            observations=observations,
            configured_symbols=("AAPL", "MSFT"),
        )

        reversed_result = build_market_metrics_snapshot(
            observations=list(reversed(observations)),
            configured_symbols=("MSFT", "AAPL"),
        )

        self.assertEqual(
            forward,
            reversed_result,
        )


if __name__ == "__main__":
    unittest.main()
