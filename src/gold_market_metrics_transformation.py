# Databricks notebook source
"""Build the current Gold market-metrics snapshot from Silver daily prices.

The notebook is intentionally thin. It reads validated Silver daily-price
history, converts rows to the pure-Python Gold boundary model, delegates all
alignment and metric calculation to gold_market_metrics, validates the typed
result, and atomically publishes the managed Gold Delta table.
"""

import re
from datetime import datetime, timezone
from uuid import uuid4

from equity_research.config import load_equities
from equity_research.gold_market_metrics import (
    MarketPriceObservation,
    build_market_metrics_snapshot,
)
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col,
    count,
)
from pyspark.sql.types import (
    DateType,
    DecimalType,
    IntegerType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


IDENTIFIER_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*"
)


def _required_identifier(
    value: str,
    parameter: str,
) -> str:
    """Validate one Unity Catalog identifier."""

    normalized = value.strip()

    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"Invalid {parameter} identifier: {value!r}."
        )

    return normalized


def _as_utc_aware(
    value: datetime,
) -> datetime:
    """Interpret collected Spark timestamps deterministically as UTC."""

    if not isinstance(value, datetime):
        raise ValueError(
            "Silver timestamp value must be a datetime."
        )

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


# COMMAND ----------

dbutils.widgets.text("catalog", "")  # type: ignore[name-defined]
dbutils.widgets.text("silver_schema", "")  # type: ignore[name-defined]
dbutils.widgets.text("gold_schema", "")  # type: ignore[name-defined]

catalog = _required_identifier(
    dbutils.widgets.get("catalog"),  # type: ignore[name-defined]
    "catalog",
)

silver_schema_name = _required_identifier(
    dbutils.widgets.get("silver_schema"),  # type: ignore[name-defined]
    "silver_schema",
)

gold_schema_name = _required_identifier(
    dbutils.widgets.get("gold_schema"),  # type: ignore[name-defined]
    "gold_schema",
)

silver_table_name = (
    f"{catalog}.{silver_schema_name}.daily_prices"
)

gold_table_name = (
    f"{catalog}.{gold_schema_name}.market_metrics"
)

quoted_gold_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        gold_schema_name,
        "market_metrics",
    )
)

transformation_run_id = str(uuid4())

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()

spark.conf.set(
    "spark.sql.session.timeZone",
    "UTC",
)

equities = load_equities()

configured_symbols = tuple(
    equity.alpaca_symbol
    for equity in equities.values()
)

if not configured_symbols:
    raise RuntimeError(
        "No configured equities are available for Gold market metrics."
    )

# COMMAND ----------

required_silver_columns = (
    "symbol",
    "bar_timestamp",
    "trading_date",
    "close",
    "feed",
    "adjustment",
    "timeframe",
    "currency",
    "source_system",
    "source_response_id",
    "fetched_at",
    "ingestion_run_id",
)

silver_dataframe = spark.table(
    silver_table_name
).select(
    *required_silver_columns
)

silver_rows = silver_dataframe.collect()

if not silver_rows:
    raise RuntimeError(
        "Silver daily_prices is empty; "
        "Gold market_metrics cannot be rebuilt."
    )

observations: list[MarketPriceObservation] = []

for row in silver_rows:
    observations.append(
        MarketPriceObservation(
            symbol=row["symbol"],
            bar_timestamp=_as_utc_aware(
                row["bar_timestamp"]
            ),
            trading_date=row["trading_date"],
            close=row["close"],
            source_system=row["source_system"],
            feed=row["feed"],
            adjustment=row["adjustment"],
            timeframe=row["timeframe"],
            currency=row["currency"],
            source_response_id=row[
                "source_response_id"
            ],
            fetched_at=_as_utc_aware(
                row["fetched_at"]
            ),
            ingestion_run_id=row[
                "ingestion_run_id"
            ],
        )
    )

try:
    snapshot = build_market_metrics_snapshot(
        observations=observations,
        configured_symbols=configured_symbols,
    )
except ValueError as exc:
    raise RuntimeError(
        "Gold market-metrics transformation failed "
        "before publication."
    ) from exc

if len(snapshot) != len(configured_symbols):
    raise RuntimeError(
        "Gold market-metrics snapshot does not contain "
        "exactly one row per configured symbol."
    )

# COMMAND ----------

gold_table_schema = StructType(
    [
        StructField(
            "source_system",
            StringType(),
            False,
        ),
        StructField(
            "symbol",
            StringType(),
            False,
        ),
        StructField(
            "as_of_date",
            DateType(),
            False,
        ),
        StructField(
            "as_of_bar_timestamp",
            TimestampType(),
            False,
        ),
        StructField(
            "close",
            DecimalType(20, 8),
            False,
        ),
        StructField(
            "window_start_date_60d",
            DateType(),
            False,
        ),
        StructField(
            "observations_available",
            IntegerType(),
            False,
        ),
        StructField(
            "return_1d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "return_5d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "return_20d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "return_60d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "annualized_volatility_20d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "annualized_volatility_60d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "current_drawdown_60d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "max_drawdown_60d",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "sma_20",
            DecimalType(28, 10),
            False,
        ),
        StructField(
            "sma_60",
            DecimalType(28, 10),
            False,
        ),
        StructField(
            "close_vs_sma_20",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "close_vs_sma_60",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "sma_20_vs_sma_60",
            DecimalType(20, 10),
            False,
        ),
        StructField(
            "feed",
            StringType(),
            False,
        ),
        StructField(
            "adjustment",
            StringType(),
            False,
        ),
        StructField(
            "timeframe",
            StringType(),
            False,
        ),
        StructField(
            "currency",
            StringType(),
            False,
        ),
        StructField(
            "latest_source_response_id",
            StringType(),
            False,
        ),
        StructField(
            "latest_source_fetched_at",
            TimestampType(),
            False,
        ),
        StructField(
            "latest_source_ingestion_run_id",
            StringType(),
            False,
        ),
    ]
)

