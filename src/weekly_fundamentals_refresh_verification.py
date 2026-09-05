# Databricks notebook source
"""Verify the published outputs of the weekly SEC/fundamentals refresh.

This notebook is the final operational gate for the scheduled fundamentals
DAG. It does not transform or publish data. It verifies source freshness,
configured-company coverage, snapshot uniqueness, business-data recency,
and Bronze-to-Silver-to-Gold lineage.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone

from equity_research.config import load_equities
from pyspark.sql import SparkSession, Window
from pyspark.sql.functions import (
    col,
    count,
    row_number,
)


IDENTIFIER_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*"
)

MAX_SOURCE_FETCH_AGE_HOURS = 36.0
MAX_FUNDAMENTAL_AS_OF_AGE_DAYS = 180
MAX_LATEST_10K_AGE_DAYS = 450

REQUIRED_FACT_CONCEPTS = {
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "NetIncomeLoss",
    "Assets",
}

REQUIRED_SECTION_CODES = {
    "item_1",
    "item_1a",
}


def _required_identifier(
    value: str,
    parameter: str,
) -> str:
    """Validate one Unity Catalog identifier."""

    normalized = value.strip()

    if not IDENTIFIER_PATTERN.fullmatch(
        normalized
    ):
        raise ValueError(
            f"Invalid {parameter} identifier: "
            f"{value!r}."
        )

    return normalized


def _as_utc_aware(
    value: datetime,
) -> datetime:
    """Interpret collected Spark timestamps as UTC."""

    if not isinstance(value, datetime):
        raise ValueError(
            "Expected a datetime value."
        )

    if (
        value.tzinfo is None
        or value.utcoffset() is None
    ):
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def _fetch_age_hours(
    fetched_at: datetime,
    now_utc: datetime,
) -> float:
    """Return source-fetch age in hours."""

    return (
        now_utc
        - _as_utc_aware(fetched_at)
    ).total_seconds() / 3600.0


def _date_age_days(
    value: date,
    today: date,
) -> int:
    """Return age of a business date in calendar days."""

    if (
        not isinstance(value, date)
        or isinstance(value, datetime)
    ):
        raise ValueError(
            "Expected a date value."
        )

    return (
        today - value
    ).days


# COMMAND ----------

dbutils.widgets.text(  # noqa: F821
    "catalog",
    "",
)

dbutils.widgets.text(  # noqa: F821
    "bronze_schema",
    "",
)

dbutils.widgets.text(  # noqa: F821
    "silver_schema",
    "",
)

dbutils.widgets.text(  # noqa: F821
    "gold_schema",
    "",
)


catalog = _required_identifier(
    dbutils.widgets.get("catalog"),  # noqa: F821
    "catalog",
)

bronze_schema_name = _required_identifier(
    dbutils.widgets.get(  # noqa: F821
        "bronze_schema"
    ),
    "bronze_schema",
)

silver_schema_name = _required_identifier(
    dbutils.widgets.get(  # noqa: F821
        "silver_schema"
    ),
    "silver_schema",
)

gold_schema_name = _required_identifier(
    dbutils.widgets.get(  # noqa: F821
        "gold_schema"
    ),
    "gold_schema",
)


bronze_company_facts_table = (
    f"{catalog}.{bronze_schema_name}."
    "company_facts_responses"
)

bronze_filings_table = (
    f"{catalog}.{bronze_schema_name}."
    "filing_documents"
)

silver_company_facts_table = (
    f"{catalog}.{silver_schema_name}."
    "company_facts"
)

silver_filing_sections_table = (
    f"{catalog}.{silver_schema_name}."
    "filing_sections"
)

gold_fundamentals_table = (
    f"{catalog}.{gold_schema_name}."
    "fundamental_metrics"
)


# COMMAND ----------

spark = SparkSession.builder.getOrCreate()

spark.conf.set(
    "spark.sql.session.timeZone",
    "UTC",
)

now_utc = datetime.now(
    timezone.utc
)

today_utc = now_utc.date()

equities = load_equities()

configured_companies = {
    equity.symbol: equity.sec_cik
    for equity in equities.values()
}

if not configured_companies:
    raise RuntimeError(
        "No configured companies are available "
        "for weekly fundamentals verification."
    )

configured_symbols = set(
    configured_companies
)

failures: list[str] = []


# COMMAND ----------
# Latest Bronze company-facts response per configured company.

latest_company_facts_window = (
    Window
    .partitionBy("project_symbol")
    .orderBy(
        col("fetched_at").desc(),
        col("source_response_id").desc(),
    )
)

latest_company_facts_rows = (
    spark.table(
        bronze_company_facts_table
    )
    .select(
        "project_symbol",
        "sec_cik",
        "source_response_id",
        "fetched_at",
        "ingestion_run_id",
    )
    .withColumn(
        "_row_number",
        row_number().over(
            latest_company_facts_window
        ),
    )
    .filter(
        col("_row_number") == 1
    )
    .drop("_row_number")
    .collect()
)

latest_company_facts = {
    row["project_symbol"]: row
    for row in latest_company_facts_rows
}

if set(latest_company_facts) != configured_symbols:
    failures.append(
        "Latest Bronze company-facts scope does not "
        "match configured companies."
    )

company_facts_run_ids: set[str] = set()

for symbol, expected_cik in configured_companies.items():
    row = latest_company_facts.get(
        symbol
    )

    if row is None:
        continue

    if row["sec_cik"] != expected_cik:
        failures.append(
            f"{symbol}: latest Bronze company-facts "
            "CIK does not match configuration."
        )

    fetch_age_hours = _fetch_age_hours(
        row["fetched_at"],
        now_utc,
    )

    if (
        fetch_age_hours < -0.25
        or fetch_age_hours
        > MAX_SOURCE_FETCH_AGE_HOURS
    ):
        failures.append(
            f"{symbol}: latest Bronze company-facts "
            f"fetch age is {fetch_age_hours:.2f} hours."
        )

    company_facts_run_ids.add(
        row["ingestion_run_id"]
    )

if len(company_facts_run_ids) != 1:
    failures.append(
        "Latest Bronze company-facts rows do not "
        "belong to one ingestion run."
    )


# COMMAND ----------
# Latest Bronze selected filing per configured company.

latest_filing_window = (
    Window
    .partitionBy("project_symbol")
    .orderBy(
        col("fetched_at").desc(),
        col("source_response_id").desc(),
    )
)

latest_filing_rows = (
    spark.table(
        bronze_filings_table
    )
    .select(
        "project_symbol",
        "sec_cik",
        "accession_number",
        "filing_form",
        "filing_date",
        "source_response_id",
        "response_sha256",
        "fetched_at",
        "ingestion_run_id",
    )
    .withColumn(
        "_row_number",
        row_number().over(
            latest_filing_window
        ),
    )
    .filter(
        col("_row_number") == 1
    )
    .drop("_row_number")
    .collect()
)

latest_filings = {
    row["project_symbol"]: row
    for row in latest_filing_rows
}

if set(latest_filings) != configured_symbols:
    failures.append(
        "Latest Bronze filing scope does not "
        "match configured companies."
    )

filing_run_ids: set[str] = set()

for symbol, expected_cik in configured_companies.items():
    row = latest_filings.get(
        symbol
    )

    if row is None:
        continue

    if row["sec_cik"] != expected_cik:
        failures.append(
            f"{symbol}: latest Bronze filing CIK "
            "does not match configuration."
        )

    if row["filing_form"] != "10-K":
        failures.append(
            f"{symbol}: latest selected Bronze filing "
            "is not a 10-K."
        )

    fetch_age_hours = _fetch_age_hours(
        row["fetched_at"],
        now_utc,
    )

    if (
        fetch_age_hours < -0.25
        or fetch_age_hours
        > MAX_SOURCE_FETCH_AGE_HOURS
    ):
        failures.append(
            f"{symbol}: latest Bronze filing fetch "
            f"age is {fetch_age_hours:.2f} hours."
        )

    filing_age_days = _date_age_days(
        row["filing_date"],
        today_utc,
    )

    if (
        filing_age_days < 0
        or filing_age_days
        > MAX_LATEST_10K_AGE_DAYS
    ):
        failures.append(
            f"{symbol}: latest selected 10-K filing "
            f"age is {filing_age_days} days."
        )

    filing_run_ids.add(
        row["ingestion_run_id"]
    )

if len(filing_run_ids) != 1:
    failures.append(
        "Latest Bronze filing rows do not "
        "belong to one ingestion run."
    )


# COMMAND ----------
# Silver company-facts snapshot and Bronze lineage.

silver_company_facts = spark.table(
    silver_company_facts_table
)

silver_fact_symbols = {
    row["project_symbol"]
    for row in (
        silver_company_facts
        .select("project_symbol")
        .distinct()
        .collect()
    )
}

if silver_fact_symbols != configured_symbols:
    failures.append(
        "Silver company-facts scope does not "
        "match configured companies."
    )

duplicate_fact_keys = (
    silver_company_facts
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
        count("*").alias(
            "row_count"
        )
    )
    .filter(
        col("row_count") != 1
    )
    .limit(1)
    .count()
)

if duplicate_fact_keys:
    failures.append(
        "Silver company-facts business-key "
        "uniqueness failed."
    )

silver_fact_row_count = (
    silver_company_facts.count()
)

for symbol in configured_symbols:
    symbol_facts = (
        silver_company_facts
        .filter(
            col("project_symbol")
            == symbol
        )
    )

    concepts = {
        row["concept"]
        for row in (
            symbol_facts
            .select("concept")
            .distinct()
            .collect()
        )
    }

    if concepts != REQUIRED_FACT_CONCEPTS:
        failures.append(
            f"{symbol}: Silver company-facts concept "
            "coverage is incomplete or out of scope."
        )

    provenance_rows = (
        symbol_facts
        .select(
            "source_response_id",
            "fetched_at",
            "ingestion_run_id",
        )
        .distinct()
        .collect()
    )

    if len(provenance_rows) != 1:
        failures.append(
            f"{symbol}: Silver company facts do not "
            "have exactly one source response."
        )
        continue

    latest_bronze = (
        latest_company_facts.get(
            symbol
        )
    )

    if latest_bronze is None:
        continue

    provenance = provenance_rows[0]

    if (
        provenance["source_response_id"]
        != latest_bronze["source_response_id"]
        or provenance["ingestion_run_id"]
        != latest_bronze["ingestion_run_id"]
        or _as_utc_aware(
            provenance["fetched_at"]
        )
        != _as_utc_aware(
            latest_bronze["fetched_at"]
        )
    ):
        failures.append(
            f"{symbol}: Silver company-facts lineage "
            "does not match latest Bronze."
        )


# COMMAND ----------
# Silver filing sections and Bronze lineage.

silver_filing_sections = spark.table(
    silver_filing_sections_table
)

silver_section_symbols = {
    row["project_symbol"]
    for row in (
        silver_filing_sections
        .select("project_symbol")
        .distinct()
        .collect()
    )
}

if silver_section_symbols != configured_symbols:
    failures.append(
        "Silver filing-section scope does not "
        "match configured companies."
    )

duplicate_section_keys = (
    silver_filing_sections
    .groupBy(
        "source_system",
        "cik",
        "accession_number",
        "section_code",
    )
    .agg(
        count("*").alias(
            "row_count"
        )
    )
    .filter(
        col("row_count") != 1
    )
    .limit(1)
    .count()
)

if duplicate_section_keys:
    failures.append(
        "Silver filing-section business-key "
        "uniqueness failed."
    )

silver_section_row_count = (
    silver_filing_sections.count()
)

expected_section_rows = (
    len(configured_symbols)
    * len(REQUIRED_SECTION_CODES)
)

if (
    silver_section_row_count
    != expected_section_rows
):
    failures.append(
        "Silver filing-section row count does not "
        "equal two sections per configured company."
    )

for symbol in configured_symbols:
    symbol_sections = (
        silver_filing_sections
        .filter(
            col("project_symbol")
            == symbol
        )
    )

    section_codes = {
        row["section_code"]
        for row in (
            symbol_sections
            .select("section_code")
            .distinct()
            .collect()
        )
    }

    if section_codes != REQUIRED_SECTION_CODES:
        failures.append(
            f"{symbol}: Silver filing sections are "
            "not exactly Item 1 and Item 1A."
        )

    provenance_rows = (
        symbol_sections
        .select(
            "accession_number",
            "source_response_id",
            "response_sha256",
            "fetched_at",
            "ingestion_run_id",
        )
        .distinct()
        .collect()
    )

    if len(provenance_rows) != 1:
        failures.append(
            f"{symbol}: Silver filing sections do "
            "not have exactly one filing provenance."
        )
        continue

    latest_bronze = latest_filings.get(
        symbol
    )

    if latest_bronze is None:
        continue

    provenance = provenance_rows[0]

    if (
        provenance["accession_number"]
        != latest_bronze["accession_number"]
        or provenance["source_response_id"]
        != latest_bronze["source_response_id"]
        or provenance["response_sha256"]
        != latest_bronze["response_sha256"]
        or provenance["ingestion_run_id"]
        != latest_bronze["ingestion_run_id"]
        or _as_utc_aware(
            provenance["fetched_at"]
        )
        != _as_utc_aware(
            latest_bronze["fetched_at"]
        )
    ):
        failures.append(
            f"{symbol}: Silver filing-section lineage "
            "does not match latest Bronze filing."
        )


# COMMAND ----------
# Gold fundamental metrics and Silver lineage.

gold_fundamentals = spark.table(
    gold_fundamentals_table
)

gold_rows = gold_fundamentals.collect()

if len(gold_rows) != len(
    configured_symbols
):
    failures.append(
        "Gold fundamental-metrics row count does "
        "not equal configured company count."
    )

gold_by_symbol = {
    row["symbol"]: row
    for row in gold_rows
}

if set(gold_by_symbol) != configured_symbols:
    failures.append(
        "Gold fundamental-metrics scope does not "
        "match configured companies."
    )

duplicate_gold_keys = (
    gold_fundamentals
    .groupBy(
        "symbol",
        "as_of_date",
    )
    .agg(
        count("*").alias(
            "row_count"
        )
    )
    .filter(
        col("row_count") != 1
    )
    .limit(1)
    .count()
)

if duplicate_gold_keys:
    failures.append(
        "Gold fundamental-metrics business-key "
        "uniqueness failed."
    )

for symbol, expected_cik in configured_companies.items():
    row = gold_by_symbol.get(
        symbol
    )

    if row is None:
        continue

    if row["cik"] != expected_cik:
        failures.append(
            f"{symbol}: Gold CIK does not match "
            "configuration."
        )

    if row["source_system"] != "sec":
        failures.append(
            f"{symbol}: Gold source_system is not SEC."
        )

    if row["latest_filing_form"] not in {
        "10-K",
        "10-Q",
    }:
        failures.append(
            f"{symbol}: Gold latest filing form is "
            "outside the supported scope."
        )

    if row["ttm_derivation_method"] not in {
        "annual",
        "annual_plus_ytd_minus_prior_ytd",
    }:
        failures.append(
            f"{symbol}: Gold TTM derivation method "
            "is outside the supported scope."
        )

    as_of_age_days = _date_age_days(
        row["as_of_date"],
        today_utc,
    )

    if (
        as_of_age_days < 0
        or as_of_age_days
        > MAX_FUNDAMENTAL_AS_OF_AGE_DAYS
    ):
        failures.append(
            f"{symbol}: Gold fundamental as-of age "
            f"is {as_of_age_days} days."
        )

    if (
        row["fundamental_period_end"]
        > row["as_of_date"]
    ):
        failures.append(
            f"{symbol}: Gold fundamental period ends "
            "after its as-of date."
        )

    symbol_facts = (
        silver_company_facts
        .filter(
            col("project_symbol")
            == symbol
        )
    )

    provenance_rows = (
        symbol_facts
        .select(
            "source_response_id",
            "fetched_at",
            "ingestion_run_id",
        )
        .distinct()
        .collect()
    )

    if len(provenance_rows) != 1:
        continue

    provenance = provenance_rows[0]

    if (
        row["latest_source_response_id"]
        != provenance["source_response_id"]
        or row["latest_source_ingestion_run_id"]
        != provenance["ingestion_run_id"]
        or _as_utc_aware(
            row["latest_source_fetched_at"]
        )
        != _as_utc_aware(
            provenance["fetched_at"]
        )
    ):
        failures.append(
            f"{symbol}: Gold lineage does not match "
            "current Silver company facts."
        )


# COMMAND ----------

if failures:
    failure_text = " | ".join(
        failures
    )

    raise RuntimeError(
        "WEEKLY_FUNDAMENTALS_REFRESH_VERIFICATION=FAILED; "
        + failure_text
    )


gold_as_of_dates = ",".join(
    (
        f"{symbol}:"
        f"{gold_by_symbol[symbol]['as_of_date']}"
    )
    for symbol in sorted(
        configured_symbols
    )
)

success_message = (
    "WEEKLY_FUNDAMENTALS_REFRESH_VERIFICATION=PASSED; "
    f"company_fact_rows={silver_fact_row_count}; "
    f"filing_section_rows={silver_section_row_count}; "
    f"gold_rows={len(gold_rows)}; "
    f"gold_as_of_dates={gold_as_of_dates}"
)

print(
    success_message
)

dbutils.notebook.exit(  # noqa: F821
    success_message
)
