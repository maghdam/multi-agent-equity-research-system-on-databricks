# Databricks notebook source
"""Build the current validated Silver daily-price snapshot from Bronze history.

The job reads immutable Alpaca price-response history, delegates business
validation and deterministic replay/version selection to the reusable
Silver-price module, validates the final snapshot, and publishes the managed
Delta table only after all pre-publication checks pass.
"""

import re
from datetime import datetime, timezone
from uuid import uuid4

from equity_research.config import load_equities
from equity_research.silver_prices import (
    BronzePriceResponse,
    transform_price_snapshot,
)
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count
from pyspark.sql.types import (
    DateType,
    DecimalType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _required_identifier(
    value: str,
    parameter: str,
) -> str:
    """Validate one Unity Catalog identifier from bundle configuration."""

    normalized = value.strip()

    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(
            f"Invalid {parameter} identifier: {value!r}."
        )

    return normalized


def _as_utc_aware(
    value: datetime,
) -> datetime:
    """Convert a Spark timestamp value into an aware UTC datetime.

    Spark returns Python timestamp values without tzinfo in many collection
    paths. This notebook fixes the Spark session timezone to UTC before reads,
    so a naive returned value can safely be interpreted as UTC here.
    """

    if not isinstance(value, datetime):
        raise ValueError(
            "Bronze fetched_at must be a datetime."
        )

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# COMMAND ----------

dbutils.widgets.text("catalog", "")  # type: ignore[name-defined]
dbutils.widgets.text("bronze_schema", "")  # type: ignore[name-defined]
dbutils.widgets.text("silver_schema", "")  # type: ignore[name-defined]

catalog = _required_identifier(
    dbutils.widgets.get("catalog"),  # type: ignore[name-defined]
    "catalog",
)
bronze_schema_name = _required_identifier(
    dbutils.widgets.get("bronze_schema"),  # type: ignore[name-defined]
    "bronze_schema",
)
silver_schema_name = _required_identifier(
    dbutils.widgets.get("silver_schema"),  # type: ignore[name-defined]
    "silver_schema",
)

bronze_table_name = (
    f"{catalog}.{bronze_schema_name}.price_responses"
)
silver_table_name = (
    f"{catalog}.{silver_schema_name}.daily_prices"
)

quoted_silver_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        silver_schema_name,
        "daily_prices",
    )
)

transformation_run_id = str(uuid4())

# COMMAND ----------

spark = SparkSession.builder.getOrCreate()

# Keep timestamp interpretation deterministic when Spark materializes Python
# datetime values from the Bronze TIMESTAMP column.
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
        "No configured equities are available for Silver prices."
    )

# COMMAND ----------

required_bronze_columns = (
    "source_system",
    "source_response_id",
    "request_parameters_json",
    "response_payload_json",
    "fetched_at",
    "ingestion_run_id",
)

bronze_dataframe = spark.table(
    bronze_table_name
).select(
    *required_bronze_columns
)

bronze_rows = bronze_dataframe.collect()

if not bronze_rows:
    raise RuntimeError(
        "Bronze price_responses is empty; "
        "Silver daily_prices cannot be rebuilt."
    )

bronze_responses: list[BronzePriceResponse] = []

for row in bronze_rows:
    bronze_responses.append(
        BronzePriceResponse(
            source_system=row["source_system"],
            source_response_id=row[
                "source_response_id"
            ],
            request_parameters_json=row[
                "request_parameters_json"
            ],
            response_payload_json=row[
                "response_payload_json"
            ],
            fetched_at=_as_utc_aware(
                row["fetched_at"]
            ),
            ingestion_run_id=row[
                "ingestion_run_id"
            ],
        )
    )

# All business validation, classification, replay handling, duplicate handling,
# and current-version selection happen before publication.
try:
    snapshot = transform_price_snapshot(
        bronze_responses=bronze_responses,
        configured_symbols=configured_symbols,
    )
except ValueError as exc:
    raise RuntimeError(
        "Silver price transformation failed before publication."
    ) from exc

if snapshot.selected_count == 0:
    raise RuntimeError(
        "Silver price transformation produced no publishable daily prices."
    )

# COMMAND ----------

silver_table_schema = StructType(
    [
        StructField(
            "symbol",
            StringType(),
            False,
        ),
        StructField(
            "bar_timestamp",
            TimestampType(),
            False,
        ),
        StructField(
            "trading_date",
            DateType(),
            False,
        ),
        StructField(
            "open",
            DecimalType(20, 8),
            False,
        ),
        StructField(
            "high",
            DecimalType(20, 8),
            False,
        ),
        StructField(
            "low",
            DecimalType(20, 8),
            False,
        ),
        StructField(
            "close",
            DecimalType(20, 8),
            False,
        ),
        StructField(
            "volume",
            DecimalType(20, 8),
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
            "source_system",
            StringType(),
            False,
        ),
        StructField(
            "source_response_id",
            StringType(),
            False,
        ),
        StructField(
            "fetched_at",
            TimestampType(),
            False,
        ),
        StructField(
            "ingestion_run_id",
            StringType(),
            False,
        ),
    ]
)


