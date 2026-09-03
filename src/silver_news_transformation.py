# Databricks notebook source
"""Rebuild the current Silver company-news snapshot from Bronze history."""

import re
from datetime import datetime, timezone
from uuid import uuid4

from equity_research.config import load_equities
from equity_research.silver_news import (
    BronzeNewsResponse,
    transform_news_snapshot,
)
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count
from pyspark.sql.types import (
    ArrayType,
    LongType,
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
    f"{catalog}.{bronze_schema_name}.news_responses"
)

silver_table_name = (
    f"{catalog}.{silver_schema_name}.news_articles"
)


quoted_silver_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        silver_schema_name,
        "news_articles",
    )
)


transformation_run_id = str(uuid4())


spark = SparkSession.builder.getOrCreate()

spark.conf.set(
    "spark.sql.session.timeZone",
    "UTC",
)


equities = load_equities()

configured_symbols = [
    equity.alpaca_symbol
    for equity in equities.values()
]


bronze_dataframe = (
    spark.table(bronze_table_name)
    .select(
        "source_system",
        "source_response_id",
        "response_payload_json",
        "fetched_at",
        "ingestion_run_id",
    )
)


bronze_rows = bronze_dataframe.collect()

if not bronze_rows:
    raise RuntimeError(
        "Bronze news history is empty; "
        "Silver publication is aborted."
    )

bronze_responses = [
    BronzeNewsResponse(
        source_system=row["source_system"],
        source_response_id=(
            row["source_response_id"]
        ),
        response_payload_json=(
            row["response_payload_json"]
        ),
        fetched_at=_as_utc_aware(
            row["fetched_at"]
        ),
        ingestion_run_id=(
            row["ingestion_run_id"]
        ),
    )
    for row in bronze_rows
]


try:
    snapshot = transform_news_snapshot(
        bronze_responses=bronze_responses,
        configured_symbols=configured_symbols,
    )
except ValueError as exc:
    raise RuntimeError(
        "Silver news transformation failed before "
        "publication."
    ) from exc


silver_schema = StructType(
    [
        StructField(
            "source_system",
            StringType(),
            nullable=False,
        ),
        StructField(
            "article_id",
            LongType(),
            nullable=False,
        ),
        StructField(
            "headline",
            StringType(),
            nullable=False,
        ),
        StructField(
            "symbols",
            ArrayType(
                StringType(),
                containsNull=False,
            ),
            nullable=False,
        ),
        StructField(
            "configured_symbols",
            ArrayType(
                StringType(),
                containsNull=False,
            ),
            nullable=False,
        ),
        StructField(
            "article_created_at",
            TimestampType(),
            nullable=False,
        ),
        StructField(
            "article_updated_at",
            TimestampType(),
            nullable=False,
        ),
        StructField(
            "article_source",
            StringType(),
            nullable=False,
        ),
        StructField(
            "url",
            StringType(),
            nullable=False,
        ),
        StructField(
            "summary",
            StringType(),
            nullable=True,
        ),
        StructField(
            "content",
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
        article.source_system,
        article.article_id,
        article.headline,
        list(article.symbols),
        list(article.configured_symbols),
        article.article_created_at,
        article.article_updated_at,
        article.article_source,
        article.url,
        article.summary,
        article.content,
        article.source_response_id,
        article.fetched_at,
        article.ingestion_run_id,
    )
    for article in snapshot.selected
]


silver_dataframe = spark.createDataFrame(
    silver_records,
    schema=silver_schema,
)


typed_row_count = silver_dataframe.count()

if typed_row_count != snapshot.selected_count:
    raise RuntimeError(
        "Typed Silver news row count differs from "
        "the selected snapshot count."
    )


duplicate_business_keys = (
    silver_dataframe
    .groupBy(
        "source_system",
        "article_id",
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
        "Silver news business-key uniqueness "
        "validation failed before publication."
    )


required_columns = [
    "source_system",
    "article_id",
    "headline",
    "symbols",
    "configured_symbols",
    "article_created_at",
    "article_updated_at",
    "article_source",
    "url",
    "source_response_id",
    "fetched_at",
    "ingestion_run_id",
]


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
        "Silver news required-field validation "
        "failed before publication."
    )


temporary_view_name = (
    "silver_news_publish_"
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
          'Validated current Alpaca company-news article versions'
        TBLPROPERTIES (
          'quality' = 'silver',
          'source_system' = 'alpaca'
        )
        AS
        SELECT
          source_system,
          article_id,
          headline,
          symbols,
          configured_symbols,
          article_created_at,
          article_updated_at,
          article_source,
          url,
          summary,
          content,
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


print("SILVER_NEWS_REFRESH=PASSED")
print(
    f"bronze_table={bronze_table_name}"
)
print(
    f"silver_table={silver_table_name}"
)
print(
    "configured_symbols="
    + ",".join(configured_symbols)
)
print(
    "bronze_response_count="
    f"{snapshot.bronze_response_count}"
)
print(
    "accepted_candidate_count="
    f"{snapshot.accepted_candidate_count}"
)
print(
    f"selected_count={snapshot.selected_count}"
)
print(
    f"rejected_count={snapshot.rejected_count}"
)
print(
    "out_of_scope_count="
    f"{snapshot.out_of_scope_count}"
)
print(
    f"duplicate_count={snapshot.duplicate_count}"
)
print(
    "superseded_count="
    f"{snapshot.superseded_count}"
)
print(
    f"transformation_run_id={transformation_run_id}"
)


dbutils.notebook.exit(  # type: ignore[name-defined]
    "SILVER_NEWS_REFRESH=PASSED; "
    f"silver_table={silver_table_name}; "
    f"selected_count={snapshot.selected_count}; "
    f"transformation_run_id={transformation_run_id}"
)