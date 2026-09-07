"""Controlled Silver price-history access for app-only chart rendering."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from equity_research.config import Equity
from equity_research.structured_data_tools import (
    ControlledToolDataError,
    MarketMetricsToolResult,
)
from equity_research.tool_scope import resolve_requested_equities


IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SQL_WAIT_TIMEOUT = "50s"


@dataclass(frozen=True)
class AppPriceHistoryPoint:
    """One validated Silver close used only for application presentation."""

    symbol: str
    trading_date: date
    close: Decimal
    currency: str


@dataclass(frozen=True)
class AppMarketHistorySeries:
    """One comparison-safe application price-history series."""

    symbol: str
    display_name: str
    status: str
    limitation: str | None
    points: tuple[AppPriceHistoryPoint, ...]


def build_price_history_sql_request(
    *,
    warehouse_id: str,
    table_full_name: str,
    requested_symbols: Sequence[str],
    market_window_sessions: int,
    equities: Mapping[str, Equity] | None = None,
) -> dict[str, Any]:
    """Build a bounded parameterized query for the selected app window."""

    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    observations = _required_observation_count(
        market_window_sessions
    )
    table_name = _qualified_table_name(
        table_full_name
    )

    markers: list[str] = []
    parameters: list[dict[str, str]] = []

    for index, equity in enumerate(requested):
        name = f"symbol_{index}"
        markers.append(f":{name}")
        parameters.append(
            {
                "name": name,
                "value": equity.symbol,
                "type": "STRING",
            }
        )

    parameters.append(
        {
            "name": "observation_count",
            "value": str(observations),
            "type": "INT",
        }
    )

    statement = (
        "WITH ranked AS (\n"
        "  SELECT\n"
        "    symbol,\n"
        "    trading_date,\n"
        "    close,\n"
        "    currency,\n"
        "    ROW_NUMBER() OVER (\n"
        "      PARTITION BY symbol\n"
        "      ORDER BY trading_date DESC\n"
        "    ) AS rn\n"
        f"  FROM {table_name}\n"
        f"  WHERE symbol IN ({', '.join(markers)})\n"
        ")\n"
        "SELECT symbol, trading_date, close, currency\n"
        "FROM ranked\n"
        "WHERE rn <= :observation_count\n"
        "ORDER BY trading_date, symbol"
    )

    return {
        "warehouse_id": _required_text(
            warehouse_id,
            "warehouse_id",
        ),
        "statement": statement,
        "parameters": parameters,
        "format": "JSON_ARRAY",
        "disposition": "INLINE",
        "row_limit": observations * len(requested),
        "wait_timeout": SQL_WAIT_TIMEOUT,
        "on_wait_timeout": "CONTINUE",
    }


def prepare_market_history_series(
    *,
    response: Mapping[str, Any],
    requested_symbols: Sequence[str],
    market_window_sessions: int,
    market_results: Sequence[MarketMetricsToolResult],
    equities: Mapping[str, Equity] | None = None,
) -> tuple[AppMarketHistorySeries, ...]:
    """Parse and validate chart history against the ready Gold market snapshot."""

    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    observations = _required_observation_count(
        market_window_sessions
    )

    market_by_symbol = {
        result.symbol: result
        for result in market_results
    }

    if tuple(market_by_symbol) != tuple(
        equity.symbol
        for equity in requested
    ):
        raise ControlledToolDataError(
            "market_results must exactly match requested symbol order."
        )

    unavailable = tuple(
        result
        for result in market_results
        if result.status != "ready" or result.metric is None
    )

    if unavailable:
        limitation = (
            "Price history is unavailable because the controlled Gold market "
            "snapshot is not ready for every selected company."
        )
        return tuple(
            AppMarketHistorySeries(
                symbol=equity.symbol,
                display_name=equity.display_name,
                status="unavailable",
                limitation=limitation,
                points=(),
            )
            for equity in requested
        )

    rows = _statement_rows(
        response
    )
    grouped: dict[str, list[AppPriceHistoryPoint]] = {
        equity.symbol: []
        for equity in requested
    }

    for row in rows:
        symbol = _required_cell(
            row,
            "symbol",
        )

        if symbol not in grouped:
            raise ControlledToolDataError(
                "Price-history response contains an out-of-scope symbol."
            )

        grouped[symbol].append(
            AppPriceHistoryPoint(
                symbol=symbol,
                trading_date=_parse_date_cell(
                    row,
                    "trading_date",
                ),
                close=_parse_positive_decimal_cell(
                    row,
                    "close",
                ),
                currency=_required_cell(
                    row,
                    "currency",
                ),
            )
        )

    expected_dates: tuple[date, ...] | None = None
    series: list[AppMarketHistorySeries] = []

    for equity in requested:
        points = tuple(
            sorted(
                grouped[equity.symbol],
                key=lambda point: point.trading_date,
            )
        )

        if len(points) != observations:
            raise ControlledToolDataError(
                f"{equity.symbol}: price history must contain exactly "
                f"{observations} observations."
            )

        dates = tuple(
            point.trading_date
            for point in points
        )

        if len(set(dates)) != len(dates):
            raise ControlledToolDataError(
                f"{equity.symbol}: price history contains duplicate dates."
            )

        currencies = {
            point.currency
            for point in points
        }

        if currencies != {"USD"}:
            raise ControlledToolDataError(
                f"{equity.symbol}: price history must use USD."
            )

        market_metric = market_by_symbol[
            equity.symbol
        ].metric

        if market_metric is None:
            raise ControlledToolDataError(
                "Ready market result is missing its Gold metric."
            )

        if points[-1].trading_date != market_metric.as_of_date:
            raise ControlledToolDataError(
                f"{equity.symbol}: price history does not end on the "
                "Gold market as_of_date."
            )

        if expected_dates is None:
            expected_dates = dates
        elif dates != expected_dates:
            raise ControlledToolDataError(
                "Comparison price histories do not share aligned trading dates."
            )

        series.append(
            AppMarketHistorySeries(
                symbol=equity.symbol,
                display_name=equity.display_name,
                status="ready",
                limitation=None,
                points=points,
            )
        )

    return tuple(series)


def unavailable_market_history_series(
    *,
    requested_symbols: Sequence[str],
    limitation: str,
    equities: Mapping[str, Equity] | None = None,
) -> tuple[AppMarketHistorySeries, ...]:
    """Return bounded unavailable-series metadata without source values."""

    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )
    text = _required_text(
        limitation,
        "limitation",
    )

    return tuple(
        AppMarketHistorySeries(
            symbol=equity.symbol,
            display_name=equity.display_name,
            status="unavailable",
            limitation=text,
            points=(),
        )
        for equity in requested
    )


def _required_observation_count(
    market_window_sessions: int,
) -> int:
    if (
        isinstance(market_window_sessions, bool)
        or not isinstance(market_window_sessions, int)
        or market_window_sessions not in {1, 5, 20, 60}
    ):
        raise ControlledToolDataError(
            "market_window_sessions must be one of 1, 5, 20, or 60."
        )

    return market_window_sessions + 1


def _qualified_table_name(
    value: str,
) -> str:
    text = _required_text(
        value,
        "table_full_name",
    )
    parts = tuple(
        part.strip()
        for part in text.split(".")
    )

    if (
        len(parts) != 3
        or any(
            not IDENTIFIER_PATTERN.fullmatch(part)
            for part in parts
        )
    ):
        raise ControlledToolDataError(
            "table_full_name must be a valid three-level identifier."
        )

    return ".".join(
        f"`{part}`"
        for part in parts
    )


def _statement_rows(
    response: Mapping[str, Any],
) -> tuple[dict[str, object], ...]:
    if not isinstance(response, Mapping):
        raise ControlledToolDataError(
            "Statement Execution response must be a mapping."
        )

    status = response.get("status")

    if not isinstance(status, Mapping) or status.get("state") != "SUCCEEDED":
        raise ControlledToolDataError(
            "Price-history Statement Execution did not succeed."
        )

    manifest = response.get("manifest")

    if not isinstance(manifest, Mapping):
        raise ControlledToolDataError(
            "Price-history response is missing its manifest."
        )

    schema = manifest.get("schema")

    if not isinstance(schema, Mapping):
        raise ControlledToolDataError(
            "Price-history manifest is missing its schema."
        )

    raw_columns = schema.get("columns")

    if not isinstance(raw_columns, list):
        raise ControlledToolDataError(
            "Price-history schema is missing columns."
        )

    columns = tuple(
        column.get("name")
        for column in raw_columns
        if isinstance(column, Mapping)
    )

    expected = (
        "symbol",
        "trading_date",
        "close",
        "currency",
    )

    if columns != expected:
        raise ControlledToolDataError(
            "Price-history columns do not match the controlled projection."
        )

    result = response.get("result")

    if not isinstance(result, Mapping):
        raise ControlledToolDataError(
            "Price-history response is missing result data."
        )

    if (
        manifest.get("truncated") is True
        or result.get("truncated") is True
        or result.get("next_chunk_index") is not None
        or manifest.get("total_chunk_count") not in {None, 1}
    ):
        raise ControlledToolDataError(
            "Price-history query returned a truncated or multi-chunk result."
        )

    raw_rows = result.get("data_array", [])

    if not isinstance(raw_rows, list):
        raise ControlledToolDataError(
            "Price-history data_array must be a list."
        )

    rows: list[dict[str, object]] = []

    for raw_row in raw_rows:
        if (
            not isinstance(raw_row, list)
            or len(raw_row) != len(expected)
        ):
            raise ControlledToolDataError(
                "Price-history row width does not match its schema."
            )

        rows.append(
            dict(
                zip(
                    expected,
                    raw_row,
                    strict=True,
                )
            )
        )

    return tuple(rows)


def _required_cell(
    row: Mapping[str, object],
    field: str,
) -> str:
    if field not in row:
        raise ControlledToolDataError(
            f"Price-history row is missing {field}."
        )

    return _required_text(
        row[field],
        field,
    )


def _parse_date_cell(
    row: Mapping[str, object],
    field: str,
) -> date:
    text = _required_cell(
        row,
        field,
    )

    try:
        return date.fromisoformat(
            text
        )
    except ValueError as exc:
        raise ControlledToolDataError(
            f"{field} must be an ISO date."
        ) from exc


def _parse_positive_decimal_cell(
    row: Mapping[str, object],
    field: str,
) -> Decimal:
    text = _required_cell(
        row,
        field,
    )

    try:
        value = Decimal(
            text
        )
    except InvalidOperation as exc:
        raise ControlledToolDataError(
            f"{field} must be a decimal value."
        ) from exc

    if not value.is_finite() or value <= 0:
        raise ControlledToolDataError(
            f"{field} must be finite and positive."
        )

    return value


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlledToolDataError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
