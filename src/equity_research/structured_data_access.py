"""Build controlled Databricks SQL requests for Gold metric tables."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from equity_research.config import Equity
from equity_research.structured_data_tools import ControlledToolDataError
from equity_research.tool_scope import resolve_requested_equities


IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SQL_RESULT_ROW_LIMIT = 10

MARKET_METRIC_PROJECTION = """
  source_system,
  symbol,
  as_of_date,
  unix_millis(as_of_bar_timestamp) AS as_of_bar_timestamp_ms,
  close,
  window_start_date_60d,
  observations_available,
  return_1d,
  return_5d,
  return_20d,
  return_60d,
  annualized_volatility_20d,
  annualized_volatility_60d,
  current_drawdown_60d,
  max_drawdown_60d,
  sma_20,
  sma_60,
  close_vs_sma_20,
  close_vs_sma_60,
  sma_20_vs_sma_60,
  feed,
  adjustment,
  timeframe,
  currency,
  latest_source_response_id,
  unix_millis(latest_source_fetched_at) AS latest_source_fetched_at_ms,
  latest_source_ingestion_run_id
""".strip()

FUNDAMENTAL_METRIC_PROJECTION = """
  source_system,
  symbol,
  cik,
  as_of_date,
  fundamental_period_end,
  latest_filing_form,
  latest_accession_number,
  revenue_ttm,
  net_income_ttm,
  net_margin_ttm,
  assets_latest,
  revenue_growth_latest_fy,
  net_income_change_latest_fy,
  latest_fy_end,
  prior_fy_end,
  ttm_derivation_method,
  latest_source_response_id,
  unix_millis(latest_source_fetched_at) AS latest_source_fetched_at_ms,
  latest_source_ingestion_run_id
""".strip()


def build_market_metrics_sql_request(
    *,
    warehouse_id: str,
    catalog: str,
    gold_schema: str,
    requested_symbols: Sequence[str],
    equities: Mapping[str, Equity] | None = None,
) -> dict[str, Any]:
    """Build one parameterized Statement Execution request for market metrics."""

    return _build_sql_request(
        warehouse_id=warehouse_id,
        catalog=catalog,
        gold_schema=gold_schema,
        table="market_metrics",
        projection=MARKET_METRIC_PROJECTION,
        requested_symbols=requested_symbols,
        equities=equities,
    )


def build_fundamental_metrics_sql_request(
    *,
    warehouse_id: str,
    catalog: str,
    gold_schema: str,
    requested_symbols: Sequence[str],
    equities: Mapping[str, Equity] | None = None,
) -> dict[str, Any]:
    """Build one parameterized Statement Execution request for fundamentals."""

    return _build_sql_request(
        warehouse_id=warehouse_id,
        catalog=catalog,
        gold_schema=gold_schema,
        table="fundamental_metrics",
        projection=FUNDAMENTAL_METRIC_PROJECTION,
        requested_symbols=requested_symbols,
        equities=equities,
    )


def _build_sql_request(
    *,
    warehouse_id: str,
    catalog: str,
    gold_schema: str,
    table: str,
    projection: str,
    requested_symbols: Sequence[str],
    equities: Mapping[str, Equity] | None,
) -> dict[str, Any]:
    requested = resolve_requested_equities(
        requested_symbols,
        equities=equities,
    )

    table_name = _qualified_table_name(
        catalog=catalog,
        schema=gold_schema,
        table=table,
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

    statement = (
        "SELECT\n"
        f"{projection}\n"
        f"FROM {table_name}\n"
        f"WHERE symbol IN ({', '.join(markers)})\n"
        "ORDER BY symbol"
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
        "row_limit": SQL_RESULT_ROW_LIMIT,
    }


def _qualified_table_name(
    *,
    catalog: str,
    schema: str,
    table: str,
) -> str:
    identifiers = (
        _required_identifier(catalog, "catalog"),
        _required_identifier(schema, "gold_schema"),
        _required_identifier(table, "table"),
    )

    return ".".join(
        f"`{identifier}`"
        for identifier in identifiers
    )


def _required_identifier(
    value: object,
    field: str,
) -> str:
    normalized = _required_text(value, field)

    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ControlledToolDataError(
            f"Invalid {field} identifier: {normalized!r}."
        )

    return normalized


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlledToolDataError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
