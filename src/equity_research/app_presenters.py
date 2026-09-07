"""Presentation-safe DTOs for the Databricks equity-research app."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from equity_research.app_service import AppResearchSession


@dataclass(frozen=True)
class PresentationMetric:
    """One display metric with explicit label/value/status."""

    label: str
    value: str
    status: str = "ready"


@dataclass(frozen=True)
class PresentationCompany:
    """Presentation data for one selected company."""

    symbol: str
    display_name: str
    market_status: str
    market_as_of: str | None
    market_metrics: tuple[PresentationMetric, ...]
    fundamental_status: str
    fundamental_as_of: str | None
    fundamental_metrics: tuple[PresentationMetric, ...]


@dataclass(frozen=True)
class PresentationReportSection:
    """One validated report section prepared for rendering."""

    section: str
    title: str
    status: str
    text: str
    source_finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class PresentationEvidence:
    """One validated citation reference prepared for rendering."""

    evidence_id: str
    source_finding_ids: tuple[str, ...]


@dataclass(frozen=True)
class AppResearchPresentation:
    """Complete JSON-safe presentation contract for one research session."""

    mode: str
    symbols: tuple[str, ...]
    market_window_sessions: int
    report_status: str
    synthesis_mode: str
    companies: tuple[PresentationCompany, ...]
    report_sections: tuple[PresentationReportSection, ...]
    limitations: tuple[str, ...]
    evidence: tuple[PresentationEvidence, ...]


SECTION_TITLES = {
    "market_performance": "Market performance",
    "fundamental_performance": "Fundamental performance",
    "recent_developments": "Recent developments",
    "principal_risks": "Principal risks",
    "comparative_assessment": "Comparative assessment",
}

WINDOW_RETURN_FIELDS = {
    1: "return_1d",
    5: "return_5d",
    20: "return_20d",
    60: "return_60d",
}


def build_app_research_presentation(
    session: AppResearchSession,
) -> AppResearchPresentation:
    """Convert one validated app session into presentation-only DTOs."""

    if not isinstance(session, AppResearchSession):
        raise TypeError(
            "session must be AppResearchSession."
        )

    market_by_symbol = {
        result.symbol: result
        for result in session.structured.market_results
    }
    fundamentals_by_symbol = {
        result.symbol: result
        for result in session.structured.fundamental_results
    }

    companies = tuple(
        _company_presentation(
            symbol=symbol,
            market_result=market_by_symbol[symbol],
            fundamental_result=fundamentals_by_symbol[symbol],
            market_window_sessions=(
                session.selection.market_window_sessions
            ),
        )
        for symbol in session.selection.requested_symbols
    )

    report = session.research.report

    return AppResearchPresentation(
        mode=report.mode,
        symbols=report.symbols,
        market_window_sessions=(
            session.selection.market_window_sessions
        ),
        report_status=report.status,
        synthesis_mode=report.synthesis_mode,
        companies=companies,
        report_sections=tuple(
            PresentationReportSection(
                section=section.section,
                title=SECTION_TITLES[section.section],
                status=section.status,
                text=section.text,
                source_finding_ids=section.source_finding_ids,
            )
            for section in report.sections
        ),
        limitations=report.limitations,
        evidence=tuple(
            PresentationEvidence(
                evidence_id=item.evidence_id,
                source_finding_ids=item.source_finding_ids,
            )
            for item in report.evidence
        ),
    )


def _company_presentation(
    *,
    symbol: str,
    market_result,
    fundamental_result,
    market_window_sessions: int,
) -> PresentationCompany:
    if market_result.symbol != symbol:
        raise ValueError(
            "market result symbol does not match presentation symbol."
        )

    if fundamental_result.symbol != symbol:
        raise ValueError(
            "fundamental result symbol does not match presentation symbol."
        )

    market_metric = market_result.metric
    fundamental_metric = fundamental_result.metric

    return PresentationCompany(
        symbol=symbol,
        display_name=market_result.display_name,
        market_status=market_result.status,
        market_as_of=(
            market_metric.as_of_date.isoformat()
            if market_metric is not None
            else None
        ),
        market_metrics=_market_metrics(
            market_result=market_result,
            market_window_sessions=market_window_sessions,
        ),
        fundamental_status=fundamental_result.status,
        fundamental_as_of=(
            fundamental_metric.as_of_date.isoformat()
            if fundamental_metric is not None
            else None
        ),
        fundamental_metrics=_fundamental_metrics(
            fundamental_result=fundamental_result,
        ),
    )


def _market_metrics(
    *,
    market_result,
    market_window_sessions: int,
) -> tuple[PresentationMetric, ...]:
    metric = market_result.metric

    if market_result.status != "ready" or metric is None:
        return (
            PresentationMetric(
                label="Availability",
                value=market_result.limitation or "Unavailable",
                status="unavailable",
            ),
        )

    selected_field = WINDOW_RETURN_FIELDS[
        market_window_sessions
    ]
    selected_return = getattr(
        metric,
        selected_field,
    )

    values = (
        PresentationMetric(
            label="Close",
            value=_money(metric.close, metric.currency),
            status=market_result.status,
        ),
        PresentationMetric(
            label=f"{market_window_sessions}-session return",
            value=_percentage(selected_return),
            status=market_result.status,
        ),
        PresentationMetric(
            label="1-session return",
            value=_percentage(metric.return_1d),
            status=market_result.status,
        ),
        PresentationMetric(
            label="5-session return",
            value=_percentage(metric.return_5d),
            status=market_result.status,
        ),
        PresentationMetric(
            label="20-session return",
            value=_percentage(metric.return_20d),
            status=market_result.status,
        ),
        PresentationMetric(
            label="60-session return",
            value=_percentage(metric.return_60d),
            status=market_result.status,
        ),
        PresentationMetric(
            label="20-session annualized volatility",
            value=_percentage(
                metric.annualized_volatility_20d
            ),
            status=market_result.status,
        ),
        PresentationMetric(
            label="60-session annualized volatility",
            value=_percentage(
                metric.annualized_volatility_60d
            ),
            status=market_result.status,
        ),
        PresentationMetric(
            label="Current 60-session drawdown",
            value=_percentage(
                metric.current_drawdown_60d
            ),
            status=market_result.status,
        ),
        PresentationMetric(
            label="Maximum 60-session drawdown",
            value=_percentage(
                metric.max_drawdown_60d
            ),
            status=market_result.status,
        ),
        PresentationMetric(
            label="SMA 20",
            value=_money(metric.sma_20, metric.currency),
            status=market_result.status,
        ),
        PresentationMetric(
            label="SMA 60",
            value=_money(metric.sma_60, metric.currency),
            status=market_result.status,
        ),
    )

    if market_result.limitation:
        return (
            *values,
            PresentationMetric(
                label="Market limitation",
                value=market_result.limitation,
                status="unavailable",
            ),
        )

    return values


def _fundamental_metrics(
    *,
    fundamental_result,
) -> tuple[PresentationMetric, ...]:
    metric = fundamental_result.metric

    if fundamental_result.status != "ready" or metric is None:
        return (
            PresentationMetric(
                label="Availability",
                value=fundamental_result.limitation or "Unavailable",
                status="unavailable",
            ),
        )

    values = (
        PresentationMetric(
            label="Revenue TTM",
            value=_compact_money(metric.revenue_ttm),
            status=fundamental_result.status,
        ),
        PresentationMetric(
            label="Net income TTM",
            value=_compact_money(metric.net_income_ttm),
            status=fundamental_result.status,
        ),
        PresentationMetric(
            label="Net margin TTM",
            value=_percentage(metric.net_margin_ttm),
            status=fundamental_result.status,
        ),
        PresentationMetric(
            label="Assets",
            value=_compact_money(metric.assets_latest),
            status=fundamental_result.status,
        ),
        PresentationMetric(
            label="Latest FY revenue growth",
            value=_percentage(
                metric.revenue_growth_latest_fy
            ),
            status=fundamental_result.status,
        ),
        PresentationMetric(
            label="Latest FY net income change",
            value=_compact_money(
                metric.net_income_change_latest_fy
            ),
            status=fundamental_result.status,
        ),
        PresentationMetric(
            label="Latest filing",
            value=(
                f"{metric.latest_filing_form} · "
                f"{metric.fundamental_period_end.isoformat()}"
            ),
            status=fundamental_result.status,
        ),
        PresentationMetric(
            label="TTM derivation",
            value=metric.ttm_derivation_method,
            status=fundamental_result.status,
        ),
    )

    if fundamental_result.limitation:
        return (
            *values,
            PresentationMetric(
                label="Fundamental limitation",
                value=fundamental_result.limitation,
                status="unavailable",
            ),
        )

    return values


def _percentage(
    value: Decimal,
) -> str:
    percentage = value * Decimal("100")
    return f"{percentage.quantize(Decimal('0.01'))}%"


def _money(
    value: Decimal,
    currency: str,
) -> str:
    return (
        f"{currency} "
        f"{value.quantize(Decimal('0.01')):,.2f}"
    )


def _compact_money(
    value: Decimal,
) -> str:
    absolute = abs(value)

    for threshold, suffix in (
        (Decimal("1000000000000"), "T"),
        (Decimal("1000000000"), "B"),
        (Decimal("1000000"), "M"),
    ):
        if absolute >= threshold:
            scaled = value / threshold
            return (
                f"USD {scaled.quantize(Decimal('0.01')):,.2f}{suffix}"
            )

    return f"USD {value.quantize(Decimal('0.01')):,.2f}"
