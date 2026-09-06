"""Pure controlled-tool boundary for validated Gold metric rows."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from equity_research.config import Equity, load_equities
from equity_research.gold_fundamental_metrics import GoldFundamentalMetric
from equity_research.gold_market_metrics import GoldMarketMetric
from equity_research.tool_scope import resolve_requested_equities


NEW_YORK_TIMEZONE = ZoneInfo("America/New_York")
MAX_COMPLETED_MARKET_DATE_LAG_DAYS = 4
MAX_FUNDAMENTAL_AS_OF_AGE_DAYS = 180
MIN_MARKET_OBSERVATIONS = 61

ToolStatus = Literal["ready", "unavailable"]
ToolReasonCode = Literal["missing", "stale"]


class ControlledToolDataError(RuntimeError):
    """Raised when controlled source data violates the expected contract."""


@dataclass(frozen=True)
class MarketMetricsToolResult:
    """One requested company's controlled market-metrics result."""

    symbol: str
    display_name: str
    status: ToolStatus
    reason_code: ToolReasonCode | None
    limitation: str | None
    metric: GoldMarketMetric | None


@dataclass(frozen=True)
class FundamentalMetricsToolResult:
    """One requested company's controlled fundamental-metrics result."""

    symbol: str
    display_name: str
    status: ToolStatus
    reason_code: ToolReasonCode | None
    limitation: str | None
    metric: GoldFundamentalMetric | None


def prepare_market_metrics_results(
    *,
    metrics: Sequence[GoldMarketMetric],
    requested_symbols: Sequence[str],
    now_utc: datetime,
    equities: Mapping[str, Equity] | None = None,
) -> tuple[MarketMetricsToolResult, ...]:
    """Select and readiness-check current Gold market metrics."""

    configured = (
        dict(load_equities())
        if equities is None
        else dict(equities)
    )
    requested = resolve_requested_equities(
        requested_symbols,
        equities=configured,
    )
    now = _require_aware_utc(now_utc)
    by_symbol = _index_market_metrics(
        metrics,
        configured_symbols=set(configured),
    )

    results: list[MarketMetricsToolResult] = []

    for equity in requested:
        metric = by_symbol.get(equity.symbol)

        if metric is None:
            results.append(
                MarketMetricsToolResult(
                    symbol=equity.symbol,
                    display_name=equity.display_name,
                    status="unavailable",
                    reason_code="missing",
                    limitation=(
                        "No current Gold market_metrics row is "
                        f"available for {equity.symbol}."
                    ),
                    metric=None,
                )
            )
            continue

        _validate_market_metric(
            metric,
            equity=equity,
        )

        market_date = now.astimezone(
            NEW_YORK_TIMEZONE
        ).date()
        lag_days = (
            market_date
            - metric.as_of_date
        ).days

        if lag_days < 0:
            raise ControlledToolDataError(
                f"{equity.symbol}: market_metrics as_of_date "
                "is in the future."
            )

        if not (
            1
            <= lag_days
            <= MAX_COMPLETED_MARKET_DATE_LAG_DAYS
        ):
            results.append(
                MarketMetricsToolResult(
                    symbol=equity.symbol,
                    display_name=equity.display_name,
                    status="unavailable",
                    reason_code="stale",
                    limitation=(
                        f"{equity.symbol}: market_metrics "
                        f"as_of_date={metric.as_of_date} is "
                        "outside the configured completed-market "
                        "readiness window."
                    ),
                    metric=metric,
                )
            )
            continue

        results.append(
            MarketMetricsToolResult(
                symbol=equity.symbol,
                display_name=equity.display_name,
                status="ready",
                reason_code=None,
                limitation=None,
                metric=metric,
            )
        )

    ready_market_dates = {
        result.metric.as_of_date
        for result in results
        if (
            result.status == "ready"
            and result.metric is not None
        )
    }

    if len(ready_market_dates) > 1:
        raise ControlledToolDataError(
            "Ready market_metrics rows do not share one common as_of_date."
        )

    return tuple(results)


