"""Application-facing selection and request contracts.

This module stays independent of Dash so selection/scope behavior can be tested in
credential-free CI and reused by any future UI framework.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from equity_research.config import Equity, load_equities
from equity_research.tool_scope import resolve_requested_equities


SUPPORTED_MARKET_WINDOWS = (1, 5, 20, 60)


@dataclass(frozen=True)
class CompanySelectorOption:
    """One configured equity exposed by a searchable app selector."""

    symbol: str
    label: str


@dataclass(frozen=True)
class AppResearchSelection:
    """Validated app-level research selection."""

    requested_symbols: tuple[str, ...]
    market_window_sessions: int

    @property
    def mode(self) -> str:
        return (
            "single_company"
            if len(self.requested_symbols) == 1
            else "comparison"
        )


def company_selector_options(
    equities: Mapping[str, Equity] | None = None,
) -> tuple[CompanySelectorOption, ...]:
    """Return stable searchable options from the configured equity universe."""

    configured = (
        dict(load_equities())
        if equities is None
        else dict(equities)
    )

    return tuple(
        CompanySelectorOption(
            symbol=equity.symbol,
            label=f"{equity.display_name} ({equity.symbol})",
        )
        for equity in sorted(
            configured.values(),
            key=lambda value: (
                value.display_name.casefold(),
                value.symbol,
            ),
        )
    )


def build_app_research_selection(
    *,
    primary_symbol: str,
    comparison_symbol: str | None,
    market_window_sessions: int,
    equities: Mapping[str, Equity] | None = None,
) -> AppResearchSelection:
    """Validate one app selection against project scope and supported windows."""

    if (
        not isinstance(market_window_sessions, int)
        or isinstance(market_window_sessions, bool)
        or market_window_sessions not in SUPPORTED_MARKET_WINDOWS
    ):
        raise ValueError(
            "market_window_sessions must be one of "
            f"{SUPPORTED_MARKET_WINDOWS}."
        )

    requested = [primary_symbol]

    if isinstance(comparison_symbol, str) and comparison_symbol.strip():
        requested.append(comparison_symbol)

    resolved = resolve_requested_equities(
        requested,
        equities=equities,
    )

    return AppResearchSelection(
        requested_symbols=tuple(
            equity.symbol
            for equity in resolved
        ),
        market_window_sessions=market_window_sessions,
    )


def build_research_request_text(
    selection: AppResearchSelection,
    *,
    equities: Mapping[str, Equity] | None = None,
) -> str:
    """Build deterministic request text for the existing Supervisor boundary."""

    if not isinstance(selection, AppResearchSelection):
        raise TypeError(
            "selection must be AppResearchSelection."
        )

    configured = (
        dict(load_equities())
        if equities is None
        else dict(equities)
    )

    resolved = resolve_requested_equities(
        selection.requested_symbols,
        equities=configured,
    )

    if len(resolved) == 1:
        subject = (
            f"Research {resolved[0].display_name} "
            f"({resolved[0].symbol})."
        )
    else:
        subject = (
            f"Compare {resolved[0].display_name} ({resolved[0].symbol}) "
            f"and {resolved[1].display_name} ({resolved[1].symbol})."
        )

    return (
        f"{subject} Use the {selection.market_window_sessions}-trading-session "
        "market window as the selected market-performance emphasis. Cover "
        "market performance, fundamental performance, recent developments, "
        "and principal risks. Keep conclusions bounded to the available "
        "controlled data and evidence."
    )
