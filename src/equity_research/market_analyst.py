"""Deterministic Market Analyst input/output contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from equity_research.agent_contracts import (
    AgentContractError,
    AgentLimitation,
)
from equity_research.config import Equity
from equity_research.structured_data_tools import (
    FundamentalMetricsToolResult,
    MarketMetricsToolResult,
)
from equity_research.tool_scope import resolve_requested_equities


MetricDataset = Literal["market_metrics", "fundamental_metrics"]
FindingDimension = Literal["market", "fundamental"]

MARKET_ANALYTICAL_FIELDS = frozenset(
    {
        "close",
        "return_1d",
        "return_5d",
        "return_20d",
        "return_60d",
        "annualized_volatility_20d",
        "annualized_volatility_60d",
        "current_drawdown_60d",
        "max_drawdown_60d",
        "sma_20",
        "sma_60",
        "close_vs_sma_20",
        "close_vs_sma_60",
        "sma_20_vs_sma_60",
    }
)

FUNDAMENTAL_ANALYTICAL_FIELDS = frozenset(
    {
        "revenue_ttm",
        "net_income_ttm",
        "net_margin_ttm",
        "assets_latest",
        "revenue_growth_latest_fy",
        "net_income_change_latest_fy",
    }
)


@dataclass(frozen=True)
class MetricReference:
    """Trace one analyst finding back to an exact ready Gold row."""

    dataset: MetricDataset
    symbol: str
    as_of_date: date
    fields: tuple[str, ...]


@dataclass(frozen=True)
class StructuredFinding:
    """One citation-like structured finding from the Market Analyst."""

    finding_id: str
    dimension: FindingDimension
    symbols: tuple[str, ...]
    statement: str
    metric_references: tuple[MetricReference, ...]


@dataclass(frozen=True)
class MarketAnalystResult:
    """Validated worker result plus deterministic structured-data limitations."""

    findings: tuple[StructuredFinding, ...]
    limitations: tuple[AgentLimitation, ...]


def build_market_analyst_context(
    *,
    requested_symbols: Sequence[str],
    market_results: Sequence[MarketMetricsToolResult],
    fundamental_results: Sequence[FundamentalMetricsToolResult],
    equities: Mapping[str, Equity] | None = None,
) -> dict[str, Any]:
    """Build the exact JSON-safe context the Market Analyst may receive."""

    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    symbols = tuple(
        equity.symbol
        for equity in requested
    )

    market_by_symbol = _index_results(
        market_results,
        expected_type=MarketMetricsToolResult,
        requested_symbols=symbols,
        dataset="market_metrics",
    )
    fundamental_by_symbol = _index_results(
        fundamental_results,
        expected_type=FundamentalMetricsToolResult,
        requested_symbols=symbols,
        dataset="fundamental_metrics",
    )

    return {
        "requested_symbols": list(symbols),
        "market_metrics": [
            _market_result_payload(
                market_by_symbol[symbol]
            )
            for symbol in symbols
        ],
        "fundamental_metrics": [
            _fundamental_result_payload(
                fundamental_by_symbol[symbol]
            )
            for symbol in symbols
        ],
    }


def validate_market_analyst_output(
    raw_output: Mapping[str, Any],
    *,
    requested_symbols: Sequence[str],
    market_results: Sequence[MarketMetricsToolResult],
    fundamental_results: Sequence[FundamentalMetricsToolResult],
    equities: Mapping[str, Equity] | None = None,
) -> MarketAnalystResult:
    """Validate model-produced findings against controlled ready Gold rows."""

    if not isinstance(raw_output, Mapping):
        raise AgentContractError(
            "Market Analyst output must be an object."
        )

    unknown = set(raw_output) - {"findings"}

    if unknown:
        raise AgentContractError(
            f"Market Analyst output has unknown fields: {sorted(unknown)}."
        )

    raw_findings = raw_output.get("findings")

    if not isinstance(raw_findings, list):
        raise AgentContractError(
            "Market Analyst findings must be a list."
        )

    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    symbols = tuple(
        equity.symbol
        for equity in requested
    )
    symbol_set = set(symbols)

    market_by_symbol = _index_results(
        market_results,
        expected_type=MarketMetricsToolResult,
        requested_symbols=symbols,
        dataset="market_metrics",
    )
    fundamental_by_symbol = _index_results(
        fundamental_results,
        expected_type=FundamentalMetricsToolResult,
        requested_symbols=symbols,
        dataset="fundamental_metrics",
    )

    findings: list[StructuredFinding] = []
    seen_ids: set[str] = set()

    for raw in raw_findings:
        if not isinstance(raw, Mapping):
            raise AgentContractError(
                "Each Market Analyst finding must be an object."
            )

        unknown_finding_fields = set(raw) - {
            "finding_id",
            "dimension",
            "symbols",
            "statement",
            "metric_references",
        }

        if unknown_finding_fields:
            raise AgentContractError(
                "Market Analyst finding has unknown fields: "
                f"{sorted(unknown_finding_fields)}."
            )

        finding_id = _required_text(
            raw.get("finding_id"),
            "finding_id",
        )

        if finding_id in seen_ids:
            raise AgentContractError(
                f"Duplicate Market Analyst finding_id: {finding_id}."
            )
        seen_ids.add(finding_id)

        dimension = raw.get("dimension")

        if dimension not in {"market", "fundamental"}:
            raise AgentContractError(
                "finding dimension must be 'market' or 'fundamental'."
            )

        finding_symbols = _parse_symbol_tuple(
            raw.get("symbols"),
            requested_symbols=symbol_set,
        )

        statement = _required_text(
            raw.get("statement"),
            "statement",
        )

        raw_refs = raw.get("metric_references")

        if not isinstance(raw_refs, list) or not raw_refs:
            raise AgentContractError(
                "Each Market Analyst finding requires metric_references."
            )

        references = tuple(
            _parse_metric_reference(
                raw_ref,
                dimension=dimension,
                requested_symbols=symbol_set,
                market_by_symbol=market_by_symbol,
                fundamental_by_symbol=fundamental_by_symbol,
            )
            for raw_ref in raw_refs
        )

        referenced_symbols = {
            reference.symbol
            for reference in references
        }

        if referenced_symbols != set(finding_symbols):
            raise AgentContractError(
                "Finding symbols must exactly match referenced metric symbols."
            )

        findings.append(
            StructuredFinding(
                finding_id=finding_id,
                dimension=dimension,
                symbols=finding_symbols,
                statement=statement,
                metric_references=references,
            )
        )

    _validate_ready_coverage(
        findings=findings,
        symbols=symbols,
        market_by_symbol=market_by_symbol,
        fundamental_by_symbol=fundamental_by_symbol,
    )

    limitations = _derive_limitations(
        symbols=symbols,
        market_by_symbol=market_by_symbol,
        fundamental_by_symbol=fundamental_by_symbol,
    )

    return MarketAnalystResult(
        findings=tuple(findings),
        limitations=limitations,
    )


def _parse_metric_reference(
    raw: object,
    *,
    dimension: FindingDimension,
    requested_symbols: set[str],
    market_by_symbol: Mapping[str, MarketMetricsToolResult],
    fundamental_by_symbol: Mapping[str, FundamentalMetricsToolResult],
) -> MetricReference:
    if not isinstance(raw, Mapping):
        raise AgentContractError(
            "metric_references entries must be objects."
        )

    unknown = set(raw) - {
        "dataset",
        "symbol",
        "as_of_date",
        "fields",
    }

    if unknown:
        raise AgentContractError(
            f"Metric reference has unknown fields: {sorted(unknown)}."
        )

    dataset = raw.get("dataset")
    expected_dataset = (
        "market_metrics"
        if dimension == "market"
        else "fundamental_metrics"
    )

    if dataset != expected_dataset:
        raise AgentContractError(
            "Metric reference dataset does not match finding dimension."
        )

    symbol = _required_text(
        raw.get("symbol"),
        "metric reference symbol",
    ).upper()

    if symbol not in requested_symbols:
        raise AgentContractError(
            f"Metric reference symbol is outside request scope: {symbol}."
        )

    result = (
        market_by_symbol[symbol]
        if dataset == "market_metrics"
        else fundamental_by_symbol[symbol]
    )

    if result.status != "ready" or result.metric is None:
        raise AgentContractError(
            f"{dataset} is not ready for {symbol}; it cannot support a finding."
        )

    as_of_date = _parse_iso_date(
        raw.get("as_of_date"),
        "metric reference as_of_date",
    )

    if as_of_date != result.metric.as_of_date:
        raise AgentContractError(
            f"Metric reference as_of_date does not match the ready {dataset} "
            f"row for {symbol}."
        )

    fields = _parse_fields(
        raw.get("fields"),
        allowed=(
            MARKET_ANALYTICAL_FIELDS
            if dataset == "market_metrics"
            else FUNDAMENTAL_ANALYTICAL_FIELDS
        ),
    )

    return MetricReference(
        dataset=dataset,
        symbol=symbol,
        as_of_date=as_of_date,
        fields=fields,
    )


def _validate_ready_coverage(
    *,
    findings: Sequence[StructuredFinding],
    symbols: Sequence[str],
    market_by_symbol: Mapping[str, MarketMetricsToolResult],
    fundamental_by_symbol: Mapping[str, FundamentalMetricsToolResult],
) -> None:
    covered = {
        (
            finding.dimension,
            symbol,
        )
        for finding in findings
        for symbol in finding.symbols
    }

    for symbol in symbols:
        if (
            market_by_symbol[symbol].status == "ready"
            and ("market", symbol) not in covered
        ):
            raise AgentContractError(
                f"Ready market metrics for {symbol} require at least "
                "one market finding."
            )

        if (
            fundamental_by_symbol[symbol].status == "ready"
            and ("fundamental", symbol) not in covered
        ):
            raise AgentContractError(
                f"Ready fundamental metrics for {symbol} require at least "
                "one fundamental finding."
            )


def _derive_limitations(
    *,
    symbols: Sequence[str],
    market_by_symbol: Mapping[str, MarketMetricsToolResult],
    fundamental_by_symbol: Mapping[str, FundamentalMetricsToolResult],
) -> tuple[AgentLimitation, ...]:
    limitations: list[AgentLimitation] = []

    for symbol in symbols:
        for dimension, result in (
            ("market", market_by_symbol[symbol]),
            ("fundamental", fundamental_by_symbol[symbol]),
        ):
            if result.status == "ready":
                continue

            if result.reason_code is None or result.limitation is None:
                raise AgentContractError(
                    f"Unavailable {dimension} result for {symbol} "
                    "must include a reason and limitation."
                )

            limitations.append(
                AgentLimitation(
                    agent="market_analyst",
                    symbol=symbol,
                    dimension=dimension,
                    reason_code=result.reason_code,
                    message=result.limitation,
                )
            )

    return tuple(limitations)


def _market_result_payload(
    result: MarketMetricsToolResult,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": result.symbol,
        "display_name": result.display_name,
        "status": result.status,
        "reason_code": result.reason_code,
        "limitation": result.limitation,
    }

    if result.status == "ready" and result.metric is not None:
        metric = result.metric
        payload["as_of_date"] = metric.as_of_date.isoformat()
        payload["metrics"] = {
            field: _serialize_metric_value(
                getattr(metric, field)
            )
            for field in sorted(MARKET_ANALYTICAL_FIELDS)
        }

    return payload


def _fundamental_result_payload(
    result: FundamentalMetricsToolResult,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol": result.symbol,
        "display_name": result.display_name,
        "status": result.status,
        "reason_code": result.reason_code,
        "limitation": result.limitation,
    }

    if result.status == "ready" and result.metric is not None:
        metric = result.metric
        payload.update(
            {
                "as_of_date": metric.as_of_date.isoformat(),
                "fundamental_period_end": (
                    metric.fundamental_period_end.isoformat()
                ),
                "latest_filing_form": metric.latest_filing_form,
                "ttm_derivation_method": metric.ttm_derivation_method,
                "metrics": {
                    field: _serialize_metric_value(
                        getattr(metric, field)
                    )
                    for field in sorted(
                        FUNDAMENTAL_ANALYTICAL_FIELDS
                    )
                },
            }
        )

    return payload


def _index_results(
    results: Sequence[object],
    *,
    expected_type: type,
    requested_symbols: Sequence[str],
    dataset: str,
) -> dict[str, Any]:
    if isinstance(results, (str, bytes)):
        raise AgentContractError(
            f"{dataset} results must be a sequence."
        )

    indexed: dict[str, Any] = {}

    for result in results:
        if not isinstance(result, expected_type):
            raise AgentContractError(
                f"{dataset} results contain an invalid value."
            )

        if result.symbol in indexed:
            raise AgentContractError(
                f"{dataset} contains duplicate result for {result.symbol}."
            )

        indexed[result.symbol] = result

    expected = set(requested_symbols)
    actual = set(indexed)

    if actual != expected:
        raise AgentContractError(
            f"{dataset} result symbols must exactly match requested symbols."
        )

    return indexed


def _parse_symbol_tuple(
    value: object,
    *,
    requested_symbols: set[str],
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise AgentContractError(
            "finding symbols must be a nonempty list."
        )

    symbols = tuple(
        _required_text(item, "finding symbol").upper()
        for item in value
    )

    if len(set(symbols)) != len(symbols):
        raise AgentContractError(
            "finding symbols must be unique."
        )

    if not set(symbols).issubset(requested_symbols):
        raise AgentContractError(
            "finding symbols must stay within requested scope."
        )

    return symbols


def _parse_fields(
    value: object,
    *,
    allowed: frozenset[str],
) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise AgentContractError(
            "metric reference fields must be a nonempty list."
        )

    fields = tuple(
        _required_text(item, "metric field")
        for item in value
    )

    if len(set(fields)) != len(fields):
        raise AgentContractError(
            "metric reference fields must be unique."
        )

    unsupported = sorted(
        set(fields) - allowed
    )

    if unsupported:
        raise AgentContractError(
            f"Unsupported metric reference fields: {unsupported}."
        )

    return fields


def _parse_iso_date(
    value: object,
    field: str,
) -> date:
    text = _required_text(value, field)

    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise AgentContractError(
            f"{field} must be an ISO date."
        ) from exc


def _serialize_metric_value(
    value: object,
) -> str | int:
    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    raise AgentContractError(
        "Market Analyst context encountered an unsupported metric value."
    )


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentContractError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
