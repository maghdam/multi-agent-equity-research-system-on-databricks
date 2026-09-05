# Databricks notebook source
"""Publish deterministic RAG research documents and chunks from Silver data.

The notebook is intentionally thin. It converts current validated Silver news
and filing-section rows into the pure-Python RAG boundary models, builds the
complete deterministic document and chunk snapshots, validates the exact typed
DataFrames that will be published, and then replaces two managed Delta tables
in the AI retrieval schema.

All transformation logic remains in equity_research.research_documents and
equity_research.research_chunks so it can be exercised by offline unit tests.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from equity_research.config import load_equities
from equity_research.research_chunks import (
    ChunkingStrategy,
    build_research_chunks_snapshot,
)
from equity_research.research_documents import (
    build_research_documents_snapshot,
)
from equity_research.silver_filing_sections import SilverFilingSection
from equity_research.silver_news import SilverNewsArticle
from pyspark.sql import SparkSession
from pyspark.sql.functions import col, count
from pyspark.sql.types import (
    ArrayType,
    DateType,
    IntegerType,
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


def _required_positive_int(
    value: str,
    parameter: str,
) -> int:
    """Parse one strictly positive integer notebook parameter."""

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{parameter} must be an integer."
        ) from exc

    if parsed < 1:
        raise ValueError(
            f"{parameter} must be positive."
        )

    return parsed


def _required_nonnegative_int(
    value: str,
    parameter: str,
) -> int:
    """Parse one nonnegative integer notebook parameter."""

    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{parameter} must be an integer."
        ) from exc

    if parsed < 0:
        raise ValueError(
            f"{parameter} must be nonnegative."
        )

    return parsed


def _as_utc_aware(
    value: datetime,
) -> datetime:
    """Interpret collected Spark timestamps deterministically as UTC."""

    if not isinstance(value, datetime):
        raise ValueError(
            "Silver timestamp value must be a datetime."
        )

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def _corpus_snapshot_id(
    *,
    document_version_ids: list[str],
    chunking_strategy_version: str,
) -> str:
    """Build a deterministic identity for one document/chunk publication."""

    payload = {
        "chunking_strategy_version": chunking_strategy_version,
        "document_version_ids": document_version_ids,
    }

    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    return hashlib.sha256(encoded).hexdigest()


# COMMAND ----------

dbutils.widgets.text("catalog", "")  # type: ignore[name-defined]
dbutils.widgets.text("silver_schema", "")  # type: ignore[name-defined]
dbutils.widgets.text("ai_schema", "")  # type: ignore[name-defined]
dbutils.widgets.text("target_chars", "")  # type: ignore[name-defined]
dbutils.widgets.text("max_chars", "")  # type: ignore[name-defined]
dbutils.widgets.text("overlap_chars", "")  # type: ignore[name-defined]


catalog = _required_identifier(
    dbutils.widgets.get("catalog"),  # type: ignore[name-defined]
    "catalog",
)

silver_schema_name = _required_identifier(
    dbutils.widgets.get("silver_schema"),  # type: ignore[name-defined]
    "silver_schema",
)

ai_schema_name = _required_identifier(
    dbutils.widgets.get("ai_schema"),  # type: ignore[name-defined]
    "ai_schema",
)

target_chars = _required_positive_int(
    dbutils.widgets.get("target_chars"),  # type: ignore[name-defined]
    "target_chars",
)

max_chars = _required_positive_int(
    dbutils.widgets.get("max_chars"),  # type: ignore[name-defined]
    "max_chars",
)

overlap_chars = _required_nonnegative_int(
    dbutils.widgets.get("overlap_chars"),  # type: ignore[name-defined]
    "overlap_chars",
)


chunking_strategy = ChunkingStrategy(
    target_chars=target_chars,
    max_chars=max_chars,
    overlap_chars=overlap_chars,
)


silver_news_table_name = (
    f"{catalog}.{silver_schema_name}.news_articles"
)

silver_filing_table_name = (
    f"{catalog}.{silver_schema_name}.filing_sections"
)

research_documents_table_name = (
    f"{catalog}.{ai_schema_name}.research_documents"
)

research_chunks_table_name = (
    f"{catalog}.{ai_schema_name}.research_chunks"
)


quoted_research_documents_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        ai_schema_name,
        "research_documents",
    )
)

quoted_research_chunks_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        ai_schema_name,
        "research_chunks",
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
        "No configured equities are available for RAG corpus publication."
    )


# COMMAND ----------

news_dataframe = (
    spark.table(
        silver_news_table_name
    )
    .select(
        "source_system",
        "article_id",
        "headline",
        "symbols",
        "configured_symbols",
        "article_created_at",
        "article_updated_at",
        "article_source",
        "url",
        "summary",
        "content",
        "source_response_id",
        "fetched_at",
        "ingestion_run_id",
    )
)


filing_dataframe = (
    spark.table(
        silver_filing_table_name
    )
    .select(
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
)


news_rows = news_dataframe.collect()
filing_rows = filing_dataframe.collect()


if not news_rows:
    raise RuntimeError(
        "Silver news_articles is empty; RAG corpus publication is aborted."
    )

if not filing_rows:
    raise RuntimeError(
        "Silver filing_sections is empty; RAG corpus publication is aborted."
    )


expected_filing_count = len(configured_symbols) * 2

if len(filing_rows) != expected_filing_count:
    raise RuntimeError(
        "Silver filing_sections does not contain exactly Item 1 and Item 1A "
        "for every configured symbol."
    )


news_articles = [
    SilverNewsArticle(
        source_system=row["source_system"],
        article_id=row["article_id"],
        headline=row["headline"],
        symbols=tuple(row["symbols"]),
        configured_symbols=tuple(
            row["configured_symbols"]
        ),
        article_created_at=_as_utc_aware(
            row["article_created_at"]
        ),
        article_updated_at=_as_utc_aware(
            row["article_updated_at"]
        ),
        article_source=row["article_source"],
        url=row["url"],
        summary=row["summary"],
        content=row["content"],
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
    for row in news_rows
]


filing_sections = [
    SilverFilingSection(
        source_system=row["source_system"],
        cik=row["cik"],
        project_symbol=row["project_symbol"],
        accession_number=row[
            "accession_number"
        ],
        filing_form=row["filing_form"],
        filing_date=row["filing_date"],
        report_date=row["report_date"],
        primary_document=row[
            "primary_document"
        ],
        source_url=row["source_url"],
        section_code=row["section_code"],
        section_title=row["section_title"],
        section_text=row["section_text"],
        section_text_sha256=row[
            "section_text_sha256"
        ],
        source_response_id=row[
            "source_response_id"
        ],
        response_sha256=row[
            "response_sha256"
        ],
        fetched_at=_as_utc_aware(
            row["fetched_at"]
        ),
        ingestion_run_id=row[
            "ingestion_run_id"
        ],
    )
    for row in filing_rows
]


try:
    documents_snapshot = build_research_documents_snapshot(
        news_articles=news_articles,
        filing_sections=filing_sections,
        configured_symbols=configured_symbols,
    )

    chunks_snapshot = build_research_chunks_snapshot(
        documents=documents_snapshot.documents,
        strategy=chunking_strategy,
    )
except ValueError as exc:
    raise RuntimeError(
        "RAG research corpus transformation failed before publication."
    ) from exc


if documents_snapshot.document_count < documents_snapshot.filing_document_count:
    raise RuntimeError(
        "RAG document snapshot lost required filing documents."
    )

if chunks_snapshot.document_count != documents_snapshot.document_count:
    raise RuntimeError(
        "RAG chunk snapshot document count differs from document snapshot."
    )

if chunks_snapshot.chunk_count < chunks_snapshot.document_count:
    raise RuntimeError(
        "RAG chunk snapshot must contain at least one chunk per document."
    )


corpus_snapshot_id = _corpus_snapshot_id(
    document_version_ids=[
        document.document_version_id
        for document in documents_snapshot.documents
    ],
    chunking_strategy_version=(
        chunking_strategy.chunking_strategy_version
    ),
)


# COMMAND ----------

research_documents_schema = StructType(
    [
        StructField(
            "document_id",
            StringType(),
            False,
        ),
        StructField(
            "document_version_id",
            StringType(),
            False,
        ),
        StructField(
            "cleaning_strategy_version",
            StringType(),
            False,
        ),
        StructField(
            "source_type",
            StringType(),
            False,
        ),
        StructField(
            "source_system",
            StringType(),
            False,
        ),
        StructField(
            "configured_symbols",
            ArrayType(
                StringType(),
                containsNull=False,
            ),
            False,
        ),
        StructField(
            "title",
            StringType(),
            False,
        ),
        StructField(
            "document_text",
            StringType(),
            False,
        ),
        StructField(
            "document_text_sha256",
            StringType(),
            False,
        ),
        StructField(
            "text_origin",
            StringType(),
            False,
        ),
        StructField(
            "evidence_date",
            DateType(),
            False,
        ),
        StructField(
            "source_url",
            StringType(),
            False,
        ),
        StructField(
            "article_id",
            LongType(),
            True,
        ),
        StructField(
            "article_source",
            StringType(),
            True,
        ),
        StructField(
            "article_created_at",
            TimestampType(),
            True,
        ),
        StructField(
            "article_updated_at",
            TimestampType(),
            True,
        ),
        StructField(
            "cik",
            StringType(),
            True,
        ),
        StructField(
            "accession_number",
            StringType(),
            True,
        ),
        StructField(
            "filing_form",
            StringType(),
            True,
        ),
        StructField(
            "filing_date",
            DateType(),
            True,
        ),
        StructField(
            "report_date",
            DateType(),
            True,
        ),
        StructField(
            "section_code",
            StringType(),
            True,
        ),
        StructField(
            "section_title",
            StringType(),
            True,
        ),
        StructField(
            "source_response_id",
            StringType(),
            False,
        ),
        StructField(
            "source_fetched_at",
            TimestampType(),
            False,
        ),
        StructField(
            "source_ingestion_run_id",
            StringType(),
            False,
        ),
    ]
)


research_document_records = [
    (
        document.document_id,
        document.document_version_id,
        document.cleaning_strategy_version,
        document.source_type,
        document.source_system,
        list(document.configured_symbols),
        document.title,
        document.document_text,
        document.document_text_sha256,
        document.text_origin,
        document.evidence_date,
        document.source_url,
        document.article_id,
        document.article_source,
        document.article_created_at,
        document.article_updated_at,
        document.cik,
        document.accession_number,
        document.filing_form,
        document.filing_date,
        document.report_date,
        document.section_code,
        document.section_title,
        document.source_response_id,
        document.source_fetched_at,
        document.source_ingestion_run_id,
    )
    for document in documents_snapshot.documents
]


research_documents_dataframe = spark.createDataFrame(
    research_document_records,
    schema=research_documents_schema,
)


research_chunks_schema = StructType(
    [
        StructField(
            "chunk_id",
            StringType(),
            False,
        ),
        StructField(
            "document_id",
            StringType(),
            False,
        ),
        StructField(
            "document_version_id",
            StringType(),
            False,
        ),
        StructField(
            "chunking_strategy_version",
            StringType(),
            False,
        ),
        StructField(
            "source_type",
            StringType(),
            False,
        ),
        StructField(
            "source_system",
            StringType(),
            False,
        ),
        StructField(
            "configured_symbols",
            ArrayType(
                StringType(),
                containsNull=False,
            ),
            False,
        ),
        StructField(
            "title",
            StringType(),
            False,
        ),
        StructField(
            "evidence_date",
            DateType(),
            False,
        ),
        StructField(
            "source_url",
            StringType(),
            False,
        ),
        StructField(
            "section_code",
            StringType(),
            True,
        ),
        StructField(
            "section_title",
            StringType(),
            True,
        ),
        StructField(
            "chunk_index",
            IntegerType(),
            False,
        ),
        StructField(
            "character_start",
            LongType(),
            False,
        ),
        StructField(
            "character_end",
            LongType(),
            False,
        ),
        StructField(
            "chunk_text",
            StringType(),
            False,
        ),
        StructField(
            "chunk_text_sha256",
            StringType(),
            False,
        ),
        StructField(
            "source_response_id",
            StringType(),
            False,
        ),
        StructField(
            "source_fetched_at",
            TimestampType(),
            False,
        ),
        StructField(
            "source_ingestion_run_id",
            StringType(),
            False,
        ),
    ]
)


research_chunk_records = [
    (
        chunk.chunk_id,
        chunk.document_id,
        chunk.document_version_id,
        chunk.chunking_strategy_version,
        chunk.source_type,
        chunk.source_system,
        list(chunk.configured_symbols),
        chunk.title,
        chunk.evidence_date,
        chunk.source_url,
        chunk.section_code,
        chunk.section_title,
        chunk.chunk_index,
        chunk.character_start,
        chunk.character_end,
        chunk.chunk_text,
        chunk.chunk_text_sha256,
        chunk.source_response_id,
        chunk.source_fetched_at,
        chunk.source_ingestion_run_id,
    )
    for chunk in chunks_snapshot.chunks
]


research_chunks_dataframe = spark.createDataFrame(
    research_chunk_records,
    schema=research_chunks_schema,
)


# COMMAND ----------

documents_typed_count = (
    research_documents_dataframe.count()
)

if documents_typed_count != documents_snapshot.document_count:
    raise RuntimeError(
        "Typed research_documents row count differs from the "
        "deterministic document snapshot."
    )


chunks_typed_count = (
    research_chunks_dataframe.count()
)

if chunks_typed_count != chunks_snapshot.chunk_count:
    raise RuntimeError(
        "Typed research_chunks row count differs from the "
        "deterministic chunk snapshot."
    )


duplicate_document_ids = (
    research_documents_dataframe
    .groupBy(
        "document_id",
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

if duplicate_document_ids:
    raise RuntimeError(
        "research_documents document_id uniqueness validation failed."
    )


duplicate_document_version_ids = (
    research_documents_dataframe
    .groupBy(
        "document_version_id",
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

if duplicate_document_version_ids:
    raise RuntimeError(
        "research_documents document_version_id uniqueness validation failed."
    )


duplicate_chunk_ids = (
    research_chunks_dataframe
    .groupBy(
        "chunk_id",
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

if duplicate_chunk_ids:
    raise RuntimeError(
        "research_chunks chunk_id uniqueness validation failed."
    )


duplicate_chunk_versions = (
    research_chunks_dataframe
    .groupBy(
        "document_version_id",
        "chunking_strategy_version",
        "chunk_index",
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

if duplicate_chunk_versions:
    raise RuntimeError(
        "research_chunks document-version/index uniqueness validation failed."
    )


orphan_chunks = (
    research_chunks_dataframe.alias("chunk")
    .join(
        research_documents_dataframe
        .select(
            "document_id",
            "document_version_id",
        )
        .alias("document"),
        on=[
            col("chunk.document_id")
            == col("document.document_id"),
            col("chunk.document_version_id")
            == col("document.document_version_id"),
        ],
        how="left_anti",
    )
    .limit(1)
    .count()
)

if orphan_chunks:
    raise RuntimeError(
        "research_chunks contains a document/version without a matching "
        "research_documents row."
    )


required_document_columns = tuple(
    field.name
    for field in research_documents_schema.fields
    if not field.nullable
)

document_null_condition = None

for column_name in required_document_columns:
    current_condition = col(
        column_name
    ).isNull()

    document_null_condition = (
        current_condition
        if document_null_condition is None
        else document_null_condition | current_condition
    )

if (
    document_null_condition is not None
    and research_documents_dataframe
    .filter(document_null_condition)
    .limit(1)
    .count()
):
    raise RuntimeError(
        "research_documents contains a null required field."
    )


required_chunk_columns = tuple(
    field.name
    for field in research_chunks_schema.fields
    if not field.nullable
)

chunk_null_condition = None

for column_name in required_chunk_columns:
    current_condition = col(
        column_name
    ).isNull()

    chunk_null_condition = (
        current_condition
        if chunk_null_condition is None
        else chunk_null_condition | current_condition
    )

if (
    chunk_null_condition is not None
    and research_chunks_dataframe
    .filter(chunk_null_condition)
    .limit(1)
    .count()
):
    raise RuntimeError(
        "research_chunks contains a null required field."
    )


invalid_document_source = (
    research_documents_dataframe
    .filter(
        ~col("source_type").isin(
            "news",
            "filing",
        )
        | ~col("source_system").isin(
            "alpaca",
            "sec",
        )
    )
    .limit(1)
    .count()
)

if invalid_document_source:
    raise RuntimeError(
        "research_documents contains an unsupported source type/system."
    )


invalid_chunk_bounds = (
    research_chunks_dataframe
    .filter(
        (col("chunk_index") < 0)
        | (col("character_start") < 0)
        | (
            col("character_end")
            <= col("character_start")
        )
    )
    .limit(1)
    .count()
)

if invalid_chunk_bounds:
    raise RuntimeError(
        "research_chunks contains invalid chunk indexes or character bounds."
    )


# COMMAND ----------

documents_temporary_view = (
    "rag_research_documents_"
    + transformation_run_id.replace(
        "-",
        "_",
    )
)

chunks_temporary_view = (
    "rag_research_chunks_"
    + transformation_run_id.replace(
        "-",
        "_",
    )
)


research_documents_dataframe.createOrReplaceTempView(
    documents_temporary_view
)

research_chunks_dataframe.createOrReplaceTempView(
    chunks_temporary_view
)


try:
    spark.sql(
        f"""
        CREATE OR REPLACE TABLE
          {quoted_research_documents_table_name}
        USING DELTA
        COMMENT
          'Current deterministic RAG research-document versions'
        TBLPROPERTIES (
          'layer' = 'ai_retrieval',
          'dataset_role' = 'research_documents',
          'corpus_snapshot_id' = '{corpus_snapshot_id}'
        )
        AS
        SELECT *
        FROM `{documents_temporary_view}`
        """
    )

    spark.sql(
        f"""
        CREATE OR REPLACE TABLE
          {quoted_research_chunks_table_name}
        USING DELTA
        COMMENT
          'Current deterministic RAG retrieval chunks'
        TBLPROPERTIES (
          'layer' = 'ai_retrieval',
          'dataset_role' = 'research_chunks',
          'corpus_snapshot_id' = '{corpus_snapshot_id}',
          'chunking_strategy_version' =
            '{chunking_strategy.chunking_strategy_version}',
          'delta.enableChangeDataFeed' = 'true'
        )
        AS
        SELECT *
        FROM `{chunks_temporary_view}`
        """
    )
finally:
    spark.catalog.dropTempView(
        documents_temporary_view
    )
    spark.catalog.dropTempView(
        chunks_temporary_view
    )


# COMMAND ----------

published_document_count = spark.table(
    research_documents_table_name
).count()

published_chunk_count = spark.table(
    research_chunks_table_name
).count()


if published_document_count != documents_snapshot.document_count:
    raise RuntimeError(
        "Published research_documents count differs from the validated "
        "snapshot."
    )

if published_chunk_count != chunks_snapshot.chunk_count:
    raise RuntimeError(
        "Published research_chunks count differs from the validated snapshot."
    )


published_orphan_chunks = (
    spark.table(
        research_chunks_table_name
    )
    .alias("chunk")
    .join(
        spark.table(
            research_documents_table_name
        )
        .select(
            "document_id",
            "document_version_id",
        )
        .alias("document"),
        on=[
            col("chunk.document_id")
            == col("document.document_id"),
            col("chunk.document_version_id")
            == col("document.document_version_id"),
        ],
        how="left_anti",
    )
    .limit(1)
    .count()
)

if published_orphan_chunks:
    raise RuntimeError(
        "Published research_chunks contains an orphan document/version."
    )


print("RAG_RESEARCH_CORPUS_REFRESH=PASSED")
print(
    f"silver_news_table={silver_news_table_name}"
)
print(
    f"silver_filing_table={silver_filing_table_name}"
)
print(
    f"research_documents_table={research_documents_table_name}"
)
print(
    f"research_chunks_table={research_chunks_table_name}"
)
print(
    "configured_symbols="
    + ",".join(configured_symbols)
)
print(
    f"news_input_count={documents_snapshot.news_input_count}"
)
print(
    f"news_document_count={documents_snapshot.news_document_count}"
)
print(
    f"news_no_text_count={documents_snapshot.news_no_text_count}"
)
print(
    f"filing_input_count={documents_snapshot.filing_input_count}"
)
print(
    f"document_count={documents_snapshot.document_count}"
)
print(
    f"chunk_count={chunks_snapshot.chunk_count}"
)
print(
    "chunking_strategy_version="
    f"{chunking_strategy.chunking_strategy_version}"
)
print(
    f"corpus_snapshot_id={corpus_snapshot_id}"
)
print(
    f"transformation_run_id={transformation_run_id}"
)


dbutils.notebook.exit(  # type: ignore[name-defined]
    "RAG_RESEARCH_CORPUS_REFRESH=PASSED; "
    f"document_count={documents_snapshot.document_count}; "
    f"chunk_count={chunks_snapshot.chunk_count}; "
    f"corpus_snapshot_id={corpus_snapshot_id}; "
    "chunking_strategy_version="
    f"{chunking_strategy.chunking_strategy_version}; "
    f"transformation_run_id={transformation_run_id}"
)
