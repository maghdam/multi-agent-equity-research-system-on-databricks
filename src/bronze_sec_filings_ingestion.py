# Databricks notebook source
"""Append selected SEC 10-K primary documents to the Bronze layer."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
import requests
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4


# Make repository source modules importable in Databricks.
PROJECT_ROOT = Path.cwd()
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from equity_research.config import load_equities
from equity_research.sec_filings import (
    build_filing_document_path,
    build_submissions_path,
    parse_recent_10k_filings,
    select_latest_10k,
)
from equity_research.sec_http import (
    MAX_SEC_REQUEST_ATTEMPTS,
    build_sec_html_request_headers,
    build_sec_request_headers,
    calculate_sec_retry_delay,
    calculate_sec_spacing_delay,
    is_retryable_sec_http_status,
)


SEC_DATA_HOST = "data.sec.gov"
SEC_ARCHIVES_HOST = "www.sec.gov"

REQUEST_TIMEOUT_SECONDS = 30

SOURCE_SYSTEM = "sec"
SOURCE_ENDPOINT = "filing_document"

ALLOWED_HTML_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
}


def _required_identifier(
    value: str,
    field_name: str,
) -> str:
    """Validate a SQL identifier supplied by bundle configuration."""

    normalized = value.strip()

    if not normalized:
        raise ValueError(
            f"{field_name} must be nonblank."
        )

    if not normalized.replace("_", "").isalnum():
        raise ValueError(
            f"{field_name} must contain only letters, digits, "
            "or underscores."
        )

    return normalized


def _request_sec(
    host: str,
    path: str,
    headers: dict[str, str],
) -> tuple[int, dict[str, str], bytes]:
    """Fetch one SEC resource using bounded retries."""

    url = f"https://{host}{path}"

    for attempt_number in range(
        1,
        MAX_SEC_REQUEST_ATTEMPTS + 1,
    ):
        try:
            response = requests.get(
                url,
                headers=headers,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            if (
                attempt_number
                == MAX_SEC_REQUEST_ATTEMPTS
            ):
                raise RuntimeError(
                    "SEC request failed after bounded "
                    f"network retries: host={host}, "
                    f"path={path}"
                ) from exc

            delay_seconds = calculate_sec_retry_delay(
                attempt_number
            )

            sleep(delay_seconds)
            continue

        response_headers = {
            key.lower(): value
            for key, value
            in response.headers.items()
        }

        if response.status_code == 200:
            return (
                response.status_code,
                response_headers,
                response.content,
            )

        if (
            not is_retryable_sec_http_status(
                response.status_code
            )
            or attempt_number
            == MAX_SEC_REQUEST_ATTEMPTS
        ):
            raise RuntimeError(
                "SEC request failed with "
                f"HTTP status {response.status_code}: "
                f"host={host}, path={path}"
            )

        retry_after = response.headers.get(
            "Retry-After"
        )

        delay_seconds = calculate_sec_retry_delay(
            attempt_number,
            retry_after,
        )

        sleep(delay_seconds)

    raise RuntimeError(
        "SEC request exhausted retries."
    )

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

secret_scope = (
    dbutils.widgets
    .get("secret_scope")
    .strip()
)

if not secret_scope:
    raise ValueError(
        "secret_scope must be nonblank."
    )

table_name = (
    f"{catalog}."
    f"{bronze_schema}."
    "filing_documents"
)


# COMMAND ----------

equities = load_equities()

if not equities:
    raise RuntimeError(
        "No configured equities were found."
    )

user_agent = dbutils.secrets.get(
    scope=secret_scope,
    key="sec-user-agent",
).strip()


json_headers = build_sec_request_headers(
    user_agent
)

html_headers = build_sec_html_request_headers(
    user_agent
)

ingestion_run_id = str(uuid4())

document_rows: list[
    dict[str, object]
] = []

previous_request_started_at: float | None = None


def wait_for_sec_spacing() -> None:
    """Respect the shared minimum interval between SEC requests."""

    global previous_request_started_at

    if previous_request_started_at is None:
        return

    elapsed_seconds = (
        monotonic()
        - previous_request_started_at
    )

    spacing_delay = calculate_sec_spacing_delay(
        elapsed_seconds
    )

    if spacing_delay > 0:
        sleep(spacing_delay)


for project_symbol, equity in equities.items():
    sec_cik = equity.sec_cik

    # Retrieve submissions metadata used for deterministic 10-K selection.
    submissions_path = build_submissions_path(
        sec_cik
    )

    wait_for_sec_spacing()

    previous_request_started_at = monotonic()

    (
        submissions_status,
        _submissions_headers,
        submissions_bytes,
    ) = _request_sec(
        SEC_DATA_HOST,
        submissions_path,
        json_headers,
    )

    try:
        submissions_text = submissions_bytes.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"{project_symbol}: SEC submissions response "
            "was not valid UTF-8."
        ) from exc

    try:
        submissions_payload = json.loads(
            submissions_text
        )
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"{project_symbol}: SEC submissions response "
            "was not valid JSON."
        ) from exc

    try:
        eligible_filings = (
            parse_recent_10k_filings(
                submissions_payload,
                sec_cik,
            )
        )

        selected = select_latest_10k(
            eligible_filings
        )

        document_path = build_filing_document_path(
            sec_cik,
            selected,
        )
    except ValueError as exc:
        raise RuntimeError(
            f"{project_symbol}: {exc}"
        ) from exc

    # Retrieve exactly the selected primary filing document.
    wait_for_sec_spacing()

    previous_request_started_at = monotonic()

    (
        document_status,
        document_headers,
        document_bytes,
    ) = _request_sec(
        SEC_ARCHIVES_HOST,
        document_path,
        html_headers,
    )

    content_type = (
        document_headers
        .get("content-type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if content_type not in ALLOWED_HTML_CONTENT_TYPES:
        raise RuntimeError(
            f"{project_symbol}: expected an HTML filing "
            f"document, received "
            f"{content_type or 'unknown content type'}."
        )

    if not document_bytes.strip():
        raise RuntimeError(
            f"{project_symbol}: filing document was empty."
        )

    try:
        document_text = document_bytes.decode(
            "utf-8"
        )
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"{project_symbol}: filing document "
            "was not valid UTF-8."
        ) from exc

    fetched_at = datetime.now(
        timezone.utc
    )

    response_sha256 = hashlib.sha256(
        document_bytes
    ).hexdigest()

    source_response_id = str(uuid4())

    source_url = (
        f"https://{SEC_ARCHIVES_HOST}"
        f"{document_path}"
    )

    filing_metadata_json = json.dumps(
        {
            "accessionNumber": (
                selected.accession_number
            ),
            "filingDate": (
                selected.filing_date.isoformat()
            ),
            "reportDate": (
                selected.report_date.isoformat()
            ),
            "form": selected.form,
            "primaryDocument": (
                selected.primary_document
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    request_parameters_json = json.dumps(
        {
            "project_symbol": project_symbol,
            "sec_cik": sec_cik,
            "submissions_path": submissions_path,
            "document_path": document_path,
            "selection_form": "10-K",
            "selection_rule": (
                "greatest_filing_date_unique"
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )

    document_rows.append(
        {
            "source_response_id": (
                source_response_id
            ),
            "source_system": SOURCE_SYSTEM,
            "source_endpoint": SOURCE_ENDPOINT,
            "project_symbol": project_symbol,
            "sec_cik": sec_cik,
            "accession_number": (
                selected.accession_number
            ),
            "filing_form": selected.form,
            "filing_date": selected.filing_date,
            "report_date": selected.report_date,
            "primary_document": (
                selected.primary_document
            ),
            "source_url": source_url,
            "filing_metadata_json": (
                filing_metadata_json
            ),
            "request_parameters_json": (
                request_parameters_json
            ),
            "http_status": document_status,
            "response_payload_html": (
                document_text
            ),
            "response_bytes": len(
                document_bytes
            ),
            "response_sha256": (
                response_sha256
            ),
            "fetched_at": fetched_at,
            "ingestion_run_id": (
                ingestion_run_id
            ),
        }
    )

    if submissions_status != 200:
        raise RuntimeError(
            f"{project_symbol}: unexpected submissions "
            f"HTTP status {submissions_status}."
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
        accession_number STRING NOT NULL,
        filing_form STRING NOT NULL,
        filing_date DATE NOT NULL,
        report_date DATE NOT NULL,
        primary_document STRING NOT NULL,
        source_url STRING NOT NULL,
        filing_metadata_json STRING NOT NULL,
        request_parameters_json STRING NOT NULL,
        http_status INT NOT NULL,
        response_payload_html STRING NOT NULL,
        response_bytes BIGINT NOT NULL,
        response_sha256 STRING NOT NULL,
        fetched_at TIMESTAMP NOT NULL,
        ingestion_run_id STRING NOT NULL
    )
    USING DELTA
    COMMENT 'Selected raw SEC 10-K primary documents with ingestion provenance'
    TBLPROPERTIES (
        'quality' = 'bronze',
        'source_system' = 'sec'
    )
    """
)


# COMMAND ----------

if len(document_rows) != len(equities):
    raise RuntimeError(
        "SEC filing retrieval did not produce exactly "
        "one document per configured equity."
    )

document_df = spark.createDataFrame(
    document_rows
)

document_df.write.mode(
    "append"
).saveAsTable(
    table_name
)


# COMMAND ----------

persisted_rows = spark.sql(
    f"""
    SELECT COUNT(*) AS row_count
    FROM {table_name}
    WHERE ingestion_run_id = '{ingestion_run_id}'
    """
).collect()[0]["row_count"]

expected_rows = len(document_rows)

if persisted_rows != expected_rows:
    raise RuntimeError(
        "Persisted Bronze filing-document row count "
        "does not match the current ingestion run: "
        f"expected={expected_rows}, "
        f"actual={persisted_rows}."
    )

print(
    "Bronze SEC filing-document append verified: "
    f"rows_appended={persisted_rows}, "
    f"ingestion_run_id={ingestion_run_id}"
)

dbutils.notebook.exit(
    "BRONZE_SEC_FILINGS_APPEND=PASSED"
)