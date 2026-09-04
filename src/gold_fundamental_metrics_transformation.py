# Databricks notebook source
"""Build the current Gold fundamental-metrics snapshot from Silver company facts.

The notebook is intentionally thin. It reads the validated Silver company-facts
snapshot, converts rows to the pure-Python Gold boundary model, delegates filing
selection and metric calculation to gold_fundamental_metrics, validates the
typed result, and atomically publishes the managed Gold Delta table.
"""

import re
from datetime import datetime, timezone
from uuid import uuid4

from equity_research.config import load_equities
from equity_research.gold_fundamental_metrics import (
    FundamentalFactObservation,
    build_fundamental_metrics_snapshot,
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
            "Silver fetched_at value must be a datetime."
        )

    if value.tzinfo is None or value.utcoffset() is None:
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
    f"{catalog}.{silver_schema_name}.company_facts"
)

gold_table_name = (
    f"{catalog}.{gold_schema_name}.fundamental_metrics"
)

quoted_gold_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        gold_schema_name,
        "fundamental_metrics",
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

configured_companies = {
    equity.symbol: equity.sec_cik
    for equity in equities.values()
}

if not configured_companies:
    raise RuntimeError(
        "No configured companies are available for Gold fundamental metrics."
    )

# COMMAND ----------

required_silver_columns = (
    "source_system",
    "cik",
    "project_symbol",
    "taxonomy",
    "concept",
    "unit",
    "accession_number",
    "fact_value",
    "period_start",
    "period_end",
    "filing_form",
    "filing_date",
    "source_response_id",
    "fetched_at",
    "ingestion_run_id",
)

silver_dataframe = (
    spark.table(silver_table_name)
    .select(*required_silver_columns)
)

silver_rows = silver_dataframe.collect()

if not silver_rows:
    raise RuntimeError(
        "Silver company_facts is empty; "
        "Gold fundamental_metrics cannot be rebuilt."
    )

observations: list[FundamentalFactObservation] = []

for row in silver_rows:
    observations.append(
        FundamentalFactObservation(
            source_system=row["source_system"],
            cik=row["cik"],
            project_symbol=row["project_symbol"],
            taxonomy=row["taxonomy"],
            concept=row["concept"],
            unit=row["unit"],
            accession_number=row["accession_number"],
            fact_value=row["fact_value"],
            period_start=row["period_start"],
            period_end=row["period_end"],
            filing_form=row["filing_form"],
            filing_date=row["filing_date"],
            source_response_id=row["source_response_id"],
            fetched_at=_as_utc_aware(
                row["fetched_at"]
            ),
            ingestion_run_id=row["ingestion_run_id"],
        )
    )

try:
    snapshot = build_fundamental_metrics_snapshot(
        observations=observations,
        configured_companies=configured_companies,
    )
except ValueError as exc:
    raise RuntimeError(
        "Gold fundamental-metrics transformation failed "
        "before publication."
    ) from exc

if len(snapshot) != len(configured_companies):
    raise RuntimeError(
        "Gold fundamental-metrics snapshot does not contain "
        "exactly one row per configured company."
    )

# COMMAND ----------

gold_table_schema = StructType(
    [
        StructField(
            "source_system",
            StringType(),
            nullable=False,
        ),
        StructField(
            "symbol",
            StringType(),
            nullable=False,
        ),
        StructField(
            "cik",
            StringType(),
            nullable=False,
        ),
        StructField(
            "as_of_date",
            DateType(),
            nullable=False,
        ),
        StructField(
            "fundamental_period_end",
            DateType(),
            nullable=False,
        ),
        StructField(
            "latest_filing_form",
            StringType(),
            nullable=False,
        ),
        StructField(
            "latest_accession_number",
            StringType(),
            nullable=False,
        ),
        StructField(
            "revenue_ttm",
            DecimalType(30, 8),
            nullable=False,
        ),
        StructField(
            "net_income_ttm",
            DecimalType(30, 8),
            nullable=False,
        ),
        StructField(
            "net_margin_ttm",
            DecimalType(20, 10),
            nullable=False,
        ),
        StructField(
            "assets_latest",
            DecimalType(30, 8),
            nullable=False,
        ),
        StructField(
            "revenue_growth_latest_fy",
            DecimalType(20, 10),
            nullable=False,
        ),
        StructField(
            "net_income_change_latest_fy",
            DecimalType(30, 8),
            nullable=False,
        ),
        StructField(
            "latest_fy_end",
            DateType(),
            nullable=False,
        ),
        StructField(
            "prior_fy_end",
            DateType(),
            nullable=False,
        ),
        StructField(
            "ttm_derivation_method",
            StringType(),
            nullable=False,
        ),
        StructField(
            "latest_source_response_id",
            StringType(),
            nullable=False,
        ),
        StructField(
            "latest_source_fetched_at",
            TimestampType(),
            nullable=False,
        ),
        StructField(
            "latest_source_ingestion_run_id",
            StringType(),
            nullable=False,
        ),
    ]
)

