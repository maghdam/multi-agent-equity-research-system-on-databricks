# Databricks notebook source
"""Retrieve bounded Alpaca news pages and append raw envelopes to Bronze."""

import hashlib
import json
import re
from datetime import datetime, timezone
from http.client import HTTPSConnection
from time import sleep
from urllib.parse import urlencode
from uuid import uuid4

from equity_research.alpaca_http import (
    MAX_REQUEST_ATTEMPTS,
    calculate_retry_delay,
    is_retryable_http_status,
)
from equity_research.alpaca_news import (
    DEFAULT_NEWS_INCREMENTAL_LOOKBACK_DAYS,
    MAX_NEWS_PAGE_LIMIT,
    NewsPageCursor,
    advance_news_page,
    build_news_request_parameters,
    parse_news_response_page,
    resolve_news_request_window,
)
from equity_research.config import load_equities
from pyspark.sql import SparkSession
from pyspark.sql.functions import col
from pyspark.sql.types import (
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)


ALPACA_HOST = "data.alpaca.markets"
ALPACA_PATH = "/v1beta1/news"
IDENTIFIER_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _required_identifier(value: str, parameter: str) -> str:
    """Validate a Unity Catalog identifier supplied by bundle configuration."""

    normalized = value.strip()

    if not IDENTIFIER_PATTERN.fullmatch(normalized):
        raise ValueError(f"Invalid {parameter} identifier: {value!r}.")

    return normalized


def _request_alpaca_page(
    query: str,
    api_key: str,
    api_secret: str,
) -> tuple[int, bytes, datetime]:
    """Retrieve one news page with bounded retries."""

    for attempt_number in range(1, MAX_REQUEST_ATTEMPTS + 1):
        connection = HTTPSConnection(ALPACA_HOST, timeout=30)

        try:
            connection.request(
                "GET",
                f"{ALPACA_PATH}?{query}",
                headers={
                    "APCA-API-KEY-ID": api_key,
                    "APCA-API-SECRET-KEY": api_secret,
                    "Accept": "application/json",
                },
            )

            response = connection.getresponse()
            status = response.status
            retry_after_header = response.getheader("Retry-After")
            response_body = response.read()
            fetched_at = datetime.now(timezone.utc)

        except OSError as exc:
            if attempt_number == MAX_REQUEST_ATTEMPTS:
                raise RuntimeError(
                    "Alpaca news request failed after bounded network retries."
                ) from exc

            delay_seconds = calculate_retry_delay(attempt_number)

            print(
                "ALPACA_RETRY_SCHEDULED; "
                "source=news; reason=network; "
                f"attempt={attempt_number}; "
                f"delay_seconds={delay_seconds:g}"
            )

            sleep(delay_seconds)
            continue

        finally:
            connection.close()

        if status == 200:
            return status, response_body, fetched_at

        should_retry = is_retryable_http_status(status)

        if not should_retry or attempt_number == MAX_REQUEST_ATTEMPTS:
            raise RuntimeError(
                f"Alpaca news returned HTTP {status}; "
                "response is not printed."
            )

        delay_seconds = calculate_retry_delay(
            attempt_number,
            retry_after_header,
        )

        print(
            "ALPACA_RETRY_SCHEDULED; "
            f"source=news; reason=http_{status}; "
            f"attempt={attempt_number}; "
            f"delay_seconds={delay_seconds:g}"
        )

        sleep(delay_seconds)

    raise RuntimeError("Alpaca news retry loop ended unexpectedly.")


dbutils.widgets.text("catalog", "")  # type: ignore[name-defined]
dbutils.widgets.text("bronze_schema", "")  # type: ignore[name-defined]
dbutils.widgets.text("secret_scope", "")  # type: ignore[name-defined]
dbutils.widgets.text("load_mode", "backfill")  # type: ignore[name-defined]
dbutils.widgets.text("start", "")  # type: ignore[name-defined]
dbutils.widgets.text("end", "")  # type: ignore[name-defined]
dbutils.widgets.text(  # type: ignore[name-defined]
    "lookback_days",
    str(DEFAULT_NEWS_INCREMENTAL_LOOKBACK_DAYS),
)
dbutils.widgets.text(  # type: ignore[name-defined]
    "page_limit",
    str(MAX_NEWS_PAGE_LIMIT),
)


catalog = _required_identifier(
    dbutils.widgets.get("catalog"),  # type: ignore[name-defined]
    "catalog",
)

bronze_schema_name = _required_identifier(
    dbutils.widgets.get("bronze_schema"),  # type: ignore[name-defined]
    "bronze_schema",
)

secret_scope = dbutils.widgets.get("secret_scope").strip()  # type: ignore[name-defined]
load_mode = dbutils.widgets.get("load_mode").strip()  # type: ignore[name-defined]
start = dbutils.widgets.get("start").strip()  # type: ignore[name-defined]
end = dbutils.widgets.get("end").strip()  # type: ignore[name-defined]
lookback_days_text = dbutils.widgets.get("lookback_days").strip()  # type: ignore[name-defined]
page_limit_text = dbutils.widgets.get("page_limit").strip()  # type: ignore[name-defined]


if (
    not secret_scope
    or not load_mode
    or not lookback_days_text
    or not page_limit_text
):
    raise ValueError(
        "secret_scope, load_mode, lookback_days, and page_limit are required."
    )


try:
    lookback_days = int(lookback_days_text)
    page_limit = int(page_limit_text)