def prepare_fundamental_metrics_results(
    *,
    metrics: Sequence[GoldFundamentalMetric],
    requested_symbols: Sequence[str],
    now_utc: datetime,
    equities: Mapping[str, Equity] | None = None,
) -> tuple[FundamentalMetricsToolResult, ...]:
    """Select and readiness-check current Gold fundamental metrics."""

    configured = (
        dict(load_equities())
        if equities is None
        else dict(equities)
    )
    requested = resolve_requested_equities(
        requested_symbols,
        equities=configured,
    )
    now = _require_aware_utc(now_utc)
    by_symbol = _index_fundamental_metrics(
        metrics,
        configured_symbols=set(configured),
    )

    results: list[FundamentalMetricsToolResult] = []

    for equity in requested:
        metric = by_symbol.get(equity.symbol)

        if metric is None:
            results.append(
                FundamentalMetricsToolResult(
                    symbol=equity.symbol,
                    display_name=equity.display_name,
                    status="unavailable",
                    reason_code="missing",
                    limitation=(
                        "No current Gold fundamental_metrics row is "
                        f"available for {equity.symbol}."
                    ),
                    metric=None,
                )
            )
            continue

        _validate_fundamental_metric(
            metric,
            equity=equity,
        )

        age_days = (
            now.date()
            - metric.as_of_date
        ).days

        if age_days < 0:
            raise ControlledToolDataError(
                f"{equity.symbol}: fundamental_metrics as_of_date "
                "is in the future."
            )

        if age_days > MAX_FUNDAMENTAL_AS_OF_AGE_DAYS:
            results.append(
                FundamentalMetricsToolResult(
                    symbol=equity.symbol,
                    display_name=equity.display_name,
                    status="unavailable",
                    reason_code="stale",
                    limitation=(
                        f"{equity.symbol}: fundamental_metrics "
                        f"as_of_date={metric.as_of_date} is "
                        "outside the configured 180-day "
                        "readiness window."
                    ),
                    metric=metric,
                )
            )
            continue

        results.append(
            FundamentalMetricsToolResult(
                symbol=equity.symbol,
                display_name=equity.display_name,
                status="ready",
                reason_code=None,
                limitation=None,
                metric=metric,
            )
        )

    return tuple(results)


def _index_market_metrics(
    metrics: Sequence[GoldMarketMetric],
    *,
    configured_symbols: set[str],
) -> dict[str, GoldMarketMetric]:
    if isinstance(metrics, (str, bytes)):
        raise ControlledToolDataError(
            "metrics must be a sequence of GoldMarketMetric values."
        )

    indexed: dict[str, GoldMarketMetric] = {}

    for metric in metrics:
        if not isinstance(metric, GoldMarketMetric):
            raise ControlledToolDataError(
                "metrics must contain GoldMarketMetric values."
            )

        if metric.symbol not in configured_symbols:
            raise ControlledToolDataError(
                "market_metrics contains an out-of-scope symbol: "
                f"{metric.symbol!r}."
            )

        if metric.symbol in indexed:
            raise ControlledToolDataError(
                "market_metrics contains more than one current row "
                f"for {metric.symbol}."
            )

        indexed[metric.symbol] = metric

    return indexed


def _index_fundamental_metrics(
    metrics: Sequence[GoldFundamentalMetric],
    *,
    configured_symbols: set[str],
) -> dict[str, GoldFundamentalMetric]:
    if isinstance(metrics, (str, bytes)):
        raise ControlledToolDataError(
            "metrics must be a sequence of GoldFundamentalMetric values."
        )

    indexed: dict[str, GoldFundamentalMetric] = {}

    for metric in metrics:
        if not isinstance(metric, GoldFundamentalMetric):
            raise ControlledToolDataError(
                "metrics must contain GoldFundamentalMetric values."
            )

        if metric.symbol not in configured_symbols:
            raise ControlledToolDataError(
                "fundamental_metrics contains an out-of-scope symbol: "
                f"{metric.symbol!r}."
            )

        if metric.symbol in indexed:
            raise ControlledToolDataError(
                "fundamental_metrics contains more than one current row "
                f"for {metric.symbol}."
            )

        indexed[metric.symbol] = metric

    return indexed


def _validate_market_metric(
    metric: GoldMarketMetric,
    *,
    equity: Equity,
) -> None:
    if metric.symbol != equity.symbol:
        raise ControlledToolDataError(
            "market_metrics symbol does not match the requested equity."
        )

    if metric.source_system != "alpaca":
        raise ControlledToolDataError(
            f"{equity.symbol}: market_metrics source_system is not alpaca."
        )

    if metric.currency != "USD":
        raise ControlledToolDataError(
            f"{equity.symbol}: market_metrics currency is not USD."
        )

    if metric.observations_available < MIN_MARKET_OBSERVATIONS:
        raise ControlledToolDataError(
            f"{equity.symbol}: market_metrics has insufficient "
            "price observations."
        )


def _validate_fundamental_metric(
    metric: GoldFundamentalMetric,
    *,
    equity: Equity,
) -> None:
    if metric.symbol != equity.symbol:
        raise ControlledToolDataError(
            "fundamental_metrics symbol does not match the requested equity."
        )

    if metric.cik != equity.sec_cik:
        raise ControlledToolDataError(
            f"{equity.symbol}: fundamental_metrics CIK does not "
            "match configuration."
        )

    if metric.source_system != "sec":
        raise ControlledToolDataError(
            f"{equity.symbol}: fundamental_metrics source_system is not sec."
        )

    if metric.latest_filing_form not in {"10-K", "10-Q"}:
        raise ControlledToolDataError(
            f"{equity.symbol}: fundamental_metrics filing form is "
            "outside the supported scope."
        )

    if metric.fundamental_period_end > metric.as_of_date:
        raise ControlledToolDataError(
            f"{equity.symbol}: fundamental period ends after as_of_date."
        )


def _require_aware_utc(
    value: datetime,
) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ControlledToolDataError(
            "now_utc must be a timezone-aware datetime."
        )

    return value.astimezone(timezone.utc)
