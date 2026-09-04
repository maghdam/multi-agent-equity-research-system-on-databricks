"""Offline tests for Gold fundamental-metric calculation."""

import sys
import unittest
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.gold_fundamental_metrics import (  # noqa: E402
    ASSETS_CONCEPT,
    NET_INCOME_CONCEPT,
    REVENUE_CONCEPT,
    FundamentalFactObservation,
    build_fundamental_metrics_snapshot,
)


FETCHED_AT = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)


def _fact(
    symbol: str,
    cik: str,
    concept: str,
    value: str,
    *,
    start: date | None,
    end: date,
    form: str,
    filed: date,
    accession: str,
    response_id: str | None = None,
) -> FundamentalFactObservation:
    return FundamentalFactObservation(
        source_system="sec",
        cik=cik,
        project_symbol=symbol,
        taxonomy="us-gaap",
        concept=concept,
        unit="USD",
        accession_number=accession,
        fact_value=Decimal(value),
        period_start=start,
        period_end=end,
        filing_form=form,
        filing_date=filed,
        source_response_id=response_id or f"{symbol}-response",
        fetched_at=FETCHED_AT,
        ingestion_run_id=f"{symbol}-run",
    )


def _msft_history() -> list[FundamentalFactObservation]:
    symbol = "MSFT"
    cik = "0000789019"
    accession = "0001193125-26-323660"
    filed = date(2026, 7, 29)

    return [
        _fact(
            symbol, cik, REVENUE_CONCEPT, "331839000000",
            start=date(2025, 7, 1), end=date(2026, 6, 30),
            form="10-K", filed=filed, accession=accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "133749000000",
            start=date(2025, 7, 1), end=date(2026, 6, 30),
            form="10-K", filed=filed, accession=accession,
        ),
        _fact(
            symbol, cik, ASSETS_CONCEPT, "758376000000",
            start=None, end=date(2026, 6, 30),
            form="10-K", filed=filed, accession=accession,
        ),
        _fact(
            symbol, cik, REVENUE_CONCEPT, "281724000000",
            start=date(2024, 7, 1), end=date(2025, 6, 30),
            form="10-K", filed=filed, accession=accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "101832000000",
            start=date(2024, 7, 1), end=date(2025, 6, 30),
            form="10-K", filed=filed, accession=accession,
        ),
    ]


def _aapl_history() -> list[FundamentalFactObservation]:
    symbol = "AAPL"
    cik = "0000320193"
    q_accession = "0000320193-26-000020"
    q_filed = date(2026, 7, 31)
    k_accession = "0000320193-25-000079"
    k_filed = date(2025, 10, 31)

    return [
        _fact(
            symbol, cik, ASSETS_CONCEPT, "383266000000",
            start=None, end=date(2026, 6, 27),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, REVENUE_CONCEPT, "109417000000",
            start=date(2026, 3, 29), end=date(2026, 6, 27),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, REVENUE_CONCEPT, "364357000000",
            start=date(2025, 9, 28), end=date(2026, 6, 27),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "29789000000",
            start=date(2026, 3, 29), end=date(2026, 6, 27),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "101464000000",
            start=date(2025, 9, 28), end=date(2026, 6, 27),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, REVENUE_CONCEPT, "94036000000",
            start=date(2025, 3, 30), end=date(2025, 6, 28),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, REVENUE_CONCEPT, "313695000000",
            start=date(2024, 9, 29), end=date(2025, 6, 28),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "23434000000",
            start=date(2025, 3, 30), end=date(2025, 6, 28),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "84544000000",
            start=date(2024, 9, 29), end=date(2025, 6, 28),
            form="10-Q", filed=q_filed, accession=q_accession,
        ),
        _fact(
            symbol, cik, REVENUE_CONCEPT, "416161000000",
            start=date(2024, 9, 29), end=date(2025, 9, 27),
            form="10-K", filed=k_filed, accession=k_accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "112010000000",
            start=date(2024, 9, 29), end=date(2025, 9, 27),
            form="10-K", filed=k_filed, accession=k_accession,
        ),
        _fact(
            symbol, cik, REVENUE_CONCEPT, "391035000000",
            start=date(2023, 10, 1), end=date(2024, 9, 28),
            form="10-K", filed=k_filed, accession=k_accession,
        ),
        _fact(
            symbol, cik, NET_INCOME_CONCEPT, "93736000000",
            start=date(2023, 10, 1), end=date(2024, 9, 28),
            form="10-K", filed=k_filed, accession=k_accession,
        ),
    ]


