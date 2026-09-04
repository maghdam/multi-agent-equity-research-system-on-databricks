# Databricks notebook source
"""Rebuild the current Silver SEC filing-sections snapshot from Bronze history."""

import re
from datetime import date, datetime, timezone
from uuid import uuid4

from equity_research.config import load_equities
from equity_research.silver_filing_sections import (
    BronzeFilingDocument,
    MIN_SECTION_CHARS,
    transform_filing_sections_snapshot,
)
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count, length
from pyspark.sql.types import (
    DateType,
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


def _as_date(
    value: date,
    field_name: str,
) -> date:
    """Validate one Spark DATE value collected into Python."""

    if (
        not isinstance(value, date)
        or isinstance(value, datetime)
    ):
        raise ValueError(
            f"Collected {field_name} must be a date."
        )

    return value


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
    f"{catalog}.{bronze_schema_name}.filing_documents"
)

silver_table_name = (
    f"{catalog}.{silver_schema_name}.filing_sections"
)


quoted_silver_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        silver_schema_name,
        "filing_sections",
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
        "No configured companies are available for Silver filing sections."
    )


# COMMAND ----------

required_bronze_columns = (
    "source_response_id",
    "source_system",
    "source_endpoint",
    "project_symbol",
    "sec_cik",
    "accession_number",
    "filing_form",
    "filing_date",
    "report_date",
    "primary_document",
    "source_url",
    "http_status",
    "response_payload_html",
    "response_bytes",
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
        "Bronze filing_documents history is empty; "
        "Silver publication is aborted."
    )


bronze_responses = [
    BronzeFilingDocument(
        source_response_id=row["source_response_id"],
        source_system=row["source_system"],
        source_endpoint=row["source_endpoint"],
        project_symbol=row["project_symbol"],
        sec_cik=row["sec_cik"],
        accession_number=row["accession_number"],
        filing_form=row["filing_form"],
        filing_date=_as_date(
            row["filing_date"],
            "filing_date",
        ),
        report_date=_as_date(
            row["report_date"],
            "report_date",
        ),
        primary_document=row["primary_document"],
        source_url=row["source_url"],
        http_status=row["http_status"],
        response_payload_html=row["response_payload_html"],
        response_bytes=row["response_bytes"],
        response_sha256=row["response_sha256"],
        fetched_at=_as_utc_aware(
            row["fetched_at"]
        ),
        ingestion_run_id=row["ingestion_run_id"],
    )
    for row in bronze_rows
]


try:
    snapshot = transform_filing_sections_snapshot(
        responses=bronze_responses,
        configured_companies=configured_companies,
    )
except ValueError as exc:
    raise RuntimeError(
        "Silver filing-sections transformation failed "
        "before publication."
    ) from exc


expected_section_count = len(configured_companies) * 2

if snapshot.selected_count != expected_section_count:
    raise RuntimeError(
        "Validated filing-section count does not equal "
        "two sections per configured company."
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
            "accession_number",
            StringType(),
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
            "report_date",
            DateType(),
            nullable=False,
        ),
        StructField(
            "primary_document",
            StringType(),
            nullable=False,
        ),
        StructField(
            "source_url",
            StringType(),
            nullable=False,
        ),
        StructField(
            "section_code",
            StringType(),
            nullable=False,
        ),
        StructField(
            "section_title",
            StringType(),
            nullable=False,
        ),
        StructField(
            "section_text",
            StringType(),
            nullable=False,
        ),
        StructField(
            "section_text_sha256",
            StringType(),
            nullable=False,
        ),
        StructField(
            "source_response_id",
            StringType(),
            nullable=False,
        ),
        StructField(
            "response_sha256",
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
        section.source_system,
        section.cik,
        section.project_symbol,
        section.accession_number,
        section.filing_form,
        section.filing_date,
        section.report_date,
        section.primary_document,
        section.source_url,
        section.section_code,
        section.section_title,
        section.section_text,
        section.section_text_sha256,
        section.source_response_id,
        section.response_sha256,
        section.fetched_at,
        section.ingestion_run_id,
    )
    for section in snapshot.selected
]


silver_dataframe = spark.createDataFrame(
    silver_records,
    schema=silver_schema,
)


# COMMAND ----------

typed_row_count = silver_dataframe.count()

if typed_row_count != snapshot.selected_count:
    raise RuntimeError(
        "Typed Silver filing-section row count differs "
        "from the validated snapshot count."
    )


duplicate_business_keys = (
    silver_dataframe
    .groupBy(
        "source_system",
        "cik",
        "accession_number",
        "section_code",
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
        "Silver filing-section business-key uniqueness "
        "validation failed before publication."
    )


required_columns = (
    "source_system",
    "cik",
    "project_symbol",
    "accession_number",
    "filing_form",
    "filing_date",
    "report_date",
    "primary_document",
    "source_url",
    "section_code",
    "section_title",
    "section_text",
    "section_text_sha256",
    "source_response_id",
    "response_sha256",
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
        "Silver filing-section required-field validation "
        "failed before publication."
    )


scope_violation = (
    silver_dataframe
    .filter(
        (col("source_system") != "sec")
        | (col("filing_form") != "10-K")
        | ~col("section_code").isin(
            "item_1",
            "item_1a",
        )
        | (
            (col("section_code") == "item_1")
            & (col("section_title") != "Business")
        )
        | (
            (col("section_code") == "item_1a")
            & (col("section_title") != "Risk Factors")
        )
    )
    .limit(1)
    .count()
)

if scope_violation:
    raise RuntimeError(
        "Silver filing-section scope validation "
        "failed before publication."
    )


short_section_rows = (
    silver_dataframe
    .filter(
        length(col("section_text")) < MIN_SECTION_CHARS
    )
    .limit(1)
    .count()
)

if short_section_rows:
    raise RuntimeError(
        "Silver filing-section extraction-quality validation "
        "failed before publication."
    )


company_completeness_violation = (
    silver_dataframe
    .groupBy(
        "project_symbol",
    )
    .agg(
        count("*").alias("section_count"),
        count("source_response_id").alias(
            "source_response_count"
        ),
    )
    .filter(
        col("section_count") != 2
    )
    .limit(1)
    .count()
)

if company_completeness_violation:
    raise RuntimeError(
        "Silver filing-section company completeness "
        "validation failed before publication."
    )


# COMMAND ----------

temporary_view_name = (
    "silver_filing_sections_publish_"
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
          'Validated current SEC 10-K Item 1 and Item 1A sections'
        TBLPROPERTIES (
          'quality' = 'silver',
          'source_system' = 'sec'
        )
        AS
        SELECT
          source_system,
          cik,
          project_symbol,
          accession_number,
          filing_form,
          filing_date,
          report_date,
          primary_document,
          source_url,
          section_code,
          section_title,
          section_text,
          section_text_sha256,
          source_response_id,
          response_sha256,
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

print("SILVER_FILING_SECTIONS_REFRESH=PASSED")
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
    f"selected_count={snapshot.selected_count}"
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

for section in snapshot.selected:
    print(
        "section="
        f"{section.project_symbol}:"
        f"{section.section_code}; "
        f"chars={len(section.section_text)}; "
        f"sha256={section.section_text_sha256}; "
        f"source_response_id={section.source_response_id}"
    )

print(
    f"transformation_run_id={transformation_run_id}"
)


dbutils.notebook.exit(  # type: ignore[name-defined]
    "SILVER_FILING_SECTIONS_REFRESH=PASSED; "
    f"silver_table={silver_table_name}; "
    f"selected_count={snapshot.selected_count}; "
    f"transformation_run_id={transformation_run_id}"
)
