# Databricks notebook source
"""Rebuild the current Silver SEC company-facts snapshot from Bronze history."""

import re
from collections import Counter
from datetime import datetime, timezone
from uuid import uuid4

from equity_research.config import load_equities
from equity_research.silver_company_facts import (
    BronzeCompanyFactsResponse,
    transform_company_facts_snapshot,
)
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count
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
    """Normalize a Spark timestamp collected from a UTC session."""

    if not isinstance(value, datetime):
        raise ValueError(
            "Collected fetched_at must be a datetime."
        )

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


# COMMAND ----------

dbutils.widgets.text(  # type: ignore[name-defined]
    "catalog",
    "",
)
dbutils.widgets.text(  # type: ignore[name-defined]
    "bronze_schema",
    "",
)
dbutils.widgets.text(  # type: ignore[name-defined]
    "silver_schema",
    "",
)


catalog = _required_identifier(
    dbutils.widgets.get(  # type: ignore[name-defined]
        "catalog"
    ),
    "catalog",
)

bronze_schema_name = _required_identifier(
    dbutils.widgets.get(  # type: ignore[name-defined]
        "bronze_schema"
    ),
    "bronze_schema",
)

silver_schema_name = _required_identifier(
    dbutils.widgets.get(  # type: ignore[name-defined]
        "silver_schema"
    ),
    "silver_schema",
)


bronze_table_name = (
    f"{catalog}.{bronze_schema_name}.company_facts_responses"
)

silver_table_name = (
    f"{catalog}.{silver_schema_name}.company_facts"
)


quoted_silver_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        silver_schema_name,
        "company_facts",
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
        "No configured companies are available for Silver company facts."
    )


# COMMAND ----------

required_bronze_columns = (
    "source_system",
    "source_endpoint",
    "project_symbol",
    "sec_cik",
    "entity_name",
    "source_response_id",
    "response_payload_json",
    "response_sha256",
    "fetched_at",
    "ingestion_run_id",
)


bronze_dataframe = (
    spark.table(bronze_table_name)
    .select(*required_bronze_columns)
)


bronze_rows = bronze_dataframe.collect()

if not bronze_rows:
    raise RuntimeError(
        "Bronze company_facts_responses history is empty; "
        "Silver publication is aborted."
    )


bronze_responses = [
    BronzeCompanyFactsResponse(
        source_system=row["source_system"],
        source_endpoint=row["source_endpoint"],
        project_symbol=row["project_symbol"],
        sec_cik=row["sec_cik"],
        entity_name=row["entity_name"],
        source_response_id=row["source_response_id"],
        response_payload_json=row["response_payload_json"],
        response_sha256=row["response_sha256"],
        fetched_at=_as_utc_aware(
            row["fetched_at"]
        ),
        ingestion_run_id=row["ingestion_run_id"],
    )
    for row in bronze_rows
]


try:
    snapshot = transform_company_facts_snapshot(
        responses=bronze_responses,
        configured_companies=configured_companies,
    )
except ValueError as exc:
    raise RuntimeError(
        "Silver company-facts transformation failed "
        "before publication."
    ) from exc


if len(snapshot.selected_responses) != len(configured_companies):
    raise RuntimeError(
        "Selected Bronze response count does not match "
        "the configured company count."
    )


# COMMAND ----------

silver_schema = StructType(
    [
        StructField(
            "source_system",
            StringType(),
            nullable=False,
        ),
        StructField(
            "cik",
            StringType(),
            nullable=False,
        ),
        StructField(
            "project_symbol",
            StringType(),
            nullable=False,
        ),
        StructField(
            "taxonomy",
            StringType(),
            nullable=False,
        ),
        StructField(
            "concept",
            StringType(),
            nullable=False,
        ),
        StructField(
            "unit",
            StringType(),
            nullable=False,
        ),
        StructField(
            "accession_number",
            StringType(),
            nullable=False,
        ),
        StructField(
            "fact_value",
            DecimalType(28, 8),
            nullable=False,
        ),
        StructField(
            "period_start",
            DateType(),
            nullable=True,
        ),
        StructField(
            "period_end",
            DateType(),
            nullable=False,
        ),
        StructField(
            "filing_form",
            StringType(),
            nullable=False,
        ),
        StructField(
            "filing_date",
            DateType(),
            nullable=False,
        ),
        StructField(
            "entity_name",
            StringType(),
            nullable=True,
        ),
        StructField(
            "concept_label",
            StringType(),
            nullable=True,
        ),
        StructField(
            "filing_fiscal_year",
            IntegerType(),
            nullable=True,
        ),
        StructField(
            "filing_fiscal_period",
            StringType(),
            nullable=True,
        ),
        StructField(
            "frame",
            StringType(),
            nullable=True,
        ),
        StructField(
            "source_response_id",
            StringType(),
            nullable=False,
        ),
        StructField(
            "fetched_at",
            TimestampType(),
            nullable=False,
        ),
        StructField(
            "ingestion_run_id",
            StringType(),
            nullable=False,
        ),
    ]
)


silver_records = [
    (
        fact.source_system,
        fact.cik,
        fact.project_symbol,
        fact.taxonomy,
        fact.concept,
        fact.unit,
        fact.accession_number,
        fact.fact_value,
        fact.period_start,
        fact.period_end,
        fact.filing_form,
        fact.filing_date,
        fact.entity_name,
        fact.concept_label,
        fact.filing_fiscal_year,
        fact.filing_fiscal_period,
        fact.frame,
        fact.source_response_id,
        fact.fetched_at,
        fact.ingestion_run_id,
    )
    for fact in snapshot.selected
]


