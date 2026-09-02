# Databricks notebook source
"""Append raw SEC company-facts responses to the Bronze layer."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from http.client import HTTPSConnection
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4


# Make repository source modules importable in Databricks.
PROJECT_ROOT = Path.cwd()
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.config import load_equities
from equity_research.sec_company_facts import (
    SEC_DATA_HOST,
    build_company_facts_path,
    parse_company_facts_response,
)
from equity_research.sec_http import (
    MAX_SEC_REQUEST_ATTEMPTS,
    build_sec_request_headers,
    calculate_sec_retry_delay,
    calculate_sec_spacing_delay,
    is_retryable_sec_http_status,
)


REQUEST_TIMEOUT_SECONDS = 30
SOURCE_SYSTEM = "sec"
SOURCE_ENDPOINT = "companyfacts"


def _required_identifier(value: str, field_name: str) -> str:
    """Validate a SQL identifier supplied by bundle configuration."""

    normalized = value.strip()

    if not normalized:
        raise ValueError(f"{field_name} must be nonblank.")

    if not normalized.replace("_", "").isalnum():
        raise ValueError(
            f"{field_name} must contain only letters, digits, or underscores."
        )

    return normalized


def _request_sec_company_facts(
    path: str,
    headers: dict[str, str],
) -> tuple[int, str, bytes]:
    """Fetch one SEC company-facts response using bounded retries."""

    for attempt_number in range(1, MAX_SEC_REQUEST_ATTEMPTS + 1):
        connection = HTTPSConnection(
            SEC_DATA_HOST,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        try:
            connection.request(
                "GET",
                path,
                headers=headers,
            )

            response = connection.getresponse()
            response_bytes = response.read()
            response_text = response_bytes.decode("utf-8")

            if response.status == 200:
                return (
                    response.status,
                    response_text,
                    response_bytes,
                )

            if (
                not is_retryable_sec_http_status(response.status)
                or attempt_number == MAX_SEC_REQUEST_ATTEMPTS
            ):
                raise RuntimeError(
                    "SEC company-facts request failed with "
                    f"HTTP status {response.status}."
                )

            retry_after = response.getheader("Retry-After")
            delay_seconds = calculate_sec_retry_delay(
                attempt_number,
                retry_after,
            )
            sleep(delay_seconds)

        finally:
            connection.close()

    raise RuntimeError("SEC company-facts request exhausted retries.")


# COMMAND ----------

dbutils.widgets.text("catalog", "")
dbutils.widgets.text("bronze_schema", "")
dbutils.widgets.text("secret_scope", "")

catalog = _required_identifier(
    dbutils.widgets.get("catalog"),
    "catalog",
)

bronze_schema = _required_identifier(
    dbutils.widgets.get("bronze_schema"),
    "bronze_schema",
)

secret_scope = dbutils.widgets.get("secret_scope").strip()

if not secret_scope:
    raise ValueError("secret_scope must be nonblank.")

table_name = f"{catalog}.{bronze_schema}.company_facts_responses"

# COMMAND ----------

equities = load_equities()

if not equities:
    raise RuntimeError("No configured equities were found.")

user_agent = dbutils.secrets.get(
    scope=secret_scope,
    key="sec-user-agent",
).strip()

headers = build_sec_request_headers(user_agent)

ingestion_run_id = str(uuid4())
response_rows: list[dict[str, object]] = []

previous_request_started_at: float | None = None

for project_symbol, equity in equities.items():
    if previous_request_started_at is not None:
        elapsed_seconds = monotonic() - previous_request_started_at
        spacing_delay = calculate_sec_spacing_delay(elapsed_seconds)

        if spacing_delay > 0:
            sleep(spacing_delay)

    sec_cik = equity.sec_cik
    request_path = build_company_facts_path(sec_cik)

    previous_request_started_at = monotonic()

    http_status, response_text, response_bytes = (
        _request_sec_company_facts(
            request_path,
            headers,
        )
    )

    try:
        payload = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{project_symbol}: SEC response was not valid JSON."
        ) from exc

    parsed = parse_company_facts_response(payload)

    if parsed.cik != int(sec_cik):
        raise RuntimeError(
            f"{project_symbol}: SEC response CIK "
            f"{parsed.cik} does not match configured CIK {sec_cik}."
        )

    fetched_at = datetime.now(timezone.utc)

    response_sha256 = hashlib.sha256(response_bytes).hexdigest()

    source_response_id = str(uuid4())

    request_parameters_json = json.dumps(
        {
            "project_symbol": project_symbol,
            "sec_cik": sec_cik,
            "path": request_path,
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    response_rows.append(
        {
            "source_response_id": source_response_id,
            "source_system": SOURCE_SYSTEM,
            "source_endpoint": SOURCE_ENDPOINT,
            "project_symbol": project_symbol,
            "sec_cik": sec_cik,
            "entity_name": parsed.entity_name,
            "request_parameters_json": request_parameters_json,
            "http_status": http_status,
            "response_payload_json": response_text,
            "response_bytes": len(response_bytes),
            "response_sha256": response_sha256,
            "fetched_at": fetched_at,
            "ingestion_run_id": ingestion_run_id,
        }
    )

# COMMAND ----------

spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        source_response_id STRING NOT NULL,
        source_system STRING NOT NULL,
        source_endpoint STRING NOT NULL,
        project_symbol STRING NOT NULL,
        sec_cik STRING NOT NULL,
        entity_name STRING NOT NULL,
        request_parameters_json STRING NOT NULL,
        http_status INT NOT NULL,
        response_payload_json STRING NOT NULL,
        response_bytes BIGINT NOT NULL,
        response_sha256 STRING NOT NULL,
        fetched_at TIMESTAMP NOT NULL,
        ingestion_run_id STRING NOT NULL
    )
    USING DELTA
    COMMENT 'Raw SEC company-facts response snapshots with ingestion provenance'
    TBLPROPERTIES (
        'quality' = 'bronze',
        'source_system' = 'sec'
    )
    """
)

# COMMAND ----------

if len(response_rows) != len(equities):
    raise RuntimeError(
        "SEC company-facts retrieval did not produce exactly one "
        "response per configured equity."
    )

response_df = spark.createDataFrame(response_rows)

response_df.write.mode("append").saveAsTable(table_name)

# COMMAND ----------

persisted_rows = spark.sql(
    f"""
    SELECT COUNT(*) AS row_count
    FROM {table_name}
    WHERE ingestion_run_id = '{ingestion_run_id}'
    """
).collect()[0]["row_count"]

expected_rows = len(response_rows)

if persisted_rows != expected_rows:
    raise RuntimeError(
        "Persisted Bronze company-facts row count does not match "
        f"the current ingestion run: expected={expected_rows}, "
        f"actual={persisted_rows}."
    )

print(
    "Bronze SEC company-facts append verified: "
    f"rows_appended={persisted_rows}, "
    f"ingestion_run_id={ingestion_run_id}"
)

dbutils.notebook.exit("BRONZE_COMPANY_FACTS_APPEND=PASSED")
