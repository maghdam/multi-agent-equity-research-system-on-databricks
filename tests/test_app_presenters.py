from __future__ import annotations

import sys
import unittest
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from equity_research.app_contracts import AppResearchSelection  # noqa: E402
from equity_research.app_market_history import (  # noqa: E402
    AppMarketHistorySeries,
    AppPriceHistoryPoint,
)
from equity_research.app_presenters import (  # noqa: E402
    build_app_research_presentation,
)
from equity_research.app_service import (  # noqa: E402
    AppResearchSession,
    AppStructuredSnapshot,
)
from equity_research.gold_fundamental_metrics import (  # noqa: E402
    GoldFundamentalMetric,
)
from equity_research.gold_market_metrics import GoldMarketMetric  # noqa: E402
from equity_research.retrieval_tools import EvidenceRecord  # noqa: E402
from equity_research.structured_data_tools import (  # noqa: E402
    FundamentalMetricsToolResult,
    MarketMetricsToolResult,
)
from equity_research.supervisor_report import (  # noqa: E402
    EvidenceCitation,
    ReportSection,
    SupervisorReport,
)
from equity_research.supervisor_research_graph import (  # noqa: E402
    SupervisorResearchResult,
)


NOW = datetime(
    2026,
    9,
    7,
    8,
    0,
    tzinfo=timezone.utc,
)


def _market_metric() -> GoldMarketMetric:
    return GoldMarketMetric(
        source_system="alpaca",
        symbol="AAPL",
        as_of_date=date(2026, 9, 4),
        as_of_bar_timestamp=NOW,
        close=Decimal("250.00"),
        window_start_date_60d=date(2026, 6, 12),
        observations_available=61,
        return_1d=Decimal("0.01"),
        return_5d=Decimal("0.02"),
        return_20d=Decimal("0.03"),
        return_60d=Decimal("0.125"),
        annualized_volatility_20d=Decimal("0.20"),
        annualized_volatility_60d=Decimal("0.25"),
        current_drawdown_60d=Decimal("-0.04"),
        max_drawdown_60d=Decimal("-0.09"),
        sma_20=Decimal("245.00"),
        sma_60=Decimal("230.00"),
        close_vs_sma_20=Decimal("0.0204081633"),
        close_vs_sma_60=Decimal("0.0869565217"),
        sma_20_vs_sma_60=Decimal("0.0652173913"),
        feed="sip",
        adjustment="split",
        timeframe="1Day",
        currency="USD",
        latest_source_response_id="market-response",
        latest_source_fetched_at=NOW,
        latest_source_ingestion_run_id="market-run",
    )


def _fundamental_metric() -> GoldFundamentalMetric:
    return GoldFundamentalMetric(
        source_system="sec",
        symbol="AAPL",
        cik="0000320193",
        as_of_date=date(2026, 8, 1),
        fundamental_period_end=date(2026, 6, 30),
        latest_filing_form="10-Q",
        latest_accession_number="0000320193-26-000001",
        revenue_ttm=Decimal("400000000000"),
        net_income_ttm=Decimal("100000000000"),
        net_margin_ttm=Decimal("0.25"),
        assets_latest=Decimal("350000000000"),
        revenue_growth_latest_fy=Decimal("0.08"),
        net_income_change_latest_fy=Decimal("18274000000"),
        latest_fy_end=date(2025, 9, 27),
        prior_fy_end=date(2024, 9, 28),
        ttm_derivation_method="annual_plus_ytd_minus_prior_ytd",
        latest_source_response_id="fund-response",
        latest_source_fetched_at=NOW,
        latest_source_ingestion_run_id="fund-run",
    )


