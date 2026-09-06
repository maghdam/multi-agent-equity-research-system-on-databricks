"""Controlled synthetic execution fixtures for AI research contract failures."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from equity_research.config import Equity
from equity_research.gold_fundamental_metrics import GoldFundamentalMetric
from equity_research.gold_market_metrics import GoldMarketMetric
from equity_research.company_researcher import (
    CompanyResearcherResult,
    ResearchFinding,
    ResearchTopic,
)
from equity_research.market_analyst import (
    MarketAnalystResult,
    validate_market_analyst_output,
)
from equity_research.structured_data_tools import (
    prepare_fundamental_metrics_results,
    prepare_market_metrics_results,
)
from equity_research.supervisor_contracts import SupervisorRequest, SupervisorState
from equity_research.supervisor_report import (
    SupervisorReport,
    build_deterministic_supervisor_report,
)


E4_EQUITIES = {
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

E4_NOW_UTC = datetime(
    2026,
    9,
    6,
    12,
    0,
    tzinfo=timezone.utc,
)


def e4_market_worker(
    *,
    request: SupervisorRequest,
) -> MarketAnalystResult:
    """Exercise real Gold-readiness/analyst contracts with stale MSFT market data."""

    _require_e4_request(
        request
    )

    market_results = prepare_market_metrics_results(
        metrics=(
            _e4_market_metric(
                "AAPL",
                as_of_date=date(
                    2026,
                    9,
                    4,
                ),
            ),
            _e4_market_metric(
                "MSFT",
                as_of_date=date(
                    2026,
                    8,
                    20,
                ),
            ),
        ),
        requested_symbols=request.requested_symbols,
        now_utc=E4_NOW_UTC,
        equities=E4_EQUITIES,
    )
    fundamental_results = prepare_fundamental_metrics_results(
        metrics=(
            _e4_fundamental_metric(
                "AAPL",
                as_of_date=date(
                    2026,
                    7,
                    31,
                ),
            ),
            _e4_fundamental_metric(
                "MSFT",
                as_of_date=date(
                    2026,
                    7,
                    29,
                ),
            ),
        ),
        requested_symbols=request.requested_symbols,
        now_utc=E4_NOW_UTC,
        equities=E4_EQUITIES,
    )

    raw_output = {
        "findings": [
            {
                "finding_id": "market_AAPL",
                "dimension": "market",
                "symbols": ["AAPL"],
                "statement": (
                    "AAPL market metrics remain available in the controlled "
                    "E4 fixture."
                ),
                "metric_references": [
                    {
                        "dataset": "market_metrics",
                        "symbol": "AAPL",
                        "as_of_date": "2026-09-04",
                        "fields": ["return_20d"],
                    }
                ],
            },
            {
                "finding_id": "fundamental_AAPL",
                "dimension": "fundamental",
                "symbols": ["AAPL"],
                "statement": (
                    "AAPL fundamental metrics remain available in the "
                    "controlled E4 fixture."
                ),
                "metric_references": [
                    {
                        "dataset": "fundamental_metrics",
                        "symbol": "AAPL",
                        "as_of_date": "2026-07-31",
                        "fields": ["revenue_ttm"],
                    }
                ],
            },
            {
                "finding_id": "fundamental_MSFT",
                "dimension": "fundamental",
                "symbols": ["MSFT"],
                "statement": (
                    "MSFT fundamental metrics remain available in the "
                    "controlled E4 fixture."
                ),
                "metric_references": [
                    {
                        "dataset": "fundamental_metrics",
                        "symbol": "MSFT",
                        "as_of_date": "2026-07-29",
                        "fields": ["revenue_ttm"],
                    }
                ],
            },
        ]
    }

    return validate_market_analyst_output(
        raw_output,
        requested_symbols=request.requested_symbols,
        market_results=market_results,
        fundamental_results=fundamental_results,
        equities=E4_EQUITIES,
    )


def _e4_market_metric(
    symbol: str,
    *,
    as_of_date: date,
) -> GoldMarketMetric:
    return GoldMarketMetric(
        source_system="alpaca",
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
        window_start_date_60d=date(
            2026,
            6,
            9,
        ),
        observations_available=169,
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
        feed="sip",
        adjustment="split",
        timeframe="1Day",
        currency="USD",
        latest_source_response_id=f"{symbol}-e4-price-response",
        latest_source_fetched_at=datetime(
            2026,
            9,
            5,
            6,
            0,
            tzinfo=timezone.utc,
        ),
        latest_source_ingestion_run_id=f"{symbol}-e4-price-run",
    )


def _e4_fundamental_metric(
    symbol: str,
    *,
    as_of_date: date,
) -> GoldFundamentalMetric:
    return GoldFundamentalMetric(
        source_system="sec",
        symbol=symbol,
        cik=E4_EQUITIES[
            symbol
        ].sec_cik,
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
        latest_fy_end=date(
            2026,
            6,
            30,
        ),
        prior_fy_end=date(
            2025,
            6,
            30,
        ),
        ttm_derivation_method="annual",
        latest_source_response_id=f"{symbol}-e4-facts-response",
        latest_source_fetched_at=datetime(
            2026,
            9,
            5,
            7,
            0,
            tzinfo=timezone.utc,
        ),
        latest_source_ingestion_run_id=f"{symbol}-e4-facts-run",
    )


def e4_company_worker(
    *,
    request: SupervisorRequest,
    topic: ResearchTopic,
) -> CompanyResearcherResult:
    """Return complete controlled narrative coverage for both E4 companies."""

    _require_e4_request(
        request
    )

    if topic not in {
        "recent_developments",
        "principal_risks",
    }:
        raise ValueError(
            f"Unsupported E4 research topic: {topic!r}."
        )

    characterization = (
        "development"
        if topic == "recent_developments"
        else "company_disclosed_risk"
    )
    evidence_ids = {
        ("recent_developments", "AAPL"): "a" * 64,
        ("recent_developments", "MSFT"): "b" * 64,
        ("principal_risks", "AAPL"): "c" * 64,
        ("principal_risks", "MSFT"): "d" * 64,
    }

    return CompanyResearcherResult(
        findings=tuple(
            ResearchFinding(
                finding_id=f"{symbol}:{topic}",
                topic=topic,
                characterization=characterization,
                symbols=(symbol,),
                statement=(
                    f"{symbol} {topic} is supported by controlled E4 "
                    "synthetic evidence."
                ),
                evidence_ids=(
                    evidence_ids[
                        (
                            topic,
                            symbol,
                        )
                    ],
                ),
            )
            for symbol in request.requested_symbols
        ),
        limitations=(),
    )


def e4_report_synthesizer(
    *,
    state: SupervisorState,
) -> SupervisorReport:
    """Use the deterministic validated renderer for the controlled E4 fixture."""

    return build_deterministic_supervisor_report(
        state
    )


def _require_e4_request(
    request: SupervisorRequest,
) -> None:
    if not isinstance(
        request,
        SupervisorRequest,
    ):
        raise TypeError(
            "E4 fixture requires SupervisorRequest."
        )

    if (
        request.mode != "comparison"
        or request.requested_symbols
        != (
            "AAPL",
            "MSFT",
        )
    ):
        raise ValueError(
            "E4 fixture requires comparison scope ('AAPL', 'MSFT')."
        )
