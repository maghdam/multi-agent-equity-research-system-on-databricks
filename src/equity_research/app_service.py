"""Framework-independent application service for research sessions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from equity_research.app_contracts import (
    AppResearchSelection,
    build_research_request_text,
)
from equity_research.config import Equity
from equity_research.structured_data_tools import (
    FundamentalMetricsToolResult,
    MarketMetricsToolResult,
)
from equity_research.supervisor_research_graph import (
    SupervisorResearchResult,
)


@dataclass(frozen=True)
class AppStructuredSnapshot:
    """Controlled structured data loaded for one app selection."""

    market_results: tuple[MarketMetricsToolResult, ...]
    fundamental_results: tuple[FundamentalMetricsToolResult, ...]


@dataclass(frozen=True)
class AppResearchSession:
    """Complete validated application result for one research action."""

    selection: AppResearchSelection
    request_text: str
    structured: AppStructuredSnapshot
    research: SupervisorResearchResult


class AppResearchRuntime(Protocol):
    """Runtime boundary implemented separately for local and Databricks Apps."""

    def load_structured_snapshot(
        self,
        *,
        selection: AppResearchSelection,
    ) -> AppStructuredSnapshot:
        """Return controlled structured data for rendering."""

    def run_supervisor_research(
        self,
        *,
        request_text: str,
        requested_symbols: tuple[str, ...],
    ) -> SupervisorResearchResult:
        """Run the existing validated Supervisor research graph."""


def run_app_research(
    *,
    selection: AppResearchSelection,
    runtime: AppResearchRuntime,
    equities: Mapping[str, Equity] | None = None,
) -> AppResearchSession:
    """Run one application research action through injected backend runtime."""

    if not isinstance(selection, AppResearchSelection):
        raise TypeError(
            "selection must be AppResearchSelection."
        )

    request_text = build_research_request_text(
        selection,
        equities=equities,
    )
    structured = runtime.load_structured_snapshot(
        selection=selection,
    )
    _validate_structured_snapshot(
        selection=selection,
        structured=structured,
    )

    research = runtime.run_supervisor_research(
        request_text=request_text,
        requested_symbols=selection.requested_symbols,
    )
    _validate_research_result(
        selection=selection,
        research=research,
    )

    return AppResearchSession(
        selection=selection,
        request_text=request_text,
        structured=structured,
        research=research,
    )


def _validate_structured_snapshot(
    *,
    selection: AppResearchSelection,
    structured: AppStructuredSnapshot,
) -> None:
    if not isinstance(structured, AppStructuredSnapshot):
        raise TypeError(
            "runtime must return AppStructuredSnapshot."
        )

    expected = selection.requested_symbols

    for name, results in (
        ("market_results", structured.market_results),
        ("fundamental_results", structured.fundamental_results),
    ):
        symbols = tuple(
            result.symbol
            for result in results
        )
        if symbols != expected:
            raise ValueError(
                f"{name} symbols must exactly match the app selection "
                f"{expected}; received {symbols}."
            )


def _validate_research_result(
    *,
    selection: AppResearchSelection,
    research: SupervisorResearchResult,
) -> None:
    if not isinstance(research, SupervisorResearchResult):
        raise TypeError(
            "runtime must return SupervisorResearchResult."
        )

    if research.report.symbols != selection.requested_symbols:
        raise ValueError(
            "Supervisor report symbols must exactly match the app selection."
        )

    if research.report.mode != selection.mode:
        raise ValueError(
            "Supervisor report mode must match the app selection."
        )