def _session() -> AppResearchSession:
    report = SupervisorReport(
        mode="single_company",
        symbols=("AAPL",),
        status="degraded",
        sections=(
            ReportSection(
                section="market_performance",
                status="available",
                text="Market performance text.",
                source_finding_ids=("market_analysis:m1",),
            ),
            ReportSection(
                section="fundamental_performance",
                status="available",
                text="Fundamental performance text.",
                source_finding_ids=("market_analysis:f1",),
            ),
            ReportSection(
                section="recent_developments",
                status="degraded",
                text="Recent developments text.",
                source_finding_ids=("recent_developments:r1",),
            ),
            ReportSection(
                section="principal_risks",
                status="available",
                text="Principal risks text.",
                source_finding_ids=("principal_risks:p1",),
            ),
        ),
        limitations=("Recent developments coverage is incomplete.",),
        evidence=(
            EvidenceCitation(
                evidence_id="news:e1",
                source_finding_ids=("recent_developments:r1",),
            ),
            EvidenceCitation(
                evidence_id="filing:e2",
                source_finding_ids=("principal_risks:p1",),
            ),
        ),
        synthesis_mode="model",
    )

    return AppResearchSession(
        selection=AppResearchSelection(
            requested_symbols=("AAPL",),
            market_window_sessions=60,
        ),
        request_text="Research Apple.",
        structured=AppStructuredSnapshot(
            market_results=(
                MarketMetricsToolResult(
                    symbol="AAPL",
                    display_name="Apple Inc.",
                    status="ready",
                    reason_code=None,
                    limitation=None,
                    metric=_market_metric(),
                ),
            ),
            fundamental_results=(
                FundamentalMetricsToolResult(
                    symbol="AAPL",
                    display_name="Apple Inc.",
                    status="ready",
                    reason_code=None,
                    limitation=None,
                    metric=_fundamental_metric(),
                ),
            ),
            narrative_evidence=(
                EvidenceRecord(
                    evidence_id="news:e1",
                    retrieval_rank=1,
                    chunk_id="a" * 64,
                    document_id="alpaca:news:101",
                    document_version_id="news-version",
                    source_type="news",
                    source_system="alpaca",
                    configured_symbols=("AAPL", "MSFT"),
                    title="Synthetic licensed headline",
                    evidence_date=date(2026, 8, 30),
                    source_url="https://www.benzinga.com/news/example",
                    source_business_id="101",
                    section_code=None,
                    section_title=None,
                    chunk_index=2,
                    text="Synthetic licensed article text.",
                    source_response_id="news-response",
                    source_fetched_at=NOW,
                    source_ingestion_run_id="news-run",
                ),
                EvidenceRecord(
                    evidence_id="filing:e2",
                    retrieval_rank=2,
                    chunk_id="b" * 64,
                    document_id="sec:filing:aapl:item_1a",
                    document_version_id="filing-version",
                    source_type="filing",
                    source_system="sec",
                    configured_symbols=("AAPL",),
                    title="Apple Inc. Form 10-K",
                    evidence_date=date(2025, 10, 31),
                    source_url="https://www.sec.gov/Archives/example",
                    source_business_id="0000320193-25-000079",
                    section_code="item_1a",
                    section_title="Risk Factors",
                    chunk_index=4,
                    text="Synthetic SEC risk-factor text.",
                    source_response_id="filing-response",
                    source_fetched_at=NOW,
                    source_ingestion_run_id="filing-run",
                ),
            ),
        ),
        research=SupervisorResearchResult(
            state=object(),
            report=report,
        ),
    )


