"""Controlled Databricks SQL requests and Gold-result parsing."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from equity_research.config import Equity
from equity_research.gold_fundamental_metrics import GoldFundamentalMetric
from equity_research.gold_market_metrics import GoldMarketMetric
from equity_research.structured_data_tools import ControlledToolDataError
from equity_research.tool_scope import resolve_requested_equities


IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
SQL_RESULT_ROW_LIMIT = 10
SQL_WAIT_TIMEOUT = "50s"

MARKET_COLUMNS = (
    "source_system",
    "symbol",
    "as_of_date",
    "as_of_bar_timestamp_ms",
    "close",
    "window_start_date_60d",
    "observations_available",
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
    "feed",
    "adjustment",
    "timeframe",
    "currency",
    "latest_source_response_id",
    "latest_source_fetched_at_ms",
    "latest_source_ingestion_run_id",
)

FUNDAMENTAL_COLUMNS = (
    "source_system",
    "symbol",
    "cik",
    "as_of_date",
    "fundamental_period_end",
    "latest_filing_form",
    "latest_accession_number",
    "revenue_ttm",
    "net_income_ttm",
    "net_margin_ttm",
    "assets_latest",
    "revenue_growth_latest_fy",
    "net_income_change_latest_fy",
    "latest_fy_end",
    "prior_fy_end",
    "ttm_derivation_method",
    "latest_source_response_id",
    "latest_source_fetched_at_ms",
    "latest_source_ingestion_run_id",
)

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


def parse_market_metrics_statement_response(
    response: Mapping[str, Any],
) -> tuple[GoldMarketMetric, ...]:
    """Parse a successful inline Statement Execution response."""

    rows = _statement_rows(
        response,
        expected_columns=MARKET_COLUMNS,
    )

    return tuple(
        GoldMarketMetric(
            source_system=_required_cell(row, "source_system"),
            symbol=_required_cell(row, "symbol"),
            as_of_date=_parse_date_cell(row, "as_of_date"),
            as_of_bar_timestamp=_parse_epoch_millis_cell(
                row,
                "as_of_bar_timestamp_ms",
            ),
            close=_parse_decimal_cell(row, "close"),
            window_start_date_60d=_parse_date_cell(
                row,
                "window_start_date_60d",
            ),
            observations_available=_parse_int_cell(
                row,
                "observations_available",
            ),
            return_1d=_parse_decimal_cell(row, "return_1d"),
            return_5d=_parse_decimal_cell(row, "return_5d"),
            return_20d=_parse_decimal_cell(row, "return_20d"),
            return_60d=_parse_decimal_cell(row, "return_60d"),
            annualized_volatility_20d=_parse_decimal_cell(
                row,
                "annualized_volatility_20d",
            ),
            annualized_volatility_60d=_parse_decimal_cell(
                row,
                "annualized_volatility_60d",
            ),
            current_drawdown_60d=_parse_decimal_cell(
                row,
                "current_drawdown_60d",
            ),
            max_drawdown_60d=_parse_decimal_cell(
                row,
                "max_drawdown_60d",
            ),
            sma_20=_parse_decimal_cell(row, "sma_20"),
            sma_60=_parse_decimal_cell(row, "sma_60"),
            close_vs_sma_20=_parse_decimal_cell(
                row,
                "close_vs_sma_20",
            ),
            close_vs_sma_60=_parse_decimal_cell(
                row,
                "close_vs_sma_60",
            ),
            sma_20_vs_sma_60=_parse_decimal_cell(
                row,
                "sma_20_vs_sma_60",
            ),
            feed=_required_cell(row, "feed"),
            adjustment=_required_cell(row, "adjustment"),
            timeframe=_required_cell(row, "timeframe"),
            currency=_required_cell(row, "currency"),
            latest_source_response_id=_required_cell(
                row,
                "latest_source_response_id",
            ),
            latest_source_fetched_at=_parse_epoch_millis_cell(
                row,
                "latest_source_fetched_at_ms",
            ),
            latest_source_ingestion_run_id=_required_cell(
                row,
                "latest_source_ingestion_run_id",
            ),
        )
        for row in rows
    )


def parse_fundamental_metrics_statement_response(
    response: Mapping[str, Any],
) -> tuple[GoldFundamentalMetric, ...]:
    """Parse a successful inline Statement Execution response."""

    rows = _statement_rows(
        response,
        expected_columns=FUNDAMENTAL_COLUMNS,
    )

    return tuple(
        GoldFundamentalMetric(
            source_system=_required_cell(row, "source_system"),
            symbol=_required_cell(row, "symbol"),
            cik=_required_cell(row, "cik"),
            as_of_date=_parse_date_cell(row, "as_of_date"),
            fundamental_period_end=_parse_date_cell(
                row,
                "fundamental_period_end",
            ),
            latest_filing_form=_required_cell(
                row,
                "latest_filing_form",
            ),
            latest_accession_number=_required_cell(
                row,
                "latest_accession_number",
            ),
            revenue_ttm=_parse_decimal_cell(row, "revenue_ttm"),
            net_income_ttm=_parse_decimal_cell(
                row,
                "net_income_ttm",
            ),
            net_margin_ttm=_parse_decimal_cell(
                row,
                "net_margin_ttm",
            ),
            assets_latest=_parse_decimal_cell(
                row,
                "assets_latest",
            ),
            revenue_growth_latest_fy=_parse_decimal_cell(
                row,
                "revenue_growth_latest_fy",
            ),
            net_income_change_latest_fy=_parse_decimal_cell(
                row,
                "net_income_change_latest_fy",
            ),
            latest_fy_end=_parse_date_cell(row, "latest_fy_end"),
            prior_fy_end=_parse_date_cell(row, "prior_fy_end"),
            ttm_derivation_method=_required_cell(
                row,
                "ttm_derivation_method",
            ),
            latest_source_response_id=_required_cell(
                row,
                "latest_source_response_id",
            ),
            latest_source_fetched_at=_parse_epoch_millis_cell(
                row,
                "latest_source_fetched_at_ms",
            ),
            latest_source_ingestion_run_id=_required_cell(
                row,
                "latest_source_ingestion_run_id",
            ),
        )
        for row in rows
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
        "wait_timeout": SQL_WAIT_TIMEOUT,
        "on_wait_timeout": "CONTINUE",
    }


def _statement_rows(
    response: Mapping[str, Any],
    *,
    expected_columns: Sequence[str],
) -> tuple[dict[str, object], ...]:
    if not isinstance(response, Mapping):
        raise ControlledToolDataError(
            "Statement Execution response must be a mapping."
        )

    status = response.get("status")

    if not isinstance(status, Mapping):
        raise ControlledToolDataError(
            "Statement Execution response is missing status."
        )

    state = status.get("state")

    if state != "SUCCEEDED":
        error = status.get("error")
        detail = ""

        if isinstance(error, Mapping):
            error_code = error.get("error_code")
            message = error.get("message")
            detail = f"; error_code={error_code}; message={message}"

        raise ControlledToolDataError(
            "Statement Execution did not succeed: "
            f"state={state!r}{detail}."
        )

    manifest = response.get("manifest")

    if not isinstance(manifest, Mapping):
        raise ControlledToolDataError(
            "Successful Statement Execution response is missing manifest."
        )

    if manifest.get("format") != "JSON_ARRAY":
        raise ControlledToolDataError(
            "Statement Execution result must use JSON_ARRAY format."
        )

    schema = manifest.get("schema")

    if not isinstance(schema, Mapping):
        raise ControlledToolDataError(
            "Statement Execution manifest is missing schema."
        )

    raw_columns = schema.get("columns")

    if not isinstance(raw_columns, list):
        raise ControlledToolDataError(
            "Statement Execution schema is missing columns."
        )

    column_names = tuple(
        column.get("name")
        for column in raw_columns
        if isinstance(column, Mapping)
    )

    if column_names != tuple(expected_columns):
        raise ControlledToolDataError(
            "Statement Execution columns do not match the controlled "
            "projection."
        )

    result = response.get("result")

    if not isinstance(result, Mapping):
        raise ControlledToolDataError(
            "Successful Statement Execution response is missing result data."
        )

    if result.get("next_chunk_index") is not None:
        raise ControlledToolDataError(
            "Controlled Gold query unexpectedly returned multiple chunks."
        )

    if manifest.get("total_chunk_count") not in {None, 1}:
        raise ControlledToolDataError(
            "Controlled Gold query unexpectedly returned multiple chunks."
        )

    if manifest.get("truncated") is True or result.get("truncated") is True:
        raise ControlledToolDataError(
            "Controlled Gold query result was truncated."
        )

    data_array = result.get("data_array", [])

    if not isinstance(data_array, list):
        raise ControlledToolDataError(
            "Statement Execution data_array must be a list."
        )

    rows: list[dict[str, object]] = []

    for raw_row in data_array:
        if not isinstance(raw_row, list):
            raise ControlledToolDataError(
                "Statement Execution rows must be arrays."
            )

        if len(raw_row) != len(column_names):
            raise ControlledToolDataError(
                "Statement Execution row width does not match its schema."
            )

        rows.append(
            dict(
                zip(
                    column_names,
                    raw_row,
                    strict=True,
                )
            )
        )

    return tuple(rows)


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


def _required_cell(
    row: Mapping[str, object],
    field: str,
) -> str:
    if field not in row:
        raise ControlledToolDataError(
            f"Statement row is missing {field}."
        )

    return _required_text(row[field], field)


def _parse_date_cell(
    row: Mapping[str, object],
    field: str,
) -> date:
    text = _required_cell(row, field)

    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ControlledToolDataError(
            f"{field} must be an ISO date."
        ) from exc


def _parse_epoch_millis_cell(
    row: Mapping[str, object],
    field: str,
) -> datetime:
    text = _required_cell(row, field)

    try:
        millis = int(text)
    except ValueError as exc:
        raise ControlledToolDataError(
            f"{field} must be epoch milliseconds."
        ) from exc

    try:
        return datetime.fromtimestamp(
            millis / 1000,
            tz=timezone.utc,
        )
    except (OSError, OverflowError, ValueError) as exc:
        raise ControlledToolDataError(
            f"{field} contains invalid epoch milliseconds."
        ) from exc


def _parse_decimal_cell(
    row: Mapping[str, object],
    field: str,
) -> Decimal:
    text = _required_cell(row, field)

    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ControlledToolDataError(
            f"{field} must be a decimal value."
        ) from exc

    if not value.is_finite():
        raise ControlledToolDataError(
            f"{field} must be finite."
        )

    return value


def _parse_int_cell(
    row: Mapping[str, object],
    field: str,
) -> int:
    text = _required_cell(row, field)

    try:
        return int(text)
    except ValueError as exc:
        raise ControlledToolDataError(
            f"{field} must be an integer."
        ) from exc


def _required_text(
    value: object,
    field: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ControlledToolDataError(
            f"{field} must be a nonblank string."
        )

    return value.strip()