silver_dataframe = spark.createDataFrame(
    silver_records,
    schema=silver_schema,
)


# COMMAND ----------

typed_row_count = silver_dataframe.count()

if typed_row_count != snapshot.selected_count:
    raise RuntimeError(
        "Typed Silver company-facts row count differs "
        "from the validated snapshot count."
    )


duplicate_business_keys = (
    silver_dataframe
    .groupBy(
        "source_system",
        "cik",
        "taxonomy",
        "concept",
        "unit",
        "period_start",
        "period_end",
        "accession_number",
    )
    .agg(
        count("*").alias("row_count")
    )
    .filter(
        col("row_count") != 1
    )
    .limit(1)
    .count()
)

if duplicate_business_keys:
    raise RuntimeError(
        "Silver company-facts business-key uniqueness "
        "validation failed before publication."
    )


required_columns = (
    "source_system",
    "cik",
    "project_symbol",
    "taxonomy",
    "concept",
    "unit",
    "accession_number",
    "fact_value",
    "period_end",
    "filing_form",
    "filing_date",
    "source_response_id",
    "fetched_at",
    "ingestion_run_id",
)


null_condition = None

for column_name in required_columns:
    current_condition = col(
        column_name
    ).isNull()

    null_condition = (
        current_condition
        if null_condition is None
        else null_condition | current_condition
    )


if (
    null_condition is not None
    and silver_dataframe
    .filter(null_condition)
    .limit(1)
    .count()
):
    raise RuntimeError(
        "Silver company-facts required-field validation "
        "failed before publication."
    )


invalid_period_semantics = (
    silver_dataframe
    .filter(
        (
            col("concept").isin(
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "NetIncomeLoss",
            )
            & col("period_start").isNull()
        )
        |
        (
            (col("concept") == "Assets")
            & col("period_start").isNotNull()
        )
        |
        (
            col("period_start").isNotNull()
            & (col("period_start") > col("period_end"))
        )
    )
    .limit(1)
    .count()
)

if invalid_period_semantics:
    raise RuntimeError(
        "Silver company-facts period-semantics validation "
        "failed before publication."
    )


scope_violation = (
    silver_dataframe
    .filter(
        (col("source_system") != "sec")
        | (col("taxonomy") != "us-gaap")
        | (col("unit") != "USD")
        | ~col("concept").isin(
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "NetIncomeLoss",
            "Assets",
        )
    )
    .limit(1)
    .count()
)

if scope_violation:
    raise RuntimeError(
        "Silver company-facts scope validation "
        "failed before publication."
    )


# COMMAND ----------

temporary_view_name = (
    "silver_company_facts_publish_"
    + transformation_run_id.replace("-", "_")
)


silver_dataframe.createOrReplaceTempView(
    temporary_view_name
)


try:
    spark.sql(
        f"""
        CREATE OR REPLACE TABLE
          {quoted_silver_table_name}
        USING DELTA
        COMMENT
          'Validated current SEC company-facts snapshot'
        TBLPROPERTIES (
          'quality' = 'silver',
          'source_system' = 'sec'
        )
        AS
        SELECT
          source_system,
          cik,
          project_symbol,
          taxonomy,
          concept,
          unit,
          accession_number,
          fact_value,
          period_start,
          period_end,
          filing_form,
          filing_date,
          entity_name,
          concept_label,
          filing_fiscal_year,
          filing_fiscal_period,
          frame,
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

candidate_fact_count = (
    snapshot.selected_count
    + snapshot.rejected_count
    + snapshot.duplicate_count
)

rejection_issue_counts = Counter(
    issue.code
    for rejected_fact in snapshot.rejected
    for issue in rejected_fact.issues
)


print("SILVER_COMPANY_FACTS_REFRESH=PASSED")
print(
    f"bronze_table={bronze_table_name}"
)
print(
    f"silver_table={silver_table_name}"
)
print(
    "configured_companies="
    + ",".join(
        f"{symbol}:{cik}"
        for symbol, cik in configured_companies.items()
    )
)
print(
    "bronze_response_count="
    f"{snapshot.bronze_response_count}"
)
print(
    "selected_response_count="
    f"{len(snapshot.selected_responses)}"
)
print(
    f"candidate_fact_count={candidate_fact_count}"
)
print(
    f"selected_count={snapshot.selected_count}"
)
print(
    f"rejected_count={snapshot.rejected_count}"
)
print(
    f"duplicate_count={snapshot.duplicate_count}"
)
print(
    "unavailable_scope_count="
    f"{snapshot.unavailable_scope_count}"
)
print(
    "out_of_scope_response_count="
    f"{snapshot.out_of_scope_response_count}"
)
print(
    "superseded_response_count="
    f"{snapshot.superseded_response_count}"
)
print(
    f"tie_repeat_count={snapshot.tie_repeat_count}"
)
print(
    "rejection_issue_counts="
    + ",".join(
        f"{code}:{count_value}"
        for code, count_value
        in sorted(rejection_issue_counts.items())
    )
)
print(
    "unavailable_scopes="
    + ",".join(snapshot.unavailable_scopes)
)
print(
    f"transformation_run_id={transformation_run_id}"
)


dbutils.notebook.exit(  # type: ignore[name-defined]
    "SILVER_COMPANY_FACTS_REFRESH=PASSED; "
    f"silver_table={silver_table_name}; "
    f"selected_count={snapshot.selected_count}; "
    f"rejected_count={snapshot.rejected_count}; "
    f"transformation_run_id={transformation_run_id}"
)
