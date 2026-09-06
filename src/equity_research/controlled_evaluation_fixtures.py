"""Controlled synthetic execution fixtures for AI research contract failures."""

from __future__ import annotations

from datetime import date

from equity_research.agent_contracts import AgentLimitation
from equity_research.company_researcher import (
    CompanyResearcherResult,
    ResearchFinding,
    ResearchTopic,
)
from equity_research.market_analyst import (
    MarketAnalystResult,
    MetricReference,
    StructuredFinding,
)
from equity_research.supervisor_contracts import SupervisorRequest, SupervisorState
from equity_research.supervisor_report import (
    SupervisorReport,
    build_deterministic_supervisor_report,
)


def e4_market_worker(
    *,
    request: SupervisorRequest,
) -> MarketAnalystResult:
    """Return controlled comparison coverage with stale MSFT market data."""

    _require_e4_request(
        request
    )

    return MarketAnalystResult(
        findings=(
            StructuredFinding(
                finding_id="market_AAPL",
                dimension="market",
                symbols=("AAPL",),
                statement=(
                    "AAPL market metrics remain available in the controlled "
                    "E4 fixture."
                ),
                metric_references=(
                    MetricReference(
                        dataset="market_metrics",
                        symbol="AAPL",
                        as_of_date=date(
                            2026,
                            9,
                            4,
                        ),
                        fields=(
                            "return_20d",
                        ),
                    ),
                ),
            ),
            StructuredFinding(
                finding_id="fundamental_AAPL",
                dimension="fundamental",
                symbols=("AAPL",),
                statement=(
                    "AAPL fundamental metrics remain available in the "
                    "controlled E4 fixture."
                ),
                metric_references=(
                    MetricReference(
                        dataset="fundamental_metrics",
                        symbol="AAPL",
                        as_of_date=date(
                            2026,
                            7,
                            31,
                        ),
                        fields=(
                            "revenue_ttm",
                        ),
                    ),
                ),
            ),
            StructuredFinding(
                finding_id="fundamental_MSFT",
                dimension="fundamental",
                symbols=("MSFT",),
                statement=(
                    "MSFT fundamental metrics remain available in the "
                    "controlled E4 fixture."
                ),
                metric_references=(
                    MetricReference(
                        dataset="fundamental_metrics",
                        symbol="MSFT",
                        as_of_date=date(
                            2026,
                            7,
                            29,
                        ),
                        fields=(
                            "revenue_ttm",
                        ),
                    ),
                ),
            ),
        ),
        limitations=(
            AgentLimitation(
                agent="market_analyst",
                symbol="MSFT",
                dimension="market",
                reason_code="stale",
                message=(
                    "MSFT market_metrics is outside the configured "
                    "completed-market readiness window."
                ),
            ),
        ),
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
