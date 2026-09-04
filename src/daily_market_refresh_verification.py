# Databricks notebook source
"""Verify the published outputs of the daily market/news refresh.

This notebook is the final operational gate for the scheduled daily DAG.
It does not transform or publish data. It reads the completed Bronze,
Silver, and Gold outputs and fails the parent job when freshness, scope,
coverage, uniqueness, or lineage invariants are violated.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from equity_research.config import load_equities
from pyspark.sql import SparkSession
from pyspark.sql.functions import (
    col,
    count as spark_count,
    max as spark_max,
)


IDENTIFIER_PATTERN = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*"
)

NEW_YORK_TIMEZONE = ZoneInfo(
    "America/New_York"
)

MAX_SOURCE_FETCH_AGE_HOURS = 36.0
MAX_COMPLETED_MARKET_DATE_LAG_DAYS = 4
MIN_PRICE_OBSERVATIONS = 61


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


bronze_price_table = (
    f"{catalog}.{bronze_schema_name}."
    "price_responses"
)

bronze_news_table = (
    f"{catalog}.{bronze_schema_name}."
    "news_responses"
)

silver_price_table = (
    f"{catalog}.{silver_schema_name}."
    "daily_prices"
)

silver_news_table = (
    f"{catalog}.{silver_schema_name}."
    "news_articles"
)

gold_market_table = (
    f"{catalog}.{gold_schema_name}."
    "market_metrics"
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

market_date = now_utc.astimezone(
    NEW_YORK_TIMEZONE
).date()

equities = load_equities()

configured_symbols = {
    equity.alpaca_symbol
    for equity in equities.values()
}

if not configured_symbols:
    raise RuntimeError(
        "No configured equities are available "
        "for daily refresh verification."
    )

failures: list[str] = []


# COMMAND ----------
# Bronze source freshness

price_fetch_row = (
    spark.table(
        bronze_price_table
    )
    .agg(
        spark_max(
            "fetched_at"
        ).alias(
            "latest_fetched_at"
        )
    )
    .collect()[0]
)

latest_bronze_price_fetch = (
    price_fetch_row[
        "latest_fetched_at"
    ]
)

if latest_bronze_price_fetch is None:
    failures.append(
        "Bronze price history has no "
        "fetched_at value."
    )
else:
    price_fetch_age_hours = (
        _fetch_age_hours(
            latest_bronze_price_fetch,
            now_utc,
        )
    )

    if (
        price_fetch_age_hours < -0.25
        or price_fetch_age_hours
        > MAX_SOURCE_FETCH_AGE_HOURS
    ):
        failures.append(
            "Bronze price source freshness "
            "check failed: "
            f"age_hours="
            f"{price_fetch_age_hours:.2f}."
        )


news_fetch_row = (
    spark.table(
        bronze_news_table
    )
    .agg(
        spark_max(
            "fetched_at"
        ).alias(
            "latest_fetched_at"
        )
    )
    .collect()[0]
)

latest_bronze_news_fetch = (
    news_fetch_row[
        "latest_fetched_at"
    ]
)

if latest_bronze_news_fetch is None:
    failures.append(
        "Bronze news history has no "
        "fetched_at value."
    )
else:
    news_fetch_age_hours = (
        _fetch_age_hours(
            latest_bronze_news_fetch,
            now_utc,
        )
    )

    if (
        news_fetch_age_hours < -0.25
        or news_fetch_age_hours
        > MAX_SOURCE_FETCH_AGE_HOURS
    ):
        failures.append(
            "Bronze news source freshness "
            "check failed: "
            f"age_hours="
            f"{news_fetch_age_hours:.2f}."
        )


# COMMAND ----------
# Silver daily-price validation

price_df = spark.table(
    silver_price_table
)

price_row_count = price_df.count()

if price_row_count == 0:
    failures.append(
        "Silver daily_prices is empty."
    )

silver_price_symbols = {
    row["symbol"]
    for row in (
        price_df
        .select(
            "symbol"
        )
        .distinct()
        .collect()
    )
}

if (
    silver_price_symbols
    != configured_symbols
):
    failures.append(
        "Silver daily_prices symbol scope "
        "does not exactly match configured "
        "equities."
    )


duplicate_price_keys = (
    price_df
    .groupBy(
        "symbol",
        "bar_timestamp",
        "feed",
        "adjustment",
    )
    .agg(
        spark_count(
            "*"
        ).alias(
            "key_count"
        )
    )
    .filter(
        col(
            "key_count"
        ) != 1
    )
    .limit(1)
    .count()
)

if duplicate_price_keys:
    failures.append(
        "Silver daily_prices contains "
        "duplicate business keys."
    )


price_counts = {
    row["symbol"]: row[
        "observation_count"
    ]
    for row in (
        price_df
        .groupBy(
            "symbol"
        )
        .agg(
            spark_count(
                "*"
            ).alias(
                "observation_count"
            )
        )
        .collect()
    )
}

for symbol in configured_symbols:
    if (
        price_counts.get(
            symbol,
            0,
        )
        < MIN_PRICE_OBSERVATIONS
    ):
        failures.append(
            f"{symbol}: fewer than "
            f"{MIN_PRICE_OBSERVATIONS} "
            "Silver price observations."
        )


latest_price_dates_by_symbol = {
    row["symbol"]: row[
        "latest_trading_date"
    ]
    for row in (
        price_df
        .groupBy(
            "symbol"
        )
        .agg(
            spark_max(
                "trading_date"
            ).alias(
                "latest_trading_date"
            )
        )
        .collect()
    )
}

latest_price_dates = set(
    latest_price_dates_by_symbol.values()
)

common_price_date = None

if (
    len(latest_price_dates) != 1
    or None in latest_price_dates
):
    failures.append(
        "Silver daily_prices does not have "
        "one common latest trading date."
    )
else:
    common_price_date = next(
        iter(
            latest_price_dates
        )
    )

    market_date_lag_days = (
        market_date
        - common_price_date
    ).days

    if not (
        1
        <= market_date_lag_days
        <= MAX_COMPLETED_MARKET_DATE_LAG_DAYS
    ):
        failures.append(
            "Silver latest completed market "
            "date freshness failed: "
            f"market_date={market_date}, "
            f"latest_trading_date="
            f"{common_price_date}, "
            f"lag_days="
            f"{market_date_lag_days}."
        )


latest_silver_price_fetch = (
    price_df
    .agg(
        spark_max(
            "fetched_at"
        ).alias(
            "latest_fetched_at"
        )
    )
    .collect()[0][
        "latest_fetched_at"
    ]
)

if (
    latest_bronze_price_fetch
    is not None
    and latest_silver_price_fetch
    is not None
    and _as_utc_aware(
        latest_silver_price_fetch
    )
    != _as_utc_aware(
        latest_bronze_price_fetch
    )
):
    failures.append(
        "Silver daily_prices does not "
        "incorporate the latest Bronze "
        "price fetch."
    )


# COMMAND ----------
# Silver news validation

news_df = spark.table(
    silver_news_table
)

news_row_count = news_df.count()

if news_row_count == 0:
    failures.append(
        "Silver news_articles is empty."
    )


duplicate_news_keys = (
    news_df
    .groupBy(
        "source_system",
        "article_id",
    )
    .agg(
        spark_count(
            "*"
        ).alias(
            "key_count"
        )
    )
    .filter(
        col(
            "key_count"
        ) != 1
    )
    .limit(1)
    .count()
)

if duplicate_news_keys:
    failures.append(
        "Silver news_articles contains "
        "duplicate business keys."
    )


news_symbol_coverage: set[str] = set()

for row in (
    news_df
    .select(
        "configured_symbols"
    )
    .collect()
):
    row_symbols = set(
        row[
            "configured_symbols"
        ]
        or []
    )

    if not row_symbols:
        failures.append(
            "Silver news article has no "
            "configured-symbol scope."
        )
        break

    if not row_symbols.issubset(
        configured_symbols
    ):
        failures.append(
            "Silver news article contains "
            "an out-of-scope configured "
            "symbol."
        )
        break

    news_symbol_coverage.update(
        row_symbols
    )

if (
    news_symbol_coverage
    != configured_symbols
):
    failures.append(
        "Silver news snapshot does not "
        "cover every configured equity."
    )


latest_silver_news_fetch = (
    news_df
    .agg(
        spark_max(
            "fetched_at"
        ).alias(
            "latest_fetched_at"
        )
    )
    .collect()[0][
        "latest_fetched_at"
    ]
)

if (
    latest_bronze_news_fetch
    is not None
    and latest_silver_news_fetch
    is not None
    and _as_utc_aware(
        latest_silver_news_fetch
    )
    != _as_utc_aware(
        latest_bronze_news_fetch
    )
):
    failures.append(
        "Silver news_articles does not "
        "incorporate the latest Bronze "
        "news fetch."
    )


latest_article_created_at = (
    news_df
    .agg(
        spark_max(
            "article_created_at"
        ).alias(
            "latest_article_created_at"
        )
    )
    .collect()[0][
        "latest_article_created_at"
    ]
)


# COMMAND ----------
# Gold market-metrics validation

gold_df = spark.table(
    gold_market_table
)

gold_rows = gold_df.collect()

if len(gold_rows) != len(
    configured_symbols
):
    failures.append(
        "Gold market_metrics does not "
        "contain exactly one row per "
        "configured equity."
    )


gold_symbols = {
    row["symbol"]
    for row in gold_rows
}

if gold_symbols != configured_symbols:
    failures.append(
        "Gold market_metrics symbol scope "
        "does not exactly match configured "
        "equities."
    )


gold_as_of_dates = {
    row["as_of_date"]
    for row in gold_rows
}

if (
    len(gold_as_of_dates) != 1
    or None in gold_as_of_dates
):
    failures.append(
        "Gold market_metrics does not "
        "share one common as_of_date."
    )
else:
    gold_as_of_date = next(
        iter(
            gold_as_of_dates
        )
    )

    if (
        common_price_date is not None
        and gold_as_of_date
        != common_price_date
    ):
        failures.append(
            "Gold market_metrics as_of_date "
            "does not match the latest "
            "common Silver trading date."
        )


for row in gold_rows:
    if (
        row[
            "observations_available"
        ]
        < MIN_PRICE_OBSERVATIONS
    ):
        failures.append(
            f"{row['symbol']}: Gold market "
            "metrics has insufficient "
            "price observations."
        )


if common_price_date is not None:
    latest_silver_rows = (
        price_df
        .filter(
            col(
                "trading_date"
            )
            == common_price_date
        )
        .select(
            "symbol",
            "source_response_id",
            "fetched_at",
            "ingestion_run_id",
        )
        .collect()
    )

    latest_silver_by_symbol = {
        row["symbol"]: row
        for row in latest_silver_rows
    }

    if (
        set(
            latest_silver_by_symbol
        )
        != configured_symbols
    ):
        failures.append(
            "Latest Silver price date does "
            "not contain exactly one row "
            "per configured equity."
        )
    else:
        for gold_row in gold_rows:
            symbol = gold_row[
                "symbol"
            ]

            silver_row = (
                latest_silver_by_symbol[
                    symbol
                ]
            )

            if (
                gold_row[
                    "latest_source_response_id"
                ]
                != silver_row[
                    "source_response_id"
                ]
                or gold_row[
                    "latest_source_ingestion_run_id"
                ]
                != silver_row[
                    "ingestion_run_id"
                ]
                or _as_utc_aware(
                    gold_row[
                        "latest_source_fetched_at"
                    ]
                )
                != _as_utc_aware(
                    silver_row[
                        "fetched_at"
                    ]
                )
            ):
                failures.append(
                    f"{symbol}: Gold latest "
                    "price provenance does "
                    "not match Silver."
                )


# COMMAND ----------
# Final operational gate

if failures:
    raise RuntimeError(
        "DAILY_MARKET_REFRESH_VERIFICATION="
        "FAILED; "
        + " | ".join(
            failures
        )
    )


print(
    "DAILY_MARKET_REFRESH_VERIFICATION=PASSED"
)

print(
    f"configured_symbols="
    f"{sorted(configured_symbols)}"
)

print(
    f"price_row_count="
    f"{price_row_count}"
)

print(
    f"common_price_date="
    f"{common_price_date}"
)

print(
    f"latest_bronze_price_fetch="
    f"{_as_utc_aware(latest_bronze_price_fetch)}"
)

print(
    f"news_row_count="
    f"{news_row_count}"
)

print(
    f"latest_article_created_at="
    f"{latest_article_created_at}"
)

print(
    f"latest_bronze_news_fetch="
    f"{_as_utc_aware(latest_bronze_news_fetch)}"
)

print(
    f"gold_row_count="
    f"{len(gold_rows)}"
)


dbutils.notebook.exit(  # noqa: F821
    "DAILY_MARKET_REFRESH_VERIFICATION="
    "PASSED; "
    f"price_rows={price_row_count}; "
    f"price_as_of_date={common_price_date}; "
    f"news_rows={news_row_count}; "
    f"gold_rows={len(gold_rows)}"
)