class AppPresenterTests(unittest.TestCase):
    def test_presentation_uses_selected_market_window(self) -> None:
        presentation = build_app_research_presentation(
            _session()
        )

        company = presentation.companies[0]
        selected = next(
            metric
            for metric in company.market_metrics
            if metric.label == "60-session return"
        )

        self.assertEqual(
            selected.value,
            "12.50%",
        )
        self.assertEqual(
            company.market_as_of,
            "2026-09-04",
        )
        self.assertEqual(
            company.fundamental_as_of,
            "2026-08-01",
        )

    def test_presentation_preserves_report_status_and_evidence(self) -> None:
        presentation = build_app_research_presentation(
            _session()
        )

        self.assertEqual(
            presentation.report_status,
            "degraded",
        )
        self.assertEqual(
            presentation.synthesis_mode,
            "model",
        )
        self.assertEqual(
            tuple(
                section.title
                for section in presentation.report_sections
            ),
            (
                "Market performance",
                "Fundamental performance",
                "Recent developments",
                "Principal risks",
            ),
        )
        self.assertEqual(
            presentation.limitations,
            ("Recent developments coverage is incomplete.",),
        )
        self.assertEqual(
            tuple(
                item.evidence_id
                for item in presentation.evidence
            ),
            ("news:e1", "filing:e2"),
        )

    def test_evidence_presentation_exposes_safe_metadata_only(self) -> None:
        presentation = build_app_research_presentation(
            _session()
        )
        news, filing = presentation.evidence

        self.assertEqual(
            news.source_label,
            "Alpaca/Benzinga news",
        )
        self.assertEqual(
            news.symbols,
            ("AAPL",),
        )
        self.assertEqual(
            news.evidence_date,
            "2026-08-30",
        )
        self.assertEqual(
            news.source_domain,
            "www.benzinga.com",
        )
        self.assertEqual(
            news.source_business_id,
            "101",
        )
        self.assertIsNone(
            news.section_label
        )
        self.assertEqual(
            news.retrieval_rank,
            1,
        )
        self.assertEqual(
            news.chunk_index,
            2,
        )

        self.assertEqual(
            filing.source_label,
            "SEC filing",
        )
        self.assertEqual(
            filing.section_label,
            "Risk Factors",
        )
        self.assertEqual(
            filing.source_domain,
            "www.sec.gov",
        )

        serialized = repr(
            presentation.evidence
        )
        self.assertNotIn(
            "Synthetic licensed headline",
            serialized,
        )
        self.assertNotIn(
            "Synthetic licensed article text",
            serialized,
        )
        self.assertNotIn(
            "Synthetic SEC risk-factor text",
            serialized,
        )

    def test_unavailable_market_result_does_not_render_stale_values(self) -> None:
        session = _session()
        stale_market = MarketMetricsToolResult(
            symbol="AAPL",
            display_name="Apple Inc.",
            status="unavailable",
            reason_code="stale",
            limitation="AAPL market data is stale.",
            metric=_market_metric(),
        )
        stale_session = AppResearchSession(
            selection=session.selection,
            request_text=session.request_text,
            structured=AppStructuredSnapshot(
                market_results=(stale_market,),
                fundamental_results=(
                    session.structured.fundamental_results[0],
                ),
            ),
            research=session.research,
        )

        presentation = build_app_research_presentation(
            stale_session
        )
        market_metrics = presentation.companies[0].market_metrics

        self.assertEqual(
            len(market_metrics),
            1,
        )
        self.assertEqual(
            market_metrics[0].label,
            "Availability",
        )
        self.assertEqual(
            market_metrics[0].value,
            "AAPL market data is stale.",
        )
        self.assertNotIn(
            "USD 250.00",
            tuple(
                metric.value
                for metric in market_metrics
            ),
        )

    def test_price_history_is_normalized_to_100(self) -> None:
        session = _session()
        history_session = AppResearchSession(
            selection=session.selection,
            request_text=session.request_text,
            structured=AppStructuredSnapshot(
                market_results=session.structured.market_results,
                fundamental_results=session.structured.fundamental_results,
                market_history=(
                    AppMarketHistorySeries(
                        symbol="AAPL",
                        display_name="Apple Inc.",
                        status="ready",
                        limitation=None,
                        points=(
                            AppPriceHistoryPoint(
                                symbol="AAPL",
                                trading_date=date(2026, 9, 3),
                                close=Decimal("200"),
                                currency="USD",
                            ),
                            AppPriceHistoryPoint(
                                symbol="AAPL",
                                trading_date=date(2026, 9, 4),
                                close=Decimal("220"),
                                currency="USD",
                            ),
                        ),
                    ),
                ),
            ),
            research=session.research,
        )

        presentation = build_app_research_presentation(
            history_session
        )

        self.assertEqual(
            tuple(
                point.indexed_close
                for point in presentation.market_history[0].points
            ),
            (100.0, 110.0),
        )

    def test_money_values_are_compact_and_readable(self) -> None:
        presentation = build_app_research_presentation(
            _session()
        )
        company = presentation.companies[0]
        revenue = next(
            metric
            for metric in company.fundamental_metrics
            if metric.label == "Revenue TTM"
        )
        net_income_change = next(
            metric
            for metric in company.fundamental_metrics
            if metric.label == "Latest FY net income change"
        )
        ttm_derivation = next(
            metric
            for metric in company.fundamental_metrics
            if metric.label == "TTM derivation"
        )

        self.assertEqual(
            revenue.value,
            "USD 400.00B",
        )
        self.assertEqual(
            net_income_change.value,
            "USD 18.27B",
        )
        self.assertEqual(
            ttm_derivation.value,
            "Annual + current YTD - prior YTD",
        )


if __name__ == "__main__":
    unittest.main()