gold_records: list[tuple[object, ...]] = []

for metric in snapshot:
    gold_records.append(
        (
            metric.source_system,
            metric.symbol,
            metric.as_of_date,
            metric.as_of_bar_timestamp,
            metric.close,
            metric.window_start_date_60d,
            metric.observations_available,
            metric.return_1d,
            metric.return_5d,
            metric.return_20d,
            metric.return_60d,
            metric.annualized_volatility_20d,
            metric.annualized_volatility_60d,
            metric.current_drawdown_60d,
            metric.max_drawdown_60d,
            metric.sma_20,
            metric.sma_60,
            metric.close_vs_sma_20,
            metric.close_vs_sma_60,
            metric.sma_20_vs_sma_60,
            metric.feed,
            metric.adjustment,
            metric.timeframe,
            metric.currency,
            metric.latest_source_response_id,
            metric.latest_source_fetched_at,
            metric.latest_source_ingestion_run_id,
        )
    )

gold_dataframe = spark.createDataFrame(
    gold_records,
    schema=gold_table_schema,
)

# COMMAND ----------

# Validate the exact typed DataFrame that will be published.

typed_row_count = gold_dataframe.count()

if typed_row_count != len(configured_symbols):
    raise RuntimeError(
        "Typed Gold row count differs from configured universe size."
    )

distinct_symbol_count = (
    gold_dataframe.select(
        "symbol"
    ).distinct().count()
)

if distinct_symbol_count != len(configured_symbols):
    raise RuntimeError(
        "Gold snapshot does not contain exactly one row "
        "per configured symbol."
    )

distinct_as_of_dates = (
    gold_dataframe.select(
        "as_of_date"
    ).distinct().count()
)

if distinct_as_of_dates != 1:
    raise RuntimeError(
        "Gold snapshot does not share one common as_of_date."
    )

duplicate_keys = (
    gold_dataframe.groupBy(
        "symbol",
        "as_of_date",
    )
    .agg(
        count("*").alias("key_count")
    )
    .filter(
        col("key_count") != 1
    )
    .limit(1)
    .count()
)

if duplicate_keys:
    raise RuntimeError(
        "Gold market-metrics business-key uniqueness failed."
    )

required_columns = tuple(
    field.name
    for field in gold_table_schema.fields
)

null_condition = None

for column_name in required_columns:
    condition = col(
        column_name
    ).isNull()

    null_condition = (
        condition
        if null_condition is None
        else null_condition | condition
    )

if (
    null_condition is not None
    and gold_dataframe.filter(
        null_condition
    ).limit(1).count()
):
    raise RuntimeError(
        "Gold market-metrics snapshot contains a null required field."
    )

invalid_scope = (
    gold_dataframe.filter(
        (col("source_system") != "alpaca")
        | (col("feed") != "sip")
        | (col("adjustment") != "split")
        | (col("timeframe") != "1Day")
        | (col("currency") != "USD")
        | (col("observations_available") < 61)
    )
    .limit(1)
    .count()
)

if invalid_scope:
    raise RuntimeError(
        "Gold market-metrics source or coverage validation failed."
    )

invalid_metric_ranges = (
    gold_dataframe.filter(
        (col("close") <= 0)
        | (col("sma_20") <= 0)
        | (col("sma_60") <= 0)
        | (col("annualized_volatility_20d") < 0)
        | (col("annualized_volatility_60d") < 0)
        | (col("current_drawdown_60d") < -1)
        | (col("current_drawdown_60d") > 0)
        | (col("max_drawdown_60d") < -1)
        | (col("max_drawdown_60d") > 0)
    )
    .limit(1)
    .count()
)

if invalid_metric_ranges:
    raise RuntimeError(
        "Gold market-metrics final metric-range validation failed."
    )

# COMMAND ----------

# Atomic publication boundary.

temporary_view_name = (
    "gold_market_metrics_"
    + transformation_run_id.replace(
        "-",
        "_",
    )
)

gold_dataframe.createOrReplaceTempView(
    temporary_view_name
)

try:
    spark.sql(
        f"""
        CREATE OR REPLACE TABLE {quoted_gold_table_name}
        USING DELTA
        COMMENT 'Current comparable equity market metrics'
        TBLPROPERTIES (
          'quality' = 'gold',
          'source_system' = 'alpaca'
        )
        AS
        SELECT *
        FROM `{temporary_view_name}`
        """
    )
finally:
    spark.catalog.dropTempView(
        temporary_view_name
    )

# COMMAND ----------

as_of_date = snapshot[0].as_of_date

print("GOLD_MARKET_METRICS_REFRESH=PASSED")
print(f"silver_table={silver_table_name}")
print(f"gold_table={gold_table_name}")
print(f"configured_symbols={configured_symbols}")
print(f"selected_count={len(snapshot)}")
print(f"as_of_date={as_of_date}")
print(
    f"transformation_run_id="
    f"{transformation_run_id}"
)

dbutils.notebook.exit(  # type: ignore[name-defined]
    "GOLD_MARKET_METRICS_REFRESH=PASSED; "
    f"gold_table={gold_table_name}; "
    f"selected_count={len(snapshot)}; "
    f"as_of_date={as_of_date}; "
    f"transformation_run_id={transformation_run_id}"
)