gold_records = [
    (
        metric.source_system,
        metric.symbol,
        metric.cik,
        metric.as_of_date,
        metric.fundamental_period_end,
        metric.latest_filing_form,
        metric.latest_accession_number,
        metric.revenue_ttm,
        metric.net_income_ttm,
        metric.net_margin_ttm,
        metric.assets_latest,
        metric.revenue_growth_latest_fy,
        metric.net_income_change_latest_fy,
        metric.latest_fy_end,
        metric.prior_fy_end,
        metric.ttm_derivation_method,
        metric.latest_source_response_id,
        metric.latest_source_fetched_at,
        metric.latest_source_ingestion_run_id,
    )
    for metric in snapshot
]

gold_dataframe = spark.createDataFrame(
    gold_records,
    schema=gold_table_schema,
)

# COMMAND ----------

# Validate the exact typed DataFrame that will be published.

typed_row_count = gold_dataframe.count()

if typed_row_count != len(configured_companies):
    raise RuntimeError(
        "Typed Gold fundamental-metrics row count differs "
        "from configured company count."
    )

distinct_symbol_count = (
    gold_dataframe
    .select("symbol")
    .distinct()
    .count()
)

if distinct_symbol_count != len(configured_companies):
    raise RuntimeError(
        "Gold fundamental snapshot does not contain exactly "
        "one row per configured company."
    )

duplicate_keys = (
    gold_dataframe
    .groupBy(
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
        "Gold fundamental-metrics business-key uniqueness failed."
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
    and gold_dataframe
    .filter(null_condition)
    .limit(1)
    .count()
):
    raise RuntimeError(
        "Gold fundamental-metrics snapshot contains "
        "a null required field."
    )

invalid_scope = (
    gold_dataframe
    .filter(
        (col("source_system") != "sec")
        | (~col("latest_filing_form").isin("10-K", "10-Q"))
        | (
            ~col("ttm_derivation_method").isin(
                "annual",
                "annual_plus_ytd_minus_prior_ytd",
            )
        )
    )
    .limit(1)
    .count()
)

if invalid_scope:
    raise RuntimeError(
        "Gold fundamental-metrics source or derivation validation failed."
    )

invalid_metric_ranges = (
    gold_dataframe
    .filter(
        (col("revenue_ttm") <= 0)
        | (col("assets_latest") < 0)
        | (col("latest_fy_end") <= col("prior_fy_end"))
        | (col("fundamental_period_end") > col("as_of_date"))
    )
    .limit(1)
    .count()
)

if invalid_metric_ranges:
    raise RuntimeError(
        "Gold fundamental-metrics final range/period validation failed."
    )

expected_pairs = {
    (symbol, cik)
    for symbol, cik in configured_companies.items()
}
actual_pairs = {
    (metric.symbol, metric.cik)
    for metric in snapshot
}

if actual_pairs != expected_pairs:
    raise RuntimeError(
        "Gold fundamental-metrics symbol/CIK coverage "
        "does not match configured companies."
    )

# COMMAND ----------

# Atomic publication boundary.

temporary_view_name = (
    "gold_fundamental_metrics_"
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
        COMMENT 'Current comparable equity fundamental metrics'
        TBLPROPERTIES (
          'quality' = 'gold',
          'source_system' = 'sec'
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

print("GOLD_FUNDAMENTAL_METRICS_REFRESH=PASSED")
print(f"silver_table={silver_table_name}")
print(f"gold_table={gold_table_name}")
print(f"configured_companies={tuple(sorted(configured_companies))}")
print(f"selected_count={len(snapshot)}")
print(
    "as_of_dates="
    + ",".join(
        f"{metric.symbol}:{metric.as_of_date}"
        for metric in snapshot
    )
)
print(
    f"transformation_run_id="
    f"{transformation_run_id}"
)

dbutils.notebook.exit(  # type: ignore[name-defined]
    "GOLD_FUNDAMENTAL_METRICS_REFRESH=PASSED; "
    f"gold_table={gold_table_name}; "
    f"selected_count={len(snapshot)}; "
    f"transformation_run_id={transformation_run_id}"
)