except ValueError as exc:
    raise ValueError(
        "lookback_days and page_limit must be integers."
    ) from exc


if not 1 <= page_limit <= MAX_NEWS_PAGE_LIMIT:
    raise ValueError(
        f"page_limit must be from 1 to {MAX_NEWS_PAGE_LIMIT}."
    )


request_window = resolve_news_request_window(
    load_mode,
    start,
    end,
    lookback_days=lookback_days,
)


equities = load_equities()
symbols = [equity.alpaca_symbol for equity in equities.values()]


api_key = dbutils.secrets.get(  # type: ignore[name-defined]
    scope=secret_scope,
    key="alpaca-api-key",
)

api_secret = dbutils.secrets.get(  # type: ignore[name-defined]
    scope=secret_scope,
    key="alpaca-secret-key",
)


ingestion_run_id = str(uuid4())

table_name = f"{catalog}.{bronze_schema_name}.news_responses"

quoted_table_name = ".".join(
    f"`{identifier}`"
    for identifier in (
        catalog,
        bronze_schema_name,
        "news_responses",
    )
)


spark = SparkSession.builder.getOrCreate()

spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {quoted_table_name} (
      source_response_id STRING NOT NULL,
      source_system STRING NOT NULL,
      source_endpoint STRING NOT NULL,
      request_parameters_json STRING NOT NULL,
      request_page_token STRING,
      response_next_page_token STRING,
      page_number INT NOT NULL,
      http_status INT NOT NULL,
      response_payload_json STRING NOT NULL,
      response_bytes BIGINT NOT NULL,
      response_sha256 STRING NOT NULL,
      records_received BIGINT NOT NULL,
      fetched_at TIMESTAMP NOT NULL,
      ingestion_run_id STRING NOT NULL
    )
    USING DELTA
    COMMENT 'Raw Alpaca company-news response pages and retrieval provenance'
    TBLPROPERTIES (
      'quality' = 'bronze',
      'source_system' = 'alpaca'
    )
    """
)


bronze_table_schema = StructType(
    [
        StructField("source_response_id", StringType(), False),
        StructField("source_system", StringType(), False),
        StructField("source_endpoint", StringType(), False),
        StructField("request_parameters_json", StringType(), False),
        StructField("request_page_token", StringType(), True),
        StructField("response_next_page_token", StringType(), True),
        StructField("page_number", IntegerType(), False),
        StructField("http_status", IntegerType(), False),
        StructField("response_payload_json", StringType(), False),
        StructField("response_bytes", LongType(), False),
        StructField("response_sha256", StringType(), False),
        StructField("records_received", LongType(), False),
        StructField("fetched_at", TimestampType(), False),
        StructField("ingestion_run_id", StringType(), False),
    ]
)


cursor: NewsPageCursor | None = NewsPageCursor()
bronze_records: list[tuple[object, ...]] = []
articles_received = 0


while cursor is not None:
    request_parameters = build_news_request_parameters(
        symbols,
        request_window.start,
        request_window.end,
        page_token=cursor.page_token,
        limit=page_limit,
    )

    query = urlencode(request_parameters)

    status, response_body, fetched_at = _request_alpaca_page(
        query,
        api_key,
        api_secret,
    )

    try:
        response_text = response_body.decode("utf-8")
        payload = json.loads(response_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            "Alpaca returned an invalid JSON news response."
        ) from exc

    try:
        response_page = parse_news_response_page(payload)
    except ValueError as exc:
        raise RuntimeError(
            "Alpaca returned an invalid news-response page."
        ) from exc

    next_cursor = advance_news_page(
        cursor,
        response_page.next_page_token,
    )

    articles_received += response_page.record_count

    bronze_records.append(
        (
            str(uuid4()),
            "alpaca",
            f"https://{ALPACA_HOST}{ALPACA_PATH}",
            json.dumps(
                request_parameters,
                sort_keys=True,
                separators=(",", ":"),
            ),
            cursor.page_token,
            response_page.next_page_token,
            cursor.page_number,
            status,
            response_text,
            len(response_body),
            hashlib.sha256(response_body).hexdigest(),
            response_page.record_count,
            fetched_at,
            ingestion_run_id,
        )
    )

    cursor = next_cursor


rows_appended = len(bronze_records)


spark.createDataFrame(
    bronze_records,
    schema=bronze_table_schema,
).write.format("delta").mode("append").saveAsTable(table_name)


written_rows = (
    spark.table(table_name)
    .filter(col("ingestion_run_id") == ingestion_run_id)
    .count()
)


if written_rows != rows_appended:
    raise RuntimeError(
        f"Expected {rows_appended} persisted Bronze news responses, "
        f"found {written_rows}."
    )


print("BRONZE_NEWS_APPEND=PASSED")
print(f"bronze_table={table_name}")
print(f"load_mode={request_window.load_mode}")
print(f"request_start={request_window.start}")
print(f"request_end={request_window.end}")
print(f"configured_symbols={symbols}")
print(f"articles_received={articles_received}")
print(f"pages_retrieved={rows_appended}")
print(f"ingestion_run_id={ingestion_run_id}")
print(f"rows_appended={rows_appended}")


dbutils.notebook.exit(  # type: ignore[name-defined]
    "BRONZE_NEWS_APPEND=PASSED; "
    f"bronze_table={table_name}; "
    f"rows_appended={rows_appended}; "
    f"articles_received={articles_received}; "
    f"ingestion_run_id={ingestion_run_id}"
)