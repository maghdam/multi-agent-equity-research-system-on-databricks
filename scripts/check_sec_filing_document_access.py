"""Verify live access to the selected SEC 10-K primary documents.

This is a read-only diagnostic. It uses shared project configuration,
production filing-selection logic, and shared SEC request-policy helpers.
It validates Bronze-level retrieval properties only; it does not extract
filing sections or interpret Inline XBRL content.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from time import monotonic, sleep

import requests
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
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
    build_sec_html_request_headers,
    build_sec_request_headers,
    calculate_sec_spacing_delay,
)


SEC_DATA_BASE_URL = "https://data.sec.gov"
SEC_ARCHIVES_BASE_URL = "https://www.sec.gov"

REQUEST_TIMEOUT_SECONDS = 30

ALLOWED_HTML_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
}


# Reuse private settings without displaying them.
env_path = PROJECT_ROOT / ".env"
config = dotenv_values(
    env_path,
    interpolate=False,
)

user_agent = (
    config.get("SEC_USER_AGENT")
    or ""
).strip()

if not user_agent:
    raise SystemExit(
        "Missing SEC_USER_AGENT. Check your local .env file."
    )

json_headers = build_sec_request_headers(user_agent)
html_headers = build_sec_html_request_headers(user_agent)

equities = load_equities()

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

    # First retrieve the company's current submissions metadata.
    submissions_path = build_submissions_path(sec_cik)

    wait_for_sec_spacing()
    previous_request_started_at = monotonic()

    try:
        submissions_response = requests.get(
            f"{SEC_DATA_BASE_URL}{submissions_path}",
            headers=json_headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise SystemExit(
            f"{project_symbol}: SEC submissions request failed."
        ) from None

    print(
        f"\n{project_symbol} submissions HTTP status:",
        submissions_response.status_code,
    )

    if submissions_response.status_code != 200:
        raise SystemExit(
            f"{project_symbol}: submissions access failed."
        )

    try:
        payload = submissions_response.json()
    except ValueError:
        raise SystemExit(
            f"{project_symbol}: submissions response was not valid JSON."
        ) from None

    try:
        filings = parse_recent_10k_filings(
            payload,
            sec_cik,
        )

        selected = select_latest_10k(
            filings
        )

        document_path = build_filing_document_path(
            sec_cik,
            selected,
        )
    except ValueError as exc:
        raise SystemExit(
            f"{project_symbol}: {exc}"
        ) from None

    # Then retrieve exactly the primary document selected from metadata.
    wait_for_sec_spacing()
    previous_request_started_at = monotonic()

    document_url = (
        f"{SEC_ARCHIVES_BASE_URL}"
        f"{document_path}"
    )

    try:
        document_response = requests.get(
            document_url,
            headers=html_headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise SystemExit(
            f"{project_symbol}: filing-document request failed."
        ) from None

    print(
        f"{project_symbol} document HTTP status:",
        document_response.status_code,
    )

    if document_response.status_code != 200:
        raise SystemExit(
            f"{project_symbol}: filing-document access failed."
        )

    content_type = (
        document_response.headers
        .get("Content-Type", "")
        .split(";", 1)[0]
        .strip()
        .lower()
    )

    if content_type not in ALLOWED_HTML_CONTENT_TYPES:
        raise SystemExit(
            f"{project_symbol}: expected an HTML document, "
            f"received {content_type or 'unknown content type'}."
        )

    response_bytes = document_response.content

    if not response_bytes.strip():
        raise SystemExit(
            f"{project_symbol}: filing document was empty."
        )

    response_sha256 = hashlib.sha256(
        response_bytes
    ).hexdigest()

    print("CIK:", sec_cik)

    print(
        "Selected filing:",
        {
            "accessionNumber": selected.accession_number,
            "filingDate": selected.filing_date.isoformat(),
            "reportDate": selected.report_date.isoformat(),
            "form": selected.form,
            "primaryDocument": selected.primary_document,
        },
    )

    print("Document path:", document_path)
    print("Content type:", content_type)
    print("Response bytes:", len(response_bytes))
    print("SHA-256:", response_sha256)