class GoldFundamentalMetricsTests(unittest.TestCase):
    def test_latest_10k_uses_direct_annual_ttm(self) -> None:
        metric = build_fundamental_metrics_snapshot(
            observations=_msft_history(),
            configured_companies={"MSFT": "0000789019"},
        )[0]

        self.assertEqual(metric.ttm_derivation_method, "annual")
        self.assertEqual(
            metric.revenue_ttm, Decimal("331839000000.00000000")
        )
        self.assertEqual(
            metric.net_income_ttm, Decimal("133749000000.00000000")
        )
        self.assertEqual(metric.net_margin_ttm, Decimal("0.4030538906"))
        self.assertEqual(
            metric.assets_latest, Decimal("758376000000.00000000")
        )
        self.assertEqual(
            metric.revenue_growth_latest_fy, Decimal("0.1778868680")
        )
        self.assertEqual(
            metric.net_income_change_latest_fy,
            Decimal("31917000000.00000000"),
        )
        self.assertEqual(metric.latest_fy_end, date(2026, 6, 30))
        self.assertEqual(metric.prior_fy_end, date(2025, 6, 30))

    def test_latest_10q_builds_aapl_style_ttm_bridge(self) -> None:
        metric = build_fundamental_metrics_snapshot(
            observations=_aapl_history(),
            configured_companies={"AAPL": "0000320193"},
        )[0]

        self.assertEqual(
            metric.ttm_derivation_method,
            "annual_plus_ytd_minus_prior_ytd",
        )
        self.assertEqual(metric.as_of_date, date(2026, 7, 31))
        self.assertEqual(
            metric.fundamental_period_end, date(2026, 6, 27)
        )
        self.assertEqual(
            metric.revenue_ttm, Decimal("466823000000.00000000")
        )
        self.assertEqual(
            metric.net_income_ttm, Decimal("128930000000.00000000")
        )
        self.assertEqual(metric.net_margin_ttm, Decimal("0.2761860491"))
        self.assertEqual(
            metric.assets_latest, Decimal("383266000000.00000000")
        )
        self.assertEqual(
            metric.revenue_growth_latest_fy, Decimal("0.0642551178")
        )
        self.assertEqual(
            metric.net_income_change_latest_fy,
            Decimal("18274000000.00000000"),
        )

    def test_missing_prior_ytd_fails(self) -> None:
        rows = [
            row
            for row in _aapl_history()
            if not (
                row.concept == REVENUE_CONCEPT
                and row.period_end == date(2025, 6, 28)
                and row.period_start == date(2024, 9, 29)
            )
        ]

        with self.assertRaisesRegex(ValueError, "prior-year comparable YTD"):
            build_fundamental_metrics_snapshot(
                observations=rows,
                configured_companies={"AAPL": "0000320193"},
            )

    def test_mismatched_current_ytd_periods_fail(self) -> None:
        rows = _aapl_history()
        target = next(
            row
            for row in rows
            if row.concept == NET_INCOME_CONCEPT
            and row.period_start == date(2025, 9, 28)
            and row.period_end == date(2026, 6, 27)
        )
        rows[rows.index(target)] = replace(
            target,
            period_start=date(2025, 9, 29),
        )

        with self.assertRaisesRegex(ValueError, "current YTD.*identical"):
            build_fundamental_metrics_snapshot(
                observations=rows,
                configured_companies={"AAPL": "0000320193"},
            )

    def test_missing_current_assets_fails(self) -> None:
        rows = [
            row for row in _aapl_history()
            if row.concept != ASSETS_CONCEPT
        ]

        with self.assertRaisesRegex(ValueError, "current assets"):
            build_fundamental_metrics_snapshot(
                observations=rows,
                configured_companies={"AAPL": "0000320193"},
            )

    def test_ambiguous_latest_filing_fails(self) -> None:
        rows = _aapl_history()
        rows.append(
            _fact(
                "AAPL",
                "0000320193",
                ASSETS_CONCEPT,
                "383266000000",
                start=None,
                end=date(2026, 6, 27),
                form="10-Q",
                filed=date(2026, 7, 31),
                accession="0000320193-26-000021",
            )
        )

        with self.assertRaisesRegex(ValueError, "ambiguous"):
            build_fundamental_metrics_snapshot(
                observations=rows,
                configured_companies={"AAPL": "0000320193"},
            )

    def test_requires_two_comparable_annual_periods(self) -> None:
        rows = [
            row for row in _msft_history()
            if row.period_end != date(2025, 6, 30)
        ]

        with self.assertRaisesRegex(
            ValueError, "two comparable full-year"
        ):
            build_fundamental_metrics_snapshot(
                observations=rows,
                configured_companies={"MSFT": "0000789019"},
            )

    def test_mismatched_annual_revenue_income_period_fails(self) -> None:
        rows = _msft_history()
        target = next(
            row
            for row in rows
            if row.concept == NET_INCOME_CONCEPT
            and row.period_end == date(2026, 6, 30)
        )
        rows[rows.index(target)] = replace(
            target,
            period_start=date(2025, 7, 2),
        )

        with self.assertRaisesRegex(ValueError, "current 10-K.*identical"):
            build_fundamental_metrics_snapshot(
                observations=rows,
                configured_companies={"MSFT": "0000789019"},
            )

    def test_input_and_configuration_order_do_not_change_output(self) -> None:
        observations = _aapl_history() + _msft_history()

        forward = build_fundamental_metrics_snapshot(
            observations=observations,
            configured_companies={
                "AAPL": "0000320193",
                "MSFT": "0000789019",
            },
        )
        reversed_result = build_fundamental_metrics_snapshot(
            observations=list(reversed(observations)),
            configured_companies={
                "MSFT": "0000789019",
                "AAPL": "0000320193",
            },
        )

        self.assertEqual(forward, reversed_result)


if __name__ == "__main__":
    unittest.main()