silver_records: list[tuple[object, ...]] = []

for candidate in snapshot.selected:
    silver_records.append(
        (
            candidate.symbol,
            candidate.bar_timestamp,
            candidate.trading_date,
            candidate.open,
            candidate.high,
            candidate.low,
            candidate.close,
            candidate.volume,
            candidate.feed,
            candidate.adjustment,
            candidate.timeframe,
            candidate.currency,
            candidate.source_system,
            candidate.source_response_id,
            candidate.fetched_at,
            candidate.ingestion_run_id,
        )
    )

silver_dataframe = spark.createDataFrame(
    silver_records,
    schema=silver_table_schema,
)

# COMMAND ----------

# Final publication checks happen on the exact typed Spark DataFrame that will
# become daily_prices.

typed_row_count = silver_dataframe.count()

if typed_row_count != snapshot.selected_count:
    raise RuntimeError(
        "Typed Silver row count differs from the "
        "validated snapshot row count."
    )

duplicate_keys = (
    silver_dataframe.groupBy(
        "symbol",
        "bar_timestamp",
        "feed",
        "adjustment",
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
        "Final Silver price business-key uniqueness "
        "validation failed."
    )

invalid_null_rows = (
    silver_dataframe.filter(
        col("symbol").isNull()
        | col("bar_timestamp").isNull()
        | col("trading_date").isNull()
        | col("open").isNull()
        | col("high").isNull()
        | col("low").isNull()
        | col("close").isNull()
        | col("volume").isNull()
        | col("feed").isNull()
        | col("adjustment").isNull()
        | col("timeframe").isNull()
        | col("currency").isNull()
        | col("source_system").isNull()
        | col("source_response_id").isNull()
        | col("fetched_at").isNull()
        | col("ingestion_run_id").isNull()
    )
    .limit(1)
    .count()
)

if invalid_null_rows:
    raise RuntimeError(
        "Final Silver price snapshot contains a null "
        "required field."
    )

# COMMAND ----------

# Publication boundary:
#
# Nothing has changed in daily_prices before this statement. The validated
# DataFrame is exposed only as a temporary view, and CREATE OR REPLACE TABLE
# performs the managed Delta replacement after all business and uniqueness
# checks have succeeded.

temporary_view_name = (
    f"silver_daily_prices_{transformation_run_id.replace('-', '_')}"
)

silver_dataframe.createOrReplaceTempView(
    temporary_view_name
)

try:
    spark.sql(
        f"""
        CREATE OR REPLACE TABLE {quoted_silver_table_name}
        USING DELTA
        COMMENT 'Validated current daily equity-price snapshot'
        TBLPROPERTIES (
          'quality' = 'silver',
          'source_system' = 'alpaca'
        )
        AS
        SELECT
          symbol,
          bar_timestamp,
          trading_date,
          open,
          high,
          low,
          close,
          volume,
          feed,
          adjustment,
          timeframe,
          currency,
          source_system,
          source_response_id,
          fetched_at,
          ingestion_run_id
        FROM `{temporary_view_name}`
        """
    )
finally:
    spark.catalog.dropTempView(
        temporary_view_name
    )

# COMMAND ----------

# Operational verification after the atomic publication boundary.


print("SILVER_PRICE_REFRESH=PASSED")
print(f"bronze_table={bronze_table_name}")
print(f"silver_table={silver_table_name}")
print(
    f"configured_symbols={configured_symbols}"
)
print(
    f"bronze_response_count="
    f"{snapshot.bronze_response_count}"
)
print(
    f"accepted_candidate_count="
    f"{snapshot.accepted_candidate_count}"
)
print(
    f"selected_count="
    f"{snapshot.selected_count}"
)
print(
    f"rejected_count="
    f"{snapshot.rejected_count}"
)
print(
    f"out_of_scope_count="
    f"{snapshot.out_of_scope_count}"
)
print(
    f"duplicate_count="
    f"{snapshot.duplicate_count}"
)
print(
    f"superseded_count="
    f"{snapshot.superseded_count}"
)
print(
    f"transformation_run_id="
    f"{transformation_run_id}"
)

dbutils.notebook.exit(  # type: ignore[name-defined]
    "SILVER_PRICE_REFRESH=PASSED; "
    f"silver_table={silver_table_name}; "
    f"selected_count={snapshot.selected_count}; "
    f"transformation_run_id={transformation_run_id}"
)